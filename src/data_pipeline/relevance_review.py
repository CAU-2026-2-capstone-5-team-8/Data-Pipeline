"""One human relevance label per book across two scale selections."""

import csv
import json
from pathlib import Path
from typing import Any

from data_pipeline.scale_comparison import load_scale_pair
from data_pipeline.scale_reporting import spreadsheet_safe_csv_value

REVIEW_FIELDS = (
    "book_id",
    "topic",
    "title",
    "authors",
    "published_year",
    "v1_selected",
    "v2_selected",
    "changed_selection",
    "relevance_basis",
    "relevance_match_method",
    "relevance_source_records",
    "subject_evidence",
    "title_evidence",
    "topic_relevant",
    "notes",
)
SUBJECT_ORIGINS = {"work_detail", "edition_detail"}


def _audit_rows(path: Path, expected: dict[str, dict]) -> tuple[list[str], list[dict[str, str]]]:
    """Check that a generated audit matches a report and has no human labels yet."""
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        fields = reader.fieldnames
        if (
            not fields
            or len(fields) != len(set(fields))
            or not {
                "book_id",
                "topic",
                "topic_relevant",
                "notes",
            }
            <= set(fields)
        ):
            raise ValueError(f"invalid scale audit columns: {path}")
        rows = list(reader)
    seen: set[str] = set()
    for row in rows:
        book_id = row.get("book_id")
        if (
            None in row
            or not isinstance(book_id, str)
            or book_id in seen
            or book_id not in expected
        ):
            raise ValueError(f"duplicate or unknown audit book ID in {path}: {book_id}")
        if row.get("topic") != expected[book_id]["topic"]:
            raise ValueError(f"audit topic mismatch for {book_id}: {path}")
        if row.get("topic_relevant") != "":
            raise ValueError(f"expected a blank generated audit, not human labels: {path}")
        seen.add(book_id)
    if seen != set(expected):
        raise ValueError(f"audit is missing selected books: {path}")
    return fields, rows


def _rejected_by_topic_title(report: dict[str, Any]) -> dict[tuple[str, str], list[dict]]:
    """Index v2 rejections without guessing a canonical ID from a provider work ID."""
    indexed: dict[tuple[str, str], list[dict]] = {}
    for item in report.get("discovery_normalization", {}).get("relevance_rejected_candidates", []):
        indexed.setdefault((item["topic"], item["title"]), []).append(item)
    return indexed


def prepare_relevance_review(
    v1_report: Path,
    v2_report: Path,
    v1_audit: Path,
    v2_audit: Path,
    output: Path,
) -> dict[str, int]:
    """Write a blank, de-duplicated review CSV from matching scale reports."""
    if output.exists() or output in {v1_report, v2_report, v1_audit, v2_audit}:
        raise ValueError(f"review output already exists or overlaps an input: {output}")
    _first, second, first_rows, second_rows = load_scale_pair(v1_report, v2_report)
    _audit_rows(v1_audit, first_rows)
    _audit_rows(v2_audit, second_rows)
    rejected = _rejected_by_topic_title(second)
    rows: list[dict[str, str]] = []
    for book_id in sorted(first_rows.keys() | second_rows.keys()):
        v1 = first_rows.get(book_id)
        v2 = second_rows.get(book_id)
        book = v2 or v1
        assert book is not None
        if v2:
            basis = v2.get("relevance_basis", "unknown")
            evidence = v2.get("relevance_evidence", [])
            match_method = "v2_book_id"
        else:
            matches = rejected.get((book["topic"], book["title"]), [])
            if len(matches) > 1:
                raise ValueError(f"ambiguous v2 rejection for v1-only book: {book_id}")
            basis = matches[0]["reason"] if matches else "not_selected_v2_unattributed"
            evidence = matches[0]["evidence"] if matches else []
            match_method = "unique_topic_title" if matches else "unattributed"
        subject_evidence = [item for item in evidence if item["origin"] in SUBJECT_ORIGINS]
        title_evidence = [item for item in evidence if item["origin"] not in SUBJECT_ORIGINS]
        rows.append(
            {
                "book_id": book_id,
                "topic": book["topic"],
                "title": book["title"],
                "authors": " | ".join(book["authors"]),
                "published_year": str(book.get("published_year") or ""),
                "v1_selected": "yes" if v1 else "no",
                "v2_selected": "yes" if v2 else "no",
                "changed_selection": "no" if v1 and v2 else "yes",
                "relevance_basis": basis,
                "relevance_match_method": match_method,
                "relevance_source_records": " | ".join(
                    sorted({f"{item['origin']}:{item['external_id']}" for item in evidence})
                ),
                "subject_evidence": json.dumps(subject_evidence, ensure_ascii=False),
                "title_evidence": json.dumps(title_evidence, ensure_ascii=False),
                "topic_relevant": "",
                "notes": "",
            }
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=REVIEW_FIELDS)
        writer.writeheader()
        writer.writerows(
            {field: spreadsheet_safe_csv_value(value) for field, value in row.items()}
            for row in rows
        )
    return {
        "v1": len(first_rows),
        "v2": len(second_rows),
        "union": len(rows),
        "shared": len(first_rows.keys() & second_rows.keys()),
        "v1_only": len(first_rows.keys() - second_rows.keys()),
        "v2_only": len(second_rows.keys() - first_rows.keys()),
    }


def _human_labels(
    path: Path, expected: dict[str, dict], first_ids: set[str], second_ids: set[str]
) -> dict[str, dict]:
    """Require one complete yes/no decision for every expected book and topic."""
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        fields = reader.fieldnames
        if not fields or len(fields) != len(set(fields)) or not set(REVIEW_FIELDS) <= set(fields):
            raise ValueError(f"invalid relevance review columns: {path}")
        rows = list(reader)
    labels: dict[str, dict] = {}
    for row in rows:
        book_id = row.get("book_id")
        if (
            None in row
            or not isinstance(book_id, str)
            or book_id in labels
            or book_id not in expected
        ):
            raise ValueError(f"duplicate or unknown review book ID: {book_id}")
        if row.get("topic") != expected[book_id]["topic"]:
            raise ValueError(f"review topic mismatch for {book_id}")
        book = expected[book_id]
        identity = {
            "title": spreadsheet_safe_csv_value(book["title"]),
            "authors": spreadsheet_safe_csv_value(" | ".join(book["authors"])),
            "published_year": str(book.get("published_year") or ""),
        }
        if any(row.get(field) != value for field, value in identity.items()):
            raise ValueError(f"review identity changed for {book_id}")
        if row.get("v1_selected") != ("yes" if book_id in first_ids else "no") or row.get(
            "v2_selected"
        ) != ("yes" if book_id in second_ids else "no"):
            raise ValueError(f"review selection flags changed for {book_id}")
        if row.get("changed_selection") != ("no" if book_id in (first_ids & second_ids) else "yes"):
            raise ValueError(f"review replacement flag changed for {book_id}")
        answer = row.get("topic_relevant")
        if not isinstance(answer, str) or answer.strip().lower() not in {"yes", "no"}:
            raise ValueError(f"incomplete or invalid human topic_relevant for {book_id}")
        notes = row.get("notes")
        if not isinstance(notes, str):
            raise ValueError(f"invalid human notes for {book_id}")
        labels[book_id] = {"topic_relevant": answer.strip().lower(), "notes": notes}
    if labels.keys() != expected.keys():
        missing = len(expected.keys() - labels.keys())
        raise ValueError(f"incomplete human relevance review: missing {missing} books")
    return labels


def finalize_relevance_review(
    v1_report: Path,
    v2_report: Path,
    v1_audit: Path,
    v2_audit: Path,
    review: Path,
    v1_output: Path,
    v2_output: Path,
) -> None:
    """Split complete human judgments into both original scale audit formats."""
    inputs = {v1_report, v2_report, v1_audit, v2_audit, review}
    if v1_output == v2_output or v1_output in inputs or v2_output in inputs:
        raise ValueError("review outputs must be distinct from each other and all inputs")
    if v1_output.exists() or v2_output.exists():
        raise ValueError("review output already exists; refusing to overwrite human work")
    _first, _second, first_rows, second_rows = load_scale_pair(v1_report, v2_report)
    first_fields, first_audit = _audit_rows(v1_audit, first_rows)
    second_fields, second_audit = _audit_rows(v2_audit, second_rows)
    expected = first_rows | second_rows
    labels = _human_labels(review, expected, set(first_rows), set(second_rows))
    for output, fields, audit in (
        (v1_output, first_fields, first_audit),
        (v2_output, second_fields, second_audit),
    ):
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            for row in audit:
                label = labels[row["book_id"]]
                row["topic_relevant"] = label["topic_relevant"]
                row["notes"] = spreadsheet_safe_csv_value(label["notes"])
                writer.writerow(row)
