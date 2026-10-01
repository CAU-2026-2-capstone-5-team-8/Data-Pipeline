"""Fail-closed contracts for the reviewed Greub second-edition Springer TOC."""

import json
from dataclasses import replace
from datetime import UTC, datetime

import httpx
import pytest

from data_pipeline.collectors.base import InvalidProviderResponse
from data_pipeline.collectors.public_book_pages import PublicBookPageCollector
from data_pipeline.normalizers import normalize_public_book_page_response
from data_pipeline.public_book_sources import public_book_source

RETRIEVED_AT = datetime(2026, 9, 29, tzinfo=UTC)


def compact_springer_page(
    *,
    title: str = "Linear Algebra",
    author: str = "Werner H. Greub",
    edition: str = "2nd edition",
    year: str = "1963",
    isbn: str = "978-3-662-01545-2",
) -> str:
    """Return the official page's identity and TOC shapes without copied prose."""
    structured = json.dumps(
        {
            "@context": "https://schema.org",
            "@type": "Book",
            "name": title,
            "author": [{"@type": "Person", "name": author}],
            "copyrightYear": year,
            "isbn": isbn,
        }
    )
    return f"""
    <script type="application/ld+json">{structured}</script>
    <h1 data-test="book-title">{title}</h1>
    <ul>
      <li class="c-article-identifiers__item"><span>&copy;</span> {year}</li>
      <li class="c-article-identifiers__item" data-test="edition-number">{edition}</li>
    </ul>
    <a data-test="author-name">{author}</a>
    <section data-title="Table of contents">
      <ol>
        <li data-test="chapter">
          <h3 class="app-card-open__heading" data-test="front-matter">Front Matter</h3>
          <span data-test="page-number">Pages II-XI</span>
        </li>
        <li data-test="chapter">
          <h3 class="app-card-open__heading" data-test="chapter-title-Linear spaces">
            <a href="/chapter/10.1007/978-3-662-01545-2_1">Linear spaces</a>
          </h3>
          <span data-test="page-number">Pages 1-15</span>
        </li>
        <li data-test="chapter">
          <h3 class="app-card-open__heading" data-test="chapter-title-Linear transformations">
            <a href="/chapter/10.1007/978-3-662-01545-2_2">Linear transformations</a>
          </h3>
          <span data-test="page-number">Pages 16-31</span>
        </li>
        <li data-test="chapter">
          <h3 class="app-card-open__heading" data-test="back-matter">Back Matter</h3>
          <span data-test="page-number">Pages 333-338</span>
        </li>
      </ol>
    </section>
    """


def compact_source(monkeypatch):
    source = replace(
        public_book_source("springer-greub-linear-algebra2"),
        expected_toc_count=4,
        expected_root_titles=(
            "Front Matter",
            "Linear spaces",
            "Linear transformations",
            "Back Matter",
        ),
        expected_chapter_labels=("1", "2"),
    )
    monkeypatch.setattr("data_pipeline.normalizers.public_book_source", lambda _slug: source)
    return source


def normalize(source, html: str):
    return normalize_public_book_page_response(
        {"source_slug": source.slug, "url": source.url, "html": html},
        topic=source.topic,
        retrieved_at=RETRIEVED_AT,
    )


def test_springer_toc_requires_exact_publisher_identity_and_flat_sequence(monkeypatch) -> None:
    source = compact_source(monkeypatch)

    dataset = normalize(source, compact_springer_page())

    assert dataset.documents == []
    assert [entry.label for entry in dataset.toc] == [None, "1", "2", None]
    assert all(entry.level == 1 and entry.parent_entry_id is None for entry in dataset.toc)
    canonical_source = dataset.sources[0]
    assert canonical_source.source_type == "publisher_page"
    assert canonical_source.external_id == "10.1007/978-3-662-01545-2"
    assert canonical_source.evidence is not None
    assert canonical_source.evidence.target_isbn is None
    assert canonical_source.evidence.source_isbns == ["9783662015452"]
    assert canonical_source.evidence.same_edition is True


@pytest.mark.parametrize(
    ("html", "message"),
    [
        (compact_springer_page(title="Other Algebra"), "identity"),
        (compact_springer_page(author="Other Author"), "identity"),
        (compact_springer_page(edition="3rd edition"), "identity"),
        (compact_springer_page(year="1970"), "identity"),
        (compact_springer_page(isbn="978-0-000-00000-2"), "identity"),
        (
            compact_springer_page().replace(
                '<a href="/chapter/10.1007/978-3-662-01545-2_2">',
                '<a href="/chapter/10.1007/978-3-662-01545-2_3">',
            ),
            "complete sequence",
        ),
        (
            compact_springer_page().replace('<span data-test="page-number">Pages 16-31</span>', ""),
            "malformed metadata",
        ),
        (
            compact_springer_page().replace(
                """        <li data-test="chapter">
          <h3 class="app-card-open__heading" data-test="chapter-title-Linear transformations">
            <a href="/chapter/10.1007/978-3-662-01545-2_2">Linear transformations</a>
          </h3>
          <span data-test="page-number">Pages 16-31</span>
        </li>
""",
                "",
            ),
            "entry count",
        ),
    ],
)
def test_springer_toc_rejects_changed_identity_or_structure(
    monkeypatch, html: str, message: str
) -> None:
    source = compact_source(monkeypatch)

    with pytest.raises(InvalidProviderResponse, match=message):
        normalize(source, html)


def test_springer_collector_follows_only_reviewed_https_identity_hosts() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if request.url.host == "link.springer.com" and len(calls) == 1:
            return httpx.Response(
                303,
                headers={"location": "https://idp.springer.com/authorize"},
                request=request,
            )
        if request.url.host == "idp.springer.com":
            return httpx.Response(
                302,
                headers={"location": "https://link.springer.com/book/10.1007/978-3-662-01545-2"},
                request=request,
            )
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            text="<html>reviewed page</html>",
            request=request,
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        payload = PublicBookPageCollector(client=client).fetch("springer-greub-linear-algebra2")

    assert payload["html"] == "<html>reviewed page</html>"
    assert [httpx.URL(url).host for url in calls] == [
        "link.springer.com",
        "idp.springer.com",
        "link.springer.com",
    ]


def test_springer_collector_rejects_redirect_outside_reviewed_hosts() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            302,
            headers={"location": "https://example.test/login"},
            request=request,
        )

    with (
        httpx.Client(transport=httpx.MockTransport(handler)) as client,
        pytest.raises(InvalidProviderResponse, match="unapproved redirect"),
    ):
        PublicBookPageCollector(client=client).fetch("springer-greub-linear-algebra2")
