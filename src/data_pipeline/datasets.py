"""Safe composition of canonical datasets from multiple collection runs."""

from collections.abc import Iterable
from typing import Any

from pydantic import BaseModel

from data_pipeline.models import Book, CanonicalDataset, Source
from data_pipeline.public_book_sources import preferred_public_toc_source_ids


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
        if (
            source.retrieved_at == existing.retrieved_at
            and source.content_hash != existing.content_hash
        ):
            raise DatasetMergeError(
                f"conflicting source snapshot at the same retrieval time: {source.source_id}"
            )
        if source.retrieved_at > existing.retrieved_at:
            merged[source.source_id] = source
    return list(merged.values())


def _records_from_selected_sources[Record: BaseModel](
    datasets: list[CanonicalDataset],
    field: str,
    selected_sources: dict[str, Source],
) -> Iterable[Record]:
    """Yield sourced records only from the canonical snapshot selected for each source."""
    for dataset in datasets:
        local_sources = {source.source_id: source for source in dataset.sources}
        records: Any = getattr(dataset, field)
        for record in records:
            local_source = local_sources.get(record.source_id)
            selected_source = selected_sources.get(record.source_id)
            if local_source is None or selected_source is None or local_source == selected_source:
                yield record


def merge_datasets(datasets: Iterable[CanonicalDataset]) -> CanonicalDataset:
    """Merge datasets and apply explicit reviewed TOC source preferences."""
    items = list(datasets)
    sources = _merge_sources(source for dataset in items for source in dataset.sources)
    sources_by_id = {source.source_id: source for source in sources}
    toc = _merge_records(
        _records_from_selected_sources(items, "toc", sources_by_id), "toc_entry_id"
    )
    preferred_by_book = preferred_public_toc_source_ids()
    active_preferences = {
        book_id: source_id
        for book_id, source_id in preferred_by_book.items()
        if any(entry.book_id == book_id and entry.source_id == source_id for entry in toc)
    }
    selected_toc = [
        entry
        for entry in toc
        if entry.book_id not in active_preferences
        or entry.source_id == active_preferences[entry.book_id]
    ]
    return CanonicalDataset(
        books=_merge_books(book for dataset in items for book in dataset.books),
        documents=_merge_records(
            _records_from_selected_sources(items, "documents", sources_by_id), "document_id"
        ),
        toc=selected_toc,
        sources=sources,
    )


def without_books(dataset: CanonicalDataset, book_ids: set[str]) -> CanonicalDataset:
    """Remove books and every canonical record scoped to them."""
    return CanonicalDataset(
        books=[book for book in dataset.books if book.book_id not in book_ids],
        documents=[document for document in dataset.documents if document.book_id not in book_ids],
        toc=[entry for entry in dataset.toc if entry.book_id not in book_ids],
        sources=[source for source in dataset.sources if source.book_id not in book_ids],
    )
