import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from data_pipeline.collectors.base import InvalidProviderResponse
from data_pipeline.datasets import DatasetMergeError, merge_datasets
from data_pipeline.identifiers import normalize_bibliographic_text, sha256_json, sha256_text
from data_pipeline.models import Book, CanonicalDataset
from data_pipeline.normalizers import (
    normalize_google_books_response,
    normalize_isbn,
    normalize_open_library_response,
    normalize_public_book_page_response,
    normalize_publisher_page_response,
)
from data_pipeline.public_book_sources import public_book_source
from data_pipeline.publisher_sources import publisher_source
from data_pipeline.validation import validate_dataset

FIXTURE = Path(__file__).parent / "fixtures" / "google_books_operating_systems.json"
OPEN_LIBRARY_FIXTURE = Path(__file__).parent / "fixtures" / "open_library_operating_systems.json"
WILEY_ELA_HOME_FIXTURE = Path(__file__).parent / "fixtures" / "wiley_ela10_home.html"
WILEY_ELA_TOC_FIXTURE = Path(__file__).parent / "fixtures" / "wiley_ela10_toc.html"
WILEY_HOME_FIXTURE = Path(__file__).parent / "fixtures" / "wiley_osc7_home.html"
WILEY_TOC_FIXTURE = Path(__file__).parent / "fixtures" / "wiley_osc7_toc.html"
ECAMPUS_FIXTURE = Path(__file__).parent / "fixtures" / "ecampus_stallings_os4.html"
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


def test_open_library_normalizes_descriptions_and_hierarchical_toc() -> None:
    payload = {
        "search_response": {
            "docs": [
                {
                    "key": "/works/OL1W",
                    "title": "Linear Algebra",
                    "author_name": ["Example Author"],
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
        "edition_details": {
            "/books/OL1M": {
                "description": {"type": "/type/text", "value": "Edition description"},
                "table_of_contents": [
                    {"level": 0, "label": "1", "title": "Vectors"},
                    {"level": 1, "label": "1.1", "title": "Vector Spaces"},
                    {"level": 0, "label": "2", "title": "Matrices"},
                ],
            }
        },
        "work_details": {
            "/works/OL1W": {
                "key": "/works/OL1W",
                "description": "A different work description",
            }
        },
    }

    dataset = normalize_open_library_response(
        payload, topic="linear-algebra", limit=1, retrieved_at=RETRIEVED_AT
    )

    assert [document.text for document in dataset.documents] == [
        "Edition description",
        "A different work description",
    ]
    assert len(dataset.sources) == 3
    assert dataset.sources[1].url == "https://openlibrary.org/books/OL1M.json"
    assert dataset.sources[1].content_hash == sha256_json(payload["edition_details"]["/books/OL1M"])
    assert dataset.sources[2].url == "https://openlibrary.org/works/OL1W.json"
    assert dataset.documents[1].source_id == dataset.sources[2].source_id
    assert [entry.level for entry in dataset.toc] == [1, 2, 1]
    assert [entry.order_index for entry in dataset.toc] == [0, 0, 1]
    assert dataset.toc[1].parent_entry_id == dataset.toc[0].toc_entry_id
    assert dataset.toc[2].parent_entry_id is None
    assert validate_dataset(dataset) == []


def test_open_library_deduplicates_identical_edition_and_work_descriptions() -> None:
    payload = {
        "search_response": {
            "docs": [
                {
                    "key": "/works/OL1W",
                    "title": "Operating Systems",
                    "author_name": ["Example Author"],
                    "editions": {
                        "docs": [
                            {
                                "key": "/books/OL1M",
                                "title": "Operating Systems",
                                "language": ["eng"],
                            }
                        ]
                    },
                }
            ]
        },
        "edition_details": {"/books/OL1M": {"description": "Same description"}},
        "work_details": {"/works/OL1W": {"description": {"value": "Same description"}}},
    }

    dataset = normalize_open_library_response(
        payload, topic="operating-systems", limit=1, retrieved_at=RETRIEVED_AT
    )

    assert len(dataset.documents) == 1
    assert len(dataset.sources) == 2


def test_open_library_rejects_work_description_for_a_different_edition() -> None:
    payload = {
        "search_response": {
            "docs": [
                {
                    "key": "/works/OL1W",
                    "title": "Operating System Concepts",
                    "author_name": ["Example Author"],
                    "editions": {
                        "docs": [
                            {
                                "key": "/books/OL1M",
                                "title": "Operating System Concepts",
                                "language": ["eng"],
                            }
                        ]
                    },
                }
            ]
        },
        "edition_details": {"/books/OL1M": {"edition_name": "7th ed."}},
        "work_details": {
            "/works/OL1W": {"description": "This Eighth Edition adds new operating system topics."}
        },
    }

    dataset = normalize_open_library_response(
        payload, topic="operating-systems", limit=1, retrieved_at=RETRIEVED_AT
    )

    assert dataset.documents == []
    assert len(dataset.sources) == 1


def test_wiley_page_normalizes_exact_edition_toc() -> None:
    source = publisher_source("wiley-osc7")
    home_html = WILEY_HOME_FIXTURE.read_text(encoding="utf-8")
    toc_html = WILEY_TOC_FIXTURE.read_text(encoding="utf-8")
    payload = {
        "source_slug": source.slug,
        "home_url": source.home_url,
        "home_html": home_html,
        "toc_url": source.toc_url,
        "toc_html": toc_html,
    }

    dataset = normalize_publisher_page_response(
        payload, topic="operating-systems", retrieved_at=RETRIEVED_AT
    )

    assert dataset.books == []
    assert dataset.documents == []
    assert len(dataset.toc) == 26
    assert [entry.label for entry in dataset.toc] == list(source.expected_toc_labels)
    assert dataset.toc[0].title == "Introduction"
    assert dataset.toc[-1].title == "Windows 2000"
    assert [entry.order_index for entry in dataset.toc] == list(range(26))
    assert all(entry.level == 1 for entry in dataset.toc)
    assert len(dataset.sources) == 2
    assert all(item.book_id == source.book_id for item in dataset.sources)
    assert all(item.source_type == "publisher_page" for item in dataset.sources)
    assert dataset.sources[0].url == source.home_url
    assert dataset.sources[0].content_hash == sha256_text(home_html)
    assert dataset.sources[1].url == source.toc_url
    assert dataset.sources[1].content_hash == sha256_text(toc_html)
    assert all(entry.source_id == dataset.sources[1].source_id for entry in dataset.toc)


def test_wiley_page_rejects_wrong_edition() -> None:
    source = publisher_source("wiley-osc7")
    payload = {
        "source_slug": source.slug,
        "home_url": source.home_url,
        "home_html": "Operating System Concepts, Eighth Edition 0471694665",
        "toc_url": source.toc_url,
        "toc_html": '<div class="chapterTitle"><h3>Chapter 1: Introduction</h3></div>',
    }

    with pytest.raises(InvalidProviderResponse, match="expected edition"):
        normalize_publisher_page_response(
            payload, topic="operating-systems", retrieved_at=RETRIEVED_AT
        )


def test_wiley_elementary_linear_algebra_toc_matches_exact_tenth_edition() -> None:
    source = publisher_source("wiley-ela10")
    payload = {
        "source_slug": source.slug,
        "home_url": source.home_url,
        "home_html": WILEY_ELA_HOME_FIXTURE.read_text(encoding="utf-8"),
        "toc_url": source.toc_url,
        "toc_html": WILEY_ELA_TOC_FIXTURE.read_text(encoding="utf-8"),
    }

    dataset = normalize_publisher_page_response(
        payload, topic="linear-algebra", retrieved_at=RETRIEVED_AT
    )

    assert len(dataset.toc) == 9
    assert [entry.label for entry in dataset.toc] == list(source.expected_toc_labels)
    assert dataset.toc[0].title == "SYSTEMS OF LINEAR EQUATIONS AND MATRICES."
    assert dataset.toc[-1].title == "NUMERICAL METHODS."
    assert all(entry.book_id == source.book_id for entry in dataset.toc)
    assert {item.url for item in dataset.sources} == {source.home_url, source.toc_url}


def test_wiley_page_rejects_incomplete_toc() -> None:
    source = publisher_source("wiley-osc7")
    payload = {
        "source_slug": source.slug,
        "home_url": source.home_url,
        "home_html": WILEY_HOME_FIXTURE.read_text(encoding="utf-8"),
        "toc_url": source.toc_url,
        "toc_html": '<div class="chapterTitle"><h3>Chapter 1: Introduction</h3></div>',
    }

    with pytest.raises(InvalidProviderResponse, match="incomplete"):
        normalize_publisher_page_response(
            payload, topic="operating-systems", retrieved_at=RETRIEVED_AT
        )


def test_unchanged_wiley_evidence_merges_without_duplicate_toc() -> None:
    source = publisher_source("wiley-osc7")
    payload = {
        "source_slug": source.slug,
        "home_url": source.home_url,
        "home_html": WILEY_HOME_FIXTURE.read_text(encoding="utf-8"),
        "toc_url": source.toc_url,
        "toc_html": WILEY_TOC_FIXTURE.read_text(encoding="utf-8"),
    }
    first = normalize_publisher_page_response(
        payload, topic="operating-systems", retrieved_at=RETRIEVED_AT
    )
    later_payload = {
        **payload,
        "home_html": payload["home_html"] + "\n",
        "toc_html": payload["toc_html"] + "\n",
    }
    later = normalize_publisher_page_response(
        later_payload,
        topic="operating-systems",
        retrieved_at=datetime(2026, 9, 13, 12, 0, tzinfo=UTC),
    )

    merged = merge_datasets([later, first])

    assert len(merged.toc) == 26
    assert len(merged.sources) == 2
    assert all(
        item.retrieved_at == datetime(2026, 9, 13, 12, 0, tzinfo=UTC) for item in merged.sources
    )
    assert merged.sources[0].content_hash == sha256_text(later_payload["home_html"])
    assert merged.sources[1].content_hash == sha256_text(later_payload["toc_html"])


def test_newer_wiley_snapshot_replaces_changed_toc_heading() -> None:
    source = publisher_source("wiley-osc7")
    payload = {
        "source_slug": source.slug,
        "home_url": source.home_url,
        "home_html": WILEY_HOME_FIXTURE.read_text(encoding="utf-8"),
        "toc_url": source.toc_url,
        "toc_html": WILEY_TOC_FIXTURE.read_text(encoding="utf-8"),
    }
    first = normalize_publisher_page_response(
        payload, topic="operating-systems", retrieved_at=RETRIEVED_AT
    )
    later_payload = {
        **payload,
        "toc_html": payload["toc_html"].replace(
            "Chapter 2: Operating-System Structures",
            "Chapter 2: Operating System Structures Revised",
        ),
    }
    later = normalize_publisher_page_response(
        later_payload,
        topic="operating-systems",
        retrieved_at=datetime(2026, 9, 13, 12, 0, tzinfo=UTC),
    )

    merged = merge_datasets([first, later])

    assert len(merged.toc) == 26
    assert merged.toc[1].title == "Operating System Structures Revised"
    assert all(entry.title != "Operating-System Structures" for entry in merged.toc)


def test_same_time_different_source_snapshots_are_rejected() -> None:
    source = publisher_source("wiley-osc7")
    payload = {
        "source_slug": source.slug,
        "home_url": source.home_url,
        "home_html": WILEY_HOME_FIXTURE.read_text(encoding="utf-8"),
        "toc_url": source.toc_url,
        "toc_html": WILEY_TOC_FIXTURE.read_text(encoding="utf-8"),
    }
    first = normalize_publisher_page_response(
        payload, topic="operating-systems", retrieved_at=RETRIEVED_AT
    )
    conflicting = normalize_publisher_page_response(
        {**payload, "toc_html": payload["toc_html"] + "\n"},
        topic="operating-systems",
        retrieved_at=RETRIEVED_AT,
    )

    with pytest.raises(DatasetMergeError, match="same retrieval time"):
        merge_datasets([first, conflicting])


def test_public_book_page_normalizes_description_and_hierarchical_toc(monkeypatch) -> None:
    source = public_book_source("ecampus-stallings-os4")
    reviewed_roots = (
        "Web Site for Operating Systems: Internals and Design Principles",
        "Preface",
        "PART ONE BACKGROUND",
        "APPENDICES",
        "Index",
    )
    fixture_spec = replace(
        source,
        expected_toc_count=12,
        expected_root_titles=reviewed_roots,
    )
    monkeypatch.setattr("data_pipeline.normalizers.public_book_source", lambda _slug: fixture_spec)
    html = ECAMPUS_FIXTURE.read_text(encoding="utf-8")

    dataset = normalize_public_book_page_response(
        {"source_slug": source.slug, "url": source.url, "html": html},
        topic="operating-systems",
        retrieved_at=RETRIEVED_AT,
    )

    assert len(dataset.documents) == 1
    assert dataset.documents[0].document_type == "description"
    assert dataset.documents[0].text.startswith("A public catalog description")
    assert len(dataset.toc) == 12
    assert (
        tuple(entry.title for entry in dataset.toc if entry.parent_entry_id is None)
        == reviewed_roots
    )
    by_title = {entry.title: entry for entry in dataset.toc}
    assert by_title["Reader's Guide"].parent_entry_id == by_title["Preface"].toc_entry_id
    assert (
        by_title["Basic Elements"].parent_entry_id
        == by_title["Computer System Overview"].toc_entry_id
    )
    assert (
        by_title["Appendix 1A Memory"].parent_entry_id
        == by_title["Computer System Overview"].toc_entry_id
    )
    assert by_title["Appendix A TCP/IP"].parent_entry_id == by_title["APPENDICES"].toc_entry_id
    assert by_title["A.1 Overview"].parent_entry_id == by_title["Appendix A TCP/IP"].toc_entry_id
    assert dataset.sources[0].source_type == "other"
    assert dataset.sources[0].content_hash == sha256_text(html)
    assert (
        validate_dataset(
            CanonicalDataset(
                books=[
                    Book(
                        book_id=source.book_id,
                        isbn_10="0130319996",
                        isbn_13=source.isbn_13,
                        title=source.title,
                        authors=["William Stallings"],
                        publisher="Prentice Hall",
                        published_year=2000,
                        language="en",
                        topics=["computer-science", "operating-systems"],
                    )
                ],
                documents=dataset.documents,
                toc=dataset.toc,
                sources=dataset.sources,
            )
        )
        == []
    )


def test_public_book_page_rejects_incomplete_toc(monkeypatch) -> None:
    source = public_book_source("ecampus-stallings-os4")
    monkeypatch.setattr(
        "data_pipeline.normalizers.public_book_source",
        lambda _slug: replace(source, expected_toc_count=13),
    )

    with pytest.raises(InvalidProviderResponse, match="entry count"):
        normalize_public_book_page_response(
            {
                "source_slug": source.slug,
                "url": source.url,
                "html": ECAMPUS_FIXTURE.read_text(encoding="utf-8"),
            },
            topic="operating-systems",
            retrieved_at=RETRIEVED_AT,
        )


def test_malformed_toc_item_does_not_change_valid_base_level(caplog) -> None:
    payload = {
        "search_response": {
            "docs": [
                {
                    "key": "/works/OL1W",
                    "title": "Linear Algebra",
                    "author_name": ["Example Author"],
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
        "edition_details": {
            "/books/OL1M": {
                "table_of_contents": [
                    {"level": 0, "title": ""},
                    {"level": 1, "label": "1", "title": "Valid Root"},
                ]
            }
        },
    }

    dataset = normalize_open_library_response(
        payload, topic="linear-algebra", limit=1, retrieved_at=RETRIEVED_AT
    )

    assert len(dataset.toc) == 1
    assert dataset.toc[0].level == 1
    assert dataset.toc[0].parent_entry_id is None
    assert "raw_index=0 reason=invalid_title_or_level" in caplog.text


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
