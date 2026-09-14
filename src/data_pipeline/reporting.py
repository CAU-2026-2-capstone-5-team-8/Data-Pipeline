"""Coverage reporting for the canonical evidence dataset."""

from collections import defaultdict

from data_pipeline.models import CanonicalDataset


def coverage_rows(dataset: CanonicalDataset) -> list[dict[str, int | str]]:
    documents_by_book: dict[str, set[str]] = defaultdict(set)
    for document in dataset.documents:
        documents_by_book[document.book_id].add(document.document_type)
    toc_books = {entry.book_id for entry in dataset.toc}

    rows: list[dict[str, int | str]] = []
    leaf_topics = sorted({book.topics[-1] for book in dataset.books})
    for topic in leaf_topics:
        books = [book for book in dataset.books if book.topics[-1] == topic]
        book_ids = {book.book_id for book in books}
        rows.append(
            {
                "topic": topic,
                "metadata": len(books),
                "toc": len(book_ids & toc_books),
                "description": sum(
                    "description" in documents_by_book[book_id] for book_id in book_ids
                ),
                "preface_or_introduction": sum(
                    bool({"preface", "introduction"} & documents_by_book[book_id])
                    for book_id in book_ids
                ),
                "preview_or_sample": sum(
                    bool({"preview", "sample_chapter"} & documents_by_book[book_id])
                    for book_id in book_ids
                ),
                "other_document": sum(
                    "other" in documents_by_book[book_id] for book_id in book_ids
                ),
            }
        )
    return rows


def format_coverage(dataset: CanonicalDataset) -> str:
    blocks = []
    for row in coverage_rows(dataset):
        blocks.append(
            "\n".join(
                [
                    str(row["topic"]),
                    f"Metadata collected:       {row['metadata']}",
                    f"TOC available:            {row['toc']}",
                    f"Description:              {row['description']}",
                    f"Preface/Introduction:     {row['preface_or_introduction']}",
                    f"Preview/Sample text:      {row['preview_or_sample']}",
                    f"Other document:           {row['other_document']}",
                ]
            )
        )
    return "\n\n".join(blocks) if blocks else "No books collected."
