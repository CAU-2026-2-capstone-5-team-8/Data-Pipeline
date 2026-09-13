"""Open Library Search API metadata collector."""

from typing import Any

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from data_pipeline.collectors.base import parse_json_object
from data_pipeline.collectors.google_books import is_transient_http_error

API_URL = "https://openlibrary.org/search.json"
TOPIC_TITLES = {
    "operating-systems": "operating systems",
    "linear-algebra": "linear algebra",
}
FIELDS = ",".join(
    [
        "key",
        "title",
        "author_name",
        "first_publish_year",
        "language",
        "editions",
        "editions.key",
        "editions.title",
        "editions.subtitle",
        "editions.isbn",
        "editions.publisher",
        "editions.publish_date",
        "editions.language",
    ]
)


class OpenLibraryCollector:
    def __init__(self, client: httpx.Client | None = None) -> None:
        self._owns_client = client is None
        self.client = client or httpx.Client(
            timeout=httpx.Timeout(20.0),
            headers={"User-Agent": "cau-capstone-data-pipeline/0.1 (metadata research)"},
        )

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def __enter__(self) -> "OpenLibraryCollector":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    @retry(
        retry=retry_if_exception(is_transient_http_error),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
        reraise=True,
    )
    def search_books(self, topic: str, candidate_limit: int = 20) -> dict[str, Any]:
        """Search English editions for one supported topic."""
        response = self.client.get(API_URL, params=self.search_parameters(topic, candidate_limit))
        response.raise_for_status()
        return parse_json_object(response, "open-library")

    @staticmethod
    def search_parameters(topic: str, candidate_limit: int) -> dict[str, Any]:
        """Return the exact public API parameters used for a topic search."""
        try:
            title = TOPIC_TITLES[topic]
        except KeyError as exc:
            raise ValueError(f"unsupported topic: {topic}") from exc
        return {
            "title": title,
            "language": "eng",
            "fields": FIELDS,
            "limit": min(candidate_limit, 100),
        }
