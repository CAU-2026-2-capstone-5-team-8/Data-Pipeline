"""Collector for a small allowlist of public publisher HTML pages."""

from typing import Any

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from data_pipeline.collectors.base import InvalidProviderResponse, is_transient_http_error
from data_pipeline.publisher_sources import publisher_source


class PublisherPageCollector:
    """Fetch exact-edition publisher pages without crawling linked resources."""

    def __init__(self, client: httpx.Client | None = None) -> None:
        self._owns_client = client is None
        self.client = client or httpx.Client(
            timeout=httpx.Timeout(20.0),
            follow_redirects=True,
            headers={"User-Agent": "cau-capstone-data-pipeline/0.1 (book evidence research)"},
        )

    def close(self) -> None:
        """Close the internally owned HTTP client."""
        if self._owns_client:
            self.client.close()

    def __enter__(self) -> "PublisherPageCollector":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    @retry(
        retry=retry_if_exception(is_transient_http_error),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
        reraise=True,
    )
    def _fetch_html(self, url: str) -> str:
        response = self.client.get(url)
        response.raise_for_status()
        content_type = response.headers.get("content-type", "").casefold()
        if "text/html" not in content_type:
            raise InvalidProviderResponse(
                f"publisher page returned unsupported content type: {content_type or 'missing'}"
            )
        html = response.text
        if not html.strip():
            raise InvalidProviderResponse("publisher page returned empty HTML")
        return html

    def fetch(self, source_slug: str) -> dict[str, Any]:
        """Fetch only the reviewed identity page and its public TOC page."""
        source = publisher_source(source_slug)
        return {
            "source_slug": source.slug,
            "home_url": source.home_url,
            "home_html": self._fetch_html(source.home_url),
            "toc_url": source.toc_url,
            "toc_html": self._fetch_html(source.toc_url),
        }

    @staticmethod
    def request_parameters(source_slug: str) -> dict[str, str]:
        """Return the exact allowlisted request inputs used for reproducibility."""
        source = publisher_source(source_slug)
        return {
            "source": source.slug,
            "home_url": source.home_url,
            "toc_url": source.toc_url,
        }
