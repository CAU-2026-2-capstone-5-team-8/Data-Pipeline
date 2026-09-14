"""Reviewed open textbooks whose public evidence can be collected reproducibly."""

from dataclasses import dataclass


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
    license_reference_url: str | None = None
    license: str | None = None
    max_resource_bytes: int = 5 * 1024 * 1024
    expected_page_count: int | None = None
    preface_page_range: tuple[int, int] | None = None


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
    "hefferon-linear-algebra-4": OpenTextbookSourceSpec(
        slug="hefferon-linear-algebra-4",
        provider="hefferon",
        topic="linear-algebra",
        replaces_book_id="isbn13:9780126736502",
        book_id="book_b9e14d342f56d9651d61",
        isbn_10=None,
        isbn_13=None,
        title="Linear Algebra",
        authors=("Jim Hefferon",),
        publisher=None,
        published_year=2020,
        version="Fourth edition",
        home_url="https://hefferon.net/linearalgebra/",
        documents=(
            OpenTextbookDocumentSpec(
                document_type="full_text",
                external_id="hefferon-linear-algebra-fourth-edition",
                url="https://jheffero.w3.uvm.edu/linearalgebra/book.pdf",
                expected_text_markers=(),
                identity_text_markers=(
                    "Linear Algebra",
                    "Jim Hefferon",
                    "Fourth edition",
                ),
                preface_text_markers=(
                    "Preface",
                    "standard US undergraduate first course",
                    "2020-Apr-26",
                ),
                sample_text_markers=(
                    "Chapter One",
                    "Linear Systems",
                    "Gauss's Method",
                    "Analyzing Networks",
                ),
            ),
        ),
        source_format="hefferon_pdf_outline",
        license_url="https://hefferon.net/source.html",
        license=(
            "GNU Free Documentation License OR Creative Commons "
            "Attribution-ShareAlike 3.0 United States License"
        ),
        max_resource_bytes=10 * 1024 * 1024,
        expected_page_count=525,
        preface_page_range=(2, 6),
    ),
    "understanding-linear-algebra-2022": OpenTextbookSourceSpec(
        slug="understanding-linear-algebra-2022",
        provider="understanding_linear_algebra",
        topic="linear-algebra",
        replaces_book_id="isbn13:9780135370193",
        book_id="book_a1364d52179f6fca0403",
        isbn_10=None,
        isbn_13=None,
        title="Understanding Linear Algebra",
        authors=("David Austin",),
        publisher=None,
        published_year=2022,
        version=None,
        home_url="https://understandinglinearalgebra.org/home.html",
        documents=(
            OpenTextbookDocumentSpec(
                document_type="metadata",
                external_id="gvsu-open-textbooks:26",
                url="https://scholarworks.gvsu.edu/books/26/",
                media_type="text/html",
                expected_text_markers=(
                    "Understanding Linear Algebra",
                    "David Austin",
                    "2022",
                    "Creative Commons Attribution 4.0 International License",
                ),
            ),
            OpenTextbookDocumentSpec(
                document_type="toc",
                external_id="understanding-linear-algebra:toc",
                url="https://understandinglinearalgebra.org/ula.html",
                media_type="text/html",
                expected_text_markers=(
                    "Systems of equations",
                    "Singular value decompositions",
                ),
            ),
            OpenTextbookDocumentSpec(
                document_type="preface",
                external_id="understanding-linear-algebra:preface",
                url="https://understandinglinearalgebra.org/frontmatter-7.html",
                media_type="text/html",
                expected_text_markers=(
                    "This is a textbook for a first-year course in linear algebra",
                    "reason mathematically",
                ),
            ),
            OpenTextbookDocumentSpec(
                document_type="preview",
                external_id="understanding-linear-algebra:chapter-1",
                url="https://understandinglinearalgebra.org/chap1.html",
                media_type="text/html",
                expected_text_markers=(
                    "Chapter 1 Systems of equations",
                    "Pivots and their influence on solution spaces",
                ),
            ),
            OpenTextbookDocumentSpec(
                document_type="preview",
                external_id="understanding-linear-algebra:section-1.1",
                url="https://understandinglinearalgebra.org/sec-expect.html",
                media_type="text/html",
                expected_text_markers=(
                    "sets of two or more linear equations",
                    "Some simple examples",
                ),
            ),
            OpenTextbookDocumentSpec(
                document_type="preview",
                external_id="understanding-linear-algebra:section-1.2",
                url="https://understandinglinearalgebra.org/sec-finding-solutions.html",
                media_type="text/html",
                expected_text_markers=("Gaussian elimination", "reduced row echelon"),
            ),
            OpenTextbookDocumentSpec(
                document_type="preview",
                external_id="understanding-linear-algebra:section-1.3",
                url="https://understandinglinearalgebra.org/sec-sage-introduction.html",
                media_type="text/html",
                expected_text_markers=(
                    "Computation with Sage",
                    "No serious application of linear algebra",
                ),
            ),
            OpenTextbookDocumentSpec(
                document_type="preview",
                external_id="understanding-linear-algebra:section-1.4",
                url="https://understandinglinearalgebra.org/sec-pivots.html",
                media_type="text/html",
                expected_text_markers=(
                    "Pivots and their influence on solution spaces",
                    "leading entry",
                ),
            ),
        ),
        source_format="pretext_html",
        license_reference_url="https://creativecommons.org/licenses/by/4.0/",
        license="Creative Commons Attribution 4.0 International License",
        max_resource_bytes=1024 * 1024,
    ),
}


def open_textbook_source(source_slug: str) -> OpenTextbookSourceSpec:
    """Return one reviewed open textbook or reject arbitrary URLs."""
    try:
        return OPEN_TEXTBOOK_SOURCES[source_slug]
    except KeyError as exc:
        choices = ", ".join(sorted(OPEN_TEXTBOOK_SOURCES))
        raise ValueError(f"open textbook source must be one of: {choices}") from exc
