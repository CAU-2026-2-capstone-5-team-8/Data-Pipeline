from datetime import UTC, datetime

from typer.testing import CliRunner

from data_pipeline.cli import _collect_payload, app
from data_pipeline.collectors.open_library import OpenLibraryCollector
from data_pipeline.storage import RawArtifact, write_raw_response


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
