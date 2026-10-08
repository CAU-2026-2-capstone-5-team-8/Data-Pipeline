"""Synthetic bibliography records verify contracts, not live metadata coverage."""

from datetime import UTC, datetime

import httpx
import pytest
from tenacity import wait_none

from data_pipeline.collection_scope import (
    collection_scope,
    common_field_scope,
    merge_scope_catalogs,
)
from data_pipeline.collectors.base import InvalidProviderResponse
from data_pipeline.collectors.national_library import NationalLibraryCollector
from data_pipeline.common_fields import resolve_common_field
from data_pipeline.national_library import normalize_national_library_response
from data_pipeline.validation import validate_dataset

NOW = datetime(2026, 10, 8, tzinfo=UTC)


def row(**changes):
    return (
        dict(
            TITLE="미시경제학 입문",
            EA_ISBN="9780306406157",
            AUTHOR="가상 저자",
            PUBLISHER="가상 출판사",
            SUBJECT="미시경제학",
            KDC="320",
            DDC="330",
            PUBLISH_PREDATE="20270101",
            EBOOK_YN="N",
            BOOK_TB_CNT="제1장 수요와 공급<br>1.1 균형 가격<br>제2장 소비자 선택",
            BOOK_INTRODUCTION="<p>경제학의 기초를 다루는 가상 책소개.</p>",
        )
        | changes
    )


def normalize(rows, limit=20, scope=None):
    field = resolve_common_field("미시경제학")
    return normalize_national_library_response(
        {"docs": rows}, scope or common_field_scope(field), field.spec(), NOW, limit
    )


def test_request_and_response_preserve_no_credentials():
    params = NationalLibraryCollector.query_parameters("미시경제학", 999)
    assert params["page_size"] == 30 and params["page_no"] == 1
    assert params["ebook_yn"] == "N" and "cert_key" not in params

    def handle(request):
        assert request.url.params["cert_key"] == "synthetic-secret"
        return httpx.Response(200, json={"docs": [row()], "cert_key": "synthetic-secret"})

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        result = NationalLibraryCollector(client, "synthetic-secret").search_scope(params)
    assert "synthetic-secret" not in str(result) and "cert_key" not in params


def test_http_failure_is_bounded_and_cannot_expose_key():
    attempts = []

    def handle(request):
        attempts.append(request)
        return httpx.Response(429, text="quota")

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        collector = NationalLibraryCollector(client, "synthetic-secret")
        with pytest.raises(httpx.HTTPStatusError) as failure:
            collector.search_scope.retry_with(wait=wait_none())(
                collector, collector.query_parameters("미시경제학")
            )
    assert len(attempts) == 2
    assert "synthetic-secret" not in str(failure.value)
    assert "cert_key" not in str(failure.value.request.url)
    assert "cert_key" not in str(failure.value.response.request.url)


@pytest.mark.parametrize("payload", [{"ERROR_CODE": "011", "docs": []}, {"docs": {}}, {}])
def test_api_error_is_not_a_successful_empty_search(payload):
    with (
        httpx.Client(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
        ) as c,
        pytest.raises(InvalidProviderResponse),
    ):
        NationalLibraryCollector(c, "synthetic-secret").search_scope(
            NationalLibraryCollector.query_parameters("미시경제학")
        )


def test_toc_description_and_classifications_keep_provenance_and_unknowns():
    dataset, audit = normalize([row()])
    assert len(dataset.books) == 1 and len(dataset.toc) == 3
    assert dataset.toc[1].parent_entry_id == dataset.toc[0].toc_entry_id
    assert dataset.documents[0].text == "경제학의 기초를 다루는 가상 책소개."
    assert dataset.books[0].language == "und" and dataset.books[0].published_year is None
    assert audit[0]["KDC"] == "320" and audit[0]["DDC"] == "330"
    assert dataset.sources[0].provider == "national_library"
    assert dataset.documents[0].source_id == dataset.sources[0].source_id
    assert normalize([row()])[0] == dataset and not validate_dataset(dataset)


def test_invalid_isbn_wrong_subject_duplicates_and_limits_are_audited():
    dataset, audit = normalize(
        [
            row(),
            row(),
            row(EA_ISBN="invalid"),
            row(TITLE="소설", SUBJECT="소설"),
            row(EA_ISBN="9780134853987"),
            None,
        ],
        limit=1,
    )
    assert len(dataset.books) == 1
    assert [a["reason"] for a in audit] == [
        "matching_title_or_subject",
        "duplicate_isbn",
        "missing_valid_isbn",
        "no_topic_evidence",
        "normalization_limit",
        "invalid_record",
    ]
    converted, _ = normalize([row(EA_ISBN="0306406152")])
    assert converted.books[0].book_id == dataset.books[0].book_id


def test_missing_retailer_category_evidence_is_not_promoted():
    scope = collection_scope("미시경제학", "국내도서-어린이")
    dataset, audit = normalize([row()], scope=scope)
    assert not dataset.books and audit[0]["reason"] == "category_constraints_unconfirmed"


def test_same_isbn_overlap_enriches_known_language_book_and_quarantines_conflicts():
    library, _ = normalize([row()])
    primary = library.model_copy(
        update={
            "books": [library.books[0].model_copy(update={"language": "ko"})],
            "documents": [],
            "toc": [],
            "sources": [],
        }
    )
    merged, audit = merge_scope_catalogs(primary, library)
    assert len(merged.books) == 1 and merged.books[0].language == "ko"
    assert len(merged.toc) == 3 and not validate_dataset(merged)
    assert audit[0]["reason"] == "exact_isbn_overlap_primary_metadata"
    conflict, _ = normalize([row(TITLE="미시경제학 다른 책")])
    merged, audit = merge_scope_catalogs(primary, conflict)
    assert len(merged.books) == 1 and not merged.toc and not merged.sources
    assert audit[0]["reason"] == "isbn_identity_conflict"
