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
    "xv6-riscv-rev5": OpenTextbookSourceSpec(
        slug="xv6-riscv-rev5",
        provider="mit_pdos",
        topic="operating-systems",
        replaces_book_id="isbn13:9780070575721",
        book_id="book_21ac29d979effd89fad2",
        isbn_10=None,
        isbn_13=None,
        title="xv6: a simple, Unix-like teaching operating system",
        authors=("Russ Cox", "Frans Kaashoek", "Robert Morris"),
        publisher=None,
        published_year=2025,
        version="RISC-V rev5",
        home_url="https://pdos.csail.mit.edu/6.1810/2025/xv6.html",
        documents=(
            OpenTextbookDocumentSpec(
                document_type="full_text",
                external_id="mit-pdos:xv6-riscv-rev5",
                url=("https://pdos.csail.mit.edu/6.1810/2025/xv6/book-riscv-rev5.pdf"),
                expected_text_markers=(),
                identity_text_markers=(
                    "xv6: a simple, Unix-like teaching operating system",
                    "Russ Cox",
                    "Frans Kaashoek",
                    "Robert Morris",
                    "September 2, 2025",
                ),
                preface_text_markers=(
                    "Foreword and acknowledgments",
                    "draft text intended for a class on operating systems",
                    "multi-core RISC-V",
                ),
                sample_text_markers=(
                    "Chapter 1",
                    "Operating system interfaces",
                    "processes, memory, file descriptors, pipes",
                ),
            ),
        ),
        source_format="xv6_pdf_outline",
        license_url=("https://raw.githubusercontent.com/mit-pdos/xv6-riscv-book/xv6-riscv/LICENSE"),
        license_media_type="text/plain",
        license_reference_url="https://github.com/mit-pdos/xv6-riscv-book",
        license=None,
        max_resource_bytes=2 * 1024 * 1024,
        expected_page_count=116,
        preface_page_range=(6, 8),
        home_license_reference_url="https://creativecommons.org/licenses/by/3.0/us/",
        home_license="Creative Commons Attribution 3.0 United States License",
        sample_page_range=(8, 20),
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
    "think-os-0.7.4": OpenTextbookSourceSpec(
        slug="think-os-0.7.4",
        provider="green_tea_press",
        topic="operating-systems",
        replaces_book_id="isbn13:9781292025773",
        book_id="book_7d22aef622717f0ad24b",
        isbn_10=None,
        isbn_13=None,
        title="Think OS: A Brief Introduction to Operating Systems",
        authors=("Allen B. Downey",),
        publisher="Green Tea Press",
        published_year=2015,
        version="0.7.4",
        home_url="https://greenteapress.com/wp/think-os/",
        documents=(
            OpenTextbookDocumentSpec(
                document_type="toc",
                external_id="think-os-0.7.4:html-index",
                url="https://greenteapress.com/thinkos/html/index.html",
                media_type="text/html",
                expected_text_markers=(
                    "Think OS: A Brief Introduction to Operating Systems",
                    "Version 0.7.4",
                    "Compilation",
                    "Semaphores in C",
                ),
            ),
            OpenTextbookDocumentSpec(
                document_type="preface",
                external_id="think-os-0.7.4:preface",
                url="https://greenteapress.com/thinkos/html/thinkos001.html",
                media_type="text/html",
                expected_text_markers=(
                    "This book is intended for a different audience",
                    "A note on this draft",
                    "Contributor List",
                ),
            ),
            OpenTextbookDocumentSpec(
                document_type="sample_chapter",
                external_id="think-os-0.7.4:chapter-1",
                url="https://greenteapress.com/thinkos/html/thinkos003.html",
                media_type="text/html",
                expected_text_markers=(
                    "Chapter 1 Compilation",
                    "Compiled and interpreted languages",
                    "Understanding errors",
                ),
            ),
        ),
        source_format="think_os_html",
        license_reference_url="http://creativecommons.org/licenses/by-nc-sa/4.0/",
        license=(
            "Creative Commons Attribution-NonCommercial-ShareAlike 4.0 "
            "International Unported License"
        ),
        home_license_reference_url="http://creativecommons.org/licenses/by-nc/3.0/",
        home_license="Creative Commons Attribution-NonCommercial 3.0 Unported License",
        max_resource_bytes=1024 * 1024,
    ),
    "nicholson-linear-algebra-2023": OpenTextbookSourceSpec(
        slug="nicholson-linear-algebra-2023",
        provider="libretexts",
        topic="linear-algebra",
        replaces_book_id="isbn13:9780205080106",
        book_id="book_d061d898abc6ada0c56b",
        isbn_10=None,
        isbn_13=None,
        title="Linear Algebra with Applications",
        authors=("W. Keith Nicholson",),
        publisher="Lyryx",
        published_year=2023,
        version="2023-A-D",
        home_url=(
            "https://math.libretexts.org/Bookshelves/Linear_Algebra/"
            "Linear_Algebra_with_Applications_(Nicholson)"
        ),
        documents=(
            OpenTextbookDocumentSpec(
                document_type="metadata",
                external_id="open-textbook-library:533",
                url="https://open.umn.edu/opentextbooks/textbooks/533.html",
                media_type="text/html",
                expected_text_markers=(
                    "Linear Algebra with Applications",
                    "W. Keith Nicholson",
                    "2023-A-D",
                    "Lyryx",
                ),
                license="Attribution-NonCommercial-ShareAlike",
            ),
            OpenTextbookDocumentSpec(
                document_type="navigation",
                external_id="libretexts:nicholson:front-matter",
                url=(
                    "https://math.libretexts.org/Bookshelves/Linear_Algebra/"
                    "Linear_Algebra_with_Applications_(Nicholson)/00%3A_Front_Matter"
                ),
                media_type="text/html",
                expected_text_markers=("Front Matter", "TitlePage", "Preface"),
            ),
            OpenTextbookDocumentSpec(
                document_type="toc",
                external_id="libretexts:nicholson:chapter-1",
                url=(
                    "https://math.libretexts.org/Bookshelves/Linear_Algebra/"
                    "Linear_Algebra_with_Applications_(Nicholson)/"
                    "01%3A_Systems_of_Linear_Equations"
                ),
                media_type="text/html",
                expected_text_markers=(
                    "1: Systems of Linear Equations",
                    "1.0: Prelude to Systems of Linear Equations",
                    "1.E: Supplementary Exercises for Chapter 1",
                ),
            ),
            OpenTextbookDocumentSpec(
                document_type="toc",
                external_id="libretexts:nicholson:chapter-2",
                url=(
                    "https://math.libretexts.org/Bookshelves/Linear_Algebra/"
                    "Linear_Algebra_with_Applications_(Nicholson)/02%3A_Matrix_Algebra"
                ),
                media_type="text/html",
                expected_text_markers=(
                    "2: Matrix Algebra",
                    "2.0: Prelude to Matrix Algebra",
                    "2.E: Supplementary Exercises for Chapter 2",
                ),
            ),
            OpenTextbookDocumentSpec(
                document_type="toc",
                external_id="libretexts:nicholson:chapter-3",
                url=(
                    "https://math.libretexts.org/Bookshelves/Linear_Algebra/"
                    "Linear_Algebra_with_Applications_(Nicholson)/"
                    "03%3A_Determinants_and_Diagonalization"
                ),
                media_type="text/html",
                expected_text_markers=(
                    "3: Determinants and Diagonalization",
                    "3.0: Prelude to Determinants and Diagonalization",
                    "3.E: Supplementary Exercises for Chapter 3",
                ),
            ),
            OpenTextbookDocumentSpec(
                document_type="toc",
                external_id="libretexts:nicholson:chapter-4",
                url=(
                    "https://math.libretexts.org/Bookshelves/Linear_Algebra/"
                    "Linear_Algebra_with_Applications_(Nicholson)/04%3A_Vector_Geometry"
                ),
                media_type="text/html",
                expected_text_markers=(
                    "4: Vector Geometry",
                    "4.0: Prelude to Vector Geometry",
                    "4.E: Supplementary Exercises for Chapter 4",
                ),
            ),
            OpenTextbookDocumentSpec(
                document_type="toc",
                external_id="libretexts:nicholson:chapter-5",
                url=(
                    "https://math.libretexts.org/Bookshelves/Linear_Algebra/"
                    "Linear_Algebra_with_Applications_(Nicholson)/05%3A_Vector_Space_R"
                ),
                media_type="text/html",
                expected_text_markers=(
                    "5: Vector Space Rⁿ",
                    "5.0: Prelude to Vector Space Rⁿ",
                    "5.E: Supplementary Exercises for Chapter 5",
                ),
            ),
            OpenTextbookDocumentSpec(
                document_type="toc",
                external_id="libretexts:nicholson:chapter-6",
                url=(
                    "https://math.libretexts.org/Bookshelves/Linear_Algebra/"
                    "Linear_Algebra_with_Applications_(Nicholson)/06%3A_Vector_Spaces"
                ),
                media_type="text/html",
                expected_text_markers=(
                    "6: Vector Spaces",
                    "6.0: Prelude to Vector Spaces",
                    "6.E: Supplementary Exercises for Chapter 6",
                ),
            ),
            OpenTextbookDocumentSpec(
                document_type="toc",
                external_id="libretexts:nicholson:chapter-7",
                url=(
                    "https://math.libretexts.org/Bookshelves/Linear_Algebra/"
                    "Linear_Algebra_with_Applications_(Nicholson)/"
                    "07%3A_Linear_Transformations"
                ),
                media_type="text/html",
                expected_text_markers=(
                    "7: Linear Transformations",
                    "7.0: Prelude to Linear Transformations",
                    "7.5: More on Linear Recurrences",
                ),
            ),
            OpenTextbookDocumentSpec(
                document_type="toc",
                external_id="libretexts:nicholson:chapter-8",
                url=(
                    "https://math.libretexts.org/Bookshelves/Linear_Algebra/"
                    "Linear_Algebra_with_Applications_(Nicholson)/08%3A_Orthogonality"
                ),
                media_type="text/html",
                expected_text_markers=(
                    "8: Orthogonality",
                    "8.0: Prelude to Orthogonality",
                    "8.11: An Application to Statistical Principal Component Analysis",
                ),
            ),
            OpenTextbookDocumentSpec(
                document_type="toc",
                external_id="libretexts:nicholson:chapter-9",
                url=(
                    "https://math.libretexts.org/Bookshelves/Linear_Algebra/"
                    "Linear_Algebra_with_Applications_(Nicholson)/09%3A_Change_of_Basis"
                ),
                media_type="text/html",
                expected_text_markers=(
                    "9: Change of Basis",
                    "9.0: Prelude to Change of Basis",
                    "9.3: Invariant Subspaces and Direct Sums",
                ),
            ),
            OpenTextbookDocumentSpec(
                document_type="toc",
                external_id="libretexts:nicholson:chapter-10",
                url=(
                    "https://math.libretexts.org/Bookshelves/Linear_Algebra/"
                    "Linear_Algebra_with_Applications_(Nicholson)/"
                    "10%3A_Inner_Product_Spaces"
                ),
                media_type="text/html",
                expected_text_markers=(
                    "10: Inner Product Spaces",
                    "10.0: Prelude to Inner Product Spaces",
                    "10.5: An Application to Fourier Approximation",
                ),
            ),
            OpenTextbookDocumentSpec(
                document_type="toc",
                external_id="libretexts:nicholson:chapter-11",
                url=(
                    "https://math.libretexts.org/Bookshelves/Linear_Algebra/"
                    "Linear_Algebra_with_Applications_(Nicholson)/11%3A_Canonical_Forms"
                ),
                media_type="text/html",
                expected_text_markers=(
                    "11: Canonical Forms",
                    "11.0: Prelude to Canonical Forms",
                    "11.2: The Jordan Canonical Form",
                ),
            ),
            OpenTextbookDocumentSpec(
                document_type="toc",
                external_id="libretexts:nicholson:chapter-12",
                url=(
                    "https://math.libretexts.org/Bookshelves/Linear_Algebra/"
                    "Linear_Algebra_with_Applications_(Nicholson)/12%3A_Appendices"
                ),
                media_type="text/html",
                expected_text_markers=(
                    "12: Appendices",
                    "12.A: Complex Numbers",
                    "12.D: Polynomials",
                ),
            ),
            OpenTextbookDocumentSpec(
                document_type="preface",
                external_id="libretexts:nicholson:preface",
                url=(
                    "https://math.libretexts.org/Bookshelves/Linear_Algebra/"
                    "Linear_Algebra_with_Applications_(Nicholson)/00%3A_Front_Matter/"
                    "06%3A_Preface"
                ),
                media_type="text/html",
                expected_text_markers=(
                    "This textbook is an introduction to the ideas and techniques "
                    "of linear algebra",
                    "SUGGESTED COURSE OUTLINES",
                    "ACKNOWLEDGMENTS",
                ),
            ),
            OpenTextbookDocumentSpec(
                document_type="preview",
                external_id="libretexts:nicholson:section-1.1",
                url=(
                    "https://math.libretexts.org/Bookshelves/Linear_Algebra/"
                    "Linear_Algebra_with_Applications_(Nicholson)/"
                    "01%3A_Systems_of_Linear_Equations/"
                    "1.01%3A_Solutions_and_Elementary_Operations"
                ),
                media_type="text/html",
                expected_text_markers=(
                    "Practical problems in many fields of study",
                    "Elementary Operations",
                    "system of linear equations",
                ),
            ),
        ),
        source_format="libretexts_html",
        license_reference_url="https://creativecommons.org/licenses/by-nc-sa/4.0",
        license=("Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International License"),
        max_resource_bytes=512 * 1024,
    ),
    "hailperin-os-middleware-1.2": OpenTextbookSourceSpec(
        slug="hailperin-os-middleware-1.2",
        provider="open_textbook_library",
        topic="operating-systems",
        replaces_book_id="isbn13:9780471694663",
        book_id="book_28fad378fb6e900626f2",
        isbn_10=None,
        isbn_13=None,
        title="Operating Systems and Middleware: Supporting Controlled Interaction",
        authors=("Max Hailperin",),
        publisher="Max Hailperin",
        published_year=2015,
        version="Revised Edition 1.2",
        home_url=(
            "https://open.umn.edu/opentextbooks/textbooks/"
            "operating-systems-and-middleware-supporting-controlled-interaction.html"
        ),
        documents=(
            OpenTextbookDocumentSpec(
                document_type="full_text",
                external_id="internet-archive:osm-rev1.2",
                url="https://archive.org/download/osm-rev1.2/osm-rev1.2.pdf",
                expected_text_markers=(),
                identity_text_markers=(
                    "Operating Systems and Middleware: Supporting Controlled Interaction",
                    "Max Hailperin",
                    "Revised Edition 1.2",
                    "July 11, 2015",
                ),
                preface_text_markers=(
                    "Suppose you sit down at your computer",
                    "Audience",
                    "Features of the Text",
                    "Acknowledgments",
                ),
                sample_text_markers=(
                    "Chapter 1",
                    "What Is an Operating System?",
                    "What Is Middleware?",
                    "Security",
                ),
                license=("Creative Commons Attribution-ShareAlike 3.0 Unported License"),
                allowed_redirect_hosts=("archive.org",),
            ),
        ),
        source_format="hailperin_pdf_outline",
        license_reference_url="http://creativecommons.org/licenses/by-sa/3.0/",
        license="Creative Commons Attribution-ShareAlike 3.0 Unported License",
        max_resource_bytes=8 * 1024 * 1024,
        expected_page_count=559,
        preface_page_range=(10, 20),
        home_license="Attribution-ShareAlike",
        document_reference_url="https://open.umn.edu/opentextbooks/formats/33",
        sample_page_range=(20, 40),
    ),
}


def open_textbook_source(source_slug: str) -> OpenTextbookSourceSpec:
    """Return one reviewed open textbook or reject arbitrary URLs."""
    try:
        return OPEN_TEXTBOOK_SOURCES[source_slug]
    except KeyError as exc:
        choices = ", ".join(sorted(OPEN_TEXTBOOK_SOURCES))
        raise ValueError(f"open textbook source must be one of: {choices}") from exc
