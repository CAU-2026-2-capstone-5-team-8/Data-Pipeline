"""Tests for the selection audit that reports why a book can support difficulty work."""

import csv
from datetime import UTC, datetime
from pathlib import Path

import pytest

from data_pipeline.models import Book, CanonicalDataset, Document, Source, TocEntry
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
            toc_entry_id=f"toc_{book_id}_{index}",
            book_id=book_id,
            parent_entry_id=None,
            level=1,
            order_index=index,
            label=None,
            title=f"Chapter {index}",
            source_id=f"source_{book_id}",
        )
        for index in range(count)
    ]


def description(book_id: str, text: str) -> Document:
    return Document(
        document_id=f"doc_{book_id}"[:24],
        book_id=book_id,
        document_type="description",
        text=text,
        source_id=f"source_{book_id}",
        content_hash="sha256:" + "0" * 64,
    )


def dataset(books, toc_entries=(), documents=()) -> CanonicalDataset:
    return CanonicalDataset(
        books=list(books),
        documents=list(documents),
        toc=list(toc_entries),
        sources=[
            Source(
                source_id=f"source_{b.book_id}",
                book_id=b.book_id,
                provider="synthetic",
                source_type="metadata_api",
                url="https://example.com/book",
                retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
                content_hash="sha256:" + "0" * 64,
            )
            for b in books
        ],
    )


def status_of(report: dict, book_id: str) -> str:
    return next(item["status"] for item in report["books"] if item["book_id"] == book_id)


def test_toc_presence_does_not_claim_eligibility() -> None:
    target = book("isbn13:9780306406157", "Operating Systems")

    report = audit_selection(dataset([target], toc(target.book_id, 12)))

    assert status_of(report, target.book_id) == "evidence_present"
    assert report["book_count"] == 1


def test_subject_marker_requires_review_even_with_a_toc() -> None:
    """A book from another field supplies confident, wrong concepts."""
    target = book("isbn13:9781849353878", "The Operating System")
    documents = [description(target.book_id, "A study of anarchism as a political philosophy.")]

    report = audit_selection(dataset([target], toc(target.book_id, 14), documents))

    assert status_of(report, target.book_id) == "review_required"
    assert "conflicting_subject_marker" in report["books"][0]["findings"]


def test_book_without_isbn_requires_review_not_unresolvable() -> None:
    target = book("book_a1364d52179f6fca0403", "Operating systems")

    report = audit_selection(dataset([target]))

    assert status_of(report, target.book_id) == "review_required"


def test_study_aid_is_flagged_even_with_a_full_toc() -> None:
    """A Schaum's outline may still carry a usable TOC, so it is reported, not dropped."""
    target = book("isbn13:9780071364355", "Schaum's Outline of Operating Systems")

    report = audit_selection(dataset([target], toc(target.book_id, 50)))

    assert status_of(report, target.book_id) == "review_required"
    assert report["books"][0]["toc_entries"] == 50


def test_title_only_metadata_is_separated_from_a_merely_missing_toc() -> None:
    bare = book("isbn13:9781119800361", "Operating System Concepts")
    described = book("isbn13:9781292025773", "Modern Operating Systems")
    documents = [description(described.book_id, "A textbook about operating systems.")]

    report = audit_selection(dataset([bare, described], (), documents))

    assert status_of(report, bare.book_id) == "metadata_only"
    assert status_of(report, described.book_id) == "evidence_present"


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
    assert rows[0]["audit_status"] == "evidence_present"


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


def test_korean_workbook_subtitle_and_math_parent_topic_are_handled():
    target = book("isbn13:9780306406157", "확률과 통계", subtitle="내신 문제집")
    target = target.model_copy(
        update={"topics": ["mathematics", "probability-statistics"], "language": "ko"}
    )
    report = audit_selection(dataset([target], toc(target.book_id, 3)))
    row = report["books"][0]
    assert row["topic"] == "probability-statistics"
    assert "study_aid_marker" in row["findings"]
    assert "topic_terms_not_observed" not in row["findings"]
    assert row["signals"][0]["field"] == "subtitle"
    assert all(target.subtitle[s["start"] : s["end"]] == s["matched_text"] for s in row["signals"])


def test_assigned_topic_is_not_evidence_and_multiple_leaf_topics_are_retained():
    target = book("isbn13:9780306406157", "Unrelated title")
    target = target.model_copy(update={"topics": ["mathematics", "linear-algebra", "algorithms"]})
    report = audit_selection(dataset([target]))
    assert report["book_count"] == 1 and report["audit_row_count"] == 2
    assert {r["topic"] for r in report["books"]} == {"linear-algebra", "algorithms"}
    assert all("topic_terms_not_observed" in r["findings"] for r in report["books"])


def test_description_marker_records_document_and_source_not_a_subject_verdict():
    target = book("isbn13:9780306406157", "Operating systems")
    document = description(target.book_id, "This contrasts anarchism with operating systems.")
    report = audit_selection(dataset([target], (), [document]))
    row = report["books"][0]
    signal = row["signals"][0]
    assert signal["record_id"] == document.document_id
    assert signal["source_id"] == document.source_id
    assert document.text[signal["start"] : signal["end"]] == "anarchism"
    assert row["status"] == "review_required"
    assert row["evidence_state"] == "description_only"
    assert row["has_prose"] is False
    assert report["sources"][0]["url"] == "https://example.com/book"


def test_generic_outline_and_problem_solving_are_not_workbook_proof():
    target = book("isbn13:9780306406157", "An Outline of Operating Systems: Problem Solving")
    row = audit_selection(dataset([target], toc(target.book_id, 3)))["books"][0]
    assert "study_aid_marker" not in row["findings"]
    assert row["evidence_state"] == "toc_only"
    assert row["status"] == "evidence_present"


def test_invalid_provenance_is_rejected_before_reporting():
    target = book("isbn13:9780306406157", "Operating Systems")
    source = dataset([target], toc(target.book_id, 2))
    source = source.model_copy(update={"sources": []})
    with pytest.raises(ValueError, match="missing source"):
        audit_selection(source)


def test_existing_reports_and_human_judgments_cannot_be_overwritten(tmp_path):
    target = book("isbn13:9780306406157", "Operating Systems")
    report = audit_selection(dataset([target]))
    path = tmp_path / "human.csv"
    path.write_text("a real human judgment\n")
    for writer in (write_selection_report, write_selection_review):
        with pytest.raises(FileExistsError):
            writer(report, path)
        assert path.read_text() == "a real human judgment\n"


def test_multi_topic_audit_is_invariant_to_input_record_order():
    books = [
        book("isbn13:9780306406157", "Operating Systems"),
        book("isbn13:9781119800361", "Operating System Concepts"),
    ]
    original = dataset(
        books, toc(books[0].book_id, 3), [description(books[1].book_id, "Operating systems")]
    )
    shuffled = original.model_copy(
        update={
            "books": list(reversed(original.books)),
            "toc": list(reversed(original.toc)),
            "sources": list(reversed(original.sources)),
        }
    )
    assert audit_selection(original) == audit_selection(shuffled)


def test_cli_preserves_inputs_and_review_sheet_and_pins_hashes(tmp_path):
    import hashlib
    import json

    from typer.testing import CliRunner

    from data_pipeline.cli import app
    from data_pipeline.storage import write_dataset

    target = book("isbn13:9780306406157", "Operating Systems")
    processed = tmp_path / "data" / "processed"
    write_dataset(dataset([target], toc(target.book_id, 2)), processed)
    originals = {p.name: p.read_bytes() for p in processed.iterdir()}
    report, review = tmp_path / "audit.json", tmp_path / "review.csv"
    args = [
        "audit-selection",
        "--data-dir",
        str(processed.parent),
        "--report",
        str(report),
        "--review",
        str(review),
    ]
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 0, result.output
    output = json.loads(report.read_text())
    assert (
        output["canonical_hashes"]["books.jsonl"]
        == "sha256:" + hashlib.sha256(originals["books.jsonl"]).hexdigest()
    )
    review.write_text("keep real human edits")
    assert CliRunner().invoke(app, args).exit_code != 0
    assert review.read_text() == "keep real human edits"
    assert {p.name: p.read_bytes() for p in processed.iterdir()} == originals
    same_path = CliRunner().invoke(
        app,
        [
            "audit-selection",
            "--data-dir",
            str(processed.parent),
            "--report",
            str(tmp_path / "same"),
            "--review",
            str(tmp_path / "same"),
        ],
    )
    assert same_path.exit_code != 0 and not (tmp_path / "same").exists()


def test_alternate_edition_toc_carries_source_evidence_and_requires_review():
    from data_pipeline.models import EvidenceProvenance

    target = book("isbn13:9780306406157", "Operating Systems")
    original = dataset([target], toc(target.book_id, 2))
    provenance = EvidenceProvenance(
        evidence_type="toc",
        tier="same_work_alternate_edition_toc",
        target_title=target.title,
        target_authors=target.authors,
        same_edition=False,
        discovery_method="synthetic-test",
        match_basis=["same work"],
        validation_status="acceptable",
    )
    original.sources[0] = original.sources[0].model_copy(update={"evidence": provenance})
    report = audit_selection(original)
    row = report["books"][0]
    assert "alternate_edition_toc" in row["findings"]
    assert row["toc_source_ids"] == [original.sources[0].source_id]
    assert report["sources"][0]["evidence"]["same_edition"] is False
    assert row["status"] == "review_required"


def test_cli_rolls_back_its_report_if_review_cannot_be_created(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from data_pipeline import cli
    from data_pipeline.storage import write_dataset

    target = book("isbn13:9780306406157", "Operating Systems")
    write_dataset(dataset([target]), tmp_path / "data" / "processed")
    report = tmp_path / "report.json"
    review = tmp_path / "review.csv"

    def reject(*args):
        raise PermissionError("synthetic review write failure")

    monkeypatch.setattr(cli, "write_selection_review", reject)
    result = CliRunner().invoke(
        cli.app,
        [
            "audit-selection",
            "--data-dir",
            str(tmp_path / "data"),
            "--report",
            str(report),
            "--review",
            str(review),
        ],
    )
    assert result.exit_code != 0
    assert not report.exists() and not review.exists()


def test_review_export_escapes_formula_titles_without_altering_canonical_text(tmp_path):
    target = book("isbn13:9780306406157", "=Operating Systems")
    source = dataset([target])
    report = audit_selection(source)
    path = tmp_path / "review.csv"
    write_selection_review(report, path)
    with path.open(newline="") as stream:
        row = next(csv.DictReader(stream))
    assert row["title"] == "'=Operating Systems"
    assert report["books"][0]["title"] == source.books[0].title == "=Operating Systems"
