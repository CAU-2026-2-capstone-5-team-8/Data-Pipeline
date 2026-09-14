"""Reviewed public book pages that provide exact-edition evidence."""

from dataclasses import dataclass
from typing import Literal


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
    toc_format: Literal["indented_table", "heading_sequence"]
    expected_toc_count: int
    expected_root_titles: tuple[str, ...]
    expected_chapter_labels: tuple[str, ...]


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
        toc_format="indented_table",
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
        expected_chapter_labels=(),
    ),
    "ecampus-singhal-os1": PublicBookSourceSpec(
        slug="ecampus-singhal-os1",
        provider="ecampus",
        topic="operating-systems",
        book_id="isbn13:9780070575721",
        isbn_13="9780070575721",
        title="Advanced Concepts In Operating Systems",
        edition=1,
        url=(
            "https://cincinnatistate.ecampus.com/"
            "advanced-concepts-operating-systems-1st/bk/9780070575721"
        ),
        toc_format="heading_sequence",
        expected_toc_count=27,
        expected_root_titles=(
            "Process Synchronization",
            "Distributed Operating Systems",
            "Distributed Resource Management",
            "Failure Recovery and Fault Tolerance",
            "Protection and Security",
            "Multiprocessor Operating Systems",
            "Database Operating Systems",
        ),
        expected_chapter_labels=tuple(str(number) for number in range(1, 21)),
    ),
}


def public_book_source(source_slug: str) -> PublicBookSourceSpec:
    """Return one reviewed source or reject arbitrary public pages."""
    try:
        return PUBLIC_BOOK_SOURCES[source_slug]
    except KeyError as exc:
        choices = ", ".join(sorted(PUBLIC_BOOK_SOURCES))
        raise ValueError(f"public book source must be one of: {choices}") from exc
