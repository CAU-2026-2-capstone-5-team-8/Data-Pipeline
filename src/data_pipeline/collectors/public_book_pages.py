"""Collector for exact-edition public HTML pages on a small allowlist."""

from typing import Any

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from data_pipeline.collectors.base import InvalidProviderResponse, is_transient_http_error
from data_pipeline.public_book_sources import public_book_source


class PublicBookPageCollector:
    """Fetch one reviewed public HTML page without crawling its links."""

    def __init__(self, client: httpx.Client | None = None) -> None:
        self._owns_client = client is None
        self.client = client or httpx.Client(
            timeout=httpx.Timeout(20.0),
            follow_redirects=False,
            headers={"User-Agent": "cau-capstone-data-pipeline/0.1 (book evidence research)"},
        )

    def close(self) -> None:
        """Close the internally owned HTTP client."""
        if self._owns_client:
            self.client.close()

    def __enter__(self) -> "PublicBookPageCollector":
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
        if response.is_redirect:
            raise InvalidProviderResponse("public book page returned an unapproved redirect")
        response.raise_for_status()
        content_type = response.headers.get("content-type", "").casefold()
        if "text/html" not in content_type:
            raise InvalidProviderResponse(
                f"public book page returned unsupported content type: {content_type or 'missing'}"
            )
        html = response.text
        if not html.strip():
            raise InvalidProviderResponse("public book page returned empty HTML")
        return html

    def fetch(self, source_slug: str) -> dict[str, Any]:
        """Fetch only the reviewed page and preserve its complete HTML response."""
        source = public_book_source(source_slug)
        return {
            "source_slug": source.slug,
            "url": source.url,
            "html": self._fetch_html(source.url),
        }

    @staticmethod
    def request_parameters(source_slug: str) -> dict[str, str]:
        """Return the allowlisted request inputs needed for offline rebuilding."""
        source = public_book_source(source_slug)
        return {"source": source.slug, "url": source.url}
