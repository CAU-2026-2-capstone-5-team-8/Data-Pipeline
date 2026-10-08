"""Fail-closed contracts for the official Xinu second-edition TOC and preface."""

import base64
from dataclasses import replace
from datetime import UTC, datetime

import httpx
import pytest

from data_pipeline.collectors.base import InvalidProviderResponse
from data_pipeline.collectors.public_book_pages import PublicBookPageCollector
from data_pipeline.normalizers import (
    normalize_public_book_page_response,
    normalize_publisher_document_response,
)
from data_pipeline.public_book_sources import public_book_source
from data_pipeline.publisher_document_sources import publisher_document_source

RETRIEVED_AT = datetime(2026, 9, 29, tzinfo=UTC)


def compact_xinu_toc(*, edition: int = 2, isbn: str | None = None) -> str:
    """Return only the structural fragments exercised by the Xinu parser."""
    isbn_html = f'<span itemprop="isbn">{isbn}</span>' if isbn is not None else ""
    return f"""
    <h2>Table of Contents For Xinu {edition}nd Edition</h2>
    {isbn_html}
    <p>Operating System Design: The Xinu Approach; Galileo (Intel)</p>
    <h3>Preface xix</h3>
    <h3>Chapter 1 Introduction And Overview 1</h3>
    <table>
      <tr><td>1.1</td><td>Operating Systems 1</td></tr>
      <tr><td></td><td>Exercises 10</td></tr>
    </table>
    <h3>Appendix 1 Porting An Operating System 11</h3>
    <table><tr><td>A1.1</td><td>Introduction 11</td></tr></table>
    <h3>Index 12</h3>
    """


def compact_source(monkeypatch):
    source = replace(
        public_book_source("purdue-xinu-os-design2"),
        expected_toc_count=7,
        expected_root_titles=(
            "Preface",
            "Introduction And Overview",
            "Porting An Operating System",
            "Index",
        ),
        expected_chapter_labels=("1", "A1"),
        expected_child_counts=(0, 2, 1, 0),
        expected_descendant_counts=(0, 2, 1, 0),
        expected_identity_markers=(
            "Table of Contents For Xinu 2nd Edition",
            "Operating System Design: The Xinu Approach",
            "Galileo (Intel)",
        ),
    )
    monkeypatch.setattr("data_pipeline.normalizers.public_book_source", lambda _slug: source)
    return source


def normalize_toc(source, html: str):
    return normalize_public_book_page_response(
        {"source_slug": source.slug, "url": source.url, "html": html},
        topic=source.topic,
        retrieved_at=RETRIEVED_AT,
    )


def test_xinu_toc_preserves_reviewed_hierarchy_without_inventing_prose(monkeypatch) -> None:
    source = compact_source(monkeypatch)

    dataset = normalize_toc(source, compact_xinu_toc())

    assert len(dataset.toc) == 7
    assert dataset.documents == []
    assert [entry.level for entry in dataset.toc] == [1, 1, 2, 2, 1, 2, 1]
    assert dataset.toc[2].parent_entry_id == dataset.toc[1].toc_entry_id
    assert dataset.sources[0].source_type == "author_page"
    assert dataset.sources[0].evidence is not None
    assert dataset.sources[0].evidence.source_isbns == []
    assert dataset.sources[0].evidence.same_edition is True


@pytest.mark.parametrize(
    ("html", "message"),
    [
        (compact_xinu_toc(edition=3), "reviewed Xinu edition"),
        (compact_xinu_toc(isbn="9780000000002"), "different ISBN"),
        (
            compact_xinu_toc().replace("Operating System Design: The Xinu Approach", "Other Book"),
            "edition markers",
        ),
        (compact_xinu_toc().replace("<h3>Index 12</h3>", ""), "entry count"),
        (
            compact_xinu_toc().replace(
                "<tr><td>1.1</td><td>Operating Systems 1</td></tr>",
                "<tr><td>1.1</td></tr>",
            ),
            "malformed",
        ),
    ],
)
def test_xinu_toc_rejects_identity_and_structure_changes(
    monkeypatch, html: str, message: str
) -> None:
    source = compact_source(monkeypatch)

    with pytest.raises(InvalidProviderResponse, match=message):
        normalize_toc(source, html)


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (
            {"status_code": 302, "headers": {"location": "https://example.test/login"}},
            "unapproved redirect",
        ),
        (
            {"status_code": 200, "headers": {"content-type": "application/pdf"}, "text": "x"},
            "content type",
        ),
        (
            {"status_code": 200, "headers": {"content-type": "text/html"}, "text": ""},
            "empty HTML",
        ),
    ],
)
def test_xinu_toc_collector_rejects_unsupported_http_responses(
    response: dict, message: str
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(request=request, **response)

    with (
        httpx.Client(transport=httpx.MockTransport(handler)) as client,
        pytest.raises(InvalidProviderResponse, match=message),
    ):
        PublicBookPageCollector(client=client).fetch("purdue-xinu-os-design2")


def publisher_payload(home_html: str) -> dict[str, str]:
    source = publisher_document_source("purdue-xinu-os-design2-preface")
    return {
        "source_slug": source.slug,
        "home_url": source.home_url,
        "home_html": home_html,
        "referrer_url": source.referrer_url,
        "referrer_html": home_html,
        "document_url": source.document_url,
        "document_media_type": "application/pdf",
        "document_base64": base64.b64encode(b"%PDF-1.3 compact test").decode("ascii"),
    }


def xinu_home() -> str:
    return """
    <h3>Textbook</h3>
    <p>D. Comer, Operating System Design - The Xinu Approach.</p>
    <a href="preface.pdf">Preface</a>
    <p>Comer publishes a second edition of the Xinu book.</p>
    <p>Versions For The Second Edition Of The Text
       (the second edition was published in 2015).</p>
    """


def test_xinu_preface_requires_reviewed_identity_link_pages_and_text(monkeypatch) -> None:
    extracted = (
        "Building a computer operating system is like weaving a fine tapestry. "
        "Operating System Design uses a Galileo board and a BeagleBone Black. Douglas Comer"
    )
    monkeypatch.setattr("data_pipeline.normalizers._extract_pdf_text", lambda _pdf: extracted)
    monkeypatch.setattr("data_pipeline.normalizers._pdf_page_count", lambda _pdf: 4)

    dataset = normalize_publisher_document_response(
        publisher_payload(xinu_home()),
        topic="operating-systems",
        retrieved_at=RETRIEVED_AT,
    )

    assert len(dataset.documents) == 1
    assert dataset.documents[0].document_type == "preface"
    assert dataset.sources[0].source_type == "author_page"


@pytest.mark.parametrize(
    ("home", "pages", "text", "message"),
    [
        (xinu_home().replace("published in 2015", "published later"), 4, "", "Xinu edition"),
        (xinu_home().replace('href="preface.pdf"', 'href="other.pdf"'), 4, "", "not linked"),
        (xinu_home(), 3, "", "page count"),
        (xinu_home(), 4, "unrelated text", "reviewed document"),
    ],
)
def test_xinu_preface_rejects_changed_evidence(
    monkeypatch, home: str, pages: int, text: str, message: str
) -> None:
    monkeypatch.setattr("data_pipeline.normalizers._pdf_page_count", lambda _pdf: pages)
    monkeypatch.setattr("data_pipeline.normalizers._extract_pdf_text", lambda _pdf: text)

    with pytest.raises(InvalidProviderResponse, match=message):
        normalize_publisher_document_response(
            publisher_payload(home),
            topic="operating-systems",
            retrieved_at=RETRIEVED_AT,
        )
