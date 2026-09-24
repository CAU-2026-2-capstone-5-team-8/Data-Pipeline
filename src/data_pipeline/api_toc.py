"""Normalize ISBN-keyed bookstore/publisher API TOC responses into canonical evidence.

Both providers are looked up by a canonical book's own ISBN, so a match is exact-edition
evidence. Only TOC titles become canonical records; descriptions and chapter abstracts
stay in the preserved raw response and are never copied into documents.
"""

import html
import re
from datetime import datetime
from typing import Any

from data_pipeline.collectors.base import InvalidProviderResponse
from data_pipeline.identifiers import sha256_json, sha256_text, stable_id
from data_pipeline.models import Book, CanonicalDataset, EvidenceProvenance, Source, TocEntry

MIN_TOC_ENTRIES = 3
# GOODS_001: the product has no TOC; GOODS_002: no product for the ISBN.
YES24_NO_TOC_ERRORS = {"GOODS_001", "GOODS_002"}
YES24_PRODUCT_URL = "https://www.yes24.com/product/goods/{item_id}"
YES24_RIGHTS_NOTE = (
    "TOC from the YES24 Open API. YES24 terms require a 'YES24 출처' attribution and a link "
    "to the product page, and prohibit accumulating its catalog into a separate database or "
    "redistributing it. No license inferred."
)

_TAG = re.compile(r"<[^>]+>")
_LINE_BREAK_TAG = re.compile(r"<\s*(?:br|/p|p|/li|/div|/h[1-6])\b[^>]*>", re.IGNORECASE)
_PAGE_NUMBER = re.compile(r"^(?:\d+|[ivxlcdm]+)$", re.IGNORECASE)
_NUMBER_LABEL = re.compile(r"^\d+(?:\.\d+)*\.?$")
_LABELED_LINE = re.compile(
    r"^(?:chapter\s+)?(?P<label>\d+(?:\.\d+)*)(?:\.(?!\d)|\s*장)?\s+(?P<title>\S.*)$",
    re.IGNORECASE,
)
_PART_LINE = re.compile(r"^(?:part\b|제\s*\d+\s*부\b|\d+\s*부\b)", re.IGNORECASE)
_SPRINGER_CHAPTER_DOI = re.compile(r"^10\.1007/(?P<isbn>[0-9-]+X?)_(?P<number>\d+)$")


def _clean_title(value: str) -> str:
    return " ".join(value.split()).strip(" .")


def _text_lines(contents: str) -> list[str]:
    """Turn YES24's mixed plain-text/HTML TOC into logical lines, keeping tab columns."""
    text = _LINE_BREAK_TAG.sub("\n", contents)
    text = html.unescape(_TAG.sub("", text))
    lines = [line.strip("  ") for line in text.replace("\r", "\n").split("\n")]
    lines = [line for line in lines if re.search(r"\w", line)]
    merged: list[str] = []
    for line in lines:
        if merged and merged[-1].strip().casefold() == "chapter":
            merged[-1] = f"Chapter {line.strip()}"
        else:
            merged.append(line)
    return merged


def _split_line(line: str) -> tuple[str | None, str]:
    """Return (numeric label, title), dropping a trailing tab-separated page number."""
    fields = [field.strip() for field in line.split("\t") if field.strip()]
    if len(fields) > 1 and _PAGE_NUMBER.match(fields[-1]):
        fields = fields[:-1]
    if len(fields) > 1 and _NUMBER_LABEL.match(fields[0]):
        return fields[0].rstrip("."), _clean_title(" ".join(fields[1:]))
    joined = " ".join(fields)
    match = _LABELED_LINE.match(joined)
    if match:
        return match["label"], _clean_title(match["title"])
    return None, _clean_title(joined)


def _period_run(title: str) -> list[str]:
    """Split an unlabeled run of period-delimited sibling titles, or keep it whole."""
    parts = [_clean_title(part) for part in re.split(r"\.\s+", title)]
    parts = [part for part in parts if part]
    return parts if len(parts) >= MIN_TOC_ENTRIES else [title]


def parse_yes24_contents(contents: str) -> list[dict[str, Any]]:
    """Parse YES24 TOC text into ordered {level, label, title} items without inventing depth.

    Numbered entries take their depth from the dotted label. An unlabeled line belongs
    under the most recent numbered entry, or at the top level before any numbered entry.
    "Part" headings are top-level and push the chapters that follow one level down.
    """
    items: list[dict[str, Any]] = []
    in_part = False
    last_labeled_level: int | None = None
    for line in _text_lines(contents):
        label, title = _split_line(line)
        if not title:
            continue
        if label is None and _PART_LINE.match(title):
            items.append({"level": 1, "label": None, "title": title})
            in_part = True
            last_labeled_level = None
            continue
        offset = 1 if in_part else 0
        if label is not None:
            level = label.count(".") + 1 + offset
            items.append({"level": level, "label": label, "title": title})
            last_labeled_level = level
            continue
        level = last_labeled_level + 1 if last_labeled_level is not None else 1 + offset
        items.extend({"level": level, "label": None, "title": part} for part in _period_run(title))
    return items


def _toc_entries(items: list[dict[str, Any]], book_id: str, source_id: str) -> list[TocEntry]:
    """Build parent links and per-parent integer ordering, clamping skipped depths."""
    latest_by_level: dict[int, str] = {}
    sibling_counts: dict[str | None, int] = {}
    entries: list[TocEntry] = []
    previous_level = 0
    for index, item in enumerate(items):
        level = min(int(item["level"]), previous_level + 1)
        parent_id = latest_by_level.get(level - 1) if level > 1 else None
        entry_id = stable_id(
            "toc", book_id, source_id, str(index), item["label"] or "", item["title"]
        )
        entries.append(
            TocEntry(
                toc_entry_id=entry_id,
                book_id=book_id,
                parent_entry_id=parent_id,
                level=level,
                order_index=sibling_counts.get(parent_id, 0),
                label=item["label"],
                title=item["title"],
                source_id=source_id,
            )
        )
        sibling_counts[parent_id] = sibling_counts.get(parent_id, 0) + 1
        latest_by_level = {key: value for key, value in latest_by_level.items() if key < level}
        latest_by_level[level] = entry_id
        previous_level = level
    return entries


def _exact_isbn_evidence(
    book: Book, *, source_title: str | None, source_isbns: list[str], discovery_method: str
) -> EvidenceProvenance:
    return EvidenceProvenance(
        evidence_type="toc",
        tier="exact_edition_toc",
        target_isbn=book.isbn_13,
        target_title=book.title,
        target_authors=book.authors,
        source_edition_id=book.isbn_13,
        source_isbns=source_isbns,
        source_title=source_title,
        same_edition=True,
        source_document_type="toc_api_record",
        discovery_method=discovery_method,
        match_basis=["isbn_13"],
        validation_status="strong",
    )


def normalize_yes24_toc_response(
    response: dict[str, Any], *, book: Book, retrieved_at: datetime
) -> CanonicalDataset | None:
    """Convert one YES24 content lookup; None when YES24 has no usable TOC for the ISBN."""
    if response.get("success") is False:
        if response.get("errorCode") in YES24_NO_TOC_ERRORS:
            return None
        raise InvalidProviderResponse(
            f"yes24 lookup failed: {response.get('errorCode')} {response.get('message')}"
        )
    data = response.get("data")
    record = data.get("data") if isinstance(data, dict) else None
    if not isinstance(record, dict):
        raise InvalidProviderResponse("yes24 response is missing data.data")
    item_id = record.get("itemId")
    if isinstance(item_id, bool) or not isinstance(item_id, int):
        raise InvalidProviderResponse("yes24 response is missing an integer itemId")
    contents = record.get("contents")
    if not isinstance(contents, str) or not contents.strip():
        return None
    items = parse_yes24_contents(contents)
    if len(items) < MIN_TOC_ENTRIES:
        return None

    source_id = stable_id("source", "yes24", str(item_id), book.book_id, retrieved_at.isoformat())
    source = Source(
        source_id=source_id,
        book_id=book.book_id,
        provider="yes24",
        source_type="metadata_api",
        url=YES24_PRODUCT_URL.format(item_id=item_id),
        external_id=str(item_id),
        retrieved_at=retrieved_at,
        license=None,
        rights_note=YES24_RIGHTS_NOTE,
        content_hash=sha256_text(contents),
        evidence=_exact_isbn_evidence(
            book,
            source_title=None,
            source_isbns=[book.isbn_13] if book.isbn_13 else [],
            discovery_method="yes24_isbn13_lookup",
        ),
    )
    return CanonicalDataset(
        books=[], documents=[], toc=_toc_entries(items, book.book_id, source_id), sources=[source]
    )


def _digits(isbn: Any) -> str | None:
    return re.sub(r"[^0-9X]", "", isbn.upper()) if isinstance(isbn, str) else None


def normalize_springer_metadata_response(
    payload: dict[str, Any], *, book: Book, retrieved_at: datetime
) -> CanonicalDataset | None:
    """Convert paged chapter records for one ISBN into a flat, DOI-ordered chapter list.

    Springer's metadata lists chapters as separate records with no hierarchy, so every
    chapter is level 1; the chapter number comes from the chapter DOI suffix.
    """
    pages = payload.get("pages")
    if not isinstance(pages, list):
        raise InvalidProviderResponse("springer-metadata payload is missing pages")
    target = book.isbn_13
    chapters: dict[int, dict[str, Any]] = {}
    for page in pages:
        records = page.get("response", {}).get("records") if isinstance(page, dict) else None
        if not isinstance(records, list):
            raise InvalidProviderResponse("springer-metadata page is missing records")
        for record in records:
            if not isinstance(record, dict) or record.get("contentType") != "Chapter":
                continue
            if target not in {
                _digits(record.get("printIsbn")),
                _digits(record.get("electronicIsbn")),
            }:
                continue
            match = _SPRINGER_CHAPTER_DOI.match(str(record.get("doi") or ""))
            title = _clean_title(str(record.get("title") or ""))
            if match and title:
                chapters.setdefault(int(match["number"]), record)
    if len(chapters) < MIN_TOC_ENTRIES:
        return None

    first = chapters[min(chapters)]
    electronic_isbn = str(first.get("electronicIsbn") or "")
    book_doi = f"10.1007/{electronic_isbn}" if electronic_isbn else None
    source_isbns = sorted(
        {
            digits
            for digits in (_digits(first.get("printIsbn")), _digits(first.get("electronicIsbn")))
            if digits
        }
    )
    ordered = [chapters[number] for number in sorted(chapters)]
    external_id = book_doi or f"isbn:{target}"
    source_id = stable_id(
        "source", "springer_metadata", external_id, book.book_id, retrieved_at.isoformat()
    )
    copyright_note = f" Copyright: {first['copyright']}." if first.get("copyright") else ""
    source = Source(
        source_id=source_id,
        book_id=book.book_id,
        provider="springer_nature",
        source_type="metadata_api",
        url=f"https://link.springer.com/book/{book_doi}"
        if book_doi
        else "https://link.springer.com",
        external_id=external_id,
        retrieved_at=retrieved_at,
        license=None,
        rights_note=(
            "Chapter titles from the Springer Nature Metadata API; chapter abstracts are kept "
            f"only in the raw response.{copyright_note} No license inferred."
        ),
        content_hash=sha256_json(
            [{"doi": record.get("doi"), "title": record.get("title")} for record in ordered]
        ),
        evidence=_exact_isbn_evidence(
            book,
            source_title=str(first.get("publicationName") or "") or None,
            source_isbns=source_isbns,
            discovery_method="springer_metadata_isbn_lookup",
        ),
    )
    items = [
        {"level": 1, "label": str(number), "title": _clean_title(str(chapters[number]["title"]))}
        for number in sorted(chapters)
    ]
    return CanonicalDataset(
        books=[], documents=[], toc=_toc_entries(items, book.book_id, source_id), sources=[source]
    )
