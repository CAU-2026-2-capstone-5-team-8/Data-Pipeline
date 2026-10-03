"""Public, explicitly attributed preface excerpts from publisher product pages.

The first adapter supports Kyungmoon product pages, without per-book URL/ISBN lists.
A product description alone is never promoted to preface evidence.
"""

import re
from datetime import datetime
from urllib.parse import parse_qs, urlsplit

import httpx
from selectolax.parser import HTMLParser

from data_pipeline.collectors.base import InvalidProviderResponse
from data_pipeline.identifiers import normalize_bibliographic_text, sha256_text, stable_id
from data_pipeline.models import Book, CanonicalDataset, Document, Source, TextExtent

PROVIDER = "kyungmoon-preface-excerpt"
MAX_HTML_BYTES = 2 * 1024 * 1024
PREFACE_ATTRIBUTION = re.compile(r"[-–—]?\s*머리말\s+중에서\s*[-–—]?\s*$")


def validate_excerpt_url(url: str) -> None:
    """Accept the public product route only; never follow arbitrary hosts or redirects."""
    parsed = urlsplit(url)
    query = parse_qs(parsed.query, keep_blank_values=True)
    if (
        parsed.scheme != "https"
        or parsed.netloc != "www.kyungmoon.com"
        or parsed.path != "/shop/item.php"
        or parsed.fragment
        or set(query) - {"it_id", "device"}
        or len(query.get("it_id", [])) != 1
        or not re.fullmatch(r"[0-9]+", query["it_id"][0])
        or ("device" in query and query["device"] != ["pc"])
    ):
        raise ValueError("expected a public https://www.kyungmoon.com/shop/item.php?it_id=... URL")


def fetch_excerpt_page(url: str, *, client: httpx.Client | None = None) -> dict:
    validate_excerpt_url(url)
    if client is None:
        with httpx.Client(
            timeout=25,
            follow_redirects=False,
            headers={"User-Agent": "cau-capstone-data-pipeline/0.1 (book evidence research)"},
        ) as owned:
            return fetch_excerpt_page(url, client=owned)
    with client.stream("GET", url, follow_redirects=False) as response:
        if response.is_redirect:
            raise InvalidProviderResponse("publisher excerpt returned an unapproved redirect")
        response.raise_for_status()
        if "text/html" not in response.headers.get("content-type", "").casefold():
            raise InvalidProviderResponse("publisher excerpt is not HTML")
        content = bytearray()
        for chunk in response.iter_bytes():
            content.extend(chunk)
            if len(content) > MAX_HTML_BYTES:
                raise InvalidProviderResponse("publisher excerpt exceeds the 2 MiB limit")
        try:
            html = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise InvalidProviderResponse("publisher excerpt is not UTF-8") from exc
    if not html.strip():
        raise InvalidProviderResponse("publisher excerpt is empty")
    return {"url": url, "html": html}


def normalize_preface_excerpt(
    payload: dict, book: Book, retrieved_at: datetime
) -> CanonicalDataset:
    """Require product ISBN/title and explicit terminal attribution; preserve original text."""
    url, html = payload.get("url"), payload.get("html")
    if not isinstance(url, str) or not isinstance(html, str):
        raise InvalidProviderResponse("publisher excerpt requires URL and original HTML")
    validate_excerpt_url(url)
    if len(html.encode("utf-8")) > MAX_HTML_BYTES:
        raise InvalidProviderResponse("publisher excerpt exceeds the 2 MiB limit")
    tree = HTMLParser(html)
    titles, sections, tables = (
        tree.css("#sit_title"),
        tree.css("#sit_introduce_explan"),
        tree.css("table.sit_ov_tbl"),
    )
    if len(titles) != 1 or len(sections) != 1 or len(tables) != 1:
        raise InvalidProviderResponse("publisher product identity/excerpt section is ambiguous")
    identity = {}
    for row in tables[0].css("tr"):
        heading, value = row.css_first("th"), row.css_first("td")
        if heading is not None and value is not None:
            key = heading.text().strip()
            if key in identity:
                raise InvalidProviderResponse("duplicate publisher identity field")
            identity[key] = value.text().strip()
    observed_isbn = identity.get("ISBN", "").replace("-", "").replace(" ", "")
    if not book.isbn_13 or observed_isbn != book.isbn_13:
        raise InvalidProviderResponse("publisher product ISBN does not match canonical edition")
    title = normalize_bibliographic_text(titles[0].text())
    if normalize_bibliographic_text(book.title) not in title:
        raise InvalidProviderResponse("publisher product title does not match canonical book")
    if book.language != "ko":
        raise InvalidProviderResponse("Korean excerpt requires a Korean canonical edition")
    # Only this explicit publisher attribution distinguishes an excerpt from marketing copy.
    section = sections[0]
    for hidden in section.css("script, style, noscript, [hidden], [aria-hidden='true']"):
        hidden.decompose()
    text = section.text(separator="\n").strip()
    if not PREFACE_ATTRIBUTION.search(text) or len(text) < 120:
        raise InvalidProviderResponse("no sufficiently long explicitly attributed preface excerpt")
    source_id = stable_id("source", PROVIDER, book.book_id, url)
    return CanonicalDataset(
        books=[book],
        toc=[],
        sources=[
            Source(
                source_id=source_id,
                book_id=book.book_id,
                provider=PROVIDER,
                source_type="publisher_page",
                url=url,
                external_id=book.isbn_13 + ":preface_excerpt",
                retrieved_at=retrieved_at,
                content_hash=sha256_text(html),
                license=None,
                rights_note=(
                    "Public publisher product page explicitly attributes this section to a "
                    "preface excerpt (머리말 중에서). Partial excerpt, not a complete preface or "
                    "sample chapter. Matched product ISBN and title to the Korean canonical "
                    "edition; printing-specific differences were not verified. "
                    "No reuse license established. HTML text extraction only; "
                    "no OCR or translation."
                ),
            )
        ],
        documents=[
            Document(
                document_id=stable_id("doc", source_id, "preface", sha256_text(text)),
                book_id=book.book_id,
                document_type="preface",
                text_extent=TextExtent(
                    scope="excerpt",
                    basis="Publisher introduction section explicitly ends with 머리말 중에서.",
                ),
                text=text,
                source_id=source_id,
                content_hash=sha256_text(text),
            )
        ],
    )
