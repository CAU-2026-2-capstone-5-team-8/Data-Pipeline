import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from data_pipeline.api_toc import (
    normalize_springer_metadata_response,
    normalize_yes24_toc_response,
    parse_yes24_contents,
)
from data_pipeline.cli import app
from data_pipeline.collectors.base import InvalidProviderResponse
from data_pipeline.collectors.springer_metadata import SpringerMetadataCollector, hyphenated_isbn
from data_pipeline.collectors.yes24 import Yes24Collector
from data_pipeline.models import Book, CanonicalDataset, Source, TocEntry
from data_pipeline.storage import read_dataset, write_dataset
from data_pipeline.validation import validate_dataset

RETRIEVED_AT = datetime(2026, 9, 23, 12, 0, tzinfo=UTC)
YES24_ISBN = "9781118909584"
SPRINGER_ISBN = "9783319110806"


def _book(isbn_13: str = YES24_ISBN, topic: str = "linear-algebra") -> Book:
    return Book(
        book_id=f"isbn13:{isbn_13}",
        isbn_13=isbn_13,
        title="Example Linear Algebra",
        authors=["Example Author"],
        language="en",
        topics=["mathematics", topic],
    )


def _outline(contents: str) -> list[tuple[int, str | None, str]]:
    return [
        (item["level"], item["label"], item["title"]) for item in parse_yes24_contents(contents)
    ]


# Shapes below are trimmed from real YES24 content responses (2026-09-23).
TAB_PAGED = (
    "Preface\tXI\r\n \t\tFeatures of the text\tXIII\r\n"
    " \t \t1.\tSystems of Linear Equations\t1\r\n"
    " \t \t \t1.1\tThe Vector Space of m X n Matrices\t1\r\n"
    " \t\tThe Space Rn\t4\r\n"
    " \t \t \t \t1.1.1\tComputer Projects\t22\r\n"
    " \t \t \t1.2\tSystems\t28\r\n"
)
PERIOD_SECTIONS = (
    "1. Linear Equations and Matrices. \r\n\r\n"
    "Linear Systems. Matrices. Dot Product and Matrix Multiplication. \r\n\r\n"
    "2. Determinants. \r\n\r\n"
    "Definition and Properties. Cofactor Expansion and Applications. Cramer's Rule. \r\n"
)
HTML_PARTS = (
    " <p><b>PART ONE. OVERVIEW</b></p> <br/><br/>Chapter<br/>1. Introduction. <br/><br/>"
    "Chapter<br/>2. Operating-System Structures. <br/><br/>"
    "<b>PART TWO. PROCESS MANAGEMENT</b> <br/><br/>Chapter<br/>3. Processes <br/><br/>"
    "Chapter<br/>9. . Mass-Storage Structure. <br/>"
)
KOREAN = (
    "옮긴이의 글\r\n서문\r\n\r\n1장 클린 코드\r\n\r\n<b>1부 코드</b>\r\n\r\n"
    "2장 코드를 깨끗하게!\r\n3장 기본 원칙\r\n"
)


def _yes24_response(contents: str = TAB_PAGED, item_id: int = 15704408) -> dict:
    return {
        "success": True,
        "message": "성공",
        "errorCode": None,
        "data": {
            "meta": {"apiTitle": "상품 목차 조회"},
            "data": {"itemId": item_id, "contents": contents},
        },
    }


def _yes24_not_found() -> dict:
    return {
        "success": False,
        "message": "ISBN13에 해당하는 상품을 찾을 수 없습니다.",
        "data": None,
        "errorCode": "GOODS_002",
    }


def _springer_record(number: int | str, title: str, **overrides: str) -> dict:
    record = {
        "contentType": "Chapter",
        "doi": f"10.1007/978-3-319-11080-6_{number}",
        "title": title,
        "abstract": "Chapter abstract text that must never reach canonical records.",
        "publicationName": "Linear Algebra Done Right",
        "printIsbn": "978-3-319-11079-0",
        "electronicIsbn": "978-3-319-11080-6",
        "copyright": "©2015 Springer International Publishing",
    }
    return {**record, **overrides}


def _springer_payload(records: list[dict]) -> dict:
    return {
        "query": "isbn:978-3-319-11080-6",
        "pages": [
            {
                "request_parameters": {"q": "isbn:978-3-319-11080-6", "p": 25, "s": 1},
                "response": {"result": [{"total": str(len(records))}], "records": records},
            }
        ],
    }


# --- YES24 TOC parsing -------------------------------------------------------


def test_tab_paged_toc_keeps_dotted_depth_and_drops_page_numbers() -> None:
    assert _outline(TAB_PAGED) == [
        (1, None, "Preface"),
        (1, None, "Features of the text"),
        (1, "1", "Systems of Linear Equations"),
        (2, "1.1", "The Vector Space of m X n Matrices"),
        (3, None, "The Space Rn"),
        (3, "1.1.1", "Computer Projects"),
        (2, "1.2", "Systems"),
    ]


def test_unlabeled_period_run_becomes_children_of_the_chapter() -> None:
    assert _outline(PERIOD_SECTIONS) == [
        (1, "1", "Linear Equations and Matrices"),
        (2, None, "Linear Systems"),
        (2, None, "Matrices"),
        (2, None, "Dot Product and Matrix Multiplication"),
        (1, "2", "Determinants"),
        (2, None, "Definition and Properties"),
        (2, None, "Cofactor Expansion and Applications"),
        (2, None, "Cramer's Rule"),
    ]


def test_html_part_headings_contain_the_chapters_that_follow() -> None:
    assert _outline(HTML_PARTS) == [
        (1, None, "PART ONE. OVERVIEW"),
        (2, "1", "Introduction"),
        (2, "2", "Operating-System Structures"),
        (1, None, "PART TWO. PROCESS MANAGEMENT"),
        (2, "3", "Processes"),
        (2, "9", "Mass-Storage Structure"),
    ]


def test_single_period_delimited_paragraph_becomes_a_flat_list() -> None:
    outline = _outline("<p>Introduction and Overview. Message Passing. File Systems. Index.</p>")
    assert outline == [
        (1, None, "Introduction and Overview"),
        (1, None, "Message Passing"),
        (1, None, "File Systems"),
        (1, None, "Index"),
    ]


def test_korean_chapter_and_part_markers() -> None:
    assert _outline(KOREAN) == [
        (1, None, "옮긴이의 글"),
        (1, None, "서문"),
        (1, "1", "클린 코드"),
        (1, None, "1부 코드"),
        (2, "2", "코드를 깨끗하게!"),
        (2, "3", "기본 원칙"),
    ]


# --- YES24 normalizer --------------------------------------------------------


def test_yes24_normalizer_records_exact_edition_provenance_and_attribution() -> None:
    book = _book()
    evidence = normalize_yes24_toc_response(_yes24_response(), book=book, retrieved_at=RETRIEVED_AT)

    assert evidence is not None
    (source,) = evidence.sources
    assert source.provider == "yes24"
    assert source.url == "https://www.yes24.com/product/goods/15704408"
    assert source.external_id == "15704408"
    assert source.license is None
    assert "YES24 출처" in (source.rights_note or "")
    assert source.evidence is not None
    assert source.evidence.tier == "exact_edition_toc"
    assert source.evidence.match_basis == ["isbn_13"]
    assert evidence.documents == []
    assert [entry.title for entry in evidence.toc][:3] == [
        "Preface",
        "Features of the text",
        "Systems of Linear Equations",
    ]
    merged = CanonicalDataset(
        books=[book], documents=[], toc=evidence.toc, sources=evidence.sources
    )
    assert validate_dataset(merged) == []


def test_yes24_normalizer_is_deterministic() -> None:
    first = normalize_yes24_toc_response(_yes24_response(), book=_book(), retrieved_at=RETRIEVED_AT)
    second = normalize_yes24_toc_response(
        _yes24_response(), book=_book(), retrieved_at=RETRIEVED_AT
    )
    assert first == second


def test_yes24_not_found_and_too_short_tocs_yield_no_evidence() -> None:
    book = _book()
    assert (
        normalize_yes24_toc_response(_yes24_not_found(), book=book, retrieved_at=RETRIEVED_AT)
        is None
    )
    no_toc = {
        **_yes24_not_found(),
        "errorCode": "GOODS_001",
        "message": "상품 목차 정보가 없습니다.",
    }
    assert normalize_yes24_toc_response(no_toc, book=book, retrieved_at=RETRIEVED_AT) is None
    short = _yes24_response("Preface\r\nIndex\r\n")
    assert normalize_yes24_toc_response(short, book=book, retrieved_at=RETRIEVED_AT) is None


def test_yes24_other_failures_are_reported() -> None:
    failure = {
        "success": False,
        "message": "잘못된 파라미터",
        "data": None,
        "errorCode": "PARAM_004",
    }
    with pytest.raises(InvalidProviderResponse, match="PARAM_004"):
        normalize_yes24_toc_response(failure, book=_book(), retrieved_at=RETRIEVED_AT)


# --- Springer normalizer -----------------------------------------------------


def test_springer_chapters_are_ordered_by_doi_and_filtered_to_the_book() -> None:
    book = _book(SPRINGER_ISBN)
    records = [
        _springer_record(10, "Trace and Determinant"),
        _springer_record(2, "Finite-Dimensional Vector Spaces"),
        _springer_record(1, "Vector Spaces"),
        _springer_record("BookFrontmatter", "Front Matter"),
        _springer_record(3, "Linear Maps", contentType="Article"),
        _springer_record(
            4, "Another Book's Chapter", printIsbn="978-0-000-00000-0", electronicIsbn=""
        ),
    ]
    evidence = normalize_springer_metadata_response(
        _springer_payload(records), book=book, retrieved_at=RETRIEVED_AT
    )

    assert evidence is not None
    assert [(e.level, e.label, e.title, e.order_index) for e in evidence.toc] == [
        (1, "1", "Vector Spaces", 0),
        (1, "2", "Finite-Dimensional Vector Spaces", 1),
        (1, "10", "Trace and Determinant", 2),
    ]
    (source,) = evidence.sources
    assert source.provider == "springer_nature"
    assert source.url == "https://link.springer.com/book/10.1007/978-3-319-11080-6"
    assert source.evidence is not None
    assert source.evidence.source_isbns == ["9783319110790", "9783319110806"]
    assert "abstract text" not in json.dumps(
        [entry.model_dump() for entry in evidence.toc] + [source.model_dump(mode="json")]
    )
    merged = CanonicalDataset(
        books=[book], documents=[], toc=evidence.toc, sources=evidence.sources
    )
    assert validate_dataset(merged) == []


def test_springer_without_enough_chapters_yields_no_evidence() -> None:
    payload = _springer_payload([_springer_record(1, "Vector Spaces")])
    assert (
        normalize_springer_metadata_response(
            payload, book=_book(SPRINGER_ISBN), retrieved_at=RETRIEVED_AT
        )
        is None
    )
    empty = {"query": "isbn:978-3-319-11080-6", "pages": []}
    assert (
        normalize_springer_metadata_response(
            empty, book=_book(SPRINGER_ISBN), retrieved_at=RETRIEVED_AT
        )
        is None
    )


# --- Collectors ----------------------------------------------------------------


def test_yes24_collector_sends_key_as_header_and_returns_not_found_body() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(404, json=_yes24_not_found(), request=request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        payload = Yes24Collector("yk_live_test", client=client).fetch_toc(YES24_ISBN)

    assert payload == _yes24_not_found()
    request = captured[0]
    assert request.headers["X-Api-Key"] == "yk_live_test"
    assert dict(request.url.params) == {"searchType": "ISBN13", "query": YES24_ISBN}
    assert "yk_live_test" not in json.dumps(Yes24Collector.request_parameters(YES24_ISBN))


def test_collectors_require_an_api_key() -> None:
    with pytest.raises(ValueError, match="YES24_API_KEY"):
        Yes24Collector("")
    with pytest.raises(ValueError, match="SPRINGER_API_KEY"):
        SpringerMetadataCollector("")


def test_springer_collector_hyphenates_pages_and_keeps_key_out_of_raw() -> None:
    captured: list[httpx.Request] = []
    records = [_springer_record(n, f"Chapter {n}") for n in range(1, 31)]

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        start = int(request.url.params["s"])
        page = records[start - 1 : start - 1 + 25]
        return httpx.Response(
            200, json={"result": [{"total": "30"}], "records": page}, request=request
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        collector = SpringerMetadataCollector("secret-key", client=client)
        payload = collector.fetch_chapters(SPRINGER_ISBN)

    assert hyphenated_isbn(SPRINGER_ISBN) == "978-3-319-11080-6"
    assert [request.url.params["s"] for request in captured] == ["1", "26"]
    assert all(request.url.params["q"] == "isbn:978-3-319-11080-6" for request in captured)
    assert all(request.url.params["api_key"] == "secret-key" for request in captured)
    assert len(payload["pages"]) == 2
    assert "secret-key" not in json.dumps(payload)


def test_springer_collector_treats_404_as_no_records() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(404, json={"status": "Fail"}, request=request)
    )
    with httpx.Client(transport=transport) as client:
        payload = SpringerMetadataCollector("k", client=client).fetch_chapters(SPRINGER_ISBN)
    assert payload == {"query": "isbn:978-3-319-11080-6", "pages": []}


# --- CLI -----------------------------------------------------------------------


def _seed(processed: Path, books: list[Book], toc: list[TocEntry] | None = None) -> None:
    sources = [
        Source(
            source_id=f"source_seed_{book.isbn_13}",
            book_id=book.book_id,
            provider="test_seed",
            source_type="other",
            url="https://example.org/seed",
            retrieved_at=RETRIEVED_AT,
            content_hash="sha256:" + "0" * 64,
        )
        for book in books
    ]
    write_dataset(
        CanonicalDataset(books=books, documents=[], toc=toc or [], sources=sources), processed
    )


class _FakeYes24Collector:
    requested: list[str] = []

    def __init__(self, api_key: str) -> None:
        assert api_key == "yk_live_test"

    def __enter__(self) -> "_FakeYes24Collector":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    request_parameters = staticmethod(Yes24Collector.request_parameters)

    def fetch_toc(self, isbn_13: str) -> dict:
        self.requested.append(isbn_13)
        return _yes24_response() if isbn_13 == YES24_ISBN else _yes24_not_found()


def test_enrich_api_toc_fills_missing_tocs_only(tmp_path, monkeypatch) -> None:
    missing = _book(YES24_ISBN)
    unknown = _book("9780131437401")
    covered = _book("9781118804926", topic="linear-algebra")
    existing = TocEntry(
        toc_entry_id="toc_existing",
        book_id=covered.book_id,
        level=1,
        order_index=0,
        title="Existing",
        source_id=f"source_seed_{covered.isbn_13}",
    )
    _seed(tmp_path / "processed", [missing, unknown, covered], [existing])
    _FakeYes24Collector.requested = []
    monkeypatch.setattr("data_pipeline.cli.Yes24Collector", _FakeYes24Collector)
    monkeypatch.setenv("YES24_API_KEY", "yk_live_test")

    result = CliRunner().invoke(
        app, ["enrich-api-toc", "--provider", "yes24", "--data-dir", str(tmp_path)]
    )

    assert result.exit_code == 0, result.output
    assert "1/3 -> 2/3" in result.output
    assert sorted(_FakeYes24Collector.requested) == ["9780131437401", YES24_ISBN]
    dataset = read_dataset(tmp_path / "processed")
    assert validate_dataset(dataset) == []
    assert {e.book_id for e in dataset.toc} == {missing.book_id, covered.book_id}
    report = json.loads(
        (tmp_path / "reports" / "api-toc-enrichment-yes24.json").read_text(encoding="utf-8")
    )
    assert report["status_counts"] == {"added": 1, "no_toc": 1}
    raw_files = list((tmp_path / "raw").rglob("*.json"))
    assert len(raw_files) == 2
    assert all("yk_live_test" not in path.read_text(encoding="utf-8") for path in raw_files)


def test_enrich_api_toc_requires_the_api_key(tmp_path, monkeypatch) -> None:
    _seed(tmp_path / "processed", [_book()])
    monkeypatch.delenv("SPRINGER_API_KEY", raising=False)

    result = CliRunner().invoke(
        app, ["enrich-api-toc", "--provider", "springer-metadata", "--data-dir", str(tmp_path)]
    )

    assert result.exit_code != 0
    assert "SPRINGER_API_KEY" in result.output
