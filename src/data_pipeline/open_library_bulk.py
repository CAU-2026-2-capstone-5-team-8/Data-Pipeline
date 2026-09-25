"""Streaming Open Library dump projection and local ISBN/Work resolver.

The index is an ignored, reproducible acceleration structure. Canonical consumers do not
depend on its SQLite schema.
"""

import gzip
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from data_pipeline.identifiers import normalize_bibliographic_text, sha256_json, stable_id
from data_pipeline.models import Book, CanonicalDataset, EvidenceProvenance, Source, TocEntry

EDITION_TYPE = "/type/edition"
WORK_TYPE = "/type/work"
PARSER_VERSION = "open-library-bulk-v1"
DUMP_SCAN_CHUNK_SIZE = 16 * 1024 * 1024
SUPPLEMENT_MARKERS = (
    "solution manual",
    "solutions manual",
    "student solution",
    "student solutions",
    "instructor manual",
    "instructors manual",
    "workbook",
    "study guide",
    "companion",
)


class OpenLibraryDumpFile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["editions", "works"]
    url: str = Field(pattern=r"^https://")
    filename: str = Field(min_length=1)
    compressed_size: int = Field(gt=0)
    md5: str = Field(pattern=r"^[0-9a-f]{32}$")
    sha1: str = Field(pattern=r"^[0-9a-f]{40}$")


class OpenLibraryDumpManifest(BaseModel):
    """Pinned official inputs for one reproducible local index."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    provider: Literal["open_library"]
    dataset_name: str = Field(min_length=1)
    dump_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    official_page_url: str = Field(pattern=r"^https://")
    archive_metadata_url: str = Field(pattern=r"^https://")
    license_url: str = Field(pattern=r"^https://")
    license_note: str = Field(min_length=1)
    update_frequency: Literal["monthly"]
    source_format: Literal["gzip_tsv_json"]
    parser_version: Literal["open-library-bulk-v1"]
    retrieved_at: datetime
    files: list[OpenLibraryDumpFile] = Field(min_length=2, max_length=2)

    @field_validator("retrieved_at")
    @classmethod
    def retrieved_at_must_include_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("retrieved_at must include a timezone")
        return value

    @field_validator("files")
    @classmethod
    def file_kinds_must_be_complete(
        cls, files: list[OpenLibraryDumpFile]
    ) -> list[OpenLibraryDumpFile]:
        if {item.kind for item in files} != {"editions", "works"}:
            raise ValueError("manifest must contain exactly one editions and one works dump")
        return files


@dataclass(frozen=True)
class DumpRecord:
    record_type: str
    key: str
    revision: int
    last_modified: str
    value: dict[str, Any]


@dataclass(frozen=True)
class TocResolution:
    target_isbn: str
    target_edition_key: str
    target_title: str
    target_author_ids: tuple[str, ...]
    work_key: str
    tier: Literal["exact_edition_toc", "same_work_alternate_edition_toc"]
    source_edition_key: str
    source_isbns: tuple[str, ...]
    source_title: str
    source_author_ids: tuple[str, ...]
    source_publish_date: str | None
    toc: tuple[dict[str, Any], ...]
    match_basis: tuple[str, ...]
    validation_status: Literal["strong", "acceptable"]


@dataclass(frozen=True)
class TocResolutionInspection:
    """Auditable availability facts for one ISBN lookup in a local bulk index."""

    target_isbn: str
    exact_editions_count: int
    eligible_exact_editions_count: int
    exact_toc_found: bool
    work_keys: tuple[str, ...]
    alternate_editions_count: int
    alternate_toc_found: bool
    selected_alternate_edition: str | None


def load_dump_manifest(path: Path) -> OpenLibraryDumpManifest:
    try:
        return OpenLibraryDumpManifest.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"external dataset manifest is invalid: {path}: {exc}") from exc


def parse_dump_line(line: str, *, expected_type: str | None = None) -> DumpRecord:
    """Parse one five-column Open Library dump line without accepting silent truncation."""
    columns = line.rstrip("\n").split("\t", 4)
    if len(columns) != 5:
        raise ValueError("Open Library dump row must contain five TSV columns")
    record_type, key, raw_revision, last_modified, raw_json = columns
    if expected_type is not None and record_type != expected_type:
        raise ValueError(f"unexpected Open Library record type: {record_type}")
    try:
        revision = int(raw_revision)
        value = json.loads(raw_json)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("malformed Open Library dump row") from exc
    if not isinstance(value, dict):
        raise ValueError("Open Library dump JSON must be an object")
    if value.get("key") != key:
        raise ValueError("Open Library dump key does not match JSON record")
    return DumpRecord(record_type, key, revision, last_modified, value)


def iter_dump(path: Path, *, expected_type: str) -> Iterator[DumpRecord]:
    """Stream a gzip TSV dump; no decompressed copy is created."""
    with gzip.open(path, mode="rt", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            try:
                yield parse_dump_line(line, expected_type=expected_type)
            except ValueError as exc:
                raise ValueError(f"invalid dump record at {path}:{line_number}: {exc}") from exc


def iter_dump_candidates(
    path: Path, *, expected_type: str, needles: set[str]
) -> Iterator[DumpRecord]:
    """Parse only rows containing a target identifier while still streaming the full gzip.

    Targeted benchmark builds must decompress the dump once per pass, but parsing every
    JSON object is avoidable. The exact ISBN/Work checks after parsing remain authoritative;
    this byte prefilter only discards rows that cannot possibly match.
    """
    patterns = tuple(_candidate_pattern(value) for value in sorted(needles) if value)
    if not patterns:
        return

    ripgrep = shutil.which("rg")
    if ripgrep is not None:
        command = [
            ripgrep,
            "--search-zip",
            "--text",
            "--no-filename",
            "--no-heading",
        ]
        for pattern in patterns:
            command.extend(("-e", pattern))
        command.extend(("--", str(path)))
        process = subprocess.Popen(  # noqa: S603 - fixed executable and arguments only
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        assert process.stdout is not None
        yielded_candidate = False
        try:
            for candidate_number, line in enumerate(process.stdout, start=1):
                try:
                    yielded_candidate = True
                    yield parse_dump_line(line, expected_type=expected_type)
                except ValueError as exc:
                    raise ValueError(
                        f"invalid candidate record from {path} #{candidate_number}: {exc}"
                    ) from exc
        except BaseException:
            process.terminate()
            process.wait()
            if process.stderr is not None:
                process.stderr.close()
            raise
        finally:
            process.stdout.close()
        stderr = process.stderr.read() if process.stderr is not None else ""
        return_code = process.wait()
        if process.stderr is not None:
            process.stderr.close()
        if return_code not in {0, 1}:
            raise ValueError(f"ripgrep could not scan Open Library dump {path}: {stderr.strip()}")
        # Some rg builds accept --search-zip but have no gzip decompressor available.
        # They report an ordinary no-match exit (1), so use the deterministic Python
        # scanner instead of silently treating every target ISBN as absent.
        if yielded_candidate:
            return

    candidate_pattern = re.compile("|".join(patterns).encode("ascii"))

    def matching_lines(block: bytes, first_line_number: int) -> Iterator[DumpRecord]:
        spans: set[tuple[int, int]] = set()
        for match in candidate_pattern.finditer(block):
            start = block.rfind(b"\n", 0, match.start()) + 1
            end = block.find(b"\n", match.end())
            if end < 0:
                end = len(block)
            spans.add((start, end))
        for start, end in sorted(spans):
            line_number = first_line_number + block.count(b"\n", 0, start)
            try:
                line = block[start:end].decode("utf-8")
                yield parse_dump_line(line, expected_type=expected_type)
            except (UnicodeDecodeError, ValueError) as exc:
                raise ValueError(f"invalid dump record at {path}:{line_number}: {exc}") from exc

    carry = b""
    first_line_number = 1
    with gzip.open(path, mode="rb") as stream:
        while chunk := stream.read(DUMP_SCAN_CHUNK_SIZE):
            block = carry + chunk
            final_newline = block.rfind(b"\n")
            if final_newline < 0:
                carry = block
                continue
            complete = block[: final_newline + 1]
            carry = block[final_newline + 1 :]
            yield from matching_lines(complete, first_line_number)
            first_line_number += complete.count(b"\n")
        if carry:
            yield from matching_lines(carry, first_line_number)


def _normalized_isbn(value: str) -> str:
    """Normalize dump ISBN spelling before matching or indexing."""
    return re.sub(r"[^0-9Xx]", "", value).upper()


def _candidate_pattern(value: str) -> str:
    """Allow common ISBN punctuation/case variants without weakening other key matches."""
    normalized = _normalized_isbn(value)
    if (
        re.fullmatch(r"[0-9Xx -]+", value)
        and len(normalized) in {10, 13}
        and re.fullmatch(r"[0-9]{9}[0-9X]|[0-9]{13}", normalized)
    ):
        characters = ["[Xx]" if character == "X" else character for character in normalized]
        return "[- ]*".join(characters)
    return re.escape(value)


def _reference_keys(value: Any, *, nested: str | None = None) -> list[str]:
    if not isinstance(value, list):
        return []
    keys: list[str] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        if nested is not None:
            item = item.get(nested)
            if not isinstance(item, dict):
                continue
        key = item.get("key")
        if isinstance(key, str) and key.strip():
            keys.append(key.strip())
    return list(dict.fromkeys(keys))


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return list(
        dict.fromkeys(item.strip() for item in value if isinstance(item, str) and item.strip())
    )


def _toc(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    result = []
    for item in value:
        if not isinstance(item, dict):
            continue
        title = item.get("title")
        level = item.get("level")
        if not isinstance(title, str) or not title.strip():
            continue
        if not isinstance(level, int) or isinstance(level, bool) or level < 0:
            continue
        normalized = {"title": title.strip(), "level": level}
        for optional in ("label", "pagenum"):
            optional_value = item.get(optional)
            if isinstance(optional_value, str) and optional_value.strip():
                normalized[optional] = optional_value.strip()
        result.append(normalized)
    return result


def toc_is_usable(value: list[dict[str, Any]]) -> bool:
    """Require a sequence, not a lone heading or a page containing the word contents."""
    if len(value) < 3:
        return False
    titles = {normalize_bibliographic_text(str(item["title"])) for item in value}
    return len(titles) >= 3


def _description(value: Any) -> str | None:
    if isinstance(value, dict):
        value = value.get("value")
    return value.strip() if isinstance(value, str) and value.strip() else None


def _connect_index(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    return connection


def _create_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        PRAGMA journal_mode=DELETE;
        PRAGMA synchronous=NORMAL;
        CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE works (
            work_key TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            author_keys_json TEXT NOT NULL,
            subjects_json TEXT NOT NULL,
            description TEXT,
            revision INTEGER NOT NULL,
            last_modified TEXT NOT NULL
        );
        CREATE TABLE editions (
            edition_key TEXT PRIMARY KEY,
            work_key TEXT,
            title TEXT NOT NULL,
            subtitle TEXT,
            author_keys_json TEXT NOT NULL,
            publishers_json TEXT NOT NULL,
            publish_date TEXT,
            languages_json TEXT NOT NULL,
            toc_json TEXT NOT NULL,
            source_records_json TEXT NOT NULL,
            revision INTEGER NOT NULL,
            last_modified TEXT NOT NULL
        );
        CREATE TABLE edition_isbns (
            isbn TEXT NOT NULL,
            edition_key TEXT NOT NULL,
            kind TEXT NOT NULL CHECK(kind IN ('isbn_10', 'isbn_13')),
            PRIMARY KEY (isbn, edition_key, kind),
            FOREIGN KEY (edition_key) REFERENCES editions(edition_key)
        );
        CREATE INDEX editions_work_key_idx ON editions(work_key);
        CREATE INDEX edition_isbns_isbn_idx ON edition_isbns(isbn);
        """
    )


def _insert_edition(
    connection: sqlite3.Connection, envelope: DumpRecord, counts: dict[str, int]
) -> bool:
    record = envelope.value
    title = record.get("title")
    if not isinstance(title, str) or not title.strip():
        return False
    work_keys = _reference_keys(record.get("works"))
    toc = _toc(record.get("table_of_contents"))
    connection.execute(
        "INSERT INTO editions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            envelope.key,
            work_keys[0] if work_keys else None,
            title.strip(),
            record.get("subtitle") if isinstance(record.get("subtitle"), str) else None,
            json.dumps(_reference_keys(record.get("authors"))),
            json.dumps(_string_list(record.get("publishers")), ensure_ascii=False),
            record.get("publish_date") if isinstance(record.get("publish_date"), str) else None,
            json.dumps(_reference_keys(record.get("languages"))),
            json.dumps(toc, ensure_ascii=False, sort_keys=True),
            json.dumps(_string_list(record.get("source_records")), ensure_ascii=False),
            envelope.revision,
            envelope.last_modified,
        ),
    )
    counts["editions"] += 1
    counts["toc_editions"] += bool(toc)
    for kind in ("isbn_10", "isbn_13"):
        for isbn in _string_list(record.get(kind)):
            normalized_isbn = _normalized_isbn(isbn)
            if not normalized_isbn:
                continue
            cursor = connection.execute(
                "INSERT OR IGNORE INTO edition_isbns VALUES (?, ?, ?)",
                (normalized_isbn, envelope.key, kind),
            )
            counts["isbns"] += cursor.rowcount
    return True


def build_open_library_index(
    *,
    editions_dump: Path,
    works_dump: Path,
    output_path: Path,
    manifest: OpenLibraryDumpManifest,
) -> dict[str, int]:
    """Build a minimal SQLite projection atomically from compressed official dumps."""
    if output_path.exists():
        raise FileExistsError(f"refusing to overwrite existing index: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.with_name(f".{output_path.name}.tmp")
    if temporary_path.exists():
        raise FileExistsError(f"stale temporary index requires inspection: {temporary_path}")
    counts = {"works": 0, "editions": 0, "isbns": 0, "toc_editions": 0}
    connection = _connect_index(temporary_path)
    try:
        _create_schema(connection)
        connection.executemany(
            "INSERT INTO metadata(key, value) VALUES (?, ?)",
            (
                ("provider", manifest.provider),
                ("dump_date", manifest.dump_date),
                ("parser_version", PARSER_VERSION),
                ("source_manifest", manifest.model_dump_json()),
            ),
        )
        for envelope in iter_dump(works_dump, expected_type=WORK_TYPE):
            record = envelope.value
            title = record.get("title")
            if not isinstance(title, str) or not title.strip():
                continue
            connection.execute(
                "INSERT INTO works VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    envelope.key,
                    title.strip(),
                    json.dumps(_reference_keys(record.get("authors"), nested="author")),
                    json.dumps(_string_list(record.get("subjects")), ensure_ascii=False),
                    _description(record.get("description")),
                    envelope.revision,
                    envelope.last_modified,
                ),
            )
            counts["works"] += 1
        for envelope in iter_dump(editions_dump, expected_type=EDITION_TYPE):
            _insert_edition(connection, envelope, counts)
        connection.commit()
        connection.execute("PRAGMA optimize")
        connection.close()
        os.replace(temporary_path, output_path)
        return counts
    except Exception:
        connection.close()
        temporary_path.unlink(missing_ok=True)
        raise


def build_targeted_open_library_index(
    *,
    editions_dump: Path,
    output_path: Path,
    manifest: OpenLibraryDumpManifest,
    target_isbns: set[str],
) -> dict[str, int]:
    """Build a small benchmark index with two compressed scans and no full projection."""
    if output_path.exists():
        raise FileExistsError(f"refusing to overwrite existing index: {output_path}")
    normalized_targets = {_normalized_isbn(value) for value in target_isbns if value}
    normalized_targets.discard("")
    if not normalized_targets:
        raise ValueError("at least one target ISBN is required")

    target_edition_keys: set[str] = set()
    target_work_keys: set[str] = set()
    matched_targets: set[str] = set()
    for envelope in iter_dump_candidates(
        editions_dump,
        expected_type=EDITION_TYPE,
        needles=normalized_targets,
    ):
        record_isbns = {
            normalized
            for kind in ("isbn_10", "isbn_13")
            for value in _string_list(envelope.value.get(kind))
            if (normalized := _normalized_isbn(value))
        }
        matches = record_isbns & normalized_targets
        if not matches:
            continue
        matched_targets.update(matches)
        target_edition_keys.add(envelope.key)
        target_work_keys.update(_reference_keys(envelope.value.get("works")))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.with_name(f".{output_path.name}.tmp")
    if temporary_path.exists():
        raise FileExistsError(f"stale temporary index requires inspection: {temporary_path}")
    counts = {
        "target_isbns": len(normalized_targets),
        "matched_target_isbns": len(matched_targets),
        "target_editions": len(target_edition_keys),
        "target_works": len(target_work_keys),
        "works": 0,
        "editions": 0,
        "isbns": 0,
        "toc_editions": 0,
    }
    connection = _connect_index(temporary_path)
    try:
        _create_schema(connection)
        connection.executemany(
            "INSERT INTO metadata(key, value) VALUES (?, ?)",
            (
                ("provider", manifest.provider),
                ("dump_date", manifest.dump_date),
                ("parser_version", PARSER_VERSION),
                ("source_manifest", manifest.model_dump_json()),
                ("index_scope", "targeted"),
                ("target_isbns", json.dumps(sorted(normalized_targets))),
            ),
        )
        for envelope in iter_dump_candidates(
            editions_dump,
            expected_type=EDITION_TYPE,
            needles=target_edition_keys | target_work_keys,
        ):
            work_keys = set(_reference_keys(envelope.value.get("works")))
            if envelope.key not in target_edition_keys and work_keys.isdisjoint(target_work_keys):
                continue
            _insert_edition(connection, envelope, counts)
        connection.commit()
        connection.execute("PRAGMA optimize")
        connection.close()
        os.replace(temporary_path, output_path)
        return counts
    except Exception:
        connection.close()
        temporary_path.unlink(missing_ok=True)
        raise


def _file_digest(path: Path, algorithm: str) -> str:
    digest = hashlib.new(algorithm)
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_dump_file(
    path: Path, specification: OpenLibraryDumpFile, *, checksum: bool = True
) -> list[str]:
    errors = []
    if not path.exists():
        return ["missing"]
    if path.stat().st_size != specification.compressed_size:
        errors.append("size_mismatch")
        return errors
    if checksum and _file_digest(path, "sha1") != specification.sha1:
        errors.append("sha1_mismatch")
    return errors


def download_dump_file(
    specification: OpenLibraryDumpFile,
    destination_directory: Path,
    *,
    client: httpx.Client | None = None,
) -> Literal["downloaded", "resumed", "already_present"]:
    """Download one pinned dump with range resume, checksum, and atomic publication."""
    destination_directory.mkdir(parents=True, exist_ok=True)
    destination = destination_directory / specification.filename
    if destination.exists():
        errors = verify_dump_file(destination, specification)
        if errors:
            raise ValueError(f"existing dump failed verification: {', '.join(errors)}")
        return "already_present"

    partial = destination.with_suffix(destination.suffix + ".part")
    offset = partial.stat().st_size if partial.exists() else 0
    if offset > specification.compressed_size:
        raise ValueError("partial dump is larger than the pinned source")
    headers = {"Range": f"bytes={offset}-"} if offset else {}
    owns_client = client is None
    active_client = client or httpx.Client(
        timeout=httpx.Timeout(connect=30.0, read=120.0, write=30.0, pool=30.0),
        follow_redirects=True,
        headers={"User-Agent": "cau-capstone-data-pipeline/0.1 (bulk metadata research)"},
    )
    resumed = offset > 0
    try:
        with active_client.stream("GET", specification.url, headers=headers) as response:
            response.raise_for_status()
            if resumed and response.status_code == 206:
                content_range = response.headers.get("content-range", "")
                if not content_range.startswith(f"bytes {offset}-"):
                    raise ValueError("resumed dump returned an unexpected Content-Range")
                mode = "ab"
            elif resumed and response.status_code == 200:
                offset = 0
                resumed = False
                mode = "wb"
            elif not resumed and response.status_code == 200:
                mode = "wb"
            else:
                raise ValueError(f"unexpected dump download status: {response.status_code}")
            with partial.open(mode) as stream:
                for chunk in response.iter_bytes(chunk_size=1024 * 1024):
                    stream.write(chunk)
    finally:
        if owns_client:
            active_client.close()

    errors = verify_dump_file(partial, specification)
    if errors:
        raise ValueError(f"downloaded dump failed verification: {', '.join(errors)}")
    os.replace(partial, destination)
    return "resumed" if resumed else "downloaded"


def _edition_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "edition_key": row["edition_key"],
        "work_key": row["work_key"],
        "title": row["title"],
        "subtitle": row["subtitle"],
        "author_keys": json.loads(row["author_keys_json"]),
        "publish_date": row["publish_date"],
        "languages": json.loads(row["languages_json"]),
        "toc": json.loads(row["toc_json"]),
        "source_records": json.loads(row["source_records_json"]),
    }


def _is_supplement(edition: dict[str, Any]) -> bool:
    material = " ".join(
        [
            str(edition.get("title") or ""),
            str(edition.get("subtitle") or ""),
            *[str(item) for item in edition.get("source_records", [])],
        ]
    )
    normalized = normalize_bibliographic_text(material)
    collapsed = normalized.replace(" ", "")
    return any(
        marker in normalized or marker.replace(" ", "") in collapsed
        for marker in SUPPLEMENT_MARKERS
    )


def _year(value: str | None) -> int | None:
    match = re.search(r"\b(1[5-9]\d{2}|20\d{2})\b", value or "")
    return int(match.group(1)) if match else None


def _volume(value: str) -> int | None:
    normalized = normalize_bibliographic_text(value)
    match = re.search(r"\b(?:volume|vol)\s+(\d+)\b", normalized)
    return int(match.group(1)) if match else None


def _title_matches(target: dict[str, Any], candidate: dict[str, Any]) -> bool:
    target_title = normalize_bibliographic_text(str(target["title"]))
    candidate_title = normalize_bibliographic_text(str(candidate["title"]))
    if target_title != candidate_title:
        return False
    target_volume = _volume(" ".join([str(target["title"]), str(target.get("subtitle") or "")]))
    candidate_volume = _volume(
        " ".join([str(candidate["title"]), str(candidate.get("subtitle") or "")])
    )
    return target_volume is None or candidate_volume is None or target_volume == candidate_volume


def resolve_toc(index_path: Path, isbn: str) -> TocResolution | None:
    """Resolve exact first, then a validated TOC from the provider-native Work."""
    normalized_isbn = _normalized_isbn(isbn)
    with _connect_index(index_path) as connection:
        exact_rows = connection.execute(
            """
            SELECT DISTINCT e.* FROM editions e
            JOIN edition_isbns i ON i.edition_key = e.edition_key
            WHERE i.isbn = ? ORDER BY e.edition_key
            """,
            (normalized_isbn,),
        ).fetchall()
        exact_editions = [_edition_from_row(row) for row in exact_rows]
        exact_editions = [edition for edition in exact_editions if not _is_supplement(edition)]
        if not exact_editions:
            return None

        target = exact_editions[0]
        exact_with_toc = [edition for edition in exact_editions if toc_is_usable(edition["toc"])]
        if exact_with_toc:
            selected = sorted(
                exact_with_toc,
                key=lambda item: (-len(item["toc"]), item["edition_key"]),
            )[0]
            return TocResolution(
                normalized_isbn,
                target["edition_key"],
                target["title"],
                tuple(target["author_keys"]),
                target["work_key"] or "",
                "exact_edition_toc",
                selected["edition_key"],
                tuple(
                    row["isbn"]
                    for row in connection.execute(
                        "SELECT isbn FROM edition_isbns WHERE edition_key = ? ORDER BY isbn",
                        (selected["edition_key"],),
                    )
                ),
                selected["title"],
                tuple(selected["author_keys"]),
                selected["publish_date"],
                tuple(selected["toc"]),
                ("exact_isbn", "exact_edition"),
                "strong",
            )

        work_key = target["work_key"]
        if not work_key:
            return None
        alternate_rows = connection.execute(
            "SELECT * FROM editions WHERE work_key = ? AND edition_key != ?",
            (work_key, target["edition_key"]),
        ).fetchall()
        candidates = []
        for row in alternate_rows:
            candidate = _edition_from_row(row)
            if (
                _is_supplement(candidate)
                or not toc_is_usable(candidate["toc"])
                or not _title_matches(target, candidate)
            ):
                continue
            target_authors = set(target["author_keys"])
            source_authors = set(candidate["author_keys"])
            if target_authors and source_authors and target_authors.isdisjoint(source_authors):
                continue
            target_languages = set(target["languages"])
            source_languages = set(candidate["languages"])
            if (
                target_languages
                and source_languages
                and target_languages.isdisjoint(source_languages)
            ):
                continue
            target_year = _year(target["publish_date"])
            source_year = _year(candidate["publish_date"])
            candidates.append(
                (
                    0 if target_languages & source_languages else 1,
                    0 if target_authors & source_authors else 1,
                    abs(target_year - source_year)
                    if target_year is not None and source_year is not None
                    else 9999,
                    -len(candidate["toc"]),
                    candidate["edition_key"],
                    candidate,
                )
            )
        if not candidates:
            return None
        *_, selected = min(candidates)
        source_isbns = tuple(
            row["isbn"]
            for row in connection.execute(
                "SELECT isbn FROM edition_isbns WHERE edition_key = ? ORDER BY isbn",
                (selected["edition_key"],),
            )
        )
        match_basis = ["open_library_work_relation", "normalized_title"]
        if set(target["languages"]) & set(selected["languages"]):
            match_basis.append("same_language")
        if set(target["author_keys"]) & set(selected["author_keys"]):
            match_basis.append("author_key_overlap")
        return TocResolution(
            normalized_isbn,
            target["edition_key"],
            target["title"],
            tuple(target["author_keys"]),
            work_key,
            "same_work_alternate_edition_toc",
            selected["edition_key"],
            source_isbns,
            selected["title"],
            tuple(selected["author_keys"]),
            selected["publish_date"],
            tuple(selected["toc"]),
            tuple(match_basis),
            "strong" if len(match_basis) >= 3 else "acceptable",
        )


def inspect_toc_resolution(index_path: Path, isbn: str) -> TocResolutionInspection:
    """Report lookup coverage without treating rejected editions as usable evidence."""
    normalized_isbn = _normalized_isbn(isbn)
    with _connect_index(index_path) as connection:
        exact_rows = connection.execute(
            """
            SELECT DISTINCT e.* FROM editions e
            JOIN edition_isbns i ON i.edition_key = e.edition_key
            WHERE i.isbn = ? ORDER BY e.edition_key
            """,
            (normalized_isbn,),
        ).fetchall()
        exact_editions = [_edition_from_row(row) for row in exact_rows]
        eligible = [edition for edition in exact_editions if not _is_supplement(edition)]
        work_keys = tuple(
            sorted({str(edition["work_key"]) for edition in eligible if edition.get("work_key")})
        )
        exact_keys = {str(edition["edition_key"]) for edition in eligible}
        alternate_count = 0
        if work_keys:
            work_placeholders = ",".join("?" for _ in work_keys)
            parameters: list[str] = list(work_keys)
            exclusion = ""
            if exact_keys:
                exclusion = " AND edition_key NOT IN (" + ",".join("?" for _ in exact_keys) + ")"
                parameters.extend(sorted(exact_keys))
            alternate_count = int(
                connection.execute(
                    f"SELECT COUNT(*) FROM editions WHERE work_key IN ({work_placeholders})"
                    + exclusion,
                    parameters,
                ).fetchone()[0]
            )

    resolution = resolve_toc(index_path, normalized_isbn)
    return TocResolutionInspection(
        target_isbn=normalized_isbn,
        exact_editions_count=len(exact_editions),
        eligible_exact_editions_count=len(eligible),
        exact_toc_found=resolution is not None and resolution.tier == "exact_edition_toc",
        work_keys=work_keys,
        alternate_editions_count=alternate_count,
        alternate_toc_found=(
            resolution is not None and resolution.tier == "same_work_alternate_edition_toc"
        ),
        selected_alternate_edition=(
            resolution.source_edition_key
            if resolution is not None and resolution.tier == "same_work_alternate_edition_toc"
            else None
        ),
    )


def canonical_toc_evidence(
    resolution: TocResolution,
    *,
    target_book: Book,
    retrieved_at: datetime,
    dump_date: str,
) -> CanonicalDataset:
    """Convert a local-index resolution into ordinary canonical Source and TOC records."""
    source_id = stable_id(
        "source",
        "open_library_bulk",
        dump_date,
        resolution.source_edition_key,
        target_book.book_id,
    )
    source = Source(
        source_id=source_id,
        book_id=target_book.book_id,
        provider="open_library",
        source_type="metadata_api",
        url=f"https://openlibrary.org{resolution.source_edition_key}.json",
        external_id=resolution.source_edition_key,
        retrieved_at=retrieved_at,
        license=None,
        rights_note=(f"TOC selected from Open Library {dump_date} bulk dump; no license inferred."),
        content_hash=sha256_json(list(resolution.toc)),
        evidence=EvidenceProvenance(
            evidence_type="toc",
            tier=resolution.tier,
            target_isbn=resolution.target_isbn,
            target_title=target_book.title,
            target_authors=target_book.authors,
            source_edition_id=resolution.source_edition_key,
            source_isbns=list(resolution.source_isbns),
            source_title=resolution.source_title,
            source_author_ids=list(resolution.source_author_ids),
            same_edition=resolution.tier == "exact_edition_toc",
            source_document_type="open_library_edition_record",
            discovery_method="open_library_bulk_index",
            match_basis=list(resolution.match_basis),
            validation_status=resolution.validation_status,
        ),
    )
    valid = list(resolution.toc)
    base_level = min(int(item["level"]) for item in valid)
    latest_by_level: dict[int, str] = {}
    sibling_counts: dict[str | None, int] = {}
    entries: list[TocEntry] = []
    for index, item in enumerate(valid):
        level = int(item["level"]) - base_level + 1
        parent_id = latest_by_level.get(level - 1) if level > 1 else None
        if level > 1 and parent_id is None:
            continue
        title = str(item["title"])
        label = str(item.get("label") or "").strip() or None
        entry_id = stable_id("toc", target_book.book_id, source_id, str(index), label or "", title)
        entries.append(
            TocEntry(
                toc_entry_id=entry_id,
                book_id=target_book.book_id,
                parent_entry_id=parent_id,
                level=level,
                order_index=sibling_counts.get(parent_id, 0),
                label=label,
                title=title,
                source_id=source_id,
            )
        )
        sibling_counts[parent_id] = sibling_counts.get(parent_id, 0) + 1
        latest_by_level[level] = entry_id
        latest_by_level = {key: value for key, value in latest_by_level.items() if key <= level}
    return CanonicalDataset(books=[], documents=[], toc=entries, sources=[source])
