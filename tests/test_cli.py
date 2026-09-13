from datetime import UTC, datetime

from typer.testing import CliRunner

from data_pipeline.cli import app
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
