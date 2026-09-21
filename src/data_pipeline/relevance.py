"""Transparent, metadata-only relevance decisions for opt-in scale experiments."""

from dataclasses import dataclass
from typing import Any

from data_pipeline.topics import topic_conflicting_subjects_pattern, topic_relevance_pattern


@dataclass(frozen=True)
class RelevanceDecision:
    accepted: bool
    reason: str
    evidence: list[dict[str, str]]


def open_library_relevance(
    topic: str,
    record: dict[str, Any],
    edition_details: dict[str, dict[str, Any]],
    work_details: dict[str, dict[str, Any]],
    *,
    selected_title: str | None = None,
) -> RelevanceDecision:
    """Prefer source-attributed subjects, then the exact normalized edition title."""
    subject_evidence: list[dict[str, str]] = []
    english_title = ""
    edition_key = ""
    work_key = record.get("key")
    work = work_details.get(work_key) if isinstance(work_key, str) else None
    if isinstance(work, dict) and isinstance(work.get("subjects"), list):
        subject_evidence.extend(
            {"origin": "work_detail", "external_id": work_key, "value": item}
            for item in work["subjects"]
            if isinstance(item, str)
        )
    editions = record.get("editions", {})
    if isinstance(editions, dict) and isinstance(editions.get("docs"), list):
        for edition in editions["docs"]:
            if not isinstance(edition, dict) or not isinstance(edition.get("language"), list):
                continue
            if "eng" not in edition["language"]:
                continue
            english_title = edition.get("title") if isinstance(edition.get("title"), str) else ""
            selected_key = edition.get("key")
            edition_key = selected_key if isinstance(selected_key, str) else ""
            detail = edition_details.get(edition_key)
            if isinstance(detail, dict) and isinstance(detail.get("subjects"), list):
                subject_evidence.extend(
                    {"origin": "edition_detail", "external_id": edition_key, "value": item}
                    for item in detail["subjects"]
                    if isinstance(item, str)
                )
            break
    title = selected_title or english_title or record.get("title", "")
    title = title if isinstance(title, str) else ""
    subjects = " | ".join(item["value"] for item in subject_evidence)
    if subjects:
        conflict = topic_conflicting_subjects_pattern(topic)
        if conflict is not None and conflict.search(subjects):
            return RelevanceDecision(False, "conflicting_subject", subject_evidence)
        if topic_relevance_pattern(topic).search(subjects):
            return RelevanceDecision(True, "matching_subject", subject_evidence)
    title_evidence = [
        {
            "origin": "search_edition_title" if english_title else "search_work_title",
            "external_id": edition_key
            if english_title
            else work_key
            if isinstance(work_key, str)
            else "",
            "value": title,
        }
    ]
    if topic_relevance_pattern(topic).search(title):
        return RelevanceDecision(
            True, "title_only_unverified", [*subject_evidence, *title_evidence]
        )
    return RelevanceDecision(False, "no_topic_evidence", [*subject_evidence, *title_evidence])
