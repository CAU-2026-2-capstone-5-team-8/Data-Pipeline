"""Command-line entry point for the small MVP collection slice."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import httpx
import typer

from data_pipeline.collectors.google_books import GoogleBooksCollector
from data_pipeline.collectors.open_library import OpenLibraryCollector
from data_pipeline.normalizers import (
    TOPICS,
    normalize_google_books_response,
    normalize_open_library_response,
)
from data_pipeline.reporting import format_coverage
from data_pipeline.storage import (
    RawArtifact,
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


def _collect_payload(provider: str, topic: str, candidate_limit: int) -> dict:
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
            return collector.search_books(topic, candidate_limit=candidate_limit)
    except httpx.HTTPStatusError as exc:
        raise typer.BadParameter(
            f"{provider} returned HTTP {exc.response.status_code}; no data was written"
        ) from exc
    except httpx.RequestError as exc:
        raise typer.BadParameter(f"{provider} network failure; no data was written: {exc}") from exc


def _normalize(payload: dict, provider: str, topic: str, limit: int, retrieved_at: datetime):
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
    payload = _collect_payload(provider, topic, max(limit * 4, limit))
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
    payload = _collect_payload(provider, topic, max(limit * 4, limit))
    provider_directory = provider.replace("-", "_")
    raw_path = data_dir / "raw" / provider_directory / f"{topic}.json"
    write_raw_response(
        RawArtifact(provider=provider, retrieved_at=retrieved_at, response=payload), raw_path
    )
    dataset = _normalize(payload, provider, topic, limit, retrieved_at)
    if len(dataset.books) < limit:
        typer.echo(
            f"Only {len(dataset.books)} eligible English records found; requested {limit}", err=True
        )
        raise typer.Exit(code=1)
    errors = validate_dataset(dataset)
    if errors:
        for error in errors:
            typer.echo(f"ERROR {error}", err=True)
        raise typer.Exit(code=1)
    write_dataset(dataset, data_dir / "processed")
    typer.echo(f"Raw response: {raw_path}")
    typer.echo(f"Canonical output: {data_dir / 'processed'}")
    typer.echo(format_coverage(dataset))


@app.command()
def build(
    raw: Annotated[Path, typer.Option(exists=True, dir_okay=False)],
    topic: TopicOption,
    limit: LimitOption = 5,
    provider: ProviderOption = "open-library",
    output: Annotated[Path, typer.Option(help="Canonical output directory.")] = Path(
        "data/processed"
    ),
) -> None:
    """Rebuild canonical JSONL from a preserved raw response without network access."""
    _ensure_topic(topic)
    artifact = read_raw_response(raw)
    if artifact.provider != provider:
        raise typer.BadParameter(
            f"raw artifact provider is {artifact.provider}, but --provider is {provider}"
        )
    dataset = _normalize(
        artifact.response, provider, topic, limit, retrieved_at=artifact.retrieved_at
    )
    errors = validate_dataset(dataset)
    if errors:
        raise typer.BadParameter("; ".join(errors))
    write_dataset(dataset, output)
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
