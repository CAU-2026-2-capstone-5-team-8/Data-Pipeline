"""Transparent, metadata-only relevance decisions for opt-in scale experiments."""

import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RelevanceDecision:
    accepted: bool
    reason: str
    evidence: str


TOPIC_TERMS = {
    "operating-systems": re.compile(r"\boperating\s+systems?\b", re.IGNORECASE),
    "linear-algebra": re.compile(r"\blinear\s+algebra\b", re.IGNORECASE),
}

# Broad competing disciplines, not specific titles, identifiers, or providers.
CONFLICTING_SUBJECTS = {
    "operating-systems": re.compile(
        r"\b(?:robotics?|electric\s+power|political\s+science|anarchism)\b",
        re.IGNORECASE,
    ),
}


def open_library_relevance(
    topic: str,
    record: dict[str, Any],
    edition_details: dict[str, dict[str, Any]],
    work_details: dict[str, dict[str, Any]],
) -> RelevanceDecision:
    """Prefer preserved subject evidence, falling back to an explicit weak title signal."""
    subject_values: list[str] = []
    english_title = ""
    work_key = record.get("key")
    work = work_details.get(work_key) if isinstance(work_key, str) else None
    if isinstance(work, dict) and isinstance(work.get("subjects"), list):
        subject_values.extend(item for item in work["subjects"] if isinstance(item, str))
    editions = record.get("editions", {})
    if isinstance(editions, dict) and isinstance(editions.get("docs"), list):
        for edition in editions["docs"]:
            if not isinstance(edition, dict) or not isinstance(edition.get("language"), list):
                continue
            if "eng" not in edition["language"]:
                continue
            english_title = edition.get("title") if isinstance(edition.get("title"), str) else ""
            edition_key = edition.get("key")
            detail = edition_details.get(edition_key) if isinstance(edition_key, str) else None
            if isinstance(detail, dict) and isinstance(detail.get("subjects"), list):
                subject_values.extend(item for item in detail["subjects"] if isinstance(item, str))
            break
    subjects = " | ".join(subject_values)
    if subjects:
        conflict = CONFLICTING_SUBJECTS.get(topic)
        if conflict is not None and conflict.search(subjects):
            return RelevanceDecision(False, "conflicting_subject", subjects)
        if TOPIC_TERMS[topic].search(subjects):
            return RelevanceDecision(True, "matching_subject", subjects)
    title = english_title or record.get("title", "")
    title = title if isinstance(title, str) else ""
    if TOPIC_TERMS[topic].search(title):
        return RelevanceDecision(True, "title_only_unverified", title)
    return RelevanceDecision(False, "no_topic_evidence", title)
