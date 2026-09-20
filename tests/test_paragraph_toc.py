from datetime import UTC, datetime

import pytest

from data_pipeline.collectors.base import InvalidProviderResponse
from data_pipeline.normalizers import (
    _paragraph_sequence_toc_entries,
    normalize_public_book_page_response,
)
from data_pipeline.public_book_sources import public_book_source


def page(content: str) -> str:
    return (
        '<div class="summary"><h2>Table of Contents</h2><div class="content">'
        + content
        + "</div></div>"
    )


def test_paragraph_toc_restores_part_and_chapter_hierarchy() -> None:
    entries = _paragraph_sequence_toc_entries(
        page(
            "<p><b>Part 1 Overview</b></p>"
            "<p>Chapter 1 Introduction</p>"
            "<p>Chapter 2. Structures</p>"
            "<p><b>PART TWO. MEMORY.</b></p>"
            "<p>Chapter A Appendix Material</p>"
        ),
        "book",
        "source",
    )

    assert [(entry.level, entry.label, entry.title) for entry in entries] == [
        (1, "Part 1", "Overview"),
        (2, "1", "Introduction"),
        (2, "2", "Structures"),
        (1, "PART TWO", "MEMORY."),
        (2, "A", "Appendix Material"),
    ]
    assert entries[1].parent_entry_id == entries[0].toc_entry_id
    assert entries[4].parent_entry_id == entries[3].toc_entry_id


def test_operating_system_concepts_10_reviewed_sequence() -> None:
    source = public_book_source("ecampus-osc10")
    parts = (
        ("Part 1 Overview", ("1 Introduction", "2 Operating-System Structures")),
        (
            "Part 2 Process Management",
            ("3 Processes", "4 Threads & Concurrency", "5 CPU Scheduling"),
        ),
        (
            "Part 3 Process Synchronization",
            ("6 Synchronization Tools", "7 Synchronization Examples", "8 Deadlocks"),
        ),
        ("Part 4 Memory Management", ("9 Main Memory", "10 Virtual Memory")),
        ("Part 5 Storage Management", ("11 Mass-Storage Structure", "12 I/O Systems")),
        (
            "Part 6 File System",
            (
                "13 File-System Interface",
                "14 File-System Implementation",
                "15 File-System Internals",
            ),
        ),
        ("Part 7 Security and Protection", ("16 Security", "17 Protection")),
        (
            "Part 8 Advanced Topics",
            ("18 Virtual Machines", "19 Network and Distributed Systems"),
        ),
        ("Part 9 Case Studies", ("20 The Linux System", "21 Windows 10")),
        (
            "Part 10 Appendices",
            (
                "A Influential Operating Systems",
                "B Windows 7",
                "C BSD Unix",
                "D The Mach System",
                "E Exercises",
            ),
        ),
    )
    toc_html = "".join(
        f"<p><b>{part}</b></p>" + "".join(f"<p>Chapter {chapter}</p>" for chapter in chapters)
        for part, chapters in parts
    )
    html = (
        f'<h1 class="title">{source.title}</h1>'
        f'<span itemprop="isbn">{source.isbn_13}</span>'
        f'<span itemprop="bookEdition">{source.edition}th</span>'
        '<div class="summary">'
        '<h2>Summary</h2><div class="content">Reviewed description.</div>'
        f'<h2>Table of Contents</h2><div class="content">{toc_html}</div>'
        "</div>"
    )

    dataset = normalize_public_book_page_response(
        {"source_slug": source.slug, "url": source.url, "html": html},
        topic=source.topic,
        retrieved_at=datetime(2026, 9, 21, tzinfo=UTC),
    )

    assert len(dataset.toc) == 36
    assert tuple(entry.title for entry in dataset.toc if entry.level == 1) == (
        source.expected_root_titles
    )


@pytest.mark.parametrize(
    "content",
    [
        "<p>Chapter 1 Orphan</p>",
        "<p><b>Part 1 Overview</b></p><p>Unsupported entry</p>",
        "<p><b>Part 1 Overview</b></p>lost text",
    ],
)
def test_paragraph_toc_rejects_unsupported_content(content: str) -> None:
    with pytest.raises(InvalidProviderResponse):
        _paragraph_sequence_toc_entries(page(content), "book", "source")
