"""Reviewed public documents linked from exact-edition public identity pages.

Entries live in configs/sources/publisher-document/<slug>.json (one file per book),
loaded at import time. Adding a source is a config file addition, not a code change.
"""

from dataclasses import dataclass
from typing import Literal

from data_pipeline.source_registry import config_path, load_registry_dir

CONFIG_DIR = config_path("sources", "publisher-document")


@dataclass(frozen=True)
class PublisherDocumentSourceSpec:
    """Exact-book identity and integrity checks for one reviewed public document."""

    slug: str
    provider: str
    topic: str
    book_id: str
    isbn_10: str
    title: str
    edition: int
    document_type: str
    external_id: str
    home_url: str
    referrer_url: str
    document_url: str
    referrer_heading: str
    source_type: str
    require_document_link: bool
    rights_note: str
    expected_text_markers: tuple[str, ...]
    identity_format: Literal["wiley_isbn_page", "xinu_second_edition"] = "wiley_isbn_page"
    expected_identity_markers: tuple[str, ...] = ()
    document_link_href: str | None = None
    expected_page_count: int | None = None


PUBLISHER_DOCUMENT_SOURCES: dict[str, PublisherDocumentSourceSpec] = load_registry_dir(
    PublisherDocumentSourceSpec, CONFIG_DIR
)


def publisher_document_source(source_slug: str) -> PublisherDocumentSourceSpec:
    """Return one reviewed public document or reject arbitrary URLs."""
    try:
        return PUBLISHER_DOCUMENT_SOURCES[source_slug]
    except KeyError as exc:
        choices = ", ".join(sorted(PUBLISHER_DOCUMENT_SOURCES))
        raise ValueError(f"publisher document source must be one of: {choices}") from exc
