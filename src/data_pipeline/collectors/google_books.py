"""Small, polite Google Books API metadata collector."""

from typing import Any

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

API_URL = "https://www.googleapis.com/books/v1/volumes"
TOPIC_QUERIES = {
    "operating-systems": 'subject:"Operating systems"',
    "linear-algebra": 'subject:"Linear algebra"',
}


def is_transient_http_error(exception: BaseException) -> bool:
    if isinstance(exception, (httpx.TimeoutException, httpx.NetworkError)):
        return True
    return isinstance(exception, httpx.HTTPStatusError) and (
        exception.response.status_code == 429 or exception.response.status_code >= 500
    )


class GoogleBooksCollector:
    def __init__(self, client: httpx.Client | None = None) -> None:
        self._owns_client = client is None
        self.client = client or httpx.Client(
            timeout=httpx.Timeout(20.0),
            headers={"User-Agent": "cau-capstone-data-pipeline/0.1"},
        )

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def __enter__(self) -> "GoogleBooksCollector":
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
        try:
            query = TOPIC_QUERIES[topic]
        except KeyError as exc:
            raise ValueError(f"unsupported topic: {topic}") from exc
        response = self.client.get(
            API_URL,
            params={
                "q": query,
                "langRestrict": "en",
                "maxResults": min(candidate_limit, 40),
                "orderBy": "relevance",
                "printType": "books",
            },
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("Google Books returned a non-object response")
        return payload
