from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from data_pipeline.cli import app
from data_pipeline.collectors.base import InvalidProviderResponse
from data_pipeline.collectors.hathitrust import HathiTrustCollector
from data_pipeline.models import Book, CanonicalDataset, Source
from data_pipeline.normalizers import normalize_hathitrust_response
from data_pipeline.storage import read_dataset, write_dataset

RETRIEVED_AT = datetime(2026, 9, 21, 12, 0, tzinfo=UTC)


def _match_response(isbn: str = "9780132017992") -> dict:
    return {
        f"isbn:{isbn}": {
            "records": {
                "000556966": {
                    "recordURL": "https://catalog.hathitrust.org/Record/000556966",
                    "titles": ["The design of the UNIX operating system"],
                    "isbns": [isbn, isbn],
                    "oclcs": ["14061640"],
                    "publishDates": ["1986"],
                }
            },
            "items": [
                {
                    "orig": "University of Michigan",
                    "fromRecord": "000556966",
                    "htid": "mdp.39015036954827",
                    "rightsCode": "ic",
                    "usRightsString": "Limited (search-only)",
                }
            ],
        }
    }


def _empty_response(isbn: str = "9780132017992") -> dict:
    return {f"isbn:{isbn}": {"records": [], "items": []}}


# --- Collector ---------------------------------------------------------------


def test_lookup_isbn_requests_the_expected_url() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json=_match_response(), request=request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        payload = HathiTrustCollector(client=client).lookup_isbn("9780132017992")

    assert str(captured[0].url) == (
        "https://catalog.hathitrust.org/api/volumes/brief/json/isbn:9780132017992"
    )
    assert payload == _match_response()


def test_collector_reports_malformed_success_response() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, text="not-json", request=request)
    )
    with (
        httpx.Client(transport=transport) as client,
        pytest.raises(InvalidProviderResponse, match="malformed JSON"),
    ):
        HathiTrustCollector(client=client).lookup_isbn("9780132017992")


# --- Normalizer ----------------------------------------------------------------


def test_normalize_builds_a_corroborating_source_without_a_license() -> None:
    source = normalize_hathitrust_response(
        _match_response(),
        isbn="9780132017992",
        book_id="isbn13:9780132017992",
        retrieved_at=RETRIEVED_AT,
    )

    assert source is not None
    assert source.book_id == "isbn13:9780132017992"
    assert source.provider == "hathitrust"
    assert source.source_type == "other"
    assert source.url == "https://catalog.hathitrust.org/Record/000556966"
    assert source.external_id == "000556966"
    assert source.license is None
    assert "rights: ic" in source.rights_note
    assert "no item text" in source.rights_note
    assert source.content_hash.startswith("sha256:")


def test_normalize_returns_none_when_hathitrust_has_no_record() -> None:
    source = normalize_hathitrust_response(
        _empty_response(),
        isbn="9780132017992",
        book_id="isbn13:9780132017992",
        retrieved_at=RETRIEVED_AT,
    )
    assert source is None


def test_normalize_requires_the_queried_isbn_key() -> None:
    with pytest.raises(InvalidProviderResponse, match="isbn:0000000000000"):
        normalize_hathitrust_response(
            _match_response(),
            isbn="0000000000000",
            book_id="isbn13:0000000000000",
            retrieved_at=RETRIEVED_AT,
        )


def test_normalize_rejects_a_record_without_recordurl() -> None:
    response = _match_response()
    del response["isbn:9780132017992"]["records"]["000556966"]["recordURL"]

    with pytest.raises(InvalidProviderResponse, match="recordURL"):
        normalize_hathitrust_response(
            response,
            isbn="9780132017992",
            book_id="isbn13:9780132017992",
            retrieved_at=RETRIEVED_AT,
        )


def test_normalize_picks_the_lexicographically_first_record_deterministically() -> None:
    response = _match_response()
    response["isbn:9780132017992"]["records"]["999999999"] = {
        "recordURL": "https://catalog.hathitrust.org/Record/999999999",
    }

    first = normalize_hathitrust_response(
        response,
        isbn="9780132017992",
        book_id="isbn13:9780132017992",
        retrieved_at=RETRIEVED_AT,
    )
    second = normalize_hathitrust_response(
        response,
        isbn="9780132017992",
        book_id="isbn13:9780132017992",
        retrieved_at=RETRIEVED_AT,
    )

    assert first.external_id == second.external_id == "000556966"


def test_normalize_summarizes_multiple_distinct_rights_codes_sorted() -> None:
    response = _match_response()
    response["isbn:9780132017992"]["items"].append({"rightsCode": "pd", "fromRecord": "000556966"})

    source = normalize_hathitrust_response(
        response,
        isbn="9780132017992",
        book_id="isbn13:9780132017992",
        retrieved_at=RETRIEVED_AT,
    )

    assert "rights: ic, pd" in source.rights_note


# --- CLI -------------------------------------------------------------------


def _seed_dataset(processed_dir: Path, *, isbn_13: str, book_id: str) -> None:
    book = Book(
        book_id=book_id,
        isbn_10=None,
        isbn_13=isbn_13,
        title="Design of the UNIX Operating System",
        authors=["Maurice J. Bach"],
        publisher=None,
        published_year=1986,
        language="en",
        topics=["computer-science", "operating-systems"],
    )
    source = Source(
        source_id="source_seed",
        book_id=book_id,
        provider="test_seed",
        source_type="other",
        url="https://example.org/seed",
        retrieved_at=RETRIEVED_AT,
        license=None,
        rights_note=None,
        content_hash="sha256:" + "0" * 64,
    )
    write_dataset(
        CanonicalDataset(books=[book], documents=[], toc=[], sources=[source]), processed_dir
    )


class _FakeHathiTrustCollector:
    def __init__(self, response: dict) -> None:
        self._response = response

    def __enter__(self) -> "_FakeHathiTrustCollector":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def lookup_isbn(self, _isbn: str) -> dict:
        return self._response


def test_enrich_bibliography_adds_a_source_for_a_known_isbn(tmp_path, monkeypatch) -> None:
    _seed_dataset(tmp_path / "processed", isbn_13="9780132017992", book_id="isbn13:9780132017992")
    monkeypatch.setattr(
        "data_pipeline.cli.HathiTrustCollector",
        lambda: _FakeHathiTrustCollector(_match_response()),
    )

    result = CliRunner().invoke(
        app, ["enrich-bibliography", "--isbn", "9780132017992", "--data-dir", str(tmp_path)]
    )

    assert result.exit_code == 0, result.output
    dataset = read_dataset(tmp_path / "processed")
    hathitrust_sources = [s for s in dataset.sources if s.provider == "hathitrust"]
    assert len(hathitrust_sources) == 1
    assert hathitrust_sources[0].book_id == "isbn13:9780132017992"


def test_enrich_bibliography_is_idempotent(tmp_path, monkeypatch) -> None:
    _seed_dataset(tmp_path / "processed", isbn_13="9780132017992", book_id="isbn13:9780132017992")
    monkeypatch.setattr(
        "data_pipeline.cli.HathiTrustCollector",
        lambda: _FakeHathiTrustCollector(_match_response()),
    )
    runner = CliRunner()
    first = runner.invoke(
        app, ["enrich-bibliography", "--isbn", "9780132017992", "--data-dir", str(tmp_path)]
    )
    second = runner.invoke(
        app, ["enrich-bibliography", "--isbn", "9780132017992", "--data-dir", str(tmp_path)]
    )

    assert first.exit_code == 0
    assert second.exit_code == 0
    assert "already recorded" in second.output
    dataset = read_dataset(tmp_path / "processed")
    assert sum(s.provider == "hathitrust" for s in dataset.sources) == 1


def test_enrich_bibliography_rejects_an_isbn_outside_the_dataset(tmp_path, monkeypatch) -> None:
    _seed_dataset(tmp_path / "processed", isbn_13="9780132017992", book_id="isbn13:9780132017992")

    result = CliRunner().invoke(
        app, ["enrich-bibliography", "--isbn", "0000000000000", "--data-dir", str(tmp_path)]
    )

    assert result.exit_code != 0
    assert "no canonical book has ISBN" in result.output


def test_enrich_bibliography_reports_no_match_and_preserves_raw(tmp_path, monkeypatch) -> None:
    _seed_dataset(tmp_path / "processed", isbn_13="9780132017992", book_id="isbn13:9780132017992")
    monkeypatch.setattr(
        "data_pipeline.cli.HathiTrustCollector",
        lambda: _FakeHathiTrustCollector(_empty_response()),
    )

    result = CliRunner().invoke(
        app, ["enrich-bibliography", "--isbn", "9780132017992", "--data-dir", str(tmp_path)]
    )

    assert result.exit_code == 1
    assert "no record" in result.output
    assert "preserved at" in result.output
    dataset = read_dataset(tmp_path / "processed")
    assert not any(s.provider == "hathitrust" for s in dataset.sources)
    raw_files = list((tmp_path / "raw" / "hathitrust").rglob("*.json"))
    assert len(raw_files) == 1


def test_enrich_bibliography_reports_normalization_failure_and_preserves_raw(
    tmp_path, monkeypatch
) -> None:
    _seed_dataset(tmp_path / "processed", isbn_13="9780132017992", book_id="isbn13:9780132017992")
    malformed = _match_response()
    del malformed["isbn:9780132017992"]["records"]["000556966"]["recordURL"]
    monkeypatch.setattr(
        "data_pipeline.cli.HathiTrustCollector",
        lambda: _FakeHathiTrustCollector(malformed),
    )

    result = CliRunner().invoke(
        app, ["enrich-bibliography", "--isbn", "9780132017992", "--data-dir", str(tmp_path)]
    )

    assert result.exit_code != 0
    assert "preserved" in result.output
    assert len(list((tmp_path / "raw" / "hathitrust").rglob("*.json"))) == 1
