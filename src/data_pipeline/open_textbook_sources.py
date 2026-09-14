"""Reviewed open textbooks whose public evidence can be collected reproducibly."""

from dataclasses import dataclass


@dataclass(frozen=True)
class OpenTextbookDocumentSpec:
    """One reviewed public document belonging to an open textbook."""

    document_type: str
    external_id: str
    url: str
    expected_text_markers: tuple[str, ...]


@dataclass(frozen=True)
class OpenTextbookSourceSpec:
    """Identity, replacement, and public-document rules for one open textbook."""

    slug: str
    provider: str
    topic: str
    replaces_book_id: str
    book_id: str
    isbn_10: str
    isbn_13: str
    title: str
    authors: tuple[str, ...]
    publisher: str
    published_year: int
    version: str
    home_url: str
    documents: tuple[OpenTextbookDocumentSpec, ...]


OPEN_TEXTBOOK_SOURCES = {
    "ostep-1.10": OpenTextbookSourceSpec(
        slug="ostep-1.10",
        provider="ostep",
        topic="operating-systems",
        replaces_book_id="isbn13:9780070394551",
        book_id="isbn13:9781985086593",
        isbn_10="198508659X",
        isbn_13="9781985086593",
        title="Operating Systems: Three Easy Pieces",
        authors=("Remzi H. Arpaci-Dusseau", "Andrea C. Arpaci-Dusseau"),
        publisher="Arpaci-Dusseau Books",
        published_year=2023,
        version="1.10",
        home_url="https://pages.cs.wisc.edu/~remzi/OSTEP/",
        documents=(
            OpenTextbookDocumentSpec(
                document_type="preface",
                external_id="ostep-1.10:preface",
                url="https://pages.cs.wisc.edu/~remzi/OSTEP/preface.pdf",
                expected_text_markers=("Preface", "Welcome to this book", "three easy pieces"),
            ),
            OpenTextbookDocumentSpec(
                document_type="introduction",
                external_id="ostep-1.10:introduction",
                url="https://pages.cs.wisc.edu/~remzi/OSTEP/intro.pdf",
                expected_text_markers=(
                    "Introduction to Operating Systems",
                    "virtualization",
                    "resource manager",
                ),
            ),
            OpenTextbookDocumentSpec(
                document_type="sample_chapter",
                external_id="ostep-1.10:chapter-4",
                url="https://pages.cs.wisc.edu/~remzi/OSTEP/cpu-intro.pdf",
                expected_text_markers=("The Abstraction", "The Process", "virtualizing the CPU"),
            ),
        ),
    ),
}


def open_textbook_source(source_slug: str) -> OpenTextbookSourceSpec:
    """Return one reviewed open textbook or reject arbitrary URLs."""
    try:
        return OPEN_TEXTBOOK_SOURCES[source_slug]
    except KeyError as exc:
        choices = ", ".join(sorted(OPEN_TEXTBOOK_SOURCES))
        raise ValueError(f"open textbook source must be one of: {choices}") from exc
