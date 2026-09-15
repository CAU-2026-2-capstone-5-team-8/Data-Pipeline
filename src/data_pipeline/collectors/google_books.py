"""Small, polite Google Books API metadata collector."""

from typing import Any

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from data_pipeline.collectors.base import (
    InvalidProviderResponse,
    is_transient_http_error,
    parse_json_object,
)

API_URL = "https://www.googleapis.com/books/v1/volumes"
MAX_PAGE_SIZE = 40
TOPIC_QUERIES = {
    "operating-systems": 'subject:"Operating systems"',
    "linear-algebra": 'subject:"Linear algebra"',
}


class GoogleBooksCollector:
    def __init__(self, client: httpx.Client | None = None) -> None:
        """Create a collector with an optional injected client for deterministic tests."""
        self._owns_client = client is None
        self.client = client or httpx.Client(
            timeout=httpx.Timeout(20.0),
            headers={"User-Agent": "cau-capstone-data-pipeline/0.1"},
        )

    def close(self) -> None:
        """Close the internally owned HTTP client."""
        if self._owns_client:
            self.client.close()

    def __enter__(self) -> "GoogleBooksCollector":
        """Return this collector as a context-managed resource."""
        return self

    def __exit__(self, *_args: object) -> None:
        """Close resources when leaving a context manager."""
        self.close()

    @retry(
        retry=retry_if_exception(is_transient_http_error),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
        reraise=True,
    )
    def _fetch_page(self, parameters: dict[str, Any]) -> dict[str, Any]:
        """Fetch and decode one independently retried Google Books result page."""
        response = self.client.get(API_URL, params=parameters)
        response.raise_for_status()
        return parse_json_object(response, "google-books")

    def search_books(self, topic: str, candidate_limit: int = 20) -> dict[str, Any]:
        """Fetch bounded pages and preserve each response with its exact request parameters."""
        plan = self.search_parameters(topic, candidate_limit)
        pages: list[dict[str, Any]] = []
        collected_count = 0
        for parameters in plan["pages"]:
            try:
                response = self._fetch_page(parameters)
            except httpx.HTTPError as exc:
                start_index = parameters["startIndex"]
                raise InvalidProviderResponse(
                    f"google-books page failed at startIndex={start_index}: {exc}"
                ) from exc
            items = response.get("items", [])
            if not isinstance(items, list):
                raise InvalidProviderResponse(
                    "google-books returned an invalid 'items' collection; expected a list"
                )
            pages.append({"request_parameters": parameters, "response": response})
            collected_count += len(items)
            total_items = response.get("totalItems")
            reached_total = (
                isinstance(total_items, int)
                and not isinstance(total_items, bool)
                and collected_count >= total_items
            )
            if len(items) < parameters["maxResults"] or reached_total:
                break
        return {"pages": pages}

    @staticmethod
    def search_parameters(topic: str, candidate_limit: int) -> dict[str, Any]:
        """Return the exact ordered page requests for one bounded search."""
        if candidate_limit < 1:
            raise ValueError("candidate_limit must be at least 1")
        try:
            query = TOPIC_QUERIES[topic]
        except KeyError as exc:
            raise ValueError(f"unsupported topic: {topic}") from exc
        pages = []
        for start_index in range(0, candidate_limit, MAX_PAGE_SIZE):
            pages.append(
                {
                    "q": query,
                    "langRestrict": "en",
                    "maxResults": min(MAX_PAGE_SIZE, candidate_limit - start_index),
                    "orderBy": "relevance",
                    "printType": "books",
                    "startIndex": start_index,
                }
            )
        return {"pages": pages}
