import json
from pathlib import Path

REPORT = (
    Path(__file__).parents[1]
    / "docs"
    / "experiments"
    / "discovery-600-evidence-availability-2026-09-29.json"
)


def test_discovery_600_report_aggregates_match_per_book_rows() -> None:
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    books = report["books"]
    total = report["coverage"]["unique_total"]

    assert report["experiment"] == "discovery-600"
    assert len(books) == report["collection"]["unique_books"] == total["books"]
    assert sum(book["has_toc"] for book in books) == total["toc_books"]
    assert sum(book["has_description"] for book in books) == total["description_books"]
    assert sum(book["has_both_description_and_toc"] for book in books) == total["both_books"]
    assert sum(row["books"] for row in report["coverage"]["by_publication_year"].values()) == len(
        books
    )


def test_discovery_600_report_keeps_raw_prose_and_credentials_out() -> None:
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    serialized = json.dumps(report, ensure_ascii=False)
    forbidden_keys = {
        "bookIntroduction",
        "bookSummary",
        "contents",
        "description_text",
        "toc_text",
    }

    assert all(key not in serialized for key in forbidden_keys)
    assert all(
        "api_key" not in artifact["request_parameters"]
        for artifact in report["collection"]["raw_artifacts"]
    )
    assert all(
        {
            "topic",
            "book_id",
            "isbn13",
            "title",
            "publisher",
            "published_year",
            "translation",
            "has_description",
            "has_toc",
            "toc_entry_count",
            "has_both_description_and_toc",
        }
        <= book.keys()
        for book in report["books"]
    )


def _report_module():
    import importlib.util

    path = Path(__file__).parents[1] / "scripts" / "report_discovery_600.py"
    spec = importlib.util.spec_from_file_location("report_discovery_600", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_discovery_600_topic_rows_read_paginated_yes24_artifacts(tmp_path) -> None:
    from datetime import UTC, datetime

    from data_pipeline.collectors.yes24 import Yes24Collector
    from data_pipeline.normalizers import normalize_yes24_response
    from data_pipeline.storage import (
        RawArtifact,
        raw_artifact_path,
        write_dataset,
        write_raw_response,
    )

    retrieved_at = datetime(2026, 9, 30, tzinfo=UTC)
    item = {
        "itemId": 105894639,
        "title": "스트랭 선형대수학",
        "isbn13": "9791173400438",
        "goodsSortNm": "국내도서-대학교재",
        "originalTranslation": "Y",
        "originalTitle": "Introduction to Linear Algebra",
    }
    plan = Yes24Collector.search_parameters("linear-algebra", 400)
    response = {
        "pages": [
            {
                "request_parameters": plan["pages"][0],
                "response": {"success": True, "data": {"items": [item], "totalCount": 1}},
            }
        ]
    }
    artifact = RawArtifact(
        provider="yes24",
        topic="linear-algebra",
        requested_limit=100,
        retrieved_at=retrieved_at,
        request_parameters=plan,
        response=response,
    )
    write_raw_response(artifact, raw_artifact_path(tmp_path, artifact))
    dataset = normalize_yes24_response(
        response, topic="linear-algebra", limit=100, retrieved_at=retrieved_at
    )
    write_dataset(dataset, tmp_path / "topics" / "linear-algebra" / "processed")

    rows, raw_summary = _report_module()._topic_rows(tmp_path, "linear-algebra")

    assert raw_summary["provider_items"] == 1
    assert rows[0]["provider_category"] == "국내도서-대학교재"
    assert rows[0]["translation"] != "unknown"
