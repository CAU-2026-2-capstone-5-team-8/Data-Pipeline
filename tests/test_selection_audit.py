"""Tests for the selection audit that reports why a book can support difficulty work."""

import csv
from pathlib import Path

import pytest

from data_pipeline.models import Book, CanonicalDataset, Document, TocEntry
from data_pipeline.selection_audit import (
    audit_selection,
    write_selection_report,
    write_selection_review,
)


def book(book_id: str, title: str, *, isbn_13: str | None = "", **kwargs) -> Book:
    """Build a canonical Book whose ISBN-13 stays consistent with its book_id."""
    if isbn_13 == "":
        isbn_13 = book_id.removeprefix("isbn13:") if book_id.startswith("isbn13:") else None
    return Book(
        book_id=book_id,
        isbn_10=kwargs.pop("isbn_10", None),
        isbn_13=isbn_13,
        title=title,
        subtitle=kwargs.pop("subtitle", None),
        authors=kwargs.pop("authors", ["Author"]),
        publisher=None,
        published_year=2020,
        language="en",
        topics=["computer-science", "operating-systems"],
    )


def toc(book_id: str, count: int) -> list[TocEntry]:
    return [
        TocEntry(
            toc_entry_id=f"toc_{book_id}_{index:016x}"[:24],
            book_id=book_id,
            parent_entry_id=None,
            level=1,
            order_index=index,
            label=None,
            title=f"Chapter {index}",
            source_id="source_0000000000000000000",
        )
        for index in range(count)
    ]


def description(book_id: str, text: str) -> Document:
    return Document(
        document_id=f"doc_{book_id}"[:24],
        book_id=book_id,
        document_type="description",
        text=text,
        source_id="source_0000000000000000000",
        content_hash="sha256:" + "0" * 64,
    )


def dataset(books, toc_entries=(), documents=()) -> CanonicalDataset:
    return CanonicalDataset(
        books=list(books), documents=list(documents), toc=list(toc_entries), sources=[]
    )


def status_of(report: dict, book_id: str) -> str:
    return next(item["status"] for item in report["books"] if item["book_id"] == book_id)


def test_book_with_a_table_of_contents_is_usable() -> None:
    target = book("isbn13:9780306406157", "Operating Systems")

    report = audit_selection(dataset([target], toc(target.book_id, 12)))

    assert status_of(report, target.book_id) == "usable"
    assert report["book_count"] == 1


def test_wrong_subject_outranks_having_a_table_of_contents() -> None:
    """A book from another field supplies confident, wrong concepts."""
    target = book("isbn13:9781849353878", "The Operating System")
    documents = [description(target.book_id, "A study of anarchism as a political philosophy.")]

    report = audit_selection(dataset([target], toc(target.book_id, 14), documents))

    assert status_of(report, target.book_id) == "wrong_subject"
    assert "conflicting_subject" in report["books"][0]["findings"]


def test_book_without_any_identifier_is_unresolvable() -> None:
    target = book("book_a1364d52179f6fca0403", "Operating systems")

    report = audit_selection(dataset([target]))

    assert status_of(report, target.book_id) == "unresolvable"


def test_study_aid_is_flagged_even_with_a_full_toc() -> None:
    """A Schaum's outline may still carry a usable TOC, so it is reported, not dropped."""
    target = book("isbn13:9780071364355", "Schaum's Outline of Operating Systems")

    report = audit_selection(dataset([target], toc(target.book_id, 50)))

    assert status_of(report, target.book_id) == "study_aid"
    assert report["books"][0]["toc_entries"] == 50


def test_title_only_metadata_is_separated_from_a_merely_missing_toc() -> None:
    bare = book("isbn13:9781119800361", "Operating System Concepts")
    described = book("isbn13:9781292025773", "Modern Operating Systems")
    documents = [description(described.book_id, "A textbook about operating systems.")]

    report = audit_selection(dataset([bare, described], (), documents))

    assert status_of(report, bare.book_id) == "no_usable_evidence"
    assert status_of(report, described.book_id) == "toc_missing"


def test_missing_prose_is_reported_for_every_book() -> None:
    """The text difficulty profile needs prose, which TOC-only evidence cannot supply."""
    target = book("isbn13:9780306406157", "Operating Systems")

    report = audit_selection(dataset([target], toc(target.book_id, 12)))

    assert "no_prose" in report["books"][0]["findings"]


def test_audit_reports_without_removing_any_book() -> None:
    books = [
        book("isbn13:9780306406157", "Operating Systems"),
        book("book_a1364d52179f6fca0403", "Operating systems"),
    ]
    source = dataset(books)

    report = audit_selection(source)

    assert report["book_count"] == len(source.books) == 2
    assert {item["book_id"] for item in report["books"]} == {item.book_id for item in books}


def test_review_sheet_leaves_every_human_decision_blank(tmp_path: Path) -> None:
    target = book("isbn13:9780306406157", "Operating Systems")
    report = audit_selection(dataset([target], toc(target.book_id, 12)))
    review_path = tmp_path / "review.csv"

    write_selection_review(report, review_path)

    with review_path.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 1
    assert rows[0]["human_decision"] == ""
    assert rows[0]["replacement_isbn_13"] == ""
    assert rows[0]["audit_status"] == "usable"


def test_report_is_deterministic(tmp_path: Path) -> None:
    books = [
        book("isbn13:9780306406157", "Operating Systems"),
        book("isbn13:9781119800361", "Operating System Concepts"),
    ]
    source = dataset(books, toc(books[0].book_id, 4))

    first, second = tmp_path / "a.json", tmp_path / "b.json"
    write_selection_report(audit_selection(source), first)
    write_selection_report(audit_selection(source), second)

    assert first.read_bytes() == second.read_bytes()


def test_book_without_a_topic_fails_loudly() -> None:
    target = book("isbn13:9780306406157", "Operating Systems")
    target = target.model_copy(update={"topics": ["computer-science"]})

    with pytest.raises(ValueError, match="no usable topic"):
        audit_selection(dataset([target]))
