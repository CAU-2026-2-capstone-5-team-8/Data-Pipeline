"""Reviewed public book pages that provide exact-edition evidence.

Entries live in configs/sources/public-book-page/<slug>.json (one file per book),
loaded at import time. Adding a source is a config file addition, not a code change.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from data_pipeline.identifiers import stable_id
from data_pipeline.source_registry import load_registry_dir

CONFIG_DIR = Path(__file__).resolve().parents[2] / "configs" / "sources" / "public-book-page"


@dataclass(frozen=True)
class PublicBookSourceSpec:
    """Identity and completeness checks for one public catalog page."""

    slug: str
    provider: str
    topic: str
    book_id: str
    isbn_13: str
    title: str
    edition: int
    url: str
    toc_format: Literal[
        "indented_table",
        "indented_table_chapter_roots",
        "heading_sequence",
        "flat_bold",
        "flat_table",
        "paragraph_sequence",
        "bold_chapter_paragraphs",
    ]
    expected_toc_count: int
    expected_root_titles: tuple[str, ...]
    expected_chapter_labels: tuple[str, ...]
    expected_child_label_groups: tuple[tuple[str, ...], ...] = ()
    expected_child_counts: tuple[int, ...] = ()
    expected_descendant_counts: tuple[int, ...] = ()
    preferred_toc: bool = False


PUBLIC_BOOK_SOURCES: dict[str, PublicBookSourceSpec] = load_registry_dir(
    PublicBookSourceSpec, CONFIG_DIR
)


def public_book_source(source_slug: str) -> PublicBookSourceSpec:
    """Return one reviewed source or reject arbitrary public pages."""
    try:
        return PUBLIC_BOOK_SOURCES[source_slug]
    except KeyError as exc:
        choices = ", ".join(sorted(PUBLIC_BOOK_SOURCES))
        raise ValueError(f"public book source must be one of: {choices}") from exc


def public_book_source_id(source_spec: PublicBookSourceSpec) -> str:
    """Return the deterministic canonical source ID for a reviewed catalog page."""
    return stable_id("source", source_spec.provider, source_spec.url, source_spec.book_id)


def preferred_public_toc_source_ids() -> dict[str, str]:
    """Map each explicitly reviewed replacement book to its preferred TOC source."""
    preferred: dict[str, str] = {}
    for source_spec in PUBLIC_BOOK_SOURCES.values():
        if not source_spec.preferred_toc:
            continue
        if source_spec.book_id in preferred:
            raise ValueError(f"multiple preferred TOC sources configured for {source_spec.book_id}")
        preferred[source_spec.book_id] = public_book_source_id(source_spec)
    return preferred
