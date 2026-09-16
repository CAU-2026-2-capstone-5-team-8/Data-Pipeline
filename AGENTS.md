# AGENTS.md

## 1. Project Overview

This repository is the data collection and normalization pipeline for the CAU Capstone Team 8 book recommendation project.

The system recommends technical books by comparing:

- what a reader currently knows,
- what the reader wants to learn,
- what prerequisite knowledge a book expects,
- what concepts the book covers,
- and the textual difficulty of the book.

The recommendation system is concept-centered.

However, **this repository does not perform recommendation, concept mastery estimation, book difficulty scoring, or ML inference.**

The responsibility of this repository is:

> Collect reliable book metadata and publicly available book contents such as table of contents, descriptions, prefaces, introductions, and preview/sample text, preserve their provenance, normalize them into a stable schema, and provide them to the ML repository.

The initial target language is English.

The initial subject hierarchy is:

```text
Computer Science
└── Operating Systems

Mathematics
└── Linear Algebra
```

The first milestone uses only a small dataset:

- 5 Operating Systems books
- 5 Linear Algebra books
- 10 books total

Do not optimize for hundreds or thousands of books before this first pipeline works end-to-end.

---

## 2. Core Design Principle

The most important design principle is:

> Preserve evidence first. Infer later.

The Data-Pipeline repository collects evidence about a book.

Examples:

- title
- authors
- ISBN
- publisher
- publication year
- subject/category
- description
- table of contents
- preface
- introduction
- publicly available preview/sample text
- index, when available
- source URL
- source provider
- licensing/rights information when available

The ML repository will later use these materials to infer:

- required concepts
- prerequisite knowledge
- covered concepts
- target level
- terminology requirements
- lexical difficulty
- syntactic complexity
- concept density
- recommendation suitability

Do **not** implement those ML features in this repository.

---

## 3. System Boundary

The intended pipeline is:

```text
External Sources
    ↓
Collectors
    ↓
Raw Responses
    ↓
Parsing / Normalization
    ↓
Validation / Deduplication
    ↓
Canonical Dataset
    ↓
ML Repository
```

The boundary between repositories is:

```text
Data-Pipeline
    ↓
canonical book/document data
    ↓
ML
    ↓
concept extraction
book requirement profile
reader profile
matching/ranking
evaluation
```

The Data-Pipeline repository should not depend on the ML repository.

The ML repository should be able to consume the canonical dataset without knowing where each item was collected from.

---

## 4. Source Strategy

Use sources in the following priority order:

1. Official/public APIs
2. Publisher or author-provided public pages
3. Open educational resources
4. Public HTML pages that can be fetched normally
5. Browser automation only when genuinely necessary

Initial metadata sources may include:

- Google Books API
- Open Library API

Additional public sources may be introduced for:

- table of contents
- preface
- introduction
- preview text
- sample chapters

A metadata provider and a document provider do not need to be the same source.

For example:

```text
Google Books
    → ISBN / title / author / publisher

Publisher or author site
    → TOC / preface / sample

Open textbook site
    → publicly available text
```

The architecture must allow these sources to be combined into one canonical book record.

---

## 5. Scraping and Access Rules

Do not build aggressive scraping infrastructure.

Do not attempt to bypass:

- authentication
- paywalls
- CAPTCHA
- bot protection
- access control
- rate limiting
- technical restrictions

Prefer an API when an appropriate public API exists.

Respect provider rate limits and terms of use.

Use reasonable request delays and retry policies.

Do not introduce Playwright unless normal HTTP/API access is insufficient for a source that is genuinely needed.

Do not make the entire pipeline dependent on a single commercial bookstore website.

The project must continue functioning even if one source becomes unavailable.

---

## 6. Provenance Is Mandatory

Every piece of collected information must remain traceable to its origin.

Never normalize data in a way that destroys its provenance.

Whenever possible preserve:

- provider
- source URL
- retrieval timestamp
- external identifier
- source type
- license or rights statement
- content hash

The project must be able to answer:

> Where did this piece of book information come from?

This is important both for debugging and for later capstone evaluation/documentation.

---

## 7. Canonical Data Model

The canonical output should initially consist of four JSONL datasets:

```text
books.jsonl
documents.jsonl
toc.jsonl
sources.jsonl
```

Do not prematurely introduce PostgreSQL into this repository.

The Backend repository will eventually own the service database.

JSONL is the primary interchange format for the initial milestone.

---

## 8. books.jsonl

One record represents one normalized book.

Example:

```json
{
  "book_id": "isbn13:9780000000000",
  "isbn_10": null,
  "isbn_13": "9780000000000",
  "title": "Example Book",
  "subtitle": null,
  "authors": ["Example Author"],
  "publisher": "Example Publisher",
  "published_year": 2024,
  "language": "en",
  "topics": [
    "computer-science",
    "operating-systems"
  ]
}
```

Prefer ISBN-13 as the stable identifier when available.

When ISBN is unavailable, use a deterministic fallback identifier based on normalized bibliographic information or a provider identifier.

Do not silently create duplicate books from multiple providers.

Deduplication priority should generally be:

1. ISBN-13
2. ISBN-10
3. normalized title + author
4. provider identifier as a last resort

Keep deduplication logic simple and inspectable for the MVP.

---

## 9. documents.jsonl

This dataset stores textual evidence associated with books.

Example:

```json
{
  "document_id": "doc_xxx",
  "book_id": "isbn13:9780000000000",
  "document_type": "preface",
  "text": "Publicly available text...",
  "source_id": "source_xxx",
  "content_hash": "sha256:..."
}
```

Initial `document_type` values may include:

```text
description
publisher_summary
preface
introduction
preview
sample_chapter
index
other
```

Do not assume every book has every document type.

The pipeline must tolerate missing information.

For example:

```text
Book A
metadata       yes
description    yes
TOC            yes
preface        yes
preview        yes

Book B
metadata       yes
description    yes
TOC            yes
preface        no
preview        yes

Book C
metadata       yes
description    yes
TOC            yes
preface        no
preview        no
```

Missing optional data must not make the entire book record invalid.

---

## 10. toc.jsonl

Table-of-contents structure is especially important for downstream learning-goal matching.

Do not flatten the TOC into one large text string when hierarchy is available.

Preserve hierarchy.

Example:

```json
{
  "toc_entry_id": "toc_xxx",
  "book_id": "isbn13:9780000000000",
  "parent_entry_id": null,
  "level": 1,
  "order_index": 4,
  "label": "4",
  "title": "Concurrency",
  "source_id": "source_xxx"
}
```

A child item might look like:

```json
{
  "toc_entry_id": "toc_yyy",
  "book_id": "isbn13:9780000000000",
  "parent_entry_id": "toc_xxx",
  "level": 2,
  "order_index": 2,
  "label": "4.2",
  "title": "Semaphores",
  "source_id": "source_xxx"
}
```

Do not use floating-point values such as `4.2` as ordering keys.

Use explicit hierarchy and integer ordering.

The TOC will later be used by the ML repository to infer concepts and compare them with user learning goals.

---

## 11. sources.jsonl

Every collected artifact should reference a source record.

Example:

```json
{
  "source_id": "source_xxx",
  "book_id": "isbn13:9780000000000",
  "provider": "google_books",
  "source_type": "metadata_api",
  "url": "https://...",
  "external_id": "...",
  "retrieved_at": "2026-09-12T12:00:00Z",
  "license": null,
  "rights_note": null,
  "content_hash": "sha256:..."
}
```

Possible source types include:

```text
metadata_api
publisher_page
author_page
open_textbook
preview_page
sample_page
other
```

If licensing information is not available, store `null`.

Never invent license information.

---

## 12. Raw Data Preservation

Raw provider responses must be kept separate from normalized data.

Suggested structure:

```text
data/
├── raw/
│   ├── google_books/
│   ├── open_library/
│   └── web/
│
├── processed/
│   ├── books.jsonl
│   ├── documents.jsonl
│   ├── toc.jsonl
│   └── sources.jsonl
│
└── examples/
```

`data/raw/` and `data/processed/` should normally be excluded from Git.

Do not commit large third-party datasets or copyrighted book text.

Only small, legally appropriate test/example fixtures should be committed.

Preserving raw responses allows parsing logic to be fixed and rerun without repeatedly contacting external services.

---

## 13. Topic Representation

Topics are hierarchical.

Initial taxonomy:

```text
computer-science
└── operating-systems

mathematics
└── linear-algebra
```

Do not treat `Computer Science` or `Mathematics` alone as the actual recommendation granularity.

The first experiments operate at the subtopic level:

```text
Operating Systems
Linear Algebra
```

The data model should allow future expansion without schema changes:

```text
computer-science
├── operating-systems
├── networking
├── databases
└── algorithms

mathematics
├── linear-algebra
├── discrete-mathematics
├── probability
└── number-theory
```

For the MVP, taxonomy configuration may live in a small version-controlled YAML or JSON file.

Do not build a taxonomy management system yet.

---

## 14. Collector Architecture

Collectors should be source-specific adapters.

Suggested structure:

```text
src/
└── data_pipeline/
    ├── collectors/
    │   ├── base.py
    │   ├── google_books.py
    │   ├── open_library.py
    │   └── web.py
    │
    ├── parsers/
    ├── normalizers/
    ├── models/
    ├── storage/
    ├── validation/
    ├── reporting/
    └── cli.py
```

Avoid unnecessary abstraction, but keep provider-specific code isolated.

Metadata search and document collection are separate concerns.

A metadata source may support operations similar to:

```python
search_books(query, limit)
fetch_book(external_id)
```

A document source may provide:

```python
fetch_documents(book)
fetch_toc(book)
```

Do not force every provider to implement functionality it does not support.

Use Python protocols or lightweight interfaces where useful.

---

## 15. Technology Stack

Use:

```text
Python 3.12+
uv
httpx
pydantic
typer
tenacity
pytest
ruff
```

For HTML parsing, prefer a lightweight parser such as:

```text
selectolax
```

or:

```text
beautifulsoup4
```

Choose one unless there is a concrete reason to need both.

Do not add a heavy dependency without a demonstrated requirement.

Do not introduce:

- pandas solely for simple JSON processing
- a database
- Kafka
- Redis
- Celery
- distributed crawling infrastructure

during the MVP.

---

## 16. CLI

The pipeline should be runnable without manually opening Python files or notebooks.

Provide a small CLI.

The exact CLI may evolve, but the target workflow should resemble:

```bash
uv run data-pipeline search \
  --topic operating-systems \
  --limit 5
```

```bash
uv run data-pipeline collect \
  --topic operating-systems \
  --limit 5
```

```bash
uv run data-pipeline collect \
  --topic linear-algebra \
  --limit 5
```

```bash
uv run data-pipeline build
```

```bash
uv run data-pipeline report
```

A manifest/config-based command is also acceptable, for example:

```bash
uv run data-pipeline collect --config configs/mvp.yaml
```

Prefer reproducible commands over ad-hoc scripts.

---

## 17. Coverage Reporting

The first experiment is not successful merely because ten titles were found.

The pipeline must report how much usable evidence was actually obtained.

For example:

```text
Operating Systems
Books requested:      5
Metadata collected:   5
TOC available:        5
Description:          5
Preface/Introduction: 3
Preview/Sample:       4

Linear Algebra
Books requested:      5
Metadata collected:   5
TOC available:        4
Description:          5
Preface/Introduction: 2
Preview/Sample:       3
```

This coverage information is an important result of the first milestone.

It will determine whether the downstream ML design is feasible with the chosen sources.

---

## 18. Data Validation

At minimum validate:

- valid `book_id`
- non-empty title
- at least one author when available
- valid language representation
- valid source reference
- valid book/source relationship
- deterministic IDs
- duplicate ISBN detection
- duplicate source detection
- empty document text
- broken TOC parent relationships

Validation errors should be visible.

Do not silently discard records.

When a record cannot be normalized, preserve enough information to debug why.

---

## 19. Logging and Error Handling

Use structured and readable logging.

A failure to fetch one book must not crash the entire collection run unless continuing would corrupt the dataset.

Distinguish:

- network failures
- rate limits
- parsing failures
- missing optional fields
- invalid provider responses
- unsupported page structures

Retries should only be used for appropriate transient failures.

Do not retry deterministic parsing failures repeatedly.

---

## 20. Tests

Tests should focus on deterministic transformation logic.

Prioritize tests for:

- provider response parsing
- ISBN normalization
- book deduplication
- TOC hierarchy parsing
- document normalization
- source/provenance preservation
- validation

Network-dependent tests should not be the default test suite.

Use stored fixtures for provider responses.

The basic command:

```bash
uv run pytest
```

must work.

Code quality checks should include:

```bash
uv run ruff check .
uv run ruff format --check .
```

---

## 21. Non-Goals

Do NOT implement the following in this repository unless explicitly requested later:

- Reader Profile calculation
- Concept mastery estimation
- required-concept inference
- covered-concept inference
- learning-goal matching
- recommendation ranking
- recommendation scoring
- lexical difficulty scoring
- syntactic difficulty scoring
- LLM question generation
- user assessment
- Spring Boot integration
- production database design
- OCR
- mobile application features

Those belong to other components.

---

## 22. Relationship to the ML Design

The downstream ML design is concept-centered.

Eventually:

```text
Book evidence
(metadata / TOC / preface / preview)
        ↓
Concept Extraction
        ↓
Book Requirement Profile
```

The ML repository may derive:

```text
required concepts
covered concepts
target level
terminology
text difficulty
```

The user's state may later contain:

```text
Current Concept Knowledge
+
Learning Goals
```

The recommendation layer will compare them.

The Data-Pipeline must therefore preserve enough book evidence for this inference to be possible.

In particular, prioritize acquiring:

1. Table of contents
2. Preface / introduction
3. Book description
4. Public preview/sample text
5. Metadata

Do not reduce all of these inputs to one summary string.

---

## 23. First Milestone

The first milestone is intentionally small.

### Scope

Collect:

```text
5 Operating Systems books
5 Linear Algebra books
```

English-language technical books only.

### Required output

At the end of the milestone:

```text
books.jsonl
documents.jsonl
toc.jsonl
sources.jsonl
```

must be generated successfully.

The pipeline must also produce a coverage report.

### Questions the milestone must answer

1. Can metadata be collected reliably?
2. Can TOCs be obtained for most books?
3. Can prefaces, introductions, or descriptions be obtained?
4. How many books expose usable preview/sample text?
5. Can the information be normalized without manual per-book editing?
6. Is the collected evidence sufficient for downstream concept extraction?

Do not scale the crawler before answering these questions.

---

## 24. Definition of Done for MVP Data Collection

The MVP data pipeline is considered successful when:

- 10 target books can be collected reproducibly
- all books have normalized metadata
- provenance is preserved
- TOC information exists for a useful majority of books
- available public descriptions/prefaces/previews are captured
- failures and missing fields are explicitly represented
- duplicate books are avoided
- canonical JSONL outputs pass validation
- another developer can reproduce the dataset with documented commands
- the ML repository can consume the generated files without source-specific logic

---

## 24A. Second Milestone: Scale Pilot

Treat the completed ten-book dataset declared by `configs/mvp.json` as a curated regression and
golden dataset. Do not replace its identities or pursue 100% optional-evidence coverage as part of
this milestone.

The Scale Pilot tests the existing topics at a larger book count:

```text
approximately 25 Operating Systems books
approximately 25 Linear Algebra books
approximately 50 books total
```

Use a separate version-controlled experiment manifest under `configs/experiments/`. Preserve the
exact selected canonical book identities in that manifest, while keeping third-party raw and
generated processed data outside Git.

Prefer generic metadata and evidence collectors. Do not add book-specific parsers, exact URLs, or
ISBN allowlist entries merely to fill optional evidence gaps. Existing exact-edition allowlists
remain safety boundaries and must not be weakened. Missing evidence from a generic run is an
experiment result, not a reason to bypass those boundaries.

The report for this milestone must distinguish candidate discovery, normalization, deduplication,
edition mismatches, identifiers, evidence coverage, classified failures, data integrity, artifact
sizes, and build time. It must include per-topic and per-book evidence counts and prose sizes.
Generate a compact CSV or JSON audit artifact with blank fields for human identity, relevance,
TOC, prose, and edition judgments. Never fabricate those human judgments.

The same raw manifest must produce byte-identical canonical output in two offline builds. The
canonical four-JSONL schema remains unchanged so downstream ML code does not need provider-specific
knowledge. Do not add ML, concept inference, scoring, or recommendation logic here.

The Scale Pilot is successful when it reproducibly demonstrates where generic collection works
and where it fails at roughly fifty books. It is not required to make optional evidence coverage
100% before proceeding.

---

## 24B. Scale Pilot v2: Relevance Audit

Preserve the first fifty-book manifest and ten-book curated MVP. Evaluate a small, opt-in metadata
topic gate against the **same immutable raw responses** as the first scale experiment; do not
change the canonical JSONL contract or treat inferred topic relevance as human ground truth.
Record decisions, rejected candidates, weak title-only evidence, and changed selected identities.
Keep the original raw and v1 selection untouched. A precision claim requires independent human
labels for every selected book in both versions; report precision as unavailable until that audit
is complete. Do not add ML or per-book relevance allowlists.

---

## 25. Development Workflow for the Agent

Before writing implementation code:

1. Inspect the repository.
2. Read this `AGENTS.md` completely.
3. Inspect the current README and existing project files.
4. Produce a concise implementation plan.
5. Identify assumptions or uncertain external-source behavior.
6. Implement only the smallest vertical slice needed for the first milestone.

Do not generate a large framework before testing real data.

Prefer this order:

```text
project setup
    ↓
canonical models
    ↓
one metadata provider
    ↓
raw persistence
    ↓
normalization
    ↓
5-book test
    ↓
second provider / document source
    ↓
TOC + document collection
    ↓
10-book dataset
    ↓
coverage report
```

After each meaningful step:

- run tests
- run linting
- inspect generated output
- update README when usage changes

Do not claim the implementation works without running it.

---

## 26. Engineering Philosophy

Prefer:

- simple code
- reproducibility
- explicit schemas
- traceable data
- deterministic transformations
- small vertical slices
- real-data validation

Avoid:

- speculative abstractions
- premature scalability
- hidden magic
- irreversible normalization
- silent data loss
- source-specific assumptions leaking into downstream datasets

For this capstone, a transparent pipeline that reliably collects ten books is more valuable than a sophisticated crawler architecture that has not been validated on real data.
