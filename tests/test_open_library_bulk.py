import gzip
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

import data_pipeline.open_library_bulk as ol_bulk
from data_pipeline.cli import app
from data_pipeline.models import Book, CanonicalDataset, Source
from data_pipeline.open_library_bulk import (
    EDITION_TYPE,
    WORK_TYPE,
    OpenLibraryDumpFile,
    build_open_library_index,
    build_targeted_open_library_index,
    canonical_toc_evidence,
    download_dump_file,
    inspect_toc_resolution,
    iter_dump,
    iter_dump_candidates,
    load_dump_manifest,
    parse_dump_line,
    resolve_toc,
    verify_dump_file,
)
from data_pipeline.storage import read_dataset, write_dataset

FIXTURE = Path(__file__).parent / "fixtures" / "open_library_bulk_records.json"
MANIFEST = Path(__file__).parents[1] / "configs" / "external" / "open-library-2026-08-31.json"


def _dump_fixture(tmp_path: Path) -> tuple[Path, Path]:
    records = json.loads(FIXTURE.read_text(encoding="utf-8"))
    paths = []
    for name, record_type in (("works", WORK_TYPE), ("editions", EDITION_TYPE)):
        path = tmp_path / f"{name}.txt.gz"
        with gzip.open(path, "wt", encoding="utf-8") as stream:
            for revision, record in enumerate(records[name], start=1):
                stream.write(
                    "\t".join(
                        [
                            record_type,
                            record["key"],
                            str(revision),
                            "2026-08-31T00:00:00.000000",
                            json.dumps(record, ensure_ascii=False, separators=(",", ":")),
                        ]
                    )
                    + "\n"
                )
        paths.append(path)
    return paths[0], paths[1]


@pytest.fixture
def bulk_index(tmp_path: Path) -> Path:
    works, editions = _dump_fixture(tmp_path)
    path = tmp_path / "open-library.sqlite"
    counts = build_open_library_index(
        editions_dump=editions,
        works_dump=works,
        output_path=path,
        manifest=load_dump_manifest(MANIFEST),
    )
    assert counts == {"works": 3, "editions": 10, "isbns": 11, "toc_editions": 6}
    return path


def test_dump_parser_reads_edition_fields_and_missing_optionals(tmp_path: Path) -> None:
    _works, editions = _dump_fixture(tmp_path)

    records = list(iter_dump(editions, expected_type=EDITION_TYPE))

    assert records[0].value["isbn_10"] == ["0306406152"]
    assert records[0].value["works"] == [{"key": "/works/OL-EXACT-W"}]
    assert records[0].value["table_of_contents"][0]["title"] == "Foundations"
    assert records[-1].value == {"key": "/books/OL-MINIMAL-M", "title": "Minimal Edition"}


def test_dump_candidate_prefilter_only_parses_matching_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _works, editions = _dump_fixture(tmp_path)
    monkeypatch.setattr(ol_bulk, "DUMP_SCAN_CHUNK_SIZE", 31)
    monkeypatch.setattr(ol_bulk.shutil, "which", lambda _command: None)

    records = list(
        iter_dump_candidates(
            editions,
            expected_type=EDITION_TYPE,
            needles={"9781292025773"},
        )
    )

    assert [record.key for record in records] == ["/books/OL-TARGET-M"]


def test_targeted_prefilter_and_index_normalize_formatted_isbn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "formatted-edition.txt.gz"
    record = {
        "key": "/books/OL-FORMATTED-M",
        "title": "Formatted ISBN Book",
        "isbn_10": ["013359162x"],
        "isbn_13": ["978-1-292-02577-3"],
        "works": [{"key": "/works/OL-FORMATTED-W"}],
        "table_of_contents": [
            {"level": 0, "title": "One"},
            {"level": 0, "title": "Two"},
            {"level": 0, "title": "Three"},
        ],
    }
    with gzip.open(path, "wt", encoding="utf-8") as stream:
        stream.write(
            "\t".join(
                [
                    EDITION_TYPE,
                    record["key"],
                    "1",
                    "2026-08-31T00:00:00.000000",
                    json.dumps(record, separators=(",", ":")),
                ]
            )
            + "\n"
        )
    monkeypatch.setattr(ol_bulk.shutil, "which", lambda _command: None)

    candidates = list(
        iter_dump_candidates(path, expected_type=EDITION_TYPE, needles={"9781292025773"})
    )
    index = tmp_path / "formatted.sqlite"
    counts = build_targeted_open_library_index(
        editions_dump=path,
        output_path=index,
        manifest=load_dump_manifest(MANIFEST),
        target_isbns={"9781292025773"},
    )

    assert [candidate.key for candidate in candidates] == ["/books/OL-FORMATTED-M"]
    assert counts["matched_target_isbns"] == 1
    assert resolve_toc(index, "978-1-292-02577-3") is not None
    with ol_bulk._connect_index(index) as connection:
        indexed_isbns = [
            row[0] for row in connection.execute("SELECT isbn FROM edition_isbns ORDER BY isbn")
        ]
        assert indexed_isbns == [
            "013359162X",
            "9781292025773",
        ]


@pytest.mark.parametrize(
    "line",
    [
        "too\tfew\tcolumns",
        f"{EDITION_TYPE}\t/books/OL1M\tbad\t2026-01-01\t{{}}",
        f"{EDITION_TYPE}\t/books/OL1M\t1\t2026-01-01\tnot-json",
        f'{EDITION_TYPE}\t/books/OL1M\t1\t2026-01-01\t{{"key":"/books/OTHER"}}',
    ],
)
def test_dump_parser_rejects_malformed_records(line: str) -> None:
    with pytest.raises(ValueError):
        parse_dump_line(line, expected_type=EDITION_TYPE)


def test_index_resolves_exact_edition_toc_first(bulk_index: Path) -> None:
    result = resolve_toc(bulk_index, "978-0-306-40615-7")

    assert result is not None
    assert result.tier == "exact_edition_toc"
    assert result.target_edition_key == "/books/OL-EXACT-M"
    assert result.source_edition_key == result.target_edition_key
    assert result.source_isbns == ("0306406152", "9780306406157")


def test_targeted_index_keeps_only_target_work_editions(tmp_path: Path) -> None:
    _works, editions = _dump_fixture(tmp_path)
    path = tmp_path / "targeted.sqlite"

    counts = build_targeted_open_library_index(
        editions_dump=editions,
        output_path=path,
        manifest=load_dump_manifest(MANIFEST),
        target_isbns={"9781292025773", "9780306406157", "9789999999991"},
    )

    assert counts["target_isbns"] == 3
    assert counts["matched_target_isbns"] == 2
    assert counts["target_works"] == 2
    assert counts["editions"] == 7
    assert resolve_toc(path, "9781292025773") is not None
    assert resolve_toc(path, "9780000000040") is None


def test_index_resolves_validated_same_work_alternate(bulk_index: Path) -> None:
    result = resolve_toc(bulk_index, "9781292025773")

    assert result is not None
    assert result.tier == "same_work_alternate_edition_toc"
    assert result.source_edition_key == "/books/OL-ALT-M"
    assert result.source_isbns == ("013359162X", "9780133591620")
    assert "open_library_work_relation" in result.match_basis
    assert "author_key_overlap" in result.match_basis


def test_resolution_inspection_distinguishes_exact_and_alternate(bulk_index: Path) -> None:
    exact = inspect_toc_resolution(bulk_index, "9780306406157")
    alternate = inspect_toc_resolution(bulk_index, "9781292025773")

    assert exact.exact_editions_count == 1
    assert exact.exact_toc_found is True
    assert exact.alternate_toc_found is False
    assert alternate.eligible_exact_editions_count == 1
    assert alternate.work_keys == ("/works/OL-ALT-W",)
    assert alternate.alternate_editions_count == 5
    assert alternate.alternate_toc_found is True
    assert alternate.selected_alternate_edition == "/books/OL-ALT-M"


def test_index_rejects_solution_manual_isbn(bulk_index: Path) -> None:
    assert resolve_toc(bulk_index, "9780136054276") is None


def test_index_rejects_different_volume(bulk_index: Path) -> None:
    assert resolve_toc(bulk_index, "9780000000040") is None


def test_index_refuses_to_overwrite_reproducible_artifact(bulk_index: Path) -> None:
    manifest = load_dump_manifest(MANIFEST)
    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        build_open_library_index(
            editions_dump=bulk_index,
            works_dump=bulk_index,
            output_path=bulk_index,
            manifest=manifest,
        )


def test_alternate_provenance_survives_canonical_conversion(bulk_index: Path) -> None:
    result = resolve_toc(bulk_index, "9781292025773")
    assert result is not None
    target = Book(
        book_id="isbn13:9781292025773",
        isbn_10="1292025778",
        isbn_13="9781292025773",
        title="Modern Operating Systems",
        subtitle="Pearson New International Edition",
        authors=["Andrew S. Tanenbaum", "Herbert Bos"],
        publisher="Pearson",
        published_year=2013,
        language="en",
        topics=["computer-science", "operating-systems"],
    )

    evidence = canonical_toc_evidence(
        result,
        target_book=target,
        retrieved_at=datetime(2026, 9, 21, tzinfo=UTC),
        dump_date="2026-08-31",
    )

    assert len(evidence.toc) == 3
    assert evidence.sources[0].book_id == target.book_id
    assert evidence.sources[0].evidence is not None
    assert evidence.sources[0].evidence.tier == "same_work_alternate_edition_toc"
    assert evidence.sources[0].evidence.same_edition is False
    assert evidence.sources[0].evidence.source_edition_id == "/books/OL-ALT-M"
    assert evidence.sources[0].evidence.target_isbn == "9781292025773"


def test_bulk_enrichment_command_only_fills_missing_toc(bulk_index: Path, tmp_path: Path) -> None:
    dataset_dir = tmp_path / "processed"
    target = Book(
        book_id="isbn13:9781292025773",
        isbn_10="1292025778",
        isbn_13="9781292025773",
        title="Modern Operating Systems",
        subtitle="Pearson New International Edition",
        authors=["Andrew S. Tanenbaum", "Herbert Bos"],
        publisher="Pearson",
        published_year=2013,
        language="en",
        topics=["computer-science", "operating-systems"],
    )
    metadata_source = Source(
        source_id="source_fixture_metadata",
        book_id=target.book_id,
        provider="fixture",
        source_type="metadata_api",
        url="https://example.test/book",
        retrieved_at=datetime(2026, 9, 1, tzinfo=UTC),
        content_hash="sha256:" + "0" * 64,
    )
    write_dataset(
        CanonicalDataset(books=[target], documents=[], toc=[], sources=[metadata_source]),
        dataset_dir,
    )

    result = CliRunner().invoke(
        app,
        [
            "enrich-open-library-bulk",
            "--dataset-dir",
            str(dataset_dir),
            "--index",
            str(bulk_index),
        ],
    )

    assert result.exit_code == 0, result.output
    enriched = read_dataset(dataset_dir)
    assert len(enriched.toc) == 3
    bulk_source = next(source for source in enriched.sources if source.provider == "open_library")
    assert bulk_source.evidence is not None
    assert bulk_source.evidence.tier == "same_work_alternate_edition_toc"
    report = json.loads((tmp_path / "reports" / "open-library-bulk-enrichment.json").read_text())
    assert report["before_toc_books"] == 0
    assert report["after_toc_books"] == 1


def _dump_spec(content: bytes) -> OpenLibraryDumpFile:
    return OpenLibraryDumpFile(
        kind="editions",
        url="https://archive.org/download/fixture/editions.txt.gz",
        filename="editions.txt.gz",
        compressed_size=len(content),
        md5=hashlib.md5(content, usedforsecurity=False).hexdigest(),
        sha1=hashlib.sha1(content, usedforsecurity=False).hexdigest(),
    )


def test_dump_download_is_atomic_and_reuses_verified_file(tmp_path: Path) -> None:
    content = b"complete fixture dump"
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, content=content, request=request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert download_dump_file(_dump_spec(content), tmp_path, client=client) == "downloaded"
        assert download_dump_file(_dump_spec(content), tmp_path, client=client) == "already_present"

    assert len(requests) == 1
    assert (tmp_path / "editions.txt.gz").read_bytes() == content
    assert not (tmp_path / "editions.txt.gz.part").exists()


def test_dump_size_check_can_skip_redundant_checksum(tmp_path: Path) -> None:
    expected = b"expected"
    path = tmp_path / "editions.txt.gz"
    path.write_bytes(b"tampered")
    specification = _dump_spec(expected)

    assert verify_dump_file(path, specification, checksum=False) == []
    assert verify_dump_file(path, specification) == ["sha1_mismatch"]


def test_dump_download_resumes_partial_file(tmp_path: Path) -> None:
    content = b"0123456789"
    partial = tmp_path / "editions.txt.gz.part"
    partial.write_bytes(content[:4])

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["range"] == "bytes=4-"
        return httpx.Response(
            206,
            content=content[4:],
            headers={"content-range": "bytes 4-9/10"},
            request=request,
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        status = download_dump_file(_dump_spec(content), tmp_path, client=client)

    assert status == "resumed"
    assert (tmp_path / "editions.txt.gz").read_bytes() == content


def test_dump_download_preserves_partial_on_network_failure(tmp_path: Path) -> None:
    content = b"0123456789"

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("fixture timeout", request=request)

    with (
        httpx.Client(transport=httpx.MockTransport(handler)) as client,
        pytest.raises(httpx.ReadTimeout),
    ):
        download_dump_file(_dump_spec(content), tmp_path, client=client)

    assert not (tmp_path / "editions.txt.gz").exists()
