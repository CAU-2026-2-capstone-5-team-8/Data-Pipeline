"""Collector for reviewed public PDF documents on publisher sites."""

import base64
from typing import Any

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from data_pipeline.collectors.base import InvalidProviderResponse, is_transient_http_error
from data_pipeline.publisher_document_sources import publisher_document_source

MAX_DOCUMENT_BYTES = 5 * 1024 * 1024


class PublisherDocumentCollector:
    """Fetch one allowlisted PDF plus the pages proving its exact-edition relationship."""

    def __init__(self, client: httpx.Client | None = None) -> None:
        self._owns_client = client is None
        self.client = client or httpx.Client(
            timeout=httpx.Timeout(30.0),
            follow_redirects=False,
            headers={"User-Agent": "cau-capstone-data-pipeline/0.1 (book evidence research)"},
        )

    def close(self) -> None:
        """Close the internally owned HTTP client."""
        if self._owns_client:
            self.client.close()

    def __enter__(self) -> "PublisherDocumentCollector":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    @retry(
        retry=retry_if_exception(is_transient_http_error),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
        reraise=True,
    )
    def _fetch(self, url: str, expected_content_type: str) -> bytes:
        response = self.client.get(url)
        if response.is_redirect:
            raise InvalidProviderResponse("publisher document returned an unapproved redirect")
        response.raise_for_status()
        content_type = response.headers.get("content-type", "").casefold()
        if expected_content_type not in content_type:
            raise InvalidProviderResponse(
                f"publisher document returned unsupported content type: {content_type or 'missing'}"
            )
        content = response.content
        if not content:
            raise InvalidProviderResponse("publisher document returned empty content")
        if len(content) > MAX_DOCUMENT_BYTES:
            raise InvalidProviderResponse("publisher document exceeded the 5 MiB MVP limit")
        return content

    def fetch(self, source_slug: str) -> dict[str, Any]:
        """Fetch only the reviewed identity page, referrer page, and PDF."""
        source = publisher_document_source(source_slug)
        home = self._fetch(source.home_url, "text/html").decode("utf-8", errors="replace")
        referrer = self._fetch(source.referrer_url, "text/html").decode("utf-8", errors="replace")
        document = self._fetch(source.document_url, "application/pdf")
        if not document.startswith(b"%PDF-"):
            raise InvalidProviderResponse("publisher document response is not a PDF")
        return {
            "source_slug": source.slug,
            "home_url": source.home_url,
            "home_html": home,
            "referrer_url": source.referrer_url,
            "referrer_html": referrer,
            "document_url": source.document_url,
            "document_media_type": "application/pdf",
            "document_base64": base64.b64encode(document).decode("ascii"),
        }

    @staticmethod
    def request_parameters(source_slug: str) -> dict[str, str]:
        """Return the exact allowlisted request inputs used for reproducibility."""
        source = publisher_document_source(source_slug)
        return {
            "source": source.slug,
            "home_url": source.home_url,
            "referrer_url": source.referrer_url,
            "document_url": source.document_url,
        }
