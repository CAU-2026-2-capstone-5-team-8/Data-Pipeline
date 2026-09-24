"""Reviewed Springer book landing pages that publish a chapter-level TOC.

Entries live in configs/sources/springer-book/<slug>.json (one file per book),
loaded at import time. Adding a source is a config file addition, not a code change.

Springer exposes the eBook ISBN on a book landing page, not the print ISBN a canonical
record usually carries, and it keeps one landing page per edition. A spec therefore
states both identifiers and whether the Springer edition is the canonical book's own
edition, so an alternate edition is never recorded as exact-edition evidence.
"""

from dataclasses import dataclass
from typing import Literal

from data_pipeline.identifiers import stable_id
from data_pipeline.source_registry import config_path, load_registry_dir

CONFIG_DIR = config_path("sources", "springer-book")


@dataclass(frozen=True)
class SpringerBookSourceSpec:
    """Identity and completeness checks for one Springer book landing page."""

    slug: str
    topic: str
    book_id: str
    url: str
    doi: str
    ebook_isbn: str
    title: str
    authors: tuple[str, ...]
    edition_relation: Literal["exact", "same_work"]
    expected_entry_titles: tuple[str, ...]
    provider: str = "springer"
    isbn_13: str | None = None
    edition: int | None = None
    springer_edition_label: str | None = None


SPRINGER_BOOK_SOURCES: dict[str, SpringerBookSourceSpec] = load_registry_dir(
    SpringerBookSourceSpec, CONFIG_DIR
)


def springer_book_source(source_slug: str) -> SpringerBookSourceSpec:
    """Return one reviewed source or reject arbitrary Springer pages."""
    try:
        return SPRINGER_BOOK_SOURCES[source_slug]
    except KeyError as exc:
        choices = ", ".join(sorted(SPRINGER_BOOK_SOURCES))
        raise ValueError(f"springer book source must be one of: {choices}") from exc


def springer_book_source_id(source_spec: SpringerBookSourceSpec) -> str:
    """Return the deterministic canonical source ID for a reviewed Springer page."""
    return stable_id("source", source_spec.provider, source_spec.url, source_spec.book_id)
