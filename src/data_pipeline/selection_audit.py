"""Classify why each selected book can or cannot support concept difficulty work.

The audit only reports machine-checkable facts and never removes a book. Dropping a
title from a benchmark is a human decision, so the command emits a report plus a blank
review sheet, mirroring the existing relevance-review workflow.
"""

import csv
import json
import re
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

from data_pipeline.models import CanonicalDataset
from data_pipeline.scale_reporting import spreadsheet_safe_csv_value
from data_pipeline.topics import topic_conflicting_subjects_pattern, topic_relevance_pattern

SCHEMA_VERSION = 1

# Reviewed title markers for books that accompany a course rather than teach it.
# A study aid is reported, never auto-dropped: some carry a usable concept TOC.
STUDY_AID_PATTERN = re.compile(
    r"\b(?:solutions?\s+manual|study\s+guide|solved\s+problems?|schaum'?s\s+outline"
    r"|outline\s+of|workbook|exam\s+prep|test\s+bank|problem\s+book)\b",
    re.IGNORECASE,
)

PROSE_DOCUMENT_TYPES = frozenset({"preface", "introduction", "preview", "sample_chapter"})

REVIEW_FIELDS = (
    "book_id",
    "topic",
    "title",
    "authors",
    "published_year",
    "isbn_13",
    "toc_entries",
    "has_description",
    "has_prose",
    "findings",
    "audit_status",
    "human_decision",
    "replacement_isbn_13",
    "notes",
)


@dataclass(frozen=True)
class BookAudit:
    """One book's machine-checkable selection facts."""

    book_id: str
    topic: str
    title: str
    authors: list[str]
    published_year: int | None
    isbn_13: str | None
    toc_entries: int
    has_description: bool
    has_prose: bool
    findings: list[str]
    status: str


def _findings(
    book,
    topic: str,
    toc_entries: int,
    has_description: bool,
    has_prose: bool,
    description_text: str,
):
    """Return every objective reason this book may not belong in the benchmark."""
    findings: list[str] = []
    if not book.isbn_13 and not book.isbn_10:
        # Without an identifier no provider can resolve an exact edition.
        findings.append("no_identifier")

    # A conflicting subject usually shows up in the collected description rather than
    # in a title that legitimately contains the topic phrase.
    haystack = " ".join(
        [book.title or "", book.subtitle or "", *(book.topics or []), description_text]
    )
    conflicting = topic_conflicting_subjects_pattern(topic)
    if conflicting is not None and conflicting.search(haystack):
        findings.append("conflicting_subject")
    if not topic_relevance_pattern(topic).search(haystack):
        findings.append("title_off_topic")
    if STUDY_AID_PATTERN.search(book.title or ""):
        findings.append("study_aid")
    if toc_entries == 0:
        findings.append("no_toc")
    if not has_description and not has_prose and toc_entries == 0:
        findings.append("title_metadata_only")
    if not has_prose:
        findings.append("no_prose")
    return findings


def _status(findings: list[str]) -> str:
    """Name the observed state. Whether to replace or to collect more is a human call.

    A wrong subject outranks having a TOC: a book about another field supplies
    confident, wrong concepts, which is worse than supplying none.
    """
    if "conflicting_subject" in findings:
        return "wrong_subject"
    if "no_identifier" in findings:
        return "unresolvable"
    if "study_aid" in findings:
        return "study_aid"
    if "title_metadata_only" in findings:
        return "no_usable_evidence"
    if "no_toc" in findings:
        return "toc_missing"
    return "usable"


def audit_selection(dataset: CanonicalDataset, topic: str | None = None) -> dict:
    """Report one audit row per selected book without changing the dataset."""
    toc_counts = Counter(entry.book_id for entry in dataset.toc)
    described = {
        document.book_id
        for document in dataset.documents
        if document.document_type in {"description", "publisher_summary"}
    }
    prose = {
        document.book_id
        for document in dataset.documents
        if document.document_type in PROSE_DOCUMENT_TYPES
    }
    description_text: dict[str, str] = {}
    for document in dataset.documents:
        if document.document_type in {"description", "publisher_summary"}:
            description_text[document.book_id] = (
                description_text.get(document.book_id, "") + " " + document.text
            )

    audits: list[BookAudit] = []
    for book in dataset.books:
        book_topics = [item for item in book.topics if item != "computer-science"]
        book_topic = topic or (book_topics[0] if book_topics else "")
        if not book_topic:
            raise ValueError(f"book has no usable topic for audit: {book.book_id}")
        toc_entries = toc_counts.get(book.book_id, 0)
        has_description = book.book_id in described
        has_prose = book.book_id in prose
        findings = _findings(
            book,
            book_topic,
            toc_entries,
            has_description,
            has_prose,
            description_text.get(book.book_id, ""),
        )
        audits.append(
            BookAudit(
                book_id=book.book_id,
                topic=book_topic,
                title=book.title,
                authors=list(book.authors),
                published_year=book.published_year,
                isbn_13=book.isbn_13,
                toc_entries=toc_entries,
                has_description=has_description,
                has_prose=has_prose,
                findings=findings,
                status=_status(findings),
            )
        )

    audits.sort(key=lambda item: (item.status, item.book_id))
    return {
        "schema_version": SCHEMA_VERSION,
        "book_count": len(audits),
        "status_counts": dict(Counter(item.status for item in audits)),
        "finding_counts": dict(Counter(name for item in audits for name in item.findings)),
        "books": [asdict(item) for item in audits],
    }


def write_selection_report(report: dict, path: Path) -> None:
    """Write the deterministic machine-readable audit."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_selection_review(report: dict, path: Path) -> None:
    """Write one blank human decision row per book; no decision is pre-filled."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=REVIEW_FIELDS)
        writer.writeheader()
        for book in report["books"]:
            writer.writerow(
                {
                    field: spreadsheet_safe_csv_value(value)
                    for field, value in {
                        "book_id": book["book_id"],
                        "topic": book["topic"],
                        "title": book["title"],
                        "authors": "; ".join(book["authors"]),
                        "published_year": book["published_year"] or "",
                        "isbn_13": book["isbn_13"] or "",
                        "toc_entries": book["toc_entries"],
                        "has_description": book["has_description"],
                        "has_prose": book["has_prose"],
                        "findings": " ".join(book["findings"]),
                        "audit_status": book["status"],
                        "human_decision": "",
                        "replacement_isbn_13": "",
                        "notes": "",
                    }.items()
                }
            )
