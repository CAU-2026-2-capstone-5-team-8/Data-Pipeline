import csv
from datetime import UTC, datetime
from pathlib import Path

import pytest

from data_pipeline.manifest import MvpManifest, RawArtifactSelector, load_manifest
from data_pipeline.normalizers import normalize_open_library_response
from data_pipeline.scale_reporting import (
    _author_conflicts,
    create_scale_report,
    spreadsheet_safe_csv_value,
    write_scale_artifacts,
)
from data_pipeline.storage import RawArtifact, read_raw_response, write_raw_response

RETRIEVED_AT = datetime(2026, 9, 16, 12, tzinfo=UTC)
BOOK_ID = "isbn13:9780306406157"


def _raw_response() -> dict:
    edition = {
        "key": "/books/OL1M",
        "title": "Fixture Linear Algebra",
        "language": ["eng"],
        "isbn": ["9780306406157", "0306406152"],
        "publisher": ["Fixture Press"],
        "publish_date": ["2007"],
    }
    return {
        "search_response": {
            "docs": [
                {
                    "key": "/works/OL1W",
                    "title": "Fixture Linear Algebra",
                    "author_name": ["Ada Author"],
                    "editions": {"docs": [edition]},
                },
                {
                    "key": "/works/OL2W",
                    "title": "Fixture Linear Algebra duplicate",
                    "author_name": ["Ada Author"],
                    "editions": {"docs": [{**edition, "key": "/books/OL2M"}]},
                },
                {
                    "key": "/works/OL3W",
                    "title": "No English Edition",
                    "author_name": ["Other Author"],
                    "editions": {
                        "docs": [
                            {
                                "key": "/books/OL3M",
                                "title": "No English Edition",
                                "language": ["spa"],
                            }
                        ]
                    },
                },
            ]
        },
        "edition_details": {"/books/OL1M": {"edition_name": "7th edition"}},
        "work_details": {"/works/OL1W": {"description": "Description for the 8th edition."}},
        "collection_failures": [],
    }


def test_versioned_scale_manifest_keeps_exact_fifty_book_identities() -> None:
    scale_manifest = load_manifest(Path("configs/experiments/scale-50.json"))
    mvp_manifest = load_manifest(Path("configs/mvp.json"))

    assert len(scale_manifest.expected_book_ids) == 50
    assert [selector.requested_limit for selector in scale_manifest.raw_artifacts] == [25, 25]
    assert {selector.provider for selector in scale_manifest.raw_artifacts} == {"open-library"}
    assert len(mvp_manifest.expected_book_ids) == 10


def test_scale_report_counts_candidates_failures_and_leaves_human_review_blank(
    tmp_path,
) -> None:
    response = _raw_response()
    artifact = RawArtifact(
        provider="open-library",
        topic="linear-algebra",
        requested_limit=1,
        retrieved_at=RETRIEVED_AT,
        request_parameters={"fixture": True},
        response=response,
    )
    raw_path = tmp_path / "raw.json"
    write_raw_response(artifact, raw_path)
    dataset = normalize_open_library_response(
        response,
        topic="linear-algebra",
        limit=1,
        retrieved_at=RETRIEVED_AT,
    )
    manifest = MvpManifest(
        raw_artifacts=[
            RawArtifactSelector(provider="open-library", topic="linear-algebra", requested_limit=1)
        ],
        expected_book_ids=[BOOK_ID],
    )

    report = create_scale_report(
        manifest=manifest,
        dataset=dataset,
        raw_paths=[raw_path],
        deterministic_rebuild=True,
        build_seconds=0.01,
        canonical_bytes=123,
    )
    report_path, audit_path = write_scale_artifacts(report, dataset, tmp_path / "reports")

    discovery = report["discovery_normalization"]
    assert discovery["candidate_count"] == 3
    assert discovery["duplicate_candidate_count"] == 1
    assert discovery["normalization_failure_count"] == 1
    assert discovery["edition_mismatch_count"] == 1
    assert report["data_integrity"]["offline_rebuild_byte_identical"] is True
    assert report_path.exists()
    with audit_path.open(encoding="utf-8") as stream:
        audit_row = next(csv.DictReader(stream))
    assert audit_row["identity_ok"] == ""
    assert audit_row["topic_relevant"] == ""
    assert (
        audit_row["suspected_identity_or_edition_conflicts"] == "work_description_edition_mismatch"
    )


def test_scale_audit_flags_reordered_duplicate_author_variants() -> None:
    response = _raw_response()
    book = normalize_open_library_response(
        response,
        topic="linear-algebra",
        limit=1,
        retrieved_at=RETRIEVED_AT,
    ).books[0]
    book = book.model_copy(update={"authors": ["William S. Davis", "Davis, William S."]})

    assert _author_conflicts(book) == ["suspected_duplicate_author_variants"]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("=SUM(1, 2)", "'=SUM(1, 2)"),
        ("+something", "'+something"),
        ("-something", "'-something"),
        ("@something", "'@something"),
        ("  =SUM(1, 2)", "'  =SUM(1, 2)"),
        ("Normal title", "Normal title"),
        ("Normal Author", "Normal Author"),
        ("https://example.test/book", "https://example.test/book"),
        ("", ""),
    ],
)
def test_spreadsheet_safe_csv_value_only_neutralizes_formula_like_strings(value, expected) -> None:
    assert spreadsheet_safe_csv_value(value) == expected


def test_scale_audit_sanitizes_external_cells_without_changing_canonical_data(
    tmp_path,
) -> None:
    response = _raw_response()
    artifact = RawArtifact(
        provider="open-library",
        topic="linear-algebra",
        requested_limit=1,
        retrieved_at=RETRIEVED_AT,
        request_parameters={"fixture": True},
        response=response,
    )
    raw_path = tmp_path / "raw.json"
    write_raw_response(artifact, raw_path)
    dataset = normalize_open_library_response(
        response,
        topic="linear-algebra",
        limit=1,
        retrieved_at=RETRIEVED_AT,
    )
    unsafe_book = dataset.books[0].model_copy(
        update={"title": "=SUM(1, 2)", "authors": ["+something", "Normal Author"]}
    )
    unsafe_source = dataset.sources[0].model_copy(update={"url": "  @something"})
    dataset = dataset.model_copy(update={"books": [unsafe_book], "sources": [unsafe_source]})
    manifest = MvpManifest(
        raw_artifacts=[
            RawArtifactSelector(provider="open-library", topic="linear-algebra", requested_limit=1)
        ],
        expected_book_ids=[BOOK_ID],
    )
    report = create_scale_report(
        manifest=manifest,
        dataset=dataset,
        raw_paths=[raw_path],
        deterministic_rebuild=True,
        build_seconds=0.01,
        canonical_bytes=123,
    )

    _, audit_path = write_scale_artifacts(report, dataset, tmp_path / "reports")

    with audit_path.open(encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        audit_row = next(reader)
        assert set(audit_row) == set(reader.fieldnames or [])
    assert audit_row["title"] == "'=SUM(1, 2)"
    assert audit_row["authors"] == "'+something | Normal Author"
    assert audit_row["source_urls"] == "'  @something"
    assert audit_row["identity_ok"] == ""
    assert unsafe_book.title == "=SUM(1, 2)"
    assert read_raw_response(raw_path).response == response
