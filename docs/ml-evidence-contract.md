# ML book evidence contract

## Purpose

`book-evidence-v1` is a provider-independent handoff from Data-Pipeline to ML. It does not try to
turn all books into TOC-bearing books, infer concepts, or assign confidence and ranking weights.
Instead, it preserves the strongest available collected evidence for every canonical book and
makes its origin explicit.

The Scale-50 acquisition run on 2026-09-22 found usable TOCs for 20/50 books. The other 30 books
remain useful through verified descriptions, subject/topic metadata, and title metadata. Public
structured data and reviewed public-web data are complementary sources; neither replaces the
other. No generated TOC or description is added.

## Artifact

The output is deterministic JSONL with one `MlBookEvidence` record per canonical book:

```text
schema_version
contract_version
book
book_content_hash
evidence[]
```

Every evidence item contains:

```text
evidence_id
evidence_type
text
source_id
provider
source_type
source_url
source_retrieved_at
source_content_hash
source_evidence_tier
source_evidence
edition_relation
provenance_hash
```

`source_evidence` is the canonical provenance snapshot, including source edition/ISBN data,
discovery method, match basis, and validation status when available. TOC evidence also carries its
canonical entry ID, parent, level, order, label, and full TOC path.
Document evidence carries the canonical document ID, type, and content hash. Minimal metadata
evidence identifies whether its value came from the canonical title or topics.

The evidence categories are deterministic provenance labels, not scores:

| Category | Meaning |
| --- | --- |
| `toc_exact` | Exact-edition TOC from a structured source |
| `toc_public_web_exact` | Reviewed exact-edition TOC from a public webpage |
| `toc_same_work` | Provider-native same-Work TOC from another edition |
| `toc_unspecified` | Legacy TOC without explicit edition provenance; never promoted to exact |
| `description` | Collected description or publisher summary |
| `document` | Other collected canonical document evidence |
| `subject` | Canonical subject/topic metadata |
| `metadata_minimal` | Canonical title and subtitle fallback |

`edition_relation` distinguishes `exact`, `same_work`, `canonical_record`, and `unspecified`.
Legacy descriptions whose edition relation was never established remain `unspecified`; the export
does not silently promote them to exact-edition evidence.

## Validation and determinism

The exporter first requires a valid canonical four-file dataset. It then validates that every
exported item:

- belongs to the same book as its source;
- repeats the source provider, URL, content hash, and evidence tier exactly;
- matches its canonical TOC or document record;
- keeps same-Work evidence distinct from exact-edition evidence;
- has a deterministic provenance hash and identifier;
- appears only once.

The validator also compares the artifact with a fresh deterministic projection of the canonical
input. Books with no TOC still have title and topic evidence, so a valid canonical book cannot
produce an empty evidence list.

## Rebuild

From a local canonical Scale-50 result:

```bash
uv run data-pipeline export-ml-evidence \
  --dataset-dir data/experiments/scale-50-bulk-web-20260922/processed \
  --output data/experiments/scale-50-bulk-web-20260922/ml-evidence-v1/book-evidence.jsonl \
  --report data/experiments/scale-50-bulk-web-20260922/ml-evidence-v1/summary.json
```

The generated artifact and summary are ignored local data, like the canonical inputs. Unit tests
use tiny committed fixtures and do not download external data. The 12.59 GB Open Library Editions
dump is not a runtime dependency: the small local projection and already-built canonical data are
sufficient for export.

## Scale-50 result

The 2026-09-22 export produced 50 records and passed validation with no errors:

| Measure | Result |
| --- | ---: |
| Books with TOC evidence | 20 |
| Books with exact-edition TOC | 19 |
| Books with reviewed public-web TOC | 16 |
| Books with same-Work alternate TOC | 1 |
| Books with unspecified-edition TOC | 0 |
| Metadata-fallback-only books | 30 |
| Books with zero evidence | 0 |

The exact and public-web counts overlap: reviewed public-web exact TOCs are exact-edition evidence.
They must not be summed as independent book coverage.

Evidence row counts were:

| Evidence type | Rows |
| --- | ---: |
| `toc_exact` | 163 |
| `toc_public_web_exact` | 1,561 |
| `toc_same_work` | 493 |
| `description` | 27 |
| `subject` | 100 |
| `metadata_minimal` | 50 |

ML may later compare TOC-only, metadata-only, combined, and source-aware weighting policies. This
contract intentionally does not choose those weights.
