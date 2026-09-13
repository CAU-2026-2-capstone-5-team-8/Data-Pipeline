"""Safe composition of canonical datasets from multiple collection runs."""

from collections.abc import Iterable

from pydantic import BaseModel

from data_pipeline.models import Book, CanonicalDataset, Source


class DatasetMergeError(ValueError):
    """Raised when records with the same deterministic ID disagree."""


def _merge_records[Record: BaseModel](records: Iterable[Record], id_field: str) -> list[Record]:
    merged: dict[str, Record] = {}
    for record in records:
        record_id = str(getattr(record, id_field))
        existing = merged.get(record_id)
        if existing is None:
            merged[record_id] = record
        elif existing != record:
            raise DatasetMergeError(f"conflicting {id_field}: {record_id}")
    return list(merged.values())


def _merge_books(books: Iterable[Book]) -> list[Book]:
    merged: dict[str, Book] = {}
    for book in books:
        existing = merged.get(book.book_id)
        if existing is None:
            merged[book.book_id] = book
            continue
        existing_without_topics = existing.model_dump(exclude={"topics"})
        incoming_without_topics = book.model_dump(exclude={"topics"})
        if existing_without_topics != incoming_without_topics:
            raise DatasetMergeError(f"conflicting book_id: {book.book_id}")
        topics = list(dict.fromkeys([*existing.topics, *book.topics]))
        merged[book.book_id] = existing.model_copy(update={"topics": topics})
    return list(merged.values())


def _merge_sources(sources: Iterable[Source]) -> list[Source]:
    """Collapse repeated URL snapshots while retaining the latest raw provenance."""
    merged: dict[str, Source] = {}
    for source in sources:
        existing = merged.get(source.source_id)
        if existing is None:
            merged[source.source_id] = source
            continue
        mutable_snapshot_fields = {"retrieved_at", "content_hash"}
        existing_identity = existing.model_dump(exclude=mutable_snapshot_fields)
        incoming_identity = source.model_dump(exclude=mutable_snapshot_fields)
        if existing_identity != incoming_identity:
            raise DatasetMergeError(f"conflicting source_id: {source.source_id}")
        if source.retrieved_at > existing.retrieved_at:
            merged[source.source_id] = source
    return list(merged.values())


def merge_datasets(datasets: Iterable[CanonicalDataset]) -> CanonicalDataset:
    """Merge datasets without silently resolving conflicting deterministic IDs."""
    items = list(datasets)
    return CanonicalDataset(
        books=_merge_books(book for dataset in items for book in dataset.books),
        documents=_merge_records(
            (document for dataset in items for document in dataset.documents), "document_id"
        ),
        toc=_merge_records((entry for dataset in items for entry in dataset.toc), "toc_entry_id"),
        sources=_merge_sources(source for dataset in items for source in dataset.sources),
    )
