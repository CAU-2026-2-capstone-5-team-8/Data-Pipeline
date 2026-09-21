"""Internet Archive metadata collector.

Collects public catalog metadata (title, creator, ISBN, publisher, date, and any
provider-supplied description text) for text items via the unauthenticated
advancedsearch.php API. Never fetches item files (scans, OCR text, PDFs) -- many
Internet Archive items are controlled-digital-lending items with
"access-restricted-item": true, and this collector treats that the same as any other
item: catalog metadata only, no attempt to read the item's actual text.
"""

from typing import Any

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from data_pipeline.collectors.base import is_transient_http_error, parse_json_object
from data_pipeline.topics import topic_title_phrase

SEARCH_URL = "https://archive.org/advancedsearch.php"
SEARCH_FIELDS = (
    "identifier",
    "title",
    "creator",
    "date",
    "isbn",
    "publisher",
    "language",
    "description",
    "access-restricted-item",
)


class InternetArchiveCollector:
    def __init__(self, client: httpx.Client | None = None) -> None:
        self._owns_client = client is None
        self.client = client or httpx.Client(
            timeout=httpx.Timeout(20.0),
            headers={"User-Agent": "cau-capstone-data-pipeline/0.1 (metadata research)"},
        )

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def __enter__(self) -> "InternetArchiveCollector":
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
        """Search public text items whose title matches one supported topic."""
        parameters = self.search_parameters(topic, candidate_limit)
        response = self.client.get(SEARCH_URL, params=parameters)
        response.raise_for_status()
        return parse_json_object(response, "internet-archive")

    @staticmethod
    def search_parameters(topic: str, candidate_limit: int) -> dict[str, Any]:
        """Return the exact public API parameters used for a topic search."""
        if candidate_limit < 1:
            raise ValueError("candidate_limit must be at least 1")
        title = topic_title_phrase(topic)
        return {
            "q": f'title:"{title}" AND mediatype:(texts)',
            "fl[]": list(SEARCH_FIELDS),
            "rows": min(candidate_limit, 100),
            "page": 1,
            "output": "json",
        }
