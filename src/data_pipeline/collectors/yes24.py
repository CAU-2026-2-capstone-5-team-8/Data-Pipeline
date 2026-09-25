"""YES24 Open API collector.

Book-specialty online bookstore API. Two uses share this client:

* `search_books` -- topic discovery through `/v1/goods/itemList` (the `yes24`
  provider of `collect`). It also marks whether a listing is a translated edition
  (`originalTranslation`/`originalTitle`), which this project treats as a
  first-class fact rather than something to normalize away -- see AGENTS.md's
  language-scope note.
* `fetch_toc` -- exact ISBN-13 lookup of one canonical book's table of contents
  (`enrich-api-toc`). It never discovers books.

YES24's terms prohibit accumulating its catalog into a separate database, so
discovery results must stay topic-scoped.

Requires an API key issued at https://developers.yes24.com, sent as the
`X-Api-Key` header. Rate limit per the published OpenAPI spec: 5 requests/sec,
5,000 requests/day.
"""

import os
import time
from typing import Any

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from data_pipeline.collectors.base import is_transient_http_error, parse_json_object
from data_pipeline.topics import topic_korean_query

ITEM_LIST_URL = "https://apis.yes24.com/v1/goods/itemList"
CONTENT_URL = "https://apis.yes24.com/v1/goods/content"
# Live-verified: pageSize=1000 returns whatever the true result count is (e.g. 976
# for "algorithms") with no error -- the API has no page-size wall in this range.
# This cap is a defensive ceiling, not a discovered API limit; it sits comfortably
# above the largest candidate_limit the CLI can ever request (100-book limit * 4).
MAX_PAGE_SIZE = 1000
API_URL = CONTENT_URL
API_KEY_ENV = "YES24_API_KEY"
MIN_REQUEST_INTERVAL_SECONDS = 0.25


class MissingApiKey(ValueError):
    """Raised when YES24_API_KEY is not set."""


class Yes24Collector:
    def __init__(self, api_key: str | None = None, client: httpx.Client | None = None) -> None:
        key = os.environ.get(API_KEY_ENV) if api_key is None else api_key
        if not key:
            raise MissingApiKey(f"{API_KEY_ENV} is not set (see .env.example)")
        # Sent per-request rather than as a client default header, so the key is
        # never silently dropped when a caller (e.g. a test) supplies its own client.
        self._auth_headers = {"X-Api-Key": key}
        self._owns_client = client is None
        self.client = client or httpx.Client(
            timeout=httpx.Timeout(20.0),
            headers={"User-Agent": "cau-capstone-data-pipeline/0.1 (metadata research)"},
        )
        self._last_request_at: float | None = None

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def __enter__(self) -> "Yes24Collector":
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
        """Search YES24's domestic book catalog for one supported topic.

        A query with zero matches is a normal outcome (HTTP 404, errorCode
        SEARCH_001), not a failure; this returns an empty item list for it
        rather than raising.
        """
        if candidate_limit < 1:
            raise ValueError("candidate_limit must be at least 1")
        self._wait_for_rate_limit()
        response = self.client.get(
            ITEM_LIST_URL,
            params={
                "query": topic_korean_query(topic),
                "category": "BOOK",
                "detail": "Y",
                "pageSize": min(candidate_limit, MAX_PAGE_SIZE),
            },
            headers=self._auth_headers,
        )
        payload = _not_found_as_empty(response, empty_key="items")
        if payload is not None:
            return payload
        response.raise_for_status()
        return parse_json_object(response, "yes24")

    @staticmethod
    def search_parameters(topic: str, candidate_limit: int) -> dict[str, Any]:
        """Return the exact public API parameters used for a topic search."""
        if candidate_limit < 1:
            raise ValueError("candidate_limit must be at least 1")
        return {
            "query": topic_korean_query(topic),
            "category": "BOOK",
            "detail": "Y",
            "pageSize": min(candidate_limit, MAX_PAGE_SIZE),
        }

    @retry(
        retry=retry_if_exception(is_transient_http_error),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
        reraise=True,
    )
    def fetch_content(self, isbn13: str) -> dict[str, Any]:
        """Fetch the raw table-of-contents blob for one ISBN13.

        No listed content (HTTP 404, errorCode GOODS_001/GOODS_002) is a normal
        outcome, not a failure; this returns a payload with `data: None` for it
        rather than raising.
        """
        self._wait_for_rate_limit()
        response = self.client.get(
            CONTENT_URL,
            params={"searchType": "ISBN13", "query": isbn13},
            headers=self._auth_headers,
        )
        payload = _not_found_as_empty(response, empty_key=None)
        if payload is not None:
            return payload
        response.raise_for_status()
        return parse_json_object(response, "yes24")

    @staticmethod
    def request_parameters(isbn_13: str) -> dict[str, str]:
        """Return the exact TOC query sent for one ISBN; the API key is never part of it."""
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
        """Fetch one book's TOC; a "product not found" answer is returned, not raised.

        Unlike `fetch_content`, the YES24 error body is kept as-is so the raw
        artifact records exactly why no TOC was found.
        """
        self._wait_for_rate_limit()
        response = self.client.get(
            API_URL,
            params=self.request_parameters(isbn_13),
            headers=self._auth_headers,
        )
        if response.status_code == 404:
            payload = parse_json_object(response, "yes24")
            if payload.get("success") is False:
                return payload
        response.raise_for_status()
        return parse_json_object(response, "yes24")


_NOT_FOUND_CODES = {"SEARCH_001", "GOODS_001", "GOODS_002"}


def _not_found_as_empty(response: httpx.Response, empty_key: str | None) -> dict[str, Any] | None:
    """Turn YES24's documented "no results" 404s into an empty success payload.

    Returns None (caller should fall through to raise_for_status) for any
    other status, including a 404 with an unrecognized errorCode.
    """
    if response.status_code != 404:
        return None
    try:
        body = response.json()
    except ValueError:
        return None
    if not isinstance(body, dict) or body.get("errorCode") not in _NOT_FOUND_CODES:
        return None
    data: dict[str, Any] = {"items": []} if empty_key == "items" else {}
    return {"success": True, "message": body.get("message"), "data": data, "errorCode": None}
