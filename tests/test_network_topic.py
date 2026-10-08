from datetime import UTC, datetime

import pytest

from data_pipeline.normalizers import normalize_yes24_response


@pytest.mark.parametrize(
    ("title", "category", "accepted"),
    [
        ("컴퓨터 네트워크 원리", "국내도서-IT 모바일-네트워크", True),
        ("데이터 통신과 TCP/IP", "국내도서-대학교재-컴퓨터공학", True),
        ("네트워크 기초", "국내도서-IT 모바일", True),
        ("컴퓨터 네트워크로 이해하는 신경망", "국내도서-IT 모바일", False),
        ("소셜 네트워크 마케팅", "국내도서-경제 경영", False),
        ("컴퓨터 네트워크", "국내도서-소설", False),
        ("컴퓨터 네트워크", None, False),
        ("알고리즘 입문", "국내도서-IT 모바일", False),
    ],
)
def test_network_rules_require_topic_and_provider_category(title, category, accepted):
    item = {
        "itemId": 123,
        "title": title,
        "goodsSortNm": category,
        "isbn13": "9780306406157",
        "author": "Synthetic author",
    }
    dataset = normalize_yes24_response(
        {"data": {"items": [item]}},
        topic="computer-networks",
        limit=20,
        retrieved_at=datetime(2026, 10, 5, tzinfo=UTC),
    )
    assert bool(dataset.books) is accepted
    if accepted:
        assert dataset.books[0].topics == ["computer-science", "computer-networks"]
        assert dataset.sources[0].book_id == dataset.books[0].book_id
