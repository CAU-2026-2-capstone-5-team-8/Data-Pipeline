import json
from datetime import UTC, datetime
from pathlib import Path

from data_pipeline.normalizers import (
    normalize_google_books_response,
    normalize_isbn,
    normalize_open_library_response,
)

FIXTURE = Path(__file__).parent / "fixtures" / "google_books_operating_systems.json"
OPEN_LIBRARY_FIXTURE = Path(__file__).parent / "fixtures" / "open_library_operating_systems.json"
RETRIEVED_AT = datetime(2026, 9, 12, 12, 0, tzinfo=UTC)


def test_normalize_isbn_removes_display_punctuation() -> None:
    assert normalize_isbn("978-0-123456-47-2", 13) == "9780123456472"
    assert normalize_isbn("0-123456-47-X", 10) == "012345647X"
    assert normalize_isbn("too-short", 13) is None


def test_google_response_preserves_provenance_and_deduplicates_isbn() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))

    dataset = normalize_google_books_response(
        payload,
        topic="operating-systems",
        limit=5,
        retrieved_at=RETRIEVED_AT,
    )

    assert len(dataset.books) == 1
    assert dataset.books[0].book_id == "isbn13:9780123456472"
    assert dataset.books[0].topics == ["computer-science", "operating-systems"]
    assert len(dataset.sources) == 1
    assert dataset.sources[0].book_id == dataset.books[0].book_id
    assert dataset.sources[0].retrieved_at == RETRIEVED_AT
    assert dataset.sources[0].content_hash.startswith("sha256:")
    assert len(dataset.documents) == 1
    assert dataset.documents[0].source_id == dataset.sources[0].source_id
    assert dataset.documents[0].document_type == "description"
    assert dataset.toc == []


def test_fallback_book_id_is_deterministic() -> None:
    response = {
        "items": [
            {
                "id": "provider-one",
                "volumeInfo": {
                    "title": "No ISBN Book!",
                    "authors": ["An Author"],
                    "language": "en",
                },
            }
        ]
    }
    first = normalize_google_books_response(
        response, topic="linear-algebra", limit=1, retrieved_at=RETRIEVED_AT
    )
    response["items"][0]["id"] = "provider-two"
    second = normalize_google_books_response(
        response, topic="linear-algebra", limit=1, retrieved_at=RETRIEVED_AT
    )

    assert first.books[0].book_id == second.books[0].book_id


def test_open_library_response_is_normalized_deterministically() -> None:
    payload = json.loads(OPEN_LIBRARY_FIXTURE.read_text(encoding="utf-8"))

    dataset = normalize_open_library_response(
        payload,
        topic="operating-systems",
        limit=5,
        retrieved_at=RETRIEVED_AT,
    )

    assert len(dataset.books) == 2
    assert dataset.books[0].book_id == "isbn13:9780471694663"
    assert dataset.books[0].published_year == 2005
    assert dataset.books[0].language == "en"
    assert dataset.sources[0].url == "https://openlibrary.org/books/OL21152589M"
    assert dataset.sources[0].provider == "open_library"
    assert dataset.documents == []
