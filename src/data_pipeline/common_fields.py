"""Reviewed multilingual field identities, independent of any provider taxonomy.

Only aliases in this small registry get a common identity. Unknown text still needs
source discovery; it never silently becomes an approved field or diagnosis.
"""

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass

from data_pipeline.source_registry import config_path
from data_pipeline.topics import TopicSpec


def _name(value: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", value)).casefold()


@dataclass(frozen=True)
class CommonField:
    id: str
    name: str
    english_name: str
    domain: str
    domain_name: str
    domain_english_name: str
    aliases: tuple[str, ...]
    korean_query: str
    english_query: str
    evidence_pattern: str
    korean_evidence_pattern: str
    korean_category_pattern: str
    registry_hash: str

    @property
    def slug(self) -> str:
        # Namespace protects curated assessment IDs and existing legacy snapshots.
        return "field-" + self.id

    @property
    def parent_code(self) -> str:
        return "SRC-" + hashlib.sha256(self.domain.encode()).hexdigest()[:16]

    def spec(self) -> TopicSpec:
        return TopicSpec(
            slug=self.slug,
            domain=self.domain,
            title=self.english_name,
            open_library_title=self.english_query,
            google_books_subject=self.english_query,
            relevance_term_pattern=self.evidence_pattern,
            korean_query=self.korean_query,
            korean_relevance_term_pattern=self.korean_evidence_pattern,
            korean_allowed_category_pattern=self.korean_category_pattern,
        )


def common_field(identifier: str) -> CommonField:
    entries = json.loads(config_path("discovery-subjects.json").read_text())
    entry = entries[identifier]
    if not re.fullmatch(r"[a-z][a-z0-9-]{1,80}", identifier):
        raise ValueError("invalid common field identifier")
    # Hash the selected definition, not unrelated fields. Freeze it in each selection.
    encoded = json.dumps(entry, ensure_ascii=False, sort_keys=True).encode()
    return CommonField(
        id=identifier,
        name=entry["name"],
        english_name=entry["english_name"],
        domain=entry["domain"],
        domain_name=entry["domain_name"],
        domain_english_name=entry["domain_english_name"],
        aliases=tuple(entry["aliases"]),
        korean_query=entry["korean_query"],
        english_query=entry["english_query"],
        evidence_pattern=entry["evidence_pattern"],
        korean_evidence_pattern=entry["korean_evidence_pattern"],
        korean_category_pattern=entry["korean_category_pattern"],
        registry_hash="sha256:" + hashlib.sha256(encoded).hexdigest(),
    )


def resolve_common_field(query: str) -> CommonField | None:
    entries = json.loads(config_path("discovery-subjects.json").read_text())
    matches = [
        key
        for key, entry in entries.items()
        if _name(query) in {_name(key), *(_name(a) for a in entry["aliases"])}
    ]
    if len(matches) > 1:
        raise ValueError("ambiguous common field alias")
    return common_field(matches[0]) if matches else None


def is_browsing_spec(spec: TopicSpec) -> bool:
    if spec.slug.startswith("search-"):
        return True
    if spec.slug.startswith("field-"):
        try:
            return common_field(spec.slug[6:]).spec() == spec
        except (KeyError, ValueError):
            return False
    return False
