import httpx
import pytest

from data_pipeline.collectors.base import InvalidProviderResponse
from data_pipeline.collectors.google_books import GoogleBooksCollector
from data_pipeline.collectors.open_library import OpenLibraryCollector
from data_pipeline.collectors.public_book_pages import PublicBookPageCollector
from data_pipeline.collectors.publisher_pages import PublisherPageCollector
from data_pipeline.public_book_sources import public_book_source
from data_pipeline.publisher_sources import publisher_source


@pytest.mark.parametrize("collector_class", [GoogleBooksCollector, OpenLibraryCollector])
def test_collector_reports_malformed_success_response(collector_class) -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, text="not-json", request=request)
    )
    with httpx.Client(transport=transport) as client:
        collector = collector_class(client=client)

        with pytest.raises(InvalidProviderResponse, match="malformed JSON"):
            collector.search_books("operating-systems", candidate_limit=5)


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
