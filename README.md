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

Exact-edition publisher evidence slices are also available for the public Wiley companion sites
for *Operating System Concepts, 7th Edition* and *Elementary Linear Algebra, 10th Edition*. Each
allowlist entry binds its publisher pages to the canonical book by ISBN, title, and edition. The
collector fetches only the identity page and TOC page, preserves both HTML responses in one
immutable raw artifact, and extracts the complete reviewed top-level heading sequence. It does not
follow resource links or collect textbook body content.

One reviewed public catalog source is available for *Operating Systems: Internals and Design
Principles, 4th Edition*. The eCampus page exposes the exact ISBN and edition, a description, and a
detailed 201-entry TOC in ordinary HTML. The collector preserves that single response and converts
its visible indentation into explicit parent relationships. Since this is a bookstore catalog
rather than a publisher or author page, its source is explicitly recorded as `other`; no license
or access rights are inferred from the page.

Google Books is also implemented (`--provider google-books`), but its public endpoint returned
HTTP 429 from the development environment on 2026-09-12. A borrow link, scan identifier, preview
URL, or TOC heading named `Preface` is not treated as public book text. The pipeline does not fetch
restricted scans or infer unavailable preface, introduction, preview, or sample content.

## Real-data evidence experiment

The 2026-09-14 Open Library plus Wiley experiment produced the following coverage for the current
ten books:

| Topic | Metadata | TOC | Description | Preface / Introduction | Preview / Sample |
| --- | ---: | ---: | ---: | ---: | ---: |
| Operating Systems | 5/5 | 2/5 | 2/5 | 0/5 | 0/5 |
| Linear Algebra | 5/5 | 3/5 | 4/5 | 0/5 | 0/5 |

The five TOCs contain 373 canonical entries. The two Open Library TOCs and the eCampus TOC retain
their available parent-child hierarchy; the Wiley pages expose chapter and appendix headings only,
so their 35 entries are represented truthfully as top-level items.
This is useful progress but not the full MVP definition of done: TOC coverage has reached half of
the books but not yet a useful majority, and no public preface/introduction or preview/sample text
has been collected.
One work-level description was intentionally excluded because it explicitly described a different
edition than the selected ISBN; the conflicting response remains available in the raw artifact.

## Setup and commands

Python 3.12 or later and [uv](https://docs.astral.sh/uv/) are required.

```bash
uv sync
uv run data-pipeline search --topic operating-systems --limit 5
uv run data-pipeline collect --topic operating-systems --limit 5
uv run data-pipeline collect --topic linear-algebra --limit 5
uv run data-pipeline collect-publisher --source wiley-osc7
uv run data-pipeline collect-publisher --source wiley-ela10
uv run data-pipeline collect-public-page --source ecampus-stallings-os4
uv run data-pipeline report
```

`collect-publisher` requires the matching metadata book to exist in `data/processed` and stops if
the exact canonical `book_id` is absent. Unknown publisher URLs cannot be supplied at the CLI; a
new source must first be reviewed and added to the small version-controlled allowlist.
Repeated retrievals of the same allowlisted URL update its canonical source snapshot. Documents
and TOC entries owned by an older snapshot are replaced, while every immutable raw response is
still retained for audit and offline rebuilding.
`collect-public-page` applies the same exact-book and allowlist boundary to a reviewed ordinary
public HTML source. It additionally rejects a response unless the ISBN, edition, complete reviewed
entry count, and top-level TOC structure all match.

Each raw artifact is immutable and saved under a timestamped, content-addressed path such as
`data/raw/open_library/operating-systems/<timestamp>_<hash>.json`. The artifact records its
provider, topic, request limit, query parameters, retrieval time, and all bounded detail responses.
Canonical data can be rebuilt without another network request:

```bash
uv run data-pipeline build \
  --raw data/raw/open_library/operating-systems/<artifact>.json \
  --raw data/raw/open_library/linear-algebra/<artifact>.json \
  --raw data/raw/publisher_page/operating-systems/<artifact>.json \
  --raw data/raw/publisher_page/linear-algebra/<artifact>.json \
  --raw data/raw/public_book_page/operating-systems/<artifact>.json
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
