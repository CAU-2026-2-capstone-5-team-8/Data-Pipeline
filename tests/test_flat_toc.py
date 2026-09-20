import pytest

from data_pipeline.collectors.base import InvalidProviderResponse
from data_pipeline.normalizers import _flat_bold_toc_entries


def page(content):
    return (
        '<div class="summary"><h2>Table of Contents</h2><div class="content">'
        + content
        + "</div></div>"
    )


def test_flat_bold_toc_retains_chapter_labels_and_front_matter():
    entries = _flat_bold_toc_entries(
        page("<b>Preface.</b><br><b>1. Intro.</b><br><b>2. Files.</b>"), "book", "source"
    )
    assert [(e.label, e.title, e.level, e.parent_entry_id) for e in entries] == [
        (None, "Preface.", 1, None),
        ("1", "Intro.", 1, None),
        ("2", "Files.", 1, None),
    ]
    assert [e.order_index for e in entries] == [0, 1, 2]
    assert all(e.source_id == "source" for e in entries)


@pytest.mark.parametrize(
    "content", ["<p>No supported TOC</p>", "<b></b>", "<b>1. Intro.</b><br>lost text"]
)
def test_flat_bold_toc_rejects_unsupported_or_unparsed_content(content):
    with pytest.raises(InvalidProviderResponse):
        _flat_bold_toc_entries(page(content), "book", "source")
