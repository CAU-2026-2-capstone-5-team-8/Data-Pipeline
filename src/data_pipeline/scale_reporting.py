"""Detailed reporting and human-audit artifacts for scale experiments."""

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from data_pipeline.diagnostics import NormalizationDiagnostics
from data_pipeline.identifiers import normalize_bibliographic_text
from data_pipeline.manifest import MvpManifest
from data_pipeline.models import Book, CanonicalDataset
from data_pipeline.normalizers import (
    normalize_google_books_response,
    normalize_open_library_response,
)
from data_pipeline.storage import RawArtifact, read_raw_response
from data_pipeline.validation import validate_dataset

EVIDENCE_TYPES = (
    "description",
    "preface",
    "introduction",
    "preview",
    "sample_chapter",
)
PROSE_TYPES = {
    "description",
    "publisher_summary",
    "preface",
    "introduction",
    "preview",
    "sample_chapter",
    "other",
}
FORMULA_PREFIXES = ("=", "+", "-", "@")


def spreadsheet_safe_csv_value(value: Any) -> Any:
    """Neutralize formula-like strings only at the spreadsheet-facing CSV boundary."""
    if isinstance(value, str) and value.lstrip().startswith(FORMULA_PREFIXES):
        return "'" + value
    return value


def normalization_diagnostics(raw_paths: list[Path]) -> list[NormalizationDiagnostics]:
    """Replay generic provider normalizers over their full candidate pools for metrics."""
    results: list[NormalizationDiagnostics] = []
    for raw_path in raw_paths:
        artifact = read_raw_response(raw_path)
        diagnostics = NormalizationDiagnostics(provider=artifact.provider.replace("-", "_"))
        search_response = artifact.response.get("search_response", artifact.response)
        records = search_response.get(
            "items" if artifact.provider == "google-books" else "docs", []
        )
        candidate_limit = len(records) if isinstance(records, list) else artifact.requested_limit
        if artifact.provider == "open-library":
            normalize_open_library_response(
                artifact.response,
                topic=artifact.topic,
                limit=candidate_limit,
                retrieved_at=artifact.retrieved_at,
                diagnostics=diagnostics,
            )
        elif artifact.provider == "google-books":
            normalize_google_books_response(
                artifact.response,
                topic=artifact.topic,
                limit=candidate_limit,
                retrieved_at=artifact.retrieved_at,
                diagnostics=diagnostics,
            )
        else:
            continue
        results.append(diagnostics)
    return results


def _book_coverage(dataset: CanonicalDataset) -> list[dict[str, Any]]:
    """Return source-aware evidence and size metrics for every canonical book."""
    documents_by_book: dict[str, list[Any]] = defaultdict(list)
    toc_by_book: Counter[str] = Counter()
    sources_by_book: dict[str, list[Any]] = defaultdict(list)
    for document in dataset.documents:
        documents_by_book[document.book_id].append(document)
    for entry in dataset.toc:
        toc_by_book[entry.book_id] += 1
    for source in dataset.sources:
        sources_by_book[source.book_id].append(source)

    rows: list[dict[str, Any]] = []
    for book in sorted(
        dataset.books,
        key=lambda item: (item.topics[-1], item.title.casefold(), item.book_id),
    ):
        documents = documents_by_book[book.book_id]
        document_types = {document.document_type for document in documents}
        prose_documents = [
            document for document in documents if document.document_type in PROSE_TYPES
        ]
        providers = sorted({source.provider for source in sources_by_book[book.book_id]})
        rows.append(
            {
                "book_id": book.book_id,
                "title": book.title,
                "authors": book.authors,
                "isbn_10": book.isbn_10,
                "isbn_13": book.isbn_13,
                "published_year": book.published_year,
                "topic": book.topics[-1],
                "metadata": True,
                "description": "description" in document_types,
                "toc": toc_by_book[book.book_id] > 0,
                "preface": "preface" in document_types,
                "introduction": "introduction" in document_types,
                "preview": "preview" in document_types,
                "sample_chapter": "sample_chapter" in document_types,
                "other_prose": bool({"publisher_summary", "other"} & document_types),
                "toc_entry_count": toc_by_book[book.book_id],
                "document_count": len(documents),
                "prose_document_count": len(prose_documents),
                "prose_character_count": sum(len(document.text) for document in prose_documents),
                "providers": providers,
                "source_urls": sorted({source.url for source in sources_by_book[book.book_id]}),
            }
        )
    return rows


def _aggregate_coverage(rows: list[dict[str, Any]]) -> dict[str, int]:
    """Aggregate per-book booleans and sizes without hiding the denominator."""
    return {
        "book_count": len(rows),
        "metadata": sum(bool(row["metadata"]) for row in rows),
        "description": sum(bool(row["description"]) for row in rows),
        "toc": sum(bool(row["toc"]) for row in rows),
        "preface": sum(bool(row["preface"]) for row in rows),
        "introduction": sum(bool(row["introduction"]) for row in rows),
        "preview": sum(bool(row["preview"]) for row in rows),
        "sample_chapter": sum(bool(row["sample_chapter"]) for row in rows),
        "other_prose": sum(bool(row["other_prose"]) for row in rows),
        "toc_entry_count": sum(int(row["toc_entry_count"]) for row in rows),
        "document_count": sum(int(row["document_count"]) for row in rows),
        "prose_document_count": sum(int(row["prose_document_count"]) for row in rows),
        "prose_character_count": sum(int(row["prose_character_count"]) for row in rows),
    }


def _author_conflicts(book: Book) -> list[str]:
    """Flag inspectable author-shape anomalies without changing canonical identity."""
    signatures = [
        tuple(sorted(normalize_bibliographic_text(author).split())) for author in book.authors
    ]
    conflicts = []
    if any(count > 1 for count in Counter(signatures).values()):
        conflicts.append("suspected_duplicate_author_variants")
    if any(len(author) > 100 or "[by]" in author.casefold() for author in book.authors):
        conflicts.append("suspicious_author_format")
    return conflicts


def _failure_analysis(
    rows: list[dict[str, Any]],
    artifacts: list[RawArtifact],
    diagnostics: list[NormalizationDiagnostics],
) -> dict[str, Any]:
    """Classify collection, normalization, and missing-evidence outcomes."""
    counts: Counter[str] = Counter()
    per_book: list[dict[str, Any]] = []
    for diagnostic in diagnostics:
        counts.update(diagnostic.failure_counts)
        if diagnostic.duplicate_candidate_count:
            counts["duplicate"] += diagnostic.duplicate_candidate_count
    for artifact in artifacts:
        failures = artifact.response.get("collection_failures", [])
        if isinstance(failures, list):
            for failure in failures:
                if isinstance(failure, dict) and isinstance(failure.get("reason"), str):
                    counts[failure["reason"]] += 1

    for row in rows:
        providers = set(row["providers"])
        metadata_only = providers <= {"open_library", "google_books"}
        missing: dict[str, str] = {}
        for evidence_type in EVIDENCE_TYPES:
            if row[evidence_type]:
                continue
            reason = (
                "unsupported_source"
                if metadata_only
                and evidence_type in {"preface", "introduction", "preview", "sample_chapter"}
                else "provider_returned_no_evidence"
            )
            missing[evidence_type] = reason
            counts[reason] += 1
        if not row["toc"]:
            missing["toc"] = "provider_returned_no_evidence"
            counts["provider_returned_no_evidence"] += 1
        if not row["other_prose"]:
            missing["other_prose"] = (
                "unsupported_source" if metadata_only else "provider_returned_no_evidence"
            )
            counts[missing["other_prose"]] += 1
        if row["prose_character_count"] == 0:
            missing["public_prose"] = "insufficient_public_prose"
            counts["insufficient_public_prose"] += 1
        if missing:
            per_book.append({"book_id": row["book_id"], "missing": missing})
    return {"counts": dict(sorted(counts.items())), "by_book": per_book}


def _integrity_metrics(dataset: CanonicalDataset, deterministic_rebuild: bool) -> dict[str, Any]:
    """Count referential and identifier defects independently of coverage."""
    book_ids = {book.book_id for book in dataset.books}
    sources_by_id = {source.source_id: source for source in dataset.sources}
    toc_by_id = {entry.toc_entry_id: entry for entry in dataset.toc}
    all_ids = {
        "book": [book.book_id for book in dataset.books],
        "source": [source.source_id for source in dataset.sources],
        "document": [document.document_id for document in dataset.documents],
        "toc": [entry.toc_entry_id for entry in dataset.toc],
    }
    duplicate_ids = sum(
        sum(count - 1 for count in Counter(values).values() if count > 1)
        for values in all_ids.values()
    )
    broken_references = sum(source.book_id not in book_ids for source in dataset.sources)
    missing_provenance = 0
    for document in dataset.documents:
        source = sources_by_id.get(document.source_id)
        broken = (
            document.book_id not in book_ids or source is None or source.book_id != document.book_id
        )
        broken_references += broken
        missing_provenance += source is None
    invalid_toc_parents = 0
    for entry in dataset.toc:
        source = sources_by_id.get(entry.source_id)
        broken = entry.book_id not in book_ids or source is None or source.book_id != entry.book_id
        broken_references += broken
        missing_provenance += source is None
        if entry.parent_entry_id is not None:
            parent = toc_by_id.get(entry.parent_entry_id)
            invalid_toc_parents += parent is None or parent.book_id != entry.book_id
    sourced_books = {source.book_id for source in dataset.sources}
    missing_provenance += sum(book.book_id not in sourced_books for book in dataset.books)
    validation_errors = validate_dataset(dataset)
    return {
        "broken_book_source_document_toc_references": broken_references,
        "unresolved_duplicate_canonical_ids": duplicate_ids,
        "invalid_toc_parent_relationships": invalid_toc_parents,
        "missing_provenance_for_emitted_evidence": missing_provenance,
        "validation_error_count": len(validation_errors),
        "validation_errors": validation_errors,
        "deterministic_canonical_ids": deterministic_rebuild,
        "offline_rebuild_byte_identical": deterministic_rebuild,
    }


def create_scale_report(
    *,
    manifest: MvpManifest,
    dataset: CanonicalDataset,
    raw_paths: list[Path],
    deterministic_rebuild: bool,
    build_seconds: float,
    canonical_bytes: int,
) -> dict[str, Any]:
    """Create the complete machine-readable Scale Pilot report."""
    artifacts = [read_raw_response(path) for path in raw_paths]
    diagnostics = normalization_diagnostics(raw_paths)
    rows = _book_coverage(dataset)
    books_by_id = {book.book_id: book for book in dataset.books}
    edition_mismatch_book_ids = set().union(
        *(item.edition_mismatch_book_ids for item in diagnostics)
    )
    for row in rows:
        conflicts = _author_conflicts(books_by_id[row["book_id"]])
        if row["book_id"] in edition_mismatch_book_ids:
            conflicts.append("work_description_edition_mismatch")
        row["suspected_identity_or_edition_conflicts"] = conflicts
    rows_by_topic: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        rows_by_topic[row["topic"]].append(row)
    provider_counts: Counter[str] = Counter()
    for diagnostic in diagnostics:
        provider_counts[diagnostic.provider] += diagnostic.candidate_count
    discovery = {
        "candidate_count": sum(item.candidate_count for item in diagnostics),
        "requested_book_count": sum(
            selector.requested_limit for selector in manifest.raw_artifacts
        ),
        "selected_book_count": len(manifest.expected_book_ids),
        "successfully_normalized_book_count": len(dataset.books),
        "topic_book_count": dict(sorted(Counter(row["topic"] for row in rows).items())),
        "provider_discovery_count": dict(sorted(provider_counts.items())),
        "isbn_13_availability": sum(book.isbn_13 is not None for book in dataset.books),
        "isbn_10_availability": sum(book.isbn_10 is not None for book in dataset.books),
        "fallback_book_id_count": sum(book.book_id.startswith("book_") for book in dataset.books),
        "duplicate_candidate_count": sum(item.duplicate_candidate_count for item in diagnostics),
        "eligible_normalized_candidate_count": sum(
            item.normalized_candidate_count + item.duplicate_candidate_count for item in diagnostics
        ),
        "deduplicated_candidate_pool_count": sum(
            item.normalized_candidate_count for item in diagnostics
        ),
        "deduplicated_book_count": len(dataset.books),
        "edition_mismatch_count": sum(item.edition_mismatch_count for item in diagnostics),
        "normalization_failure_count": sum(
            item.normalization_failure_count for item in diagnostics
        ),
    }
    return {
        "schema_version": 1,
        "experiment": "scale-50",
        "discovery_normalization": discovery,
        "evidence_coverage": {
            "overall": _aggregate_coverage(rows),
            "by_topic": {
                topic: _aggregate_coverage(topic_rows)
                for topic, topic_rows in sorted(rows_by_topic.items())
            },
            "by_book": rows,
        },
        "failure_analysis": _failure_analysis(rows, artifacts, diagnostics),
        "data_integrity": _integrity_metrics(dataset, deterministic_rebuild),
        "artifacts": {
            "raw_artifact_count": len(raw_paths),
            "raw_bytes": sum(path.stat().st_size for path in raw_paths),
            "canonical_bytes": canonical_bytes,
            "two_offline_build_seconds": round(build_seconds, 6),
        },
    }


def _audit_warnings(book: Book, row: dict[str, Any]) -> list[str]:
    """Build automated warnings while leaving human audit judgments blank."""
    warnings = list(row["suspected_identity_or_edition_conflicts"])
    if book.isbn_13 is None:
        warnings.append("missing_isbn_13")
    if book.isbn_10 is None:
        warnings.append("missing_isbn_10")
    if book.book_id.startswith("book_"):
        warnings.append("fallback_book_id")
    if not book.authors:
        warnings.append("missing_authors")
    if book.published_year is None:
        warnings.append("missing_year")
    if not row["toc"]:
        warnings.append("missing_toc")
    if row["prose_character_count"] == 0:
        warnings.append("insufficient_public_prose")
    return warnings


def write_scale_artifacts(
    report: dict[str, Any], dataset: CanonicalDataset, output_directory: Path
) -> tuple[Path, Path]:
    """Write a JSON report and blank-review CSV without fabricating human judgments."""
    output_directory.mkdir(parents=True, exist_ok=True)
    report_path = output_directory / "scale-report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    audit_path = output_directory / "scale-audit.csv"
    books_by_id = {book.book_id: book for book in dataset.books}
    fieldnames = [
        "book_id",
        "title",
        "authors",
        "isbn_10",
        "isbn_13",
        "edition_or_year",
        "topic",
        "evidence_types",
        "source_providers",
        "source_urls",
        "prose_character_count",
        "toc_entry_count",
        "warnings",
        "suspected_identity_or_edition_conflicts",
        "identity_ok",
        "topic_relevant",
        "toc_matches_book",
        "prose_matches_book",
        "edition_ok",
        "notes",
    ]
    with audit_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        for row in report["evidence_coverage"]["by_book"]:
            book = books_by_id[row["book_id"]]
            evidence_types = [
                evidence_type
                for evidence_type in ("metadata", *EVIDENCE_TYPES, "toc", "other_prose")
                if row[evidence_type]
            ]
            audit_row = {
                "book_id": book.book_id,
                "title": book.title,
                "authors": " | ".join(book.authors),
                "isbn_10": book.isbn_10 or "",
                "isbn_13": book.isbn_13 or "",
                "edition_or_year": book.published_year or "",
                "topic": row["topic"],
                "evidence_types": " | ".join(evidence_types),
                "source_providers": " | ".join(row["providers"]),
                "source_urls": " | ".join(row["source_urls"]),
                "prose_character_count": row["prose_character_count"],
                "toc_entry_count": row["toc_entry_count"],
                "warnings": " | ".join(_audit_warnings(book, row)),
                "suspected_identity_or_edition_conflicts": " | ".join(
                    row["suspected_identity_or_edition_conflicts"]
                ),
                "identity_ok": "",
                "topic_relevant": "",
                "toc_matches_book": "",
                "prose_matches_book": "",
                "edition_ok": "",
                "notes": "",
            }
            writer.writerow(
                {field: spreadsheet_safe_csv_value(value) for field, value in audit_row.items()}
            )
    return report_path, audit_path
