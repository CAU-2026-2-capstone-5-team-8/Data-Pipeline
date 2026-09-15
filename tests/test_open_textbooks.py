import base64
import json
from dataclasses import replace
from datetime import UTC, datetime

import httpx
import pytest
from typer.testing import CliRunner

from data_pipeline.cli import app
from data_pipeline.collectors.base import InvalidProviderResponse
from data_pipeline.collectors.open_textbooks import OpenTextbookCollector
from data_pipeline.datasets import without_books
from data_pipeline.identifiers import sha256_bytes, sha256_text, stable_id
from data_pipeline.models import Book, CanonicalDataset, Document, Source, TocEntry
from data_pipeline.normalizers import _same_web_resource, normalize_open_textbook_response
from data_pipeline.open_textbook_sources import open_textbook_source
from data_pipeline.storage import RawArtifact, read_dataset, write_dataset, write_raw_response
from data_pipeline.validation import validate_dataset

RETRIEVED_AT = datetime(2026, 9, 14, 12, tzinfo=UTC)


class _FakePage:
    def __init__(self, text: str = "") -> None:
        self.text = text

    def extract_text(self) -> str:
        return self.text


class _FakeDestination:
    def __init__(self, title: str, page_index: int) -> None:
        self.title = title
        self.page_index = page_index


class _FakeHefferonReader:
    def __init__(self, _stream, page_count: int = 525, deep_outline: bool = False) -> None:
        self.pages = [_FakePage() for _ in range(page_count)]
        if page_count >= 93:
            self.pages[0] = _FakePage("LINEAR ALGEBRA Jim Hefferon Fourth edition")
            self.pages[2] = _FakePage(
                "Preface standard US undergraduate first course Jim Hefferon 2020-Apr-26"
            )
            self.pages[10] = _FakePage(
                "Chapter One Linear Systems Gauss's Method Analyzing Networks"
            )
        self.metadata = {"/Title": "Linear Algebra", "/Author": "Jim Hefferon"}
        root_titles = [
            "Linear Systems",
            "Vector Spaces",
            "Maps Between Spaces",
            "Determinants",
            "Similarity",
            "Appendix",
        ]
        root_pages = [10, 92, 182, 334, 406, 496]
        self.outline = []
        level_two_counts = (8, 8, 9, 7, 8, 6)
        for root_index, (title, page_index) in enumerate(zip(root_titles, root_pages, strict=True)):
            self.outline.append(_FakeDestination(title, page_index))
            children = [
                _FakeDestination(f"{title} child {index + 1}", page_index)
                for index in range(level_two_counts[root_index])
            ]
            if root_index == 0:
                level_three_count = 43 if deep_outline else 44
                nested = [
                    _FakeDestination(f"Nested subsection {index + 1}", page_index)
                    for index in range(level_three_count)
                ]
                if deep_outline:
                    nested.insert(1, [_FakeDestination("Unexpected deep section", page_index)])
                children.insert(1, nested)
            self.outline.append(children)

    @staticmethod
    def get_destination_page_number(destination: _FakeDestination) -> int:
        return destination.page_index


class _FakeHailperinReader:
    def __init__(
        self,
        _stream,
        page_count: int = 559,
        incomplete_outline: bool = False,
    ) -> None:
        self.pages = [_FakePage() for _ in range(page_count)]
        if page_count >= 41:
            self.pages[0] = _FakePage(
                "Operating Systems and Middleware: Supporting Controlled Interaction "
                "Max Hailperin Gustavus Adolphus College Revised Edition 1.2 July 11, 2015"
            )
            self.pages[1] = _FakePage(
                "Creative Commons Attribution-ShareAlike 3.0 Unported License "
                "http://creativecommons.org/licenses/by-sa/3.0/"
            )
            self.pages[10] = _FakePage(
                "Suppose you sit down at your computer Audience Features of the Text "
                "Acknowledgments"
            )
            self.pages[20] = _FakePage(
                "Chapter 1 Introduction What Is an Operating System? What Is Middleware? Security"
            )
        self.metadata = {
            "/Title": "Operating Systems and Middleware: Supporting Controlled Interaction",
            "/Author": "Max Hailperin",
        }
        root_titles = (
            "Preface",
            "Introduction",
            "Threads",
            "Scheduling",
            "Synchronization and Deadlocks",
            "Atomic Transactions",
            "Virtual Memory",
            "Processes and Protection",
            "Files and Other Persistent Storage",
            "Networking",
            "Messaging, RPC, and Web Services",
            "Security",
            "Stacks",
            "Bibliography",
            "Index",
        )
        root_pages = (10, 20, 40, 64, 112, 180, 228, 292, 352, 414, 466, 486, 524, 530, 530)
        self.outline = []
        for root_index, (title, page_index) in enumerate(zip(root_titles, root_pages, strict=True)):
            self.outline.append(_FakeDestination(title, page_index))
            child_count = 6 if root_index < 5 else 5
            children = [
                _FakeDestination(f"{title} section {index + 1}", page_index)
                for index in range(child_count)
            ]
            if root_index == 0:
                level_three_count = 83 if incomplete_outline else 84
                children.insert(
                    1,
                    [
                        _FakeDestination(f"Preface detail {index + 1}", page_index)
                        for index in range(level_three_count)
                    ],
                )
            self.outline.append(children)

    @staticmethod
    def get_destination_page_number(destination: _FakeDestination) -> int:
        return destination.page_index


def _home_html() -> str:
    source = open_textbook_source("ostep-1.10")
    heading_cells = "".join(
        f'<td bgcolor="yellow"><b>{heading}</b></td>'
        for heading in ("Intro", "Virtualization", "Concurrency", "Persistence", "Security")
    )
    chapter_cells = "".join(
        f'<td bgcolor="yellow"><small>{number}</small> '
        f'<a href="chapter-{number}.pdf">Chapter {number}</a></td>'
        for number in range(1, 58)
    )
    document_links = "".join(
        f'<a href="{document.url.rsplit("/", 1)[-1]}">Evidence</a>' for document in source.documents
    )
    return (
        "<html><body>"
        f"<h2>{source.title}</h2>"
        f"<h3>{source.authors[0]} and {source.authors[1]}</h3>"
        f"<p>Welcome to <b>{source.title}</b> (now <b>version {source.version}</b>), "
        "a free online operating systems book! The book is centered around virtualization, "
        "concurrency, and persistence.</p>"
        f"<p>{source.publisher} November, {source.published_year} "
        f"(Version {source.version}) {source.isbn_10}</p>"
        f"{document_links}<table>{heading_cells}{chapter_cells}</table>"
        "</body></html>"
    )


def _payload() -> dict:
    source = open_textbook_source("ostep-1.10")
    return {
        "source_slug": source.slug,
        "home_url": source.home_url,
        "home_html": _home_html(),
        "documents": [
            {
                "url": document.url,
                "media_type": "application/pdf",
                "content_base64": base64.b64encode(
                    f"%PDF-{document.document_type}".encode()
                ).decode(),
            }
            for document in source.documents
        ],
    }


def _extracted_text(pdf: bytes) -> str:
    document_type = pdf.decode().removeprefix("%PDF-")
    source = open_textbook_source("ostep-1.10")
    document = next(item for item in source.documents if item.document_type == document_type)
    return " | ".join(document.expected_text_markers)


def _hefferon_payload() -> dict:
    source = open_textbook_source("hefferon-linear-algebra-4")
    return {
        "source_slug": source.slug,
        "home_url": source.home_url,
        "home_html": (
            "<html><body><p>Linear Algebra by Jim Hefferon is a text for a first "
            "undergraduate course. It is Free.</p><a href='../source.html'>License</a>"
            "</body></html>"
        ),
        "license_url": source.license_url,
        "license_html": (
            "<html><body>Linear Algebra GNU Free Documentation License or Creative Commons "
            "Attribution-ShareAlike 3.0 United States License</body></html>"
        ),
        "documents": [
            {
                "url": source.documents[0].url,
                "media_type": "application/pdf",
                "content_base64": base64.b64encode(b"%PDF-hefferon").decode(),
            }
        ],
    }


def _hailperin_payload() -> dict:
    source = open_textbook_source("hailperin-os-middleware-1.2")
    metadata = {
        "@context": "https://schema.org",
        "@type": "Book",
        "@id": "161",
        "name": source.title,
        "description": "Public operating systems and middleware textbook description.",
        "inLanguage": "English",
        "license": source.home_license,
        "copyrightYear": source.published_year,
        "author": [{"@type": "Person", "name": source.authors[0]}],
        "publisher": [{"@type": "Organization", "name": source.publisher}],
        "isAccessibleForFree": True,
    }
    home_html = (
        '<html><body><script type="application/ld+json">'
        f"{json.dumps(metadata)}</script>"
        f'<a href="{source.document_reference_url}">PDF</a>'
        "</body></html>"
    )
    document = source.documents[0]
    return {
        "source_slug": source.slug,
        "home_url": source.home_url,
        "home_html": home_html,
        "documents": [
            {
                "url": document.url,
                "resolved_url": (
                    "https://dn721903.ca.archive.org/0/items/osm-rev1.2/osm-rev1.2.pdf"
                ),
                "media_type": document.media_type,
                "content_base64": base64.b64encode(b"%PDF-hailperin").decode(),
            }
        ],
    }


def _ula_home_html() -> str:
    source = open_textbook_source("understanding-linear-algebra-2022")
    return (
        "<html><body>"
        "<div id='about'><p><em>Understanding Linear Algebra</em> is a freely available "
        "linear algebra textbook suitable for use in a first undergraduate linear algebra "
        "course.</p></div>"
        "<div id='contact'>David Austin</div>"
        "<div id='license'>This work is licensed under a Creative Commons Attribution 4.0 "
        "International License. © David Austin 2017 - 2025 "
        f"<a href='{source.license_reference_url}'>License</a></div>"
        "<a href='https://scholarworks.gvsu.edu/books/26/'>Repository metadata</a>"
        "<a href='ula.html'>Read online</a>"
        "</body></html>"
    )


def _ula_book_html(*, omit_last_entry: bool = False) -> str:
    source = open_textbook_source("understanding-linear-algebra-2022")
    root_titles = (
        "Systems of equations",
        "Vectors, matrices, and linear combinations",
        "Invertibility, bases, and coordinate systems",
        "Eigenvalues and eigenvectors",
        "Linear algebra and computing",
        "Orthogonality and Least Squares",
        "Singular value decompositions",
    )
    level_two_counts = (6, 6, 6, 5, 5, 5, 5)
    level_two_index = 0
    chapters = []
    for chapter_index, (root_title, level_two_count) in enumerate(
        zip(root_titles, level_two_counts, strict=True), start=1
    ):
        sections = []
        for section_index in range(1, level_two_count + 1):
            child_count = 5 if level_two_index < 25 else 4
            subsections = []
            for child_index in range(1, child_count + 1):
                if omit_last_entry and level_two_index == 37 and child_index == child_count:
                    continue
                subsections.append(
                    "<li class='toc-item toc-subsection'><div class='toc-title-box'>"
                    f"<a href='chapter-{chapter_index}.html#section-{section_index}-{child_index}'>"
                    f"<span class='codenumber'>{chapter_index}.{section_index}.{child_index}</span>"
                    "<span class='title'>"
                    f"Topic {chapter_index}.{section_index}.{child_index}"
                    "</span>"
                    "</a></div></li>"
                )
            sections.append(
                "<li class='toc-item toc-section'><div class='toc-title-box'>"
                f"<a href='section-{chapter_index}-{section_index}.html'>"
                f"<span class='codenumber'>{chapter_index}.{section_index}</span>"
                f"<span class='title'>Section {chapter_index}.{section_index}</span>"
                "</a></div><ul>" + "".join(subsections) + "</ul></li>"
            )
            level_two_index += 1
        chapters.append(
            "<li class='toc-item toc-chapter'><div class='toc-title-box'>"
            f"<a href='chapter-{chapter_index}.html'>"
            f"<span class='codenumber'>{chapter_index}</span>"
            f"<span class='title'>{root_title}</span>"
            "</a></div><ul>" + "".join(sections) + "</ul></li>"
        )
    evidence_links = "".join(
        f"<a href='{document.url.rsplit('/', 1)[-1]}'>Evidence</a>"
        for document in source.documents
        if document.document_type not in {"metadata", "toc"}
    )
    return (
        "<html><body><div>Understanding Linear Algebra David Austin</div>"
        f"{evidence_links}<nav id='ptx-toc'><ul>"
        "<li class='toc-item toc-frontmatter'>Front matter</li>"
        + "".join(chapters)
        + "</ul></nav><main><div id='ptx-content'>Book landing page</div></main>"
        "</body></html>"
    )


def _ula_document_html(document_type: str, markers: tuple[str, ...]) -> str:
    metadata = (
        '<meta name="bepress_citation_date" content="2022">'
        '<meta name="bepress_citation_title" content="Understanding Linear Algebra">'
        '<meta name="bepress_citation_author" content="Austin, David">'
        if document_type == "metadata"
        else ""
    )
    return (
        f"<html><head>{metadata}</head><body><nav>Repeated navigation</nav><main>"
        f"<div id='ptx-content'><section class='{document_type}'>"
        f"<h1>{document_type}</h1><p>{' '.join(markers)}</p>"
        "<p>Reviewed public textbook evidence.</p></section></div>"
        "</main></body></html>"
    )


def _ula_payload(*, omit_last_toc_entry: bool = False) -> dict:
    source = open_textbook_source("understanding-linear-algebra-2022")
    documents = []
    for document in source.documents:
        html = (
            _ula_book_html(omit_last_entry=omit_last_toc_entry)
            if document.document_type == "toc"
            else _ula_document_html(document.document_type, document.expected_text_markers)
        )
        documents.append(
            {
                "url": document.url,
                "media_type": document.media_type,
                "content_base64": base64.b64encode(html.encode()).decode(),
            }
        )
    return {
        "source_slug": source.slug,
        "home_url": source.home_url,
        "home_html": _ula_home_html(),
        "documents": documents,
    }


def _think_os_home_html() -> str:
    source = open_textbook_source("think-os-0.7.4")
    description = "".join(
        f"<p>Description paragraph {index} for operating systems programmers.</p>"
        for index in range(1, 9)
    )
    return (
        "<html><head><title>Think OS - Green Tea Press</title></head><body>"
        "<article><h1>Think OS</h1><div class='entry-content'>"
        "<h3>A Brief Introduction to Operating Systems</h3><p>by Allen B. Downey</p>"
        f"<p><a href='http://greenteapress.com/thinkos/html/index.html'>Read HTML</a></p>"
        f"<h3>Description</h3>{description}"
        f"<p>Think OS is a Free Book under <a href='{source.home_license_reference_url}'>"
        f"{source.home_license}</a>.</p></div></article></body></html>"
    )


def _think_os_index_html(*, omit_last_entry: bool = False) -> str:
    source = open_textbook_source("think-os-0.7.4")
    root_titles = (
        "Compilation",
        "Processes",
        "Virtual memory",
        "Files and file systems",
        "More bits and bytes",
        "Memory management",
        "Caching",
        "Multitasking",
        "Threads",
        "Condition variables",
        "Semaphores in C",
    )
    child_counts = (7, 3, 6, 4, 5, 3, 8, 5, 5, 5, 3)
    chapters = []
    for chapter_index, (title, child_count) in enumerate(
        zip(root_titles, child_counts, strict=True), start=1
    ):
        children = []
        for child_index in range(1, child_count + 1):
            if omit_last_entry and chapter_index == 11 and child_index == child_count:
                continue
            child_title = (
                "Compiled and interpreted languages"
                if (chapter_index, child_index) == (1, 1)
                else "Understanding errors"
                if (chapter_index, child_index) == (1, 7)
                else f"Section {chapter_index}.{child_index}"
            )
            children.append(
                f"<li><a href='thinkos{chapter_index + 2:03}.html#section-{child_index}'>"
                f"{child_title}</a></li>"
            )
        chapters.append(
            f"<li><a href='thinkos{chapter_index + 2:03}.html'>{title}</a>"
            f"<ul>{''.join(children)}</ul></li>"
        )
    return (
        "<html><body><div id='content'>"
        f"<p>{source.title}</p><p>{source.authors[0]}</p>"
        f"<p>Version {source.version}</p><p>Copyright {source.published_year}</p>"
        f"<p>{source.license} <a href='{source.license_reference_url}'>License</a></p>"
        "<ul><li><a href='thinkos001.html'>Preface</a><ul>"
        "<li><a href='thinkos001.html#note'>A note on this draft</a></li>"
        "<li><a href='thinkos001.html#code'>Using the code</a></li>"
        "<li><a href='thinkos001.html#contributors'>Contributor List</a></li>"
        "</ul></li><li><a href='thinkos002.html'>Contents</a></li>"
        f"{''.join(chapters)}</ul></div></body></html>"
    )


def _think_os_payload(*, omit_last_toc_entry: bool = False) -> dict:
    source = open_textbook_source("think-os-0.7.4")
    documents = []
    for document in source.documents:
        if document.document_type == "toc":
            html = _think_os_index_html(omit_last_entry=omit_last_toc_entry)
        else:
            html = (
                "<html><body><div id='content'><div class='notice'>PDF navigation</div>"
                f"<h1>{document.document_type}</h1>"
                f"<p>{' '.join(document.expected_text_markers)}</p>"
                "<p>Reviewed public operating systems evidence.</p>"
                "</div><div id='sidebar'>Unrelated books</div></body></html>"
            )
        documents.append(
            {
                "url": document.url,
                "media_type": document.media_type,
                "content_base64": base64.b64encode(html.encode()).decode(),
            }
        )
    return {
        "source_slug": source.slug,
        "home_url": source.home_url,
        "home_html": _think_os_home_html(),
        "documents": documents,
    }


def _nicholson_tags() -> str:
    return (
        '<div id="pageTagsHolder">license:ccbyncsa licenseversion:40 '
        "authorname:wknicholson "
        "source@https://lyryx.com/linear-algebra-applications</div>"
    )


def _nicholson_home_html() -> str:
    source = open_textbook_source("nicholson-linear-algebra-2023")
    page_links = "".join(
        f'<a href="{document.url}">Reviewed page</a>'
        for document in source.documents
        if document.document_type in {"navigation", "toc"}
    )
    return (
        "<html><body>"
        f'<div id="titleHolder">{source.title} (Nicholson)</div>'
        f"{_nicholson_tags()}"
        f'<a href="{source.license_reference_url}">CC BY-NC-SA 4.0</a>'
        f"{page_links}</body></html>"
    )


def _nicholson_toc_html(
    chapter_index: int,
    *,
    omit_last_entry: bool = False,
) -> str:
    source = open_textbook_source("nicholson-linear-algebra-2023")
    roots = (
        "1: Systems of Linear Equations",
        "2: Matrix Algebra",
        "3: Determinants and Diagonalization",
        "4: Vector Geometry",
        "5: Vector Space Rⁿ",
        "6: Vector Spaces",
        "7: Linear Transformations",
        "8: Orthogonality",
        "9: Change of Basis",
        "10: Inner Product Spaces",
        "11: Canonical Forms",
        "12: Appendices",
    )
    section_counts = (8, 11, 10, 7, 9, 8, 6, 12, 4, 6, 3, 4)
    child_counts = (6, 9, 8, 5, 7, 6, 4, 9, 3, 5, 2, 3)
    document = [item for item in source.documents if item.document_type == "toc"][chapter_index]
    sections = []
    for section_index in range(section_counts[chapter_index]):
        title = f"{chapter_index + 1}.{section_index}: Section {section_index}"
        if section_index == 0:
            title = document.expected_text_markers[1]
        if section_index == section_counts[chapter_index] - 1:
            title = document.expected_text_markers[2]
        children = ""
        if section_index < child_counts[chapter_index] and not (
            omit_last_entry and chapter_index == 11 and section_index == 2
        ):
            children = (
                "<dd class='mt-listing-detailed-subpages'><ul>"
                "<li class='mt-list-topics-childs'>"
                f"<a>{chapter_index + 1}.{section_index}E: Exercises</a>"
                "</li></ul></dd>"
            )
        sections.append(
            "<li class='mt-list-topics'><dl>"
            f"<dt class='mt-listing-detailed-title'><a>{title}</a></dt>"
            f"{children}</dl></li>"
        )
    preview = next(item for item in source.documents if item.document_type == "preview")
    preview_link = f'<a href="{preview.url}">Preview</a>' if chapter_index == 0 else ""
    return (
        "<html><body>"
        f'<div id="titleHolder">{roots[chapter_index]}</div>'
        f"{_nicholson_tags()}{preview_link}"
        '<section class="mt-content-container"><div class="mt-guide-content"><ul>'
        f"{''.join(sections)}</ul></div></section>"
        f'<a href="{source.license_reference_url}">License</a>'
        "</body></html>"
    )


def _nicholson_payload(*, omit_last_toc_entry: bool = False) -> dict:
    source = open_textbook_source("nicholson-linear-algebra-2023")
    metadata = {
        "@context": "https://schema.org",
        "@type": "Book",
        "@id": "533",
        "name": source.title,
        "bookEdition": source.version,
        "description": "A reviewed public description of linear algebra and its applications.",
        "inLanguage": "English",
        "license": "Attribution-NonCommercial-ShareAlike",
        "copyrightYear": source.published_year,
        "author": [{"@type": "Person", "name": source.authors[0]}],
        "publisher": [{"@type": "Organization", "name": source.publisher}],
        "isAccessibleForFree": True,
    }
    documents = []
    toc_index = 0
    for document in source.documents:
        if document.document_type == "metadata":
            html = (
                '<html><body><script type="application/ld+json">'
                f"{json.dumps(metadata)}</script></body></html>"
            )
        elif document.document_type == "navigation":
            preface = next(item for item in source.documents if item.document_type == "preface")
            html = (
                "<html><body><div id='titleHolder'>Front Matter</div>"
                f"{_nicholson_tags()}<p>TitlePage</p>"
                f"<a href='{preface.url}'>Preface</a></body></html>"
            )
        elif document.document_type == "toc":
            html = _nicholson_toc_html(
                toc_index,
                omit_last_entry=omit_last_toc_entry,
            )
            toc_index += 1
        else:
            page_title = (
                "Preface"
                if document.document_type == "preface"
                else "1.1: Solutions and Elementary Operations"
            )
            html = (
                f"<html><body><div id='titleHolder'>{page_title}</div>{_nicholson_tags()}"
                '<section class="mt-content-container">'
                f"<p>{' '.join(document.expected_text_markers)}</p>"
                "<p>Reviewed public textbook evidence.</p>"
                "<footer>Platform navigation and attribution controls.</footer>"
                "</section></body></html>"
            )
        documents.append(
            {
                "url": document.url,
                "media_type": document.media_type,
                "content_base64": base64.b64encode(html.encode()).decode(),
            }
        )
    return {
        "source_slug": source.slug,
        "home_url": source.home_url,
        "home_html": _nicholson_home_html(),
        "documents": documents,
    }


def test_open_textbook_collector_fetches_only_allowlisted_resources() -> None:
    source = open_textbook_source("ostep-1.10")
    requested_urls = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        if str(request.url) == source.home_url:
            return httpx.Response(
                200,
                text=_home_html(),
                headers={"content-type": "text/html; charset=utf-8"},
                request=request,
            )
        return httpx.Response(
            200,
            content=b"%PDF-synthetic",
            headers={"content-type": "application/pdf"},
            request=request,
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        payload = OpenTextbookCollector(client=client).fetch(source.slug)

    assert requested_urls == [source.home_url, *(document.url for document in source.documents)]
    assert payload["source_slug"] == source.slug
    assert len(payload["documents"]) == 3


def test_open_textbook_collector_rejects_arbitrary_source() -> None:
    with httpx.Client(transport=httpx.MockTransport(lambda _request: None)) as client:
        collector = OpenTextbookCollector(client=client)
        with pytest.raises(ValueError, match="source must be one of"):
            collector.fetch("arbitrary-url")


def test_hefferon_collector_preserves_home_license_and_pdf() -> None:
    source = open_textbook_source("hefferon-linear-algebra-4")
    requested_urls = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        if str(request.url) == source.documents[0].url:
            return httpx.Response(
                200,
                content=b"%PDF-hefferon",
                headers={"content-type": "application/pdf"},
                request=request,
            )
        return httpx.Response(
            200,
            text="<html><body>Author evidence</body></html>",
            headers={"content-type": "text/html; charset=utf-8"},
            request=request,
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        payload = OpenTextbookCollector(client=client).fetch(source.slug)

    assert requested_urls == [source.home_url, source.license_url, source.documents[0].url]
    assert payload["license_url"] == source.license_url
    assert payload["license_html"].startswith("<html>")
    assert len(payload["documents"]) == 1


def test_hailperin_collector_preserves_approved_archive_redirect() -> None:
    source = open_textbook_source("hailperin-os-middleware-1.2")
    document = source.documents[0]
    resolved_url = "https://dn721903.ca.archive.org/0/items/osm-rev1.2/osm-rev1.2.pdf"
    requested_urls = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        if str(request.url) == source.home_url:
            return httpx.Response(
                200,
                text=_hailperin_payload()["home_html"],
                headers={"content-type": "text/html; charset=utf-8"},
                request=request,
            )
        if str(request.url) == document.url:
            return httpx.Response(
                302,
                headers={"location": resolved_url},
                request=request,
            )
        return httpx.Response(
            200,
            content=b"%PDF-hailperin",
            headers={"content-type": "application/pdf"},
            request=request,
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        payload = OpenTextbookCollector(client=client).fetch(source.slug)

    assert requested_urls == [source.home_url, document.url, resolved_url]
    assert payload["documents"][0]["url"] == document.url
    assert payload["documents"][0]["resolved_url"] == resolved_url


def test_hailperin_collector_rejects_unapproved_archive_redirect() -> None:
    source = open_textbook_source("hailperin-os-middleware-1.2")
    document = source.documents[0]
    unapproved_url = "https://downloads.example.test/osm-rev1.2.pdf"
    requested_urls = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        if str(request.url) == source.home_url:
            return httpx.Response(
                200,
                text=_hailperin_payload()["home_html"],
                headers={"content-type": "text/html; charset=utf-8"},
                request=request,
            )
        if str(request.url) == document.url:
            return httpx.Response(
                302,
                headers={"location": unapproved_url},
                request=request,
            )
        return httpx.Response(
            200,
            content=b"%PDF-hailperin",
            headers={"content-type": "application/pdf"},
            request=request,
        )

    with (
        httpx.Client(transport=httpx.MockTransport(handler)) as client,
        pytest.raises(InvalidProviderResponse, match="unapproved host"),
    ):
        OpenTextbookCollector(client=client).fetch(source.slug)

    assert requested_urls == [source.home_url, document.url]


def test_pretext_collector_preserves_only_allowlisted_html_pages() -> None:
    source = open_textbook_source("understanding-linear-algebra-2022")
    requested_urls = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        return httpx.Response(
            200,
            text=_ula_home_html(),
            headers={"content-type": "text/html; charset=utf-8"},
            request=request,
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        payload = OpenTextbookCollector(client=client).fetch(source.slug)

    assert requested_urls == [source.home_url, *(document.url for document in source.documents)]
    assert payload["source_slug"] == source.slug
    assert {document["media_type"] for document in payload["documents"]} == {"text/html"}
    assert len(payload["documents"]) == 8


def test_open_textbook_normalizes_book_documents_toc_and_provenance(monkeypatch) -> None:
    source = open_textbook_source("ostep-1.10")
    monkeypatch.setattr("data_pipeline.normalizers._extract_pdf_text", _extracted_text)

    dataset = normalize_open_textbook_response(
        _payload(), topic=source.topic, retrieved_at=RETRIEVED_AT
    )

    assert len(dataset.books) == 1
    assert dataset.books[0].book_id == source.book_id
    assert dataset.books[0].authors == list(source.authors)
    assert [document.document_type for document in dataset.documents] == [
        "description",
        "preface",
        "introduction",
        "sample_chapter",
    ]
    assert len(dataset.sources) == 4
    assert all(item.source_type == "open_textbook" for item in dataset.sources)
    assert dataset.sources[0].content_hash == sha256_text(_home_html())
    assert dataset.sources[1].content_hash == sha256_bytes(b"%PDF-preface")
    assert len(dataset.toc) == 62
    assert [entry.title for entry in dataset.toc if entry.level == 1] == [
        "Intro",
        "Virtualization",
        "Concurrency",
        "Persistence",
        "Security",
    ]
    chapter_25 = next(entry for entry in dataset.toc if entry.label == "25")
    concurrency = next(entry for entry in dataset.toc if entry.title == "Concurrency")
    assert chapter_25.parent_entry_id == concurrency.toc_entry_id
    assert chapter_25.order_index == 0
    assert validate_dataset(dataset) == []


def test_hefferon_normalizes_pdf_outline_and_selected_text(monkeypatch) -> None:
    source = open_textbook_source("hefferon-linear-algebra-4")
    monkeypatch.setattr("data_pipeline.normalizers.PdfReader", _FakeHefferonReader)

    dataset = normalize_open_textbook_response(
        _hefferon_payload(), topic=source.topic, retrieved_at=RETRIEVED_AT
    )

    assert dataset.books[0].book_id == source.book_id
    assert dataset.books[0].isbn_10 is None
    assert dataset.books[0].isbn_13 is None
    assert dataset.books[0].publisher is None
    assert [document.document_type for document in dataset.documents] == [
        "description",
        "preface",
        "sample_chapter",
    ]
    assert len(dataset.toc) == 96
    assert [entry.title for entry in dataset.toc if entry.level == 1] == [
        "Linear Systems",
        "Vector Spaces",
        "Maps Between Spaces",
        "Determinants",
        "Similarity",
        "Appendix",
    ]
    assert sum(entry.level == 2 for entry in dataset.toc) == 46
    assert sum(entry.level == 3 for entry in dataset.toc) == 44
    assert len(dataset.sources) == 3
    assert {item.source_type for item in dataset.sources} == {"author_page", "open_textbook"}
    assert all(item.license == source.license for item in dataset.sources)
    assert dataset.sources[-1].content_hash == sha256_bytes(b"%PDF-hefferon")
    assert validate_dataset(dataset) == []


def test_hailperin_normalizes_metadata_pdf_outline_and_selected_text(monkeypatch) -> None:
    source = open_textbook_source("hailperin-os-middleware-1.2")
    monkeypatch.setattr("data_pipeline.normalizers.PdfReader", _FakeHailperinReader)

    dataset = normalize_open_textbook_response(
        _hailperin_payload(), topic=source.topic, retrieved_at=RETRIEVED_AT
    )

    assert dataset.books[0].book_id == source.book_id
    assert dataset.books[0].isbn_10 is None
    assert dataset.books[0].isbn_13 is None
    assert dataset.books[0].authors == ["Max Hailperin"]
    assert [document.document_type for document in dataset.documents] == [
        "description",
        "preface",
        "sample_chapter",
    ]
    assert len(dataset.toc) == 179
    assert {level: sum(entry.level == level for entry in dataset.toc) for level in (1, 2, 3)} == {
        1: 15,
        2: 80,
        3: 84,
    }
    assert [entry.title for entry in dataset.toc if entry.level == 1][:3] == [
        "Preface",
        "Introduction",
        "Threads",
    ]
    assert [source_record.provider for source_record in dataset.sources] == [
        "open_textbook_library",
        "internet_archive",
    ]
    assert dataset.sources[0].license == "Attribution-ShareAlike"
    assert dataset.sources[1].license == source.license
    assert dataset.sources[1].content_hash == sha256_bytes(b"%PDF-hailperin")
    assert validate_dataset(dataset) == []


def test_hailperin_rejects_incomplete_pdf_outline(monkeypatch) -> None:
    source = open_textbook_source("hailperin-os-middleware-1.2")
    monkeypatch.setattr(
        "data_pipeline.normalizers.PdfReader",
        lambda stream: _FakeHailperinReader(stream, incomplete_outline=True),
    )

    with pytest.raises(InvalidProviderResponse, match="outline does not match review"):
        normalize_open_textbook_response(
            _hailperin_payload(), topic=source.topic, retrieved_at=RETRIEVED_AT
        )


def test_hailperin_rejects_unreviewed_resolved_pdf() -> None:
    source = open_textbook_source("hailperin-os-middleware-1.2")
    payload = _hailperin_payload()
    payload["documents"][0]["resolved_url"] = (
        "https://dn721903.ca.archive.org/0/items/other/other.pdf"
    )

    with pytest.raises(InvalidProviderResponse, match="unreviewed resource"):
        normalize_open_textbook_response(payload, topic=source.topic, retrieved_at=RETRIEVED_AT)


def test_pretext_normalizes_description_preface_previews_toc_and_provenance() -> None:
    source = open_textbook_source("understanding-linear-algebra-2022")

    dataset = normalize_open_textbook_response(
        _ula_payload(), topic=source.topic, retrieved_at=RETRIEVED_AT
    )

    assert dataset.books[0].book_id == source.book_id
    assert dataset.books[0].isbn_10 is None
    assert dataset.books[0].isbn_13 is None
    assert dataset.books[0].authors == ["David Austin"]
    assert [document.document_type for document in dataset.documents] == [
        "description",
        "preface",
        "preview",
        "preview",
        "preview",
        "preview",
        "preview",
    ]
    assert len(dataset.toc) == 222
    assert {level: sum(entry.level == level for entry in dataset.toc) for level in (1, 2, 3)} == {
        1: 7,
        2: 38,
        3: 177,
    }
    assert len(dataset.sources) == 9
    assert dataset.sources[0].source_type == "author_page"
    assert all(item.license == source.license for item in dataset.sources)
    assert validate_dataset(dataset) == []


def test_libretexts_normalizes_description_preface_preview_toc_and_provenance() -> None:
    source = open_textbook_source("nicholson-linear-algebra-2023")

    dataset = normalize_open_textbook_response(
        _nicholson_payload(), topic=source.topic, retrieved_at=RETRIEVED_AT
    )

    assert dataset.books[0].book_id == source.book_id
    assert dataset.books[0].authors == ["W. Keith Nicholson"]
    assert dataset.books[0].publisher == "Lyryx"
    assert dataset.books[0].isbn_10 is None
    assert dataset.books[0].isbn_13 is None
    assert [document.document_type for document in dataset.documents] == [
        "description",
        "preface",
        "preview",
    ]
    assert "Platform navigation" not in dataset.documents[-1].text
    assert len(dataset.toc) == 167
    assert {level: sum(entry.level == level for entry in dataset.toc) for level in (1, 2, 3)} == {
        1: 12,
        2: 88,
        3: 67,
    }
    assert len(dataset.sources) == 17
    metadata_source = next(
        item for item in dataset.sources if item.provider == "open_textbook_library"
    )
    assert metadata_source.source_id == stable_id(
        "source", "open_textbook_library", metadata_source.url, source.book_id
    )
    assert metadata_source.license == "Attribution-NonCommercial-ShareAlike"
    assert all(
        item.license == source.license
        for item in dataset.sources
        if item.provider == source.provider
    )
    assert validate_dataset(dataset) == []


def test_libretexts_rejects_incomplete_toc() -> None:
    source = open_textbook_source("nicholson-linear-algebra-2023")

    with pytest.raises(InvalidProviderResponse, match="TOC does not match review"):
        normalize_open_textbook_response(
            _nicholson_payload(omit_last_toc_entry=True),
            topic=source.topic,
            retrieved_at=RETRIEVED_AT,
        )


def test_libretexts_rejects_changed_structured_book_identity() -> None:
    source = open_textbook_source("nicholson-linear-algebra-2023")
    payload = _nicholson_payload()
    metadata_spec = next(item for item in source.documents if item.document_type == "metadata")
    raw_metadata = next(item for item in payload["documents"] if item["url"] == metadata_spec.url)
    html = base64.b64decode(raw_metadata["content_base64"]).decode()
    raw_metadata["content_base64"] = base64.b64encode(
        html.replace('"copyrightYear": 2023', '"copyrightYear": 2022').encode()
    ).decode()

    with pytest.raises(InvalidProviderResponse, match="metadata does not match review"):
        normalize_open_textbook_response(payload, topic=source.topic, retrieved_at=RETRIEVED_AT)


def test_libretexts_requires_reviewed_preface_link_chain() -> None:
    source = open_textbook_source("nicholson-linear-algebra-2023")
    payload = _nicholson_payload()
    navigation_spec = next(item for item in source.documents if item.document_type == "navigation")
    raw_navigation = next(
        item for item in payload["documents"] if item["url"] == navigation_spec.url
    )
    html = base64.b64decode(raw_navigation["content_base64"]).decode()
    raw_navigation["content_base64"] = base64.b64encode(
        html.replace("06%3A_Preface", "06%3A_Unreviewed").encode()
    ).decode()

    with pytest.raises(InvalidProviderResponse, match="preface is not linked"):
        normalize_open_textbook_response(payload, topic=source.topic, retrieved_at=RETRIEVED_AT)


def test_think_os_normalizes_description_preface_sample_toc_and_licenses() -> None:
    source = open_textbook_source("think-os-0.7.4")

    dataset = normalize_open_textbook_response(
        _think_os_payload(), topic=source.topic, retrieved_at=RETRIEVED_AT
    )

    assert dataset.books[0].book_id == source.book_id
    assert dataset.books[0].authors == ["Allen B. Downey"]
    assert dataset.books[0].publisher == "Green Tea Press"
    assert [document.document_type for document in dataset.documents] == [
        "description",
        "preface",
        "sample_chapter",
    ]
    assert len(dataset.toc) == 65
    assert {level: sum(entry.level == level for entry in dataset.toc) for level in (1, 2)} == {
        1: 11,
        2: 54,
    }
    assert [entry.title for entry in dataset.toc if entry.level == 1][0] == "Compilation"
    assert [entry.title for entry in dataset.toc if entry.level == 1][-1] == "Semaphores in C"
    assert len(dataset.sources) == 4
    assert dataset.sources[0].license == source.home_license
    assert all(item.license == source.license for item in dataset.sources[1:])
    assert "PDF navigation" not in dataset.documents[1].text
    assert "Unrelated books" not in dataset.documents[2].text
    assert validate_dataset(dataset) == []


def test_think_os_rejects_incomplete_toc() -> None:
    source = open_textbook_source("think-os-0.7.4")

    with pytest.raises(InvalidProviderResponse, match="TOC does not match review"):
        normalize_open_textbook_response(
            _think_os_payload(omit_last_toc_entry=True),
            topic=source.topic,
            retrieved_at=RETRIEVED_AT,
        )


def test_think_os_rejects_publisher_page_without_reviewed_index_link() -> None:
    source = open_textbook_source("think-os-0.7.4")
    payload = _think_os_payload()
    payload["home_html"] = payload["home_html"].replace(
        "http://greenteapress.com/thinkos/html/index.html",
        "http://example.test/thinkos/html/index.html",
    )

    with pytest.raises(InvalidProviderResponse, match="not linked"):
        normalize_open_textbook_response(payload, topic=source.topic, retrieved_at=RETRIEVED_AT)


def test_reviewed_link_comparison_rejects_malformed_ports() -> None:
    assert not _same_web_resource(
        "https://greenteapress.com:invalid/thinkos/html/index.html",
        "https://greenteapress.com/thinkos/html/index.html",
    )


def test_think_os_preserves_different_page_license_statements() -> None:
    source = open_textbook_source("think-os-0.7.4")
    payload = _think_os_payload()
    payload["home_html"] = payload["home_html"].replace(
        source.home_license_reference_url,
        "http://creativecommons.org/licenses/by-nc-sa/4.0/",
    )

    with pytest.raises(InvalidProviderResponse, match="publisher page is missing its license"):
        normalize_open_textbook_response(payload, topic=source.topic, retrieved_at=RETRIEVED_AT)


def test_pretext_rejects_incomplete_toc() -> None:
    source = open_textbook_source("understanding-linear-algebra-2022")

    with pytest.raises(InvalidProviderResponse, match="TOC does not match review"):
        normalize_open_textbook_response(
            _ula_payload(omit_last_toc_entry=True),
            topic=source.topic,
            retrieved_at=RETRIEVED_AT,
        )


def test_pretext_rejects_repository_publication_mismatch() -> None:
    source = open_textbook_source("understanding-linear-algebra-2022")
    payload = _ula_payload()
    metadata = next(item for item in payload["documents"] if item["url"] == source.documents[0].url)
    html = base64.b64decode(metadata["content_base64"]).decode()
    html = html.replace(
        'bepress_citation_date" content="2022', 'bepress_citation_date" content="2021'
    )
    metadata["content_base64"] = base64.b64encode(html.encode()).decode()

    with pytest.raises(InvalidProviderResponse, match="repository metadata"):
        normalize_open_textbook_response(payload, topic=source.topic, retrieved_at=RETRIEVED_AT)


def test_pretext_rejects_license_text_without_reviewed_link() -> None:
    source = open_textbook_source("understanding-linear-algebra-2022")
    payload = _ula_payload()
    payload["home_html"] = payload["home_html"].replace(
        source.license_reference_url, "https://example.test/licenses/by/4.0/"
    )

    with pytest.raises(InvalidProviderResponse, match="license link"):
        normalize_open_textbook_response(payload, topic=source.topic, retrieved_at=RETRIEVED_AT)


def test_pretext_rejects_evidence_page_not_linked_from_toc() -> None:
    source = open_textbook_source("understanding-linear-algebra-2022")
    payload = _ula_payload()
    toc_spec = next(item for item in source.documents if item.document_type == "toc")
    toc_document = next(item for item in payload["documents"] if item["url"] == toc_spec.url)
    html = base64.b64decode(toc_document["content_base64"]).decode()
    html = html.replace("href='sec-pivots.html'", "href='unreviewed.html'")
    toc_document["content_base64"] = base64.b64encode(html.encode()).decode()

    with pytest.raises(InvalidProviderResponse, match="not linked"):
        normalize_open_textbook_response(payload, topic=source.topic, retrieved_at=RETRIEVED_AT)


def test_hefferon_rejects_changed_pdf_page_count(monkeypatch) -> None:
    source = open_textbook_source("hefferon-linear-algebra-4")
    monkeypatch.setattr(
        "data_pipeline.normalizers.PdfReader",
        lambda stream: _FakeHefferonReader(stream, page_count=524),
    )

    with pytest.raises(InvalidProviderResponse) as exc_info:
        normalize_open_textbook_response(
            _hefferon_payload(), topic=source.topic, retrieved_at=RETRIEVED_AT
        )
    assert str(exc_info.value) == "Hefferon PDF page count does not match review"


def test_hefferon_rejects_license_filename_without_reviewed_link(monkeypatch) -> None:
    source = open_textbook_source("hefferon-linear-algebra-4")
    payload = _hefferon_payload()
    payload["home_html"] = (
        "<html><body><p>Linear Algebra by Jim Hefferon is a text for a first "
        "undergraduate course. It is Free. See source.html.</p>"
        "<a href='https://example.test/source.html'>Unrelated license</a></body></html>"
    )
    monkeypatch.setattr("data_pipeline.normalizers.PdfReader", _FakeHefferonReader)

    with pytest.raises(InvalidProviderResponse, match="not linked"):
        normalize_open_textbook_response(payload, topic=source.topic, retrieved_at=RETRIEVED_AT)


def test_hefferon_rejects_raw_pdf_above_reviewed_size(monkeypatch) -> None:
    source = open_textbook_source("hefferon-linear-algebra-4")
    payload = _hefferon_payload()
    reviewed_source = replace(source, max_resource_bytes=8)
    monkeypatch.setattr(
        "data_pipeline.normalizers.open_textbook_source", lambda _slug: reviewed_source
    )

    with pytest.raises(InvalidProviderResponse, match="size limit"):
        normalize_open_textbook_response(payload, topic=source.topic, retrieved_at=RETRIEVED_AT)


def test_hefferon_rejects_unreviewed_outline_depth(monkeypatch) -> None:
    source = open_textbook_source("hefferon-linear-algebra-4")
    monkeypatch.setattr(
        "data_pipeline.normalizers.PdfReader",
        lambda stream: _FakeHefferonReader(stream, deep_outline=True),
    )

    with pytest.raises(InvalidProviderResponse, match="outline does not match review"):
        normalize_open_textbook_response(
            _hefferon_payload(), topic=source.topic, retrieved_at=RETRIEVED_AT
        )


def test_hefferon_validates_every_configured_sample_marker(monkeypatch) -> None:
    source = open_textbook_source("hefferon-linear-algebra-4")
    document = replace(
        source.documents[0],
        sample_text_markers=(*source.documents[0].sample_text_markers, "Missing marker"),
    )
    reviewed_source = replace(source, documents=(document,))
    monkeypatch.setattr(
        "data_pipeline.normalizers.open_textbook_source", lambda _slug: reviewed_source
    )
    monkeypatch.setattr("data_pipeline.normalizers.PdfReader", _FakeHefferonReader)

    with pytest.raises(InvalidProviderResponse, match="sample chapter text"):
        normalize_open_textbook_response(
            _hefferon_payload(), topic=source.topic, retrieved_at=RETRIEVED_AT
        )


def test_hefferon_rejects_unverified_license(monkeypatch) -> None:
    source = open_textbook_source("hefferon-linear-algebra-4")
    payload = _hefferon_payload()
    payload["license_html"] = "<html><body>License unavailable</body></html>"
    monkeypatch.setattr("data_pipeline.normalizers.PdfReader", _FakeHefferonReader)

    with pytest.raises(InvalidProviderResponse, match="license page"):
        normalize_open_textbook_response(payload, topic=source.topic, retrieved_at=RETRIEVED_AT)


def test_open_textbook_requires_complete_numbered_toc(monkeypatch) -> None:
    source = open_textbook_source("ostep-1.10")
    payload = _payload()
    payload["home_html"] = payload["home_html"].replace("<small>57</small>", "")
    monkeypatch.setattr("data_pipeline.normalizers._extract_pdf_text", _extracted_text)

    with pytest.raises(InvalidProviderResponse, match="1 through 57"):
        normalize_open_textbook_response(payload, topic=source.topic, retrieved_at=RETRIEVED_AT)


def test_without_books_removes_all_book_scoped_records() -> None:
    old_book_id = "isbn13:9780306406157"
    book = Book(
        book_id=old_book_id,
        isbn_10="0306406152",
        isbn_13="9780306406157",
        title="Old Candidate",
        authors=["Fixture Author"],
        published_year=1974,
        language="en",
        topics=["computer-science", "operating-systems"],
    )
    source = Source(
        source_id="source_old",
        book_id=old_book_id,
        provider="fixture",
        source_type="metadata_api",
        url="https://example.test/old",
        retrieved_at=RETRIEVED_AT,
        content_hash="sha256:" + "a" * 64,
    )
    dataset = CanonicalDataset(
        books=[book],
        documents=[
            Document(
                document_id="doc_old",
                book_id=old_book_id,
                document_type="description",
                text="Old evidence",
                source_id=source.source_id,
                content_hash="sha256:" + "b" * 64,
            )
        ],
        toc=[
            TocEntry(
                toc_entry_id="toc_old",
                book_id=old_book_id,
                level=1,
                order_index=0,
                title="Old TOC",
                source_id=source.source_id,
            )
        ],
        sources=[source],
    )

    assert without_books(dataset, {old_book_id}) == CanonicalDataset(
        books=[], documents=[], toc=[], sources=[]
    )


def test_collect_open_textbook_replaces_existing_candidate(tmp_path, monkeypatch) -> None:
    source = open_textbook_source("ostep-1.10")
    old_book = Book(
        book_id=source.replaces_book_id,
        isbn_10="0070394555",
        isbn_13="9780070394551",
        title="Operating systems",
        authors=["Fixture Author"],
        published_year=1974,
        language="en",
        topics=["computer-science", "operating-systems"],
    )
    old_source = Source(
        source_id="source_old",
        book_id=old_book.book_id,
        provider="fixture",
        source_type="metadata_api",
        url="https://example.test/old",
        retrieved_at=RETRIEVED_AT,
        content_hash="sha256:" + "a" * 64,
    )
    write_dataset(
        CanonicalDataset(books=[old_book], documents=[], toc=[], sources=[old_source]),
        tmp_path / "processed",
    )
    monkeypatch.setattr("data_pipeline.normalizers._extract_pdf_text", _extracted_text)
    monkeypatch.setattr(
        "data_pipeline.cli._collect_open_textbook_payload",
        lambda _slug: (_payload(), OpenTextbookCollector.request_parameters(source.slug)),
    )

    result = CliRunner().invoke(
        app,
        ["collect-open-textbook", "--source", source.slug, "--data-dir", str(tmp_path)],
    )

    dataset = read_dataset(tmp_path / "processed")
    assert result.exit_code == 0
    assert "Open-textbook documents collected: 4" in result.output
    assert {book.book_id for book in dataset.books} == {source.book_id}
    assert len(dataset.documents) == 4
    assert len(dataset.toc) == 62
    assert len(dataset.sources) == 4
    assert validate_dataset(dataset) == []
    assert len(list((tmp_path / "raw" / "open_textbook").rglob("*.json"))) == 1


def test_build_reapplies_open_textbook_replacement_from_raw(tmp_path, monkeypatch) -> None:
    source = open_textbook_source("ostep-1.10")
    old_book = Book(
        book_id=source.replaces_book_id,
        isbn_10="0070394555",
        isbn_13="9780070394551",
        title="Operating systems",
        authors=["Fixture Author"],
        published_year=1974,
        language="en",
        topics=["computer-science", "operating-systems"],
    )
    old_source = Source(
        source_id="source_old",
        book_id=old_book.book_id,
        provider="fixture",
        source_type="metadata_api",
        url="https://example.test/old",
        retrieved_at=RETRIEVED_AT,
        content_hash="sha256:" + "a" * 64,
    )
    old_dataset = CanonicalDataset(books=[old_book], documents=[], toc=[], sources=[old_source])
    monkeypatch.setattr("data_pipeline.normalizers._extract_pdf_text", _extracted_text)
    new_dataset = normalize_open_textbook_response(
        _payload(), topic=source.topic, retrieved_at=RETRIEVED_AT
    )
    metadata_raw = tmp_path / "metadata.json"
    textbook_raw = tmp_path / "textbook.json"
    write_raw_response(
        RawArtifact(
            provider="fixture-metadata",
            topic=source.topic,
            requested_limit=5,
            retrieved_at=RETRIEVED_AT,
            request_parameters={"fixture": "metadata"},
            response={"fixture": "metadata"},
        ),
        metadata_raw,
    )
    write_raw_response(
        RawArtifact(
            provider="open-textbook",
            topic=source.topic,
            requested_limit=1,
            retrieved_at=RETRIEVED_AT,
            request_parameters={"source": source.slug},
            response={"fixture": "textbook"},
        ),
        textbook_raw,
    )
    monkeypatch.setattr(
        "data_pipeline.cli._expected_request_parameters",
        lambda artifact: artifact.request_parameters,
    )
    monkeypatch.setattr(
        "data_pipeline.cli._normalize",
        lambda _payload, provider, _topic, _limit, retrieved_at: (
            new_dataset if provider == "open-textbook" else old_dataset
        ),
    )

    result = CliRunner().invoke(
        app,
        [
            "build",
            "--raw",
            str(metadata_raw),
            "--raw",
            str(textbook_raw),
            "--output",
            str(tmp_path / "rebuilt"),
        ],
    )

    rebuilt = read_dataset(tmp_path / "rebuilt")
    assert result.exit_code == 0
    assert {book.book_id for book in rebuilt.books} == {source.book_id}
    assert all(record.book_id != source.replaces_book_id for record in rebuilt.sources)
