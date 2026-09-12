"""Raw-response preservation and canonical JSONL storage."""

import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from data_pipeline.models import Book, CanonicalDataset, Document, Source, TocEntry


@dataclass(frozen=True)
class RawArtifact:
    provider: str
    retrieved_at: datetime
    response: dict[str, Any]


def write_raw_response(artifact: RawArtifact, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "provider": artifact.provider,
        "retrieved_at": artifact.retrieved_at.isoformat(),
        "response": artifact.response,
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def read_raw_response(path: Path) -> RawArtifact:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"raw artifact is not a JSON object: {path}")
    try:
        provider = payload["provider"]
        retrieved_at = datetime.fromisoformat(payload["retrieved_at"])
        response = payload["response"]
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"raw artifact metadata is invalid: {path}") from exc
    if not isinstance(provider, str) or not isinstance(response, dict):
        raise ValueError(f"raw artifact fields are invalid: {path}")
    return RawArtifact(provider=provider, retrieved_at=retrieved_at, response=response)


def _write_jsonl(records: Iterable[BaseModel], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        for record in records:
            stream.write(record.model_dump_json(exclude_none=False) + "\n")


def write_dataset(dataset: CanonicalDataset, directory: Path) -> None:
    _write_jsonl(dataset.books, directory / "books.jsonl")
    _write_jsonl(dataset.documents, directory / "documents.jsonl")
    _write_jsonl(dataset.toc, directory / "toc.jsonl")
    _write_jsonl(dataset.sources, directory / "sources.jsonl")


def _read_jsonl(model: type[BaseModel], path: Path) -> list[BaseModel]:
    if not path.exists():
        raise FileNotFoundError(f"missing canonical dataset: {path}")
    lines = path.read_text(encoding="utf-8").splitlines()
    return [model.model_validate_json(line) for line in lines if line.strip()]


def read_dataset(directory: Path) -> CanonicalDataset:
    return CanonicalDataset(
        books=_read_jsonl(Book, directory / "books.jsonl"),
        documents=_read_jsonl(Document, directory / "documents.jsonl"),
        toc=_read_jsonl(TocEntry, directory / "toc.jsonl"),
        sources=_read_jsonl(Source, directory / "sources.jsonl"),
    )
