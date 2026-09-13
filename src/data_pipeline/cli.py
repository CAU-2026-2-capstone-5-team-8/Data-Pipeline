"""Command-line entry point for the small MVP collection slice."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import httpx
import typer

from data_pipeline.collectors.base import InvalidProviderResponse
from data_pipeline.collectors.google_books import GoogleBooksCollector
from data_pipeline.collectors.open_library import OpenLibraryCollector
from data_pipeline.datasets import DatasetMergeError, merge_datasets
from data_pipeline.models import CanonicalDataset
from data_pipeline.normalizers import (
    TOPICS,
    normalize_google_books_response,
    normalize_open_library_response,
)
from data_pipeline.reporting import format_coverage
from data_pipeline.storage import (
    RawArtifact,
    dataset_exists,
    raw_artifact_path,
    read_dataset,
    read_raw_response,
    write_dataset,
    write_raw_response,
)
from data_pipeline.validation import validate_dataset

app = typer.Typer(no_args_is_help=True, help="Collect and normalize public book evidence.")
TopicOption = Annotated[str, typer.Option(help="Configured leaf topic slug.")]
LimitOption = Annotated[int, typer.Option(min=1, max=10, help="Books to normalize.")]
ProviderOption = Annotated[
    str, typer.Option(help="Metadata provider: open-library or google-books.")
]


def _ensure_topic(topic: str) -> None:
    if topic not in TOPICS:
        choices = ", ".join(sorted(TOPICS))
        raise typer.BadParameter(f"topic must be one of: {choices}")


def _collect_payload(
    provider: str,
    topic: str,
    candidate_limit: int,
    *,
    edition_detail_limit: int = 0,
) -> tuple[dict, dict]:
    collectors = {
        "google-books": GoogleBooksCollector,
        "open-library": OpenLibraryCollector,
    }
    try:
        collector_class = collectors[provider]
    except KeyError as exc:
        raise typer.BadParameter("provider must be open-library or google-books") from exc
    try:
        with collector_class() as collector:
            request_parameters = collector.search_parameters(topic, candidate_limit)
            payload = collector.search_books(topic, candidate_limit=candidate_limit)
            if isinstance(collector, OpenLibraryCollector) and edition_detail_limit > 0:
                payload = {
                    "search_response": payload,
                    "edition_details": collector.fetch_edition_details(
                        payload, candidate_limit=edition_detail_limit
                    ),
                }
            return payload, request_parameters
    except httpx.HTTPStatusError as exc:
        raise typer.BadParameter(
            f"{provider} returned HTTP {exc.response.status_code}; no data was written"
        ) from exc
    except httpx.RequestError as exc:
        raise typer.BadParameter(f"{provider} network failure; no data was written: {exc}") from exc
    except InvalidProviderResponse as exc:
        raise typer.BadParameter(f"{exc}; no data was written") from exc


def _expected_request_parameters(provider: str, topic: str, limit: int) -> dict:
    collectors = {
        "google-books": GoogleBooksCollector,
        "open-library": OpenLibraryCollector,
    }
    try:
        collector_class = collectors[provider]
    except KeyError as exc:
        raise typer.BadParameter(f"unsupported raw artifact provider: {provider}") from exc
    return collector_class.search_parameters(topic, max(limit * 4, limit))


def _normalize(
    payload: dict, provider: str, topic: str, limit: int, retrieved_at: datetime
) -> CanonicalDataset:
    if provider == "google-books":
        return normalize_google_books_response(
            payload, topic=topic, limit=limit, retrieved_at=retrieved_at
        )
    if provider == "open-library":
        return normalize_open_library_response(
            payload, topic=topic, limit=limit, retrieved_at=retrieved_at
        )
    raise typer.BadParameter("provider must be open-library or google-books")


@app.command()
def search(
    topic: TopicOption, limit: LimitOption = 5, provider: ProviderOption = "open-library"
) -> None:
    """Preview metadata candidates without writing data."""
    _ensure_topic(topic)
    payload, _request_parameters = _collect_payload(provider, topic, max(limit * 4, limit))
    candidates = []
    dataset = _normalize(payload, provider, topic, limit, datetime.now(UTC))
    for book in dataset.books:
        candidates.append(
            {
                "book_id": book.book_id,
                "title": book.title,
                "authors": book.authors,
                "published_year": book.published_year,
            }
        )
    typer.echo(json.dumps(candidates, ensure_ascii=False, indent=2))


@app.command()
def collect(
    topic: TopicOption,
    limit: LimitOption = 5,
    provider: ProviderOption = "open-library",
    data_dir: Annotated[Path, typer.Option(help="Raw and processed data root.")] = Path("data"),
) -> None:
    """Fetch one small response, preserve it, normalize it, and validate outputs."""
    _ensure_topic(topic)
    retrieved_at = datetime.now(UTC)
    candidate_limit = max(limit * 4, limit)
    payload, request_parameters = _collect_payload(
        provider,
        topic,
        candidate_limit,
        edition_detail_limit=min(limit + 3, candidate_limit),
    )
    artifact = RawArtifact(
        provider=provider,
        topic=topic,
        requested_limit=limit,
        retrieved_at=retrieved_at,
        request_parameters=request_parameters,
        response=payload,
    )
    raw_path = raw_artifact_path(data_dir, artifact)
    write_raw_response(artifact, raw_path)
    dataset = _normalize(payload, provider, topic, limit, retrieved_at)
    if len(dataset.books) < limit:
        typer.echo(
            f"Only {len(dataset.books)} eligible English records found; requested {limit}", err=True
        )
        raise typer.Exit(code=1)
    processed_directory = data_dir / "processed"
    try:
        if dataset_exists(processed_directory):
            existing = read_dataset(processed_directory)
            existing_errors = validate_dataset(existing)
            if existing_errors:
                raise DatasetMergeError(
                    "existing dataset is invalid: " + "; ".join(existing_errors)
                )
            dataset = merge_datasets([existing, dataset])
    except (DatasetMergeError, ValueError) as exc:
        typer.echo(f"ERROR canonical merge failed: {exc}", err=True)
        typer.echo(f"Raw response was preserved at: {raw_path}", err=True)
        raise typer.Exit(code=1) from exc

    errors = validate_dataset(dataset)
    if errors:
        for error in errors:
            typer.echo(f"ERROR {error}", err=True)
        raise typer.Exit(code=1)
    write_dataset(dataset, processed_directory)
    typer.echo(f"Raw response: {raw_path}")
    typer.echo(f"Canonical output: {processed_directory}")
    typer.echo(f"Books requested this run: {limit}")
    typer.echo(format_coverage(dataset))


@app.command()
def build(
    raw: Annotated[
        list[Path], typer.Option(exists=True, dir_okay=False, help="Repeat for each raw artifact.")
    ],
    output: Annotated[Path, typer.Option(help="Canonical output directory.")] = Path(
        "data/processed"
    ),
) -> None:
    """Rebuild canonical JSONL solely from preserved raw artifact metadata."""
    datasets = []
    requested_by_topic: dict[str, int] = {}
    for raw_path in raw:
        try:
            artifact = read_raw_response(raw_path)
        except ValueError as exc:
            raise typer.BadParameter(str(exc)) from exc
        _ensure_topic(artifact.topic)
        expected_parameters = _expected_request_parameters(
            artifact.provider, artifact.topic, artifact.requested_limit
        )
        if artifact.request_parameters != expected_parameters:
            raise typer.BadParameter(
                f"raw artifact topic/query mismatch or unsupported query shape: {raw_path}"
            )
        datasets.append(
            _normalize(
                artifact.response,
                artifact.provider,
                artifact.topic,
                artifact.requested_limit,
                retrieved_at=artifact.retrieved_at,
            )
        )
        requested_by_topic[artifact.topic] = max(
            requested_by_topic.get(artifact.topic, 0), artifact.requested_limit
        )
    try:
        dataset = merge_datasets(datasets)
    except DatasetMergeError as exc:
        raise typer.BadParameter(str(exc)) from exc
    errors = validate_dataset(dataset)
    if errors:
        raise typer.BadParameter("; ".join(errors))
    write_dataset(dataset, output)
    for topic, requested in sorted(requested_by_topic.items()):
        typer.echo(f"Books requested for {topic}: {requested}")
    typer.echo(format_coverage(dataset))


@app.command()
def report(
    data_dir: Annotated[Path, typer.Option(exists=True, file_okay=False)] = Path("data/processed"),
) -> None:
    """Report evidence coverage from canonical JSONL files."""
    dataset = read_dataset(data_dir)
    errors = validate_dataset(dataset)
    if errors:
        for error in errors:
            typer.echo(f"ERROR {error}", err=True)
        raise typer.Exit(code=1)
    typer.echo(format_coverage(dataset))


if __name__ == "__main__":
    app()
