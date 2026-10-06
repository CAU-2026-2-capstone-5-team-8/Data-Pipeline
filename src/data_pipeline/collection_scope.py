"""Small, deterministic cross-provider browsing scopes; never ML approval.

The selected source category remains evidence, not a universal taxonomy. Unsupported
category constraints or untranslated names skip foreign collection instead of widening it.
"""

import json
import re
import unicodedata
from dataclasses import asdict, dataclass
from typing import Any

from data_pipeline.collectors.base import InvalidProviderResponse
from data_pipeline.collectors.open_library import FIELDS
from data_pipeline.common_fields import CommonField, is_browsing_spec
from data_pipeline.datasets import merge_datasets, without_books
from data_pipeline.models import CanonicalDataset
from data_pipeline.normalizers import (
    _google_book_items,
    normalize_google_books_response,
    normalize_isbn,
    normalize_open_library_response,
)
from data_pipeline.source_registry import config_path
from data_pipeline.topics import TOPIC_REGISTRY, TopicSpec


def _name(value: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", value)).casefold()


@dataclass(frozen=True)
class CollectionScope:
    query: str
    source_provider: str
    source_category: str
    subject: str | None
    english_query: str | None
    evidence_pattern: str | None
    book_kind: str | None
    audience: str | None
    mapping_basis: str
    foreign_status: str
    category_subject_pattern: str | None = None
    version: str = "collection-scope-v1"

    def to_dict(self) -> dict:
        return asdict(self)


def common_field_scope(field: CommonField) -> CollectionScope:
    return CollectionScope(
        query=field.name,
        source_provider="common",
        source_category="",
        subject=field.id,
        english_query=field.english_query,
        evidence_pattern=field.evidence_pattern,
        book_kind=None,
        audience=None,
        mapping_basis="reviewed_common_field",
        foreign_status="ready",
        version="common-field-scope-v1",
    )


def collection_scope(query: str, category: str) -> CollectionScope:
    """Derive constraints only from reviewed name/category mappings."""
    subject = english = pattern = None
    basis = "unmapped"
    entries = json.loads(config_path("discovery-subjects.json").read_text())
    for key, entry in entries.items():
        if _name(query) in {_name(alias) for alias in entry["aliases"]}:
            subject, english, pattern = key, entry["english_query"], entry["evidence_pattern"]
            basis = "reviewed_alias"
            break
    if english is None:
        for key, spec in TOPIC_REGISTRY.items():
            if _name(query) in {_name(spec.korean_query or ""), _name(spec.title), _name(key)}:
                subject, english, pattern = (
                    key,
                    spec.open_library_title,
                    spec.relevance_term_pattern,
                )
                basis = "reviewed_topic"
                break
    if english is None and re.fullmatch(r"[A-Za-z][A-Za-z0-9 -]{1,119}", query.strip()):
        english = query.strip()
        pattern = r"(?<![a-z0-9])" + re.escape(english) + r"(?![a-z0-9])"
        basis = "literal_english"

    parts = category.split("-")[1:]
    root = parts[0] if parts else ""
    kind = "textbook" if root == "대학교재" else None
    audience = {"어린이": "children", "청소년": "teen"}.get(root)
    category_patterns = {
        "경제 경영": r"\beconom(?:y|ic|ics)\b|\bbusiness\b|\bfinance\b|\bmanagement\b|\bcommerce\b",
        "IT 모바일": r"\bcomput\w*|\bsoftware\b|\bprogramming\b|\binformation technology\b",
        "자연과학": r"\bscien\w*|\bmathemat\w*|\balgebra\b|\bphysics\b|\bbiology\b|\bchemistry\b",
        "인문": r"\bphilosoph\w*|\bhumanities\b|\blinguistic\w*|\blanguage\b",
        "사회 정치": r"\bsocial\b|\bpolitic\w*|\bsociolog\w*",
    }
    supported = len(parts) == 1 and root in {
        "경제 경영",
        "대학교재",
        "어린이",
        "청소년",
        "IT 모바일",
        "자연과학",
        "인문",
        "사회 정치",
    }
    # More specific provider paths require their own mapping; never discard a constraint.
    status = (
        "ready"
        if supported and english
        else ("unmapped_category" if not supported else "unmapped_language")
    )
    return CollectionScope(
        query,
        "yes24",
        category,
        subject,
        english,
        pattern,
        kind,
        audience,
        basis,
        status,
        category_patterns.get(root),
    )


def open_library_parameters(scope: CollectionScope, limit: int = 30) -> dict[str, Any]:
    if scope.foreign_status != "ready" or not scope.english_query:
        raise ValueError("scope unavailable for foreign collection")
    # English fallback is literal and mappings are server-owned, never Solr syntax from users.
    phrase = scope.english_query.replace("\\", "\\\\").replace('"', '\\"')
    query = f'(subject:"{phrase}" OR title:"{phrase}") AND language:eng'
    if scope.book_kind == "textbook":
        query += " AND subject:textbooks"
    if scope.audience == "children":
        query += " AND subject:juvenile"
    if scope.audience == "teen":
        query += ' AND subject:"young adult"'
    return {"q": query, "fields": FIELDS + ",subject", "limit": min(max(limit, 1), 30)}


def google_books_parameters(scope: CollectionScope, limit: int = 30) -> dict[str, Any]:
    if scope.foreign_status != "ready" or not scope.english_query:
        raise ValueError("scope unavailable for foreign collection")
    phrase = scope.english_query.replace("\\", "\\\\").replace('"', '\\"')
    # Google Books has its own query grammar; never forward Open Library's Solr query.
    return {
        "q": f'subject:"{phrase}"',
        "langRestrict": "en",
        "printType": "books",
        "maxResults": min(max(limit, 1), 30),
        "startIndex": 0,
        "orderBy": "relevance",
    }


def _scope_decision(
    scope: CollectionScope, title: str, subjects: list[str], english: bool, has_isbn: bool
) -> tuple[bool, str]:
    """Apply the same evidence rules to each provider's native metadata fields."""
    joined = " | ".join(subjects)
    pattern = re.compile(scope.evidence_pattern or r"(?!)", re.IGNORECASE)
    reason = (
        "matching_subject"
        if pattern.search(joined)
        else ("title_only_unverified" if pattern.search(title) else "no_subject_evidence")
    )
    include = reason in {"matching_subject", "title_only_unverified"}
    if not english:
        return False, "no_english_edition"
    if not has_isbn:
        return False, "missing_valid_isbn"
    if (
        include
        and scope.category_subject_pattern
        and not re.search(scope.category_subject_pattern, joined, re.I)
    ):
        return False, "category_subject_unconfirmed"
    if include and scope.book_kind == "textbook" and not re.search(r"textbooks?", joined, re.I):
        return False, "book_kind_unconfirmed"
    if (
        include
        and scope.audience == "children"
        and not re.search(r"juvenile|children", joined, re.I)
    ):
        return False, "audience_unconfirmed"
    if include and scope.audience == "teen" and not re.search(r"young adult", joined, re.I):
        return False, "audience_unconfirmed"
    if (
        include
        and scope.audience is None
        and re.search(r"juvenile|children|young adult", joined, re.I)
    ):
        return False, "conflicting_audience"
    if include and re.search(r"\bfiction\b|\bexaminations\b|\bstudy guides\b", joined, re.I):
        return False, "conflicting_book_kind"
    return include, reason


def normalize_scope_response(
    response: dict, scope: CollectionScope, spec: TopicSpec, retrieved_at, limit: int = 20
) -> tuple[CanonicalDataset, list[dict]]:
    """Audit every candidate before normalizing the selected ISBN-bearing English edition."""
    if scope.foreign_status != "ready" or not scope.evidence_pattern:
        raise ValueError("scope unavailable for foreign collection")
    if spec.slug in TOPIC_REGISTRY or not is_browsing_spec(spec):
        raise ValueError("discovery cannot override registered topics")
    rows = response.get("docs", [])
    if not isinstance(rows, list):
        raise InvalidProviderResponse("invalid Open Library docs")
    accepted = []
    audit = []
    for row in rows:
        if not isinstance(row, dict):
            audit.append({"included": False, "reason": "invalid_record"})
            continue
        container = row.get("editions", {})
        editions = container.get("docs", []) if isinstance(container, dict) else []
        edition = (
            next(
                (
                    e
                    for e in editions
                    if isinstance(e, dict)
                    and isinstance(e.get("language"), list)
                    and "eng" in e["language"]
                ),
                None,
            )
            if isinstance(editions, list)
            else None
        )
        subjects = row.get("subject", [])
        subjects = [s for s in subjects if isinstance(s, str)] if isinstance(subjects, list) else []
        title = str(edition.get("title", "")) if edition else ""
        has_isbn = bool(
            edition
            and isinstance(edition.get("isbn"), list)
            and any(normalize_isbn(i, 13) or normalize_isbn(i, 10) for i in edition["isbn"])
        )
        include, reason = _scope_decision(scope, title, subjects, edition is not None, has_isbn)
        audit.append(
            {
                "external_id": row.get("key"),
                "edition_id": edition.get("key") if edition else None,
                "title": title,
                "subjects": subjects,
                "included": include,
                "reason": reason,
            }
        )
        if include:
            accepted.append(row)
    dataset = normalize_open_library_response(
        {"docs": accepted},
        topic=spec.slug,
        limit=limit,
        retrieved_at=retrieved_at,
        discovery_spec=spec,
    )
    selected = {s.external_id for s in dataset.sources}
    for decision in audit:
        if decision["included"] and decision["edition_id"] not in selected:
            decision.update(included=False, reason="normalization_or_limit")
    return dataset, audit


def normalize_google_scope_response(
    response: dict, scope: CollectionScope, spec: TopicSpec, retrieved_at, limit: int = 20
) -> tuple[CanonicalDataset, list[dict]]:
    """Preserve volume identifiers/categories and distinguish unknown metadata from a match."""
    if scope.foreign_status != "ready" or not scope.evidence_pattern:
        raise ValueError("scope unavailable for foreign collection")
    if spec.slug in TOPIC_REGISTRY or not is_browsing_spec(spec):
        raise ValueError("discovery cannot override registered topics")
    accepted, audit = [], []
    for item in _google_book_items(response):
        if not isinstance(item, dict) or not isinstance(item.get("volumeInfo"), dict):
            audit.append({"included": False, "reason": "invalid_record"})
            continue
        info = item["volumeInfo"]
        subjects = info.get("categories", [])
        subjects = [s for s in subjects if isinstance(s, str)] if isinstance(subjects, list) else []
        identifiers = info.get("industryIdentifiers", [])
        identifiers = identifiers if isinstance(identifiers, list) else []
        has_isbn = any(
            isinstance(i, dict)
            and (
                i.get("type") == "ISBN_13"
                and normalize_isbn(i.get("identifier"), 13)
                or i.get("type") == "ISBN_10"
                and normalize_isbn(i.get("identifier"), 10)
            )
            for i in identifiers
        )
        title = str(info.get("title", ""))
        include, reason = _scope_decision(
            scope,
            title,
            subjects,
            str(info.get("language", "")).lower() == "en",
            has_isbn,
        )
        audit.append(
            {
                "external_id": item.get("id"),
                "title": title,
                "categories": subjects,
                "included": include,
                "reason": reason,
            }
        )
        if include:
            accepted.append(item)
    dataset = normalize_google_books_response(
        {"items": accepted},
        topic=spec.slug,
        limit=limit,
        retrieved_at=retrieved_at,
        discovery_spec=spec,
    )
    selected = {s.external_id for s in dataset.sources}
    for decision in audit:
        if decision["included"] and decision["external_id"] not in selected:
            decision.update(included=False, reason="normalization_or_limit")
    return dataset, audit


def merge_scope_catalogs(
    primary: CanonicalDataset, foreign: CanonicalDataset
) -> tuple[CanonicalDataset, list[dict]]:
    """Keep primary bibliographic values on exact ISBN overlap; quarantine identity conflicts."""
    books = {b.book_id: b for b in primary.books}
    rejected = set()
    audit = []
    incoming = []
    for book in foreign.books:
        existing = books.get(book.book_id)
        if existing and (
            existing.language != book.language or _name(existing.title) != _name(book.title)
        ):
            rejected.add(book.book_id)
            audit.append({"book_id": book.book_id, "reason": "isbn_identity_conflict"})
            continue
        if existing:
            audit.append({"book_id": book.book_id, "reason": "exact_isbn_overlap_primary_metadata"})
        incoming.append(existing or book)
    clean = without_books(foreign, rejected).model_copy(update={"books": incoming})
    return merge_datasets([primary, clean]), audit
