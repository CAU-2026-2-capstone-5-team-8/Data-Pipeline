import httpx
import pytest

from data_pipeline.collectors.base import InvalidProviderResponse
from data_pipeline.collectors.google_books import GoogleBooksCollector
from data_pipeline.collectors.internet_archive import InternetArchiveCollector
from data_pipeline.collectors.open_library import OpenLibraryCollector
from data_pipeline.collectors.public_book_pages import PublicBookPageCollector
from data_pipeline.collectors.publisher_documents import PublisherDocumentCollector
from data_pipeline.collectors.publisher_pages import PublisherPageCollector
from data_pipeline.public_book_sources import public_book_source
from data_pipeline.publisher_document_sources import publisher_document_source
from data_pipeline.publisher_sources import publisher_source


def _google_item(index: int) -> dict:
    return {
        "id": f"volume-{index}",
        "volumeInfo": {
            "title": f"Book {index}",
            "authors": [f"Author {index}"],
            "language": "en",
        },
    }


@pytest.mark.parametrize(
    "collector_class", [GoogleBooksCollector, OpenLibraryCollector, InternetArchiveCollector]
)
def test_collector_reports_malformed_success_response(collector_class) -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, text="not-json", request=request)
    )
    with httpx.Client(transport=transport) as client:
        collector = collector_class(client=client)

        with pytest.raises(InvalidProviderResponse, match="malformed JSON"):
            collector.search_books("operating-systems", candidate_limit=5)


@pytest.mark.parametrize(
    ("candidate_limit", "expected_page_sizes"),
    [
        (25, [25]),
        (40, [40]),
        (41, [40, 1]),
        (50, [40, 10]),
        (100, [40, 40, 20]),
    ],
)
def test_google_books_paginates_with_bounded_page_sizes(
    candidate_limit, expected_page_sizes
) -> None:
    requested: list[tuple[int, int]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        start_index = int(request.url.params["startIndex"])
        page_size = int(request.url.params["maxResults"])
        requested.append((start_index, page_size))
        return httpx.Response(
            200,
            json={
                "totalItems": 500,
                "items": [
                    _google_item(index) for index in range(start_index, start_index + page_size)
                ],
            },
            request=request,
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        payload = GoogleBooksCollector(client=client).search_books(
            "operating-systems", candidate_limit=candidate_limit
        )

    assert requested == [
        (start_index, page_size)
        for start_index, page_size in zip(
            range(0, candidate_limit, 40), expected_page_sizes, strict=True
        )
    ]
    assert [page["request_parameters"]["maxResults"] for page in payload["pages"]] == (
        expected_page_sizes
    )


def test_google_books_continues_after_a_short_page_when_total_items_remain() -> None:
    requested_start_indexes = []

    def handler(request: httpx.Request) -> httpx.Response:
        start_index = int(request.url.params["startIndex"])
        requested_start_indexes.append(start_index)
        item_count = 40 if start_index == 0 else 7
        return httpx.Response(
            200,
            json={
                "totalItems": 100,
                "items": [
                    _google_item(index) for index in range(start_index, start_index + item_count)
                ],
            },
            request=request,
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        payload = GoogleBooksCollector(client=client).search_books(
            "linear-algebra", candidate_limit=100
        )

    assert requested_start_indexes == [0, 40, 80]
    assert [len(page["response"]["items"]) for page in payload["pages"]] == [40, 7, 7]


def test_google_books_stops_after_a_short_final_page() -> None:
    requested_start_indexes = []

    def handler(request: httpx.Request) -> httpx.Response:
        start_index = int(request.url.params["startIndex"])
        requested_start_indexes.append(start_index)
        item_count = 40 if start_index == 0 else 7
        return httpx.Response(
            200,
            json={
                "totalItems": 47,
                "items": [
                    _google_item(index) for index in range(start_index, start_index + item_count)
                ],
            },
            request=request,
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        payload = GoogleBooksCollector(client=client).search_books(
            "linear-algebra", candidate_limit=100
        )

    assert requested_start_indexes == [0, 40]
    assert [len(page["response"]["items"]) for page in payload["pages"]] == [40, 7]


def test_google_books_reports_middle_page_failure() -> None:
    requested_start_indexes = []

    def handler(request: httpx.Request) -> httpx.Response:
        start_index = int(request.url.params["startIndex"])
        requested_start_indexes.append(start_index)
        if start_index == 40:
            return httpx.Response(400, text="bad page", request=request)
        return httpx.Response(
            200,
            json={"totalItems": 50, "items": [_google_item(index) for index in range(40)]},
            request=request,
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        collector = GoogleBooksCollector(client=client)
        with pytest.raises(InvalidProviderResponse, match="startIndex=40"):
            collector.search_books("operating-systems", candidate_limit=50)

    assert requested_start_indexes == [0, 40]


def test_open_library_fetches_bounded_english_edition_details() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"key": "/books/OL1M", "by_statement": "by First Author, Second Author."},
            request=request,
        )

    response = {
        "docs": [
            {
                "editions": {
                    "docs": [
                        {"key": "/books/OL1M", "language": ["eng"]},
                        {"key": "/books/OL2M", "language": ["spa"]},
                    ]
                }
            }
        ]
    }
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        collector = OpenLibraryCollector(client=client)
        details = collector.fetch_edition_details(response, candidate_limit=1)

    assert details["/books/OL1M"]["by_statement"].startswith("by First Author")


def test_open_library_fetches_bounded_work_details() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"key": "/works/OL1W", "description": "Public description"},
            request=request,
        )

    response = {
        "docs": [
            {"key": "/works/OL1W"},
            {"key": "invalid-work-key"},
        ]
    }
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        collector = OpenLibraryCollector(client=client)
        details = collector.fetch_work_details(response, candidate_limit=2)

    assert details == {"/works/OL1W": {"key": "/works/OL1W", "description": "Public description"}}


def test_publisher_collector_fetches_only_allowlisted_pages() -> None:
    source = publisher_source("wiley-osc7")
    requested_urls = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        return httpx.Response(
            200,
            text="<html><body>Public publisher page</body></html>",
            headers={"content-type": "text/html; charset=utf-8"},
            request=request,
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        collector = PublisherPageCollector(client=client)
        payload = collector.fetch("wiley-osc7")

    assert requested_urls == [source.home_url, source.toc_url]
    assert payload["source_slug"] == source.slug
    assert payload["home_html"].startswith("<html>")


def test_publisher_collector_rejects_non_html_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b"not html",
            headers={"content-type": "application/octet-stream"},
            request=request,
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        collector = PublisherPageCollector(client=client)

        with pytest.raises(InvalidProviderResponse, match="content type"):
            collector.fetch("wiley-osc7")


def test_publisher_collector_does_not_follow_redirects() -> None:
    requested_urls = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        return httpx.Response(
            302,
            headers={"location": "https://unreviewed.example.test/page"},
            request=request,
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        collector = PublisherPageCollector(client=client)

        with pytest.raises(InvalidProviderResponse, match="unapproved redirect"):
            collector.fetch("wiley-osc7")

    assert len(requested_urls) == 1


def test_publisher_document_collector_preserves_identity_link_and_pdf() -> None:
    source = publisher_document_source("wiley-osc7-appendix-b")
    requested_urls = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        if str(request.url) == source.document_url:
            return httpx.Response(
                200,
                content=b"%PDF-1.3 synthetic fixture",
                headers={"content-type": "application/pdf"},
                request=request,
            )
        return httpx.Response(
            200,
            text="<html><body>Publisher evidence</body></html>",
            headers={"content-type": "text/html; charset=utf-8"},
            request=request,
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        collector = PublisherDocumentCollector(client=client)
        payload = collector.fetch(source.slug)

    assert requested_urls == [source.home_url, source.referrer_url, source.document_url]
    assert payload["source_slug"] == source.slug
    assert payload["document_media_type"] == "application/pdf"
    assert payload["document_base64"] == "JVBERi0xLjMgc3ludGhldGljIGZpeHR1cmU="


def test_publisher_document_collector_rejects_non_pdf_content() -> None:
    source = publisher_document_source("wiley-osc7-appendix-b")

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == source.document_url:
            return httpx.Response(
                200,
                content=b"not a PDF",
                headers={"content-type": "application/pdf"},
                request=request,
            )
        return httpx.Response(
            200,
            text="<html></html>",
            headers={"content-type": "text/html"},
            request=request,
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        collector = PublisherDocumentCollector(client=client)

        with pytest.raises(InvalidProviderResponse, match="not a PDF"):
            collector.fetch(source.slug)


def test_public_book_collector_fetches_only_allowlisted_page() -> None:
    source = public_book_source("ecampus-stallings-os4")
    requested_urls = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        return httpx.Response(
            200,
            text="<html><body>Public catalog page</body></html>",
            headers={"content-type": "text/html; charset=utf-8"},
            request=request,
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        collector = PublicBookPageCollector(client=client)
        payload = collector.fetch(source.slug)

    assert requested_urls == [source.url]
    assert payload == {
        "source_slug": source.slug,
        "url": source.url,
        "html": "<html><body>Public catalog page</body></html>",
    }


def test_public_book_collector_rejects_redirects() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            302,
            headers={"location": "https://unreviewed.example.test/page"},
            request=request,
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        collector = PublicBookPageCollector(client=client)

        with pytest.raises(InvalidProviderResponse, match="unapproved redirect"):
            collector.fetch("ecampus-stallings-os4")
