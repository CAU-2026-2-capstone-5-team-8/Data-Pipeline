"""Traceable collection signals, never book eligibility or human review decisions."""

import csv
import json
import re
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

from data_pipeline.models import CanonicalDataset
from data_pipeline.scale_reporting import spreadsheet_safe_csv_value
from data_pipeline.topics import TOPIC_REGISTRY
from data_pipeline.validation import validate_dataset

SCHEMA_VERSION = 2
# Explicit title/subtitle markers, not a classifier of all textbooks or workbooks.
STUDY_AID_PATTERN = re.compile(
    r"\b(?:solutions?\s+manual|study\s+guide|solved\s+problems?|schaum'?s\s+outline"
    r"|workbooks?|exam\s+prep(?:aration)?|test\s+bank|problem\s+book)\b"
    r"|문제집|문제서|워크북|해설집|내신|수능|기출|모의고사|수험서",
    re.IGNORECASE,
)
PROSE_DOCUMENT_TYPES = frozenset({"preface", "introduction", "preview", "sample_chapter"})
DESCRIPTION_TYPES = frozenset({"description", "publisher_summary"})
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
    evidence_state: str
    signals: list[dict]
    source_ids: list[str]
    toc_source_ids: list[str]
    documents: list[dict]


def _matches(pattern: str, fields: list[dict], finding: str) -> list[dict]:
    result = []
    for field in fields:
        for match in re.finditer(pattern, field["text"], re.IGNORECASE):
            result.append(
                {
                    "finding": finding,
                    **{key: value for key, value in field.items() if key != "text"},
                    "matched_text": match.group(),
                    "start": match.start(),
                    "end": match.end(),
                }
            )
    return result


def _audit_book(book, topic: str, dataset: CanonicalDataset) -> BookAudit:
    spec = TOPIC_REGISTRY[topic]
    documents = sorted(
        (d for d in dataset.documents if d.book_id == book.book_id),
        key=lambda d: d.document_id,
    )
    toc = [entry for entry in dataset.toc if entry.book_id == book.book_id]
    sources = sorted(
        (s for s in dataset.sources if s.book_id == book.book_id), key=lambda s: s.source_id
    )
    metadata_fields = [
        {"field": "title", "record_id": book.book_id, "text": book.title},
        {"field": "subtitle", "record_id": book.book_id, "text": book.subtitle or ""},
    ]
    text_fields = metadata_fields + [
        {"field": "text", "record_id": d.document_id, "source_id": d.source_id, "text": d.text}
        for d in documents
        if d.document_type in DESCRIPTION_TYPES
    ]
    # Assigned canonical topic slugs are not independent relevance evidence.
    relevant = any(
        re.search(pattern, field["text"], re.IGNORECASE)
        for pattern in (spec.relevance_term_pattern, spec.korean_relevance_term_pattern)
        if pattern
        for field in text_fields
    )
    signals = _matches(STUDY_AID_PATTERN.pattern, metadata_fields, "study_aid_marker")
    for pattern in (spec.conflicting_subjects_pattern, spec.korean_conflicting_subjects_pattern):
        if pattern:
            signals.extend(_matches(pattern, text_fields, "conflicting_subject_marker"))
    findings = {signal["finding"] for signal in signals}
    if not book.isbn_13 and not book.isbn_10:
        findings.add("no_isbn")  # Title/author/provider IDs may still identify this book.
    if not relevant:
        findings.add("topic_terms_not_observed")
    has_description = any(d.document_type in DESCRIPTION_TYPES for d in documents)
    has_prose = any(d.document_type in PROSE_DOCUMENT_TYPES for d in documents)
    if not toc:
        findings.add("no_toc")
    if not has_prose:
        findings.add("no_prose")
    if not toc and not documents:
        findings.add("title_metadata_only")
    toc_sources = {entry.source_id for entry in toc}
    for source in sources:
        if (
            source.source_id in toc_sources
            and source.evidence
            and (
                source.evidence.same_edition is False
                or source.evidence.tier == "same_work_alternate_edition_toc"
            )
        ):
            findings.add("alternate_edition_toc")
            signals.append({"finding": "alternate_edition_toc", "source_id": source.source_id})
    if has_prose:
        evidence_state = "toc_and_prose_documents" if toc else "prose_documents"
    elif toc:
        evidence_state = "toc_and_description" if has_description else "toc_only"
    else:
        evidence_state = (
            "description_only"
            if has_description
            else ("other_documents_only" if documents else "metadata_only")
        )
    review_signals = {
        "no_isbn",
        "topic_terms_not_observed",
        "study_aid_marker",
        "conflicting_subject_marker",
        "alternate_edition_toc",
    }
    status = (
        "review_required"
        if findings & review_signals
        else ("evidence_present" if toc or documents else "metadata_only")
    )
    return BookAudit(
        book.book_id,
        topic,
        book.title,
        list(book.authors),
        book.published_year,
        book.isbn_13,
        len(toc),
        has_description,
        has_prose,
        sorted(findings),
        status,
        evidence_state,
        sorted(signals, key=lambda s: json.dumps(s, sort_keys=True)),
        [s.source_id for s in sources],
        sorted(toc_sources),
        [
            {
                "document_id": d.document_id,
                "document_type": d.document_type,
                "source_id": d.source_id,
                "content_hash": d.content_hash,
                "character_count": len(d.text),
            }
            for d in documents
        ],
    )


def audit_selection(dataset: CanonicalDataset, topic: str | None = None) -> dict:
    """One row per book/leaf topic; no inference of textbook validity or text difficulty."""
    errors = validate_dataset(dataset)
    if errors:
        raise ValueError("; ".join(errors))
    if topic is not None and topic not in TOPIC_REGISTRY:
        raise ValueError(f"unsupported topic: {topic}")
    audits = []
    for book in sorted(dataset.books, key=lambda b: b.book_id):
        topics = [topic] if topic else sorted(set(book.topics) & TOPIC_REGISTRY.keys())
        if not topics:
            raise ValueError(f"book has no usable topic for audit: {book.book_id}")
        audits.extend(_audit_book(book, leaf, dataset) for leaf in topics)
    return {
        "schema_version": SCHEMA_VERSION,
        "policy": "selection-signals-v2",
        "rules": {
            "study_aid_pattern": STUDY_AID_PATTERN.pattern,
            "topics": {
                leaf: {
                    field: getattr(TOPIC_REGISTRY[leaf], field)
                    for field in (
                        "relevance_term_pattern",
                        "korean_relevance_term_pattern",
                        "conflicting_subjects_pattern",
                        "korean_conflicting_subjects_pattern",
                    )
                }
                for leaf in sorted({a.topic for a in audits})
            },
        },
        "book_count": len(dataset.books),
        "audit_row_count": len(audits),
        "status_counts": dict(sorted(Counter(a.status for a in audits).items())),
        "finding_counts": dict(sorted(Counter(f for a in audits for f in a.findings).items())),
        "evidence_state_counts": dict(sorted(Counter(a.evidence_state for a in audits).items())),
        "books": [asdict(a) for a in audits],
        "sources": [
            s.model_dump(mode="json") for s in sorted(dataset.sources, key=lambda s: s.source_id)
        ],
    }


def write_selection_report(report: dict, path: Path) -> None:
    """Never replace an existing report or canonical input."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")


def write_selection_review(report: dict, path: Path) -> None:
    """Never erase existing human decisions; new decision fields are blank."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=REVIEW_FIELDS)
        writer.writeheader()
        for book in report["books"]:
            values = {field: book.get(field, "") for field in REVIEW_FIELDS}
            values.update(
                authors="; ".join(book["authors"]),
                findings=" ".join(book["findings"]),
                audit_status=book["status"],
                human_decision="",
                replacement_isbn_13="",
                notes="",
            )
            writer.writerow(
                {field: spreadsheet_safe_csv_value(value) for field, value in values.items()}
            )
