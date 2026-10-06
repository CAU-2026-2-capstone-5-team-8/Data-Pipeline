from datetime import UTC, datetime

import httpx
import pytest
from tenacity import wait_none

from data_pipeline.collection_scope import (
    collection_scope,
    google_books_parameters,
    merge_scope_catalogs,
    normalize_google_scope_response,
    normalize_scope_response,
)
from data_pipeline.collectors.google_books import GoogleBooksCollector
from data_pipeline.normalizers import normalize_google_books_response
from data_pipeline.query_discovery import discovery_policy
from data_pipeline.validation import validate_dataset

NOW = datetime(2026, 10, 6, tzinfo=UTC)
CATEGORY = "국내도서-경제 경영"


def item(identifier="g1", title="Economics", categories=None, isbn="9780306406157", language="en"):
    return {
        "id": identifier,
        "volumeInfo": {
            "title": title,
            "authors": ["Author"],
            "language": language,
            "categories": ["Business & Economics"] if categories is None else categories,
            "industryIdentifiers": [
                {"type": "ISBN_10" if len(isbn) == 10 else "ISBN_13", "identifier": isbn}
            ],
            "description": "A public bibliographic description.",
        },
    }


def normalize(rows, category=CATEGORY, limit=20):
    return normalize_google_scope_response(
        {"items": rows},
        collection_scope("경제", category),
        discovery_policy("경제", category),
        NOW,
        limit,
    )


def test_google_uses_native_query_grammar_and_never_persists_credentials():
    scope = collection_scope("경제", CATEGORY)
    params = google_books_parameters(scope, limit=999)
    assert params["q"] == 'subject:"economics"'
    assert params["maxResults"] == 30 and params["langRestrict"] == "en"
    assert "AND" not in params["q"] and "language:" not in params["q"]
    seen = []

    def handler(request):
        seen.append(request)
        assert request.url.params["key"] == "synthetic-key"
        return httpx.Response(200, json={"items": [item()]})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = GoogleBooksCollector(client=client, api_key="synthetic-key").search_scope(params)
    assert "key" not in params and "synthetic-key" not in str(result)
    assert len(seen) == 1
    with pytest.raises(ValueError):
        google_books_parameters(collection_scope("새한글분야", CATEGORY))


def test_google_scope_preserves_provenance_and_audits_nonmatches():
    rows = [
        item(),
        item("g2", "A Novel", ["Fiction"]),
        item("g3", isbn="invalid"),
        item("g4", language="fr"),
        item("g5", categories=[]),
    ]
    dataset, audit = normalize(rows)
    assert len(dataset.books) == 1 and len(dataset.documents) == 1
    assert [a["reason"] for a in audit] == [
        "matching_subject",
        "no_subject_evidence",
        "missing_valid_isbn",
        "no_english_edition",
        "category_subject_unconfirmed",
    ]
    assert dataset.sources[0].provider == "google_books"
    assert dataset.documents[0].source_id == dataset.sources[0].source_id
    assert not validate_dataset(dataset)
    assert normalize(rows)[0].model_dump() == dataset.model_dump()


def test_google_scope_does_not_invent_textbook_or_audience_metadata():
    dataset, audit = normalize(
        [item(), item("g2", categories=["Business & Economics", "Textbooks"])], "국내도서-대학교재"
    )
    assert len(dataset.books) == 1 and audit[0]["reason"] == "book_kind_unconfirmed"
    dataset, audit = normalize([item(categories=["Juvenile Nonfiction / Business & Economics"])])
    assert not dataset.books and audit[0]["reason"] == "conflicting_audience"
    dataset, audit = normalize(
        [item(categories=["Juvenile Nonfiction / Business & Economics"])], "국내도서-어린이"
    )
    assert len(dataset.books) == 1 and audit[0]["included"]
    dataset, audit = normalize([item(categories=["Business & Economics", "Fiction"])])
    assert not dataset.books and audit[0]["reason"] == "conflicting_book_kind"


def test_two_foreign_providers_share_an_isbn_and_retain_both_sources():
    scope = collection_scope("경제", CATEGORY)
    policy = discovery_policy("경제", CATEGORY)
    ol = {
        "docs": [
            {
                "key": "/works/OL1W",
                "title": "Economics",
                "author_name": ["Author"],
                "subject": ["Economics"],
                "editions": {
                    "docs": [
                        {
                            "key": "/books/OL1M",
                            "title": "Economics",
                            "language": ["eng"],
                            "isbn": ["9780306406157"],
                        }
                    ]
                },
            }
        ]
    }
    original, _ = normalize_scope_response(ol, scope, policy, NOW)
    google, _ = normalize([item(isbn="0306406152")])
    combined, audit = merge_scope_catalogs(original, google)
    assert len(combined.books) == 1 and len(combined.sources) == 2
    assert len(combined.documents) == 1 and not validate_dataset(combined)
    assert audit[0]["reason"] == "exact_isbn_overlap_primary_metadata"


def test_missing_fields_duplicates_and_limits_stay_explicit():
    rows = [
        None,
        {"id": "bad", "volumeInfo": None},
        item(),
        item("dupe"),
        item("other", isbn="9780134853987"),
    ]
    dataset, audit = normalize(rows, limit=1)
    assert len(dataset.books) == 1
    assert not audit[0]["included"] and not audit[1]["included"]
    assert audit[3]["reason"] == "normalization_or_limit"
    assert audit[4]["reason"] == "normalization_or_limit"
    assert not validate_dataset(dataset)
    with pytest.raises(Exception, match="invalid"):
        normalize_google_scope_response(
            {"items": {}},
            collection_scope("경제", CATEGORY),
            discovery_policy("경제", CATEGORY),
            NOW,
        )


def test_google_dynamic_scope_cannot_replace_curated_policy():
    policy = discovery_policy("경제", CATEGORY).model_copy(update={"slug": "linear-algebra"})
    with pytest.raises(ValueError, match="override"):
        normalize_google_books_response(
            {"items": []}, topic=policy.slug, limit=20, retrieved_at=NOW, discovery_spec=policy
        )


def test_quota_retry_is_bounded_and_403_is_not_retried(monkeypatch):
    monkeypatch.setattr(GoogleBooksCollector.search_scope.retry, "wait", wait_none())
    for code, expected in [(429, 3), (403, 1)]:
        seen = []

        def handler(request, status=code, requests=seen):
            requests.append(request)
            return httpx.Response(status, json={"error": {"code": status}})

        with (
            httpx.Client(transport=httpx.MockTransport(handler)) as client,
            pytest.raises(httpx.HTTPStatusError),
        ):
            GoogleBooksCollector(client=client).search_scope({"q": 'subject:"economics"'})
        assert len(seen) == expected
