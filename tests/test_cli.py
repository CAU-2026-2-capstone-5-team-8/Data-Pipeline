from datetime import UTC, datetime

from typer.testing import CliRunner

from data_pipeline.cli import _collect_payload, app
from data_pipeline.collectors.open_library import OpenLibraryCollector
from data_pipeline.models import Book, CanonicalDataset, Source
from data_pipeline.publisher_sources import publisher_source
from data_pipeline.storage import RawArtifact, read_dataset, write_dataset, write_raw_response
from data_pipeline.validation import validate_dataset


def test_build_rejects_topic_query_mismatch(tmp_path) -> None:
    raw_path = tmp_path / "raw.json"
    artifact = RawArtifact(
        provider="open-library",
        topic="linear-algebra",
        requested_limit=5,
        retrieved_at=datetime(2026, 9, 12, 12, 34, tzinfo=UTC),
        request_parameters={"title": "operating systems", "limit": 20},
        response={"docs": []},
    )
    write_raw_response(artifact, raw_path)

    result = CliRunner().invoke(
        app, ["build", "--raw", str(raw_path), "--output", str(tmp_path / "processed")]
    )

    assert result.exit_code != 0
    assert "topic/query mismatch" in result.output


def test_build_reports_invalid_provider_collection_without_traceback(tmp_path) -> None:
    raw_path = tmp_path / "raw.json"
    artifact = RawArtifact(
        provider="open-library",
        topic="linear-algebra",
        requested_limit=5,
        retrieved_at=datetime(2026, 9, 12, 12, 34, tzinfo=UTC),
        request_parameters=OpenLibraryCollector.search_parameters("linear-algebra", 20),
        response={"docs": None},
    )
    write_raw_response(artifact, raw_path)

    result = CliRunner().invoke(
        app, ["build", "--raw", str(raw_path), "--output", str(tmp_path / "processed")]
    )

    assert result.exit_code != 0
    assert "invalid 'docs' collection" in result.output
    assert "Traceback" not in result.output


def test_collect_payload_includes_open_library_work_details(monkeypatch) -> None:
    class FakeOpenLibraryCollector:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        @staticmethod
        def search_parameters(topic, candidate_limit):
            return {"title": topic, "limit": candidate_limit}

        @staticmethod
        def search_books(topic, candidate_limit):
            return {"docs": [{"key": "/works/OL1W"}]}

        @staticmethod
        def fetch_edition_details(payload, candidate_limit):
            return {"/books/OL1M": {"title": "Fixture"}}

        @staticmethod
        def fetch_work_details(payload, candidate_limit):
            return {"/works/OL1W": {"description": "Public description"}}

    monkeypatch.setattr("data_pipeline.cli.OpenLibraryCollector", FakeOpenLibraryCollector)

    payload, _parameters = _collect_payload(
        "open-library", "operating-systems", 20, edition_detail_limit=8
    )

    assert payload["work_details"]["/works/OL1W"]["description"] == "Public description"


def test_collect_publisher_merges_exact_book_evidence(tmp_path, monkeypatch) -> None:
    source_spec = publisher_source("wiley-osc7")
    book = Book(
        book_id=source_spec.book_id,
        isbn_10=source_spec.isbn_10,
        isbn_13="9780471694663",
        title="Operating system concepts",
        subtitle=None,
        authors=["Abraham Silberschatz"],
        publisher="Wiley",
        published_year=2005,
        language="en",
        topics=["computer-science", "operating-systems"],
    )
    metadata_source = Source(
        source_id="source_metadata",
        book_id=book.book_id,
        provider="fixture",
        source_type="metadata_api",
        url="https://example.test/book",
        retrieved_at=datetime(2026, 9, 12, tzinfo=UTC),
        content_hash="sha256:" + "a" * 64,
    )
    write_dataset(
        CanonicalDataset(books=[book], documents=[], toc=[], sources=[metadata_source]),
        tmp_path / "processed",
    )
    payload = {
        "source_slug": source_spec.slug,
        "home_url": source_spec.home_url,
        "home_html": "Operating System Concepts, Seventh Edition 0471694665",
        "toc_url": source_spec.toc_url,
        "toc_html": '<div class="chapterTitle"><h3>Chapter 1: Introduction</h3></div>',
    }
    parameters = {
        "source": source_spec.slug,
        "home_url": source_spec.home_url,
        "toc_url": source_spec.toc_url,
    }
    monkeypatch.setattr(
        "data_pipeline.cli._collect_publisher_payload",
        lambda _source: (payload, parameters),
    )

    result = CliRunner().invoke(
        app,
        ["collect-publisher", "--source", source_spec.slug, "--data-dir", str(tmp_path)],
    )

    dataset = read_dataset(tmp_path / "processed")
    assert result.exit_code == 0
    assert "Publisher TOC entries collected: 1" in result.output
    assert len(dataset.books) == 1
    assert len(dataset.toc) == 1
    assert validate_dataset(dataset) == []
    assert len(list((tmp_path / "raw" / "publisher_page").rglob("*.json"))) == 1
