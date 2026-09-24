"""Springer Nature Metadata API chapter-list collector.

ISBN-keyed lookup only. The API matches ``isbn:`` queries only in hyphenated
form, and page sizes above 25 or title/subject searches are premium features for
the key this project has, so this collector pages through one exact ISBN's
chapter records and never searches.
"""

import time
from typing import Any

import httpx
import isbnlib
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from data_pipeline.collectors.base import (
    InvalidProviderResponse,
    is_transient_http_error,
    parse_json_object,
)

API_URL = "https://api.springernature.com/meta/v2/json"
API_KEY_ENV = "SPRINGER_API_KEY"
PAGE_SIZE = 25
MAX_PAGES = 8
MIN_REQUEST_INTERVAL_SECONDS = 0.5


def hyphenated_isbn(isbn: str) -> str:
    """Return the registration-group hyphenation Springer's ``isbn:`` query requires."""
    masked = isbnlib.mask(isbn)
    if not masked:
        raise ValueError(f"cannot hyphenate ISBN {isbn}")
    return masked


class SpringerMetadataCollector:
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

    def __enter__(self) -> "SpringerMetadataCollector":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

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
    def _fetch_page(self, parameters: dict[str, Any]) -> dict[str, Any] | None:
        """Fetch one page; Springer answers an unmatched query with HTTP 404."""
        self._wait_for_rate_limit()
        response = self.client.get(API_URL, params={**parameters, "api_key": self._api_key})
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return parse_json_object(response, "springer-metadata")

    def fetch_chapters(self, isbn: str) -> dict[str, Any]:
        """Page through every record for one ISBN, keeping the key out of the raw parameters."""
        query = f"isbn:{hyphenated_isbn(isbn)}"
        pages: list[dict[str, Any]] = []
        for page_index in range(MAX_PAGES):
            parameters = {"q": query, "p": PAGE_SIZE, "s": page_index * PAGE_SIZE + 1}
            response = self._fetch_page(parameters)
            if response is None:
                break
            records = response.get("records")
            if not isinstance(records, list):
                raise InvalidProviderResponse(
                    "springer-metadata returned an invalid 'records' collection"
                )
            pages.append({"request_parameters": parameters, "response": response})
            total = _total_records(response)
            if not records or total is None or (page_index + 1) * PAGE_SIZE >= total:
                break
        return {"query": query, "pages": pages}


def _total_records(response: dict[str, Any]) -> int | None:
    result = response.get("result")
    if not isinstance(result, list) or not result or not isinstance(result[0], dict):
        return None
    try:
        return int(result[0].get("total"))
    except (TypeError, ValueError):
        return None
