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
    toc_format: Literal[
        "indented_table",
        "heading_sequence",
        "flat_bold",
        "paragraph_sequence",
        "bold_chapter_paragraphs",
    ]
    expected_toc_count: int
    expected_root_titles: tuple[str, ...]
    expected_chapter_labels: tuple[str, ...]
    expected_child_label_groups: tuple[tuple[str, ...], ...] = ()
    expected_child_counts: tuple[int, ...] = ()


PUBLIC_BOOK_SOURCES = {
    "ecampus-osc10": PublicBookSourceSpec(
        slug="ecampus-osc10",
        provider="ecampus",
        topic="operating-systems",
        book_id="isbn13:9781119800361",
        isbn_13="9781119800361",
        title="Operating System Concepts",
        edition=10,
        url="https://umass.ecampus.com/operating-system-concepts-10th/bk/9781119800361",
        toc_format="paragraph_sequence",
        expected_toc_count=36,
        expected_root_titles=(
            "Overview",
            "Process Management",
            "Process Synchronization",
            "Memory Management",
            "Storage Management",
            "File System",
            "Security and Protection",
            "Advanced Topics",
            "Case Studies",
            "Appendices",
        ),
        expected_chapter_labels=(
            *(str(number) for number in range(1, 22)),
            "A",
            "B",
            "C",
            "D",
            "E",
        ),
        expected_child_label_groups=(
            ("1", "2"),
            ("3", "4", "5"),
            ("6", "7", "8"),
            ("9", "10"),
            ("11", "12"),
            ("13", "14", "15"),
            ("16", "17"),
            ("18", "19"),
            ("20", "21"),
            ("A", "B", "C", "D", "E"),
        ),
    ),
    "ecampus-penney-linear-algebra4": PublicBookSourceSpec(
        slug="ecampus-penney-linear-algebra4",
        provider="ecampus",
        topic="linear-algebra",
        book_id="isbn13:9781118909584",
        isbn_13="9781118909584",
        title="Linear Algebra Ideas and Applications",
        edition=4,
        url=("https://wright.ecampus.com/linear-algebra-ideas-applications-4th/bk/9781118909584"),
        toc_format="bold_chapter_paragraphs",
        expected_toc_count=161,
        expected_root_titles=(
            "Preface",
            "Features of the Text",
            "Acknowledgments",
            "About the Companion Website",
            "Systems of Linear Equations",
            "Linear Independence and Dimension",
            "Linear Transformations",
            "Determinants",
            "Eigenvectors and Eigenvalues",
            "Orthogonality",
            "Generalized Eigenvectors",
            "Numerical Techniques",
            "Answers and Hints",
            "Index",
        ),
        expected_chapter_labels=tuple(str(number) for number in range(1, 9)),
        expected_child_label_groups=(
            (),
            (),
            (),
            (),
            (
                "1.1",
                "1.1.1",
                "1.1.2",
                "1.2",
                "1.2.1",
                "1.2.2",
                "1.3",
                "1.3.1",
                "1.3.2",
                "1.4",
                "1.4.1",
            ),
            ("2.1", "2.1.1", "2.2", "2.2.1", "2.2.2", "2.3", "2.3.1"),
            (
                "3.1",
                "3.1.1",
                "3.2",
                "3.2.1",
                "3.2.2",
                "3.3",
                "3.3.1",
                "3.3.2",
                "3.4",
                "3.4.1",
                "3.5",
                "3.5.1",
            ),
            ("4.1", "4.1.1", "4.1.2", "4.2", "4.2.1", "4.3"),
            ("5.1", "5.1.1", "5.1.2", "5.2", "5.2.1", "5.2.2", "5.3", "5.3.1"),
            (
                "6.1",
                "6.2",
                "6.2.1",
                "6.3",
                "6.3.1",
                "6.3.2",
                "6.4",
                "6.4.1",
                "6.5",
                "6.5.1",
                "6.6",
                "6.6.1",
                "6.7",
                "6.8",
            ),
            ("7.1", "7.2"),
            ("8.1", "8.2"),
            (),
            (),
        ),
        expected_child_counts=(0, 0, 0, 0, 26, 16, 26, 12, 16, 34, 7, 10, 0, 0),
    ),
    "ecampus-tanenbaum-distributed1": PublicBookSourceSpec(
        slug="ecampus-tanenbaum-distributed1",
        provider="ecampus",
        topic="operating-systems",
        book_id="isbn13:9780132199087",
        isbn_13="9780132199087",
        title="Distributed Operating Systems",
        edition=1,
        url="https://cincinnatistate.ecampus.com/distributed-operating-systems-1st/bk/9780132199087",
        toc_format="flat_bold",
        expected_toc_count=12,
        expected_root_titles=(
            "Preface.",
            "Introduction to Distributed Systems.",
            "Communication in Distributed Systems.",
            "Synchronization in Distributed Systems.",
            "Processes and Processors in Distributed Systems.",
            "Distributed File Systems.",
            "Distributed Shared Memory.",
            "Case Study I: Amoeba.",
            "Case Study II: Mach.",
            "Case Study III: Chorus.",
            "Case Study IV: DCE.",
            "Index.",
        ),
        expected_chapter_labels=tuple(str(number) for number in range(1, 11)),
    ),
    "ecampus-bach-unix1": PublicBookSourceSpec(
        slug="ecampus-bach-unix1",
        provider="ecampus",
        topic="operating-systems",
        book_id="isbn13:9780132017992",
        isbn_13="9780132017992",
        title="Design of the UNIX Operating System",
        edition=1,
        url="https://wright.ecampus.com/design-unix-operating-system-1st-bach/bk/9780132017992",
        toc_format="flat_bold",
        expected_toc_count=12,
        expected_root_titles=(
            "General Review of the System.",
            "Introduction to the Kernel.",
            "The Buffer Cache.",
            "Internal Representation of Files.",
            "System Calls for the File System.",
            "The System Representation of Processes.",
            "Process Control.",
            "Process Scheduling and Time.",
            "Memory Management Policies.",
            "Interprocess Communication.",
            "Multiprocessor Systems.",
            "Distributed UNIX System.",
        ),
        expected_chapter_labels=tuple(str(number) for number in range(1, 13)),
    ),
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
