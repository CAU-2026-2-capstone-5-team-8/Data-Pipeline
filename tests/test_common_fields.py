from datetime import UTC, datetime

import pytest

from data_pipeline.collection_scope import (
    common_field_scope,
    normalize_scope_response,
    open_library_parameters,
)
from data_pipeline.common_fields import common_field, is_browsing_spec, resolve_common_field
from data_pipeline.models import CanonicalDataset
from data_pipeline.normalizers import normalize_yes24_response


def test_multilingual_aliases_share_identity_and_provider_specific_queries():
    field = common_field("microeconomics")
    assert all(
        resolve_common_field(name) == field
        for name in ["미시경제", "미시 경제학", "Microeconomics", "ＭＩＣＲＯＥＣＯＮＯＭＩＣＳ"]
    )
    assert field.slug == "field-microeconomics"
    assert field.spec().domain == "social-sciences"
    assert field.spec().korean_query == "미시경제학"
    assert field.english_query == "microeconomics"
    scope = common_field_scope(field)
    assert scope.source_provider == "common" and scope.source_category == ""
    assert scope.book_kind is None
    assert 'subject:"microeconomics"' in open_library_parameters(scope)["q"]
    assert all(
        resolve_common_field(name) is None
        for name in ["aa", "foobar", "미시 경제 공부하는 법", "foo OR *:*", "수학"]
    )


def test_common_identity_does_not_allow_unreviewed_policy_override():
    spec = common_field("microeconomics").spec()
    assert is_browsing_spec(spec)
    forged = spec.model_copy(update={"relevance_term_pattern": ".*"})
    assert not is_browsing_spec(forged)
    with pytest.raises(ValueError):
        normalize_scope_response(
            {"docs": []},
            common_field_scope(common_field("microeconomics")),
            forged,
            datetime.now(UTC),
        )
    with pytest.raises(ValueError):
        normalize_yes24_response(
            {"data": {"items": []}},
            topic=forged.slug,
            limit=20,
            retrieved_at=datetime.now(UTC),
            discovery_spec=forged,
        )
    assert normalize_yes24_response(
        {"data": {"items": []}},
        topic=spec.slug,
        limit=20,
        retrieved_at=datetime.now(UTC),
        discovery_spec=spec,
    ) == CanonicalDataset(books=[], documents=[], toc=[], sources=[])
