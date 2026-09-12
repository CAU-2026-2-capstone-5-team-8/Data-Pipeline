"""Normalization of Google Books records into canonical evidence records."""

import re
from datetime import datetime
from typing import Any

from data_pipeline.identifiers import (
    normalize_bibliographic_text,
    sha256_json,
    sha256_text,
    stable_id,
)
from data_pipeline.models import Book, CanonicalDataset, Document, Source

TOPICS: dict[str, list[str]] = {
    "operating-systems": ["computer-science", "operating-systems"],
    "linear-algebra": ["mathematics", "linear-algebra"],
}


def normalize_isbn(value: str | None, length: int) -> str | None:
    if not value:
        return None
    cleaned = re.sub(r"[^0-9Xx]", "", value).upper()
    if len(cleaned) != length:
        return None
    return cleaned


def _isbns(volume_info: dict[str, Any]) -> tuple[str | None, str | None]:
    isbn_10 = None
    isbn_13 = None
    for identifier in volume_info.get("industryIdentifiers", []):
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
    external_id: str,
) -> str:
    if isbn_13:
        return f"isbn13:{isbn_13}"
    if isbn_10:
        return f"isbn10:{isbn_10}"
    if title and authors:
        return stable_id(
            "book",
            normalize_bibliographic_text(title),
            normalize_bibliographic_text(authors[0]),
        )
    return stable_id("book", "google_books", external_id)


def _published_year(value: str | None) -> int | None:
    if not value:
        return None
    match = re.match(r"^(\d{4})", value)
    return int(match.group(1)) if match else None


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

    for item in response.get("items", []):
        info = item.get("volumeInfo", {})
        external_id = str(item.get("id", "")).strip()
        title = str(info.get("title", "")).strip()
        language = str(info.get("language", "")).lower()
        if not external_id or not title or language != "en":
            continue

        authors = [str(author).strip() for author in info.get("authors", []) if str(author).strip()]
        isbn_10, isbn_13 = _isbns(info)
        book_id = _book_id(isbn_10, isbn_13, title, authors, external_id)
        if book_id in seen_books:
            continue

        source_id = stable_id("source", "google_books", external_id, book_id)
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
        if isinstance(description, str) and description.strip():
            text = description.strip()
            documents.append(
                Document(
                    document_id=stable_id("doc", book_id, "description", source_id),
                    book_id=book_id,
                    document_type="description",
                    text=text,
                    source_id=source_id,
                    content_hash=sha256_text(text),
                )
            )

        seen_books.add(book_id)
        books.append(book)
        sources.append(source)
        if len(books) >= limit:
            break

    return CanonicalDataset(books=books, documents=documents, toc=[], sources=sources)


def _open_library_isbns(record: dict[str, Any]) -> tuple[str | None, str | None]:
    values = {str(value) for value in record.get("isbn", [])}
    isbn_10_values = sorted(filter(None, (normalize_isbn(value, 10) for value in values)))
    isbn_13_values = sorted(filter(None, (normalize_isbn(value, 13) for value in values)))
    return (
        isbn_10_values[0] if isbn_10_values else None,
        isbn_13_values[0] if isbn_13_values else None,
    )


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
    sources: list[Source] = []
    seen_books: set[str] = set()
    for record in response.get("docs", []):
        work_id = str(record.get("key", "")).strip()
        edition_records = record.get("editions", {}).get("docs", [])
        edition = next(
            (item for item in edition_records if "eng" in item.get("language", [])),
            edition_records[0] if edition_records else {},
        )
        external_id = str(edition.get("key") or work_id).strip()
        title = str(edition.get("title") or record.get("title", "")).strip()
        languages = record.get("language", [])
        if not external_id or not title or "eng" not in languages:
            continue

        authors = [
            str(author).strip() for author in record.get("author_name", []) if str(author).strip()
        ]
        isbn_10, isbn_13 = _open_library_isbns(edition)
        book_id = _book_id(isbn_10, isbn_13, title, authors, external_id)
        if book_id in seen_books:
            continue

        source_id = stable_id("source", "open_library", external_id, book_id)
        publisher_values = edition.get("publisher", [])
        publisher = str(publisher_values[0]).strip() if publisher_values else None
        publish_dates = edition.get("publish_date", [])
        published_year = _published_year(str(publish_dates[0])) if publish_dates else None
        books.append(
            Book(
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
        )
        sources.append(
            Source(
                source_id=source_id,
                book_id=book_id,
                provider="open_library",
                source_type="metadata_api",
                url=f"https://openlibrary.org{external_id}",
                external_id=external_id,
                retrieved_at=retrieved_at,
                license=None,
                rights_note=None,
                content_hash=sha256_json(record),
            )
        )
        seen_books.add(book_id)
        if len(books) >= limit:
            break

    return CanonicalDataset(books=books, documents=[], toc=[], sources=sources)
