import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from data_pipeline.cli import app
from data_pipeline.models import Book, CanonicalDataset, Source
from data_pipeline.public_book_sources import public_book_source
from data_pipeline.storage import read_dataset, write_dataset
from data_pipeline.validation import validate_dataset


@pytest.fixture
def enrichment_dataset(tmp_path, monkeypatch):
    spec = public_book_source("ecampus-stallings-os4")
    fixture_spec = replace(
        spec,
        expected_toc_count=12,
        expected_root_titles=(
            "Web Site for Operating Systems: Internals and Design Principles",
            "Preface",
            "PART ONE BACKGROUND",
            "APPENDICES",
            "Index",
        ),
    )
    monkeypatch.setattr("data_pipeline.normalizers.public_book_source", lambda _: fixture_spec)
    book = Book(
        book_id=spec.book_id,
        isbn_13=spec.isbn_13,
        title=spec.title,
        authors=["William Stallings"],
        language="en",
        topics=["operating-systems"],
    )
    source = Source(
        source_id="metadata",
        book_id=book.book_id,
        provider="fixture",
        source_type="metadata_api",
        url="https://example.test/book",
        retrieved_at=datetime(2026, 9, 20, tzinfo=UTC),
        content_hash="sha256:" + "a" * 64,
    )
    write_dataset(
        CanonicalDataset(books=[book], sources=[source], documents=[], toc=[]),
        tmp_path / "processed",
    )
    calls = []

    def fetch(slug):
        calls.append(slug)
        return (
            {
                "source_slug": slug,
                "url": spec.url,
                "html": Path("tests/fixtures/ecampus_stallings_os4.html").read_text(
                    encoding="utf-8"
                ),
            },
            {"source": slug, "url": spec.url},
        )

    monkeypatch.setattr("data_pipeline.cli._collect_public_book_payload", fetch)
    return tmp_path, calls


def test_enrich_recovers_missing_toc_and_second_run_skips_network(enrichment_dataset):
    root, calls = enrichment_dataset
    for _ in range(2):
        result = CliRunner().invoke(app, ["enrich-toc", "--data-dir", str(root)])
        assert result.exit_code == 0, result.output
    assert calls == ["ecampus-stallings-os4"]
    dataset = read_dataset(root / "processed")
    assert len(dataset.books) == 1
    assert len(dataset.toc) == 12
    assert validate_dataset(dataset) == []
    report = json.loads((root / "reports/toc-enrichment.json").read_text(encoding="utf-8"))
    assert report["toc_books_before"] == report["toc_books_after"] == 1
    assert len(list((root / "raw").rglob("*.json"))) == 1


def test_enrich_rejects_wrong_edition_without_publishing(enrichment_dataset, monkeypatch):
    root, _ = enrichment_dataset

    def fetch(slug):
        spec = public_book_source(slug)
        html = Path("tests/fixtures/ecampus_stallings_os4.html").read_text(encoding="utf-8")
        return (
            {
                "source_slug": slug,
                "url": spec.url,
                "html": html.replace("9780130319999", "9780070575721"),
            },
            {},
        )

    monkeypatch.setattr("data_pipeline.cli._collect_public_book_payload", fetch)
    result = CliRunner().invoke(app, ["enrich-toc", "--data-dir", str(root)])
    assert result.exit_code == 1, result.output
    assert read_dataset(root / "processed").toc == []
    assert len(list((root / "raw").rglob("*.json"))) == 1
    report = json.loads((root / "reports/toc-enrichment.json").read_text(encoding="utf-8"))
    assert report["attempts"][0]["status"] == "failed"


def test_enrich_dry_run_never_fetches(enrichment_dataset):
    root, calls = enrichment_dataset
    result = CliRunner().invoke(app, ["enrich-toc", "--data-dir", str(root), "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "ecampus-stallings-os4" in result.output
    assert calls == []
    assert read_dataset(root / "processed").toc == []


@pytest.mark.parametrize("budget, expected_count", [(1, 0), (2, 12)])
def test_enrich_continues_after_failure_with_bounded_attempts(
    enrichment_dataset, monkeypatch, budget, expected_count
):
    from data_pipeline.collectors.base import InvalidProviderResponse
    from data_pipeline.publisher_sources import publisher_source

    root, calls = enrichment_dataset
    dataset = read_dataset(root / "processed")
    spec = publisher_source("wiley-osc7")
    dataset.books.append(
        Book(
            book_id=spec.book_id,
            isbn_13="9780471694663",
            title=spec.title,
            authors=["Silberschatz"],
            language="en",
            topics=["operating-systems"],
        )
    )
    dataset.sources.append(
        dataset.sources[0].model_copy(
            update={
                "source_id": "wiley-metadata",
                "book_id": spec.book_id,
            }
        )
    )
    write_dataset(dataset, root / "processed")

    def fail(_):
        raise InvalidProviderResponse("fixture provider failure")

    monkeypatch.setattr("data_pipeline.cli._collect_publisher_payload", fail)
    result = CliRunner().invoke(
        app, ["enrich-toc", "--data-dir", str(root), "--max-sources", str(budget)]
    )
    assert result.exit_code == 1, result.output
    assert len(read_dataset(root / "processed").toc) == expected_count
    report = json.loads((root / "reports/toc-enrichment.json").read_text(encoding="utf-8"))
    assert len(report["attempts"]) == budget
    assert report["attempts"][0]["status"] == "failed"
    assert len(calls) == budget - 1


def test_enrich_does_not_match_title_from_a_different_edition(enrichment_dataset):
    root, calls = enrichment_dataset
    dataset = read_dataset(root / "processed")
    dataset.books[0] = dataset.books[0].model_copy(
        update={
            "book_id": "isbn13:9780306406157",
            "isbn_13": "9780306406157",
        }
    )
    dataset.sources[0] = dataset.sources[0].model_copy(
        update={
            "book_id": "isbn13:9780306406157",
        }
    )
    write_dataset(dataset, root / "processed")
    result = CliRunner().invoke(app, ["enrich-toc", "--data-dir", str(root)])
    assert result.exit_code == 0, result.output
    assert calls == []
    assert read_dataset(root / "processed").toc == []
