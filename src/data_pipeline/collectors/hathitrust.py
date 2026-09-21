"""HathiTrust Bibliographic API collector.

ISBN-keyed catalog lookup only -- HathiTrust's free Bibliographic API has no
topic/subject search, and returns no full text or table of contents (only
whether an item exists, its rights status, and catalog identifiers such as
OCLC/LCCN). This collector corroborates the bibliographic identity of a book
already in the canonical dataset; it never discovers new books.
"""

from typing import Any

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from data_pipeline.collectors.base import is_transient_http_error, parse_json_object

API_URL = "https://catalog.hathitrust.org/api/volumes/brief/json/isbn"


class HathiTrustCollector:
    def __init__(self, client: httpx.Client | None = None) -> None:
        self._owns_client = client is None
        self.client = client or httpx.Client(
            timeout=httpx.Timeout(20.0),
            headers={"User-Agent": "cau-capstone-data-pipeline/0.1 (metadata research)"},
        )

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def __enter__(self) -> "HathiTrustCollector":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    @retry(
        retry=retry_if_exception(is_transient_http_error),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
        reraise=True,
    )
    def lookup_isbn(self, isbn: str) -> dict[str, Any]:
        """Look up one ISBN's HathiTrust catalog records and holdings."""
        response = self.client.get(f"{API_URL}:{isbn}")
        response.raise_for_status()
        return parse_json_object(response, "hathitrust")
