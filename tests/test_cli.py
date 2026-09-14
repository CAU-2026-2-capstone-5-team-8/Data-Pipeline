import base64
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from typer.testing import CliRunner

from data_pipeline.cli import _collect_payload, app
from data_pipeline.collectors.open_library import OpenLibraryCollector
from data_pipeline.collectors.public_book_pages import PublicBookPageCollector
from data_pipeline.collectors.publisher_documents import PublisherDocumentCollector
from data_pipeline.collectors.publisher_pages import PublisherPageCollector
from data_pipeline.models import Book, CanonicalDataset, Source
from data_pipeline.public_book_sources import public_book_source
from data_pipeline.publisher_document_sources import publisher_document_source
from data_pipeline.publisher_sources import publisher_source
from data_pipeline.storage import RawArtifact, read_dataset, write_dataset, write_raw_response
from data_pipeline.validation import validate_dataset

WILEY_HOME_FIXTURE = Path(__file__).parent / "fixtures" / "wiley_osc7_home.html"
WILEY_TOC_FIXTURE = Path(__file__).parent / "fixtures" / "wiley_osc7_toc.html"
ECAMPUS_FIXTURE = Path(__file__).parent / "fixtures" / "ecampus_stallings_os4.html"


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


def test_build_rejects_publisher_limit_other_than_one(tmp_path) -> None:
    raw_path = tmp_path / "publisher.json"
    artifact = RawArtifact(
        provider="publisher-page",
        topic="operating-systems",
        requested_limit=2,
        retrieved_at=datetime(2026, 9, 12, 12, 34, tzinfo=UTC),
        request_parameters=PublisherPageCollector.request_parameters("wiley-osc7"),
        response={},
    )
    write_raw_response(artifact, raw_path)

    result = CliRunner().invoke(
        app, ["build", "--raw", str(raw_path), "--output", str(tmp_path / "processed")]
    )

    assert result.exit_code != 0
    assert "requested_limit must be 1" in result.output


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
        "home_html": WILEY_HOME_FIXTURE.read_text(encoding="utf-8"),
        "toc_url": source_spec.toc_url,
        "toc_html": WILEY_TOC_FIXTURE.read_text(encoding="utf-8"),
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
    assert "Publisher TOC entries collected: 26" in result.output
    assert len(dataset.books) == 1
    assert len(dataset.toc) == 26
    assert len(dataset.sources) == 3
    assert validate_dataset(dataset) == []
    assert len(list((tmp_path / "raw" / "publisher_page").rglob("*.json"))) == 1


def test_collect_public_page_merges_description_and_toc(tmp_path, monkeypatch) -> None:
    source_spec = public_book_source("ecampus-stallings-os4")
    fixture_spec = replace(
        source_spec,
        expected_toc_count=12,
        expected_root_titles=(
            "Web Site for Operating Systems: Internals and Design Principles",
            "Preface",
            "PART ONE BACKGROUND",
            "APPENDICES",
            "Index",
        ),
    )
    monkeypatch.setattr("data_pipeline.normalizers.public_book_source", lambda _slug: fixture_spec)
    book = Book(
        book_id=source_spec.book_id,
        isbn_10="0130319996",
        isbn_13=source_spec.isbn_13,
        title=source_spec.title,
        authors=["William Stallings"],
        publisher="Prentice Hall",
        published_year=2000,
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
        "url": source_spec.url,
        "html": ECAMPUS_FIXTURE.read_text(encoding="utf-8"),
    }
    monkeypatch.setattr(
        "data_pipeline.cli._collect_public_book_payload",
        lambda _source: (
            payload,
            PublicBookPageCollector.request_parameters(source_spec.slug),
        ),
    )

    result = CliRunner().invoke(
        app,
        ["collect-public-page", "--source", source_spec.slug, "--data-dir", str(tmp_path)],
    )

    dataset = read_dataset(tmp_path / "processed")
    assert result.exit_code == 0
    assert "Public-page documents collected: 1" in result.output
    assert "Public-page TOC entries collected: 12" in result.output
    assert len(dataset.books) == 1
    assert len(dataset.documents) == 1
    assert len(dataset.toc) == 12
    assert len(dataset.sources) == 2
    assert validate_dataset(dataset) == []
    assert len(list((tmp_path / "raw" / "public_book_page").rglob("*.json"))) == 1


def test_collect_publisher_document_merges_extracted_text(tmp_path, monkeypatch) -> None:
    source_spec = publisher_document_source("wiley-osc7-appendix-b")
    book = Book(
        book_id=source_spec.book_id,
        isbn_10=source_spec.isbn_10,
        isbn_13="9780471694663",
        title=source_spec.title,
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
        "home_html": WILEY_HOME_FIXTURE.read_text(encoding="utf-8"),
        "referrer_url": source_spec.referrer_url,
        "referrer_html": (
            f"<h3>{source_spec.referrer_heading}</h3>"
            f'<a href="{source_spec.document_url}">Appendix</a>'
        ),
        "document_url": source_spec.document_url,
        "document_media_type": "application/pdf",
        "document_base64": base64.b64encode(b"%PDF-1.3 synthetic").decode("ascii"),
    }
    monkeypatch.setattr(
        "data_pipeline.cli._collect_publisher_document_payload",
        lambda _source: (
            payload,
            PublisherDocumentCollector.request_parameters(source_spec.slug),
        ),
    )
    extracted = "The Mach System History of the Mach System Programmer Interface"
    monkeypatch.setattr("data_pipeline.normalizers._extract_pdf_text", lambda _pdf: extracted)

    result = CliRunner().invoke(
        app,
        [
            "collect-publisher-document",
            "--source",
            source_spec.slug,
            "--data-dir",
            str(tmp_path),
        ],
    )

    dataset = read_dataset(tmp_path / "processed")
    assert result.exit_code == 0
    assert "Publisher documents collected: 1" in result.output
    assert "Other document:           1" in result.output
    assert len(dataset.books) == 1
    assert len(dataset.documents) == 1
    assert dataset.documents[0].text == extracted
    assert len(dataset.sources) == 2
    assert validate_dataset(dataset) == []
    assert len(list((tmp_path / "raw" / "publisher_document").rglob("*.json"))) == 1
