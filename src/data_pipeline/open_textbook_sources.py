"""Reviewed open textbooks whose public evidence can be collected reproducibly.

Entries live in configs/sources/open-textbook/<slug>.json (one file per book), loaded
at import time. Adding a source is a config file addition, not a code change.
"""

from dataclasses import dataclass

from data_pipeline.source_registry import config_path, load_registry_dir

CONFIG_DIR = config_path("sources", "open-textbook")


@dataclass(frozen=True)
class OpenTextbookDocumentSpec:
    """One reviewed public document belonging to an open textbook."""

    document_type: str
    external_id: str
    url: str
    expected_text_markers: tuple[str, ...]
    media_type: str = "application/pdf"
    identity_text_markers: tuple[str, ...] = ()
    preface_text_markers: tuple[str, ...] = ()
    sample_text_markers: tuple[str, ...] = ()
    license: str | None = None
    allowed_redirect_hosts: tuple[str, ...] = ()


@dataclass(frozen=True)
class OpenTextbookSourceSpec:
    """Identity, replacement, and public-document rules for one open textbook."""

    slug: str
    provider: str
    topic: str
    replaces_book_id: str
    book_id: str
    isbn_10: str | None
    isbn_13: str | None
    title: str
    authors: tuple[str, ...]
    publisher: str | None
    published_year: int
    version: str | None
    home_url: str
    documents: tuple[OpenTextbookDocumentSpec, ...]
    source_format: str = "ostep_chapter_pdfs"
    license_url: str | None = None
    license_media_type: str = "text/html"
    license_reference_url: str | None = None
    license: str | None = None
    max_resource_bytes: int = 5 * 1024 * 1024
    expected_page_count: int | None = None
    preface_page_range: tuple[int, int] | None = None
    home_license_reference_url: str | None = None
    home_license: str | None = None
    document_reference_url: str | None = None
    sample_page_range: tuple[int, int] | None = None


OPEN_TEXTBOOK_SOURCES: dict[str, OpenTextbookSourceSpec] = load_registry_dir(
    OpenTextbookSourceSpec, CONFIG_DIR
)


def open_textbook_source(source_slug: str) -> OpenTextbookSourceSpec:
    """Return one reviewed open textbook or reject arbitrary URLs."""
    try:
        return OPEN_TEXTBOOK_SOURCES[source_slug]
    except KeyError as exc:
        choices = ", ".join(sorted(OPEN_TEXTBOOK_SOURCES))
        raise ValueError(f"open textbook source must be one of: {choices}") from exc
