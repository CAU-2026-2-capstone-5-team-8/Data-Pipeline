"""Command-line entry point for the small MVP collection slice."""

import json
import os
import re
import shutil
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter
from typing import Annotated, Any

import httpx
import typer
from dotenv import load_dotenv

from data_pipeline.api_toc import (
    normalize_springer_metadata_response,
    normalize_yes24_toc_response,
)
from data_pipeline.collectors.base import InvalidProviderResponse
from data_pipeline.collectors.google_books import GoogleBooksCollector
from data_pipeline.collectors.hathitrust import HathiTrustCollector
from data_pipeline.collectors.internet_archive import InternetArchiveCollector
from data_pipeline.collectors.open_library import OpenLibraryCollector
from data_pipeline.collectors.open_textbooks import OpenTextbookCollector
from data_pipeline.collectors.public_book_pages import PublicBookPageCollector
from data_pipeline.collectors.publisher_documents import PublisherDocumentCollector
from data_pipeline.collectors.publisher_pages import PublisherPageCollector
from data_pipeline.collectors.springer_metadata import (
    SpringerMetadataCollector,
    hyphenated_isbn,
)
from data_pipeline.collectors.yes24 import Yes24Collector
from data_pipeline.datasets import DatasetMergeError, merge_datasets, without_books
from data_pipeline.manifest import (
    load_manifest,
    select_manifest_raw_paths,
    validate_manifest_books,
)
from data_pipeline.ml_evidence import (
    export_ml_evidence,
    summarize_ml_evidence,
    validate_ml_evidence,
    write_ml_evidence,
    write_ml_evidence_summary,
)
from data_pipeline.models import Book, CanonicalDataset
from data_pipeline.normalizers import (
    TOPICS,
    normalize_google_books_response,
    normalize_hathitrust_response,
    normalize_internet_archive_response,
    normalize_open_library_response,
    normalize_open_textbook_response,
    normalize_public_book_page_response,
    normalize_publisher_document_response,
    normalize_publisher_page_response,
    normalize_yes24_response,
)
from data_pipeline.open_library_bulk import (
    build_targeted_open_library_index,
    canonical_toc_evidence,
    download_dump_file,
    load_dump_manifest,
    resolve_toc,
    verify_dump_file,
)
from data_pipeline.open_textbook_sources import OPEN_TEXTBOOK_SOURCES, open_textbook_source
from data_pipeline.public_book_sources import (
    PUBLIC_BOOK_SOURCES,
    public_book_source,
    public_book_source_id,
)
from data_pipeline.publisher_document_sources import (
    PUBLISHER_DOCUMENT_SOURCES,
    publisher_document_source,
)
from data_pipeline.publisher_sources import PUBLISHER_SOURCES, publisher_source
from data_pipeline.relevance_review import finalize_relevance_review, prepare_relevance_review
from data_pipeline.reporting import format_book_coverage, format_coverage
from data_pipeline.scale_comparison import compare_scale_reports
from data_pipeline.scale_reporting import create_scale_report, write_scale_artifacts
from data_pipeline.source_registry import config_path
from data_pipeline.storage import (
    RawArtifact,
    dataset_exists,
    raw_artifact_path,
    read_dataset,
    read_raw_response,
    write_dataset,
    write_raw_response,
)
from data_pipeline.toc_acquisition_report import build_toc_acquisition_report
from data_pipeline.validation import validate_dataset

load_dotenv()

app = typer.Typer(no_args_is_help=True, help="Collect and normalize public book evidence.")
TopicOption = Annotated[str, typer.Option(help="Configured leaf topic slug.")]
LimitOption = Annotated[int, typer.Option(min=1, max=100, help="Books to normalize.")]
ProviderOption = Annotated[
    str,
    typer.Option(help="Metadata provider: open-library, google-books, internet-archive, or yes24."),
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
ManifestOption = Annotated[
    Path, typer.Option(exists=True, dir_okay=False, help="Versioned dataset JSON manifest.")
]
DEFAULT_OPEN_LIBRARY_DUMP_MANIFEST = config_path("external", "open-library-2026-08-31.json")


def _ensure_topic(topic: str) -> None:
    if topic not in TOPICS:
        choices = ", ".join(sorted(TOPICS))
        raise typer.BadParameter(f"topic must be one of: {choices}")


def _metadata_candidate_limit(provider: str, requested_limit: int) -> int:
    """Choose provider-specific discovery depth for one requested result set."""
    return (
        requested_limit if provider == "google-books" else max(requested_limit * 4, requested_limit)
    )


def _collect_payload(
    provider: str,
    topic: str,
    candidate_limit: int,
    *,
    edition_detail_limit: int = 0,
) -> tuple[dict, dict]:
    """Collect one provider response together with its reproducible request plan."""
    collectors = {
        "google-books": GoogleBooksCollector,
        "open-library": OpenLibraryCollector,
        "internet-archive": InternetArchiveCollector,
        "yes24": Yes24Collector,
    }
    try:
        collector_class = collectors[provider]
    except KeyError as exc:
        raise typer.BadParameter(
            "provider must be open-library, google-books, internet-archive, or yes24"
        ) from exc
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
                    "collection_failures": getattr(collector, "detail_failures", []),
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


API_TOC_PROVIDERS = {"yes24": "YES24_API_KEY", "springer-metadata": "SPRINGER_API_KEY"}


def _api_toc_isbn(artifact: RawArtifact) -> str:
    """Return the ISBN-13 an API TOC raw artifact was looked up by."""
    parameters = artifact.request_parameters
    isbn_13 = parameters.get("query" if artifact.provider == "yes24" else "isbn")
    if not isinstance(isbn_13, str) or not re.fullmatch(r"[0-9]{13}", isbn_13):
        raise typer.BadParameter(f"{artifact.provider} raw artifact is missing its ISBN-13")
    return isbn_13


def _api_toc_target(dataset: CanonicalDataset, isbn_13: str) -> Book | None:
    """Return the canonical book for an ISBN-13 only while it still has no TOC."""
    book = next((b for b in dataset.books if b.isbn_13 == isbn_13), None)
    if book is None or any(entry.book_id == book.book_id for entry in dataset.toc):
        return None
    return book


def _with_api_toc(dataset: CanonicalDataset, additions: list[CanonicalDataset]) -> CanonicalDataset:
    return CanonicalDataset(
        books=dataset.books,
        documents=dataset.documents,
        toc=[*dataset.toc, *(entry for item in additions for entry in item.toc)],
        sources=[*dataset.sources, *(source for item in additions for source in item.sources)],
    )


def _expected_request_parameters(artifact: RawArtifact) -> dict:
    """Reconstruct the deterministic request identity recorded by one raw artifact."""
    provider = artifact.provider
    topic = artifact.topic
    limit = artifact.requested_limit
    if provider in API_TOC_PROVIDERS:
        if limit != 1:
            raise typer.BadParameter(f"{provider} raw artifact requested_limit must be 1")
        isbn_13 = _api_toc_isbn(artifact)
        if provider == "yes24":
            return Yes24Collector.request_parameters(isbn_13)
        return {"isbn": isbn_13, "q": f"isbn:{hyphenated_isbn(isbn_13)}"}
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
        "internet-archive": InternetArchiveCollector,
        "yes24": Yes24Collector,
    }
    try:
        collector_class = collectors[provider]
    except KeyError as exc:
        raise typer.BadParameter(f"unsupported raw artifact provider: {provider}") from exc
    return collector_class.search_parameters(topic, _metadata_candidate_limit(provider, limit))


def _validate_google_page_provenance(artifact: RawArtifact) -> None:
    """Require fetched Google pages to be an ordered, explainable prefix of the request plan."""
    if artifact.provider != "google-books" or "pages" not in artifact.response:
        return
    planned_pages = artifact.request_parameters.get("pages")
    fetched_pages = artifact.response.get("pages")
    if not isinstance(planned_pages, list) or not isinstance(fetched_pages, list):
        raise typer.BadParameter("paginated google-books raw artifact has invalid page lists")
    if not fetched_pages or len(fetched_pages) > len(planned_pages):
        raise typer.BadParameter("paginated google-books raw artifact has an invalid page count")
    for index, fetched_page in enumerate(fetched_pages):
        if not isinstance(fetched_page, dict):
            raise typer.BadParameter(
                f"paginated google-books raw artifact has invalid page {index}"
            )
        if fetched_page.get("request_parameters") != planned_pages[index]:
            raise typer.BadParameter(
                f"paginated google-books raw artifact page {index} request mismatch"
            )
    if len(fetched_pages) < len(planned_pages):
        last_page = fetched_pages[-1]
        response = last_page.get("response")
        items = response.get("items", []) if isinstance(response, dict) else None
        page_size = planned_pages[len(fetched_pages) - 1].get("maxResults")
        total_items = response.get("totalItems") if isinstance(response, dict) else None
        collected_count = sum(
            len(page.get("response", {}).get("items", []))
            for page in fetched_pages
            if isinstance(page, dict)
            and isinstance(page.get("response"), dict)
            and isinstance(page["response"].get("items", []), list)
        )
        reached_total = (
            isinstance(total_items, int)
            and not isinstance(total_items, bool)
            and total_items >= 0
            and collected_count >= total_items
        )
        total_requires_more = (
            isinstance(total_items, int)
            and not isinstance(total_items, bool)
            and total_items >= 0
            and collected_count < total_items
        )
        if (
            not isinstance(items, list)
            or not isinstance(page_size, int)
            or total_requires_more
            or (len(items) >= page_size and not reached_total)
        ):
            raise typer.BadParameter("google-books raw pages ended before plan was satisfied")


def _request_parameters_match(artifact: RawArtifact, expected: dict) -> bool:
    """Accept the current plan or the pre-pagination Google single-request identity."""
    if artifact.request_parameters == expected:
        return True
    if artifact.provider != "google-books" or "pages" in artifact.response:
        return False
    legacy_plan = GoogleBooksCollector.search_parameters(
        artifact.topic, max(artifact.requested_limit * 4, artifact.requested_limit)
    )
    legacy_parameters = dict(legacy_plan["pages"][0])
    legacy_parameters.pop("startIndex")
    return artifact.request_parameters == legacy_parameters


def _normalize(
    payload: dict,
    provider: str,
    topic: str,
    limit: int,
    retrieved_at: datetime,
    relevance_gate: str | None = None,
) -> CanonicalDataset:
    try:
        if provider == "google-books":
            return normalize_google_books_response(
                payload, topic=topic, limit=limit, retrieved_at=retrieved_at
            )
        if provider == "open-library":
            return normalize_open_library_response(
                payload,
                topic=topic,
                limit=limit,
                retrieved_at=retrieved_at,
                relevance_gate=relevance_gate,
            )
        if provider == "internet-archive":
            return normalize_internet_archive_response(
                payload, topic=topic, limit=limit, retrieved_at=retrieved_at
            )
        if provider == "yes24":
            return normalize_yes24_response(
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
            "provider must be open-library, google-books, internet-archive, yes24, "
            "publisher-page, public-book-page, publisher-document, or open-textbook"
        )
    except InvalidProviderResponse as exc:
        raise typer.BadParameter(str(exc)) from exc


def _dataset_from_raw_paths(
    raw_paths: list[Path],
    relevance_gate: str | None = None,
) -> tuple[CanonicalDataset, dict[str, int]]:
    """Normalize and merge preserved raw artifacts without publishing files."""
    datasets = []
    replacement_book_ids: set[str] = set()
    requested_by_topic: dict[str, int] = {}
    api_toc_artifacts: list[RawArtifact] = []
    for raw_path in raw_paths:
        try:
            artifact = read_raw_response(raw_path)
        except ValueError as exc:
            raise typer.BadParameter(str(exc)) from exc
        _ensure_topic(artifact.topic)
        expected_parameters = _expected_request_parameters(artifact)
        if not _request_parameters_match(artifact, expected_parameters):
            raise typer.BadParameter(
                f"raw artifact topic/query mismatch or unsupported query shape: {raw_path}"
            )
        if artifact.provider in API_TOC_PROVIDERS:
            api_toc_artifacts.append(artifact)
            continue
        _validate_google_page_provenance(artifact)
        normalization_args = (
            artifact.response,
            artifact.provider,
            artifact.topic,
            artifact.requested_limit,
        )
        evidence = (
            _normalize(*normalization_args, retrieved_at=artifact.retrieved_at)
            if relevance_gate is None
            else _normalize(
                *normalization_args,
                retrieved_at=artifact.retrieved_at,
                relevance_gate=relevance_gate,
            )
        )
        datasets.append(evidence)
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
    # API TOC lookups enrich books the metadata artifacts produced, so replay them last,
    # in the given (collection) order, under the same fill-only-missing rule as the command.
    for artifact in api_toc_artifacts:
        book = _api_toc_target(dataset, _api_toc_isbn(artifact))
        if book is None:
            continue
        try:
            evidence = _normalize_api_toc(
                artifact.provider, artifact.response, book, artifact.retrieved_at
            )
        except ValueError as exc:
            raise typer.BadParameter(str(exc)) from exc
        if evidence is not None:
            dataset = _with_api_toc(dataset, [evidence])
    return dataset, requested_by_topic


@app.command()
def search(
    topic: TopicOption, limit: LimitOption = 5, provider: ProviderOption = "open-library"
) -> None:
    """Preview metadata candidates without writing data."""
    _ensure_topic(topic)
    payload, _request_parameters = _collect_payload(
        provider, topic, _metadata_candidate_limit(provider, limit)
    )
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
    detail_limit: Annotated[
        int | None,
        typer.Option(
            min=1, max=100, help="Open Library detail candidate budget; default limit + 3."
        ),
    ] = None,
) -> None:
    """Fetch one small response, preserve it, normalize it, and validate outputs."""
    _ensure_topic(topic)
    if detail_limit is not None and provider != "open-library":
        raise typer.BadParameter("--detail-limit is only supported for open-library")
    retrieved_at = datetime.now(UTC)
    candidate_limit = _metadata_candidate_limit(provider, limit)
    payload, request_parameters = _collect_payload(
        provider,
        topic,
        candidate_limit,
        edition_detail_limit=min(
            detail_limit if detail_limit is not None else limit + 3, candidate_limit
        ),
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


@app.command("enrich-toc")
def enrich_toc(
    data_dir: Annotated[Path, typer.Option(help="Existing raw and processed data root.")] = Path(
        "data"
    ),
    max_sources: Annotated[int, typer.Option(min=1, max=20)] = 4,
    dry_run: Annotated[
        bool, typer.Option(help="Show exact-edition plan without fetching.")
    ] = False,
) -> None:
    """Fill missing TOCs using existing reviewed publisher/catalog sources only."""
    processed = data_dir / "processed"
    if not dataset_exists(processed):
        raise typer.BadParameter("enrich-toc requires an existing canonical dataset")
    original = read_dataset(processed)
    errors = validate_dataset(original)
    if errors:
        raise typer.BadParameter("; ".join(errors))
    books = {book.book_id: book for book in original.books}
    before = {entry.book_id for entry in original.toc}
    before_toc_sources = {
        book_id: sorted({entry.source_id for entry in original.toc if entry.book_id == book_id})
        for book_id in before
    }

    def source_needed(kind: str, spec: Any, dataset: CanonicalDataset) -> bool:
        entries = [entry for entry in dataset.toc if entry.book_id == spec.book_id]
        if not entries:
            return True
        if kind != "public-book-page" or not spec.preferred_toc:
            return False
        preferred_source_id = public_book_source_id(spec)
        return all(entry.source_id != preferred_source_id for entry in entries)

    plan = [
        (kind, spec)
        for kind, registry in (
            ("publisher-page", PUBLISHER_SOURCES),
            ("public-book-page", PUBLIC_BOOK_SOURCES),
        )
        for spec in sorted(registry.values(), key=lambda item: item.slug)
        if spec.book_id in books
        and spec.topic in books[spec.book_id].topics
        and source_needed(kind, spec, original)
    ]
    if dry_run:
        typer.echo(
            json.dumps(
                [
                    {"provider": kind, "source": spec.slug, "book_id": spec.book_id}
                    for kind, spec in plan[:max_sources]
                ],
                indent=2,
            )
        )
        return

    attempts = []
    for kind, spec in plan:
        if len(attempts) >= max_sources:
            break
        current = read_dataset(processed)
        if not source_needed(kind, spec, current):
            continue
        attempt = {"provider": kind, "source": spec.slug, "book_id": spec.book_id}
        try:
            if kind == "publisher-page":
                collect_publisher(source=spec.slug, data_dir=data_dir)
            else:
                collect_public_page(source=spec.slug, data_dir=data_dir)
        except (typer.BadParameter, typer.Exit, ValueError) as exc:
            attempt.update(status="failed", error=str(exc) or type(exc).__name__)
        else:
            attempt["status"] = "collected"
        attempts.append(attempt)

    final = read_dataset(processed)
    after = {entry.book_id for entry in final.toc}
    after_toc_sources = {
        book_id: sorted({entry.source_id for entry in final.toc if entry.book_id == book_id})
        for book_id in after
    }
    report = {
        "retrieved_at": datetime.now(UTC).isoformat(),
        "book_count": len(books),
        "toc_books_before": len(before),
        "toc_books_after": len(after),
        "toc_entries_before": len(original.toc),
        "toc_entries_after": len(final.toc),
        "added_book_ids": sorted(after - before),
        "replaced_book_ids": sorted(
            book_id
            for book_id in before & after
            if before_toc_sources[book_id] != after_toc_sources[book_id]
        ),
        "remaining_book_ids": sorted(set(books) - after),
        "eligible_source_count": len(plan),
        "max_sources": max_sources,
        "attempts": attempts,
    }
    report_path = data_dir / "reports" / "toc-enrichment.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    typer.echo(f"TOC coverage: {len(before)}/{len(books)} -> {len(after)}/{len(books)}")
    typer.echo(f"Enrichment report: {report_path}")
    if any(attempt["status"] == "failed" for attempt in attempts):
        raise typer.Exit(code=1)


@app.command("enrich-bibliography")
def enrich_bibliography(
    isbn: Annotated[str, typer.Option(help="ISBN-10 or ISBN-13 of an existing canonical book.")],
    data_dir: Annotated[Path, typer.Option(help="Existing raw and processed data root.")] = Path(
        "data"
    ),
) -> None:
    """Add one corroborating HathiTrust bibliographic Source to an existing book.

    HathiTrust's free Bibliographic API has no topic search and returns no item
    text or table of contents, so it cannot discover books the way collect does.
    It can only confirm/cross-reference a book that is already in the canonical
    dataset, by exact ISBN.
    """
    processed = data_dir / "processed"
    if not dataset_exists(processed):
        raise typer.BadParameter("enrich-bibliography requires an existing canonical dataset")
    dataset = read_dataset(processed)
    errors = validate_dataset(dataset)
    if errors:
        raise typer.BadParameter("; ".join(errors))

    normalized_isbn = re.sub(r"[^0-9Xx]", "", isbn).upper()
    book = next(
        (b for b in dataset.books if normalized_isbn in {b.isbn_10, b.isbn_13}),
        None,
    )
    if book is None:
        raise typer.BadParameter(f"no canonical book has ISBN {isbn}")
    if any(
        source.book_id == book.book_id and source.provider == "hathitrust"
        for source in dataset.sources
    ):
        typer.echo(f"HathiTrust source already recorded for {book.book_id}")
        return

    retrieved_at = datetime.now(UTC)
    try:
        with HathiTrustCollector() as collector:
            payload = collector.lookup_isbn(normalized_isbn)
    except InvalidProviderResponse as exc:
        raise typer.BadParameter(f"{exc}; no data was written") from exc
    except httpx.HTTPStatusError as exc:
        raise typer.BadParameter(
            f"hathitrust returned HTTP {exc.response.status_code}; no data was written"
        ) from exc
    except httpx.RequestError as exc:
        raise typer.BadParameter(f"hathitrust network failure; no data was written: {exc}") from exc

    artifact = RawArtifact(
        provider="hathitrust",
        topic=book.topics[-1],
        requested_limit=1,
        retrieved_at=retrieved_at,
        request_parameters={"isbn": normalized_isbn},
        response=payload,
    )
    raw_path = raw_artifact_path(data_dir, artifact)
    write_raw_response(artifact, raw_path)

    try:
        source = normalize_hathitrust_response(
            payload, isbn=normalized_isbn, book_id=book.book_id, retrieved_at=retrieved_at
        )
    except InvalidProviderResponse as exc:
        raise typer.BadParameter(f"{exc}; raw response was preserved at: {raw_path}") from exc
    if source is None:
        typer.echo(f"HathiTrust has no record for ISBN {isbn}")
        typer.echo(f"Raw response was preserved at: {raw_path}")
        raise typer.Exit(code=1)

    updated = CanonicalDataset(
        books=dataset.books,
        documents=dataset.documents,
        toc=dataset.toc,
        sources=[*dataset.sources, source],
    )
    errors = validate_dataset(updated)
    if errors:
        for error in errors:
            typer.echo(f"ERROR {error}", err=True)
        raise typer.Exit(code=1)
    write_dataset(updated, processed)
    typer.echo(f"HathiTrust source added for {book.book_id}: {source.url}")
    typer.echo(source.rights_note or "")


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
    dataset, requested_by_topic = _dataset_from_raw_paths(raw)
    errors = validate_dataset(dataset)
    if errors:
        raise typer.BadParameter("; ".join(errors))
    write_dataset(dataset, output)
    for topic, requested in sorted(requested_by_topic.items()):
        typer.echo(f"Books requested for {topic}: {requested}")
    typer.echo(format_coverage(dataset))


@app.command("build-manifest")
def build_manifest(
    manifest: ManifestOption = Path("configs/mvp.json"),
    data_dir: Annotated[Path, typer.Option(file_okay=False, help="Raw data root.")] = Path("data"),
    output: Annotated[
        Path | None, typer.Option(file_okay=False, help="Canonical output directory.")
    ] = None,
) -> None:
    """Rebuild and verify an exact book set from the latest matching raw artifacts."""
    try:
        manifest_spec = load_manifest(manifest)
        raw_paths = select_manifest_raw_paths(manifest_spec, data_dir / "raw")
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    dataset, requested_by_topic = (
        _dataset_from_raw_paths(raw_paths)
        if manifest_spec.relevance_gate is None
        else _dataset_from_raw_paths(raw_paths, manifest_spec.relevance_gate)
    )
    errors = [*validate_dataset(dataset), *validate_manifest_books(manifest_spec, dataset)]
    if errors:
        raise typer.BadParameter("; ".join(errors))

    output_directory = output or data_dir / "processed"
    write_dataset(dataset, output_directory)
    typer.echo(f"Manifest: {manifest}")
    for raw_path in raw_paths:
        typer.echo(f"Selected raw artifact: {raw_path}")
    typer.echo(f"Canonical output: {output_directory}")
    for topic, requested in sorted(requested_by_topic.items()):
        typer.echo(f"Books requested for {topic}: {requested}")
    typer.echo(format_coverage(dataset))
    typer.echo("\nPer-book evidence\n" + format_book_coverage(dataset))


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
    typer.echo("\nPer-book evidence\n" + format_book_coverage(dataset))


@app.command("report-scale")
def report_scale(
    manifest: ManifestOption = Path("configs/experiments/scale-50.json"),
    data_dir: Annotated[Path, typer.Option(file_okay=False, help="Experiment data root.")] = Path(
        "data/experiments/scale-50"
    ),
    output: Annotated[
        Path | None, typer.Option(file_okay=False, help="Report and audit output directory.")
    ] = None,
) -> None:
    """Rebuild twice and emit detailed scale metrics plus a blank human-audit CSV."""
    try:
        manifest_spec = load_manifest(manifest)
        unsupported = [
            selector.provider
            for selector in manifest_spec.raw_artifacts
            if selector.provider not in {"open-library", "google-books"}
        ]
        if unsupported:
            raise ValueError(
                "scale report accepts generic metadata providers only: "
                + ", ".join(sorted(set(unsupported)))
            )
        raw_paths = select_manifest_raw_paths(manifest_spec, data_dir / "raw")
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc

    started = perf_counter()
    first_dataset, _requested = _dataset_from_raw_paths(raw_paths, manifest_spec.relevance_gate)
    second_dataset, _requested_again = _dataset_from_raw_paths(
        raw_paths, manifest_spec.relevance_gate
    )
    build_seconds = perf_counter() - started
    errors = [
        *validate_dataset(first_dataset),
        *validate_manifest_books(manifest_spec, first_dataset),
        *validate_dataset(second_dataset),
        *validate_manifest_books(manifest_spec, second_dataset),
    ]
    if errors:
        raise typer.BadParameter("; ".join(errors))

    filenames = ("books.jsonl", "documents.jsonl", "toc.jsonl", "sources.jsonl")
    with (
        TemporaryDirectory(prefix="scale-rebuild-a-") as first_temp,
        TemporaryDirectory(prefix="scale-rebuild-b-") as second_temp,
    ):
        first_directory = Path(first_temp)
        second_directory = Path(second_temp)
        write_dataset(first_dataset, first_directory)
        write_dataset(second_dataset, second_directory)
        deterministic = all(
            (first_directory / filename).read_bytes() == (second_directory / filename).read_bytes()
            for filename in filenames
        )
        canonical_bytes = sum((first_directory / filename).stat().st_size for filename in filenames)
    if not deterministic:
        raise typer.BadParameter("same raw manifest produced different canonical bytes")

    report_data = create_scale_report(
        manifest=manifest_spec,
        dataset=first_dataset,
        raw_paths=raw_paths,
        deterministic_rebuild=deterministic,
        build_seconds=build_seconds,
        canonical_bytes=canonical_bytes,
    )
    report_path, audit_path = write_scale_artifacts(
        report_data, first_dataset, output or data_dir / "reports"
    )
    discovery = report_data["discovery_normalization"]
    coverage = report_data["evidence_coverage"]["overall"]
    typer.echo(f"Scale report: {report_path}")
    typer.echo(f"Human audit CSV: {audit_path}")
    typer.echo(
        "Candidates / selected / normalized: "
        f"{discovery['candidate_count']} / {discovery['selected_book_count']} / "
        f"{discovery['successfully_normalized_book_count']}"
    )
    typer.echo(
        "Evidence books — description / TOC / preface / introduction / preview / sample: "
        f"{coverage['description']} / {coverage['toc']} / {coverage['preface']} / "
        f"{coverage['introduction']} / {coverage['preview']} / {coverage['sample_chapter']}"
    )
    typer.echo(f"Offline rebuild byte-identical: {deterministic}")


@app.command("compare-scale")
def compare_scale(
    v1_report: Annotated[Path, typer.Option(exists=True, dir_okay=False)],
    v2_report: Annotated[Path, typer.Option(exists=True, dir_okay=False)],
    v1_audit: Annotated[Path, typer.Option(exists=True, dir_okay=False)],
    v2_audit: Annotated[Path, typer.Option(exists=True, dir_okay=False)],
) -> None:
    """Compare selected identities; show precision only after complete human audit."""
    try:
        comparison = compare_scale_reports(v1_report, v2_report, v1_audit, v2_audit)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(json.dumps(comparison, ensure_ascii=False, indent=2, sort_keys=True))


@app.command("prepare-relevance-review")
def prepare_relevance_review_command(
    v1_report: Annotated[Path, typer.Option(exists=True, dir_okay=False)],
    v2_report: Annotated[Path, typer.Option(exists=True, dir_okay=False)],
    v1_audit: Annotated[Path, typer.Option(exists=True, dir_okay=False)],
    v2_audit: Annotated[Path, typer.Option(exists=True, dir_okay=False)],
    output: Annotated[Path, typer.Option(dir_okay=False)],
) -> None:
    """Prepare one blank human review row per book across both scale selections."""
    try:
        counts = prepare_relevance_review(v1_report, v2_report, v1_audit, v2_audit, output)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(f"Human relevance review: {output}")
    typer.echo(json.dumps(counts, sort_keys=True))


@app.command("finalize-relevance-review")
def finalize_relevance_review_command(
    v1_report: Annotated[Path, typer.Option(exists=True, dir_okay=False)],
    v2_report: Annotated[Path, typer.Option(exists=True, dir_okay=False)],
    v1_audit: Annotated[Path, typer.Option(exists=True, dir_okay=False)],
    v2_audit: Annotated[Path, typer.Option(exists=True, dir_okay=False)],
    review: Annotated[Path, typer.Option(exists=True, dir_okay=False)],
    v1_output: Annotated[Path, typer.Option(dir_okay=False)],
    v2_output: Annotated[Path, typer.Option(dir_okay=False)],
) -> None:
    """Split a complete human review into two compare-scale audit inputs."""
    try:
        finalize_relevance_review(
            v1_report, v2_report, v1_audit, v2_audit, review, v1_output, v2_output
        )
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(f"Reviewed v1 audit: {v1_output}")
    typer.echo(f"Reviewed v2 audit: {v2_output}")


@app.command("bulk-status")
def bulk_status(
    manifest_path: Annotated[
        Path, typer.Option(exists=True, dir_okay=False, help="Pinned external dump manifest.")
    ] = DEFAULT_OPEN_LIBRARY_DUMP_MANIFEST,
    data_dir: Annotated[Path, typer.Option(help="External data and index root.")] = Path("data"),
    verify: Annotated[
        bool, typer.Option(help="Hash complete local files; this can take several minutes.")
    ] = False,
) -> None:
    """Show pinned Open Library inputs without downloading anything."""
    manifest = load_dump_manifest(manifest_path)
    external = data_dir / "external" / "open_library" / manifest.dump_date
    rows = []
    for specification in manifest.files:
        path = external / specification.filename
        partial = path.with_suffix(path.suffix + ".part")
        if path.exists():
            errors = verify_dump_file(path, specification) if verify else []
            status = "invalid" if errors else ("verified" if verify else "present_unverified")
        elif partial.exists():
            errors = []
            status = "partial"
        else:
            errors = []
            status = "missing"
        rows.append(
            {
                "kind": specification.kind,
                "dump_date": manifest.dump_date,
                "path": str(path),
                "expected_bytes": specification.compressed_size,
                "local_bytes": path.stat().st_size
                if path.exists()
                else partial.stat().st_size
                if partial.exists()
                else 0,
                "status": status,
                "errors": errors,
            }
        )
    typer.echo(json.dumps(rows, indent=2, sort_keys=True))


@app.command("fetch-open-library-dump")
def fetch_open_library_dump(
    kind: Annotated[
        str, typer.Option(help="Pinned dump to fetch: editions, works, or all.")
    ] = "editions",
    manifest_path: Annotated[
        Path, typer.Option(exists=True, dir_okay=False, help="Pinned external dump manifest.")
    ] = DEFAULT_OPEN_LIBRARY_DUMP_MANIFEST,
    data_dir: Annotated[Path, typer.Option(help="External data and index root.")] = Path("data"),
    accept_large_download: Annotated[
        bool,
        typer.Option(help="Required acknowledgement for the multi-GB public dataset download."),
    ] = False,
) -> None:
    """Fetch pinned dumps with range resume, checksum, and atomic publication."""
    if kind not in {"editions", "works", "all"}:
        raise typer.BadParameter("kind must be editions, works, or all")
    if not accept_large_download:
        raise typer.BadParameter("--accept-large-download is required")
    manifest = load_dump_manifest(manifest_path)
    selected = [item for item in manifest.files if kind == "all" or item.kind == kind]
    external = data_dir / "external" / "open_library" / manifest.dump_date
    missing_bytes = 0
    for specification in selected:
        final_path = external / specification.filename
        partial_path = final_path.with_suffix(final_path.suffix + ".part")
        if final_path.exists():
            continue
        partial_size = partial_path.stat().st_size if partial_path.exists() else 0
        missing_bytes += max(specification.compressed_size - partial_size, 0)
    free_bytes = shutil.disk_usage(data_dir if data_dir.exists() else Path(".")).free
    safety_margin = 2 * 1024**3
    if free_bytes < missing_bytes + safety_margin:
        raise typer.BadParameter(
            "insufficient free space for pinned downloads plus a 2 GiB safety margin"
        )
    results = {}
    for specification in selected:
        results[specification.kind] = download_dump_file(specification, external)
    typer.echo(json.dumps(results, indent=2, sort_keys=True))


@app.command("build-open-library-target-index")
def build_open_library_target_index(
    dataset_dir: Annotated[
        Path,
        typer.Option(
            exists=True,
            file_okay=False,
            help="Canonical benchmark directory containing books.jsonl.",
        ),
    ],
    manifest_path: Annotated[
        Path, typer.Option(exists=True, dir_okay=False, help="Pinned external dump manifest.")
    ] = DEFAULT_OPEN_LIBRARY_DUMP_MANIFEST,
    data_dir: Annotated[Path, typer.Option(help="External data and index root.")] = Path("data"),
) -> None:
    """Build a small two-pass Edition index for canonical benchmark ISBNs."""
    dataset = read_dataset(dataset_dir)
    errors = validate_dataset(dataset)
    if errors:
        raise typer.BadParameter("; ".join(errors))
    target_isbns = {
        isbn for book in dataset.books for isbn in (book.isbn_10, book.isbn_13) if isbn is not None
    }
    manifest = load_dump_manifest(manifest_path)
    edition_spec = next(item for item in manifest.files if item.kind == "editions")
    edition_path = (
        data_dir / "external" / "open_library" / manifest.dump_date / edition_spec.filename
    )
    # Downloads are checksum-verified before atomic publication. Avoid a redundant
    # 12+ GB hash pass here; both streaming passes still validate the gzip CRC.
    verification_errors = verify_dump_file(edition_path, edition_spec, checksum=False)
    if verification_errors:
        raise typer.BadParameter(f"editions dump is not ready: {', '.join(verification_errors)}")
    output = data_dir / "indexes" / "open_library" / f"scale-targets-{manifest.dump_date}.sqlite"
    started = perf_counter()
    counts = build_targeted_open_library_index(
        editions_dump=edition_path,
        output_path=output,
        manifest=manifest,
        target_isbns=target_isbns,
    )
    counts["build_seconds"] = round(perf_counter() - started, 3)
    counts["index_bytes"] = output.stat().st_size
    typer.echo(f"Open Library targeted index: {output}")
    typer.echo(json.dumps(counts, indent=2, sort_keys=True))


@app.command("inspect-open-library-index")
def inspect_open_library_index(
    isbn: Annotated[str, typer.Option(help="Target ISBN-10 or ISBN-13.")],
    index: Annotated[Path, typer.Option(exists=True, dir_okay=False)],
) -> None:
    """Inspect an exact/alternate TOC resolution without changing canonical data."""
    resolution = resolve_toc(index, isbn)
    typer.echo(
        json.dumps(asdict(resolution) if resolution is not None else None, indent=2, sort_keys=True)
    )


@app.command("enrich-open-library-bulk")
def enrich_open_library_bulk(
    dataset_dir: Annotated[
        Path,
        typer.Option(
            exists=True,
            file_okay=False,
            help="Canonical dataset to enrich only where TOC evidence is missing.",
        ),
    ],
    index: Annotated[
        Path, typer.Option(exists=True, dir_okay=False, help="Targeted Open Library SQLite index.")
    ],
    manifest_path: Annotated[
        Path, typer.Option(exists=True, dir_okay=False, help="Pinned external dump manifest.")
    ] = DEFAULT_OPEN_LIBRARY_DUMP_MANIFEST,
) -> None:
    """Merge exact/same-Work bulk TOCs into missing canonical books."""
    original = read_dataset(dataset_dir)
    errors = validate_dataset(original)
    if errors:
        raise typer.BadParameter("; ".join(errors))
    manifest = load_dump_manifest(manifest_path)
    retrieved_at = datetime.fromisoformat(manifest.dump_date).replace(tzinfo=UTC)
    existing_toc_books = {entry.book_id for entry in original.toc}
    result = original
    additions = []
    for book in original.books:
        if book.book_id in existing_toc_books:
            continue
        isbn = book.isbn_13 or book.isbn_10
        if isbn is None:
            continue
        resolution = resolve_toc(index, isbn)
        if resolution is None:
            continue
        evidence = canonical_toc_evidence(
            resolution,
            target_book=book,
            retrieved_at=retrieved_at,
            dump_date=manifest.dump_date,
        )
        result = merge_datasets([result, evidence])
        additions.append(
            {
                "book_id": book.book_id,
                "target_isbn": isbn,
                "tier": resolution.tier,
                "source_edition": resolution.source_edition_key,
                "source_isbns": list(resolution.source_isbns),
                "toc_entries": len(evidence.toc),
            }
        )
    errors = validate_dataset(result)
    if errors:
        raise typer.BadParameter("; ".join(errors))
    write_dataset(result, dataset_dir)
    total_books = len(original.books)
    report_path = dataset_dir.parent / "reports" / "open-library-bulk-enrichment.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "dump_date": manifest.dump_date,
                "index": str(index),
                "before_toc_books": len(existing_toc_books),
                "after_toc_books": len({entry.book_id for entry in result.toc}),
                "additions": additions,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    typer.echo(f"Canonical output: {dataset_dir}")
    typer.echo(
        f"Open Library bulk enrichment: {len(existing_toc_books)}/{total_books} -> "
        f"{len({entry.book_id for entry in result.toc})}/{total_books}"
    )
    typer.echo(f"Enrichment report: {report_path}")


@app.command("report-toc-acquisition")
def report_toc_acquisition(
    baseline_dir: Annotated[Path, typer.Option(exists=True, file_okay=False)],
    final_dir: Annotated[Path, typer.Option(exists=True, file_okay=False)],
    index: Annotated[Path, typer.Option(exists=True, dir_okay=False)],
    loc_result: Annotated[Path, typer.Option(exists=True, dir_okay=False)],
    experiment: Annotated[Path, typer.Option(exists=True, dir_okay=False)] = Path(
        "configs/experiments/scale-50-toc-acquisition.json"
    ),
    output: Annotated[Path, typer.Option(dir_okay=False)] = Path(
        "docs/experiments/scale-50-toc-acquisition-2026-09-22.json"
    ),
) -> None:
    """Write a unique-gain Scale-50 TOC acquisition report."""
    try:
        result = build_toc_acquisition_report(
            baseline_dir=baseline_dir,
            final_dir=final_dir,
            index_path=index,
            loc_result_path=loc_result,
            experiment_path=experiment,
        )
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    typer.echo(json.dumps(result["coverage"], indent=2, sort_keys=True))
    typer.echo(f"TOC acquisition report: {output}")


@app.command("export-ml-evidence")
def export_ml_evidence_command(
    dataset_dir: Annotated[
        Path,
        typer.Option(
            exists=True,
            file_okay=False,
            help="Validated canonical dataset directory.",
        ),
    ] = Path("data/processed"),
    output: Annotated[
        Path,
        typer.Option(dir_okay=False, help="One-book-per-line ML evidence artifact."),
    ] = Path("data/exports/ml-evidence-v1/book-evidence.jsonl"),
    report: Annotated[
        Path | None,
        typer.Option(dir_okay=False, help="Coverage and evidence-type summary JSON."),
    ] = None,
) -> None:
    """Export deterministic evidence without assigning ML confidence or weights."""
    canonical = read_dataset(dataset_dir)
    canonical_errors = validate_dataset(canonical)
    if canonical_errors:
        raise typer.BadParameter("; ".join(canonical_errors))

    records = export_ml_evidence(canonical)
    evidence_errors = validate_ml_evidence(records, canonical)
    summary = summarize_ml_evidence(records, evidence_errors)
    if evidence_errors:
        raise typer.BadParameter("; ".join(evidence_errors))

    report_path = report or output.with_name("summary.json")
    if output.resolve() == report_path.resolve():
        raise typer.BadParameter("--output and --report must be different paths")
    write_ml_evidence(records, output)
    write_ml_evidence_summary(summary, report_path)
    typer.echo(json.dumps(summary, indent=2, sort_keys=True))
    typer.echo(f"ML evidence artifact: {output}")
    typer.echo(f"ML evidence summary: {report_path}")


def _fetch_api_toc(provider: str, collector: Any, book: Book) -> tuple[dict, dict]:
    """Return (request parameters, raw response) for one ISBN-keyed API TOC lookup."""
    isbn_13 = book.isbn_13 or ""
    if provider == "yes24":
        return collector.request_parameters(isbn_13), collector.fetch_toc(isbn_13)
    payload = collector.fetch_chapters(isbn_13)
    return {"isbn": isbn_13, "q": payload["query"]}, payload


def _normalize_api_toc(
    provider: str, payload: dict, book: Book, retrieved_at: datetime
) -> CanonicalDataset | None:
    if provider == "yes24":
        return normalize_yes24_toc_response(payload, book=book, retrieved_at=retrieved_at)
    return normalize_springer_metadata_response(payload, book=book, retrieved_at=retrieved_at)


@app.command("enrich-api-toc")
def enrich_api_toc(
    provider: Annotated[str, typer.Option(help="TOC API provider: yes24 or springer-metadata.")],
    isbn: Annotated[
        str | None, typer.Option(help="Only this canonical book (ISBN-10 or ISBN-13).")
    ] = None,
    data_dir: Annotated[Path, typer.Option(help="Existing raw and processed data root.")] = Path(
        "data"
    ),
    max_books: Annotated[int, typer.Option(min=1, max=200)] = 50,
) -> None:
    """Fill missing TOCs by exact ISBN-13 lookup in the YES24 or Springer Nature API.

    Never discovers new books and never replaces an existing TOC. The API key is read
    from YES24_API_KEY or SPRINGER_API_KEY and is never written to raw artifacts.
    """
    if provider not in API_TOC_PROVIDERS:
        raise typer.BadParameter("provider must be yes24 or springer-metadata")
    api_key = os.environ.get(API_TOC_PROVIDERS[provider], "")
    if not api_key:
        raise typer.BadParameter(f"{API_TOC_PROVIDERS[provider]} is not set")
    processed = data_dir / "processed"
    if not dataset_exists(processed):
        raise typer.BadParameter("enrich-api-toc requires an existing canonical dataset")
    dataset = read_dataset(processed)
    errors = validate_dataset(dataset)
    if errors:
        raise typer.BadParameter("; ".join(errors))

    with_toc = {entry.book_id for entry in dataset.toc}
    if isbn is not None:
        normalized_isbn = re.sub(r"[^0-9Xx]", "", isbn).upper()
        targets = [b for b in dataset.books if normalized_isbn in {b.isbn_10, b.isbn_13}]
        if not targets:
            raise typer.BadParameter(f"no canonical book has ISBN {isbn}")
    else:
        targets = sorted(dataset.books, key=lambda b: b.book_id)
    targets = [b for b in targets if b.book_id not in with_toc and b.isbn_13][:max_books]
    if not targets:
        typer.echo("No selected book is missing a TOC with an ISBN-13; nothing to do.")
        return

    collector_class = Yes24Collector if provider == "yes24" else SpringerMetadataCollector
    additions: list[CanonicalDataset] = []
    attempts: list[dict[str, Any]] = []
    with collector_class(api_key) as collector:
        for book in targets:
            attempt: dict[str, Any] = {"book_id": book.book_id, "isbn_13": book.isbn_13}
            retrieved_at = datetime.now(UTC)
            try:
                parameters, payload = _fetch_api_toc(provider, collector, book)
            except httpx.HTTPStatusError as exc:
                error = f"HTTP {exc.response.status_code}"
                attempts.append({**attempt, "status": "failed", "error": error})
                continue
            except httpx.RequestError as exc:
                attempts.append({**attempt, "status": "failed", "error": f"network: {exc}"})
                continue
            except ValueError as exc:
                attempts.append({**attempt, "status": "failed", "error": str(exc)})
                continue
            artifact = RawArtifact(
                provider=provider,
                topic=book.topics[-1],
                requested_limit=1,
                retrieved_at=retrieved_at,
                request_parameters=parameters,
                response=payload,
            )
            raw_path = raw_artifact_path(data_dir, artifact)
            write_raw_response(artifact, raw_path)
            attempt["raw_path"] = raw_path.as_posix()
            try:
                evidence = _normalize_api_toc(provider, payload, book, retrieved_at)
            except ValueError as exc:
                attempts.append({**attempt, "status": "failed", "error": str(exc)})
                continue
            if evidence is None:
                attempts.append({**attempt, "status": "no_toc"})
                continue
            additions.append(evidence)
            attempts.append({**attempt, "status": "added", "toc_entries": len(evidence.toc)})

    updated = _with_api_toc(dataset, additions)
    errors = validate_dataset(updated)
    if errors:
        for error in errors:
            typer.echo(f"ERROR {error}", err=True)
        raise typer.Exit(code=1)
    if additions:
        write_dataset(updated, processed)

    after = {entry.book_id for entry in updated.toc}
    counts: dict[str, int] = {}
    for attempt in attempts:
        counts[attempt["status"]] = counts.get(attempt["status"], 0) + 1
    report = {
        "provider": provider,
        "retrieved_at": datetime.now(UTC).isoformat(),
        "book_count": len(dataset.books),
        "toc_books_before": len(with_toc),
        "toc_books_after": len(after),
        "status_counts": counts,
        "added_book_ids": sorted(after - with_toc),
        "attempts": attempts,
    }
    report_path = data_dir / "reports" / f"api-toc-enrichment-{provider}.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    typer.echo(
        f"{provider} TOC coverage: {len(with_toc)}/{len(dataset.books)} -> "
        f"{len(after)}/{len(dataset.books)} {json.dumps(counts, sort_keys=True)}"
    )
    typer.echo(f"Enrichment report: {report_path}")
    if counts.get("failed"):
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
