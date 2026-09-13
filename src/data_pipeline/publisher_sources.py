"""Small allowlist of exact-edition public publisher evidence sources."""

from dataclasses import dataclass


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


PUBLISHER_SOURCES = {
    "wiley-osc7": PublisherSourceSpec(
        slug="wiley-osc7",
        provider="wiley",
        topic="operating-systems",
        book_id="isbn13:9780471694663",
        isbn_10="0471694665",
        title="Operating System Concepts",
        edition=7,
        home_url=(
            "https://bcs.wiley.com/he-bcs/Books?"
            "action=index&bcsId=2217&itemId=0471694665&itemTypeId=BKS"
        ),
        toc_url=("https://bcs.wiley.com/he-bcs/Books?action=contents&itemId=0471694665&bcsId=2217"),
    )
}


def publisher_source(source_slug: str) -> PublisherSourceSpec:
    """Return one explicitly reviewed source or reject unknown pages."""
    try:
        return PUBLISHER_SOURCES[source_slug]
    except KeyError as exc:
        choices = ", ".join(sorted(PUBLISHER_SOURCES))
        raise ValueError(f"publisher source must be one of: {choices}") from exc
