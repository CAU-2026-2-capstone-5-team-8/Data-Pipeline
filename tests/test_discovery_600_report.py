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
