from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from typer.testing import CliRunner

from data_pipeline.cli import app
from data_pipeline.manifest import (
    MvpManifest,
    RawArtifactSelector,
    load_manifest,
    select_manifest_raw_paths,
    validate_manifest_books,
)
from data_pipeline.models import Book, CanonicalDataset, Source
from data_pipeline.reporting import book_coverage_rows, format_book_coverage
from data_pipeline.storage import RawArtifact, raw_artifact_path, read_dataset, write_raw_response

RETRIEVED_AT = datetime(2026, 9, 15, 12, tzinfo=UTC)
BOOK_ID = "isbn13:9780306406157"


def _dataset() -> CanonicalDataset:
    book = Book(
        book_id=BOOK_ID,
        isbn_10="0306406152",
        isbn_13="9780306406157",
        title="Fixture Operating Systems",
        authors=["Fixture Author"],
        publisher="Fixture Publisher",
        published_year=2026,
        language="en",
        topics=["computer-science", "operating-systems"],
    )
    source = Source(
        source_id="source_fixture",
        book_id=book.book_id,
        provider="fixture",
        source_type="metadata_api",
        url="https://example.test/book",
        retrieved_at=RETRIEVED_AT,
        content_hash="sha256:" + "a" * 64,
    )
    return CanonicalDataset(books=[book], documents=[], toc=[], sources=[source])


def _artifact(
    *,
    provider: str,
    topic: str,
    requested_limit: int,
    retrieved_at: datetime,
    source: str | None = None,
) -> RawArtifact:
    request_parameters = {"title": topic, "limit": requested_limit * 4}
    if source is not None:
        request_parameters = {"source": source}
    return RawArtifact(
        provider=provider,
        topic=topic,
        requested_limit=requested_limit,
        retrieved_at=retrieved_at,
        request_parameters=request_parameters,
        response={"retrieved_at": retrieved_at.isoformat()},
    )


def test_versioned_mvp_manifest_declares_ten_books_and_reviewed_inputs() -> None:
    manifest = load_manifest(Path("configs/mvp.json"))

    assert len(manifest.expected_book_ids) == 10
    assert len(manifest.raw_artifacts) == 12
    assert {selector.topic for selector in manifest.raw_artifacts} == {
        "linear-algebra",
        "operating-systems",
    }


def test_manifest_selects_latest_artifact_for_each_request_identity(tmp_path) -> None:
    older = _artifact(
        provider="open-library",
        topic="operating-systems",
        requested_limit=5,
        retrieved_at=RETRIEVED_AT,
    )
    newer = _artifact(
        provider="open-library",
        topic="operating-systems",
        requested_limit=5,
        retrieved_at=RETRIEVED_AT + timedelta(minutes=1),
    )
    textbook = _artifact(
        provider="open-textbook",
        topic="operating-systems",
        requested_limit=1,
        retrieved_at=RETRIEVED_AT,
        source="ostep-1.10",
    )
    for artifact in (older, newer, textbook):
        write_raw_response(artifact, raw_artifact_path(tmp_path, artifact))
    manifest = MvpManifest(
        raw_artifacts=[
            RawArtifactSelector(
                provider="open-library",
                topic="operating-systems",
                requested_limit=5,
            ),
            RawArtifactSelector(
                provider="open-textbook",
                topic="operating-systems",
                requested_limit=1,
                source="ostep-1.10",
            ),
        ],
        expected_book_ids=[BOOK_ID],
    )

    selected = select_manifest_raw_paths(manifest, tmp_path / "raw")

    assert selected == [raw_artifact_path(tmp_path, newer), raw_artifact_path(tmp_path, textbook)]


def test_manifest_reports_missing_artifact_and_wrong_book_set(tmp_path) -> None:
    manifest = MvpManifest(
        raw_artifacts=[
            RawArtifactSelector(
                provider="open-library",
                topic="linear-algebra",
                requested_limit=5,
            )
        ],
        expected_book_ids=["isbn13:9780131103627"],
    )

    with pytest.raises(ValueError, match="missing raw artifact"):
        select_manifest_raw_paths(manifest, tmp_path / "raw")
    assert validate_manifest_books(manifest, _dataset()) == [
        "manifest books missing from dataset: isbn13:9780131103627",
        f"dataset contains books outside manifest: {BOOK_ID}",
    ]


def test_build_manifest_writes_dataset_and_explicit_missing_evidence(tmp_path, monkeypatch) -> None:
    manifest_path = tmp_path / "mvp.json"
    manifest_path.write_text(
        MvpManifest(
            raw_artifacts=[
                RawArtifactSelector(
                    provider="open-library",
                    topic="operating-systems",
                    requested_limit=5,
                )
            ],
            expected_book_ids=[BOOK_ID],
        ).model_dump_json(),
        encoding="utf-8",
    )
    selected_raw = tmp_path / "raw" / "selected.json"
    monkeypatch.setattr(
        "data_pipeline.cli.select_manifest_raw_paths",
        lambda _manifest, _raw_directory: [selected_raw],
    )
    monkeypatch.setattr(
        "data_pipeline.cli._dataset_from_raw_paths",
        lambda _paths: (_dataset(), {"operating-systems": 5}),
    )

    result = CliRunner().invoke(
        app,
        [
            "build-manifest",
            "--manifest",
            str(manifest_path),
            "--data-dir",
            str(tmp_path),
        ],
    )

    rebuilt = read_dataset(tmp_path / "processed")
    assert result.exit_code == 0
    assert rebuilt.books[0].book_id == BOOK_ID
    assert f"Selected raw artifact: {selected_raw}" in result.output
    assert "Per-book evidence" in result.output
    assert "TOC: no | description: no" in result.output
    assert "Missing: TOC, description, preface/introduction, preview/sample" in result.output


def test_book_coverage_rows_and_format_make_missing_fields_visible() -> None:
    rows = book_coverage_rows(_dataset())

    assert rows == [
        {
            "topic": "operating-systems",
            "book_id": BOOK_ID,
            "title": "Fixture Operating Systems",
            "toc": False,
            "description": False,
            "preface_or_introduction": False,
            "preview_or_sample": False,
        }
    ]
    assert "Missing: TOC, description, preface/introduction, preview/sample" in (
        format_book_coverage(_dataset())
    )
