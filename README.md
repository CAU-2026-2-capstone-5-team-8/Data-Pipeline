# Data-Pipeline

Evidence-first data collection and normalization for the CAU Capstone Team 8 book
recommendation project. This repository emits provider-independent book data for downstream
ML work; it does not perform concept extraction, difficulty scoring, or recommendation.

## Current vertical slice

The implemented slices query public book APIs for a small topic search, preserve the full raw
responses, normalize metadata plus available descriptions and hierarchical tables of contents,
validate cross-record provenance, and write:

```text
data/processed/books.jsonl
data/processed/documents.jsonl
data/processed/toc.jsonl
data/processed/sources.jsonl
```

Open Library is the default because its unauthenticated endpoint worked in the initial real-data
experiment. Collection also fetches a bounded set of public edition and work records. Edition
records can provide author, description, and structured TOC evidence; work records can provide
additional descriptions. Search, edition, and work responses remain together in the immutable
raw artifact. Exact duplicate descriptions are emitted once, and every document and TOC entry
references the API source record that supports it.

Google Books is also implemented (`--provider google-books`), but its public endpoint returned
HTTP 429 from the development environment on 2026-09-12. A borrow link, scan identifier, preview
URL, or TOC heading named `Preface` is not treated as public book text. The pipeline does not fetch
restricted scans or infer unavailable preface, introduction, preview, or sample content.

## Real-data evidence experiment

The 2026-09-13 Open Library experiment produced the following coverage for the current ten books:

| Topic | Metadata | TOC | Description | Preface / Introduction | Preview / Sample |
| --- | ---: | ---: | ---: | ---: | ---: |
| Operating Systems | 5/5 | 0/5 | 2/5 | 0/5 | 0/5 |
| Linear Algebra | 5/5 | 2/5 | 4/5 | 0/5 | 0/5 |

The two structured TOCs contain 137 canonical entries with their parent-child hierarchy intact.
This is useful progress but not the full MVP definition of done: TOC coverage is not yet a useful
majority, and no public preface/introduction or preview/sample text has been collected.
One work-level description was intentionally excluded because it explicitly described a different
edition than the selected ISBN; the conflicting response remains available in the raw artifact.

## Setup and commands

Python 3.12 or later and [uv](https://docs.astral.sh/uv/) are required.

```bash
uv sync
uv run data-pipeline search --topic operating-systems --limit 5
uv run data-pipeline collect --topic operating-systems --limit 5
uv run data-pipeline collect --topic linear-algebra --limit 5
uv run data-pipeline report
```

Each raw artifact is immutable and saved under a timestamped, content-addressed path such as
`data/raw/open_library/operating-systems/<timestamp>_<hash>.json`. The artifact records its
provider, topic, request limit, query parameters, retrieval time, and all bounded detail responses.
Canonical data can be rebuilt without another network request:

```bash
uv run data-pipeline build \
  --raw data/raw/open_library/operating-systems/<artifact>.json \
  --raw data/raw/open_library/linear-algebra/<artifact>.json
```

Repeat `--raw` for multiple artifacts when rebuilding the combined two-topic dataset. Sequential
`collect` commands safely merge new books into the existing canonical dataset. Conflicting records
with the same deterministic ID stop the build instead of being silently selected.

Supported MVP topics are `operating-systems` and `linear-algebra`. Generated raw and processed
data are intentionally ignored by Git; only small test fixtures should be committed.

## Verification

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
```
