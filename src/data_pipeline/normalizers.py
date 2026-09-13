"""Normalization of provider responses into canonical evidence records."""

import logging
import re
from datetime import datetime
from typing import Any

from pydantic import ValidationError

from data_pipeline.collectors.base import InvalidProviderResponse
from data_pipeline.identifiers import (
    is_valid_isbn_10,
    is_valid_isbn_13,
    normalize_bibliographic_text,
    sha256_json,
    sha256_text,
    stable_id,
)
from data_pipeline.models import Book, CanonicalDataset, Document, Source, TocEntry

logger = logging.getLogger(__name__)

TOPICS: dict[str, list[str]] = {
    "operating-systems": ["computer-science", "operating-systems"],
    "linear-algebra": ["mathematics", "linear-algebra"],
}
MAX_AUTHORS_PER_BOOK = 8


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

    raw_levels = [
        item.get("level")
        for item in value
        if isinstance(item, dict)
        and isinstance(item.get("level"), int)
        and not isinstance(item.get("level"), bool)
    ]
    if not raw_levels:
        return []
    base_level = min(raw_levels)
    latest_by_level: dict[int, str] = {}
    sibling_counts: dict[str | None, int] = {}
    entries: list[TocEntry] = []

    for raw_index, item in enumerate(value):
        if not isinstance(item, dict):
            logger.warning(
                "event=toc_entry_skipped provider=open_library book_id=%s "
                "raw_index=%d reason=not_an_object",
                book_id,
                raw_index,
            )
            continue
        title = item.get("title")
        raw_level = item.get("level")
        if (
            not isinstance(title, str)
            or not title.strip()
            or not isinstance(raw_level, int)
            or isinstance(raw_level, bool)
            or raw_level < base_level
        ):
            logger.warning(
                "event=toc_entry_skipped provider=open_library book_id=%s "
                "raw_index=%d reason=invalid_title_or_level",
                book_id,
                raw_index,
            )
            continue

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
    if edition_description is not None:
        document = _open_library_description(edition_description, book_id, source_id)
        documents.append(document)
        description_hashes.add(document.content_hash)

    work_description = _open_library_text(work_detail.get("description"))
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
            url=f"https://openlibrary.org{work_id}",
            external_id=work_id,
            retrieved_at=retrieved_at,
            license=None,
            rights_note=None,
            content_hash=sha256_json(work_detail),
        )
        sources.append(work_source)
        documents.append(_open_library_description(work_description, book_id, work_source_id))

    toc = _normalize_open_library_toc(edition_detail.get("table_of_contents"), book_id, source_id)
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
