from datetime import UTC, datetime

import httpx
import pytest

from data_pipeline.collectors.base import InvalidProviderResponse
from data_pipeline.collectors.yes24 import MissingApiKey, Yes24Collector
from data_pipeline.diagnostics import NormalizationDiagnostics
from data_pipeline.normalizers import normalize_yes24_response
from data_pipeline.validation import validate_dataset

RETRIEVED_AT = datetime(2026, 9, 23, 12, 0, tzinfo=UTC)

PART_STYLE_CONTENTS = (
    "『제4권. 선형대수학』\r\n\r\n"
    "PART 0. 기초상식\r\n\r\n"
    "\t0-1. 집합과 명제\r\n"
    "\t0-2. 연산\r\n\r\n"
    "[부록]\r\n"
    "1. QR분해\r\n"
    "2. 특이값 분해(SVD)\r\n\r\n"
    "연습문제 정답 및 해설"
)

CHAPTER_STYLE_CONTENTS = (
    "1장 벡터와 행렬\r\n\r\n"
    "1.1 벡터와 선형결합\r\n"
    "1.2 내적으로부터의 길이와 각\r\n\r\n"
    "1장에 대한 고찰\r\n\r\n"
    "2장 선형방정식 Ax=b 풀기\r\n\r\n"
    "2.1 소거법과 역대입법"
)


def _item(**overrides: object) -> dict:
    item = {
        "itemId": 105894639,
        "title": "스트랭 선형대수학",
        "author": "Gilbert Strang 저/김영길 역",
        "publisher": "한빛아카데미",
        "isbn10": "",
        "isbn13": "9791173400438",
        "publishDate": "20250115",
        "link": "https://www.yes24.com/product/goods/105894639",
        "originalTranslation": "",
        "originalTitle": "",
        "contentDetail": {
            "bookIntroduction": "선형대수학 명저의 번역판.",
            "bookSummary": None,
            "tableOfContents": CHAPTER_STYLE_CONTENTS,
        },
    }
    item.update(overrides)
    return item


def _response(*items: dict) -> dict:
    return {
        "success": True,
        "message": "성공",
        "data": {"meta": {"apiTitle": "상품 검색"}, "items": list(items)},
        "errorCode": None,
    }


# --- Collector ---------------------------------------------------------------


def test_collector_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("YES24_API_KEY", raising=False)
    with pytest.raises(MissingApiKey):
        Yes24Collector()


def test_search_parameters_uses_korean_topic_query() -> None:
    parameters = Yes24Collector.search_parameters("linear-algebra", 20)
    assert parameters["query"] == "선형대수"
    assert parameters["category"] == "BOOK"
    assert parameters["detail"] == "Y"
    assert parameters["pageSize"] == 20


def test_search_parameters_caps_page_size_at_one_hundred() -> None:
    assert Yes24Collector.search_parameters("linear-algebra", 500)["pageSize"] == 100


def test_search_parameters_rejects_non_positive_candidate_limit() -> None:
    with pytest.raises(ValueError, match="candidate_limit"):
        Yes24Collector.search_parameters("linear-algebra", 0)


def test_search_books_sends_the_planned_request_and_returns_the_raw_response() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json=_response(_item()), request=request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        payload = Yes24Collector(client=client, api_key="test-key").search_books(
            "linear-algebra", candidate_limit=5
        )

    assert len(captured) == 1
    assert captured[0].headers["X-Api-Key"] == "test-key"
    assert captured[0].url.params["query"] == "선형대수"
    assert payload["data"]["items"][0]["itemId"] == 105894639


def test_search_books_treats_search_001_404_as_empty_results() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            404,
            json={
                "success": False,
                "message": "검색 결과가 없습니다.",
                "data": None,
                "errorCode": "SEARCH_001",
            },
            request=request,
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        payload = Yes24Collector(client=client, api_key="test-key").search_books(
            "linear-algebra", candidate_limit=5
        )

    assert payload["data"]["items"] == []


def test_search_books_reraises_other_404_errors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            404,
            json={"success": False, "message": "unexpected", "data": None, "errorCode": "UNKNOWN"},
            request=request,
        )

    with (
        httpx.Client(transport=httpx.MockTransport(handler)) as client,
        pytest.raises(httpx.HTTPStatusError),
    ):
        Yes24Collector(client=client, api_key="test-key").search_books(
            "linear-algebra", candidate_limit=5
        )


def test_fetch_content_treats_goods_001_404_as_no_content() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            404,
            json={
                "success": False,
                "message": "상품 상세/목차 정보가 없습니다.",
                "data": None,
                "errorCode": "GOODS_001",
            },
            request=request,
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        payload = Yes24Collector(client=client, api_key="test-key").fetch_content("9791173400438")

    assert payload["success"] is True
    assert payload["data"] == {}


# --- Normalizer: identity, description, translation -----------------------------


def test_normalize_preserves_identity_and_description() -> None:
    dataset = normalize_yes24_response(
        _response(_item()), topic="linear-algebra", limit=5, retrieved_at=RETRIEVED_AT
    )

    assert len(dataset.books) == 1
    book = dataset.books[0]
    assert book.book_id == "isbn13:9791173400438"
    assert book.title == "스트랭 선형대수학"
    assert book.authors == ["Gilbert Strang 저/김영길 역"]
    assert book.publisher == "한빛아카데미"
    assert book.published_year == 2025
    assert book.language == "ko"
    assert book.topics == ["mathematics", "linear-algebra"]

    assert len(dataset.sources) == 1
    source = dataset.sources[0]
    assert source.provider == "yes24"
    assert source.source_type == "metadata_api"
    assert source.url == "https://www.yes24.com/product/goods/105894639"
    assert source.license is None
    assert source.rights_note is None

    assert len(dataset.documents) == 1
    document = dataset.documents[0]
    assert document.document_type == "description"
    assert document.text == "선형대수학 명저의 번역판."
    assert document.source_id == source.source_id


def test_normalize_records_translation_without_inventing_a_license() -> None:
    dataset = normalize_yes24_response(
        _response(
            _item(
                originalTranslation="Y",
                originalTitle="Introduction to Linear Algebra",
            )
        ),
        topic="linear-algebra",
        limit=5,
        retrieved_at=RETRIEVED_AT,
    )

    source = dataset.sources[0]
    assert source.license is None
    assert source.rights_note is not None
    assert "Introduction to Linear Algebra" in source.rights_note


def test_normalize_falls_back_to_product_url_when_link_missing() -> None:
    dataset = normalize_yes24_response(
        _response(_item(link="")), topic="linear-algebra", limit=5, retrieved_at=RETRIEVED_AT
    )
    assert dataset.sources[0].url == "https://www.yes24.com/product/goods/105894639"


# --- Normalizer: TOC parsing -----------------------------------------------------


def test_normalize_parses_chapter_dot_numbered_toc_without_indentation() -> None:
    dataset = normalize_yes24_response(
        _response(_item()), topic="linear-algebra", limit=5, retrieved_at=RETRIEVED_AT
    )

    toc = dataset.toc
    roots = [entry for entry in toc if entry.parent_entry_id is None]
    assert [entry.title for entry in roots] == [
        "1장 벡터와 행렬",
        "1장에 대한 고찰",
        "2장 선형방정식 Ax=b 풀기",
    ]

    chapter_one = roots[0]
    children_of_one = [entry for entry in toc if entry.parent_entry_id == chapter_one.toc_entry_id]
    assert [(entry.label, entry.title) for entry in children_of_one] == [
        ("1.1", "벡터와 선형결합"),
        ("1.2", "내적으로부터의 길이와 각"),
    ]
    assert all(entry.level == 2 for entry in children_of_one)

    chapter_two = roots[2]
    children_of_two = [entry for entry in toc if entry.parent_entry_id == chapter_two.toc_entry_id]
    assert [(entry.label, entry.title) for entry in children_of_two] == [
        ("2.1", "소거법과 역대입법")
    ]


def test_normalize_parses_part_style_toc_with_tab_indented_children() -> None:
    dataset = normalize_yes24_response(
        _response(_item(contentDetail={"tableOfContents": PART_STYLE_CONTENTS})),
        topic="linear-algebra",
        limit=5,
        retrieved_at=RETRIEVED_AT,
    )

    toc = dataset.toc
    roots = [entry for entry in toc if entry.parent_entry_id is None]
    root_titles = [entry.title for entry in roots]
    assert "기초상식" in root_titles
    assert "부록" in root_titles
    assert "연습문제 정답 및 해설" in root_titles

    part_zero = next(entry for entry in roots if entry.title == "기초상식")
    assert part_zero.label == "0"
    children = [entry for entry in toc if entry.parent_entry_id == part_zero.toc_entry_id]
    assert [(entry.label, entry.title) for entry in children] == [
        ("0-1", "집합과 명제"),
        ("0-2", "연산"),
    ]

    # Un-indented, non-chapter-numbered lines under "[부록]" are not guessed as its
    # children -- they become their own flat roots (no invented hierarchy).
    appendix_index = root_titles.index("부록")
    assert root_titles[appendix_index + 1 : appendix_index + 3] == [
        "QR분해",
        "특이값 분해(SVD)",
    ]


def _toc_tree(contents: str) -> list[tuple[int, str | None, str, str | None]]:
    """(level, label, title, parent title) for each entry, in order."""
    dataset = normalize_yes24_response(
        _response(_item(contentDetail={"tableOfContents": contents})),
        topic="linear-algebra",
        limit=5,
        retrieved_at=RETRIEVED_AT,
    )
    titles = {entry.toc_entry_id: entry.title for entry in dataset.toc}
    return [
        (entry.level, entry.label, entry.title, titles.get(entry.parent_entry_id or ""))
        for entry in sorted(dataset.toc, key=lambda entry: entry.order_index)
    ]


def test_normalize_gives_unique_ids_and_order_when_titles_repeat_across_chapters() -> None:
    contents = "1장 벡터\r\n1.1 내적\r\n요약\r\n2장 행렬\r\n2.1 곱셈\r\n요약\r\n"
    dataset = normalize_yes24_response(
        _response(_item(contentDetail={"tableOfContents": contents})),
        topic="linear-algebra",
        limit=5,
        retrieved_at=RETRIEVED_AT,
    )

    assert validate_dataset(dataset) == []
    assert len({entry.toc_entry_id for entry in dataset.toc}) == 6
    assert [entry.order_index for entry in dataset.toc] == [0, 1, 2, 3, 4, 5]


def test_normalize_strips_html_and_nests_hyphen_sections_and_underscore_items() -> None:
    contents = (
        "<b>Chapter 01 컴퓨터 구조 시작하기</B>\r\n\r\n"
        "01-1 구조를 알아야 하는 이유\t\r\n"
        "__문제 해결\t\r\n"
        "[확인 문제]\r\n"
        "01-2 컴퓨터 구조의 큰 그림\r\n"
        "<B>Chapter 02 데이터</B>\r\n"
    )

    assert _toc_tree(contents) == [
        (1, None, "Chapter 01 컴퓨터 구조 시작하기", None),
        (2, "01-1", "구조를 알아야 하는 이유", "Chapter 01 컴퓨터 구조 시작하기"),
        (3, None, "문제 해결", "구조를 알아야 하는 이유"),
        # Unmarked lines stay flat roots but do not close the open chapter.
        (1, None, "확인 문제", None),
        (2, "01-2", "컴퓨터 구조의 큰 그림", "Chapter 01 컴퓨터 구조 시작하기"),
        (1, None, "Chapter 02 데이터", None),
    ]


def test_normalize_nests_parts_chapters_and_multi_level_numbers() -> None:
    contents = (
        "<b>PART 01 운영체제와 컴퓨터</b>\r\n"
        "CHAPTER 01 운영체제 개요\r\n"
        "01 운영체제의 개념\r\n"
        "1.2 운영체제의 유형\r\n"
        "1.2.1 일괄 처리 시스템\r\n"
        "제2장 프로세스\r\n"
        "\t1. 프로세스의 개념\r\n"
    )

    assert _toc_tree(contents) == [
        (1, "01", "운영체제와 컴퓨터", None),
        (2, None, "CHAPTER 01 운영체제 개요", "운영체제와 컴퓨터"),
        (3, "01", "운영체제의 개념", "CHAPTER 01 운영체제 개요"),
        (3, "1.2", "운영체제의 유형", "CHAPTER 01 운영체제 개요"),
        (4, "1.2.1", "일괄 처리 시스템", "운영체제의 유형"),
        (2, None, "제2장 프로세스", "운영체제와 컴퓨터"),
        (3, "1", "프로세스의 개념", "제2장 프로세스"),
    ]


def test_normalize_nests_single_numbers_under_part_and_splits_br_lines() -> None:
    contents = "<b>PART 1 주제 도출</b>\r\n01 문장 독해<br/>02 정보 관계\r\n"

    assert _toc_tree(contents) == [
        (1, "1", "주제 도출", None),
        (2, "01", "문장 독해", "주제 도출"),
        (2, "02", "정보 관계", "주제 도출"),
    ]


def test_normalize_back_matter_closes_the_open_chapter() -> None:
    contents = "Chapter 5 고유값\r\n1. 대각화\r\n[부록]\r\n1. QR분해\r\n"

    assert [(level, title) for level, _, title, _ in _toc_tree(contents)] == [
        (1, "Chapter 5 고유값"),
        (2, "대각화"),
        (1, "부록"),
        (1, "QR분해"),
    ]


def test_normalize_skips_books_with_no_table_of_contents() -> None:
    dataset = normalize_yes24_response(
        _response(_item(contentDetail={"tableOfContents": None})),
        topic="linear-algebra",
        limit=5,
        retrieved_at=RETRIEVED_AT,
    )
    assert dataset.toc == []
    assert len(dataset.books) == 1


# --- Normalizer: candidate handling, dedup, errors -------------------------------


def test_normalize_skips_items_missing_title_or_item_id() -> None:
    dataset = normalize_yes24_response(
        _response(_item(title=""), _item(itemId="not-an-int")),
        topic="linear-algebra",
        limit=5,
        retrieved_at=RETRIEVED_AT,
    )
    assert dataset.books == []


def test_normalize_skips_items_without_any_isbn() -> None:
    """A bundle/set listing (e.g. "...ver 3.0 세트") has no real ISBN and is not a book."""
    dataset = normalize_yes24_response(
        _response(_item(isbn10="", isbn13="")),
        topic="linear-algebra",
        limit=5,
        retrieved_at=RETRIEVED_AT,
    )
    assert dataset.books == []


def test_normalize_accepts_isbn10_only_items() -> None:
    dataset = normalize_yes24_response(
        _response(_item(isbn10="0070380376", isbn13="")),
        topic="linear-algebra",
        limit=5,
        retrieved_at=RETRIEVED_AT,
    )
    assert dataset.books[0].book_id == "isbn10:0070380376"


def test_normalize_drops_isbn10_that_identifies_a_different_book() -> None:
    # 979-prefixed ISBN-13s have no ISBN-10; YES24's checksum-valid isbn10 is spurious.
    dataset = normalize_yes24_response(
        _response(_item(isbn10="1169665993", isbn13="9791169665995")),
        topic="linear-algebra",
        limit=5,
        retrieved_at=RETRIEVED_AT,
    )

    book = dataset.books[0]
    assert (book.book_id, book.isbn_10, book.isbn_13) == (
        "isbn13:9791169665995",
        None,
        "9791169665995",
    )


def test_normalize_keeps_isbn10_that_matches_its_isbn13() -> None:
    dataset = normalize_yes24_response(
        _response(_item(isbn10="0070380376", isbn13="9780070380370")),
        topic="linear-algebra",
        limit=5,
        retrieved_at=RETRIEVED_AT,
    )

    assert dataset.books[0].isbn_10 == "0070380376"


def test_normalize_skips_titles_that_do_not_match_the_topic_relevance_pattern() -> None:
    dataset = normalize_yes24_response(
        _response(_item(title="이공편입수학 ver 3.0 세트")),
        topic="linear-algebra",
        limit=5,
        retrieved_at=RETRIEVED_AT,
    )
    assert dataset.books == []


def test_normalize_matches_relevance_pattern_for_other_topics() -> None:
    dataset = normalize_yes24_response(
        _response(_item(title="운영체제 개념과 예제", isbn13="9791162243022")),
        topic="operating-systems",
        limit=5,
        retrieved_at=RETRIEVED_AT,
    )
    assert len(dataset.books) == 1


def test_normalize_deduplicates_same_book_id_across_items() -> None:
    diagnostics = NormalizationDiagnostics(provider="yes24")
    dataset = normalize_yes24_response(
        _response(_item(itemId=1), _item(itemId=2)),
        topic="linear-algebra",
        limit=5,
        retrieved_at=RETRIEVED_AT,
        diagnostics=diagnostics,
    )
    assert len(dataset.books) == 1
    assert diagnostics.duplicate_candidate_count == 1
    assert diagnostics.candidate_count == 2


def test_normalize_rejects_unsupported_topic() -> None:
    with pytest.raises(ValueError, match="unsupported topic"):
        normalize_yes24_response(
            _response(_item()), topic="astrophysics", limit=5, retrieved_at=RETRIEVED_AT
        )


def test_normalize_requires_a_data_object() -> None:
    with pytest.raises(InvalidProviderResponse, match="data"):
        normalize_yes24_response(
            {"data": "not-an-object"}, topic="linear-algebra", limit=5, retrieved_at=RETRIEVED_AT
        )


def test_normalize_requires_items_to_be_a_list() -> None:
    with pytest.raises(InvalidProviderResponse, match="items"):
        normalize_yes24_response(
            {"data": {"items": {}}}, topic="linear-algebra", limit=5, retrieved_at=RETRIEVED_AT
        )
