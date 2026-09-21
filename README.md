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
no license is inferred. Arbitrary PDF URLs and documents larger than 5 MiB are rejected. This
optional slice is no longer present in the current ten-book result because the Hailperin slice
below replaces that commercial-book candidate and all evidence scoped to it.

The current Linear Algebra document slice collects Wiley's public 92-page Chapter 1 excerpt for
*Elementary Linear Algebra, 10th Edition*. The allowlist binds the PDF to the existing canonical
book using the exact ISBN in Wiley's catalog URL, the ISBN/title/edition on the companion page,
the matching Chapter 1 heading on its TOC page, and three text markers spanning sections 1.1–1.9.
The PDF is emitted as `sample_chapter` evidence. Wiley does not state a reuse license on the
collected pages, so `license` remains `null` and the access/identity facts are kept in
`rights_note` rather than interpreted as permission to redistribute it.

The first open-textbook slice collects *Operating Systems: Three Easy Pieces*, version 1.10,
from its University of Wisconsin author page. It replaces the evidence-empty 1974 Operating
Systems candidate while keeping the milestone at five books per topic. The allowlisted collector
preserves the home-page HTML and three public PDFs, then emits the official description, a
five-part/57-chapter hierarchical TOC, the preface, the introduction, and one public sample
chapter. The page states that the chapters are free online but does not identify a reuse license,
so canonical `license` values remain `null` and that distinction is recorded in `rights_note`.

The Linear Algebra open-textbook slice collects Jim Hefferon's *Linear Algebra*, Fourth edition,
from the author's public pages and university-hosted PDF. The PDF contains a 96-entry bookmark
outline, which is preserved directly as a three-level canonical TOC instead of being reconstructed
from flattened page text. The pipeline extracts the four-page preface and complete first chapter
as separate documents. The author's license page explicitly applies either the GNU Free
Documentation License or Creative Commons Attribution-ShareAlike 3.0 United States License to the
textbook, and that page is preserved alongside the home page and PDF. No ISBN is asserted because
none was verified in those official materials; the book uses a deterministic title-and-author ID.

The second Linear Algebra OER slice collects David Austin's *Understanding Linear Algebra*. It
replaces the evidence-poor 1979 Friedberg candidate and keeps the milestone at five books per
topic. The author's official page links the online PreTeXt book and the Grand Valley State
University repository record; the latter supplies the reviewed 2022 publication date. The
collector preserves those pages plus the preface and complete first-chapter page set. It emits the
full 222-entry, three-level chapter TOC, one preface, and five independently sourced preview
documents. The author's page explicitly applies the Creative Commons Attribution 4.0 International
License, which is retained on every source record. No ISBN is asserted because none is stated in
the collected official pages.

The third Linear Algebra OER slice collects W. Keith Nicholson's *Linear Algebra with
Applications*. It replaces the evidence-empty 1984 Gareth Williams candidate. A structured
[Open Textbook Library record](https://open.umn.edu/opentextbooks/textbooks/533) supplies the
reviewed title, author, publisher, 2023 version, rights statement, and description. The public
[LibreTexts book](https://math.libretexts.org/Bookshelves/Linear_Algebra/Linear_Algebra_with_Applications_(Nicholson))
supplies twelve ordinary-HTML chapter listings, the linked preface, and section 1.1 as preview
text. The chapter listings emit 167 three-level TOC entries without using the site's empty
JavaScript-generated TOC shell. LibreTexts page tags preserve the author, upstream Lyryx source,
and CC BY-NC-SA 4.0 statement on each collected page; the less-specific Open Textbook Library
license value is retained separately rather than being upgraded. No ISBN is asserted because the
reviewed records do not provide one.

The next Operating Systems OER slice collects Allen B. Downey's *Think OS: A Brief Introduction
to Operating Systems*, version 0.7.4, from the official Green Tea Press pages. It replaces the
edition-mismatched *Modern Operating Systems* candidate. The publisher page supplies the
author-written description, while the linked public HTML book supplies a complete 11-chapter,
65-entry hierarchical TOC, the preface, and the first chapter as sample text. The publisher page
states CC BY-NC 3.0 and the versioned online book states CC BY-NC-SA 4.0; those differing terms are
preserved on their respective source records instead of being collapsed into one license.

The following Operating Systems OER slice collects Max Hailperin's *Operating Systems and
Middleware: Supporting Controlled Interaction*, Revised Edition 1.2. It replaces the remaining
commercial candidate that had a TOC and supplemental appendix but no matching description,
preface, introduction, or sample. A structured
[Open Textbook Library record](https://open.umn.edu/opentextbooks/textbooks/operating-systems-and-middleware-supporting-controlled-interaction)
supplies the reviewed identity and description and links the public complete PDF preserved by
Internet Archive. The PDF supplies a 179-entry, three-level bookmark TOC, its preface, and chapter
1 as sample text. The catalog's generic `Attribution-ShareAlike` value is retained on the catalog
source, while the PDF's explicit Creative Commons Attribution-ShareAlike 3.0 Unported statement is
retained separately. Redirects are limited to `archive.org` and its subdomains, and the final
archive path, PDF identity, page count, license page, outline shape, and evidence ranges are
validated before canonical output is written.

The next Operating Systems slice collects MIT PDOS's
[xv6 teaching-operating-system text](https://pdos.csail.mit.edu/6.1810/2025/xv6.html), RISC-V
rev5. It replaces the evidence-poor *Advanced Concepts in Operating Systems* candidate. The
official MIT page directly links the versioned 116-page PDF and the authors' source repository.
The PDF supplies a 99-entry, two-level bookmark TOC, the foreword, and Chapter 1 as sample text.
The linked source repository's LICENSE permission notice is preserved verbatim in the raw
artifact and summarized in `rights_note`; because it does not name a standard license identifier,
the book PDF's canonical `license` remains `null`. The separate CC BY 3.0 US link in the MIT
course-page footer is recorded only on that HTML source instead of being silently applied to the
book.

Reviewed public catalog sources are available for *Operating Systems: Internals and Design
Principles, 4th Edition* and *Advanced Concepts in Operating Systems, 1st Edition*. The eCampus
pages expose each exact ISBN and edition, a description, and complete TOCs in ordinary HTML. The
collector preserves each single-page response. It converts the first page's visible indentation
into explicit parent relationships and the second page's 7-Part/20-Chapter sequence into two
canonical levels. Since these are bookstore catalog pages rather than publisher or author pages,
their sources are explicitly recorded as `other`; no license or access rights are inferred.

Google Books is also implemented (`--provider google-books`). Searches above its 40-result request
limit are split into ordered `startIndex` pages of at most 40 items, and every fetched page retains
its exact request parameters and unmodified response inside one immutable raw artifact. A short
page ends pagination only when `totalItems` is absent or the reported total has been reached; an
explicit remaining total continues with the next planned page. A failed page fails the collection
visibly instead of publishing a partial artifact. The public endpoint returned HTTP 429 from the
development environment on 2026-09-12, so pagination is verified with network-independent HTTP
fixtures. A borrow link, scan identifier, preview URL, or TOC heading named `Preface` is not
treated as public book text. The pipeline does not fetch restricted scans or infer unavailable
preface, introduction, preview, or sample content.

## Real-data evidence experiment

The combined public-source experiment on 2026-09-15 produced the following coverage for the
current ten books:

| Topic | Metadata | TOC | Description | Preface / Introduction | Preview / Sample | Other document |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Operating Systems | 5/5 | 5/5 | 5/5 | 4/5 | 4/5 | 0/5 |
| Linear Algebra | 5/5 | 5/5 | 5/5 | 3/5 | 4/5 | 0/5 |

All ten books now have TOCs, containing 1,163 canonical entries. The Open Library and eCampus TOCs
retain their available parent-child hierarchy; the remaining Wiley page exposes headings only, so
its nine entries are represented truthfully as top-level items. OSTEP contributes five thematic
roots and 57 numbered child chapters.
OSTEP adds a 27,155-character preface, a 47,725-character introduction, and a 25,160-character
sample chapter. This demonstrates that the schema and raw-to-canonical path can carry usable public
book text without source-specific logic downstream. The core MVP definition of done is met, while
optional evidence coverage remains incomplete for two commercial titles.
Think OS adds a 1,694-character description, a 4,843-character preface, and a 10,538-character
first chapter. Its HTML index contributes 11 chapter roots and 54 child sections. Hailperin adds a
4,984-character description, a 19,244-character preface, and a 47,845-character first chapter. Its
PDF bookmarks contribute 15 top-level, 80 second-level, and 84 third-level entries. Hefferon adds
an 8,106-character preface and a 140,910-character first chapter, demonstrating the
same public-text path for Linear Algebra. *Understanding Linear Algebra* adds an 8,902-character
preface and five first-chapter preview pages containing 106,307 characters in total. Its PreTeXt
navigation contributes 7 chapters, 38 second-level entries, and 177 third-level entries. The
Nicholson slice adds a 725-character description, a 19,955-character preface, and a
16,526-character first-section preview. Its twelve chapter pages contribute 12 chapter roots,
88 second-level entries, and 67 exercise children. The Wiley Anton slice adds a 195,549-character
Chapter 1 sample spanning all nine sections shown by the exact-edition TOC. The xv6 slice adds a
135-character description, a 2,066-character foreword, a 28,562-character Chapter 1 sample, and
99 bookmark TOC entries. The complete canonical result contains 10 books, 31 documents, 1,163 TOC
entries, and 52 source records.
One work-level description was intentionally excluded because it explicitly described a different
edition than the selected ISBN; the conflicting response remains available in the raw artifact.

## Second Milestone: Scale Pilot

The curated ten-book result above remains the regression/golden dataset in
[`configs/mvp.json`](configs/mvp.json). The separate
[`configs/experiments/scale-50.json`](configs/experiments/scale-50.json) experiment fixes the exact
identities selected for a generic 25+25-book run. It does not invoke any publisher, public-page,
publisher-document, or open-textbook allowlist. Those collectors remain reviewed, exact-edition
paths; their safety boundary was not relaxed to improve scale coverage.

The reproducible scale workflow is:

```bash
uv run data-pipeline collect \
  --topic operating-systems --limit 25 --provider open-library \
  --data-dir data/experiments/scale-50
uv run data-pipeline collect \
  --topic linear-algebra --limit 25 --provider open-library \
  --data-dir data/experiments/scale-50
uv run data-pipeline build-manifest \
  --manifest configs/experiments/scale-50.json \
  --data-dir data/experiments/scale-50
uv run data-pipeline report-scale \
  --manifest configs/experiments/scale-50.json \
  --data-dir data/experiments/scale-50
```

`report-scale` selects the manifest's two immutable raw artifacts, performs two independent
offline normalizations, compares all four canonical JSONL files byte for byte, and writes:

```text
data/experiments/scale-50/reports/scale-report.json
data/experiments/scale-50/reports/scale-audit.csv
```

The JSON contains discovery, normalization, per-topic and per-book coverage, classified missing
evidence, integrity counters, build timing, and artifact sizes. The CSV includes identity,
edition/year, evidence, sources, prose size, TOC size, automated warnings, and intentionally blank
`identity_ok`, `topic_relevant`, `toc_matches_book`, `prose_matches_book`, `edition_ok`, and `notes`
columns for human review. Generated raw, canonical, report, and audit files remain outside Git.
Formula-like strings beginning with `=`, `+`, `-`, or `@` after optional leading whitespace are
prefixed with a single quote only when written to the audit CSV. Raw responses, canonical JSONL,
and the JSON report retain the original provider text.

### 2026-09-16 real-data result

Open Library returned 100 search candidates per topic. Of 200 candidates, 198 were structurally
normalizable, one repeated a canonical identity, and 197 unique normalized candidates remained in
the pool. The manifest-selected canonical output contains exactly 25 books per topic.

| Discovery / normalization metric | Result |
| --- | ---: |
| Candidates returned | 200 |
| Requested / selected / normalized books | 50 / 50 / 50 |
| Provider discovery | Open Library 200 |
| ISBN-13 available | 46/50 |
| ISBN-10 available | 46/50 |
| Deterministic fallback IDs | 4/50 |
| Duplicate candidates | 1 |
| Deduplicated selected books | 50 |
| Edition-mismatched work descriptions rejected | 2 |
| Candidate normalization failures | 2 |
| Detail-fetch rate-limit/network/HTTP failures | 0 |

| Topic | Metadata | Description | TOC | Preface | Introduction | Preview | Sample | Other prose |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Operating Systems | 25/25 | 7/25 | 2/25 | 0/25 | 0/25 | 0/25 | 0/25 | 0/25 |
| Linear Algebra | 25/25 | 5/25 | 2/25 | 0/25 | 0/25 | 0/25 | 0/25 | 0/25 |
| Total | 50/50 | 12/50 | 4/50 | 0/50 | 0/50 | 0/50 | 0/50 | 0/50 |

The canonical result contains 13 description documents with 9,753 prose characters and 177 TOC
entries. Operating Systems contributes 8 documents, 7,342 prose characters, and 40 TOC entries;
Linear Algebra contributes 5 documents, 2,411 prose characters, and 137 TOC entries. One book has
two distinct descriptions, hence 13 documents across 12 books.

All integrity counters are zero: broken cross-record references, unresolved duplicate IDs,
invalid TOC parents, missing provenance, and validation errors. Two offline builds from the same
raw manifest were byte-identical. The two raw files total 443,536 bytes; the four canonical files
total 95,655 bytes. The two offline builds took about 0.015 seconds in this environment. Each
network topic run took about 31 seconds, dominated by the bounded edition/work detail requests.

Scale exposed quality limits that the curated ten-book result could not show:

- title-only metadata discovery admits likely off-topic meanings, including *Robot Operating
  System*, *Power System Operation*, *Computer Aided Power System Operation and Analysis*, and
  *The Operating System*; these remain in the golden scale selection so `topic_relevant` can be
  audited rather than silently asserted;
- two candidates outside the selected 50 were rejected because Open Library aggregated 11–12
  authors, and one duplicate candidate was observed;
- two selected work descriptions explicitly named a different edition and were correctly omitted;
- generic Open Library metadata is reliable enough to produce 50 valid book records, but is not a
  sufficient generic source for broad TOC or public-prose coverage;
- book-specific allowlisting is the main reason the curated ten-book evidence is much richer, but
  extending that mechanism one ISBN at a time would be the wrong scaling strategy.

Before moving to 100–200 books, metadata discovery needs a generic relevance gate that uses
provider subjects/classifications and an auditable edition resolver. A second generic source is
also needed for TOCs and legally public prose, with rate-limit and failure telemetry preserved in
raw artifacts. The current canonical schema, immutable raw storage, deterministic identifiers,
manifest build, validation, deduplication checks, audit format, and offline reporting can already
scale without source-specific downstream knowledge.

### Scale Pilot v2: opt-in topic relevance gate

[`configs/experiments/scale-50-v2.json`](configs/experiments/scale-50-v2.json) pins the **same two
raw response hashes and retrieval timestamps** used for v1 and enables `topic-evidence-v1` only
for Open Library. It uses the selected English edition's and associated work's subject metadata,
excludes candidates
whose subjects explicitly indicate a competing domain, and otherwise accepts a matching English
edition title with the audit warning `topic_title_only_unverified`. A matching subject is not a
human relevance verdict. No live recollection, new topic, source-specific book allowlist, or
canonical schema change is necessary for this controlled before/after test.

```bash
uv run data-pipeline build-manifest \
  --manifest configs/experiments/scale-50-v2.json \
  --data-dir data/experiments/scale-50 \
  --output data/experiments/scale-50-v2/processed
uv run data-pipeline report-scale \
  --manifest configs/experiments/scale-50-v2.json \
  --data-dir data/experiments/scale-50 \
  --output data/experiments/scale-50-v2/reports
uv run data-pipeline compare-scale \
  --v1-report data/experiments/scale-50/reports/scale-report.json \
  --v2-report data/experiments/scale-50-v2/reports/scale-report.json \
  --v1-audit data/experiments/scale-50/reports/scale-audit.csv \
  --v2-audit data/experiments/scale-50-v2/reports/scale-audit.csv
```

On the preserved September 2026 raw data, v2 selects 25 books per topic. It removes four
Operating Systems candidates (*Power system operation*, *Computer aided power system operation
and analysis*, *Robot Operating System*, and *The Operating System*) and adds four other candidates.
Linear Algebra identities are unchanged. Of 200 candidates, 16 were rejected (4 competing-subject,
12 without topic evidence); rejected titles, IDs, reasons, and subject evidence are in the v2
report. Every relevance evidence item records the exact Open Library work/edition external ID;
selected-book evidence is also listed in the JSON report and referenced by record ID in the CSV.
Among selected books, 24 have matching subject evidence and **26 are title-only,
unverified**. These are automated diagnostics, not human correctness ratings.

| Measure | v1 | v2 |
| --- | ---: | ---: |
| Selected books | 50 | 50 |
| Description coverage | 12 | 11 |
| TOC coverage / entries | 4 / 177 | 4 / 166 |
| Preface, introduction, preview, sample | 0 | 0 |
| Broken references / missing provenance | 0 | 0 |
| Two offline builds byte-identical | yes | yes |
| Audited relevance precision | unavailable | unavailable |

The evidence loss is real: the v1 metadata collector only fetched detail pages for its first
28 search results, so replacement candidates later in that same raw search have less detail.
Do not claim that removing four suspicious titles proved a precision gain. The automatic gate is
not human ground truth. Both generated audit CSVs keep `topic_relevant` blank, and `compare-scale`
returns `null` for any incomplete precision/delta.

### One-pass human relevance review

Recreate both reports and blank audits offline from the preserved raw artifacts. Use a separate
ignored directory so generated files do not overwrite human work:

```bash
uv run data-pipeline report-scale \
  --manifest configs/experiments/scale-50.json \
  --data-dir data/experiments/scale-50 \
  --output data/experiments/relevance-review/v1
uv run data-pipeline report-scale \
  --manifest configs/experiments/scale-50-v2.json \
  --data-dir data/experiments/scale-50 \
  --output data/experiments/relevance-review/v2
uv run data-pipeline prepare-relevance-review \
  --v1-report data/experiments/relevance-review/v1/scale-report.json \
  --v2-report data/experiments/relevance-review/v2/scale-report.json \
  --v1-audit data/experiments/relevance-review/v1/scale-audit.csv \
  --v2-audit data/experiments/relevance-review/v2/scale-audit.csv \
  --output data/experiments/relevance-review/relevance-review.csv
```

`prepare-relevance-review` requires the two reports to name the same raw snapshot hashes and
timestamps. The v1 manifest selects the latest local matching artifact, while v2 pins exact
snapshots; if new raw data makes them differ, preparation stops rather than comparing different
inputs. It also requires untouched, blank generated audits. The union CSV has one row per
`book_id`, with selection/replacement flags, bibliographic identity, v2 gate basis, source record
IDs, source-attributed subject and title evidence, and empty `topic_relevant`/`notes`. For a
v1-only book, a v2 rejection is attached only when its topic and title uniquely match; the
`relevance_match_method=unique_topic_title` column flags that association for human checking.
These diagnostics are evidence to inspect, not automatic relevance labels.

On the preserved data, the review has **54 unique books**: 46 shared, four v1-only, and four
v2-only. A reviewer should fill `topic_relevant` with `yes` or `no` for every row, optionally add
notes, and keep the edited CSV outside the generated report directories. No precision is computed
until all 54 judgments exist. Then split the one review back into both original audit formats:

```bash
uv run data-pipeline finalize-relevance-review \
  --v1-report data/experiments/relevance-review/v1/scale-report.json \
  --v2-report data/experiments/relevance-review/v2/scale-report.json \
  --v1-audit data/experiments/relevance-review/v1/scale-audit.csv \
  --v2-audit data/experiments/relevance-review/v2/scale-audit.csv \
  --review data/experiments/relevance-review/relevance-review.csv \
  --v1-output data/experiments/relevance-review/v1-reviewed.csv \
  --v2-output data/experiments/relevance-review/v2-reviewed.csv
uv run data-pipeline compare-scale \
  --v1-report data/experiments/relevance-review/v1/scale-report.json \
  --v2-report data/experiments/relevance-review/v2/scale-report.json \
  --v1-audit data/experiments/relevance-review/v1-reviewed.csv \
  --v2-audit data/experiments/relevance-review/v2-reviewed.csv
```

Finalization rejects missing, duplicate, unknown, wrong-topic, or incomplete labels before writing
either review audit, and never overwrites an existing output. The shared-book judgment is copied
into both audits consistently. The 2026-09-16 experiment has **no human labels yet**; the real-data
precision for both versions remains unavailable.

## Setup and commands

Python 3.12 or later and [uv](https://docs.astral.sh/uv/) are required.

```bash
uv sync
uv run data-pipeline search --topic operating-systems --limit 5
uv run data-pipeline collect --topic operating-systems --limit 5
uv run data-pipeline collect --topic linear-algebra --limit 5
uv run data-pipeline collect-publisher --source wiley-ela10
uv run data-pipeline collect-publisher-document --source wiley-ela10-chapter-1
uv run data-pipeline collect-public-page --source ecampus-stallings-os4
uv run data-pipeline collect-open-textbook --source ostep-1.10
uv run data-pipeline collect-open-textbook --source hefferon-linear-algebra-4
uv run data-pipeline collect-open-textbook --source understanding-linear-algebra-2022
uv run data-pipeline collect-open-textbook --source think-os-0.7.4
uv run data-pipeline collect-open-textbook --source nicholson-linear-algebra-2023
uv run data-pipeline collect-open-textbook --source hailperin-os-middleware-1.2
uv run data-pipeline collect-open-textbook --source xv6-riscv-rev5
uv run data-pipeline build-manifest --manifest configs/mvp.json --data-dir data
uv run data-pipeline report
```

The Wiley OSC7 publisher and appendix collectors remain available as reviewed experiments, but
they are not part of `configs/mvp.json` because the current Hailperin source replaces that book and
all book-scoped evidence in the final ten-book set.

`collect-publisher` requires the matching metadata book to exist in `data/processed` and stops if
the exact canonical `book_id` is absent. Unknown publisher URLs cannot be supplied at the CLI; a
new source must first be reviewed and added to the small version-controlled allowlist.
`collect-publisher-document` applies the same allowlist and exact-book requirement. It verifies the
title, edition, ISBN-bearing publisher page, reviewed companion TOC heading, PDF media type, PDF
signature, and reviewed text markers before emitting canonical evidence. A direct companion-page
link is additionally mandatory for sources that declare one. The Anton excerpt instead uses
Wiley's ISBN-bearing catalog URL because the retired title-home redirect no longer resolves.
Repeated retrievals of the same allowlisted URL update its canonical source snapshot. Documents
and TOC entries owned by an older snapshot are replaced, while every immutable raw response is
still retained for audit and offline rebuilding.
`collect-public-page` applies the same exact-book and allowlist boundary to a reviewed ordinary
public HTML source. It additionally rejects a response unless the ISBN, edition, complete reviewed
entry count, and top-level TOC structure all match.
`collect-open-textbook` verifies the title, authors, publisher, version, year, ISBN, complete
TOC or PDF outline, public document identity, resource media types, and reviewed text markers.
Source-specific size limits are enforced: 5 MiB for OSTEP resources, 10 MiB for the reviewed 7.63
MB Hefferon PDF, 1 MiB per reviewed PreTeXt or Think OS HTML page, and 512 KiB per Nicholson HTML
page. The Hailperin PDF is limited to 8 MiB and may follow redirects only within the reviewed
Internet Archive host boundary. The xv6 PDF is limited to 2 MiB and must not redirect away from
its reviewed MIT URL. The command removes the configured weak candidate and all records scoped to
that book before merging the new book. Repeated runs retain five books per topic and update only
the selected source snapshots.

[`configs/mvp.json`](configs/mvp.json) declares the twelve raw request identities used by the
current milestone and the exact ten canonical book IDs expected after replacements. The
`build-manifest` command selects the latest immutable artifact matching each provider, topic,
source slug, and request limit, rebuilds without network access, and refuses to publish output if
an input is missing or the final book set differs. This keeps local raw snapshots out of Git while
making the selected source set and replacement result version controlled. Use the lower-level
`build --raw ...` command when reproducing one specifically timestamped set of artifacts rather
than the latest local set.

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
  --raw data/raw/publisher_document/linear-algebra/<artifact>.json \
  --raw data/raw/public_book_page/operating-systems/<artifact>.json \
  --raw data/raw/open_textbook/operating-systems/<artifact>.json \
  --raw data/raw/open_textbook/linear-algebra/<artifact>.json
```

Repeat `--raw` for multiple artifacts when rebuilding the combined two-topic dataset. Sequential
`collect` commands safely merge new books into the existing canonical dataset. Conflicting records
with the same deterministic ID stop the build instead of being silently selected.

`report` and `build-manifest` print both aggregate topic coverage and one row per book. The
per-book section explicitly lists missing TOC, description, preface/introduction, and
preview/sample evidence. In the current result, two commercial books still lack both
preface/introduction and preview/sample evidence, while the Anton book has a sample chapter
but no public preface/introduction. Optional gaps do not invalidate otherwise sound metadata.

Supported MVP topics are `operating-systems` and `linear-algebra`. Generated raw and processed
data are intentionally ignored by Git; only small test fixtures should be committed.

## Topic taxonomy

Every topic's identity (domain, Open Library/Google Books search terms, and the
`topic-evidence-v1` relevance pattern) is declared in
[`configs/topics.json`](configs/topics.json) and loaded by
[`src/data_pipeline/topics.py`](src/data_pipeline/topics.py); adding a topic is a config change,
not a code change. Beyond the two curated MVP topics above, `configs/topics.json` also declares
`algorithms`, `databases`, `discrete-mathematics`, and `probability-statistics` for generic
`search`/`collect` use. Each was validated with a live 5-book Open Library search before being
added: `databases`, `discrete-mathematics`, and `probability-statistics` returned five directly
relevant textbooks each; `algorithms` returned three relevant textbooks and two adjacent
popular-science titles, which is why a relevance gate exists for scale experiments. None of these
four are part of the curated MVP or Scale Pilot manifests yet.

## Verification

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

## TOC collection diagnosis (2026-09-19)

The generic Open Library collector defaults to details for only the first `limit + 3`
search candidates. Rejected, duplicate, or relevance-filtered candidates can cause later
selected books to have no fetched edition details. That is not proof that their TOC is absent.
To cover more of the search pool explicitly (maximum 100 candidates):

```bash
uv run data-pipeline collect --topic operating-systems --limit 25 \
  --provider open-library --detail-limit 100 --data-dir data/experiments/toc-expanded
```

`--detail-limit` is Open-Library-only, bounded by the search candidate budget. It controls
both edition and work detail candidates; existing request pacing and retry rules apply.
The default stays unchanged to avoid silently increasing network traffic. Recollection
creates a new raw artifact: an offline rebuild cannot recover responses never fetched.

`report-scale` now records a book-specific TOC reason in `failure_analysis.by_book` and
in the audit CSV column `missing_toc_reason` (blank when TOC exists):

- `edition_detail_not_fetched`: no preserved detail response or fetch failure for the edition
- `rate_limit`, `network_failure`, `provider_http_error`: recorded edition-fetch failure
- `invalid_provider_response`: invalid edition response
- `provider_returned_no_evidence`: fetched edition has no TOC or an empty list
- `toc_parse_failure`: nonempty/malformed TOC exists but no canonical entries survived
- `unsupported_source`: no supported edition evidence path was found

Reasons describe preserved responses, not whether a TOC exists anywhere on the web.
Partial TOCs are not certified complete by this report. Canonical JSONL schemas and
edition matching are unchanged; TOCs from other editions are not substituted.

### Live reproduction

On 2026-09-19, an Operating Systems run requested 25 books, discovered 100 candidates,
and fetched 28 edition plus 28 work details with no recorded fetch failures. The selected
25 books had **2 TOCs and 23 fetched editions without TOC evidence**. Across the 28 fetched
editions, 3 contained TOCs; one was outside the selected set. Therefore this experiment's
low coverage is primarily missing provider evidence, not a demonstrated parser defect.
Increasing the detail budget alone does not promise to improve these 25 books.

The raw response SHA-256 is
`6fdca83dfd96` (prefix); generated raw data and audit CSV stay outside Git.
The report rebuilt the four canonical files twice with byte-identical results; all reference,
TOC-parent, provenance and validation error counts were zero. On Windows use Python UTF-8
mode (`python -X utf8 -m data_pipeline.cli ...`) if the terminal cannot print report punctuation.

Next collection work should use a second public publisher/catalog source, with exact
ISBN/edition verification and retained raw provenance. This change does not implement that
source, ML scoring, or a claim of improved live TOC coverage. The synthetic regression verifies
that an explicitly larger detail budget preserves an otherwise unqueried edition's TOC.

## Missing-TOC enrichment

After generic metadata collection, run the opt-in reviewed-source fallback:

```bash
uv run data-pipeline enrich-toc --data-dir data/experiments/scale-50 --dry-run
uv run data-pipeline enrich-toc --data-dir data/experiments/scale-50 --max-sources 4
```

This command matches missing-TOC books by exact canonical ISBN identity and topic against
existing `PUBLISHER_SOURCES` and `PUBLIC_BOOK_SOURCES`. Publisher pages are tried first.
It reuses their ISBN/title/edition/completeness checks, preserves raw HTML, and merges only
validated evidence. It never substitutes an OER book or a different edition to raise coverage.
This connects the already-reviewed sources to the scale workflow; it is not a new generic
web crawler or a claim that all books now have a supported source.

Existing TOCs are skipped, including on a second invocation. The source-attempt budget is
bounded (default 4, maximum 20). Fetch/identity/parser failures are recorded and subsequent
sources are attempted; successful prior enrichments remain saved. Exit status is 1 if any
attempt failed, even if others succeeded. Missing sources are listed as remaining books,
not treated as network failures. A dry run neither fetches nor writes anything.

`reports/toc-enrichment.json` contains before/after book counts, added and remaining book IDs,
source-level attempts and errors. It describes the latest invocation and is replaced on rerun;
immutable raw artifacts remain retained separately. The canonical four-JSONL schema is unchanged.
To reproduce the exact output order offline, pass original metadata and enrichment raw artifacts
to `build --raw ... --raw ...` in collection timestamp order. An old metadata-only manifest will
still reproduce the baseline; explicitly include the enrichment artifacts when rebuilding.

### Verified result: 2026-09-20 KST

Used the **same 25 Operating Systems books** from the 2026-09-19 experiment, with a separate
output copy at `data/experiments/toc-enriched-20260920`.

| Metric | Before | After |
| --- | ---: | ---: |
| Books | 25 | 25 |
| Books with TOC | 2 (8%) | 5 (20%) |
| TOC entries | 40 | 294 |
| Books with description | 7 | 8 |

New exact-edition TOCs: Wiley *Operating System Concepts*, 7th edition (ISBN 9780471694663,
26 entries); eCampus *Advanced Concepts in Operating Systems*, 1st edition (9780070575721,
27 entries); eCampus Stallings *Operating Systems*, 4th edition (9780130319999, 201 entries).
The existing edition/provenance validators accepted all three live responses. No new raw text
or third-party book content is committed to Git.

Offline replay in collection order produced four byte-identical JSONL files. Book records and
prior TOC entries were unchanged, and canonical validation reported no errors. Tests cover
repeated-run network skipping, wrong-edition rejection, raw preservation, dry runs, source
budgets and continuation after a failed provider. Full suite: 157 passed; Ruff check and format
check passed.

Twenty of these 25 books still lack TOCs. This result is a 12-percentage-point improvement on
this fixed Operating Systems sample, not a 50-book or arbitrary-book coverage claim. Wider
coverage requires additional reviewed publisher/catalog adapters and exact-edition discovery.

### Additional flat-TOC coverage (2026-09-20)

Added a reusable parser for bold headings separated by line breaks, preserving chapter labels
and representing the observed flat list at level 1. Text outside supported headings, empty
headings, changed entry counts, titles, ISBNs, editions or chapter sequences fail validation.
The reviewed catalog registry now includes:

- Tanenbaum, *Distributed Operating Systems*, first edition, ISBN 9780132199087:
  https://cincinnatistate.ecampus.com/distributed-operating-systems-1st/bk/9780132199087
- Bach, *Design of the UNIX Operating System*, first edition, ISBN 9780132017992:
  https://wright.ecampus.com/design-unix-operating-system-1st-bach/bk/9780132017992

Live enrichment on the same 25-book set increased TOC coverage from 5/25 (20%) to 7/25 (28%),
adding 24 entries (294 -> 318). Relative to the original metadata-only baseline this is
2/25 -> 7/25. Eighteen books remain unsupported/missing; no generalized coverage is claimed.
Both pages passed exact-edition identity and reviewed chapter-sequence validation. Raw HTML
is preserved locally and excluded from Git. Full tests: 161 passed. Offline chronological
replay of all raw artifacts again produced four byte-identical JSONL files.
Run `enrich-toc` again to pick up newly supported books; already populated TOCs are skipped.
For a fresh baseline use `--max-sources 6` to allow all currently registered sources in one run.

### Combined 50-book reproduction (2026-09-20 KST)

After integrating the TOC hierarchy checks and relevance-review workflow from `main`, a live run
against a temporary copy of the 50-book v1 scale dataset collected all six eligible reviewed
sources without failures:

| Topic | Books with TOC before | Books with TOC after |
| --- | ---: | ---: |
| Linear Algebra | 2/25 | 3/25 |
| Operating Systems | 2/25 | 7/25 |
| Combined | 4/50 | 10/50 |

The six additions were the exact ISBN editions listed in `toc-enrichment.json`: one Wiley
Linear Algebra title and five Operating Systems titles from Wiley or reviewed catalog pages.
Canonical validation succeeded after every collection. Raw responses and the temporary dataset
remain outside Git. Forty selected books still lack TOCs, so this is a bounded improvement rather
than sufficient evidence coverage for a representative 50-book ML gold evaluation.

### Scale-50 v2 exact-edition expansion (2026-09-21 KST)

The reviewed paragraph-sequence parser adds the 10th edition of Wiley's *Operating System
Concepts* (ISBN 9781119800361) from an exact-edition eCampus page. It preserves ten parts and
twenty-six chapter or appendix entries as a two-level, 36-entry TOC and rejects changed identity,
edition, entry count, part titles, or chapter labels.

A live run against a temporary copy of the relevance-gated Scale-50 v2 dataset collected every
eligible reviewed source without failures. Coverage increased from 4/50 to 11/50: Linear Algebra
2/25 to 3/25 and Operating Systems 2/25 to 8/25. The source HTML, raw artifacts, and generated
dataset remain outside Git. Thirty-nine selected books still lack TOCs.

The same investigation found a richer exact-edition page for *Operating System Concepts
Essentials*, 2nd edition, but the selected record already contains a three-entry provider TOC.
`enrich-toc` therefore skips it rather than merging two source trees and double-counting headings.
Replacing or preferring a more complete TOC is a separate source-selection policy decision.

### Scale-50 v2 Linear Algebra expansion (2026-09-21 KST)

The reviewed catalog registry also includes Richard C. Penney's *Linear Algebra: Ideas and
Applications*, fourth edition (ISBN 9781118909584):
https://wright.ecampus.com/linear-algebra-ideas-applications-4th/bk/9781118909584

Its exact-edition page exposes 161 page-numbered paragraphs. The parser preserves four front
matter entries, eight explicitly bold chapter roots with their 147 ordered children, and two back
matter entries. It does not infer deeper section nesting that the HTML does not encode. Identity,
edition, total count, root titles, chapter labels, per-root child-label sequences, and per-root
child counts are all validated before evidence is merged.

A live run against a temporary copy of the same Scale-50 v2 baseline collected all eight eligible
reviewed sources without failures. Coverage increased from 4/50 to 12/50: Linear Algebra 2/25 to
4/25 and Operating Systems 2/25 to 8/25. Relative to the preceding expansion, this source adds one
Linear Algebra book and 161 TOC entries. Raw HTML, raw artifacts, and generated canonical data
remain outside Git. Thirty-eight selected books still lack TOCs, so source expansion remains the
priority before treating a 50-book ML sample as representative.

### Scale-50 v2 flat-table expansion (2026-09-21 KST)

The reviewed catalog registry includes Larson and Edwards, *Elementary Linear Algebra*, fifth
edition (ISBN 9780618335671):
https://cincinnatistate.ecampus.com/elementary-linear-algebra-5th-larson-ron/bk/9780618335671

The exact-edition page exposes a flat 66-row publisher table. The parser verifies and excludes the
final publisher-rights notice, then preserves the remaining 65 rows in source order at level 1.
The page provides no structural indentation, so the pipeline does not invent parent relationships
or recover numbering that is absent from the HTML. Title, ISBN, edition, entry count, and every
ordered row title must match the reviewed contract.

A live run against another temporary copy of the same Scale-50 v2 baseline collected all nine
eligible reviewed sources without failures. Coverage increased from 4/50 to 13/50: Linear Algebra
2/25 to 5/25 and Operating Systems 2/25 to 8/25. Relative to the preceding expansion, this source
adds one Linear Algebra book and 65 TOC entries. Raw HTML, raw artifacts, and generated canonical
data remain outside Git. Thirty-seven selected books still lack TOCs.

### Scale-50 v2 deep OS hierarchy expansion (2026-09-21 KST)

The reviewed catalog registry includes Gary Nutt, *Operating Systems: A Modern Perspective*, third
edition (ISBN 9780201741964):
https://campusstore.miamioh.edu/operating-systems-modern-perspective-3rd/bk/9780201741964

The exact-edition page exposes 429 entries at four observed indentation values. For this source,
indentation 0 is front or back matter, 20 is a chapter, 40 is a section, and 60 is a lower-level
entry. Treating only indentation 0 as a root would incorrectly attach every chapter to *To the
Instructor*, so the reviewed format explicitly treats indentation 20 and below as roots. It
validates 24 ordered root titles, direct-child counts, descendant counts, and the total entry count
before merging the hierarchy.

A live run against a temporary copy of the same Scale-50 v2 baseline collected all ten eligible
reviewed sources without failures. Coverage increased from 4/50 to 14/50: Linear Algebra 2/25 to
5/25 and Operating Systems 2/25 to 9/25. Relative to the preceding expansion, this source adds one
Operating Systems book and 429 TOC entries. Raw HTML, raw artifacts, and generated canonical data
remain outside Git. Thirty-six selected books still lack TOCs.
