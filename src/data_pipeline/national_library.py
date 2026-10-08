"""Normalize ISBN bibliography evidence without inventing language, level, or taxonomy."""

import re
from datetime import datetime
from html import unescape
from typing import Any
from urllib.parse import urlencode

from selectolax.parser import HTMLParser

from data_pipeline.collection_scope import CollectionScope
from data_pipeline.collectors.national_library import API_URL, bibliography_rows
from data_pipeline.identifiers import isbn_10_to_13, sha256_json, sha256_text, stable_id
from data_pipeline.models import Book, CanonicalDataset, Document, Source
from data_pipeline.normalizers import _parse_yes24_toc, normalize_isbn
from data_pipeline.topics import TopicSpec


def _text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    value = re.sub(r"<(?:br\s*/?|/p|/div|/li)\s*>", "\n", value, flags=re.I)
    return unescape(HTMLParser(value).text()).strip()


def normalize_national_library_response(
    response: dict,
    scope: CollectionScope,
    spec: TopicSpec,
    retrieved_at: datetime,
    limit: int = 20,
) -> tuple[CanonicalDataset, list[dict]]:
    books, documents, toc, sources, audit = [], [], [], [], []
    seen = set()
    for row in bibliography_rows(response):
        if not isinstance(row, dict):
            audit.append({"included": False, "reason": "invalid_record"})
            continue
        isbn10 = normalize_isbn(row.get("EA_ISBN"), 10)
        isbn13 = normalize_isbn(row.get("EA_ISBN"), 13)
        if isbn10 and not isbn13:
            isbn13 = isbn_10_to_13(isbn10)
        title = _text(row.get("TITLE"))
        subject = _text(row.get("SUBJECT"))
        evidence = title + " | " + subject
        reason = "matching_title_or_subject"
        pattern = spec.korean_relevance_term_pattern or re.escape(scope.query)
        if not (isbn10 or isbn13):
            reason = "missing_valid_isbn"
        elif not title:
            reason = "missing_title"
        elif not re.search(pattern, evidence, re.I):
            reason = "no_topic_evidence"
        elif spec.korean_conflicting_subjects_pattern and re.search(
            spec.korean_conflicting_subjects_pattern, evidence, re.I
        ):
            reason = "conflicting_subject"
        elif scope.book_kind or scope.audience or scope.category_subject_pattern:
            # A keyword match alone cannot establish a retailer's audience/book-kind category.
            reason = "category_constraints_unconfirmed"
        elif row.get("EBOOK_YN") == "Y":
            reason = "conflicting_book_kind"
        book_id = f"isbn13:{isbn13}" if isbn13 else f"isbn10:{isbn10}"
        if reason == "matching_title_or_subject":
            if book_id in seen:
                reason = "duplicate_isbn"
            elif len(books) >= limit:
                reason = "normalization_limit"
        included = reason == "matching_title_or_subject"
        audit.append(
            {
                "isbn": isbn13 or isbn10,
                "title": title,
                "KDC": row.get("KDC"),
                "DDC": row.get("DDC"),
                "SUBJECT": row.get("SUBJECT"),
                "included": included,
                "reason": reason,
            }
        )
        if not included:
            continue
        seen.add(book_id)
        # The API does not declare language or actual publication date. Preserve unknowns.
        books.append(
            Book(
                book_id=book_id,
                isbn_10=isbn10,
                isbn_13=isbn13,
                title=title,
                authors=[author for author in [_text(row.get("AUTHOR"))] if author],
                publisher=_text(row.get("PUBLISHER")) or None,
                language="und",
                topics=[spec.domain, spec.slug],
            )
        )
        url = API_URL + "?" + urlencode({"isbn": isbn13 or isbn10, "result_style": "json"})
        source_id = stable_id("source", book_id, "national_library", url)
        sources.append(
            Source(
                source_id=source_id,
                book_id=book_id,
                provider="national_library",
                source_type="metadata_api",
                url=url,
                external_id=isbn13 or isbn10,
                retrieved_at=retrieved_at,
                content_hash=sha256_json(row),
            )
        )
        for field, document_type in (
            ("BOOK_INTRODUCTION", "description"),
            ("BOOK_SUMMARY", "other"),
        ):
            text = _text(row.get(field))
            if text:
                documents.append(
                    Document(
                        document_id=stable_id("doc", book_id, document_type, source_id),
                        book_id=book_id,
                        document_type=document_type,
                        text=text,
                        source_id=source_id,
                        content_hash=sha256_text(text),
                    )
                )
        text = _text(row.get("BOOK_TB_CNT"))
        if text:
            toc.extend(_parse_yes24_toc(text, book_id, source_id))
    return CanonicalDataset(books=books, documents=documents, toc=toc, sources=sources), audit
