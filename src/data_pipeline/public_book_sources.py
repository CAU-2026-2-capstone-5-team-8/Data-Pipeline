"""Reviewed public book pages that provide exact-edition evidence."""

from dataclasses import dataclass


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
    expected_toc_count: int
    expected_root_titles: tuple[str, ...]


PUBLIC_BOOK_SOURCES = {
    "ecampus-stallings-os4": PublicBookSourceSpec(
        slug="ecampus-stallings-os4",
        provider="ecampus",
        topic="operating-systems",
        book_id="isbn13:9780130319999",
        isbn_13="9780130319999",
        title="Operating Systems: Internals and Design Principles",
        edition=4,
        url=(
            "https://cincinnatistate.ecampus.com/"
            "operating-systems-internals-design/bk/9780130319999"
        ),
        expected_toc_count=201,
        expected_root_titles=(
            "Web Site for Operating Systems: Internals and Design Principles",
            "Preface",
            "PART ONE BACKGROUND",
            "PART TWO PROCESSES",
            "PART THREE MEMORY",
            "PART FOUR SCHEDULING",
            "PART FIVE INPUT/OUTPUT AND FILES",
            "PART SIX DISTRIBUTED SYSTEMS",
            "PART SEVEN SECURITY",
            "APPENDICES",
            "Glossary",
            "References",
            "Index",
        ),
    ),
}


def public_book_source(source_slug: str) -> PublicBookSourceSpec:
    """Return one reviewed source or reject arbitrary public pages."""
    try:
        return PUBLIC_BOOK_SOURCES[source_slug]
    except KeyError as exc:
        choices = ", ".join(sorted(PUBLIC_BOOK_SOURCES))
        raise ValueError(f"public book source must be one of: {choices}") from exc
