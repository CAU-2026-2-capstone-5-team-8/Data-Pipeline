import json
from datetime import UTC, datetime
from types import SimpleNamespace

from data_pipeline.identifiers import sha256_text
from data_pipeline.models import Book, CanonicalDataset, Source, TocEntry
from data_pipeline.storage import write_dataset
from data_pipeline.toc_acquisition_report import build_toc_acquisition_report


def _book(isbn: str, title: str) -> Book:
    return Book(
        book_id=f"isbn13:{isbn}",
        isbn_13=isbn,
        title=title,
        authors=["Example Author"],
        language="en",
        topics=["mathematics", "linear-algebra"],
    )


def _source_and_toc(book: Book, suffix: str) -> tuple[Source, TocEntry]:
    source_id = f"source_{suffix}"
    source = Source(
        source_id=source_id,
        book_id=book.book_id,
        provider="fixture",
        source_type="other",
        url=f"https://example.test/{suffix}",
        retrieved_at=datetime(2026, 9, 22, tzinfo=UTC),
        content_hash=sha256_text(suffix),
    )
    toc = TocEntry(
        toc_entry_id=f"toc_{suffix}",
        book_id=book.book_id,
        level=1,
        order_index=0,
        title="Chapter One",
        source_id=source_id,
    )
    return source, toc


def test_report_counts_unique_web_gain_and_metadata_separately(tmp_path, monkeypatch) -> None:
    baseline_book = _book("9780306406157", "Baseline Book")
    web_book = _book("9783161484100", "Web Book")
    metadata_book = _book("9781861972712", "Metadata Book")
    baseline_dir = tmp_path / "baseline"
    final_dir = tmp_path / "final"
    baseline_source, baseline_toc = _source_and_toc(baseline_book, "baseline")
    web_source, web_toc = _source_and_toc(web_book, "web")
    metadata_source, _metadata_toc = _source_and_toc(metadata_book, "metadata")
    write_dataset(
        CanonicalDataset(
            books=[baseline_book, web_book, metadata_book],
            documents=[],
            toc=[],
            sources=[baseline_source, web_source, metadata_source],
        ),
        baseline_dir,
    )
    write_dataset(
        CanonicalDataset(
            books=[baseline_book, web_book, metadata_book],
            documents=[],
            toc=[baseline_toc, web_toc],
            sources=[baseline_source, web_source, metadata_source],
        ),
        final_dir,
    )

    old_source = SimpleNamespace(book_id=baseline_book.book_id)
    new_source = SimpleNamespace(
        book_id=web_book.book_id,
        url="https://example.test/web",
    )
    monkeypatch.setattr(
        "data_pipeline.toc_acquisition_report.PUBLIC_BOOK_SOURCES", {"new-web": new_source}
    )
    monkeypatch.setattr(
        "data_pipeline.toc_acquisition_report.PUBLISHER_SOURCES", {"old": old_source}
    )
    empty_inspection = SimpleNamespace(
        exact_editions_count=0,
        exact_toc_found=False,
        work_keys=(),
        alternate_editions_count=0,
        alternate_toc_found=False,
        selected_alternate_edition=None,
    )
    monkeypatch.setattr(
        "data_pipeline.toc_acquisition_report.inspect_toc_resolution",
        lambda _index, _isbn: empty_inspection,
    )
    monkeypatch.setattr(
        "data_pipeline.toc_acquisition_report.resolve_toc", lambda _index, _isbn: None
    )

    experiment = tmp_path / "experiment.json"
    experiment.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "benchmark": "fixture",
                "experiment_date": "2026-09-22",
                "open_library_dump_date": "2026-08-31",
                "new_public_web_source_slugs": ["new-web"],
                "reviewed_public_web_candidates": [],
            }
        ),
        encoding="utf-8",
    )
    loc_result = tmp_path / "loc.json"
    loc_result.write_text(json.dumps({"books": []}), encoding="utf-8")
    index = tmp_path / "index.sqlite"
    index.touch()

    report = build_toc_acquisition_report(
        baseline_dir=baseline_dir,
        final_dir=final_dir,
        index_path=index,
        loc_result_path=loc_result,
        experiment_path=experiment,
    )

    assert report["coverage"] == {
        "book_count": 3,
        "baseline_exact_edition_toc": 1,
        "open_library_exact_toc_found": 0,
        "open_library_alternate_unique_gain": 0,
        "loc_505_unique_gain": 0,
        "loc_856_candidate_count": 0,
        "loc_856_usable_count": 0,
        "other_structured_unique_gain": 0,
        "structured_api_only_toc": 1,
        "public_web_candidate_count": 1,
        "public_web_unique_usable_gain": 1,
        "final_usable_toc": 2,
        "metadata_fallback_available": 1,
        "total_analyzable": 3,
        "toc_unresolved": 1,
        "fully_unresolved": 0,
        "human_search_gap_count": 0,
    }
