"""Open Library metadata collector."""

import logging
import time
from typing import Any

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from data_pipeline.collectors.base import (
    InvalidProviderResponse,
    is_transient_http_error,
    parse_json_object,
)

API_URL = "https://openlibrary.org/search.json"
BASE_URL = "https://openlibrary.org"
logger = logging.getLogger(__name__)
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

    @retry(
        retry=retry_if_exception(is_transient_http_error),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
        reraise=True,
    )
    def fetch_edition(self, edition_key: str) -> dict[str, Any]:
        """Fetch one public edition record for higher-quality bibliographic evidence."""
        response = self.client.get(f"{BASE_URL}{edition_key}.json")
        response.raise_for_status()
        return parse_json_object(response, "open-library")

    def fetch_edition_details(
        self, search_response: dict[str, Any], candidate_limit: int
    ) -> dict[str, dict[str, Any]]:
        """Fetch a bounded set of English edition records without failing the whole search."""
        details: dict[str, dict[str, Any]] = {}
        records = search_response.get("docs", [])
        if not isinstance(records, list):
            return details

        for record in records[:candidate_limit]:
            if not isinstance(record, dict):
                continue
            edition_container = record.get("editions")
            if not isinstance(edition_container, dict):
                continue
            edition_records = edition_container.get("docs")
            if not isinstance(edition_records, list):
                continue
            edition = next(
                (
                    item
                    for item in edition_records
                    if isinstance(item, dict) and "eng" in _string_list(item.get("language"))
                ),
                None,
            )
            if edition is None:
                continue
            edition_key = str(edition.get("key", "")).strip()
            if not edition_key.startswith("/books/"):
                continue
            try:
                details[edition_key] = self.fetch_edition(edition_key)
            except (httpx.HTTPError, InvalidProviderResponse) as exc:
                logger.warning(
                    "event=edition_detail_fetch_failed provider=open_library "
                    "edition_key=%s error=%s",
                    edition_key,
                    exc,
                )
            time.sleep(0.1)
        return details

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


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]
