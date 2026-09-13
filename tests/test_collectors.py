import httpx
import pytest

from data_pipeline.collectors.base import InvalidProviderResponse
from data_pipeline.collectors.google_books import GoogleBooksCollector
from data_pipeline.collectors.open_library import OpenLibraryCollector


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
