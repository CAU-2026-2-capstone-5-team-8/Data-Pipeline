"""Reproducible Scale benchmark reporting for tiered TOC acquisition."""

import json
from pathlib import Path
from typing import Any

from data_pipeline.open_library_bulk import inspect_toc_resolution, resolve_toc
from data_pipeline.public_book_sources import PUBLIC_BOOK_SOURCES
from data_pipeline.publisher_sources import PUBLISHER_SOURCES
from data_pipeline.storage import read_dataset
from data_pipeline.validation import validate_dataset


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return value


def build_toc_acquisition_report(
    *,
    baseline_dir: Path,
    final_dir: Path,
    index_path: Path,
    loc_result_path: Path,
    experiment_path: Path,
) -> dict[str, Any]:
    """Combine canonical, bulk-index, LOC, and reviewed-web results without double counting."""
    baseline = read_dataset(baseline_dir)
    final = read_dataset(final_dir)
    for name, dataset in (("baseline", baseline), ("final", final)):
        errors = validate_dataset(dataset)
        if errors:
            raise ValueError(f"{name} dataset is invalid: {'; '.join(errors)}")
    if {book.book_id for book in baseline.books} != {book.book_id for book in final.books}:
        raise ValueError("baseline and final benchmark book identities differ")

    experiment = _load_json(experiment_path)
    if experiment.get("schema_version") != 1:
        raise ValueError("unsupported TOC acquisition experiment schema")
    new_web_slugs = experiment.get("new_public_web_source_slugs")
    manual_candidates = experiment.get("reviewed_public_web_candidates")
    if not isinstance(new_web_slugs, list) or not all(
        isinstance(item, str) for item in new_web_slugs
    ):
        raise ValueError("new_public_web_source_slugs must be a string list")
    if not isinstance(manual_candidates, list) or not all(
        isinstance(item, dict) for item in manual_candidates
    ):
        raise ValueError("reviewed_public_web_candidates must be an object list")
    try:
        new_web_sources = {slug: PUBLIC_BOOK_SOURCES[slug] for slug in new_web_slugs}
    except KeyError as exc:
        raise ValueError(f"unknown public web source slug: {exc.args[0]}") from exc

    loc_result = _load_json(loc_result_path)
    raw_loc_books = loc_result.get("books")
    if not isinstance(raw_loc_books, list):
        raise ValueError("LOC feasibility result has no books list")
    loc_by_book = {
        item["target"]["book_id"]: item
        for item in raw_loc_books
        if isinstance(item, dict)
        and isinstance(item.get("target"), dict)
        and isinstance(item["target"].get("book_id"), str)
    }

    baseline_native_toc = {entry.book_id for entry in baseline.toc}
    prior_reviewed_exact = {
        source.book_id
        for slug, source in PUBLIC_BOOK_SOURCES.items()
        if slug not in new_web_sources
    } | {source.book_id for source in PUBLISHER_SOURCES.values()}
    baseline_exact = baseline_native_toc | prior_reviewed_exact
    new_web_by_book = {source.book_id: source for source in new_web_sources.values()}
    candidates_by_book: dict[str, list[dict[str, Any]]] = {}
    for source in new_web_sources.values():
        candidates_by_book.setdefault(source.book_id, []).append(
            {
                "url": source.url,
                "status": "usable_exact_edition_toc",
                "reason": "Exact ISBN, edition, normalized title, and chapter structure validated.",
            }
        )
    for candidate in manual_candidates:
        book_id = candidate.get("book_id")
        if not isinstance(book_id, str):
            raise ValueError("public web candidate is missing book_id")
        candidates_by_book.setdefault(book_id, []).append(
            {key: candidate[key] for key in ("url", "status", "reason")}
        )

    alternate_by_book = {}
    inspections = {}
    for book in baseline.books:
        isbn = book.isbn_13 or book.isbn_10
        if isbn is None:
            continue
        inspection = inspect_toc_resolution(index_path, isbn)
        inspections[book.book_id] = inspection
        resolution = resolve_toc(index_path, isbn)
        if resolution is not None and resolution.tier == "same_work_alternate_edition_toc":
            alternate_by_book[book.book_id] = resolution

    alternate_gain = set(alternate_by_book) - baseline_exact
    structured_resolved = baseline_exact | alternate_gain
    loc_505_usable = {
        book_id
        for book_id, item in loc_by_book.items()
        if isinstance(item.get("loc"), dict) and item["loc"].get("marc_505_usable") is True
    }
    loc_gain = loc_505_usable - structured_resolved
    structured_resolved |= loc_gain
    public_web_gain = set(new_web_by_book) - structured_resolved
    usable_toc = structured_resolved | public_web_gain
    loc_856_usable_books = {
        book_id
        for book_id, item in loc_by_book.items()
        if isinstance(item.get("loc_856_validation"), list)
        and any(
            validation.get("toc_extracted") is True
            for validation in item["loc_856_validation"]
            if isinstance(validation, dict)
        )
    }

    actual_final_toc = {entry.book_id for entry in final.toc}
    if usable_toc != actual_final_toc:
        missing = sorted(usable_toc - actual_final_toc)
        unexpected = sorted(actual_final_toc - usable_toc)
        raise ValueError(
            "computed coverage differs from canonical final: "
            f"missing={missing}, unexpected={unexpected}"
        )

    books = []
    for book in baseline.books:
        book_id = book.book_id
        inspection = inspections.get(book_id)
        loc_item = loc_by_book.get(book_id, {})
        loc = loc_item.get("loc", {}) if isinstance(loc_item, dict) else {}
        loc_856_validation = (
            loc_item.get("loc_856_validation", []) if isinstance(loc_item, dict) else []
        )
        candidates = candidates_by_book.get(book_id, [])
        resolution = alternate_by_book.get(book_id)
        if book_id in baseline_exact:
            tier = "exact_edition_toc"
            selected_source = "baseline canonical or previously reviewed exact-edition source"
        elif book_id in alternate_gain and resolution is not None:
            tier = "same_work_alternate_edition_toc"
            selected_source = f"https://openlibrary.org{resolution.source_edition_key}"
        elif book_id in loc_gain:
            tier = "validated_public_structured_toc"
            selected_source = "Library of Congress MARC 505"
        elif book_id in public_web_gain:
            tier = "validated_public_web_toc"
            selected_source = new_web_by_book[book_id].url
        else:
            tier = "metadata_fallback"
            selected_source = "canonical title/author/bibliographic metadata"
        books.append(
            {
                "target_isbn": book.isbn_13 or book.isbn_10,
                "book_id": book_id,
                "title": book.title,
                "authors": book.authors,
                "baseline_exact_toc": book_id in baseline_exact,
                "openlibrary_exact_edition_found": bool(
                    inspection and inspection.exact_editions_count
                ),
                "openlibrary_exact_toc_found": bool(inspection and inspection.exact_toc_found),
                "openlibrary_work_found": bool(inspection and inspection.work_keys),
                "openlibrary_alternate_editions_count": (
                    inspection.alternate_editions_count if inspection else 0
                ),
                "openlibrary_alternate_toc_found": bool(
                    inspection and inspection.alternate_toc_found
                ),
                "selected_alternate_edition": (
                    inspection.selected_alternate_edition if inspection else None
                ),
                "loc_record_found": bool(loc.get("record_count", 0)),
                "loc_505_found": bool(loc.get("marc_505_raw", [])),
                "loc_505_usable": bool(loc.get("marc_505_usable", False)),
                "loc_856_candidates": loc.get("marc_856_candidates", []),
                "loc_856_usable": any(
                    item.get("toc_extracted") is True
                    for item in loc_856_validation
                    if isinstance(item, dict)
                ),
                "public_web_attempted": book_id not in structured_resolved,
                "public_web_candidates": candidates,
                "public_web_usable": book_id in public_web_gain,
                "metadata_fallback_available": book_id not in usable_toc,
                "selected_evidence_tier": tier,
                "selected_source": selected_source,
                "toc_unresolved_reason": (
                    None
                    if book_id in usable_toc
                    else "No validated TOC after bulk/structured and reviewed public-web discovery."
                ),
            }
        )

    loc_856_candidates = sum(
        len(item.get("loc", {}).get("marc_856_candidates", []))
        for item in raw_loc_books
        if isinstance(item, dict) and isinstance(item.get("loc"), dict)
    )
    human_search_gap = sum(
        candidate.get("status") == "public_page_http_blocked" for candidate in manual_candidates
    )
    return {
        "schema_version": 1,
        "benchmark": experiment.get("benchmark"),
        "experiment_date": experiment.get("experiment_date"),
        "open_library_dump_date": experiment.get("open_library_dump_date"),
        "coverage": {
            "book_count": len(baseline.books),
            "baseline_exact_edition_toc": len(baseline_exact),
            "open_library_exact_toc_found": sum(
                inspection.exact_toc_found for inspection in inspections.values()
            ),
            "open_library_alternate_unique_gain": len(alternate_gain),
            "loc_505_unique_gain": len(loc_gain),
            "loc_856_candidate_count": loc_856_candidates,
            "loc_856_usable_count": len(loc_856_usable_books),
            "other_structured_unique_gain": 0,
            "structured_api_only_toc": len(structured_resolved),
            "public_web_candidate_count": sum(map(len, candidates_by_book.values())),
            "public_web_unique_usable_gain": len(public_web_gain),
            "final_usable_toc": len(usable_toc),
            "metadata_fallback_available": len(baseline.books) - len(usable_toc),
            "total_analyzable": len(baseline.books),
            "toc_unresolved": len(baseline.books) - len(usable_toc),
            "fully_unresolved": 0,
            "human_search_gap_count": human_search_gap,
        },
        "false_positive_prevention": {
            "policy": (
                "Provider-native Work relation or exact ISBN/edition validation; false "
                "positives are more costly than false negatives."
            ),
            "rejected_examples": [
                "9780132819824: exact Open Library records are Students Solutions Manual editions",
                (
                    "9780716721772: target itself is a solutions/study manual and is not linked "
                    "to the main textbook"
                ),
                (
                    "Public-web alternate editions without a provider-native Work relation "
                    "remain candidates only"
                ),
            ],
        },
        "books": books,
    }
