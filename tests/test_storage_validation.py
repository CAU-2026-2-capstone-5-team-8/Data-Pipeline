from datetime import UTC, datetime

import pytest

from data_pipeline.models import Book, CanonicalDataset, Document, Source, TocEntry
from data_pipeline.storage import (
    RawArtifact,
    raw_artifact_path,
    read_dataset,
    read_raw_response,
    write_dataset,
    write_raw_response,
)
from data_pipeline.validation import validate_dataset


def make_dataset() -> CanonicalDataset:
    book = Book(
        book_id="isbn13:9780306406157",
        isbn_10="0306406152",
        isbn_13="9780306406157",
        title="Fixture Book",
        subtitle=None,
        authors=["Fixture Author"],
        publisher=None,
        published_year=2025,
        language="en",
        topics=["computer-science", "operating-systems"],
    )
    source = Source(
        source_id="source_fixture",
        book_id=book.book_id,
        provider="fixture",
        source_type="metadata_api",
        url="https://example.test/book",
        retrieved_at=datetime(2026, 9, 12, tzinfo=UTC),
        content_hash="sha256:" + "a" * 64,
    )
    document = Document(
        document_id="doc_fixture",
        book_id=book.book_id,
        document_type="description",
        text="Evidence text",
        source_id=source.source_id,
        content_hash="sha256:" + "b" * 64,
    )
    toc = TocEntry(
        toc_entry_id="toc_fixture",
        book_id=book.book_id,
        parent_entry_id=None,
        level=1,
        order_index=0,
        label="1",
        title="Vectors",
        source_id=source.source_id,
    )
    return CanonicalDataset(books=[book], documents=[document], toc=[toc], sources=[source])


def test_jsonl_round_trip_writes_all_four_files(tmp_path) -> None:
    dataset = make_dataset()

    write_dataset(dataset, tmp_path)
    loaded = read_dataset(tmp_path)

    assert loaded == dataset
    assert sorted(path.name for path in tmp_path.iterdir()) == [
        "books.jsonl",
        "documents.jsonl",
        "sources.jsonl",
        "toc.jsonl",
    ]
    assert validate_dataset(loaded) == []


def test_validation_reports_broken_toc_parent_and_source_relationship() -> None:
    dataset = make_dataset()
    dataset.toc[0].parent_entry_id = "toc_missing"
    dataset.documents[0].source_id = "source_missing"

    errors = validate_dataset(dataset)

    assert "document doc_fixture references missing source source_missing" in errors
    assert "TOC toc_fixture references missing parent toc_missing" in errors


def test_validation_requires_a_source_for_every_book() -> None:
    dataset = make_dataset()
    dataset.sources = []

    errors = validate_dataset(dataset)

    assert f"book {dataset.books[0].book_id} has no source" in errors


def test_validation_rejects_cross_book_source_and_toc_parent_relationships() -> None:
    dataset = make_dataset()
    other_book = dataset.books[0].model_copy(
        update={
            "book_id": "isbn13:9780471694663",
            "isbn_10": "0471694665",
            "isbn_13": "9780471694663",
            "title": "Other Book",
        }
    )
    other_source = dataset.sources[0].model_copy(
        update={"source_id": "source_other", "book_id": other_book.book_id}
    )
    other_toc = dataset.toc[0].model_copy(
        update={
            "toc_entry_id": "toc_other",
            "book_id": other_book.book_id,
            "source_id": other_source.source_id,
        }
    )
    dataset.books.append(other_book)
    dataset.sources.append(other_source)
    dataset.toc.append(other_toc)
    dataset.documents[0].source_id = other_source.source_id
    dataset.toc[0].source_id = other_source.source_id
    dataset.toc[0].parent_entry_id = other_toc.toc_entry_id

    errors = validate_dataset(dataset)

    assert any("document doc_fixture" in error and "different book" in error for error in errors)
    assert any("TOC toc_fixture references source" in error for error in errors)
    assert any("TOC toc_fixture references parent" in error for error in errors)


def test_raw_artifact_preserves_response_and_retrieval_time(tmp_path) -> None:
    path = tmp_path / "response.json"
    artifact = RawArtifact(
        provider="open-library",
        topic="operating-systems",
        requested_limit=5,
        retrieved_at=datetime(2026, 9, 12, 12, 34, tzinfo=UTC),
        request_parameters={"title": "operating systems", "limit": 20},
        response={"docs": [{"key": "/works/example"}]},
    )

    write_raw_response(artifact, path)

    assert read_raw_response(path) == artifact


def test_raw_artifact_path_is_topic_scoped_and_cannot_be_overwritten(tmp_path) -> None:
    artifact = RawArtifact(
        provider="open-library",
        topic="operating-systems",
        requested_limit=5,
        retrieved_at=datetime(2026, 9, 12, 12, 34, tzinfo=UTC),
        request_parameters={"title": "operating systems", "limit": 20},
        response={"docs": []},
    )
    path = raw_artifact_path(tmp_path, artifact)

    write_raw_response(artifact, path)

    assert path.parent.name == "operating-systems"
    with pytest.raises(FileExistsError):
        write_raw_response(artifact, path)


def test_raw_artifact_rejects_tampered_response(tmp_path) -> None:
    path = tmp_path / "response.json"
    artifact = RawArtifact(
        provider="open-library",
        topic="operating-systems",
        requested_limit=5,
        retrieved_at=datetime(2026, 9, 12, 12, 34, tzinfo=UTC),
        request_parameters={"title": "operating systems", "limit": 20},
        response={"docs": []},
    )
    write_raw_response(artifact, path)
    original = path.read_text(encoding="utf-8")
    tampered = original.replace('"docs": []', '"docs": [{"tampered": true}]')
    path.write_text(tampered, encoding="utf-8")

    with pytest.raises(ValueError, match="content hash mismatch"):
        read_raw_response(path)
