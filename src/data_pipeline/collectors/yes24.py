"""YES24 Open API table-of-contents collector.

ISBN-13-keyed lookup only. The pipeline never uses YES24 search or bestseller
listings to discover books: YES24's terms prohibit accumulating its catalog into
a separate database, so this collector only enriches books that are already in
the canonical dataset, one exact ISBN at a time.
"""

import time
from typing import Any

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from data_pipeline.collectors.base import is_transient_http_error, parse_json_object

API_URL = "https://apis.yes24.com/v1/goods/content"
API_KEY_ENV = "YES24_API_KEY"
MIN_REQUEST_INTERVAL_SECONDS = 0.25


class Yes24Collector:
    def __init__(self, api_key: str, client: httpx.Client | None = None) -> None:
        if not api_key:
            raise ValueError(f"{API_KEY_ENV} is not set")
        self._owns_client = client is None
        self.client = client or httpx.Client(
            timeout=httpx.Timeout(20.0),
            headers={"User-Agent": "cau-capstone-data-pipeline/0.1 (metadata research)"},
        )
        self._api_key = api_key
        self._last_request_at: float | None = None

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def __enter__(self) -> "Yes24Collector":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    @staticmethod
    def request_parameters(isbn_13: str) -> dict[str, str]:
        """Return the exact query sent for one ISBN; the API key is never part of it."""
        return {"searchType": "ISBN13", "query": isbn_13}

    def _wait_for_rate_limit(self) -> None:
        if self._last_request_at is not None:
            elapsed = time.monotonic() - self._last_request_at
            if elapsed < MIN_REQUEST_INTERVAL_SECONDS:
                time.sleep(MIN_REQUEST_INTERVAL_SECONDS - elapsed)
        self._last_request_at = time.monotonic()

    @retry(
        retry=retry_if_exception(is_transient_http_error),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
        reraise=True,
    )
    def fetch_toc(self, isbn_13: str) -> dict[str, Any]:
        """Fetch one book's TOC; a "product not found" answer is returned, not raised."""
        self._wait_for_rate_limit()
        response = self.client.get(
            API_URL,
            params=self.request_parameters(isbn_13),
            headers={"X-Api-Key": self._api_key},
        )
        if response.status_code == 404:
            payload = parse_json_object(response, "yes24")
            if payload.get("success") is False:
                return payload
        response.raise_for_status()
        return parse_json_object(response, "yes24")
