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
immutable raw artifact, and extracts the complete reviewed top-level heading sequence.

One separate, reviewed document slice follows the official companion page's direct link to
*Operating System Concepts, 7th Edition*, Appendix B, “The Mach System.” It preserves the exact
identity page, linking TOC page, and Base64-encoded PDF in one raw artifact, then extracts the
28-page appendix as an `other` document. It is not classified as a preview or sample chapter, and
no license is inferred. Arbitrary PDF URLs and documents larger than 5 MiB are rejected.

The first open-textbook slice collects *Operating Systems: Three Easy Pieces*, version 1.10,
from its University of Wisconsin author page. It replaces the evidence-empty 1974 Operating
Systems candidate while keeping the milestone at five books per topic. The allowlisted collector
preserves the home-page HTML and three public PDFs, then emits the official description, a
five-part/57-chapter hierarchical TOC, the preface, the introduction, and one public sample
chapter. The page states that the chapters are free online but does not identify a reuse license,
so canonical `license` values remain `null` and that distinction is recorded in `rights_note`.

Reviewed public catalog sources are available for *Operating Systems: Internals and Design
Principles, 4th Edition* and *Advanced Concepts in Operating Systems, 1st Edition*. The eCampus
pages expose each exact ISBN and edition, a description, and complete TOCs in ordinary HTML. The
collector preserves each single-page response. It converts the first page's visible indentation
into explicit parent relationships and the second page's 7-Part/20-Chapter sequence into two
canonical levels. Since these are bookstore catalog pages rather than publisher or author pages,
their sources are explicitly recorded as `other`; no license or access rights are inferred.

Google Books is also implemented (`--provider google-books`), but its public endpoint returned
HTTP 429 from the development environment on 2026-09-12. A borrow link, scan identifier, preview
URL, or TOC heading named `Preface` is not treated as public book text. The pipeline does not fetch
restricted scans or infer unavailable preface, introduction, preview, or sample content.

## Real-data evidence experiment

The combined public-source experiment on 2026-09-14 produced the following coverage for the
current ten books:

| Topic | Metadata | TOC | Description | Preface / Introduction | Preview / Sample | Other document |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Operating Systems | 5/5 | 4/5 | 4/5 | 1/5 | 1/5 | 1/5 |
| Linear Algebra | 5/5 | 3/5 | 4/5 | 0/5 | 0/5 | 0/5 |

The seven TOCs contain 462 canonical entries. The Open Library and eCampus TOCs retain their
available parent-child hierarchy; the Wiley pages expose chapter and appendix headings only, so
their 35 entries are represented truthfully as top-level items. OSTEP contributes five thematic
roots and 57 numbered child chapters.
The canonical dataset also contains one 72,711-character public supplemental appendix for one
Operating Systems book. It is useful real book-text evidence for downstream feasibility testing,
but it intentionally does not increase the preview/sample coverage count.
OSTEP adds a 27,155-character preface, a 47,725-character introduction, and a 25,160-character
sample chapter. This demonstrates that the schema and raw-to-canonical path can carry usable public
book text without source-specific logic downstream. Coverage remains incomplete, especially for
Linear Algebra, so the full MVP definition of done has not yet been reached.
The complete canonical result contains 10 books, 13 documents, 462 TOC entries, and 27 source
records.
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
uv run data-pipeline collect-publisher-document --source wiley-osc7-appendix-b
uv run data-pipeline collect-public-page --source ecampus-stallings-os4
uv run data-pipeline collect-public-page --source ecampus-singhal-os1
uv run data-pipeline collect-open-textbook --source ostep-1.10
uv run data-pipeline report
```

`collect-publisher` requires the matching metadata book to exist in `data/processed` and stops if
the exact canonical `book_id` is absent. Unknown publisher URLs cannot be supplied at the CLI; a
new source must first be reviewed and added to the small version-controlled allowlist.
`collect-publisher-document` applies the same allowlist and exact-book requirement. It verifies the
title, edition, ISBN-bearing publisher page, direct link from the companion TOC page, PDF media
type, PDF signature, and reviewed text markers before emitting canonical evidence.
Repeated retrievals of the same allowlisted URL update its canonical source snapshot. Documents
and TOC entries owned by an older snapshot are replaced, while every immutable raw response is
still retained for audit and offline rebuilding.
`collect-public-page` applies the same exact-book and allowlist boundary to a reviewed ordinary
public HTML source. It additionally rejects a response unless the ISBN, edition, complete reviewed
entry count, and top-level TOC structure all match.
`collect-open-textbook` verifies the title, authors, publisher, version, year, ISBN, complete
numbered TOC, public document links, PDF media types and signatures, and reviewed text markers. It
removes the configured weak candidate and all records scoped to that book before merging the new
book. Repeated runs retain five Operating Systems books and update only the selected source
snapshots.

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
  --raw data/raw/publisher_document/operating-systems/<artifact>.json \
  --raw data/raw/public_book_page/operating-systems/<artifact>.json \
  --raw data/raw/open_textbook/operating-systems/<artifact>.json
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
