from datetime import UTC, datetime

from data_pipeline.normalizers import (
    _indented_table_toc_entries,
    normalize_public_book_page_response,
)
from data_pipeline.public_book_sources import public_book_source


def row(title: str, indent: int) -> str:
    if indent == 0:
        return f"<tr><td>{title}</td></tr>"
    return f'<tr><td><table><tr><td width="{indent}"></td><td>{title}</td></tr></table></td></tr>'


def page(rows: list[str]) -> str:
    return (
        '<div class="summary"><h2>Table of Contents</h2>'
        f'<div class="content"><table>{"".join(rows)}</table></div></div>'
    )


def test_chapter_root_threshold_does_not_nest_chapters_under_front_matter() -> None:
    entries = _indented_table_toc_entries(
        page(
            [
                row("To the Instructor", 0),
                row("Introduction", 20),
                row("Processes", 40),
                row("Process States", 60),
                row("Memory Management", 20),
                row("Paging", 40),
                row("Index", 0),
            ]
        ),
        "book",
        "source",
        root_indent_threshold=20,
    )

    assert [(entry.level, entry.title) for entry in entries] == [
        (1, "To the Instructor"),
        (1, "Introduction"),
        (2, "Processes"),
        (3, "Process States"),
        (1, "Memory Management"),
        (2, "Paging"),
        (1, "Index"),
    ]
    assert entries[2].parent_entry_id == entries[1].toc_entry_id
    assert entries[3].parent_entry_id == entries[2].toc_entry_id
    assert entries[4].parent_entry_id is None


def test_nutt_source_contract_covers_reviewed_hierarchy() -> None:
    source = public_book_source("ecampus-nutt-os3")
    rows = []
    for root_index, (title, child_count, descendant_count) in enumerate(
        zip(
            source.expected_root_titles,
            source.expected_child_counts,
            source.expected_descendant_counts,
            strict=True,
        )
    ):
        indent = 20 if 3 <= root_index <= 20 else 0
        rows.append(row(title, indent))
        rows.extend(row(f"Section {root_index}.{index}", 40) for index in range(child_count))
        rows.extend(
            row(f"Topic {root_index}.{index}", 60)
            for index in range(descendant_count - child_count)
        )
    toc_page = page(rows)
    toc_section = toc_page.removeprefix('<div class="summary">').removesuffix("</div>")
    html = (
        f'<h1 class="title">{source.title}</h1>'
        f'<span itemprop="isbn">{source.isbn_13}</span>'
        f'<span itemprop="bookEdition">{source.edition}rd</span>'
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
    assert tuple(entry.title for entry in dataset.toc if entry.level == 1) == (
        source.expected_root_titles
    )
