"""Versioned dataset manifest loading and raw-artifact selection."""

from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from data_pipeline.models import CanonicalDataset
from data_pipeline.storage import RawArtifact, read_raw_response
from data_pipeline.topics import topic_choices

SourceSpecificProvider = Literal[
    "open-textbook",
    "public-book-page",
    "publisher-document",
    "publisher-page",
]
MetadataProvider = Literal["google-books", "open-library", "internet-archive"]
ManifestProvider = SourceSpecificProvider | MetadataProvider
SOURCE_SPECIFIC_PROVIDERS = {
    "open-textbook",
    "public-book-page",
    "publisher-document",
    "publisher-page",
}


class RawArtifactSelector(BaseModel):
    """Identify one latest local raw artifact by its reproducible request identity."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: ManifestProvider
    topic: str
    requested_limit: int = Field(ge=1, le=100)
    source: str | None = None
    content_hash: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    retrieved_at: datetime | None = None

    @field_validator("topic")
    @classmethod
    def topic_must_be_configured(cls, value: str) -> str:
        choices = topic_choices()
        if value not in choices:
            raise ValueError(f"topic must be one of: {', '.join(choices)}")
        return value

    @field_validator("retrieved_at")
    @classmethod
    def snapshot_time_must_have_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("raw snapshot retrieved_at must include timezone")
        return value

    @model_validator(mode="after")
    def source_matches_provider(self) -> "RawArtifactSelector":
        source_specific = self.provider in SOURCE_SPECIFIC_PROVIDERS
        if source_specific and not self.source:
            raise ValueError(f"source is required for provider {self.provider}")
        if not source_specific and self.source is not None:
            raise ValueError(f"source is not supported for provider {self.provider}")
        if source_specific and self.requested_limit != 1:
            raise ValueError(f"requested_limit must be 1 for provider {self.provider}")
        return self

    def matches(self, artifact: RawArtifact) -> bool:
        """Return whether one preserved artifact has this request identity."""
        return (
            artifact.provider == self.provider
            and artifact.topic == self.topic
            and artifact.requested_limit == self.requested_limit
            and (self.source is None or artifact.request_parameters.get("source") == self.source)
            and (self.content_hash is None or artifact.content_hash == self.content_hash)
            and (self.retrieved_at is None or artifact.retrieved_at == self.retrieved_at)
        )

    def display_name(self) -> str:
        """Return a readable selector name for diagnostics."""
        suffix = f"/{self.source}" if self.source is not None else ""
        return f"{self.provider}/{self.topic}{suffix}"


class MvpManifest(BaseModel):
    """Declare raw inputs and exact canonical book identities for one reproducible build."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    raw_artifacts: list[RawArtifactSelector] = Field(min_length=1)
    expected_book_ids: list[str] = Field(min_length=1)
    relevance_gate: Literal["topic-evidence-v1"] | None = None

    @model_validator(mode="after")
    def gate_requires_supported_provider(self) -> "MvpManifest":
        """Avoid silently treating unsupported collectors as relevance-filtered."""
        if self.relevance_gate and any(
            selector.provider != "open-library" for selector in self.raw_artifacts
        ):
            raise ValueError("topic-evidence-v1 supports open-library raw artifacts only")
        return self

    @field_validator("raw_artifacts")
    @classmethod
    def raw_artifact_selectors_must_be_unique(
        cls, selectors: list[RawArtifactSelector]
    ) -> list[RawArtifactSelector]:
        identities = [selector.model_dump_json() for selector in selectors]
        if len(identities) != len(set(identities)):
            raise ValueError("raw artifact selectors must be unique")
        return selectors

    @field_validator("expected_book_ids")
    @classmethod
    def expected_book_ids_must_be_unique(cls, book_ids: list[str]) -> list[str]:
        if len(book_ids) != len(set(book_ids)):
            raise ValueError("expected book IDs must be unique")
        return book_ids


def load_manifest(path: Path) -> MvpManifest:
    """Load a strict JSON manifest with a path-aware validation error."""
    try:
        return MvpManifest.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"dataset manifest is invalid: {path}: {exc}") from exc


def select_manifest_raw_paths(manifest: MvpManifest, raw_directory: Path) -> list[Path]:
    """Select the latest matching immutable artifact for every manifest entry."""
    selected: list[Path] = []
    for selector in manifest.raw_artifacts:
        selector_directory = raw_directory / selector.provider.replace("-", "_") / selector.topic
        candidates: list[tuple[Path, RawArtifact]] = []
        for path in sorted(selector_directory.glob("*.json")):
            try:
                candidates.append((path, read_raw_response(path)))
            except ValueError as exc:
                raise ValueError(f"cannot inspect manifest raw directory: {exc}") from exc
        matches = [item for item in candidates if selector.matches(item[1])]
        if not matches:
            raise ValueError(
                f"missing raw artifact for manifest selector: {selector.display_name()}"
            )
        latest_path, _latest_artifact = max(
            matches,
            key=lambda item: (item[1].retrieved_at, item[0].as_posix()),
        )
        selected.append(latest_path)
    return selected


def validate_manifest_books(manifest: MvpManifest, dataset: CanonicalDataset) -> list[str]:
    """Return missing and unexpected canonical book identities for a manifest build."""
    expected = set(manifest.expected_book_ids)
    actual = {book.book_id for book in dataset.books}
    errors = []
    if missing := sorted(expected - actual):
        errors.append("manifest books missing from dataset: " + ", ".join(missing))
    if unexpected := sorted(actual - expected):
        errors.append("dataset contains books outside manifest: " + ", ".join(unexpected))
    return errors
