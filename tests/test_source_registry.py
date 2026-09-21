import json
from dataclasses import dataclass
from typing import Literal

import pytest
from pydantic import ValidationError

from data_pipeline.source_registry import load_registry_dir
from data_pipeline.topics import _load_registry


@dataclass(frozen=True)
class ExampleSource:
    slug: str
    edition: int
    source_format: Literal["reviewed"]
    labels: tuple[str, ...] = ()


def test_source_registry_validates_and_coerces_annotated_values(tmp_path) -> None:
    config = {
        "slug": "example",
        "edition": "4",
        "source_format": "reviewed",
        "labels": ["1", "2"],
    }
    (tmp_path / "example.json").write_text(json.dumps(config), encoding="utf-8")

    source = load_registry_dir(ExampleSource, tmp_path)["example"]

    assert source.edition == 4
    assert source.labels == ("1", "2")


def test_source_registry_rejects_unknown_fields_and_literal_values(tmp_path) -> None:
    config = {
        "slug": "example",
        "edition": 4,
        "source_format": "unsupported",
        "unexpected": True,
    }
    path = tmp_path / "example.json"
    path.write_text(json.dumps(config), encoding="utf-8")

    with pytest.raises(ValueError, match="unknown fields"):
        load_registry_dir(ExampleSource, tmp_path)

    del config["unexpected"]
    path.write_text(json.dumps(config), encoding="utf-8")
    with pytest.raises(ValidationError, match="reviewed"):
        load_registry_dir(ExampleSource, tmp_path)


def test_source_registry_rejects_missing_or_empty_directories(tmp_path) -> None:
    with pytest.raises(FileNotFoundError, match="not found"):
        load_registry_dir(ExampleSource, tmp_path / "missing")
    with pytest.raises(ValueError, match="no entries"):
        load_registry_dir(ExampleSource, tmp_path)


def test_topic_registry_rejects_duplicate_json_keys(tmp_path) -> None:
    path = tmp_path / "topics.json"
    path.write_text('{"linear-algebra": {}, "linear-algebra": {}}', encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate JSON key.*linear-algebra"):
        _load_registry(path)


def test_topic_registry_rejects_non_object_root(tmp_path) -> None:
    path = tmp_path / "topics.json"
    path.write_text("[]", encoding="utf-8")

    with pytest.raises(ValueError, match="must be a JSON object"):
        _load_registry(path)
