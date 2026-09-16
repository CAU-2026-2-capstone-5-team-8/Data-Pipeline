"""Raw-response preservation and canonical JSONL storage."""

import os
import shutil
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from data_pipeline.identifiers import sha256_json
from data_pipeline.models import Book, CanonicalDataset, Document, Source, TocEntry


class RawArtifact(BaseModel):
    """Immutable provider response plus the inputs needed for exact normalization."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    provider: str
    topic: str
    requested_limit: int = Field(ge=1, le=100)
    retrieved_at: datetime
    request_parameters: dict[str, Any]
    response: dict[str, Any]
    content_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")

    @model_validator(mode="before")
    @classmethod
    def populate_or_validate_content_hash(cls, value: Any) -> Any:
        if isinstance(value, dict):
            payload = dict(value)
            response = payload.get("response")
            if isinstance(response, dict):
                expected = sha256_json(response)
                supplied = payload.get("content_hash")
                if supplied is not None and supplied != expected:
                    raise ValueError("raw response content hash mismatch")
                payload["content_hash"] = expected
            return payload
        return value

    @field_validator("retrieved_at")
    @classmethod
    def retrieved_at_must_include_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("retrieved_at must include a timezone")
        return value


def write_raw_response(artifact: RawArtifact, path: Path) -> None:
    """Write a raw artifact once, refusing to overwrite prior evidence."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        stream.write(artifact.model_dump_json(indent=2) + "\n")


def read_raw_response(path: Path) -> RawArtifact:
    try:
        return RawArtifact.model_validate_json(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise ValueError(f"raw artifact is invalid: {path}: {exc}") from exc


def raw_artifact_path(data_dir: Path, artifact: RawArtifact) -> Path:
    """Create a collision-resistant path for one immutable retrieval event."""
    timestamp = artifact.retrieved_at.strftime("%Y%m%dT%H%M%S%fZ")
    response_hash = artifact.content_hash.removeprefix("sha256:")[:12]
    provider_directory = artifact.provider.replace("-", "_")
    return (
        data_dir / "raw" / provider_directory / artifact.topic / f"{timestamp}_{response_hash}.json"
    )


def _write_jsonl(records: Iterable[BaseModel], path: Path) -> None:
    with path.open("w", encoding="utf-8") as stream:
        for record in records:
            stream.write(record.model_dump_json(exclude_none=False) + "\n")


def write_dataset(dataset: CanonicalDataset, directory: Path) -> None:
    """Publish a complete flat dataset and restore the previous set on replacement errors."""
    directory.mkdir(parents=True, exist_ok=True)
    collections = {
        "books.jsonl": dataset.books,
        "documents.jsonl": dataset.documents,
        "toc.jsonl": dataset.toc,
        "sources.jsonl": dataset.sources,
    }
    temporary_paths: dict[str, Path] = {}
    backup_paths: dict[str, Path] = {}
    published: list[str] = []
    try:
        for filename, records in collections.items():
            with NamedTemporaryFile(
                dir=directory, prefix=f".{filename}.", suffix=".tmp", delete=False
            ) as temporary:
                temporary_path = Path(temporary.name)
            temporary_paths[filename] = temporary_path
            _write_jsonl(records, temporary_path)

        final_paths = {filename: directory / filename for filename in collections}
        existing = [path.exists() for path in final_paths.values()]
        if any(existing) and not all(existing):
            missing = ", ".join(
                filename
                for (filename, path), exists in zip(final_paths.items(), existing, strict=True)
                if not exists
            )
            raise ValueError(f"partial canonical dataset; missing: {missing}")

        if all(existing):
            for filename, final_path in final_paths.items():
                with NamedTemporaryFile(
                    dir=directory, prefix=f".{filename}.", suffix=".bak", delete=False
                ) as backup:
                    backup_path = Path(backup.name)
                shutil.copyfile(final_path, backup_path)
                backup_paths[filename] = backup_path

        for filename, temporary_path in temporary_paths.items():
            os.replace(temporary_path, directory / filename)
            published.append(filename)
    except Exception:
        for filename in reversed(published):
            final_path = directory / filename
            backup_path = backup_paths.get(filename)
            if backup_path is None:
                final_path.unlink(missing_ok=True)
            else:
                os.replace(backup_path, final_path)
        raise
    finally:
        for temporary_path in temporary_paths.values():
            temporary_path.unlink(missing_ok=True)
        for backup_path in backup_paths.values():
            backup_path.unlink(missing_ok=True)


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


def dataset_exists(directory: Path) -> bool:
    """Return whether a complete canonical four-file dataset exists."""
    paths = [
        directory / name
        for name in ("books.jsonl", "documents.jsonl", "toc.jsonl", "sources.jsonl")
    ]
    existing = [path.exists() for path in paths]
    if any(existing) and not all(existing):
        missing = ", ".join(
            path.name for path, exists in zip(paths, existing, strict=True) if not exists
        )
        raise ValueError(f"partial canonical dataset; missing: {missing}")
    return all(existing)
