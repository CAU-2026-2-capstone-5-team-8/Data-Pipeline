"""Fixture-only checks for the opt-in scale relevance experiment."""

import csv
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from data_pipeline.cli import app
from data_pipeline.collectors.open_library import OpenLibraryCollector
from data_pipeline.diagnostics import NormalizationDiagnostics
from data_pipeline.manifest import MvpManifest, RawArtifactSelector, load_manifest
from data_pipeline.normalizers import normalize_open_library_response
from data_pipeline.relevance import open_library_relevance
from data_pipeline.scale_comparison import compare_scale_reports
from data_pipeline.storage import RawArtifact, raw_artifact_path, read_dataset, write_raw_response

RETRIEVED_AT = datetime(2026, 9, 16, tzinfo=UTC)


def test_v2_manifest_pins_same_two_topic_raw_snapshots_as_v1() -> None:
    v1 = load_manifest(Path("configs/experiments/scale-50.json"))
    v2 = load_manifest(Path("configs/experiments/scale-50-v2.json"))

    assert v1.relevance_gate is None
    assert v2.relevance_gate == "topic-evidence-v1"
    assert len(v1.expected_book_ids) == len(v2.expected_book_ids) == 50
    assert len(set(v1.expected_book_ids) - set(v2.expected_book_ids)) == 4
    assert [(item.topic, item.requested_limit) for item in v2.raw_artifacts] == [
        (item.topic, item.requested_limit) for item in v1.raw_artifacts
    ]
    assert all(item.content_hash for item in v2.raw_artifacts)
    assert all(item.retrieved_at for item in v2.raw_artifacts)


def _candidate(work_key: str, title: str, isbn: str) -> dict:
    return {
        "key": work_key,
        "title": title,
        "author_name": ["Fixture Author"],
        "editions": {
            "docs": [
                {
                    "key": work_key.replace("works", "books"),
                    "title": title,
                    "language": ["eng"],
                    "isbn": [isbn],
                }
            ]
        },
    }


def test_relevance_uses_subjects_then_english_edition_title() -> None:
    robot = _candidate("/works/robot", "Robot Operating System", "9780306406157")
    subjects = {"/works/robot": {"subjects": ["Operating systems (computers)", "Robotics"]}}
    decision = open_library_relevance("operating-systems", robot, {}, subjects)
    assert (decision.accepted, decision.reason) == (False, "conflicting_subject")
    assert decision.evidence[0] == {
        "origin": "work_detail",
        "external_id": "/works/robot",
        "value": "Operating systems (computers)",
    }

    english = _candidate("/works/german", "Lineare Algebra", "9780131103627")
    english["editions"]["docs"][0]["title"] = "Linear Algebra"
    assert open_library_relevance("linear-algebra", english, {}, {}).reason == (
        "title_only_unverified"
    )
    assert open_library_relevance(
        "linear-algebra", english, {}, {"/works/german": {"subjects": ["Literature", "Matrices"]}}
    ).accepted
    no_match = _candidate("/works/power", "Power system operation", "9780306406157")
    assert not open_library_relevance("operating-systems", no_match, {}, {}).accepted


def test_title_only_decision_preserves_nonmatching_subject_evidence() -> None:
    record = _candidate("/works/algebra", "A mathematics textbook", "9780131103627")
    record["editions"]["docs"][0]["title"] = "Linear Algebra"
    decision = open_library_relevance(
        "linear-algebra",
        record,
        {},
        {"/works/algebra": {"subjects": ["Matrices"]}},
    )

    assert decision.accepted
    assert decision.reason == "title_only_unverified"
    assert decision.evidence == [
        {"origin": "work_detail", "external_id": "/works/algebra", "value": "Matrices"},
        {
            "origin": "search_edition_title",
            "external_id": "/books/algebra",
            "value": "Linear Algebra",
        },
    ]


def test_rejected_candidate_evidence_identifies_work_and_edition_records() -> None:
    record = _candidate("/works/robot", "A computing text", "9780306406157")
    record["editions"]["docs"][0]["title"] = "  Robot Operating System  "
    payload = {
        "search_response": {"docs": [record]},
        "work_details": {"/works/robot": {"subjects": ["Operating systems (computers)"]}},
        "edition_details": {"/books/robot": {"subjects": ["Robotics"]}},
    }
    diagnostics = NormalizationDiagnostics(provider="open_library")
    normalize_open_library_response(
        payload,
        topic="operating-systems",
        limit=1,
        retrieved_at=RETRIEVED_AT,
        relevance_gate="topic-evidence-v1",
        diagnostics=diagnostics,
    )
    rejected = diagnostics.relevance_rejected_candidates[0]
    assert rejected["title"] == "Robot Operating System"
    assert rejected["work_title"] == "A computing text"
    assert [item["origin"] for item in rejected["evidence"]] == ["work_detail", "edition_detail"]
    assert rejected["evidence"][1]["external_id"] == "/books/robot"


def test_opt_in_gate_replaces_conflicting_subject_without_changing_default(tmp_path) -> None:
    payload = {
        "search_response": {
            "docs": [
                _candidate("/works/robot", "Robot Operating System", "9780306406157"),
                _candidate("/works/unix", "Learning the UNIX Operating System", "9780131103627"),
            ]
        },
        "work_details": {
            "/works/robot": {"subjects": ["Operating systems (computers)", "Robotics"]},
            "/works/unix": {"subjects": ["Operating systems (computers)"]},
        },
    }
    diagnostics = NormalizationDiagnostics(provider="open_library")
    ungated = normalize_open_library_response(
        payload, topic="operating-systems", limit=1, retrieved_at=RETRIEVED_AT
    )
    gated = normalize_open_library_response(
        payload,
        topic="operating-systems",
        limit=1,
        retrieved_at=RETRIEVED_AT,
        relevance_gate="topic-evidence-v1",
        diagnostics=diagnostics,
    )
    assert ungated.books[0].title == "Robot Operating System"
    assert gated.books[0].title == "Learning the UNIX Operating System"
    assert diagnostics.relevance_rejected_count == 1
    assert diagnostics.normalization_failure_count == 0

    artifact = RawArtifact(
        provider="open-library",
        topic="operating-systems",
        requested_limit=1,
        retrieved_at=RETRIEVED_AT,
        request_parameters=OpenLibraryCollector.search_parameters("operating-systems", 4),
        response=payload,
    )
    raw_path = raw_artifact_path(tmp_path, artifact)
    write_raw_response(artifact, raw_path)
    manifest = MvpManifest(
        relevance_gate="topic-evidence-v1",
        raw_artifacts=[
            RawArtifactSelector(
                provider="open-library", topic="operating-systems", requested_limit=1
            )
        ],
        expected_book_ids=[gated.books[0].book_id],
    )
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(manifest.model_dump_json(), encoding="utf-8")
    args = ["build-manifest", "--manifest", str(manifest_path), "--data-dir", str(tmp_path)]
    assert CliRunner().invoke(app, [*args, "--output", str(tmp_path / "first")]).exit_code == 0
    assert CliRunner().invoke(app, [*args, "--output", str(tmp_path / "second")]).exit_code == 0
    for name in ("books", "documents", "toc", "sources"):
        assert (tmp_path / "first" / f"{name}.jsonl").read_bytes() == (
            tmp_path / "second" / f"{name}.jsonl"
        ).read_bytes()
    assert read_dataset(tmp_path / "first").books[0].book_id == gated.books[0].book_id
    assert raw_path.exists()
    report_result = CliRunner().invoke(
        app,
        [
            "report-scale",
            "--manifest",
            str(manifest_path),
            "--data-dir",
            str(tmp_path),
        ],
    )
    assert report_result.exit_code == 0, report_result.output
    report = json.loads((tmp_path / "reports" / "scale-report.json").read_text(encoding="utf-8"))
    assert report["discovery_normalization"]["relevance_rejected_count"] == 1
    assert (
        report["discovery_normalization"]["relevance_rejected_candidates"][0]["reason"]
        == "conflicting_subject"
    )
    assert report["artifacts"]["raw_content_hashes"] == [artifact.content_hash]
    with (tmp_path / "reports" / "scale-audit.csv").open(encoding="utf-8") as stream:
        audit = next(csv.DictReader(stream))
    assert audit["relevance_basis"] == "matching_subject"
    assert audit["relevance_source_records"] == "work_detail:/works/unix"
    assert audit["topic_relevant"] == ""
    by_book = report["evidence_coverage"]["by_book"]
    assert by_book[0]["relevance_evidence"][0]["external_id"] == "/works/unix"


def test_gate_manifest_rejects_unsupported_provider() -> None:
    with pytest.raises(ValueError, match="supports open-library"):
        MvpManifest(
            relevance_gate="topic-evidence-v1",
            raw_artifacts=[
                RawArtifactSelector(
                    provider="google-books", topic="linear-algebra", requested_limit=1
                )
            ],
            expected_book_ids=["book_example"],
        )


def test_relevance_gate_does_not_hide_normalization_failures() -> None:
    diagnostics = NormalizationDiagnostics(provider="open_library")
    payload = {
        "docs": [
            {
                "key": "/works/invalid",
                "title": "Power system operation",
                "editions": {"docs": "malformed"},
            }
        ]
    }

    dataset = normalize_open_library_response(
        payload,
        topic="operating-systems",
        limit=1,
        retrieved_at=RETRIEVED_AT,
        relevance_gate="topic-evidence-v1",
        diagnostics=diagnostics,
    )

    assert dataset.books == []
    assert diagnostics.failure_counts == {"invalid_provider_response": 1}
    assert diagnostics.relevance_rejected_count == 0


def test_precision_comparison_requires_full_consistent_human_labels(tmp_path) -> None:
    first_report = tmp_path / "first.json"
    second_report = tmp_path / "second.json"
    first_audit = tmp_path / "first.csv"
    second_audit = tmp_path / "second.csv"
    first_report.write_text(
        json.dumps(
            {
                "experiment": "scale-50",
                "artifacts": {
                    "raw_snapshots": [
                        {
                            "topic": "fixture",
                            "retrieved_at": RETRIEVED_AT.isoformat(),
                            "content_hash": "sha256:" + "a" * 64,
                        }
                    ]
                },
                "evidence_coverage": {
                    "by_book": [
                        {"book_id": "one", "title": "One", "topic": "operating-systems"},
                        {"book_id": "two", "title": "Two", "topic": "operating-systems"},
                    ]
                },
            }
        ),
        encoding="utf-8",
    )
    second_report.write_text(
        json.dumps(
            {
                "experiment": "scale-50-v2",
                "artifacts": {
                    "raw_snapshots": [
                        {
                            "topic": "fixture",
                            "retrieved_at": RETRIEVED_AT.isoformat(),
                            "content_hash": "sha256:" + "a" * 64,
                        }
                    ]
                },
                "evidence_coverage": {
                    "by_book": [
                        {"book_id": "one", "title": "One", "topic": "operating-systems"},
                        {"book_id": "three", "title": "Three", "topic": "operating-systems"},
                    ]
                },
            }
        ),
        encoding="utf-8",
    )

    def write_audit(path, rows):
        with path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=["book_id", "topic", "topic_relevant"])
            writer.writeheader()
            writer.writerows([{"topic": "operating-systems", **row} for row in rows])

    write_audit(
        first_audit,
        [{"book_id": "one", "topic_relevant": "yes"}, {"book_id": "two", "topic_relevant": ""}],
    )
    write_audit(
        second_audit,
        [
            {"book_id": "one", "topic_relevant": "yes"},
            {"book_id": "three", "topic_relevant": "yes"},
        ],
    )
    partial = compare_scale_reports(first_report, second_report, first_audit, second_audit)
    assert partial["v1_precision"] is None and partial["precision_delta"] is None
    with pytest.raises(ValueError, match="v1 report followed"):
        compare_scale_reports(second_report, first_report, second_audit, first_audit)
    write_audit(
        first_audit,
        [{"book_id": "one", "topic_relevant": "yes"}, {"book_id": "two", "topic_relevant": "no"}],
    )
    complete = compare_scale_reports(first_report, second_report, first_audit, second_audit)
    assert (complete["v1_precision"], complete["v2_precision"], complete["precision_delta"]) == (
        0.5,
        1.0,
        0.5,
    )
    write_audit(
        second_audit,
        [
            {"book_id": "one", "topic": "linear-algebra", "topic_relevant": "yes"},
            {"book_id": "three", "topic_relevant": "yes"},
        ],
    )
    with pytest.raises(ValueError, match="audit topic mismatch"):
        compare_scale_reports(first_report, second_report, first_audit, second_audit)
    write_audit(
        second_audit,
        [{"book_id": "one", "topic_relevant": "no"}, {"book_id": "three", "topic_relevant": "yes"}],
    )
    with pytest.raises(ValueError, match="conflicting human"):
        compare_scale_reports(first_report, second_report, first_audit, second_audit)
    second_report.write_text(
        json.dumps(
            {
                "experiment": "scale-50-v2",
                "artifacts": {
                    "raw_snapshots": [
                        {
                            "topic": "fixture",
                            "retrieved_at": RETRIEVED_AT.isoformat(),
                            "content_hash": "sha256:" + "b" * 64,
                        }
                    ]
                },
                "evidence_coverage": {
                    "by_book": [{"book_id": "one", "title": "One", "topic": "operating-systems"}]
                },
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="different raw snapshots"):
        compare_scale_reports(first_report, second_report, first_audit, second_audit)
