"""Visible cross-record validation for canonical datasets."""

from collections import Counter

from data_pipeline.models import CanonicalDataset


def _duplicates(values: list[str]) -> list[str]:
    return sorted(value for value, count in Counter(values).items() if count > 1)


def validate_dataset(dataset: CanonicalDataset) -> list[str]:
    errors: list[str] = []
    book_ids = {book.book_id for book in dataset.books}
    sources_by_id = {source.source_id: source for source in dataset.sources}
    toc_by_id = {entry.toc_entry_id: entry for entry in dataset.toc}
    sourced_book_ids = {source.book_id for source in dataset.sources}

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
    for book in dataset.books:
        if book.book_id not in sourced_book_ids:
            errors.append(f"book {book.book_id} has no source")
    for document in dataset.documents:
        if document.book_id not in book_ids:
            errors.append(
                f"document {document.document_id} references missing book {document.book_id}"
            )
        source = sources_by_id.get(document.source_id)
        if source is None:
            errors.append(
                f"document {document.document_id} references missing source {document.source_id}"
            )
        elif source.book_id != document.book_id:
            errors.append(
                f"document {document.document_id} references source {document.source_id} "
                f"owned by different book {source.book_id}"
            )
    for entry in dataset.toc:
        if entry.book_id not in book_ids:
            errors.append(f"TOC {entry.toc_entry_id} references missing book {entry.book_id}")
        source = sources_by_id.get(entry.source_id)
        if source is None:
            errors.append(f"TOC {entry.toc_entry_id} references missing source {entry.source_id}")
        elif source.book_id != entry.book_id:
            errors.append(
                f"TOC {entry.toc_entry_id} references source {entry.source_id} "
                f"owned by different book {source.book_id}"
            )
        if entry.parent_entry_id is not None:
            parent = toc_by_id.get(entry.parent_entry_id)
            if parent is None:
                errors.append(
                    f"TOC {entry.toc_entry_id} references missing parent {entry.parent_entry_id}"
                )
            elif parent.book_id != entry.book_id:
                errors.append(
                    f"TOC {entry.toc_entry_id} references parent {entry.parent_entry_id} "
                    f"owned by different book {parent.book_id}"
                )
            elif entry.level != parent.level + 1:
                errors.append(f"TOC {entry.toc_entry_id} level must be parent level + 1")
        elif entry.level != 1:
            errors.append(f"TOC {entry.toc_entry_id} root level must be 1")

    # Walk parent links iteratively: malformed deep trees must not overflow the stack.
    # Each completed path is visited once, including paths ending in a missing parent.
    checked: set[str] = set()
    for entry_id in toc_by_id:
        path: set[str] = set()
        current: str | None = entry_id
        while current is not None and current in toc_by_id and current not in checked:
            if current in path:
                errors.append(f"TOC parent cycle includes {current}")
                break
            path.add(current)
            current = toc_by_id[current].parent_entry_id
        checked.update(path)
    return errors
