"""Collector for a reviewed public open textbook."""

import base64
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from data_pipeline.collectors.base import InvalidProviderResponse, is_transient_http_error
from data_pipeline.open_textbook_sources import open_textbook_source


class OpenTextbookCollector:
    """Fetch one allowlisted textbook home page and its reviewed public resources."""

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

    def __enter__(self) -> "OpenTextbookCollector":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    @retry(
        retry=retry_if_exception(is_transient_http_error),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
        reraise=True,
    )
    def _fetch(
        self,
        url: str,
        expected_content_type: str,
        max_bytes: int,
        allowed_redirect_hosts: tuple[str, ...] = (),
    ) -> tuple[bytes, str]:
        response = self.client.get(url, follow_redirects=False)
        redirect_count = 0
        while response.is_redirect:
            location = response.headers.get("location")
            redirect_url = urljoin(str(response.url), location) if location else ""
            if urlsplit(redirect_url).scheme != "https" or not self._redirect_host_allowed(
                redirect_url, allowed_redirect_hosts
            ):
                raise InvalidProviderResponse(
                    "open textbook source redirected to an unapproved host"
                )
            redirect_count += 1
            if redirect_count > 5:
                raise InvalidProviderResponse("open textbook source exceeded redirect limit")
            response = self.client.get(redirect_url, follow_redirects=False)
        response.raise_for_status()
        content_type = response.headers.get("content-type", "").casefold()
        if expected_content_type not in content_type:
            raise InvalidProviderResponse(
                f"open textbook source returned unsupported content type: "
                f"{content_type or 'missing'}"
            )
        content = response.content
        if not content:
            raise InvalidProviderResponse("open textbook source returned empty content")
        if len(content) > max_bytes:
            limit_mib = max_bytes // (1024 * 1024)
            raise InvalidProviderResponse(
                f"open textbook resource exceeded its {limit_mib} MiB MVP limit"
            )
        return content, str(response.url)

    @staticmethod
    def _redirect_host_allowed(url: str, allowed_hosts: tuple[str, ...]) -> bool:
        """Accept an explicitly reviewed host or one of its subdomains."""
        hostname = urlsplit(url).hostname
        return hostname is not None and any(
            hostname == allowed or hostname.endswith(f".{allowed}") for allowed in allowed_hosts
        )

    def fetch(self, source_slug: str) -> dict[str, Any]:
        """Fetch only the allowlisted home, license, and reviewed resources."""
        source = open_textbook_source(source_slug)
        home_content, _ = self._fetch(source.home_url, "text/html", 1024 * 1024)
        home = home_content.decode("utf-8", errors="replace")
        license_html = None
        if source.license_url is not None:
            license_content, _ = self._fetch(
                source.license_url, source.license_media_type, 1024 * 1024
            )
            license_html = license_content.decode("utf-8", errors="replace")
        documents = []
        for document in source.documents:
            content, resolved_url = self._fetch(
                document.url,
                document.media_type,
                source.max_resource_bytes,
                document.allowed_redirect_hosts,
            )
            if document.media_type == "application/pdf" and not content.startswith(b"%PDF-"):
                raise InvalidProviderResponse("open textbook document response is not a PDF")
            documents.append(
                {
                    "url": document.url,
                    "resolved_url": resolved_url,
                    "media_type": document.media_type,
                    "content_base64": base64.b64encode(content).decode("ascii"),
                }
            )
        payload = {
            "source_slug": source.slug,
            "home_url": source.home_url,
            "home_html": home,
            "documents": documents,
        }
        if source.license_url is not None:
            payload["license_url"] = source.license_url
            payload["license_html"] = license_html
        return payload

    @staticmethod
    def request_parameters(source_slug: str) -> dict[str, str | list[str]]:
        """Return the complete allowlisted request inputs used for reproducibility."""
        source = open_textbook_source(source_slug)
        parameters: dict[str, str | list[str]] = {
            "source": source.slug,
            "home_url": source.home_url,
            "document_urls": [document.url for document in source.documents],
        }
        if source.license_url is not None:
            parameters["license_url"] = source.license_url
        return parameters
