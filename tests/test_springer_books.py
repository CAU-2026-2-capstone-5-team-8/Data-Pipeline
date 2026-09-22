"""Contract tests for the reviewed Springer book landing-page source."""

import json
from datetime import UTC, datetime

import pytest

from data_pipeline.collectors.base import InvalidProviderResponse
from data_pipeline.normalizers import normalize_springer_book_response
from data_pipeline.springer_book_sources import springer_book_source

SLUG = "springer-axler-linear-algebra-done-right3"


def chapter(title: str, pages: str | None = "Pages 1-26") -> str:
    page_markup = f'<span data-test="page-number">{pages}</span>' if pages else ""
    return (
        '<li data-test="chapter"><div class="app-card-open__main">'
        f'<h3 class="app-card-open__heading"><a href="/chapter/x">{title}</a></h3>'
        f'<div class="c-meta">{page_markup}</div></div></li>'
    )


def page(source, *, titles=None, isbn=None, name=None, edition_label=None) -> str:
    """Rebuild only the parts of the Springer page the normalizer reads."""
    entries = source.expected_entry_titles if titles is None else titles
    structured = {
        "@type": "Book",
        "name": source.title if name is None else name,
        "isbn": source.ebook_isbn if isbn is None else isbn,
    }
    label = source.springer_edition_label if edition_label is None else edition_label
    return (
        f'<script type="application/ld+json">{json.dumps(structured)}</script>'
        f"<div>{label}</div>"
        f'<div data-title="book-toc"><ol>{"".join(chapter(t) for t in entries)}</ol></div>'
    )


def normalize(source, html: str):
    return normalize_springer_book_response(
        {"source_slug": source.slug, "url": source.url, "html": html},
        topic=source.topic,
        retrieved_at=datetime(2026, 9, 23, tzinfo=UTC),
    )


def test_reviewed_chapter_sequence_becomes_canonical_toc() -> None:
    source = springer_book_source(SLUG)

    dataset = normalize(source, page(source))

    assert len(dataset.toc) == len(source.expected_entry_titles)
    assert tuple(entry.title for entry in dataset.toc) == source.expected_entry_titles
    assert [entry.order_index for entry in dataset.toc] == list(range(len(dataset.toc)))
    # Springer publishes a flat chapter list and the pipeline does not invent a hierarchy.
    assert {entry.level for entry in dataset.toc} == {1}
    assert all(entry.parent_entry_id is None for entry in dataset.toc)


def test_alternate_springer_edition_is_not_recorded_as_exact() -> None:
    """The canonical record is the print 2nd edition; Springer hosts the 3rd."""
    source = springer_book_source(SLUG)
    assert source.edition_relation == "same_work"

    provenance = normalize(source, page(source)).sources[0].evidence

    assert provenance is not None
    assert provenance.tier == "same_work_alternate_edition_toc"
    assert provenance.same_edition is False
    assert provenance.validation_status == "acceptable"
    assert "exact_edition" not in provenance.match_basis


def test_no_chapter_text_or_description_is_imported() -> None:
    """Only chapter titles are taken; chapter bodies stay behind the publisher."""
    dataset = normalize(springer_book_source(SLUG), page(springer_book_source(SLUG)))

    assert dataset.documents == []
    assert dataset.books == []


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({"isbn": "9780000000000"}, "a different book's ISBN"),
        ({"name": "Linear Algebra Done Wrong"}, "a different title"),
        ({"edition_label": "5th edition"}, "a different edition"),
    ],
)
def test_identity_mismatch_is_rejected(kwargs: dict, reason: str) -> None:
    source = springer_book_source(SLUG)

    with pytest.raises(InvalidProviderResponse):
        normalize(source, page(source, **kwargs))


def test_changed_chapter_sequence_is_rejected() -> None:
    """A restructured page must fail instead of silently importing new contents."""
    source = springer_book_source(SLUG)
    shortened = source.expected_entry_titles[:-1]

    with pytest.raises(InvalidProviderResponse):
        normalize(source, page(source, titles=shortened))


def test_missing_table_of_contents_is_rejected() -> None:
    source = springer_book_source(SLUG)
    structured = json.dumps({"@type": "Book", "name": source.title, "isbn": source.ebook_isbn})
    html = f'<script type="application/ld+json">{structured}</script><div>3rd edition</div>'

    with pytest.raises(InvalidProviderResponse, match="table of contents"):
        normalize(source, html)


def test_untitled_entry_is_rejected() -> None:
    source = springer_book_source(SLUG)
    titles = list(source.expected_entry_titles)
    titles[1] = ""

    with pytest.raises(InvalidProviderResponse):
        normalize(source, page(source, titles=titles))


def test_unknown_slug_is_rejected() -> None:
    with pytest.raises(InvalidProviderResponse, match="springer book source must be one of"):
        normalize_springer_book_response(
            {"source_slug": "springer-not-reviewed", "url": "https://link.springer.com/book/x"},
            topic="linear-algebra",
            retrieved_at=datetime(2026, 9, 23, tzinfo=UTC),
        )


def test_url_outside_the_allowlist_is_rejected() -> None:
    source = springer_book_source(SLUG)

    with pytest.raises(InvalidProviderResponse, match="URL does not match allowlist"):
        normalize_springer_book_response(
            {"source_slug": source.slug, "url": "https://link.springer.com/book/other"},
            topic=source.topic,
            retrieved_at=datetime(2026, 9, 23, tzinfo=UTC),
        )
