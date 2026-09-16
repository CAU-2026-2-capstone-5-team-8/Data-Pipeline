"""Compare two scale selections without inventing missing human relevance labels."""

import csv
import json
from pathlib import Path
from typing import Any


def _audit_labels(path: Path, expected_topics: dict[str, str]) -> dict[str, bool]:
    """Read explicit yes/no review labels; reject unknown identities and contradictory rows."""
    labels: dict[str, bool] = {}
    seen: set[str] = set()
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or not {"book_id", "topic", "topic_relevant"} <= set(
            reader.fieldnames
        ):
            raise ValueError(f"audit CSV lacks book_id/topic/topic_relevant columns: {path}")
        for row in reader:
            book_id = row.get("book_id")
            if book_id in seen or book_id not in expected_topics:
                raise ValueError(f"duplicate or unexpected audit book ID in {path}: {book_id}")
            if row.get("topic") != expected_topics[book_id]:
                raise ValueError(f"audit topic mismatch for {book_id}: {path}")
            seen.add(book_id)
            raw_answer = row.get("topic_relevant")
            if not isinstance(raw_answer, str):
                raise ValueError(f"malformed topic_relevant cell for {book_id}: {path}")
            answer = raw_answer.strip().lower()
            if answer in {"yes", "true", "1"}:
                labels[book_id] = True
            elif answer in {"no", "false", "0"}:
                labels[book_id] = False
            elif answer:
                raise ValueError(f"invalid topic_relevant value for {book_id}: {answer}")
    if seen != set(expected_topics):
        raise ValueError(
            f"audit CSV is missing {len(set(expected_topics) - seen)} selected books: {path}"
        )
    return labels


def compare_scale_reports(
    v1_report: Path,
    v2_report: Path,
    v1_audit: Path,
    v2_audit: Path,
) -> dict[str, Any]:
    """Compare exact IDs and independently audited precision, or return null if incomplete."""
    first = json.loads(v1_report.read_text(encoding="utf-8"))
    second = json.loads(v2_report.read_text(encoding="utf-8"))
    if first.get("experiment") != "scale-50" or second.get("experiment") != "scale-50-v2":
        raise ValueError("expected a scale-50 v1 report followed by a scale-50-v2 report")
    first_snapshots = first.get("artifacts", {}).get("raw_snapshots")
    second_snapshots = second.get("artifacts", {}).get("raw_snapshots")
    if not isinstance(first_snapshots, list) or not isinstance(second_snapshots, list):
        raise ValueError("regenerate both scale reports with raw snapshot IDs before comparing")
    if first_snapshots != second_snapshots:
        raise ValueError("v1 and v2 reports were built from different raw snapshots")
    first_rows = {row["book_id"]: row for row in first["evidence_coverage"]["by_book"]}
    second_rows = {row["book_id"]: row for row in second["evidence_coverage"]["by_book"]}
    first_labels = _audit_labels(
        v1_audit, {book_id: row["topic"] for book_id, row in first_rows.items()}
    )
    second_labels = _audit_labels(
        v2_audit, {book_id: row["topic"] for book_id, row in second_rows.items()}
    )
    for shared_id in set(first_labels) & set(second_labels):
        if first_labels[shared_id] != second_labels[shared_id]:
            raise ValueError(f"conflicting human topic relevance for {shared_id}")
    for shared_id in first_rows.keys() & second_rows.keys():
        if first_rows[shared_id].get("topic") != second_rows[shared_id].get("topic"):
            raise ValueError(f"topic changed for shared book ID: {shared_id}")

    def precision(labels: dict[str, bool], rows: dict[str, Any]) -> float | None:
        return sum(labels.values()) / len(rows) if len(labels) == len(rows) and rows else None

    first_precision = precision(first_labels, first_rows)
    second_precision = precision(second_labels, second_rows)
    by_topic = {}
    topics = {row.get("topic", "unknown") for row in (*first_rows.values(), *second_rows.values())}
    for topic in sorted(topics):
        first_subset = {
            key: row for key, row in first_rows.items() if row.get("topic", "unknown") == topic
        }
        second_subset = {
            key: row for key, row in second_rows.items() if row.get("topic", "unknown") == topic
        }
        first_topic_precision = precision(
            {key: first_labels[key] for key in first_subset if key in first_labels}, first_subset
        )
        second_topic_precision = precision(
            {key: second_labels[key] for key in second_subset if key in second_labels},
            second_subset,
        )
        by_topic[topic] = {
            "v1_labeled_count": len(first_subset.keys() & first_labels.keys()),
            "v2_labeled_count": len(second_subset.keys() & second_labels.keys()),
            "v1_precision": first_topic_precision,
            "v2_precision": second_topic_precision,
            "precision_delta": (
                second_topic_precision - first_topic_precision
                if first_topic_precision is not None and second_topic_precision is not None
                else None
            ),
        }

    return {
        "v1_book_count": len(first_rows),
        "v2_book_count": len(second_rows),
        "removed": [
            {"book_id": book_id, "title": first_rows[book_id]["title"]}
            for book_id in sorted(first_rows.keys() - second_rows.keys())
        ],
        "added": [
            {"book_id": book_id, "title": second_rows[book_id]["title"]}
            for book_id in sorted(second_rows.keys() - first_rows.keys())
        ],
        "v1_labeled_count": len(first_labels),
        "v2_labeled_count": len(second_labels),
        "v1_precision": first_precision,
        "v2_precision": second_precision,
        "precision_delta": (
            second_precision - first_precision
            if first_precision is not None and second_precision is not None
            else None
        ),
        "by_topic": by_topic,
        "note": "Precision requires independent yes/no human labels for every selected book.",
    }
