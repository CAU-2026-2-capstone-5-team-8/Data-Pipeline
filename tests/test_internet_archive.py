from datetime import UTC, datetime

import httpx
import pytest

from data_pipeline.collectors.base import InvalidProviderResponse
from data_pipeline.collectors.internet_archive import InternetArchiveCollector
from data_pipeline.diagnostics import NormalizationDiagnostics
from data_pipeline.normalizers import normalize_internet_archive_response

RETRIEVED_AT = datetime(2026, 9, 21, 12, 0, tzinfo=UTC)


def _record(**overrides: object) -> dict:
    record = {
        "identifier": "operatingsystems0000katz",
        "title": "Operating systems : a pragmatic approach",
        "creator": "Katzan, Harry",
        "date": "1986-01-01T00:00:00Z",
        "isbn": "0442247389",
        "publisher": "New York : Van Nostrand Reinhold",
        "language": "eng",
        "description": ["xii, 449 p. : 24 cm", "Bibliography: p. 421-432"],
    }
    record.update(overrides)
    return record


def _response(*docs: dict) -> dict:
    return {
        "responseHeader": {"status": 0, "params": {}},
        "response": {"numFound": len(docs), "start": 0, "docs": list(docs)},
    }


# --- Collector ---------------------------------------------------------------


def test_search_parameters_builds_phrase_query_with_mediatype_filter() -> None:
    parameters = InternetArchiveCollector.search_parameters("operating-systems", 5)

    assert parameters["q"] == 'title:"operating systems" AND mediatype:(texts)'
    assert parameters["fl[]"] == [
        "identifier",
        "title",
        "creator",
        "date",
        "isbn",
        "publisher",
        "language",
        "description",
        "access-restricted-item",
    ]
    assert parameters["rows"] == 5
    assert parameters["output"] == "json"


def test_search_parameters_caps_rows_at_one_hundred() -> None:
    parameters = InternetArchiveCollector.search_parameters("linear-algebra", 500)
    assert parameters["rows"] == 100


def test_search_parameters_rejects_non_positive_candidate_limit() -> None:
    with pytest.raises(ValueError, match="candidate_limit"):
        InternetArchiveCollector.search_parameters("operating-systems", 0)


def test_search_books_sends_the_planned_request_and_returns_the_raw_response() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json=_response(_record()), request=request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        payload = InternetArchiveCollector(client=client).search_books(
            "operating-systems", candidate_limit=5
        )

    assert len(captured) == 1
    assert captured[0].url.params["rows"] == "5"
    assert captured[0].url.params.get_list("fl[]") == list(
        InternetArchiveCollector.search_parameters("operating-systems", 5)["fl[]"]
    )
    assert payload["response"]["docs"][0]["identifier"] == "operatingsystems0000katz"


# --- Normalizer ----------------------------------------------------------------


def test_normalize_preserves_identity_and_description() -> None:
    dataset = normalize_internet_archive_response(
        _response(_record()), topic="operating-systems", limit=5, retrieved_at=RETRIEVED_AT
    )

    assert len(dataset.books) == 1
    book = dataset.books[0]
    assert book.book_id == "isbn10:0442247389"
    assert book.title == "Operating systems : a pragmatic approach"
    assert book.authors == ["Katzan, Harry"]
    assert book.publisher == "New York : Van Nostrand Reinhold"
    assert book.published_year == 1986
    assert book.topics == ["computer-science", "operating-systems"]

    assert len(dataset.sources) == 1
    source = dataset.sources[0]
    assert source.provider == "internet_archive"
    assert source.source_type == "metadata_api"
    assert source.url == "https://archive.org/details/operatingsystems0000katz"
    assert source.license is None
    assert source.rights_note is None

    assert len(dataset.documents) == 1
    document = dataset.documents[0]
    assert document.document_type == "description"
    assert document.text == "xii, 449 p. : 24 cm\n\nBibliography: p. 421-432"
    assert document.source_id == source.source_id
    assert dataset.toc == []


def test_normalize_does_not_split_a_single_creator_name_on_comma() -> None:
    """`"Last, First"` is one author string, not a citation list like OL's by_statement."""
    dataset = normalize_internet_archive_response(
        _response(_record(creator="Schröder-Preikschat, W. (Wolfgang)")),
        topic="operating-systems",
        limit=5,
        retrieved_at=RETRIEVED_AT,
    )

    assert dataset.books[0].authors == ["Schröder-Preikschat, W. (Wolfgang)"]


def test_normalize_accepts_list_shaped_creator_isbn_and_description() -> None:
    dataset = normalize_internet_archive_response(
        _response(
            _record(
                creator=["Ann McIver McHoes", "Ida M. Flynn"],
                isbn=["9781439080115", "1439080119"],
                description="single scalar description",
            )
        ),
        topic="operating-systems",
        limit=5,
        retrieved_at=RETRIEVED_AT,
    )

    book = dataset.books[0]
    assert book.authors == ["Ann McIver McHoes", "Ida M. Flynn"]
    assert book.isbn_13 == "9781439080115"
    assert book.isbn_10 == "1439080119"
    assert book.book_id == "isbn13:9781439080115"
    assert dataset.documents[0].text == "single scalar description"


def test_normalize_does_not_combine_isbns_from_different_editions() -> None:
    dataset = normalize_internet_archive_response(
        _response(_record(isbn=["9781439080115", "0442247389"])),
        topic="operating-systems",
        limit=5,
        retrieved_at=RETRIEVED_AT,
    )

    book = dataset.books[0]
    assert book.isbn_13 == "9781439080115"
    assert book.isbn_10 is None
    assert book.book_id == "isbn13:9781439080115"


def test_normalize_accepts_list_shaped_language() -> None:
    dataset = normalize_internet_archive_response(
        _response(_record(language=["eng", "ger"])),
        topic="operating-systems",
        limit=5,
        retrieved_at=RETRIEVED_AT,
    )

    assert len(dataset.books) == 1


@pytest.mark.parametrize("language", ["fre", "", "spa"])
def test_normalize_skips_non_english_items(language: str) -> None:
    dataset = normalize_internet_archive_response(
        _response(_record(language=language)),
        topic="operating-systems",
        limit=5,
        retrieved_at=RETRIEVED_AT,
    )
    assert dataset.books == []


@pytest.mark.parametrize(
    "overrides",
    [
        {"identifier": ""},
        {"identifier": None},
        {"identifier": ["unexpected"]},
        {"title": ""},
        {"title": None},
        {"title": {"unexpected": "shape"}},
    ],
)
def test_normalize_requires_identifier_and_title(overrides: dict) -> None:
    dataset = normalize_internet_archive_response(
        _response(_record(**overrides)),
        topic="operating-systems",
        limit=5,
        retrieved_at=RETRIEVED_AT,
    )
    assert dataset.books == []


def test_normalize_records_access_restricted_rights_note_without_inventing_a_license() -> None:
    dataset = normalize_internet_archive_response(
        _response(_record(**{"access-restricted-item": "true"})),
        topic="operating-systems",
        limit=5,
        retrieved_at=RETRIEVED_AT,
    )

    source = dataset.sources[0]
    assert source.license is None
    assert source.rights_note is not None
    assert "controlled-digital-lending" in source.rights_note


def test_normalize_fallback_book_id_is_deterministic_without_isbn() -> None:
    first = normalize_internet_archive_response(
        _response(_record(identifier="copy-one", isbn=None)),
        topic="operating-systems",
        limit=5,
        retrieved_at=RETRIEVED_AT,
    )
    second = normalize_internet_archive_response(
        _response(_record(identifier="copy-two", isbn=None)),
        topic="operating-systems",
        limit=5,
        retrieved_at=RETRIEVED_AT,
    )

    assert first.books[0].book_id == second.books[0].book_id
    assert first.books[0].book_id.startswith("book_")


def test_normalize_deduplicates_same_book_id_across_items() -> None:
    diagnostics = NormalizationDiagnostics(provider="internet_archive")
    dataset = normalize_internet_archive_response(
        _response(
            _record(identifier="scan-a"),
            _record(identifier="scan-b"),
        ),
        topic="operating-systems",
        limit=5,
        retrieved_at=RETRIEVED_AT,
        diagnostics=diagnostics,
    )

    assert len(dataset.books) == 1
    assert diagnostics.duplicate_candidate_count == 1
    assert diagnostics.candidate_count == 2


def test_normalize_rejects_unsupported_topic() -> None:
    with pytest.raises(ValueError, match="unsupported topic"):
        normalize_internet_archive_response(
            _response(_record()), topic="astrophysics", limit=5, retrieved_at=RETRIEVED_AT
        )


def test_normalize_requires_a_response_object() -> None:
    with pytest.raises(InvalidProviderResponse, match="response"):
        normalize_internet_archive_response(
            {"response": "not-an-object"},
            topic="operating-systems",
            limit=5,
            retrieved_at=RETRIEVED_AT,
        )


def test_normalize_requires_docs_to_be_a_list() -> None:
    with pytest.raises(InvalidProviderResponse, match="docs"):
        normalize_internet_archive_response(
            {"response": {"docs": {}}},
            topic="operating-systems",
            limit=5,
            retrieved_at=RETRIEVED_AT,
        )
