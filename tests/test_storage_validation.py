from datetime import UTC, datetime

from data_pipeline.models import Book, CanonicalDataset, Document, Source, TocEntry
from data_pipeline.storage import (
    RawArtifact,
    read_dataset,
    read_raw_response,
    write_dataset,
    write_raw_response,
)
from data_pipeline.validation import validate_dataset


def make_dataset() -> CanonicalDataset:
    book = Book(
        book_id="isbn13:9780123456789",
        isbn_10=None,
        isbn_13="9780123456789",
        title="Fixture Book",
        subtitle=None,
        authors=["Fixture Author"],
        publisher=None,
        published_year=2025,
        language="en",
        topics=["mathematics", "linear-algebra"],
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


def test_raw_artifact_preserves_response_and_retrieval_time(tmp_path) -> None:
    path = tmp_path / "response.json"
    artifact = RawArtifact(
        provider="open-library",
        retrieved_at=datetime(2026, 9, 12, 12, 34, tzinfo=UTC),
        response={"docs": [{"key": "/works/example"}]},
    )

    write_raw_response(artifact, path)

    assert read_raw_response(path) == artifact
