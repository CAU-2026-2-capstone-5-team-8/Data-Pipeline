"""Normalization of provider responses into canonical evidence records."""

import base64
import binascii
import logging
import re
from datetime import datetime
from io import BytesIO
from typing import Any
from urllib.parse import urljoin

from pydantic import ValidationError
from pypdf import PdfReader
from pypdf.errors import PdfReadError
from selectolax.parser import HTMLParser

from data_pipeline.collectors.base import InvalidProviderResponse
from data_pipeline.identifiers import (
    is_valid_isbn_10,
    is_valid_isbn_13,
    normalize_bibliographic_text,
    sha256_bytes,
    sha256_json,
    sha256_text,
    stable_id,
)
from data_pipeline.models import Book, CanonicalDataset, Document, Source, TocEntry
from data_pipeline.open_textbook_sources import OpenTextbookSourceSpec, open_textbook_source
from data_pipeline.public_book_sources import public_book_source
from data_pipeline.publisher_document_sources import publisher_document_source
from data_pipeline.publisher_sources import publisher_source

logger = logging.getLogger(__name__)
logging.getLogger("pypdf").setLevel(logging.ERROR)

TOPICS: dict[str, list[str]] = {
    "operating-systems": ["computer-science", "operating-systems"],
    "linear-algebra": ["mathematics", "linear-algebra"],
}
MAX_AUTHORS_PER_BOOK = 8
EDITION_WORDS = {
    "first": 1,
    "second": 2,
    "third": 3,
    "fourth": 4,
    "fifth": 5,
    "sixth": 6,
    "seventh": 7,
    "eighth": 8,
    "ninth": 9,
    "tenth": 10,
    "eleventh": 11,
    "twelfth": 12,
}


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _provider_records(response: dict[str, Any], field: str, provider: str) -> list[Any]:
    records = response.get(field, [])
    if not isinstance(records, list):
        raise InvalidProviderResponse(
            f"{provider} returned an invalid {field!r} collection; expected a list"
        )
    return records


def _deduplicate_authors(value: Any) -> list[str]:
    authors: list[str] = []
    seen: set[str] = set()
    for author in _string_list(value):
        key = normalize_bibliographic_text(author)
        if key and key not in seen:
            authors.append(author)
            seen.add(key)
    return authors


def _authors_from_by_statement(value: Any) -> list[str]:
    if not isinstance(value, str):
        return []
    statement = re.sub(r"^\s*by\s+", "", value.strip(), flags=re.IGNORECASE).rstrip(".")
    authors = re.split(r"\s*(?:,|\band\b)\s*", statement)
    return _deduplicate_authors(authors)


def normalize_isbn(value: str | None, length: int) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    cleaned = re.sub(r"[^0-9Xx]", "", value).upper()
    if length == 10 and not is_valid_isbn_10(cleaned):
        return None
    if length == 13 and not is_valid_isbn_13(cleaned):
        return None
    if length not in (10, 13):
        return None
    return cleaned


def _isbns(volume_info: dict[str, Any]) -> tuple[str | None, str | None]:
    isbn_10 = None
    isbn_13 = None
    for identifier in volume_info.get("industryIdentifiers", []):
        if not isinstance(identifier, dict):
            continue
        kind = identifier.get("type")
        if kind == "ISBN_10":
            isbn_10 = normalize_isbn(identifier.get("identifier"), 10)
        elif kind == "ISBN_13":
            isbn_13 = normalize_isbn(identifier.get("identifier"), 13)
    return isbn_10, isbn_13


def _book_id(
    isbn_10: str | None,
    isbn_13: str | None,
    title: str,
    authors: list[str],
    provider: str,
    external_id: str,
) -> str:
    if isbn_13:
        return f"isbn13:{isbn_13}"
    if isbn_10:
        return f"isbn10:{isbn_10}"
    if title and authors:
        normalized_title = normalize_bibliographic_text(title)
        normalized_author = normalize_bibliographic_text(authors[0])
        if normalized_title and normalized_author:
            return stable_id("book", normalized_title, normalized_author)
    return stable_id("book", provider, external_id)


def _published_year(value: str | None) -> int | None:
    if not value:
        return None
    match = re.search(r"(?<!\d)(1\d{3}|20\d{2}|21\d{2})(?!\d)", value)
    return int(match.group(1)) if match else None


def _normalize_google_item(
    item: dict[str, Any], topic: str, retrieved_at: datetime
) -> tuple[Book, Source, Document | None] | None:
    info = item.get("volumeInfo", {})
    if not isinstance(info, dict):
        return None
    external_id = str(item.get("id", "")).strip()
    title = str(info.get("title", "")).strip()
    language = str(info.get("language", "")).lower()
    if not external_id or not title or language != "en":
        return None

    authors = _deduplicate_authors(info.get("authors"))
    isbn_10, isbn_13 = _isbns(info)
    book_id = _book_id(isbn_10, isbn_13, title, authors, "google_books", external_id)
    source_id = stable_id("source", "google_books", external_id, book_id, retrieved_at.isoformat())
    source_url = str(
        item.get("selfLink") or f"https://www.googleapis.com/books/v1/volumes/{external_id}"
    )
    book = Book(
        book_id=book_id,
        isbn_10=isbn_10,
        isbn_13=isbn_13,
        title=title,
        subtitle=info.get("subtitle"),
        authors=authors,
        publisher=info.get("publisher"),
        published_year=_published_year(info.get("publishedDate")),
        language=language,
        topics=TOPICS[topic],
    )
    source = Source(
        source_id=source_id,
        book_id=book_id,
        provider="google_books",
        source_type="metadata_api",
        url=source_url,
        external_id=external_id,
        retrieved_at=retrieved_at,
        license=None,
        rights_note=None,
        content_hash=sha256_json(item),
    )
    description = info.get("description")
    document = None
    if isinstance(description, str) and description.strip():
        text = description.strip()
        document = Document(
            document_id=stable_id("doc", book_id, "description", source_id),
            book_id=book_id,
            document_type="description",
            text=text,
            source_id=source_id,
            content_hash=sha256_text(text),
        )
    return book, source, document


def normalize_google_books_response(
    response: dict[str, Any],
    *,
    topic: str,
    limit: int,
    retrieved_at: datetime,
) -> CanonicalDataset:
    if topic not in TOPICS:
        raise ValueError(f"unsupported topic: {topic}")

    books: list[Book] = []
    documents: list[Document] = []
    sources: list[Source] = []
    seen_books: set[str] = set()

    for item in _provider_records(response, "items", "google-books"):
        if not isinstance(item, dict):
            logger.warning(
                "event=normalization_skipped provider=google_books reason=record_not_object"
            )
            continue
        try:
            result = _normalize_google_item(item, topic, retrieved_at)
        except (AttributeError, TypeError, ValueError, ValidationError) as exc:
            logger.warning(
                "event=normalization_skipped provider=google_books external_id=%s error=%s",
                item.get("id"),
                exc,
            )
            continue
        if result is None:
            continue
        book, source, document = result
        book_id = book.book_id
        if book_id in seen_books:
            continue
        if document is not None:
            documents.append(document)
        seen_books.add(book_id)
        books.append(book)
        sources.append(source)
        if len(books) >= limit:
            break

    return CanonicalDataset(books=books, documents=documents, toc=[], sources=sources)


def _open_library_isbns(record: dict[str, Any]) -> tuple[str | None, str | None]:
    values = set(_string_list(record.get("isbn")))
    isbn_10_values = sorted(filter(None, (normalize_isbn(value, 10) for value in values)))
    isbn_13_values = sorted(filter(None, (normalize_isbn(value, 13) for value in values)))
    return (
        isbn_10_values[0] if isbn_10_values else None,
        isbn_13_values[0] if isbn_13_values else None,
    )


def _open_library_text(value: Any) -> str | None:
    if isinstance(value, dict):
        value = value.get("value")
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _edition_numbers(value: Any) -> set[int]:
    if not isinstance(value, str):
        return set()
    normalized = value.casefold()
    numbers = {
        int(match.group(1))
        for match in re.finditer(
            r"\b(\d{1,2})(?:st|nd|rd|th)?\s*(?:edition|ed\.?)(?:\b|$)", normalized
        )
    }
    for word, number in EDITION_WORDS.items():
        if re.search(rf"\b{word}\s+(?:edition|ed\.?)\b", normalized):
            numbers.add(number)
    return numbers


def _open_library_description(text: str, book_id: str, source_id: str) -> Document:
    return Document(
        document_id=stable_id("doc", book_id, "description", source_id),
        book_id=book_id,
        document_type="description",
        text=text,
        source_id=source_id,
        content_hash=sha256_text(text),
    )


def _normalize_open_library_toc(value: Any, book_id: str, source_id: str) -> list[TocEntry]:
    if value is None:
        return []
    if not isinstance(value, list):
        logger.warning(
            "event=toc_skipped provider=open_library book_id=%s reason=not_a_list",
            book_id,
        )
        return []

    valid_items: list[tuple[int, dict[str, Any]]] = []
    for raw_index, item in enumerate(value):
        title = item.get("title") if isinstance(item, dict) else None
        raw_level = item.get("level") if isinstance(item, dict) else None
        if (
            not isinstance(title, str)
            or not title.strip()
            or not isinstance(raw_level, int)
            or isinstance(raw_level, bool)
        ):
            logger.warning(
                "event=toc_entry_skipped provider=open_library book_id=%s "
                "raw_index=%d reason=invalid_title_or_level",
                book_id,
                raw_index,
            )
            continue
        valid_items.append((raw_index, item))

    if not valid_items:
        return []
    base_level = min(item["level"] for _, item in valid_items)
    latest_by_level: dict[int, str] = {}
    sibling_counts: dict[str | None, int] = {}
    entries: list[TocEntry] = []

    for raw_index, item in valid_items:
        title = item["title"]
        raw_level = item["level"]

        level = raw_level - base_level + 1
        parent_entry_id = latest_by_level.get(level - 1) if level > 1 else None
        if level > 1 and parent_entry_id is None:
            logger.warning(
                "event=toc_entry_skipped provider=open_library book_id=%s "
                "raw_index=%d reason=missing_parent",
                book_id,
                raw_index,
            )
            continue

        clean_title = title.strip()
        raw_label = item.get("label")
        label = raw_label.strip() if isinstance(raw_label, str) and raw_label.strip() else None
        entry_id = stable_id("toc", book_id, source_id, str(raw_index), label or "", clean_title)
        order_index = sibling_counts.get(parent_entry_id, 0)
        sibling_counts[parent_entry_id] = order_index + 1
        entries.append(
            TocEntry(
                toc_entry_id=entry_id,
                book_id=book_id,
                parent_entry_id=parent_entry_id,
                level=level,
                order_index=order_index,
                label=label,
                title=clean_title,
                source_id=source_id,
            )
        )
        latest_by_level[level] = entry_id
        latest_by_level = {
            known_level: known_id
            for known_level, known_id in latest_by_level.items()
            if known_level <= level
        }

    return entries


def _normalize_open_library_record(
    record: dict[str, Any],
    topic: str,
    retrieved_at: datetime,
    edition_details: dict[str, dict[str, Any]],
    work_details: dict[str, dict[str, Any]],
) -> tuple[Book, list[Source], list[Document], list[TocEntry]] | None:
    work_id = str(record.get("key", "")).strip()
    edition_container = record.get("editions", {})
    if not isinstance(edition_container, dict):
        return None
    edition_records = edition_container.get("docs", [])
    edition = next(
        (
            item
            for item in edition_records
            if isinstance(item, dict) and "eng" in _string_list(item.get("language"))
        ),
        None,
    )
    if edition is None:
        logger.warning(
            "event=normalization_skipped provider=open_library "
            "work_id=%s reason=no_english_edition",
            work_id,
        )
        return None

    external_id = str(edition.get("key") or work_id).strip()
    title = str(edition.get("title") or record.get("title", "")).strip()
    if not external_id or not title:
        return None
    edition_detail = edition_details.get(external_id, {})
    if not isinstance(edition_detail, dict):
        edition_detail = {}
    work_detail = work_details.get(work_id, {})
    if not isinstance(work_detail, dict):
        work_detail = {}
    authors = _deduplicate_authors(record.get("author_name"))
    statement_authors = _authors_from_by_statement(edition_detail.get("by_statement"))
    if 0 < len(statement_authors) <= MAX_AUTHORS_PER_BOOK:
        combined_authors = _deduplicate_authors([*statement_authors, *authors])
        authors = (
            combined_authors if len(combined_authors) <= MAX_AUTHORS_PER_BOOK else statement_authors
        )
    if len(authors) > MAX_AUTHORS_PER_BOOK:
        logger.warning(
            "event=normalization_skipped provider=open_library "
            "work_id=%s reason=unreliable_author_aggregation author_count=%d",
            work_id,
            len(authors),
        )
        return None
    isbn_10, isbn_13 = _open_library_isbns(edition)
    book_id = _book_id(isbn_10, isbn_13, title, authors, "open_library", external_id)
    source_id = stable_id("source", "open_library", external_id, book_id, retrieved_at.isoformat())
    publisher_values = _string_list(edition.get("publisher"))
    publisher = str(publisher_values[0]).strip() if publisher_values else None
    publish_dates = _string_list(edition.get("publish_date"))
    published_year = _published_year(str(publish_dates[0])) if publish_dates else None
    book = Book(
        book_id=book_id,
        isbn_10=isbn_10,
        isbn_13=isbn_13,
        title=title,
        subtitle=edition.get("subtitle"),
        authors=authors,
        publisher=publisher,
        published_year=published_year or record.get("first_publish_year"),
        language="en",
        topics=TOPICS[topic],
    )
    metadata_source = Source(
        source_id=source_id,
        book_id=book_id,
        provider="open_library",
        source_type="metadata_api",
        url=f"https://openlibrary.org{external_id}",
        external_id=external_id,
        retrieved_at=retrieved_at,
        license=None,
        rights_note=None,
        content_hash=sha256_json(
            {"search_record": record, "edition_detail": edition_detail or None}
        ),
    )
    sources = [metadata_source]
    documents: list[Document] = []
    description_hashes: set[str] = set()

    edition_description = _open_library_text(edition_detail.get("description"))
    edition_source_id = stable_id(
        "source", "open_library_edition", external_id, book_id, retrieved_at.isoformat()
    )
    toc = _normalize_open_library_toc(
        edition_detail.get("table_of_contents"), book_id, edition_source_id
    )
    if edition_description is not None:
        document = _open_library_description(edition_description, book_id, edition_source_id)
        documents.append(document)
        description_hashes.add(document.content_hash)
    if edition_description is not None or toc:
        sources.append(
            Source(
                source_id=edition_source_id,
                book_id=book_id,
                provider="open_library",
                source_type="metadata_api",
                url=f"https://openlibrary.org{external_id}.json",
                external_id=external_id,
                retrieved_at=retrieved_at,
                license=None,
                rights_note=None,
                content_hash=sha256_json(edition_detail),
            )
        )

    work_description = _open_library_text(work_detail.get("description"))
    selected_editions = _edition_numbers(edition_detail.get("edition_name"))
    described_editions = _edition_numbers(work_description)
    if (
        selected_editions
        and described_editions
        and selected_editions.isdisjoint(described_editions)
    ):
        logger.warning(
            "event=document_skipped provider=open_library book_id=%s "
            "reason=edition_mismatch selected=%s described=%s",
            book_id,
            sorted(selected_editions),
            sorted(described_editions),
        )
        work_description = None
    work_description_hash = sha256_text(work_description) if work_description is not None else None
    if work_description is not None and work_description_hash not in description_hashes:
        work_source_id = stable_id(
            "source", "open_library_work", work_id, book_id, retrieved_at.isoformat()
        )
        work_source = Source(
            source_id=work_source_id,
            book_id=book_id,
            provider="open_library",
            source_type="metadata_api",
            url=f"https://openlibrary.org{work_id}.json",
            external_id=work_id,
            retrieved_at=retrieved_at,
            license=None,
            rights_note=None,
            content_hash=sha256_json(work_detail),
        )
        sources.append(work_source)
        documents.append(_open_library_description(work_description, book_id, work_source_id))

    return book, sources, documents, toc


def normalize_open_library_response(
    response: dict[str, Any],
    *,
    topic: str,
    limit: int,
    retrieved_at: datetime,
) -> CanonicalDataset:
    if topic not in TOPICS:
        raise ValueError(f"unsupported topic: {topic}")

    books: list[Book] = []
    documents: list[Document] = []
    toc: list[TocEntry] = []
    sources: list[Source] = []
    seen_books: set[str] = set()
    search_response = response.get("search_response", response)
    if not isinstance(search_response, dict):
        search_response = {}
    edition_details = response.get("edition_details", {})
    if not isinstance(edition_details, dict):
        edition_details = {}
    work_details = response.get("work_details", {})
    if not isinstance(work_details, dict):
        work_details = {}
    for record in _provider_records(search_response, "docs", "open-library"):
        if not isinstance(record, dict):
            logger.warning(
                "event=normalization_skipped provider=open_library reason=record_not_object"
            )
            continue
        try:
            result = _normalize_open_library_record(
                record, topic, retrieved_at, edition_details, work_details
            )
        except (AttributeError, TypeError, ValueError, ValidationError) as exc:
            logger.warning(
                "event=normalization_skipped provider=open_library work_id=%s error=%s",
                record.get("key"),
                exc,
            )
            continue
        if result is None:
            continue
        book, book_sources, book_documents, book_toc = result
        book_id = book.book_id
        if book_id in seen_books:
            continue
        books.append(book)
        sources.extend(book_sources)
        documents.extend(book_documents)
        toc.extend(book_toc)
        seen_books.add(book_id)
        if len(books) >= limit:
            break

    return CanonicalDataset(books=books, documents=documents, toc=toc, sources=sources)


def _wiley_toc_entries(html: str, book_id: str, source_id: str) -> list[TocEntry]:
    """Extract the visible chapter and appendix headings from one Wiley TOC page."""
    tree = HTMLParser(html)
    entries: list[TocEntry] = []
    seen: set[tuple[str, str]] = set()
    for heading in tree.css("div.chapterTitle h3"):
        text = heading.text(separator=" ", strip=True)
        match = re.fullmatch(r"(Chapter|Appendix)\s+([^:]+):\s*(.+)", text, re.IGNORECASE)
        if match is None:
            raise InvalidProviderResponse(
                f"Wiley TOC contained an unsupported heading for {book_id}: {text!r}"
            )
        label = match.group(2).strip()
        title = match.group(3).strip()
        identity = (label.casefold(), title.casefold())
        if identity in seen:
            raise InvalidProviderResponse(
                f"Wiley TOC contained a duplicate heading for {book_id}: {text!r}"
            )
        seen.add(identity)
        order_index = len(entries)
        entries.append(
            TocEntry(
                toc_entry_id=stable_id("toc", book_id, source_id, str(order_index), label, title),
                book_id=book_id,
                parent_entry_id=None,
                level=1,
                order_index=order_index,
                label=label,
                title=title,
                source_id=source_id,
            )
        )
    return entries


def normalize_publisher_page_response(
    response: dict[str, Any], *, topic: str, retrieved_at: datetime
) -> CanonicalDataset:
    """Normalize one allowlisted exact-edition publisher TOC response."""
    source_slug = response.get("source_slug")
    if not isinstance(source_slug, str):
        raise InvalidProviderResponse("publisher response is missing source_slug")
    try:
        source_spec = publisher_source(source_slug)
    except ValueError as exc:
        raise InvalidProviderResponse(str(exc)) from exc
    if topic != source_spec.topic:
        raise InvalidProviderResponse("publisher response topic does not match its allowlist entry")

    expected_urls = {
        "home_url": source_spec.home_url,
        "toc_url": source_spec.toc_url,
    }
    for field, expected in expected_urls.items():
        if response.get(field) != expected:
            raise InvalidProviderResponse(f"publisher response {field} does not match allowlist")
    home_html = response.get("home_html")
    toc_html = response.get("toc_html")
    if not isinstance(home_html, str) or not isinstance(toc_html, str):
        raise InvalidProviderResponse("publisher response must contain HTML strings")

    home_text = HTMLParser(home_html).root.text(separator=" ", strip=True)
    normalized_home = normalize_bibliographic_text(home_text)
    normalized_title = normalize_bibliographic_text(source_spec.title)
    if normalized_title not in normalized_home or source_spec.isbn_10 not in home_html:
        raise InvalidProviderResponse("publisher identity page does not match the expected book")
    if source_spec.edition not in _edition_numbers(home_text):
        raise InvalidProviderResponse("publisher identity page does not match the expected edition")

    home_hash = sha256_text(home_html)
    toc_hash = sha256_text(toc_html)
    home_source_id = stable_id(
        "source",
        source_spec.provider,
        source_spec.home_url,
        source_spec.book_id,
    )
    toc_source_id = stable_id(
        "source",
        source_spec.provider,
        source_spec.toc_url,
        source_spec.book_id,
    )
    toc = _wiley_toc_entries(toc_html, source_spec.book_id, toc_source_id)
    if not toc:
        raise InvalidProviderResponse("publisher TOC page contained no supported headings")
    labels = tuple(entry.label for entry in toc)
    if labels != source_spec.expected_toc_labels:
        raise InvalidProviderResponse(
            "publisher TOC page is incomplete or does not match the reviewed structure"
        )

    rights_note = "Public publisher companion page; no license statement found."
    home_source = Source(
        source_id=home_source_id,
        book_id=source_spec.book_id,
        provider=source_spec.provider,
        source_type="publisher_page",
        url=source_spec.home_url,
        external_id=source_spec.isbn_10,
        retrieved_at=retrieved_at,
        license=None,
        rights_note=rights_note,
        content_hash=home_hash,
    )
    toc_source = Source(
        source_id=toc_source_id,
        book_id=source_spec.book_id,
        provider=source_spec.provider,
        source_type="publisher_page",
        url=source_spec.toc_url,
        external_id=source_spec.isbn_10,
        retrieved_at=retrieved_at,
        license=None,
        rights_note=rights_note,
        content_hash=toc_hash,
    )
    return CanonicalDataset(books=[], documents=[], toc=toc, sources=[home_source, toc_source])


def _extract_pdf_text(content: bytes) -> str:
    """Extract page text deterministically while retaining visible page boundaries."""
    try:
        reader = PdfReader(BytesIO(content))
        pages = [text.strip() for page in reader.pages if (text := page.extract_text())]
    except (PdfReadError, ValueError) as exc:
        raise InvalidProviderResponse(f"publisher PDF could not be parsed: {exc}") from exc
    text = "\n\n".join(page for page in pages if page)
    if not text:
        raise InvalidProviderResponse("publisher PDF contained no extractable text")
    return text


def normalize_publisher_document_response(
    response: dict[str, Any], *, topic: str, retrieved_at: datetime
) -> CanonicalDataset:
    """Normalize one allowlisted public publisher PDF into textual evidence."""
    source_slug = response.get("source_slug")
    if not isinstance(source_slug, str):
        raise InvalidProviderResponse("publisher document response is missing source_slug")
    try:
        source_spec = publisher_document_source(source_slug)
    except ValueError as exc:
        raise InvalidProviderResponse(str(exc)) from exc
    if topic != source_spec.topic:
        raise InvalidProviderResponse(
            "publisher document response topic does not match its allowlist entry"
        )

    expected_urls = {
        "home_url": source_spec.home_url,
        "referrer_url": source_spec.referrer_url,
        "document_url": source_spec.document_url,
    }
    for field, expected in expected_urls.items():
        if response.get(field) != expected:
            raise InvalidProviderResponse(
                f"publisher document response {field} does not match allowlist"
            )
    if response.get("document_media_type") != "application/pdf":
        raise InvalidProviderResponse("publisher document response has an invalid media type")
    home_html = response.get("home_html")
    referrer_html = response.get("referrer_html")
    encoded_document = response.get("document_base64")
    if not all(isinstance(value, str) for value in (home_html, referrer_html, encoded_document)):
        raise InvalidProviderResponse("publisher document response is missing string content")

    home_text = HTMLParser(home_html).root.text(separator=" ", strip=True)
    normalized_home = normalize_bibliographic_text(home_text)
    if (
        normalize_bibliographic_text(source_spec.title) not in normalized_home
        or source_spec.isbn_10 not in home_html
    ):
        raise InvalidProviderResponse("publisher document identity page does not match the book")
    if source_spec.edition not in _edition_numbers(home_text):
        raise InvalidProviderResponse(
            "publisher document identity page does not match the expected edition"
        )
    referrer_text = HTMLParser(referrer_html).root.text(separator=" ", strip=True)
    if (
        source_spec.document_url not in referrer_html
        or source_spec.referrer_heading not in referrer_text
    ):
        raise InvalidProviderResponse(
            "publisher document is not linked from its reviewed exact-edition page"
        )
    try:
        document_bytes = base64.b64decode(encoded_document, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise InvalidProviderResponse("publisher document contains invalid base64") from exc
    if not document_bytes.startswith(b"%PDF-"):
        raise InvalidProviderResponse("publisher document content is not a PDF")

    text = _extract_pdf_text(document_bytes)
    normalized_text = normalize_bibliographic_text(text)
    if any(
        normalize_bibliographic_text(marker) not in normalized_text
        for marker in source_spec.expected_text_markers
    ):
        raise InvalidProviderResponse("publisher PDF text does not match the reviewed document")

    source_id = stable_id(
        "source", source_spec.provider, source_spec.document_url, source_spec.book_id
    )
    source = Source(
        source_id=source_id,
        book_id=source_spec.book_id,
        provider=source_spec.provider,
        source_type="publisher_page",
        url=source_spec.document_url,
        external_id=source_spec.external_id,
        retrieved_at=retrieved_at,
        license=None,
        rights_note=(
            "Public supplemental appendix linked from the exact-edition publisher "
            "companion page; no license statement found."
        ),
        content_hash=sha256_bytes(document_bytes),
    )
    document = Document(
        document_id=stable_id("doc", source_spec.book_id, source_spec.document_type, source_id),
        book_id=source_spec.book_id,
        document_type=source_spec.document_type,
        text=text,
        source_id=source_id,
        content_hash=sha256_text(text),
    )
    return CanonicalDataset(books=[], documents=[document], toc=[], sources=[source])


def _ostep_description(tree: HTMLParser) -> str:
    """Extract the official introductory paragraph without unrelated page navigation."""
    for paragraph in tree.css("p"):
        text = paragraph.text(separator=" ", strip=True)
        if text.startswith("Welcome to Operating Systems: Three Easy Pieces"):
            return " ".join(text.split())
    raise InvalidProviderResponse("open textbook page is missing its reviewed description")


def _ostep_toc(html: str, book_id: str, source_id: str) -> list[TocEntry]:
    """Convert OSTEP's numbered chapter table into five explicit topic hierarchies."""
    tree = HTMLParser(html)
    chapters: dict[int, str] = {}
    heading_titles: list[str] = []
    for cell in tree.css("td[bgcolor]"):
        number_node = cell.css_first("small")
        if number_node is None:
            heading_node = cell.css_first("b")
            heading = (
                heading_node.text(separator=" ", strip=True) if heading_node is not None else ""
            )
            if heading and heading not in heading_titles:
                heading_titles.append(heading)
            continue
        number_text = number_node.text(strip=True)
        if not number_text.isdigit():
            continue
        number = int(number_text)
        pdf_links = [
            link
            for link in cell.css("a")
            if link.attributes.get("href", "").casefold().endswith(".pdf")
        ]
        if len(pdf_links) != 1:
            raise InvalidProviderResponse(
                f"open textbook chapter {number} must have exactly one PDF link"
            )
        title = pdf_links[0].text(separator=" ", strip=True)
        if number in chapters or not title:
            raise InvalidProviderResponse("open textbook TOC contains duplicate or empty chapters")
        chapters[number] = title
    if sorted(chapters) != list(range(1, 58)):
        raise InvalidProviderResponse(
            "open textbook TOC must contain numbered chapters 1 through 57"
        )

    groups = (
        ("Intro", 1, 2),
        ("Virtualization", 3, 24),
        ("Concurrency", 25, 34),
        ("Persistence", 35, 51),
        ("Security", 52, 57),
    )
    expected_headings = [title for title, _first, _last in groups]
    if heading_titles[: len(expected_headings)] != expected_headings:
        raise InvalidProviderResponse("open textbook TOC thematic headings do not match review")
    entries: list[TocEntry] = []
    for root_order, (group_title, first, last) in enumerate(groups):
        root_id = stable_id("toc", book_id, source_id, "root", group_title)
        entries.append(
            TocEntry(
                toc_entry_id=root_id,
                book_id=book_id,
                parent_entry_id=None,
                level=1,
                order_index=root_order,
                label=None,
                title=group_title,
                source_id=source_id,
            )
        )
        for child_order, chapter_number in enumerate(range(first, last + 1)):
            title = chapters[chapter_number]
            entries.append(
                TocEntry(
                    toc_entry_id=stable_id("toc", book_id, source_id, str(chapter_number), title),
                    book_id=book_id,
                    parent_entry_id=root_id,
                    level=2,
                    order_index=child_order,
                    label=str(chapter_number),
                    title=title,
                    source_id=source_id,
                )
            )
    return entries


def _reader_page_text(reader: PdfReader, start: int, end: int, document_name: str) -> str:
    """Extract a reviewed PDF page range with visible page boundaries."""
    if start < 0 or end <= start or end > len(reader.pages):
        raise InvalidProviderResponse(
            f"open textbook {document_name} page range is outside the reviewed PDF"
        )
    pages = [
        text.strip()
        for page in reader.pages[start:end]
        if (text := page.extract_text()) and text.strip()
    ]
    if not pages:
        raise InvalidProviderResponse(f"open textbook {document_name} contained no text")
    return "\n\n".join(pages)


def _pdf_outline_toc(reader: PdfReader, book_id: str, source_id: str) -> list[TocEntry]:
    """Preserve a reviewed PDF bookmark tree as canonical TOC hierarchy."""
    entries: list[TocEntry] = []

    def visit(items: list[Any], parent_id: str | None, level: int, path: tuple[int, ...]) -> None:
        order_index = 0
        previous_entry: TocEntry | None = None
        for item in items:
            if isinstance(item, list):
                if previous_entry is None:
                    raise InvalidProviderResponse("open textbook PDF outline has orphan children")
                visit(
                    item,
                    previous_entry.toc_entry_id,
                    level + 1,
                    (*path, previous_entry.order_index),
                )
                continue
            title = getattr(item, "title", None)
            if not isinstance(title, str) or not title.strip():
                raise InvalidProviderResponse("open textbook PDF outline has an empty title")
            page_index = reader.get_destination_page_number(item)
            if page_index is None or page_index < 0 or page_index >= len(reader.pages):
                raise InvalidProviderResponse(
                    "open textbook PDF outline has an invalid destination"
                )
            normalized_title = " ".join(title.split())
            entry = TocEntry(
                toc_entry_id=stable_id(
                    "toc",
                    book_id,
                    source_id,
                    *(str(index) for index in (*path, order_index)),
                    normalized_title,
                ),
                book_id=book_id,
                parent_entry_id=parent_id,
                level=level,
                order_index=order_index,
                label=None,
                title=normalized_title,
                source_id=source_id,
            )
            entries.append(entry)
            previous_entry = entry
            order_index += 1

    outline = reader.outline
    if not isinstance(outline, list):
        raise InvalidProviderResponse("open textbook PDF is missing a bookmark outline")
    visit(outline, None, 1, ())
    return entries


def _hefferon_description(tree: HTMLParser) -> str:
    """Extract the concise author-written description from the textbook home page."""
    for paragraph in tree.css("p"):
        text = " ".join(paragraph.text(separator=" ", strip=True).split())
        if text.startswith("Linear Algebra by Jim Hefferon is a text"):
            return text
    raise InvalidProviderResponse("Hefferon home page is missing its reviewed description")


def _normalize_hefferon_response(
    response: dict[str, Any], source_spec: OpenTextbookSourceSpec, retrieved_at: datetime
) -> CanonicalDataset:
    """Normalize Hefferon's fourth-edition PDF outline and selected public text."""
    if source_spec.license_url is None or source_spec.license is None:
        raise InvalidProviderResponse("Hefferon allowlist license metadata is incomplete")
    if response.get("home_url") != source_spec.home_url:
        raise InvalidProviderResponse("Hefferon home URL does not match allowlist")
    if response.get("license_url") != source_spec.license_url:
        raise InvalidProviderResponse("Hefferon license URL does not match allowlist")
    home_html = response.get("home_html")
    license_html = response.get("license_html")
    raw_documents = response.get("documents")
    if (
        not isinstance(home_html, str)
        or not isinstance(license_html, str)
        or not isinstance(raw_documents, list)
    ):
        raise InvalidProviderResponse("Hefferon response has invalid content fields")
    if len(raw_documents) != 1 or len(source_spec.documents) != 1:
        raise InvalidProviderResponse("Hefferon response must contain one reviewed PDF")

    tree = HTMLParser(home_html)
    license_links = {
        urljoin(source_spec.home_url, link.attributes["href"]) for link in tree.css("a[href]")
    }
    if source_spec.license_url not in license_links:
        raise InvalidProviderResponse("Hefferon license page is not linked from the home page")
    home_text = tree.root.text(separator=" ", strip=True)
    normalized_home = normalize_bibliographic_text(home_text)
    if any(
        normalize_bibliographic_text(marker) not in normalized_home
        for marker in (source_spec.title, *source_spec.authors, "first undergraduate course")
    ):
        raise InvalidProviderResponse("Hefferon home page does not match the reviewed book")
    description = _hefferon_description(tree)

    license_text = HTMLParser(license_html).root.text(separator=" ", strip=True)
    normalized_license = normalize_bibliographic_text(license_text)
    license_markers = (
        source_spec.title,
        "GNU Free Documentation License",
        "Creative Commons Attribution-ShareAlike 3.0 United States License",
    )
    if any(
        normalize_bibliographic_text(marker) not in normalized_license for marker in license_markers
    ):
        raise InvalidProviderResponse("Hefferon license page does not match the reviewed terms")

    raw_document = raw_documents[0]
    document_spec = source_spec.documents[0]
    if not isinstance(raw_document, dict) or raw_document.get("url") != document_spec.url:
        raise InvalidProviderResponse("Hefferon PDF URL does not match allowlist")
    if raw_document.get("media_type") != "application/pdf":
        raise InvalidProviderResponse("Hefferon PDF has an invalid media type")
    encoded_content = raw_document.get("content_base64")
    if not isinstance(encoded_content, str):
        raise InvalidProviderResponse("Hefferon PDF is missing base64 content")
    try:
        content = base64.b64decode(encoded_content, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise InvalidProviderResponse("Hefferon PDF contains invalid base64") from exc
    if not content.startswith(b"%PDF-"):
        raise InvalidProviderResponse("Hefferon document content is not a PDF")
    if len(content) > source_spec.max_resource_bytes:
        raise InvalidProviderResponse("Hefferon PDF exceeds its reviewed size limit")

    try:
        reader = PdfReader(BytesIO(content))
        if (
            source_spec.expected_page_count is None
            or len(reader.pages) != source_spec.expected_page_count
        ):
            raise InvalidProviderResponse("Hefferon PDF page count does not match review")
        first_page = _reader_page_text(reader, 0, 1, "identity page")
        normalized_first_page = normalize_bibliographic_text(first_page)
        if any(
            normalize_bibliographic_text(marker) not in normalized_first_page
            for marker in document_spec.identity_text_markers
        ):
            raise InvalidProviderResponse("Hefferon PDF identity does not match the reviewed book")
        metadata = reader.metadata or {}
        if normalize_bibliographic_text(
            str(metadata.get("/Title", ""))
        ) != normalize_bibliographic_text(source_spec.title) or normalize_bibliographic_text(
            source_spec.authors[0]
        ) not in normalize_bibliographic_text(str(metadata.get("/Author", ""))):
            raise InvalidProviderResponse("Hefferon PDF metadata does not match the reviewed book")

        pdf_source_id = stable_id(
            "source", source_spec.provider, document_spec.url, source_spec.book_id
        )
        toc = _pdf_outline_toc(reader, source_spec.book_id, pdf_source_id)
        roots = [entry for entry in toc if entry.parent_entry_id is None]
        expected_roots = [
            "Linear Systems",
            "Vector Spaces",
            "Maps Between Spaces",
            "Determinants",
            "Similarity",
            "Appendix",
        ]
        level_counts = {level: sum(entry.level == level for entry in toc) for level in (1, 2, 3)}
        if (
            len(toc) != 96
            or [entry.title for entry in roots] != expected_roots
            or level_counts != {1: 6, 2: 46, 3: 44}
            or any(entry.level > 3 for entry in toc)
        ):
            raise InvalidProviderResponse("Hefferon PDF outline does not match review")
        root_destinations = [item for item in reader.outline if not isinstance(item, list)]
        first_chapter_start = reader.get_destination_page_number(root_destinations[0])
        second_chapter_start = reader.get_destination_page_number(root_destinations[1])
        if first_chapter_start is None or second_chapter_start is None:
            raise InvalidProviderResponse("Hefferon PDF chapter destinations are missing")
        if source_spec.preface_page_range is None:
            raise InvalidProviderResponse("Hefferon preface page range is not configured")
        preface = _reader_page_text(
            reader, *source_spec.preface_page_range, document_name="preface"
        )
        sample = _reader_page_text(
            reader, first_chapter_start, second_chapter_start, "sample chapter"
        )
    except InvalidProviderResponse:
        raise
    except (PdfReadError, ValueError) as exc:
        raise InvalidProviderResponse(f"Hefferon PDF could not be parsed: {exc}") from exc

    for document_name, text, markers in (
        ("preface", preface, document_spec.preface_text_markers),
        ("sample chapter", sample, document_spec.sample_text_markers),
    ):
        normalized_text = normalize_bibliographic_text(text)
        if any(normalize_bibliographic_text(marker) not in normalized_text for marker in markers):
            raise InvalidProviderResponse(f"Hefferon {document_name} text does not match review")

    expected_book_id = stable_id(
        "book",
        normalize_bibliographic_text(source_spec.title),
        normalize_bibliographic_text(source_spec.authors[0]),
    )
    if source_spec.book_id != expected_book_id:
        raise InvalidProviderResponse("Hefferon fallback book ID is not deterministic")
    rights_note = "The author's license page explicitly applies these terms to Linear Algebra."
    home_source_id = stable_id(
        "source", source_spec.provider, source_spec.home_url, source_spec.book_id
    )
    license_source_id = stable_id(
        "source", source_spec.provider, source_spec.license_url, source_spec.book_id
    )
    sources = [
        Source(
            source_id=home_source_id,
            book_id=source_spec.book_id,
            provider=source_spec.provider,
            source_type="author_page",
            url=source_spec.home_url,
            external_id=f"{source_spec.slug}:home",
            retrieved_at=retrieved_at,
            license=source_spec.license,
            rights_note=rights_note,
            content_hash=sha256_text(home_html),
        ),
        Source(
            source_id=license_source_id,
            book_id=source_spec.book_id,
            provider=source_spec.provider,
            source_type="author_page",
            url=source_spec.license_url,
            external_id=f"{source_spec.slug}:license",
            retrieved_at=retrieved_at,
            license=source_spec.license,
            rights_note=rights_note,
            content_hash=sha256_text(license_html),
        ),
        Source(
            source_id=pdf_source_id,
            book_id=source_spec.book_id,
            provider=source_spec.provider,
            source_type="open_textbook",
            url=document_spec.url,
            external_id=document_spec.external_id,
            retrieved_at=retrieved_at,
            license=source_spec.license,
            rights_note=rights_note,
            content_hash=sha256_bytes(content),
        ),
    ]
    documents = [
        Document(
            document_id=stable_id("doc", source_spec.book_id, "description", home_source_id),
            book_id=source_spec.book_id,
            document_type="description",
            text=description,
            source_id=home_source_id,
            content_hash=sha256_text(description),
        ),
        Document(
            document_id=stable_id("doc", source_spec.book_id, "preface", pdf_source_id),
            book_id=source_spec.book_id,
            document_type="preface",
            text=preface,
            source_id=pdf_source_id,
            content_hash=sha256_text(preface),
        ),
        Document(
            document_id=stable_id("doc", source_spec.book_id, "sample_chapter", pdf_source_id),
            book_id=source_spec.book_id,
            document_type="sample_chapter",
            text=sample,
            source_id=pdf_source_id,
            content_hash=sha256_text(sample),
        ),
    ]
    book = Book(
        book_id=source_spec.book_id,
        isbn_10=None,
        isbn_13=None,
        title=source_spec.title,
        subtitle=None,
        authors=list(source_spec.authors),
        publisher=None,
        published_year=source_spec.published_year,
        language="en",
        topics=TOPICS[source_spec.topic],
    )
    return CanonicalDataset(books=[book], documents=documents, toc=toc, sources=sources)


def normalize_open_textbook_response(
    response: dict[str, Any], *, topic: str, retrieved_at: datetime
) -> CanonicalDataset:
    """Normalize one reviewed open textbook page and its public PDF evidence."""
    source_slug = response.get("source_slug")
    if not isinstance(source_slug, str):
        raise InvalidProviderResponse("open textbook response is missing source_slug")
    try:
        source_spec = open_textbook_source(source_slug)
    except ValueError as exc:
        raise InvalidProviderResponse(str(exc)) from exc
    if topic != source_spec.topic:
        raise InvalidProviderResponse("open textbook response topic does not match its allowlist")
    if source_spec.source_format == "hefferon_pdf_outline":
        return _normalize_hefferon_response(response, source_spec, retrieved_at)
    if source_spec.source_format != "ostep_chapter_pdfs":
        raise InvalidProviderResponse("open textbook source format is unsupported")
    if response.get("home_url") != source_spec.home_url:
        raise InvalidProviderResponse("open textbook home URL does not match allowlist")
    home_html = response.get("home_html")
    raw_documents = response.get("documents")
    if not isinstance(home_html, str) or not isinstance(raw_documents, list):
        raise InvalidProviderResponse("open textbook response has invalid content fields")

    tree = HTMLParser(home_html)
    home_text = tree.root.text(separator=" ", strip=True)
    normalized_home = normalize_bibliographic_text(home_text)
    if source_spec.publisher is None or source_spec.version is None or source_spec.isbn_10 is None:
        raise InvalidProviderResponse("OSTEP allowlist identity is incomplete")
    identity_markers = (
        source_spec.title,
        *source_spec.authors,
        source_spec.publisher,
        source_spec.version,
    )
    if (
        any(
            normalize_bibliographic_text(marker) not in normalized_home
            for marker in identity_markers
        )
        or source_spec.isbn_10 not in home_html
    ):
        raise InvalidProviderResponse("open textbook page does not match the reviewed book")
    if str(source_spec.published_year) not in home_text:
        raise InvalidProviderResponse("open textbook page does not match the reviewed publication")

    home_source_id = stable_id(
        "source", source_spec.provider, source_spec.home_url, source_spec.book_id
    )
    home_source = Source(
        source_id=home_source_id,
        book_id=source_spec.book_id,
        provider=source_spec.provider,
        source_type="open_textbook",
        url=source_spec.home_url,
        external_id=source_spec.slug,
        retrieved_at=retrieved_at,
        license=None,
        rights_note=(
            "Author-hosted page states that the book chapters are free online; "
            "no reuse license was identified."
        ),
        content_hash=sha256_text(home_html),
    )
    book = Book(
        book_id=source_spec.book_id,
        isbn_10=source_spec.isbn_10,
        isbn_13=source_spec.isbn_13,
        title=source_spec.title,
        subtitle=None,
        authors=list(source_spec.authors),
        publisher=source_spec.publisher,
        published_year=source_spec.published_year,
        language="en",
        topics=TOPICS[topic],
    )
    description = _ostep_description(tree)
    documents = [
        Document(
            document_id=stable_id("doc", source_spec.book_id, "description", home_source_id),
            book_id=source_spec.book_id,
            document_type="description",
            text=description,
            source_id=home_source_id,
            content_hash=sha256_text(description),
        )
    ]
    toc = _ostep_toc(home_html, source_spec.book_id, home_source_id)
    sources = [home_source]

    expected_documents = {document.url: document for document in source_spec.documents}
    if any(document.url.rsplit("/", 1)[-1] not in home_html for document in source_spec.documents):
        raise InvalidProviderResponse(
            "open textbook document is not linked from its reviewed home page"
        )
    if len(raw_documents) != len(expected_documents):
        raise InvalidProviderResponse("open textbook response has an unexpected document count")
    seen_urls: set[str] = set()
    for raw_document in raw_documents:
        if not isinstance(raw_document, dict):
            raise InvalidProviderResponse("open textbook response contains an invalid document")
        url = raw_document.get("url")
        if not isinstance(url, str) or url not in expected_documents or url in seen_urls:
            raise InvalidProviderResponse("open textbook document URL does not match allowlist")
        seen_urls.add(url)
        if raw_document.get("media_type") != "application/pdf":
            raise InvalidProviderResponse("open textbook document has an invalid media type")
        encoded_content = raw_document.get("content_base64")
        if not isinstance(encoded_content, str):
            raise InvalidProviderResponse("open textbook document is missing base64 content")
        try:
            content = base64.b64decode(encoded_content, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise InvalidProviderResponse("open textbook document contains invalid base64") from exc
        if not content.startswith(b"%PDF-"):
            raise InvalidProviderResponse("open textbook document content is not a PDF")
        if len(content) > source_spec.max_resource_bytes:
            raise InvalidProviderResponse("open textbook PDF exceeds its reviewed size limit")

        document_spec = expected_documents[url]
        text = _extract_pdf_text(content)
        normalized_text = normalize_bibliographic_text(text)
        if any(
            normalize_bibliographic_text(marker) not in normalized_text
            for marker in document_spec.expected_text_markers
        ):
            raise InvalidProviderResponse(
                f"open textbook PDF does not match reviewed document: {document_spec.document_type}"
            )
        source_id = stable_id("source", source_spec.provider, url, source_spec.book_id)
        sources.append(
            Source(
                source_id=source_id,
                book_id=source_spec.book_id,
                provider=source_spec.provider,
                source_type="open_textbook",
                url=url,
                external_id=document_spec.external_id,
                retrieved_at=retrieved_at,
                license=None,
                rights_note=(
                    "Public PDF linked as a free book chapter from the author-hosted page; "
                    "no reuse license was identified."
                ),
                content_hash=sha256_bytes(content),
            )
        )
        documents.append(
            Document(
                document_id=stable_id(
                    "doc", source_spec.book_id, document_spec.document_type, source_id
                ),
                book_id=source_spec.book_id,
                document_type=document_spec.document_type,
                text=text,
                source_id=source_id,
                content_hash=sha256_text(text),
            )
        )
    return CanonicalDataset(books=[book], documents=documents, toc=toc, sources=sources)


def _public_page_section(tree: HTMLParser, heading: str) -> Any:
    """Return the content element immediately following a named catalog heading."""
    for candidate in tree.css("div.summary h2"):
        if candidate.text(separator=" ", strip=True).casefold() != heading.casefold():
            continue
        content = candidate.next
        while content is not None and content.tag == "-text":
            content = content.next
        classes = content.attributes.get("class", "").split() if content is not None else []
        if content is not None and content.tag == "div" and "content" in classes:
            return content
    raise InvalidProviderResponse(f"public book page is missing its {heading} section")


def _direct_table_rows(table: Any) -> list[Any]:
    """Return rows owned by one table, excluding rows from nested indentation tables."""
    body = table.css_first("tbody")
    if body is None:
        return []
    return [row for row in table.css("tr") if row.parent.mem_id == body.mem_id]


def _indented_table_toc_entries(html: str, book_id: str, source_id: str) -> list[TocEntry]:
    """Parse eCampus TOC indentation into explicit canonical parent relationships."""
    tree = HTMLParser(html)
    content = _public_page_section(tree, "Table of Contents")
    table = content.css_first("table")
    if table is None:
        raise InvalidProviderResponse("public book page TOC section contained no table")

    entries: list[TocEntry] = []
    hierarchy: list[tuple[int, TocEntry]] = []
    for row in _direct_table_rows(table):
        cells = [cell for cell in row.css("td") if cell.parent.mem_id == row.mem_id]
        if not cells:
            continue
        first_cell = cells[0]
        nested_table = first_cell.css_first("table")
        if nested_table is None:
            indent = 0
            title = first_cell.text(separator=" ", strip=True)
        else:
            nested_cells = nested_table.css("td")
            if len(nested_cells) < 2:
                raise InvalidProviderResponse("public book page TOC contained a malformed row")
            width = nested_cells[0].attributes.get("width", "")
            if not width.isdigit():
                raise InvalidProviderResponse("public book page TOC contained an invalid indent")
            indent = int(width)
            title = nested_cells[-1].text(separator=" ", strip=True)
        if not title:
            raise InvalidProviderResponse("public book page TOC contained an empty title")

        # Numbered chapter appendices are siblings of chapter sections even though
        # this catalog page renders them one indentation step deeper.
        if re.match(r"^Appendix\s+\d+[A-Z]\b", title, flags=re.IGNORECASE):
            indent = 40
        while hierarchy and hierarchy[-1][0] >= indent:
            hierarchy.pop()
        parent = hierarchy[-1][1] if hierarchy else None
        level = parent.level + 1 if parent is not None else 1
        order_index = len(entries)
        entry = TocEntry(
            toc_entry_id=stable_id("toc", book_id, source_id, str(order_index), str(indent), title),
            book_id=book_id,
            parent_entry_id=parent.toc_entry_id if parent is not None else None,
            level=level,
            order_index=order_index,
            label=None,
            title=title,
            source_id=source_id,
        )
        entries.append(entry)
        hierarchy.append((indent, entry))
    return entries


def _heading_sequence_toc_entries(html: str, book_id: str, source_id: str) -> list[TocEntry]:
    """Parse an ordered Part/Chapter heading sequence into two TOC levels."""
    tree = HTMLParser(html)
    content = _public_page_section(tree, "Table of Contents")
    entries: list[TocEntry] = []
    current_part: TocEntry | None = None
    for heading in content.css("h3"):
        text = heading.text(separator=" ", strip=True)
        part_match = re.fullmatch(r"(Part\s+[A-Za-z]+):\s*(.+)", text)
        chapter_match = re.fullmatch(r"(\d+)\s+(.+)", text)
        order_index = len(entries)
        if part_match is not None:
            label = part_match.group(1)
            title = part_match.group(2).strip()
            parent_entry_id = None
            level = 1
        elif chapter_match is not None and current_part is not None:
            label = chapter_match.group(1)
            title = chapter_match.group(2).strip()
            parent_entry_id = current_part.toc_entry_id
            level = 2
        else:
            raise InvalidProviderResponse(
                f"public book page TOC contained an unsupported heading: {text!r}"
            )
        entry = TocEntry(
            toc_entry_id=stable_id("toc", book_id, source_id, str(order_index), label, title),
            book_id=book_id,
            parent_entry_id=parent_entry_id,
            level=level,
            order_index=order_index,
            label=label,
            title=title,
            source_id=source_id,
        )
        entries.append(entry)
        if level == 1:
            current_part = entry
    return entries


def normalize_public_book_page_response(
    response: dict[str, Any], *, topic: str, retrieved_at: datetime
) -> CanonicalDataset:
    """Normalize one reviewed exact-edition public catalog page."""
    source_slug = response.get("source_slug")
    if not isinstance(source_slug, str):
        raise InvalidProviderResponse("public book response is missing source_slug")
    try:
        source_spec = public_book_source(source_slug)
    except ValueError as exc:
        raise InvalidProviderResponse(str(exc)) from exc
    if topic != source_spec.topic:
        raise InvalidProviderResponse(
            "public book response topic does not match its allowlist entry"
        )
    if response.get("url") != source_spec.url:
        raise InvalidProviderResponse("public book response URL does not match allowlist")
    html = response.get("html")
    if not isinstance(html, str):
        raise InvalidProviderResponse("public book response must contain an HTML string")

    tree = HTMLParser(html)
    title_node = tree.css_first("h1.title")
    isbn_node = tree.css_first('[itemprop="isbn"]')
    edition_node = tree.css_first('[itemprop="bookEdition"]')
    page_title = title_node.text(separator=" ", strip=True) if title_node is not None else ""
    page_isbn = isbn_node.text(separator=" ", strip=True) if isbn_node is not None else ""
    page_edition = edition_node.text(separator=" ", strip=True) if edition_node is not None else ""
    if (
        normalize_bibliographic_text(page_title) != normalize_bibliographic_text(source_spec.title)
        or page_isbn != source_spec.isbn_13
    ):
        raise InvalidProviderResponse("public book identity page does not match the expected book")
    if source_spec.edition not in _edition_numbers(f"{page_edition} edition"):
        raise InvalidProviderResponse(
            "public book identity page does not match the expected edition"
        )

    source_id = stable_id("source", source_spec.provider, source_spec.url, source_spec.book_id)
    if source_spec.toc_format == "indented_table":
        toc = _indented_table_toc_entries(html, source_spec.book_id, source_id)
    else:
        toc = _heading_sequence_toc_entries(html, source_spec.book_id, source_id)
    if len(toc) != source_spec.expected_toc_count:
        raise InvalidProviderResponse(
            "public book page TOC is incomplete or does not match the reviewed entry count"
        )
    root_titles = tuple(entry.title for entry in toc if entry.parent_entry_id is None)
    if root_titles != source_spec.expected_root_titles:
        raise InvalidProviderResponse(
            "public book page TOC does not match the reviewed top-level structure"
        )
    chapter_labels = tuple(entry.label for entry in toc if entry.level == 2 and entry.label)
    if (
        source_spec.expected_chapter_labels
        and chapter_labels != source_spec.expected_chapter_labels
    ):
        raise InvalidProviderResponse(
            "public book page TOC does not match the reviewed chapter sequence"
        )

    description = _public_page_section(tree, "Summary").text(separator=" ", strip=True)
    if not description:
        raise InvalidProviderResponse("public book page contained an empty summary")
    document = Document(
        document_id=stable_id("doc", source_spec.book_id, "description", source_id),
        book_id=source_spec.book_id,
        document_type="description",
        text=description,
        source_id=source_id,
        content_hash=sha256_text(description),
    )
    source = Source(
        source_id=source_id,
        book_id=source_spec.book_id,
        provider=source_spec.provider,
        source_type="other",
        url=source_spec.url,
        external_id=source_spec.isbn_13,
        retrieved_at=retrieved_at,
        license=None,
        rights_note="Public bookstore catalog page; no license statement found.",
        content_hash=sha256_text(html),
    )
    return CanonicalDataset(books=[], documents=[document], toc=toc, sources=[source])
