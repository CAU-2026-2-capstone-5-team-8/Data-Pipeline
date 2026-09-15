"""Reviewed public documents linked from exact-edition publisher pages."""

from dataclasses import dataclass


@dataclass(frozen=True)
class PublisherDocumentSourceSpec:
    """Exact-book identity and integrity checks for one public publisher document."""

    slug: str
    provider: str
    topic: str
    book_id: str
    isbn_10: str
    title: str
    edition: int
    document_type: str
    external_id: str
    home_url: str
    referrer_url: str
    document_url: str
    referrer_heading: str
    source_type: str
    require_document_link: bool
    rights_note: str
    expected_text_markers: tuple[str, ...]


PUBLISHER_DOCUMENT_SOURCES = {
    "wiley-osc7-appendix-b": PublisherDocumentSourceSpec(
        slug="wiley-osc7-appendix-b",
        provider="wiley",
        topic="operating-systems",
        book_id="isbn13:9780471694663",
        isbn_10="0471694665",
        title="Operating System Concepts",
        edition=7,
        document_type="other",
        external_id="0471694665:appendix-b",
        home_url=(
            "https://bcs.wiley.com/he-bcs/Books?"
            "action=index&bcsId=2217&itemId=0471694665&itemTypeId=BKS"
        ),
        referrer_url=(
            "https://bcs.wiley.com/he-bcs/Books?action=contents&itemId=0471694665&bcsId=2217"
        ),
        document_url=(
            "https://higheredbcs.wiley.com/legacy/college/"
            "silberschatz/0471694665/appendices/appb.pdf"
        ),
        referrer_heading="Appendix B: The Mach System",
        source_type="publisher_page",
        require_document_link=True,
        rights_note=(
            "Public supplemental appendix linked from the exact-edition publisher "
            "companion page; no license statement found."
        ),
        expected_text_markers=(
            "The Mach System",
            "History of the Mach System",
            "Programmer Interface",
        ),
    ),
    "wiley-ela10-chapter-1": PublisherDocumentSourceSpec(
        slug="wiley-ela10-chapter-1",
        provider="wiley",
        topic="linear-algebra",
        book_id="isbn13:9780470458211",
        isbn_10="0470458216",
        title="Elementary Linear Algebra",
        edition=10,
        document_type="sample_chapter",
        external_id="9780470458211:excerpt:chapter-1",
        home_url=("https://bcs.wiley.com/he-bcs/Books?action=index&bcsId=5557&itemId=0470458216"),
        referrer_url=(
            "https://bcs.wiley.com/he-bcs/Books?action=contents&bcsId=5557&itemId=0470458216"
        ),
        document_url=("https://catalogimages.wiley.com/images/db/pdf/9780470458211.excerpt.pdf"),
        referrer_heading="Chapter 1: Systems of Linear Equations and Matrices",
        source_type="sample_page",
        require_document_link=False,
        rights_note=(
            "Public chapter excerpt on Wiley's catalog host, bound to the exact edition by "
            "the ISBN-bearing URL, companion page, TOC heading, and PDF text markers; no "
            "reuse license statement found."
        ),
        expected_text_markers=(
            "Systems of Linear Equations and Matrices",
            "Introduction to Systems of Linear Equations",
            "Leontief Input-Output Models",
        ),
    ),
}


def publisher_document_source(source_slug: str) -> PublisherDocumentSourceSpec:
    """Return one reviewed public document or reject arbitrary URLs."""
    try:
        return PUBLISHER_DOCUMENT_SOURCES[source_slug]
    except KeyError as exc:
        choices = ", ".join(sorted(PUBLISHER_DOCUMENT_SOURCES))
        raise ValueError(f"publisher document source must be one of: {choices}") from exc
