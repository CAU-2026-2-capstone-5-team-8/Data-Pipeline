"""Bounded ISBN bibliography searches against the National Library of Korea API."""

from typing import Any

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from data_pipeline.collectors.base import (
    InvalidProviderResponse,
    is_transient_http_error,
    parse_json_object,
)

API_URL = "https://www.nl.go.kr/seoji/SearchApi.do"


def bibliography_rows(response: dict[str, Any]) -> list[Any]:
    """API errors must not be mistaken for a successful empty search."""
    if any(response.get(key) for key in ("error", "ERROR", "ERROR_CODE", "error_code")):
        raise InvalidProviderResponse("national_library: bibliography API error")
    if "docs" not in response or not isinstance(response["docs"], list):
        raise InvalidProviderResponse("national_library: invalid bibliography response")
    return response["docs"]


class NationalLibraryCollector:
    def __init__(self, client: httpx.Client | None = None, api_key: str | None = None):
        self.api_key = api_key
        self._owns_client = client is None
        self.client = client or httpx.Client(
            timeout=httpx.Timeout(15.0),
            headers={"User-Agent": "cau-capstone-data-pipeline/0.1"},
        )

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        if self._owns_client:
            self.client.close()

    @staticmethod
    def query_parameters(query: str, limit: int = 30) -> dict[str, Any]:
        if not query.strip() or limit < 1:
            raise ValueError("national library query and positive limit required")
        return {
            "title": query.strip(),
            "result_style": "json",
            "page_no": 1,
            "page_size": min(limit, 30),
            "ebook_yn": "N",
        }

    @retry(
        retry=retry_if_exception(is_transient_http_error),
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=1, min=1, max=4),
        reraise=True,
    )
    def search_scope(self, parameters: dict[str, Any]) -> dict[str, Any]:
        if not self.api_key:
            raise InvalidProviderResponse("national_library: API key not configured")
        if "cert_key" in parameters:
            raise ValueError("credentials must not enter saved query parameters")
        request = dict(parameters, cert_key=self.api_key)
        # Exceptions exposed to callers must also have credential-free request URLs.
        safe_request = httpx.Request("GET", API_URL, params=parameters)
        try:
            response = self.client.get(API_URL, params=request)
        except httpx.TransportError:
            raise httpx.TransportError(
                "national_library: request failed", request=safe_request
            ) from None
        if response.is_error:
            safe_response = httpx.Response(response.status_code, request=safe_request)
            raise httpx.HTTPStatusError(
                f"national_library: HTTP {response.status_code}",
                request=safe_request,
                response=safe_response,
            ) from None
        payload = parse_json_object(response, "national_library")
        bibliography_rows(payload)
        # The key belongs only in the outgoing HTTP request, never in persisted artifacts.
        return _without_credentials(payload)


def _without_credentials(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _without_credentials(item)
            for key, item in value.items()
            if key.casefold() not in {"cert_key", "apikey", "api_key"}
        }
    if isinstance(value, list):
        return [_without_credentials(item) for item in value]
    return value
