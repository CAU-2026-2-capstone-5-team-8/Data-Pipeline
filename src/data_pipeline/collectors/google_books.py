"""Small, polite Google Books API metadata collector."""

import os
import re
from typing import Any

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from data_pipeline.collectors.base import (
    InvalidProviderResponse,
    is_transient_http_error,
    parse_json_object,
)
from data_pipeline.topics import topic_google_books_query

API_URL = "https://www.googleapis.com/books/v1/volumes"
MAX_PAGE_SIZE = 40


class GoogleBooksCollector:
    def __init__(self, client: httpx.Client | None = None, api_key: str | None = None) -> None:
        """Create a collector with an optional injected client for deterministic tests."""
        self._owns_client = client is None
        self.api_key = api_key if api_key is not None else os.getenv("GOOGLE_BOOKS_API_KEY")
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
        request = dict(parameters)
        if self.api_key:
            request["key"] = self.api_key
        safe_request = httpx.Request("GET", API_URL, params=parameters)
        try:
            response = self.client.get(API_URL, params=request)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            safe_response = httpx.Response(exc.response.status_code, request=safe_request)
            raise httpx.HTTPStatusError(
                f"google-books returned HTTP {exc.response.status_code}",
                request=safe_request,
                response=safe_response,
            ) from None
        except httpx.RequestError as exc:
            raise type(exc)("google-books request failed", request=safe_request) from None
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
            has_valid_total = (
                isinstance(total_items, int)
                and not isinstance(total_items, bool)
                and total_items >= 0
            )
            if has_valid_total and collected_count >= total_items:
                break
            if not has_valid_total and len(items) < parameters["maxResults"]:
                break
        return {"pages": pages}

    def search_scope(self, parameters: dict[str, Any]) -> dict[str, Any]:
        """Try at most three queries on empty results; preserve every credential-free response.

        Broader discovery still passes the same language, ISBN and subject evidence gate.
        Provider errors stop the search rather than switching queries to evade a quota.
        """
        queries = [parameters["q"]]
        subject = re.fullmatch(r'subject:"((?:\\.|[^"\\])*)"', parameters["q"])
        if subject:
            phrase = subject.group(1)
            queries.extend(
                [f'intitle:"{phrase}"', phrase.replace('\\"', '"').replace("\\\\", "\\")]
            )
        attempts = []
        for query in queries:
            request = dict(parameters, q=query)
            response = self._fetch_page(request)
            items = response.get("items", [])
            if not isinstance(items, list):
                raise InvalidProviderResponse("google-books returned an invalid 'items' collection")
            attempts.append({"request_parameters": request, "response": response})
            if items:
                break
        if len(attempts) == 1:
            return response
        return {**response, "search_attempts": attempts}

    @staticmethod
    def search_parameters(topic: str, candidate_limit: int) -> dict[str, Any]:
        """Return the exact ordered page requests for one bounded search."""
        if candidate_limit < 1:
            raise ValueError("candidate_limit must be at least 1")
        query = topic_google_books_query(topic)
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
