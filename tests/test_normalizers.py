import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from data_pipeline.collectors.base import InvalidProviderResponse
from data_pipeline.identifiers import normalize_bibliographic_text
from data_pipeline.normalizers import (
    normalize_google_books_response,
    normalize_isbn,
    normalize_open_library_response,
)

FIXTURE = Path(__file__).parent / "fixtures" / "google_books_operating_systems.json"
OPEN_LIBRARY_FIXTURE = Path(__file__).parent / "fixtures" / "open_library_operating_systems.json"
RETRIEVED_AT = datetime(2026, 9, 12, 12, 0, tzinfo=UTC)


def test_normalize_isbn_removes_display_punctuation() -> None:
    assert normalize_isbn("978-0-306-40615-7", 13) == "9780306406157"
    assert normalize_isbn("0-306-40615-2", 10) == "0306406152"
    assert normalize_isbn("too-short", 13) is None
    assert normalize_isbn("978-0-123456-47-0", 13) is None


def test_provider_record_collections_must_be_lists() -> None:
    with pytest.raises(InvalidProviderResponse, match="items"):
        normalize_google_books_response(
            {"items": None},
            topic="operating-systems",
            limit=1,
            retrieved_at=RETRIEVED_AT,
        )
    with pytest.raises(InvalidProviderResponse, match="docs"):
        normalize_open_library_response(
            {"docs": {}},
            topic="operating-systems",
            limit=1,
            retrieved_at=RETRIEVED_AT,
        )


def test_provider_date_formats_preserve_edition_year() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["items"][0]["volumeInfo"]["publishedDate"] = "December 15, 2000"

    dataset = normalize_google_books_response(
        payload, topic="operating-systems", limit=1, retrieved_at=RETRIEVED_AT
    )

    assert dataset.books[0].published_year == 2000


def test_bibliographic_normalization_preserves_technical_and_unicode_distinctions() -> None:
    normalized = {
        normalize_bibliographic_text("C"),
        normalize_bibliographic_text("C++"),
        normalize_bibliographic_text("C#"),
    }
    assert len(normalized) == 3
    assert normalize_bibliographic_text("홍길동") == "홍길동"


def test_google_response_preserves_provenance_and_deduplicates_isbn() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))

    dataset = normalize_google_books_response(
        payload,
        topic="operating-systems",
        limit=5,
        retrieved_at=RETRIEVED_AT,
    )

    assert len(dataset.books) == 1
    assert dataset.books[0].book_id == "isbn13:9780306406157"
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


def test_open_library_edition_statement_enriches_incomplete_work_authors() -> None:
    search_response = json.loads(OPEN_LIBRARY_FIXTURE.read_text(encoding="utf-8"))
    payload = {
        "search_response": search_response,
        "edition_details": {
            "/books/OL21152589M": {
                "key": "/books/OL21152589M",
                "by_statement": "Abraham Silberschatz, Peter Baer Galvin, Greg Gagne.",
            }
        },
    }

    dataset = normalize_open_library_response(
        payload, topic="operating-systems", limit=1, retrieved_at=RETRIEVED_AT
    )

    assert dataset.books[0].authors == [
        "Abraham Silberschatz",
        "Peter Baer Galvin",
        "Greg Gagne",
    ]


def test_open_library_edition_statement_replaces_polluted_work_authors() -> None:
    payload = {
        "search_response": {
            "docs": [
                {
                    "key": "/works/OL1W",
                    "title": "Linear Algebra",
                    "author_name": [f"Author Variant {index}" for index in range(9)],
                    "editions": {
                        "docs": [
                            {
                                "key": "/books/OL1M",
                                "title": "Linear Algebra",
                                "language": ["eng"],
                            }
                        ]
                    },
                }
            ]
        },
        "edition_details": {"/books/OL1M": {"by_statement": "by Correct Author, Second Author."}},
    }

    dataset = normalize_open_library_response(
        payload, topic="linear-algebra", limit=1, retrieved_at=RETRIEVED_AT
    )

    assert dataset.books[0].authors == ["Correct Author", "Second Author"]


def test_open_library_incomplete_edition_statement_does_not_drop_work_author() -> None:
    payload = {
        "search_response": {
            "docs": [
                {
                    "key": "/works/OL1W",
                    "title": "Elementary Linear Algebra",
                    "author_name": ["Howard Anton", "Chris Rorres"],
                    "editions": {
                        "docs": [
                            {
                                "key": "/books/OL1M",
                                "title": "Elementary Linear Algebra",
                                "language": ["eng"],
                            }
                        ]
                    },
                }
            ]
        },
        "edition_details": {"/books/OL1M": {"by_statement": "Howard Anton."}},
    }

    dataset = normalize_open_library_response(
        payload, topic="linear-algebra", limit=1, retrieved_at=RETRIEVED_AT
    )

    assert dataset.books[0].authors == ["Howard Anton", "Chris Rorres"]


def test_open_library_skips_work_without_english_edition() -> None:
    payload = {
        "docs": [
            {
                "key": "/works/OL1W",
                "title": "Operating Systems",
                "language": ["eng", "spa"],
                "editions": {
                    "docs": [
                        {
                            "key": "/books/OL1M",
                            "title": "Sistemas operativos",
                            "language": ["spa"],
                        }
                    ]
                },
            }
        ]
    }

    dataset = normalize_open_library_response(
        payload, topic="operating-systems", limit=1, retrieved_at=RETRIEVED_AT
    )

    assert dataset.books == []
    assert dataset.sources == []


def test_provider_fallback_ids_do_not_collide_without_authors_or_isbn() -> None:
    google = normalize_google_books_response(
        {
            "items": [
                {
                    "id": "same-id",
                    "volumeInfo": {"title": "Untitled Manual", "language": "en"},
                }
            ]
        },
        topic="operating-systems",
        limit=1,
        retrieved_at=RETRIEVED_AT,
    )
    open_library = normalize_open_library_response(
        {
            "docs": [
                {
                    "key": "/works/same-id",
                    "title": "Untitled Manual",
                    "language": ["eng"],
                    "editions": {
                        "docs": [
                            {
                                "key": "same-id",
                                "title": "Untitled Manual",
                                "language": ["eng"],
                            }
                        ]
                    },
                }
            ]
        },
        topic="operating-systems",
        limit=1,
        retrieved_at=RETRIEVED_AT,
    )

    assert google.books[0].book_id != open_library.books[0].book_id


def test_open_library_skips_polluted_author_aggregation_and_uses_next_candidate() -> None:
    polluted_authors = [f"Author Variant {index}" for index in range(9)]
    payload = {
        "docs": [
            {
                "key": "/works/polluted",
                "title": "Linear Algebra",
                "author_name": polluted_authors,
                "editions": {
                    "docs": [
                        {
                            "key": "/books/polluted",
                            "title": "Linear Algebra",
                            "language": ["eng"],
                        }
                    ]
                },
            },
            {
                "key": "/works/clean",
                "title": "Linear Algebra Done Right",
                "author_name": ["Sheldon Axler", "Sheldon Axler"],
                "first_publish_year": 1995,
                "editions": {
                    "docs": [
                        {
                            "key": "/books/clean",
                            "title": "Linear Algebra Done Right",
                            "language": ["eng"],
                            "publish_date": ["November 2014"],
                        }
                    ]
                },
            },
        ]
    }

    dataset = normalize_open_library_response(
        payload, topic="linear-algebra", limit=1, retrieved_at=RETRIEVED_AT
    )

    assert len(dataset.books) == 1
    assert dataset.books[0].title == "Linear Algebra Done Right"
    assert dataset.books[0].authors == ["Sheldon Axler"]
    assert dataset.books[0].published_year == 2014
