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
from data_pipeline.collectors.open_textbooks import OpenTextbookCollector
from data_pipeline.collectors.public_book_pages import PublicBookPageCollector
from data_pipeline.collectors.publisher_documents import PublisherDocumentCollector
from data_pipeline.collectors.publisher_pages import PublisherPageCollector
from data_pipeline.datasets import DatasetMergeError, merge_datasets, without_books
from data_pipeline.models import CanonicalDataset
from data_pipeline.normalizers import (
    TOPICS,
    normalize_google_books_response,
    normalize_open_library_response,
    normalize_open_textbook_response,
    normalize_public_book_page_response,
    normalize_publisher_document_response,
    normalize_publisher_page_response,
)
from data_pipeline.open_textbook_sources import OPEN_TEXTBOOK_SOURCES, open_textbook_source
from data_pipeline.public_book_sources import PUBLIC_BOOK_SOURCES, public_book_source
from data_pipeline.publisher_document_sources import (
    PUBLISHER_DOCUMENT_SOURCES,
    publisher_document_source,
)
from data_pipeline.publisher_sources import PUBLISHER_SOURCES, publisher_source
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
PublisherSourceOption = Annotated[
    str, typer.Option(help="Reviewed exact-edition publisher source slug.")
]
PublicBookSourceOption = Annotated[
    str, typer.Option(help="Reviewed exact-edition public book page slug.")
]
PublisherDocumentSourceOption = Annotated[
    str, typer.Option(help="Reviewed exact-edition public publisher document slug.")
]
OpenTextbookSourceOption = Annotated[str, typer.Option(help="Reviewed public open textbook slug.")]


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
                    "work_details": collector.fetch_work_details(
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


def _collect_publisher_payload(source_slug: str) -> tuple[dict, dict]:
    try:
        with PublisherPageCollector() as collector:
            parameters = collector.request_parameters(source_slug)
            return collector.fetch(source_slug), parameters
    except InvalidProviderResponse as exc:
        raise typer.BadParameter(f"{exc}; no data was written") from exc
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    except httpx.HTTPStatusError as exc:
        raise typer.BadParameter(
            f"publisher page returned HTTP {exc.response.status_code}; no data was written"
        ) from exc
    except httpx.RequestError as exc:
        raise typer.BadParameter(
            f"publisher page network failure; no data was written: {exc}"
        ) from exc


def _collect_public_book_payload(source_slug: str) -> tuple[dict, dict]:
    try:
        with PublicBookPageCollector() as collector:
            parameters = collector.request_parameters(source_slug)
            return collector.fetch(source_slug), parameters
    except InvalidProviderResponse as exc:
        raise typer.BadParameter(f"{exc}; no data was written") from exc
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    except httpx.HTTPStatusError as exc:
        raise typer.BadParameter(
            f"public book page returned HTTP {exc.response.status_code}; no data was written"
        ) from exc
    except httpx.RequestError as exc:
        raise typer.BadParameter(
            f"public book page network failure; no data was written: {exc}"
        ) from exc


def _collect_publisher_document_payload(source_slug: str) -> tuple[dict, dict]:
    try:
        with PublisherDocumentCollector() as collector:
            parameters = collector.request_parameters(source_slug)
            return collector.fetch(source_slug), parameters
    except InvalidProviderResponse as exc:
        raise typer.BadParameter(f"{exc}; no data was written") from exc
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    except httpx.HTTPStatusError as exc:
        raise typer.BadParameter(
            f"publisher document returned HTTP {exc.response.status_code}; no data was written"
        ) from exc
    except httpx.RequestError as exc:
        raise typer.BadParameter(
            f"publisher document network failure; no data was written: {exc}"
        ) from exc


def _collect_open_textbook_payload(source_slug: str) -> tuple[dict, dict]:
    try:
        with OpenTextbookCollector() as collector:
            parameters = collector.request_parameters(source_slug)
            return collector.fetch(source_slug), parameters
    except InvalidProviderResponse as exc:
        raise typer.BadParameter(f"{exc}; no data was written") from exc
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    except httpx.HTTPStatusError as exc:
        raise typer.BadParameter(
            f"open textbook source returned HTTP {exc.response.status_code}; no data was written"
        ) from exc
    except httpx.RequestError as exc:
        raise typer.BadParameter(
            f"open textbook source network failure; no data was written: {exc}"
        ) from exc


def _expected_request_parameters(artifact: RawArtifact) -> dict:
    provider = artifact.provider
    topic = artifact.topic
    limit = artifact.requested_limit
    if provider == "open-textbook":
        if limit != 1:
            raise typer.BadParameter("open textbook raw artifact requested_limit must be 1")
        source_slug = artifact.request_parameters.get("source")
        if not isinstance(source_slug, str):
            raise typer.BadParameter("open textbook raw artifact is missing its source slug")
        try:
            return OpenTextbookCollector.request_parameters(source_slug)
        except ValueError as exc:
            raise typer.BadParameter(str(exc)) from exc
    if provider == "publisher-document":
        if limit != 1:
            raise typer.BadParameter("publisher document raw artifact requested_limit must be 1")
        source_slug = artifact.request_parameters.get("source")
        if not isinstance(source_slug, str):
            raise typer.BadParameter("publisher document raw artifact is missing its source slug")
        try:
            return PublisherDocumentCollector.request_parameters(source_slug)
        except ValueError as exc:
            raise typer.BadParameter(str(exc)) from exc
    if provider == "publisher-page":
        if limit != 1:
            raise typer.BadParameter("publisher raw artifact requested_limit must be 1")
        source_slug = artifact.request_parameters.get("source")
        if not isinstance(source_slug, str):
            raise typer.BadParameter("publisher raw artifact is missing its source slug")
        try:
            return PublisherPageCollector.request_parameters(source_slug)
        except ValueError as exc:
            raise typer.BadParameter(str(exc)) from exc
    if provider == "public-book-page":
        if limit != 1:
            raise typer.BadParameter("public book raw artifact requested_limit must be 1")
        source_slug = artifact.request_parameters.get("source")
        if not isinstance(source_slug, str):
            raise typer.BadParameter("public book raw artifact is missing its source slug")
        try:
            return PublicBookPageCollector.request_parameters(source_slug)
        except ValueError as exc:
            raise typer.BadParameter(str(exc)) from exc
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
    try:
        if provider == "google-books":
            return normalize_google_books_response(
                payload, topic=topic, limit=limit, retrieved_at=retrieved_at
            )
        if provider == "open-library":
            return normalize_open_library_response(
                payload, topic=topic, limit=limit, retrieved_at=retrieved_at
            )
        if provider == "publisher-page":
            return normalize_publisher_page_response(
                payload, topic=topic, retrieved_at=retrieved_at
            )
        if provider == "public-book-page":
            return normalize_public_book_page_response(
                payload, topic=topic, retrieved_at=retrieved_at
            )
        if provider == "publisher-document":
            return normalize_publisher_document_response(
                payload, topic=topic, retrieved_at=retrieved_at
            )
        if provider == "open-textbook":
            return normalize_open_textbook_response(payload, topic=topic, retrieved_at=retrieved_at)
        raise typer.BadParameter(
            "provider must be open-library, google-books, publisher-page, public-book-page, "
            "publisher-document, or open-textbook"
        )
    except InvalidProviderResponse as exc:
        raise typer.BadParameter(str(exc)) from exc


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


@app.command("collect-publisher")
def collect_publisher(
    source: PublisherSourceOption = "wiley-osc7",
    data_dir: Annotated[Path, typer.Option(help="Raw and processed data root.")] = Path("data"),
) -> None:
    """Collect one reviewed publisher page and merge its evidence into existing books."""
    try:
        source_spec = publisher_source(source)
    except ValueError as exc:
        choices = ", ".join(sorted(PUBLISHER_SOURCES))
        raise typer.BadParameter(f"source must be one of: {choices}") from exc

    retrieved_at = datetime.now(UTC)
    payload, request_parameters = _collect_publisher_payload(source)
    artifact = RawArtifact(
        provider="publisher-page",
        topic=source_spec.topic,
        requested_limit=1,
        retrieved_at=retrieved_at,
        request_parameters=request_parameters,
        response=payload,
    )
    raw_path = raw_artifact_path(data_dir, artifact)
    write_raw_response(artifact, raw_path)
    evidence = _normalize(
        payload, artifact.provider, artifact.topic, artifact.requested_limit, retrieved_at
    )
    processed_directory = data_dir / "processed"
    try:
        if not dataset_exists(processed_directory):
            raise DatasetMergeError(
                "publisher evidence requires an existing canonical metadata dataset"
            )
        existing = read_dataset(processed_directory)
        existing_errors = validate_dataset(existing)
        if existing_errors:
            raise DatasetMergeError("existing dataset is invalid: " + "; ".join(existing_errors))
        if source_spec.book_id not in {book.book_id for book in existing.books}:
            raise DatasetMergeError(
                f"publisher source target is absent from canonical books: {source_spec.book_id}"
            )
        dataset = merge_datasets([existing, evidence])
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
    typer.echo(f"Publisher TOC entries collected: {len(evidence.toc)}")
    typer.echo(format_coverage(dataset))


@app.command("collect-public-page")
def collect_public_page(
    source: PublicBookSourceOption = "ecampus-stallings-os4",
    data_dir: Annotated[Path, typer.Option(help="Raw and processed data root.")] = Path("data"),
) -> None:
    """Collect one reviewed public catalog page and merge its book evidence."""
    try:
        source_spec = public_book_source(source)
    except ValueError as exc:
        choices = ", ".join(sorted(PUBLIC_BOOK_SOURCES))
        raise typer.BadParameter(f"source must be one of: {choices}") from exc

    retrieved_at = datetime.now(UTC)
    payload, request_parameters = _collect_public_book_payload(source)
    artifact = RawArtifact(
        provider="public-book-page",
        topic=source_spec.topic,
        requested_limit=1,
        retrieved_at=retrieved_at,
        request_parameters=request_parameters,
        response=payload,
    )
    raw_path = raw_artifact_path(data_dir, artifact)
    write_raw_response(artifact, raw_path)
    evidence = _normalize(
        payload, artifact.provider, artifact.topic, artifact.requested_limit, retrieved_at
    )
    processed_directory = data_dir / "processed"
    try:
        if not dataset_exists(processed_directory):
            raise DatasetMergeError(
                "public book evidence requires an existing canonical metadata dataset"
            )
        existing = read_dataset(processed_directory)
        existing_errors = validate_dataset(existing)
        if existing_errors:
            raise DatasetMergeError("existing dataset is invalid: " + "; ".join(existing_errors))
        if source_spec.book_id not in {book.book_id for book in existing.books}:
            raise DatasetMergeError(
                f"public book source target is absent from canonical books: {source_spec.book_id}"
            )
        dataset = merge_datasets([existing, evidence])
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
    typer.echo(f"Public-page documents collected: {len(evidence.documents)}")
    typer.echo(f"Public-page TOC entries collected: {len(evidence.toc)}")
    typer.echo(format_coverage(dataset))


@app.command("collect-publisher-document")
def collect_publisher_document(
    source: PublisherDocumentSourceOption = "wiley-osc7-appendix-b",
    data_dir: Annotated[Path, typer.Option(help="Raw and processed data root.")] = Path("data"),
) -> None:
    """Collect one reviewed public publisher document and merge its extracted text."""
    try:
        source_spec = publisher_document_source(source)
    except ValueError as exc:
        choices = ", ".join(sorted(PUBLISHER_DOCUMENT_SOURCES))
        raise typer.BadParameter(f"source must be one of: {choices}") from exc

    retrieved_at = datetime.now(UTC)
    payload, request_parameters = _collect_publisher_document_payload(source)
    artifact = RawArtifact(
        provider="publisher-document",
        topic=source_spec.topic,
        requested_limit=1,
        retrieved_at=retrieved_at,
        request_parameters=request_parameters,
        response=payload,
    )
    raw_path = raw_artifact_path(data_dir, artifact)
    write_raw_response(artifact, raw_path)
    evidence = _normalize(
        payload, artifact.provider, artifact.topic, artifact.requested_limit, retrieved_at
    )
    processed_directory = data_dir / "processed"
    try:
        if not dataset_exists(processed_directory):
            raise DatasetMergeError(
                "publisher document evidence requires an existing canonical metadata dataset"
            )
        existing = read_dataset(processed_directory)
        existing_errors = validate_dataset(existing)
        if existing_errors:
            raise DatasetMergeError("existing dataset is invalid: " + "; ".join(existing_errors))
        if source_spec.book_id not in {book.book_id for book in existing.books}:
            raise DatasetMergeError(
                f"publisher document target is absent from canonical books: {source_spec.book_id}"
            )
        dataset = merge_datasets([existing, evidence])
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
    typer.echo(f"Publisher documents collected: {len(evidence.documents)}")
    typer.echo(format_coverage(dataset))


@app.command("collect-open-textbook")
def collect_open_textbook(
    source: OpenTextbookSourceOption = "ostep-1.10",
    data_dir: Annotated[Path, typer.Option(help="Raw and processed data root.")] = Path("data"),
) -> None:
    """Collect one reviewed open textbook and replace one weak MVP candidate."""
    try:
        source_spec = open_textbook_source(source)
    except ValueError as exc:
        choices = ", ".join(sorted(OPEN_TEXTBOOK_SOURCES))
        raise typer.BadParameter(f"source must be one of: {choices}") from exc

    retrieved_at = datetime.now(UTC)
    payload, request_parameters = _collect_open_textbook_payload(source)
    artifact = RawArtifact(
        provider="open-textbook",
        topic=source_spec.topic,
        requested_limit=1,
        retrieved_at=retrieved_at,
        request_parameters=request_parameters,
        response=payload,
    )
    raw_path = raw_artifact_path(data_dir, artifact)
    write_raw_response(artifact, raw_path)
    evidence = _normalize(
        payload, artifact.provider, artifact.topic, artifact.requested_limit, retrieved_at
    )
    processed_directory = data_dir / "processed"
    try:
        if not dataset_exists(processed_directory):
            raise DatasetMergeError(
                "open textbook collection requires an existing canonical metadata dataset"
            )
        existing = read_dataset(processed_directory)
        existing_errors = validate_dataset(existing)
        if existing_errors:
            raise DatasetMergeError("existing dataset is invalid: " + "; ".join(existing_errors))
        existing_book_ids = {book.book_id for book in existing.books}
        if not {source_spec.replaces_book_id, source_spec.book_id} & existing_book_ids:
            raise DatasetMergeError(
                "open textbook replacement target is absent from canonical books: "
                f"{source_spec.replaces_book_id}"
            )
        existing = without_books(existing, {source_spec.replaces_book_id})
        dataset = merge_datasets([existing, evidence])
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
    typer.echo(f"Replaced MVP book: {source_spec.replaces_book_id}")
    typer.echo(f"Open-textbook documents collected: {len(evidence.documents)}")
    typer.echo(f"Open-textbook TOC entries collected: {len(evidence.toc)}")
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
    replacement_book_ids: set[str] = set()
    requested_by_topic: dict[str, int] = {}
    for raw_path in raw:
        try:
            artifact = read_raw_response(raw_path)
        except ValueError as exc:
            raise typer.BadParameter(str(exc)) from exc
        _ensure_topic(artifact.topic)
        expected_parameters = _expected_request_parameters(artifact)
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
        if artifact.provider == "open-textbook":
            source_slug = artifact.request_parameters["source"]
            replacement_book_ids.add(open_textbook_source(source_slug).replaces_book_id)
        requested_by_topic[artifact.topic] = max(
            requested_by_topic.get(artifact.topic, 0), artifact.requested_limit
        )
    try:
        dataset = without_books(merge_datasets(datasets), replacement_book_ids)
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
