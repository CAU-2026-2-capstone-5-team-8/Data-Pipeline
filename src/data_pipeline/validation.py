"""Visible cross-record validation for canonical datasets."""

from collections import Counter

from data_pipeline.models import CanonicalDataset


def _duplicates(values: list[str]) -> list[str]:
    return sorted(value for value, count in Counter(values).items() if count > 1)


def validate_dataset(dataset: CanonicalDataset) -> list[str]:
    errors: list[str] = []
    book_ids = {book.book_id for book in dataset.books}
    source_ids = {source.source_id for source in dataset.sources}
    toc_ids = {entry.toc_entry_id for entry in dataset.toc}

    for kind, values in (
        ("book_id", [book.book_id for book in dataset.books]),
        ("source_id", [source.source_id for source in dataset.sources]),
        ("document_id", [document.document_id for document in dataset.documents]),
        ("toc_entry_id", [entry.toc_entry_id for entry in dataset.toc]),
    ):
        for duplicate in _duplicates(values):
            errors.append(f"duplicate {kind}: {duplicate}")

    for kind, values in (
        ("ISBN-13", [book.isbn_13 for book in dataset.books if book.isbn_13]),
        ("ISBN-10", [book.isbn_10 for book in dataset.books if book.isbn_10]),
    ):
        for duplicate in _duplicates(values):
            errors.append(f"duplicate {kind}: {duplicate}")

    for source in dataset.sources:
        if source.book_id not in book_ids:
            errors.append(f"source {source.source_id} references missing book {source.book_id}")
    for document in dataset.documents:
        if document.book_id not in book_ids:
            errors.append(
                f"document {document.document_id} references missing book {document.book_id}"
            )
        if document.source_id not in source_ids:
            errors.append(
                f"document {document.document_id} references missing source {document.source_id}"
            )
    for entry in dataset.toc:
        if entry.book_id not in book_ids:
            errors.append(f"TOC {entry.toc_entry_id} references missing book {entry.book_id}")
        if entry.source_id not in source_ids:
            errors.append(f"TOC {entry.toc_entry_id} references missing source {entry.source_id}")
        if entry.parent_entry_id is not None and entry.parent_entry_id not in toc_ids:
            errors.append(
                f"TOC {entry.toc_entry_id} references missing parent {entry.parent_entry_id}"
            )
    return errors
