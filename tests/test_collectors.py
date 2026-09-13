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
