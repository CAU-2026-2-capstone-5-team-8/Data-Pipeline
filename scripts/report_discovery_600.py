"""Build the dated Discovery-600 evidence-availability reports from preserved data."""

# Long prose literals below are emitted as Markdown and are clearer without artificial wrapping.
# ruff: noqa: E501

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from data_pipeline.storage import read_dataset, read_raw_response

TOPICS = (
    "linear-algebra",
    "operating-systems",
    "algorithms",
    "databases",
    "discrete-mathematics",
    "probability-statistics",
)
TOPIC_TITLES = {
    "linear-algebra": "Linear Algebra",
    "operating-systems": "Operating Systems",
    "algorithms": "Algorithms",
    "databases": "Databases",
    "discrete-mathematics": "Discrete Mathematics",
    "probability-statistics": "Probability/Statistics",
}
YEAR_BUCKETS = ("<= 2000", "2001-2010", "2011-2020", "2021+", "unknown")
MAJOR_LIKE_CATEGORIES = {
    "국내도서-IT 모바일",
    "국내도서-대학교재",
    "국내도서-자연과학",
}


def _year_bucket(year: int | None) -> str:
    """Map one publication year to the experiment's fixed descriptive buckets."""
    if year is None:
        return "unknown"
    if year <= 2000:
        return "<= 2000"
    if year <= 2010:
        return "2001-2010"
    if year <= 2020:
        return "2011-2020"
    return "2021+"


def _metrics(rows: list[dict[str, Any]]) -> dict[str, int | float]:
    """Count book-level evidence availability and denominator-based percentages."""
    books = len(rows)
    toc_books = sum(bool(row["has_toc"]) for row in rows)
    description_books = sum(bool(row["has_description"]) for row in rows)
    both_books = sum(bool(row["has_both_description_and_toc"]) for row in rows)

    def percentage(count: int) -> float:
        return round(100 * count / books, 2) if books else 0.0

    return {
        "books": books,
        "toc_books": toc_books,
        "toc_percentage": percentage(toc_books),
        "description_books": description_books,
        "description_percentage": percentage(description_books),
        "both_books": both_books,
        "both_percentage": percentage(both_books),
    }


def _translation_status(item: dict[str, Any]) -> str:
    """Return a conservative yes/no/unknown translation label from public metadata."""
    marker = str(item.get("originalTranslation", "")).strip().upper()
    original_title = str(item.get("originalTitle", "")).strip()
    if original_title or marker == "Y":
        return "yes"
    if marker == "N":
        return "no"
    return "unknown"


def _topic_rows(data_dir: Path, topic: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Load one preserved topic result without copying its prose into report rows."""
    dataset = read_dataset(data_dir / "topics" / topic / "processed")
    raw_paths = sorted((data_dir / "raw" / "yes24" / topic).glob("*.json"))
    if len(raw_paths) != 1:
        raise ValueError(f"expected exactly one preserved raw artifact for {topic}")
    artifact = read_raw_response(raw_paths[0])
    items = artifact.response.get("data", {}).get("items", [])
    item_by_id = {
        str(item["itemId"]): item
        for item in items
        if isinstance(item, dict)
        and isinstance(item.get("itemId"), int)
        and not isinstance(item.get("itemId"), bool)
    }
    source_by_book = {source.book_id: source for source in dataset.sources}
    toc_counts = Counter(entry.book_id for entry in dataset.toc)
    description_books = {
        document.book_id
        for document in dataset.documents
        if document.document_type == "description"
    }
    rows: list[dict[str, Any]] = []
    for book in dataset.books:
        source = source_by_book[book.book_id]
        item = item_by_id.get(source.external_id or "", {})
        has_toc = toc_counts[book.book_id] > 0
        has_description = book.book_id in description_books
        rows.append(
            {
                "topic": topic,
                "book_id": book.book_id,
                "isbn13": book.isbn_13,
                "title": book.title,
                "publisher": book.publisher,
                "published_year": book.published_year,
                "translation": _translation_status(item),
                "has_description": has_description,
                "has_toc": has_toc,
                "toc_entry_count": toc_counts[book.book_id],
                "has_both_description_and_toc": has_description and has_toc,
                "provider_category": item.get("goodsSortNm"),
            }
        )
    raw_summary = {
        "topic": topic,
        "path": raw_paths[0].as_posix(),
        "retrieved_at": artifact.retrieved_at.isoformat(),
        "content_hash": artifact.content_hash,
        "request_parameters": artifact.request_parameters,
        "provider_items": len(items) if isinstance(items, list) else 0,
    }
    return rows, raw_summary


def _unique_rows(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, list[str]]]:
    """Deduplicate cross-topic book IDs while preserving their topic membership."""
    grouped: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row["book_id"]].append(row)
    unique: list[dict[str, Any]] = []
    duplicates: dict[str, list[str]] = {}
    for book_id, group in sorted(grouped.items()):
        topics = sorted({str(row["topic"]) for row in group})
        if len(group) > 1:
            duplicates[book_id] = topics
        first = group[0]
        translations = {str(row["translation"]) for row in group}
        translation = (
            "yes" if "yes" in translations else "no" if translations == {"no"} else "unknown"
        )
        has_description = any(row["has_description"] for row in group)
        has_toc = any(row["has_toc"] for row in group)
        unique.append(
            {
                **first,
                "topic": topics[0] if len(topics) == 1 else None,
                "topics": topics,
                "translation": translation,
                "has_description": has_description,
                "has_toc": has_toc,
                "toc_entry_count": max(int(row["toc_entry_count"]) for row in group),
                "has_both_description_and_toc": has_description and has_toc,
            }
        )
    return unique, duplicates


def _scale_50_summary(scale_dir: Path) -> dict[str, Any]:
    """Measure the existing frozen baseline without recollecting or modifying it."""
    dataset = read_dataset(scale_dir)
    toc_books = {entry.book_id for entry in dataset.toc}
    description_books = {
        document.book_id
        for document in dataset.documents
        if document.document_type == "description"
    }
    any_prose_books = {document.book_id for document in dataset.documents}
    rows = [
        {
            "published_year": book.published_year,
            "has_toc": book.book_id in toc_books,
            "has_description": book.book_id in description_books,
            "has_both_description_and_toc": book.book_id in toc_books
            and book.book_id in description_books,
        }
        for book in dataset.books
    ]
    return {
        "coverage": {**_metrics(rows), "any_prose_books": len(any_prose_books)},
        "publication_year": {
            bucket: _metrics([row for row in rows if _year_bucket(row["published_year"]) == bucket])
            for bucket in YEAR_BUCKETS
        },
    }


def build_report(data_dir: Path, scale_dir: Path, starting_head: str) -> dict[str, Any]:
    """Build aggregate and per-book Discovery-600 results from preserved artifacts."""
    telemetry_path = data_dir / "reports" / "collection-telemetry.json"
    telemetry = json.loads(telemetry_path.read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = []
    raw_artifacts: list[dict[str, Any]] = []
    for topic in TOPICS:
        topic_rows, raw_summary = _topic_rows(data_dir, topic)
        rows.extend(topic_rows)
        raw_artifacts.append(raw_summary)
    books, duplicates = _unique_rows(rows)
    category_counts = {
        topic: dict(
            Counter(
                str(row["provider_category"] or "unknown") for row in rows if row["topic"] == topic
            ).most_common()
        )
        for topic in TOPICS
    }
    major_like_rows = [row for row in books if row["provider_category"] in MAJOR_LIKE_CATEGORIES]
    run_by_topic = {run["topic"]: run for run in telemetry["runs"]}
    return {
        "schema_version": 1,
        "experiment": "discovery-600",
        "experiment_date": "2026-09-29",
        "starting_head": starting_head,
        "provider": "yes24",
        "environment": {
            "yes24_api_key_configured": True,
            "key_value_recorded": False,
            "generated_data_committed": False,
        },
        "method": {
            "topics": list(TOPICS),
            "requested_books_per_topic": 100,
            "requested_max_books": 600,
            "successful_provider_page_size": 100,
            "normalizer": "existing normalize_yes24_response semantics",
            "current_filters_preserved": [
                "configured Korean topic-title relevance",
                "configured conflicting-subject exclusions",
                "ISBN validation",
                "ISBN-less bundle/set exclusion",
            ],
            "production_selection_policy_changed": False,
        },
        "collection": {
            "raw_provider_items": sum(item["provider_items"] for item in raw_artifacts),
            "topic_candidate_rows": len(rows),
            "unique_books": len(books),
            "cross_topic_duplicate_rows": len(rows) - len(books),
            "cross_topic_duplicate_book_ids": duplicates,
            "normalization_exclusions": sum(
                int(run.get("normalization_failures", 0)) for run in telemetry["runs"]
            ),
            "by_topic": {
                topic: {
                    "provider_items": int(run_by_topic[topic]["provider_items"]),
                    "normalized_books": int(run_by_topic[topic]["books_written"]),
                    "excluded_candidates": int(run_by_topic[topic]["normalization_failures"]),
                    "failure_counts": run_by_topic[topic]["failure_counts"],
                }
                for topic in TOPICS
            },
            "telemetry": telemetry["telemetry"],
            "collection_adjustment": telemetry["collection_adjustment"],
            "raw_artifacts": raw_artifacts,
        },
        "coverage": {
            "by_topic": {
                topic: _metrics([row for row in rows if row["topic"] == topic]) for topic in TOPICS
            },
            "unique_total": {
                **_metrics(books),
                "any_prose_books": sum(bool(row["has_description"]) for row in books),
            },
            "by_publication_year": {
                bucket: _metrics(
                    [row for row in books if _year_bucket(row["published_year"]) == bucket]
                )
                for bucket in YEAR_BUCKETS
            },
        },
        "translation": {
            "counts": dict(Counter(row["translation"] for row in books)),
            "rule": (
                "yes when YES24 supplies originalTitle or explicit Y; no only for explicit N; "
                "otherwise unknown"
            ),
        },
        "pool_quality_observation": {
            "provider_categories_by_topic": category_counts,
            "probability_statistics_high_school_books": category_counts[
                "probability-statistics"
            ].get("국내도서-중고등학습서-고등학교", 0),
            "algorithm_books_outside_major_like_categories": sum(
                row["topic"] == "algorithms"
                and row["provider_category"] not in MAJOR_LIKE_CATEGORIES
                for row in rows
            ),
            "major_like_category_sensitivity": {
                "non_production_definition": sorted(MAJOR_LIKE_CATEGORIES),
                "unique_total": _metrics(major_like_rows),
                "by_topic": {
                    topic: _metrics(
                        [
                            row
                            for row in rows
                            if row["topic"] == topic
                            and row["provider_category"] in MAJOR_LIKE_CATEGORIES
                        ]
                    )
                    for topic in TOPICS
                },
            },
        },
        "scale_50_descriptive_comparison": _scale_50_summary(scale_dir),
        "interpretation": {
            "conclusion": "selection_bottleneck_supported_with_pool_quality_caveat",
            "hypothesis": "A",
            "reason": (
                "The new pool has 93.21% TOC coverage versus the frozen Scale-50's 50%, "
                "and 2021+ books have 95.38% TOC and 87.39% description coverage. The "
                "post-hoc major-like category subset still has 92.33% TOC coverage. This "
                "supports frozen target selection and age mix as the dominant measured "
                "bottleneck, while category noise prevents treating all 471 books as a "
                "production recommendation pool."
            ),
            "statistical_significance_claimed": False,
        },
        "selection_policy_candidate": {
            "fixed_benchmark": (
                "Keep Scale-50 frozen for longitudinal acquisition comparisons, including its "
                "known age and identity limitations."
            ),
            "production_pool": (
                "Require relevant metadata and a valid ISBN, then require a usable TOC or "
                "sufficiently strong prose evidence; add a separately reviewed education-level "
                "and technical-book quality gate before adoption."
            ),
            "implemented_in_this_change": False,
        },
        "books": books,
    }


def _coverage_row(label: str, values: dict[str, Any]) -> str:
    """Render one stable Markdown coverage-table row."""
    return (
        f"| {label} | {values['books']} | {values['toc_books']} | "
        f"{values['toc_percentage']:.2f}% | {values['description_books']} | "
        f"{values['description_percentage']:.2f}% | {values['both_books']} | "
        f"{values['both_percentage']:.2f}% |"
    )


def markdown_report(report: dict[str, Any], json_name: str) -> str:
    """Render the dated human-readable report from the machine-readable result."""
    coverage = report["coverage"]
    scale = report["scale_50_descriptive_comparison"]
    collection = report["collection"]
    quality = report["pool_quality_observation"]
    lines = [
        "# Discovery-600 evidence availability — 2026-09-29",
        "",
        "This independent pilot tests whether Scale-50 evidence coverage is primarily constrained ",
        "by acquisition capability or by freezing older/out-of-print targets before checking ",
        "evidence availability. It does not modify or merge into Scale-50. The companion ",
        f"[machine-readable report]({json_name}) contains aggregate and per-book results without ",
        "raw descriptions or TOC text.",
        "",
        "## Method and collection",
        "",
        "The existing YES24 collector, topic configuration, ISBN handling, relevance checks, and ",
        "normalizer were used unchanged for six configured topics. Each successful search requested ",
        "at most 100 provider items and normalized at most 100 books. Topic outputs stayed isolated; ",
        "no result was merged into the current canonical Scale-50 dataset.",
        "",
        "- Requested maximum: 6 topics × 100 = 600 books",
        f"- Raw provider items: {collection['raw_provider_items']}",
        f"- Normalized topic rows / unique books: {collection['topic_candidate_rows']} / {collection['unique_books']}",
        f"- Existing-filter exclusions: {collection['normalization_exclusions']}",
        f"- Cross-topic duplicate rows: {collection['cross_topic_duplicate_rows']}",
        f"- YES24 requests: {collection['telemetry']['requests']} total "
        f"({collection['telemetry']['http_status_counts'].get('200', 0)}×200, "
        f"{collection['telemetry']['http_status_counts'].get('400', 0)}×400, "
        f"{collection['telemetry']['retries']} retries)",
        "",
        "The first bounded run reused the generic `collect --limit 100` 4× oversampling plan, so ",
        "it sent `pageSize=400`; YES24 rejected all six topic requests with HTTP 400 and wrote no ",
        "raw responses. One fallback request per topic used `pageSize=100` and succeeded. Both sets ",
        "of calls are included above. No topic was called again after a successful raw response.",
        "",
        "## Topic coverage",
        "",
        "| Topic | Books | TOC | TOC% | Description | Desc% | Both | Both% |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    lines.extend(
        _coverage_row(TOPIC_TITLES[topic], coverage["by_topic"][topic]) for topic in TOPICS
    )
    lines.append(_coverage_row("**TOTAL (unique)**", coverage["unique_total"]))
    lines.extend(
        [
            "",
            "The six topic sets contained no duplicate book IDs, so topic rows and unique books are ",
            "both 471. Percentages use each topic's normalized candidate count as denominator.",
            "",
            "## Publication-year coverage",
            "",
            "| Publication year | Books | TOC | TOC% | Description | Desc% | Both | Both% |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    lines.extend(
        _coverage_row(bucket, coverage["by_publication_year"][bucket]) for bucket in YEAR_BUCKETS
    )
    lines.extend(
        [
            "",
            "Evidence availability rises with recency in this observed pool. The 2021+ group has ",
            "95.38% TOC and 87.39% description coverage; the eight pre-2001 books have 75% TOC but ",
            "only 12.5% description coverage. These are descriptive rates, not causal or statistical ",
            "significance claims.",
            "",
            "## Frozen Scale-50 comparison",
            "",
            "These datasets are not interchangeable: Scale-50 is a frozen English-heavy benchmark ",
            "with reviewed public sources, while Discovery-600 is a current YES24 Korean-market ",
            "discovery pool. The comparison is descriptive only.",
            "",
            "| Pool | Books | TOC | TOC% | Description | Desc% | Both | Both% |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
            _coverage_row("Frozen Scale-50", scale["coverage"]),
            _coverage_row("Discovery-600", coverage["unique_total"]),
            "",
            "Frozen Scale-50 has any prose for 26/50 books. YES24 discovery emits only description ",
            "documents in this path, so Discovery-600 any-prose coverage equals 354/471 descriptions.",
            "",
            "Scale-50 has 32/50 books published by 2000 and only 1/50 from 2021 onward. Discovery-600 ",
            "has 8/471 books published by 2000 and 238/471 from 2021 onward. The age mix is therefore ",
            "materially different, matching the experiment's target-selection hypothesis.",
            "",
            "## Pool-quality caveat",
            "",
            f"Current title-based relevance rules admit meaningful topic noise: "
            f"{quality['probability_statistics_high_school_books']}/64 probability/statistics books ",
            "are categorized by YES24 as high-school study books, and ",
            f"{quality['algorithm_books_outside_major_like_categories']}/70 algorithm books fall ",
            "outside the post-hoc university-textbook/IT/natural-science category set. This is an ",
            "observed distribution, not a new filter.",
            "",
            "As a non-production sensitivity check, the 352 books in those three major-like provider ",
            "categories still show 325/352 TOC coverage (92.33%), 244/352 description coverage ",
            "(69.32%), and 243/352 both (69.03%). High coverage is therefore not explained solely by ",
            "the obvious school/general-interest category noise, although recommendation quality ",
            "still needs a separately reviewed gate.",
            "",
            "Translation status is deliberately conservative: 27 books have a provider-supplied ",
            "original title and are marked translated; 444 remain unknown. Unknown is not treated as ",
            "non-translated.",
            "",
            "## Interpretation",
            "",
            "**Hypothesis A is better supported, with a pool-quality caveat.** Discovery-600 reaches ",
            "439/471 TOC books (93.21%) versus Scale-50's 25/50 (50%). All six topics exceed 84% TOC ",
            "coverage, recent books are best covered, and the major-like sensitivity set remains at ",
            "92.33%. Within this measured workflow, freezing older/less commercially visible targets ",
            "before testing evidence availability is a much larger bottleneck than the collector's ",
            "ability to obtain YES24 TOCs for currently discoverable books.",
            "",
            "This does not prove that acquisition is solved. Description coverage is lower than TOC ",
            "coverage, pre-2001 prose is especially sparse, YES24 reflects a current Korean retail ",
            "catalog, and the current relevance rule is not a sufficient production quality policy.",
            "",
            "## Recommendation",
            "",
            "Keep **Scale-50** frozen as a longitudinal acquisition benchmark, including its known ",
            "age and identity limitations. Build the **production recommendation pool** separately: ",
            "require relevant metadata and a valid ISBN, then require either a usable TOC or strong ",
            "prose evidence, followed by a reviewed education-level/technical-book quality gate. Do ",
            "not silently replace hard benchmark books with easier ones, and do not apply the ",
            "post-hoc provider-category sensitivity set as production policy without review.",
            "",
            "No selection policy, collector, normalizer, Scale-50 record, ML component, or other ",
            "repository was changed by this experiment.",
        ]
    )
    return "\n".join(part.rstrip() for part in lines) + "\n"


def main() -> None:
    """Parse report paths, build both artifacts, and print only aggregate counts."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--data-dir", type=Path, default=Path("data/experiments/discovery-600-20260929")
    )
    parser.add_argument(
        "--scale-dir",
        type=Path,
        default=Path("data/experiments/scale-50-api-enrichment-20260929/baseline/processed"),
    )
    parser.add_argument(
        "--json-output",
        type=Path,
        default=Path("docs/experiments/discovery-600-evidence-availability-2026-09-29.json"),
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=Path("docs/experiments/discovery-600-evidence-availability-2026-09-29.md"),
    )
    parser.add_argument("--starting-head", default="1fe5b5b6f2c62cace1b68c83d00576ec343fc3b0")
    args = parser.parse_args()

    report = build_report(args.data_dir, args.scale_dir, args.starting_head)
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.write_text(
        markdown_report(report, args.json_output.name), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "books": report["coverage"]["unique_total"]["books"],
                "toc_books": report["coverage"]["unique_total"]["toc_books"],
                "description_books": report["coverage"]["unique_total"]["description_books"],
                "both_books": report["coverage"]["unique_total"]["both_books"],
                "requests": report["collection"]["telemetry"]["requests"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
