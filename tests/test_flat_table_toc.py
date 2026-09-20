from datetime import UTC, datetime

import pytest

from data_pipeline.collectors.base import InvalidProviderResponse
from data_pipeline.normalizers import (
    _flat_table_toc_entries,
    normalize_public_book_page_response,
)
from data_pipeline.public_book_sources import public_book_source

FOOTER = "Table of Contents provided by Publisher. All Rights Reserved."


def page(rows: tuple[tuple[str, str], ...]) -> str:
    body = "".join(f"<tr><td>{first}</td><td>{second}</td></tr>" for first, second in rows)
    return (
        '<div class="summary"><h2>Table of Contents</h2>'
        f'<div class="content"><table>{body}</table></div></div>'
    )


def test_flat_table_preserves_rows_and_excludes_verified_footer() -> None:
    entries = _flat_table_toc_entries(
        page((("Vector Spaces", ""), ("Linear Independence", ""), (FOOTER, ""))),
        "book",
        "source",
    )

    assert [(entry.level, entry.label, entry.title) for entry in entries] == [
        (1, None, "Vector Spaces"),
        (1, None, "Linear Independence"),
    ]
    assert [entry.order_index for entry in entries] == [0, 1]


@pytest.mark.parametrize(
    "rows",
    [
        (("Vector Spaces", ""),),
        ((FOOTER, ""), ("Vector Spaces", "")),
        (("Vector Spaces", "unexpected"), (FOOTER, "")),
        (("", ""), (FOOTER, "")),
    ],
)
def test_flat_table_rejects_changed_structure(rows: tuple[tuple[str, str], ...]) -> None:
    with pytest.raises(InvalidProviderResponse):
        _flat_table_toc_entries(page(rows), "book", "source")


def test_larson_source_contract_covers_every_reviewed_row() -> None:
    source = public_book_source("ecampus-larson-linear-algebra5")
    rows = tuple((title, "") for title in source.expected_root_titles) + ((FOOTER, ""),)
    toc_page = page(rows)
    toc_section = toc_page.removeprefix('<div class="summary">').removesuffix("</div>")
    html = (
        f'<h1 class="title">{source.title}</h1>'
        f'<span itemprop="isbn">{source.isbn_13}</span>'
        f'<span itemprop="bookEdition">{source.edition}th</span>'
        '<div class="summary">'
        '<h2>Summary</h2><div class="content">Reviewed description.</div>'
        f"{toc_section}</div>"
    )

    dataset = normalize_public_book_page_response(
        {"source_slug": source.slug, "url": source.url, "html": html},
        topic=source.topic,
        retrieved_at=datetime(2026, 9, 21, tzinfo=UTC),
    )

    assert len(dataset.toc) == source.expected_toc_count
    assert tuple(entry.title for entry in dataset.toc) == source.expected_root_titles
