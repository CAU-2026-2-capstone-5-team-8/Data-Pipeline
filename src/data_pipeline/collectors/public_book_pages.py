"""Collector for exact-edition public HTML pages on a small allowlist."""

from typing import Any
from urllib.parse import urljoin, urlsplit

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
    def _fetch_html(self, url: str, allowed_redirect_hosts: tuple[str, ...] = ()) -> str:
        response = self.client.get(url, follow_redirects=False)
        redirect_count = 0
        while response.is_redirect:
            location = response.headers.get("location")
            redirect_url = urljoin(str(response.url), location) if location else ""
            hostname = urlsplit(redirect_url).hostname
            host_allowed = hostname is not None and any(
                hostname == allowed or hostname.endswith(f".{allowed}")
                for allowed in allowed_redirect_hosts
            )
            if urlsplit(redirect_url).scheme != "https" or not host_allowed:
                raise InvalidProviderResponse("public book page returned an unapproved redirect")
            redirect_count += 1
            if redirect_count > 5:
                raise InvalidProviderResponse("public book page exceeded redirect limit")
            response = self.client.get(redirect_url, follow_redirects=False)
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
            "html": self._fetch_html(source.url, source.allowed_redirect_hosts),
        }

    @staticmethod
    def request_parameters(source_slug: str) -> dict[str, str | list[str]]:
        """Return the allowlisted request inputs needed for offline rebuilding."""
        source = public_book_source(source_slug)
        parameters: dict[str, str | list[str]] = {
            "source": source.slug,
            "url": source.url,
        }
        if source.allowed_redirect_hosts:
            parameters["allowed_redirect_hosts"] = list(source.allowed_redirect_hosts)
        return parameters
