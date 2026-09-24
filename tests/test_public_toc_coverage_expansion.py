"""Contract tests for the three exact-edition catalog TOCs added for Scale-50 coverage.

Each source was discovered by searching the already-allowlisted eCampus catalog for the
canonical target ISBN. These tests pin the reviewed structure so a later catalog change
fails loudly instead of silently importing a different book's contents.
"""

from datetime import UTC, datetime

import pytest

from data_pipeline.collectors.base import InvalidProviderResponse
from data_pipeline.normalizers import normalize_public_book_page_response
from data_pipeline.public_book_sources import public_book_source

FOOTER = "Table of Contents provided by Publisher. All Rights Reserved."
ORDINALS = {1: "1st", 2: "2nd", 3: "3rd"}


def indented_row(title: str, indent: int) -> str:
    if indent == 0:
        return f"<tr><td>{title}</td></tr>"
    return f'<tr><td><table><tr><td width="{indent}"></td><td>{title}</td></tr></table></td></tr>'


def catalog_page(source, rows: list[str], *, edition: str | None = None) -> str:
    """Rebuild the parts of the catalog page the normalizer actually reads."""
    edition_text = edition if edition is not None else ORDINALS[source.edition]
    return (
        f'<h1 class="title">{source.title}</h1>'
        f'<span itemprop="isbn">{source.isbn_13}</span>'
        f'<span itemprop="bookEdition">{edition_text}</span>'
        '<div class="summary">'
        '<h2>Summary</h2><div class="content">Reviewed description.</div>'
        "<h2>Table of Contents</h2>"
        f'<div class="content"><table>{"".join(rows)}</table></div>'
        "</div>"
    )


def indented_rows(source) -> list[str]:
    """Rebuild the reviewed two-level hierarchy from the pinned contract."""
    root_indent = 20 if source.toc_format == "indented_table_chapter_roots" else 0
    child_indent = root_indent + 20
    rows: list[str] = []
    for root_index, (title, child_count) in enumerate(
        zip(source.expected_root_titles, source.expected_child_counts, strict=True)
    ):
        # Front matter and back matter sit above the chapter threshold.
        rows.append(indented_row(title, root_indent if child_count else 0))
        rows.extend(
            indented_row(f"Section {root_index}.{index}", child_indent)
            for index in range(child_count)
        )
    return rows


def normalize(source, html: str):
    return normalize_public_book_page_response(
        {"source_slug": source.slug, "url": source.url, "html": html},
        topic=source.topic,
        retrieved_at=datetime(2026, 9, 23, tzinfo=UTC),
    )


def test_axler_flat_catalog_toc_matches_reviewed_rows() -> None:
    source = public_book_source("ecampus-axler-linear-algebra-done-right2")
    rows = [f"<tr><td>{title}</td><td></td></tr>" for title in source.expected_root_titles]
    rows.append(f"<tr><td>{FOOTER}</td><td></td></tr>")

    dataset = normalize(source, catalog_page(source, rows))

    assert len(dataset.toc) == source.expected_toc_count == 10
    assert tuple(entry.title for entry in dataset.toc) == source.expected_root_titles
    assert {entry.level for entry in dataset.toc} == {1}
    # The publisher footer is a legal notice, never a chapter.
    assert FOOTER not in {entry.title for entry in dataset.toc}


@pytest.mark.parametrize("slug", ["ecampus-harris-schaum-os1", "ecampus-sinha-distributed-os1"])
def test_indented_catalog_toc_matches_reviewed_hierarchy(slug: str) -> None:
    source = public_book_source(slug)

    dataset = normalize(source, catalog_page(source, indented_rows(source)))

    assert len(dataset.toc) == source.expected_toc_count
    roots = tuple(entry.title for entry in dataset.toc if entry.parent_entry_id is None)
    assert roots == source.expected_root_titles
    child_counts = tuple(
        sum(entry.parent_entry_id == root.toc_entry_id for entry in dataset.toc)
        for root in dataset.toc
        if root.parent_entry_id is None
    )
    assert child_counts == source.expected_child_counts
    # Every reviewed section hangs off a chapter; nothing is orphaned at level 3.
    assert {entry.level for entry in dataset.toc} <= {1, 2}


@pytest.mark.parametrize(
    "slug",
    [
        "ecampus-axler-linear-algebra-done-right2",
        "ecampus-harris-schaum-os1",
        "ecampus-sinha-distributed-os1",
    ],
)
def test_new_sources_reject_a_different_edition(slug: str) -> None:
    """A catalog page that stops declaring the reviewed edition must not be imported."""
    source = public_book_source(slug)
    if source.toc_format == "flat_table":
        rows = [f"<tr><td>{title}</td><td></td></tr>" for title in source.expected_root_titles]
        rows.append(f"<tr><td>{FOOTER}</td><td></td></tr>")
    else:
        rows = indented_rows(source)

    with pytest.raises(InvalidProviderResponse):
        normalize(source, catalog_page(source, rows, edition="9th"))


@pytest.mark.parametrize(
    "slug",
    [
        "ecampus-axler-linear-algebra-done-right2",
        "ecampus-harris-schaum-os1",
        "ecampus-sinha-distributed-os1",
    ],
)
def test_new_sources_reject_a_truncated_toc(slug: str) -> None:
    """A partially rendered catalog page must fail instead of importing a short TOC."""
    source = public_book_source(slug)
    if source.toc_format == "flat_table":
        rows = [f"<tr><td>{title}</td><td></td></tr>" for title in source.expected_root_titles[:-1]]
        rows.append(f"<tr><td>{FOOTER}</td><td></td></tr>")
    else:
        rows = indented_rows(source)[:-1]

    with pytest.raises(InvalidProviderResponse):
        normalize(source, catalog_page(source, rows))
