from datetime import UTC, datetime

import pytest

from data_pipeline.collectors.base import InvalidProviderResponse
from data_pipeline.normalizers import (
    _bold_chapter_paragraph_toc_entries,
    normalize_public_book_page_response,
)
from data_pipeline.public_book_sources import public_book_source


def page(content: str) -> str:
    return (
        '<div class="summary"><h2>Table of Contents</h2><div class="content">'
        + content
        + "</div></div>"
    )


def test_bold_chapter_paragraphs_preserve_observed_two_level_hierarchy() -> None:
    entries = _bold_chapter_paragraph_toc_entries(
        page(
            "<p>Preface xi</p>"
            "<p><b>1 Vector Spaces 1</b></p>"
            "<p>1.1 Subspaces 2</p>"
            "<p>Exercises 8</p>"
            "<p><b>2 Matrices 10</b></p>"
            "<p>2.1 Products 11</p>"
            "<p>Answers and Hints 40</p>"
            "<p>Index 45</p>"
        ),
        "book",
        "source",
    )

    assert [(entry.level, entry.label, entry.title) for entry in entries] == [
        (1, None, "Preface"),
        (1, "1", "Vector Spaces"),
        (2, "1.1", "Subspaces"),
        (2, None, "Exercises"),
        (1, "2", "Matrices"),
        (2, "2.1", "Products"),
        (1, None, "Answers and Hints"),
        (1, None, "Index"),
    ]
    assert entries[2].parent_entry_id == entries[1].toc_entry_id
    assert entries[5].parent_entry_id == entries[4].toc_entry_id
    assert entries[6].parent_entry_id is None


@pytest.mark.parametrize(
    "content",
    [
        "<p>Preface</p>",
        "<p><b>Chapter One 1</b></p>",
        "<p><b>1 Chapter</b> 1</p>",
        "<p>Preface xi</p>lost text",
    ],
)
def test_bold_chapter_paragraphs_reject_unsupported_content(content: str) -> None:
    with pytest.raises(InvalidProviderResponse):
        _bold_chapter_paragraph_toc_entries(page(content), "book", "source")


def test_penney_source_contract_covers_every_reviewed_entry() -> None:
    source = public_book_source("ecampus-penney-linear-algebra4")
    roots = []
    for index, (title, child_labels, child_count) in enumerate(
        zip(
            source.expected_root_titles,
            source.expected_child_label_groups,
            source.expected_child_counts,
            strict=True,
        )
    ):
        if 4 <= index <= 11:
            chapter_label = str(index - 3)
            roots.append(f"<p><b>{chapter_label} {title} {index + 1}</b></p>")
            roots.extend(
                f"<p>{label} Reviewed section {child_index + 10}</p>"
                for child_index, label in enumerate(child_labels)
            )
            roots.extend(
                f"<p>Reviewed topic {child_index} {child_index + 100}</p>"
                for child_index in range(child_count - len(child_labels))
            )
        else:
            page_number = "xi" if index < 4 else str(index + 500)
            roots.append(f"<p>{title} {page_number}</p>")
    html = (
        f'<h1 class="title">{source.title}</h1>'
        f'<span itemprop="isbn">{source.isbn_13}</span>'
        f'<span itemprop="bookEdition">{source.edition}th</span>'
        '<div class="summary">'
        '<h2>Summary</h2><div class="content">Reviewed description.</div>'
        f'<h2>Table of Contents</h2><div class="content">{"".join(roots)}</div>'
        "</div>"
    )

    dataset = normalize_public_book_page_response(
        {"source_slug": source.slug, "url": source.url, "html": html},
        topic=source.topic,
        retrieved_at=datetime(2026, 9, 21, tzinfo=UTC),
    )

    assert len(dataset.toc) == source.expected_toc_count
    assert tuple(entry.title for entry in dataset.toc if entry.level == 1) == (
        source.expected_root_titles
    )
