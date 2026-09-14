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
        expected_text_markers=(
            "The Mach System",
            "History of the Mach System",
            "Programmer Interface",
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
