"""Fixture-only tests for one-label-per-book relevance review."""

import csv
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from data_pipeline.cli import app
from data_pipeline.relevance_review import finalize_relevance_review, prepare_relevance_review
from data_pipeline.scale_comparison import compare_scale_reports

TOPIC = "operating-systems"
SNAPSHOT = [{"provider": "open-library", "topic": TOPIC, "content_hash": "sha256:" + "a" * 64}]


def _book(book_id: str, title: str, *, basis: str | None = None) -> dict:
    row = {
        "book_id": book_id,
        "topic": TOPIC,
        "title": title,
        "authors": ["Fixture Author"],
        "published_year": 2020,
        "isbn_10": None,
        "isbn_13": None,
    }
    if basis:
        row["relevance_basis"] = basis
        row["relevance_evidence"] = [
            {"origin": "work_detail", "external_id": f"/works/{book_id}", "value": "Systems"},
            {
                "origin": "search_edition_title",
                "external_id": f"/books/{book_id}",
                "value": title,
            },
        ]
    return row


def _write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _read_csv(path: Path) -> tuple[list[str], list[dict]]:
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        return reader.fieldnames or [], list(reader)


def _fixture_paths(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    first_report = tmp_path / "v1-report.json"
    second_report = tmp_path / "v2-report.json"
    first_audit = tmp_path / "v1-audit.csv"
    second_audit = tmp_path / "v2-audit.csv"
    first_report.write_text(
        json.dumps(
            {
                "experiment": "scale-50",
                "artifacts": {"raw_snapshots": SNAPSHOT},
                "evidence_coverage": {
                    "by_book": [_book("shared", "Shared book"), _book("old", "Old book")]
                },
            }
        ),
        encoding="utf-8",
    )
    second_report.write_text(
        json.dumps(
            {
                "experiment": "scale-50-v2",
                "artifacts": {"raw_snapshots": SNAPSHOT},
                "evidence_coverage": {
                    "by_book": [
                        _book("shared", "Shared book", basis="matching_subject"),
                        _book("new", "New book", basis="title_only_unverified"),
                    ]
                },
                "discovery_normalization": {
                    "relevance_rejected_candidates": [
                        {
                            "topic": TOPIC,
                            "title": "Old book",
                            "reason": "conflicting_subject",
                            "external_id": "/works/old",
                            "evidence": [
                                {
                                    "origin": "work_detail",
                                    "external_id": "/works/old",
                                    "value": "Robotics",
                                }
                            ],
                        }
                    ]
                },
            }
        ),
        encoding="utf-8",
    )
    fields = ["book_id", "topic", "title", "topic_relevant", "notes"]
    _write_csv(
        first_audit,
        [
            {"book_id": "shared", "topic": TOPIC, "title": "Shared book"},
            {"book_id": "old", "topic": TOPIC, "title": "Old book"},
        ],
        fields,
    )
    _write_csv(
        second_audit,
        [
            {"book_id": "shared", "topic": TOPIC, "title": "Shared book"},
            {"book_id": "new", "topic": TOPIC, "title": "New book"},
        ],
        fields,
    )
    return first_report, second_report, first_audit, second_audit


def test_prepare_review_unions_books_and_preserves_rejection_evidence(tmp_path: Path) -> None:
    paths = _fixture_paths(tmp_path)
    review = tmp_path / "review.csv"
    counts = prepare_relevance_review(*paths, review)
    fields, rows = _read_csv(review)
    by_id = {row["book_id"]: row for row in rows}

    assert counts == {"v1": 2, "v2": 2, "union": 3, "shared": 1, "v1_only": 1, "v2_only": 1}
    assert len(rows) == len(by_id) == 3
    assert {key: by_id["shared"][key] for key in ("v1_selected", "v2_selected")} == {
        "v1_selected": "yes",
        "v2_selected": "yes",
    }
    assert (by_id["old"]["v1_selected"], by_id["old"]["v2_selected"]) == ("yes", "no")
    assert (by_id["new"]["v1_selected"], by_id["new"]["v2_selected"]) == ("no", "yes")
    assert by_id["shared"]["changed_selection"] == "no"
    assert by_id["old"]["changed_selection"] == by_id["new"]["changed_selection"] == "yes"
    assert by_id["old"]["relevance_basis"] == "conflicting_subject"
    assert by_id["old"]["relevance_match_method"] == "unique_topic_title"
    assert by_id["shared"]["relevance_match_method"] == "v2_book_id"
    assert by_id["old"]["relevance_source_records"] == "work_detail:/works/old"
    assert by_id["old"]["published_year"] == "2020"
    assert json.loads(by_id["old"]["subject_evidence"])[0]["value"] == "Robotics"
    assert json.loads(by_id["new"]["title_evidence"])[0]["value"] == "New book"
    assert all(row["topic_relevant"] == row["notes"] == "" for row in rows)
    assert "topic_relevant" in fields


def test_prepare_rejects_different_snapshots_and_ambiguous_rejections(tmp_path: Path) -> None:
    paths = _fixture_paths(tmp_path)
    second = json.loads(paths[1].read_text(encoding="utf-8"))
    second["artifacts"]["raw_snapshots"][0]["content_hash"] = "sha256:" + "b" * 64
    paths[1].write_text(json.dumps(second), encoding="utf-8")
    with pytest.raises(ValueError, match="different raw snapshots"):
        prepare_relevance_review(*paths, tmp_path / "review.csv")

    second["artifacts"]["raw_snapshots"] = SNAPSHOT
    rejected = second["discovery_normalization"]["relevance_rejected_candidates"]
    rejected.append(rejected[0].copy())
    paths[1].write_text(json.dumps(second), encoding="utf-8")
    with pytest.raises(ValueError, match="ambiguous v2 rejection"):
        prepare_relevance_review(*paths, tmp_path / "review.csv")

    rejected.pop()
    second["evidence_coverage"]["by_book"][0]["title"] = "Different edition"
    paths[1].write_text(json.dumps(second), encoding="utf-8")
    with pytest.raises(ValueError, match="shared book metadata changed"):
        prepare_relevance_review(*paths, tmp_path / "review.csv")


def test_prepare_rejects_wrong_audit_topic_and_unknown_book(tmp_path: Path) -> None:
    paths = _fixture_paths(tmp_path)
    fields, rows = _read_csv(paths[2])
    rows[0]["topic"] = "linear-algebra"
    _write_csv(paths[2], rows, fields)
    with pytest.raises(ValueError, match="audit topic mismatch"):
        prepare_relevance_review(*paths, tmp_path / "review.csv")

    rows[0]["topic"] = TOPIC
    rows[0]["book_id"] = "unknown"
    _write_csv(paths[2], rows, fields)
    with pytest.raises(ValueError, match="unknown audit book ID"):
        prepare_relevance_review(*paths, tmp_path / "review.csv")


def test_finalize_requires_complete_review_and_rejects_unknown_or_wrong_topic(
    tmp_path: Path,
) -> None:
    paths = _fixture_paths(tmp_path)
    review = tmp_path / "review.csv"
    prepare_relevance_review(*paths, review)
    first_output = tmp_path / "v1-reviewed.csv"
    second_output = tmp_path / "v2-reviewed.csv"
    with pytest.raises(ValueError, match="incomplete or invalid human"):
        finalize_relevance_review(*paths, review, first_output, second_output)
    assert not first_output.exists() and not second_output.exists()
    comparison = compare_scale_reports(*paths)
    assert comparison["v1_precision"] is comparison["v2_precision"] is None

    fields, rows = _read_csv(review)
    rows[0]["topic_relevant"] = "yes"
    _write_csv(review, rows, fields)
    with pytest.raises(ValueError, match="incomplete or invalid human"):
        finalize_relevance_review(*paths, review, first_output, second_output)
    assert not first_output.exists() and not second_output.exists()

    rows[0]["topic"] = "linear-algebra"
    _write_csv(review, rows, fields)
    with pytest.raises(ValueError, match="review topic mismatch"):
        finalize_relevance_review(*paths, review, first_output, second_output)

    rows[0]["topic"] = TOPIC
    original_title = rows[0]["title"]
    rows[0]["title"] = "Different edition"
    _write_csv(review, rows, fields)
    with pytest.raises(ValueError, match="review identity changed"):
        finalize_relevance_review(*paths, review, first_output, second_output)

    rows[0]["title"] = original_title
    rows[0]["book_id"] = "unknown"
    _write_csv(review, rows, fields)
    with pytest.raises(ValueError, match="unknown review book ID"):
        finalize_relevance_review(*paths, review, first_output, second_output)


def test_complete_review_splits_into_compatible_audits_and_cli_runs(tmp_path: Path) -> None:
    paths = _fixture_paths(tmp_path)
    review = tmp_path / "review.csv"
    first_output = tmp_path / "v1-reviewed.csv"
    second_output = tmp_path / "v2-reviewed.csv"
    runner = CliRunner()
    prepared = runner.invoke(
        app,
        [
            "prepare-relevance-review",
            "--v1-report",
            str(paths[0]),
            "--v2-report",
            str(paths[1]),
            "--v1-audit",
            str(paths[2]),
            "--v2-audit",
            str(paths[3]),
            "--output",
            str(review),
        ],
    )
    assert prepared.exit_code == 0, prepared.output
    fields, rows = _read_csv(review)
    for row in rows:
        row["topic_relevant"] = "no" if row["book_id"] == "old" else "yes"
        row["notes"] = "=SUM(1,2)" if row["book_id"] == "shared" else "checked by human"
    _write_csv(review, rows, fields)
    finalized = runner.invoke(
        app,
        [
            "finalize-relevance-review",
            "--v1-report",
            str(paths[0]),
            "--v2-report",
            str(paths[1]),
            "--v1-audit",
            str(paths[2]),
            "--v2-audit",
            str(paths[3]),
            "--review",
            str(review),
            "--v1-output",
            str(first_output),
            "--v2-output",
            str(second_output),
        ],
    )
    assert finalized.exit_code == 0, finalized.output
    first_fields, first_rows = _read_csv(first_output)
    second_fields, second_rows = _read_csv(second_output)
    assert first_fields == second_fields == _read_csv(paths[2])[0]
    assert next(row for row in first_rows if row["book_id"] == "shared")["topic_relevant"] == "yes"
    assert next(row for row in second_rows if row["book_id"] == "shared")["topic_relevant"] == "yes"
    assert next(row for row in second_rows if row["book_id"] == "shared")["notes"] == "'=SUM(1,2)"
    comparison = compare_scale_reports(paths[0], paths[1], first_output, second_output)
    assert (
        comparison["v1_precision"],
        comparison["v2_precision"],
        comparison["precision_delta"],
    ) == (0.5, 1.0, 0.5)
    compared = runner.invoke(
        app,
        [
            "compare-scale",
            "--v1-report",
            str(paths[0]),
            "--v2-report",
            str(paths[1]),
            "--v1-audit",
            str(first_output),
            "--v2-audit",
            str(second_output),
        ],
    )
    assert compared.exit_code == 0, compared.output
    assert json.loads(compared.output)["precision_delta"] == 0.5
