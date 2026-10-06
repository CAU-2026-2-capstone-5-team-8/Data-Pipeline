from datetime import UTC, datetime

import pytest

from data_pipeline.collectors.yes24 import Yes24Collector
from data_pipeline.normalizers import normalize_yes24_response
from data_pipeline.query_discovery import discover_categories, discovery_policy
from data_pipeline.validation import validate_dataset

NOW = datetime(2026, 10, 6, tzinfo=UTC)


def response():
    return {
        "data": {
            "items": [
                {
                    "itemId": 1,
                    "title": "경제학 입문",
                    "isbn13": "9780306406157",
                    "author": "저자",
                    "goodsSortNm": "국내도서-경제 경영",
                    "contentDetail": {"tableOfContents": "1. 시장\n2. 가격"},
                },
                {
                    "itemId": 2,
                    "title": "경제학 입문",
                    "isbn13": "9780306406157",
                    "author": "저자",
                    "goodsSortNm": "국내도서-경제 경영",
                },
                {
                    "itemId": 3,
                    "title": "경제 이야기",
                    "isbn13": "9780134853987",
                    "author": "다른 저자",
                    "goodsSortNm": "국내도서-어린이",
                },
                {
                    "itemId": 4,
                    "title": "관계없는 소설",
                    "isbn13": "9780201616224",
                    "author": "저자",
                    "goodsSortNm": "국내도서-경제 경영",
                },
                {"itemId": 5, "title": "경제 묶음 상품", "goodsSortNm": "국내도서-경제 경영"},
                {"itemId": 6, "title": "경제 분류 없음", "isbn13": "9780201616224"},
            ]
        }
    }


def test_discovery_returns_observed_categories_and_deduplicated_eligible_samples():
    groups = discover_categories(response(), "경제", NOW)
    assert {g["category"]: g["bookCount"] for g in groups} == {
        "국내도서-경제 경영": 1,
        "국내도서-어린이": 1,
    }
    assert groups[0]["samples"][0]["title"] == "경제학 입문"
    assert discover_categories(response(), "aa", NOW) == []


def test_selected_category_and_literal_query_are_both_required_without_schema_changes():
    policy = discovery_policy("경제", "국내도서-경제 경영")
    first = normalize_yes24_response(
        response(), topic=policy.slug, limit=20, retrieved_at=NOW, discovery_spec=policy
    )
    second = normalize_yes24_response(
        response(), topic=policy.slug, limit=20, retrieved_at=NOW, discovery_spec=policy
    )
    assert len(first.books) == 1
    assert first.books[0].topics == [policy.domain, policy.slug]
    assert first.sources[0].provider == "yes24"
    assert first.toc and not validate_dataset(first)
    assert first.model_dump() == second.model_dump()


def test_query_is_literal_and_discovery_cannot_replace_registered_policy():
    with pytest.raises(ValueError):
        discovery_policy(".*", "국내도서-경제 경영")
    literal = discovery_policy("경제.*", "국내도서-경제 경영")
    assert discover_categories(response(), "경제.*", NOW) == []
    override = literal.model_copy(update={"slug": "linear-algebra"})
    with pytest.raises(ValueError, match="override"):
        normalize_yes24_response(
            response(), topic=override.slug, limit=20, retrieved_at=NOW, discovery_spec=override
        )


def test_collector_uses_bounded_literal_query_parameters():
    assert Yes24Collector.query_parameters("경제", 100)["pages"] == [
        {"query": "경제", "category": "BOOK", "detail": "Y", "pageSize": 100, "page": 1}
    ]
    with pytest.raises(ValueError):
        discovery_policy("경제", "unknown")
