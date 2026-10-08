from datetime import UTC, datetime

import pytest

from data_pipeline.collection_scope import (
    collection_scope,
    merge_scope_catalogs,
    normalize_scope_response,
    open_library_parameters,
)
from data_pipeline.models import CanonicalDataset
from data_pipeline.normalizers import normalize_yes24_response
from data_pipeline.query_discovery import discovery_policy
from data_pipeline.validation import validate_dataset

NOW = datetime(2026, 10, 6, tzinfo=UTC)
CATEGORY = "국내도서-경제 경영"


def record(title="Economics", subjects=None, isbn="9780306406157", language="eng"):
    return {
        "key": "/works/OL1W",
        "title": title,
        "author_name": ["Author"],
        "subject": ["Economics"] if subjects is None else subjects,
        "editions": {
            "docs": [{"key": "/books/OL1M", "title": title, "isbn": [isbn], "language": [language]}]
        },
    }


def normalize(rows, category=CATEGORY):
    scope = collection_scope("경제", category)
    spec = discovery_policy("경제", category)
    return normalize_scope_response({"docs": rows}, scope, spec, NOW)


def test_scope_separates_subject_type_audience_and_keeps_original_category():
    scope = collection_scope("경제", "국내도서-대학교재")
    assert scope.subject == "economics"
    assert scope.english_query == "economics"
    assert scope.book_kind == "textbook"
    assert scope.audience is None
    assert scope.source_category == "국내도서-대학교재"
    assert "subject:textbooks" in open_library_parameters(scope)["q"]
    assert collection_scope("경제", "국내도서-어린이").audience == "children"
    assert collection_scope("  경제학 ", CATEGORY).subject == scope.subject
    assert collection_scope("선형대수", "국내도서-자연과학").mapping_basis == "reviewed_topic"


def test_unmapped_names_or_specific_categories_do_not_silently_widen_scope():
    assert collection_scope("새로운한글분야", CATEGORY).foreign_status == "unmapped_language"
    for category in ["국내도서-대학교재-의약학", "국내도서-수험서 자격증"]:
        scope = collection_scope("경제", category)
        assert scope.foreign_status == "unmapped_category"
        with pytest.raises(ValueError):
            open_library_parameters(scope)
    assert collection_scope("economics", CATEGORY).mapping_basis == "reviewed_alias"
    scope = collection_scope("new topic", CATEGORY)
    assert scope.mapping_basis == "literal_english"
    assert 'title:"new topic"' in open_library_parameters(scope)["q"]
    assert collection_scope("foo OR *:*", CATEGORY).foreign_status != "ready"


def test_foreign_metadata_requires_subject_or_selected_title_and_valid_english_isbn():
    rows = [
        record(),
        record("Unrelated", ["Novels"]),
        record("Economics", [], "not-an-isbn"),
        record(language="fre"),
    ]
    dataset, audit = normalize(rows)
    assert len(dataset.books) == 1
    assert [a["reason"] for a in audit] == [
        "matching_subject",
        "no_subject_evidence",
        "missing_valid_isbn",
        "no_english_edition",
    ]
    assert dataset.books[0].language == "en"
    assert dataset.sources[0].provider == "open_library"
    assert not validate_dataset(dataset)
    assert normalize(rows)[0].model_dump() == dataset.model_dump()
    weak, decisions = normalize([record(subjects=["Textbooks"])], "국내도서-대학교재")
    assert len(weak.books) == 1 and decisions[0]["reason"] == "title_only_unverified"


def test_constrained_scope_requires_evidence_and_rejects_conflicting_books():
    dataset, decisions = normalize(
        [record(), record(subjects=["Economics", "Textbooks"])], "국내도서-대학교재"
    )
    assert len(dataset.books) == 1
    assert decisions[0]["reason"] == "book_kind_unconfirmed"
    assert decisions[1]["included"]
    dataset, decisions = normalize([record(subjects=["Economics", "Juvenile literature"])])
    assert not dataset.books and decisions[0]["reason"] == "conflicting_audience"
    dataset, decisions = normalize(
        [record(), record(subjects=["Economics", "Juvenile literature"])], "국내도서-어린이"
    )
    assert len(dataset.books) == 1 and decisions[0]["reason"] == "audience_unconfirmed"
    dataset, decisions = normalize([record(subjects=["Economics", "Fiction"])])
    assert not dataset.books and decisions[0]["reason"] == "conflicting_book_kind"


def test_exact_isbn_overlap_preserves_provenance_and_conflicts_are_quarantined():
    foreign, _ = normalize([record()])
    primary = foreign.model_copy(
        update={"books": [foreign.books[0].model_copy(update={"publisher": "Primary"})]}
    )
    merged, audit = merge_scope_catalogs(primary, foreign)
    assert len(merged.books) == 1 and merged.books[0].publisher == "Primary"
    assert audit[0]["reason"] == "exact_isbn_overlap_primary_metadata"
    conflict = foreign.model_copy(
        update={"books": [foreign.books[0].model_copy(update={"language": "ko"})]}
    )
    merged, audit = merge_scope_catalogs(primary, conflict)
    assert merged.books[0].publisher == "Primary"
    assert merged.books[0].language == "en" and len(merged.books) == 1
    assert audit[0]["reason"] == "isbn_identity_conflict"
    standalone = merge_scope_catalogs(
        CanonicalDataset(books=[], documents=[], toc=[], sources=[]), foreign
    )[0]
    assert standalone.books[0].book_id == foreign.books[0].book_id
    assert standalone.sources == foreign.sources and not validate_dataset(standalone)


def test_foreign_dataset_can_merge_domestic_book_with_separate_translation_isbn():
    policy = discovery_policy("경제", CATEGORY)
    domestic = normalize_yes24_response(
        {
            "data": {
                "items": [
                    {
                        "itemId": 1,
                        "title": "경제학 입문",
                        "isbn13": "9780134853987",
                        "author": "저자",
                        "goodsSortNm": CATEGORY,
                    }
                ]
            }
        },
        topic=policy.slug,
        limit=20,
        retrieved_at=NOW,
        discovery_spec=policy,
    )
    foreign, _ = normalize([record()])
    merged, audit = merge_scope_catalogs(domestic, foreign)
    assert len(merged.books) == 2 and not audit and not validate_dataset(merged)
    assert {s.provider for s in merged.sources} == {"yes24", "open_library"}


def test_dynamic_normalizer_cannot_replace_a_curated_topic():
    from data_pipeline.normalizers import normalize_open_library_response

    policy = discovery_policy("경제", CATEGORY).model_copy(update={"slug": "linear-algebra"})
    with pytest.raises(ValueError, match="override"):
        normalize_open_library_response(
            {"docs": []}, topic=policy.slug, limit=20, retrieved_at=NOW, discovery_spec=policy
        )


def test_isbn10_equivalent_deduplicates_and_missing_category_is_audited():
    old_isbn, _ = normalize([record(isbn="0306406152")])
    other_record = record(isbn="9780306406157")
    other_record["editions"]["docs"][0]["key"] = "/books/OL2M"
    modern_isbn, _ = normalize([other_record])
    assert old_isbn.books[0].book_id == modern_isbn.books[0].book_id
    merged, audit = merge_scope_catalogs(modern_isbn, old_isbn)
    assert len(merged.books) == 1 and len(merged.sources) == 2
    assert audit[0]["reason"] == "exact_isbn_overlap_primary_metadata"
    unknown, audit = normalize([record(subjects=[])])
    assert not unknown.books and audit[0]["reason"] == "category_subject_unconfirmed"
