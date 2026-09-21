"""Data-driven topic taxonomy loaded from configs/topics.json.

Adding a new topic is a config change here, not a code change scattered across
normalizers.py, relevance.py, collectors/open_library.py, collectors/google_books.py,
and manifest.py.
"""

import json
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from data_pipeline.source_registry import config_path

CONFIG_PATH = config_path("topics.json")


class TopicSpec(BaseModel):
    """One leaf topic's identity and per-provider search parameters."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    slug: str
    domain: str
    title: str
    open_library_title: str
    google_books_subject: str
    relevance_term_pattern: str
    conflicting_subjects_pattern: str | None = None


def _load_registry(path: Path) -> dict[str, TopicSpec]:
    """Load unique topic slugs from one JSON registry."""

    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        """Reject duplicate keys before JSON decoding can overwrite them."""
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key in topic registry: {key}")
            result[key] = value
        return result

    raw = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_object)
    if not isinstance(raw, dict):
        raise ValueError("topic registry must be a JSON object")
    return {slug: TopicSpec(slug=slug, **fields) for slug, fields in raw.items()}


TOPIC_REGISTRY: dict[str, TopicSpec] = _load_registry(CONFIG_PATH)

# Backward-compatible shape previously hardcoded in normalizers.py, consumed by
# normalizers.py, cli.py, and Book.topics values: {"slug": ["domain", "slug"]}.
TOPICS: dict[str, list[str]] = {slug: [spec.domain, slug] for slug, spec in TOPIC_REGISTRY.items()}


def topic_choices() -> list[str]:
    """Return every configured topic slug, sorted for stable CLI/error output."""
    return sorted(TOPIC_REGISTRY)


def _spec(topic: str) -> TopicSpec:
    """Return one configured topic or reject unsupported values."""
    try:
        return TOPIC_REGISTRY[topic]
    except KeyError as exc:
        raise ValueError(f"unsupported topic: {topic}") from exc


def topic_open_library_title(topic: str) -> str:
    """Return the Open Library search title for a topic."""
    return _spec(topic).open_library_title


def topic_title_phrase(topic: str) -> str:
    """Return the natural-language topic title phrase shared by title-search providers.

    Currently the same value as topic_open_library_title(); a separate accessor keeps
    non-Open-Library callers (e.g. Internet Archive) from importing an OL-named function.
    """
    return topic_open_library_title(topic)


def topic_google_books_query(topic: str) -> str:
    """Return the Google Books `subject:"..."` query for a topic."""
    return f'subject:"{_spec(topic).google_books_subject}"'


def topic_relevance_pattern(topic: str) -> re.Pattern[str]:
    """Return the compiled topic-evidence-v1 matching term pattern for a topic."""
    return re.compile(_spec(topic).relevance_term_pattern, re.IGNORECASE)


def topic_conflicting_subjects_pattern(topic: str) -> re.Pattern[str] | None:
    """Return the compiled competing-subject rejection pattern for a topic, if any."""
    pattern = _spec(topic).conflicting_subjects_pattern
    return re.compile(pattern, re.IGNORECASE) if pattern else None
