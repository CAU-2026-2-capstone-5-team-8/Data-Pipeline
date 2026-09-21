"""Small allowlist of exact-edition public publisher evidence sources.

Entries live in configs/sources/publisher/<slug>.json (one file per book), loaded at
import time. Adding a source is a config file addition, not a code change.
"""

from dataclasses import dataclass

from data_pipeline.source_registry import config_path, load_registry_dir

CONFIG_DIR = config_path("sources", "publisher")


@dataclass(frozen=True)
class PublisherSourceSpec:
    """Identity and URLs required to bind one publisher page to one exact book."""

    slug: str
    provider: str
    topic: str
    book_id: str
    isbn_10: str
    title: str
    edition: int
    home_url: str
    toc_url: str
    expected_toc_labels: tuple[str, ...]


PUBLISHER_SOURCES: dict[str, PublisherSourceSpec] = load_registry_dir(
    PublisherSourceSpec, CONFIG_DIR
)


def publisher_source(source_slug: str) -> PublisherSourceSpec:
    """Return one explicitly reviewed source or reject unknown pages."""
    try:
        return PUBLISHER_SOURCES[source_slug]
    except KeyError as exc:
        choices = ", ".join(sorted(PUBLISHER_SOURCES))
        raise ValueError(f"publisher source must be one of: {choices}") from exc
