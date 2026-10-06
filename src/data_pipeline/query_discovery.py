"""Literal query plus observed YES24 category. Book discovery, not semantic approval."""

import hashlib
import re
import unicodedata
from collections import Counter
from datetime import datetime

from data_pipeline.normalizers import _yes24_records, normalize_yes24_response
from data_pipeline.topics import TopicSpec


def discovery_policy(query: str, category: str) -> TopicSpec:
    query = unicodedata.normalize("NFKC", query).strip()
    if not 2 <= len(query) <= 120 or not any(c.isalnum() for c in query):
        raise ValueError("invalid query")
    parts = category.split("-")
    if len(parts) < 2 or parts[0] != "국내도서" or not parts[1].strip() or len(category) > 240:
        raise ValueError("unsupported provider category")
    identity = re.sub(r"\s+", "", query).lower() + "\0" + category
    slug = "search-" + hashlib.sha256(identity.encode()).hexdigest()[:20]
    words = re.split(r"\s+", query)
    literal = r"\s*".join(re.escape(word) for word in words)
    if query.isascii():
        literal = r"(?i)(?<![a-z0-9])" + literal + r"(?![a-z0-9])"
    domain = "provider-" + hashlib.sha256(parts[1].encode()).hexdigest()[:16]
    return TopicSpec(
        slug=slug,
        domain=domain,
        title=query,
        open_library_title=query,
        google_books_subject=query,
        relevance_term_pattern=literal,
        korean_query=query,
        korean_relevance_term_pattern=literal,
        korean_allowed_category_pattern="^" + re.escape(category) + "$",
    )


def discover_categories(response: dict, query: str, retrieved_at: datetime) -> list[dict]:
    """Count eligible unique editions in the bounded response, not the whole bookstore."""
    categories = Counter(
        row.get("goodsSortNm")
        for row in _yes24_records(response)
        if isinstance(row, dict) and isinstance(row.get("goodsSortNm"), str)
    )
    groups = []
    for category in categories:
        try:
            policy = discovery_policy(query, category)
        except ValueError:
            continue
        dataset = normalize_yes24_response(
            response,
            topic=policy.slug,
            limit=100,
            retrieved_at=retrieved_at,
            discovery_spec=policy,
        )
        if dataset.books:
            groups.append(
                {
                    "category": category,
                    "bookCount": len(dataset.books),
                    "samples": [
                        {"title": b.title, "authors": b.authors} for b in dataset.books[:4]
                    ],
                }
            )
    return sorted(groups, key=lambda g: (-g["bookCount"], g["category"]))
