# Scale-50 API enrichment — 2026-09-29

This experiment measures whether the configured YES24 and Springer Nature APIs close the
remaining evidence gap after the 2026-09-29 public-web expansion. It starts from the measured
25/50 TOC baseline at PR #45 head `e99965628917e99d4073f9c5ff28c899f381ad73`. The companion
[machine-readable report](scale-50-api-enrichment-2026-09-29.json) contains all 25 unresolved
books, per-book statuses, and the ignored raw-artifact path for every live response.

## Result

| Experiment | TOC books | Independent gain |
| --- | ---: | ---: |
| Public-web baseline | 25/50 | — |
| YES24 only | 25/50 | +0 |
| Springer only | 25/50 | +0 |
| YES24 → Springer combined | **25/50** | **+0** |

The overlap is `0 + 0 - 0 = 0`. All 25 baseline gaps remain unresolved. The measured API value is
**Low** for both providers on this remainder: neither API added a TOC, and neither produced usable
prose for a correctly selected textbook.

## Environment and secret handling

The CLI's existing `python-dotenv` loading was retained. Both `YES24_API_KEY` and
`SPRINGER_API_KEY` were present in the repository-root `.env`; only those booleans were checked.
The values were never printed or copied into request parameters, raw artifacts, reports, tests,
commits, or the PR. `.env` remains ignored, and `.env.example` now documents the empty
`SPRINGER_API_KEY=` variable.

The [YES24 Basic policy](https://developers.yes24.com/docs) currently states 20,000 requests/day
and 10 requests/second. The existing 0.25-second interval is more conservative and was retained.
Springer's [Basic Meta API policy](https://dev.springernature.com/docs/rate-limit-details/rate-limits/)
states 500 requests/day and 100 requests/minute; its interval was raised from 0.5 to 0.65 seconds
so the client remains below the per-minute ceiling. Every actual HTTP attempt, including a retry,
is counted as quota-bearing.

## Verified baseline and isolation

The live API work used independent `baseline`, `yes24-only`, `springer-only`, and `combined`
copies under `data/experiments/scale-50-api-enrichment-20260929/`. The copies were byte-identical
before enrichment; generated canonical files and raw responses remain ignored.

| Evidence | Rows | Books |
| --- | ---: | ---: |
| Books | — | 50 |
| TOC | 2,954 | 25 |
| Description | 30 | 25 |
| Preface | 1 | 1 |
| Introduction | 0 | 0 |
| Preview | 0 | 0 |
| Sample chapter | 0 | 0 |
| Other prose | 0 | 0 |
| Any prose | 31 | 26 |
| Metadata-fallback only | — | 25 |

Of the 25 TOC-unresolved books, 22 have an ISBN-13 and were eligible for exact-ISBN API lookup;
three have no ISBN and were intentionally skipped. The topic split remains Linear Algebra 11/25
and Operating Systems 14/25.

The source baseline hashes are:

| File | SHA-256 |
| --- | --- |
| `books.jsonl` | `18a6a3e6315bf75e0a38a4a7daf978659c151781a3a186db910dd9de050ef74d` |
| `documents.jsonl` | `4de329836d522b520196c9e9ce3510280a0c29449fa8c1a1bbc6538f082d105c` |
| `toc.jsonl` | `29ac161d4d40160e13c1a36f5c8d8d2f1eb4fed019bb543bb9f3822ec1e9a492` |
| `sources.jsonl` | `26b13001945e26ba0bc216460fa1d342eea2518642aaba5dbb74386f465c291f` |

## YES24 exact-ISBN TOC result

The existing `/v1/goods/content` enrichment completed all 22 logical lookups. All responses were
handled 404 outcomes, not transport failures: 21 were `GOODS_002` (`no_product`) and one was
`GOODS_001` (`product found, no TOC`). There were no parser failures or retries.

| Metric | Result |
| --- | ---: |
| Requests / logical completions | 22 / 22 |
| HTTP 404 | 22 |
| Product matches | 1 |
| No product | 21 |
| Product without TOC | 1 |
| TOC matches / entries | 0 / 0 |
| Failed / retries | 0 / 0 |
| Unique TOC gain | **0** |

The one product match is ISBN `9780136054276`. YES24 correctly identifies it as *Student
Solutions Manual for Differential Equations and Linear Algebra*, while the canonical title names
the textbook. Its no-TOC result is therefore a canonical selection/ISBN identity problem, not an
API failure.

## YES24 item-detail probe and prose potential

The probe used the officially documented
[`/v1/goods/itemDetail`](https://developers.yes24.com/api-doc/goods-item-detail) endpoint with
`searchType=ISBN13` and `detail=Y`, bounded to the 22 eligible books (below the requested 25-book
cap). Raw responses were preserved locally, while the report stores only field presence, character
counts, and hashes—not the returned prose.

| Metric | Result |
| --- | ---: |
| Requests | 22 |
| HTTP 200 / 404 | 1 / 21 |
| Retries / failures | 0 / 0 |
| Exact products | 1 |
| `bookIntroduction` present | 1 |
| `bookSummary` present | 0 |
| `tableOfContents` present | 0 |
| Mechanical description potential | +1 book |
| Actionable textbook description potential after identity review | **+0 books** |

The one introduction is 395 characters (SHA-256
`14e3b5b31a72f69053d0259716d8e7132dceb4b91a9ce0f91ff172ed4100c90d`) and belongs to the same
solutions manual. It satisfies the literal formula “canonical description absent + exact ISBN
product + nonblank introduction,” but importing it would attach a solutions-manual description to
the named textbook. This is evidence for selection cleanup, not a production description
enrichment milestone.

## Springer exact-ISBN chapter metadata result

Each of the 22 eligible books required one Meta API page request. Every request returned the
provider's normal no-match 404. No response contained a record, matching chapter, TOC entry, or
chapter abstract. These outcomes are `no_result`, not failures.

| Metric | Result |
| --- | ---: |
| Requests / pages | 22 / 22 |
| Logical completions | 22 |
| HTTP 404 / normal no-result books | 22 / 22 |
| Books with records / total records | 0 / 0 |
| Matching chapter records | 0 |
| TOCs / entries normalized | 0 / 0 |
| Books with chapter abstracts / nonblank abstract records | 0 / 0 |
| Failed / retries | 0 / 0 |
| Unique TOC gain | **0** |

This measures only Springer Meta API chapter metadata. It does not claim full-text, sample-chapter,
or textbook-prose coverage. Abstracts would also remain raw-only under the current normalizer.

## Combined and quota accounting

Running YES24 first and Springer second on the third independent copy made 22 requests to each
provider. Since YES24 added nothing, all 22 ISBN targets continued to Springer. The combined copy
remained byte-identical in its canonical data: 25 TOC books and 2,954 entries.

For conservative quota accounting, this task also counts the initial uninstrumented measurement,
the instrumented independent/combined repetition, and the final detail probe:

| Provider | Provider responses during this task | Response mix | Share of daily Basic allowance |
| --- | ---: | --- | ---: |
| YES24 | 110 | 1×200, 109×404 | 0.55% of 20,000 |
| Springer Meta | 88 | 88×404 | 17.6% of 500 |

There were no provider-response retries. Sixty-six local client attempts from an initial sandboxed
detail run failed before DNS resolution and reached no provider; they are recorded separately in
the JSON and excluded from quota consumption.

## Per-book outcome

`NP` means no YES24 product, `NT` means a product with no TOC, and `NR` is Springer's normal
no-result outcome. Every API-backed row has its exact content, detail, and Springer raw-artifact
paths in `book_results` in the JSON companion.

| ISBN / book ID | Canonical title | YES24 content | YES24 detail | Springer | Identity note |
| --- | --- | --- | --- | --- | --- |
| 9780023660450 | Elementary Linear Algebra | NP | NP | NR | — |
| 9780070394551 | Operating systems | NP | NP | NR | — |
| 9780070419209 | Operating systems | NP | NP | NR | — |
| 9780074630839 | Systems Programming and Operating Systems | NP | NP | NR | — |
| 9780126736502 | Linear algebra and its applications | NP | NP | NR | — |
| 9780131907294 | Linear algebra with applications | NP | NP | NR | — |
| 9780132819824 | Introductory Linear Algebra With Applications | NP | NP | NR | Solutions-manual ISBN |
| 9780135370193 | Linear algebra | NP | NP | NR | — |
| 9780136054276 | Differential Equations and Linear Algebra | NT | intro, no TOC | NR | ISBN is a Student Solutions Manual |
| 9780136374060 | Operating systems | NP | NP | NR | Canonical author identity conflict |
| 9780138493080 | Linear algebra with applications | NP | NP | NR | — |
| 9780201033922 | Introduction to linear algebra | NP | NP | NR | — |
| 9780201111859 | Operating systems | NP | NP | NR | — |
| 9780201119497 | Linear algebra | NP | NP | NR | — |
| 9780201509397 | An introduction to operating systems | NP | NP | NR | — |
| 9780201612516 | Operating systems | NP | NP | NR | — |
| 9780534074227 | Elementary linear algebra | NP | NP | NR | — |
| 9780534950934 | Understanding operating systems | NP | NP | NR | — |
| 9780716721772 | Linear algebra | NP | NP | NR | Solutions-manual/study-guide ISBN |
| 9781549660115 | Operating System | NP | NP | NR | Selection review still advisable |
| 9781565920606 | Learning the UNIX Operating System | NP | NP | NR | — |
| 9788131703045 | Operating systems | NP | NP | NR | — |
| `book_2bd8811d69c06b3696e2` | Applied linear algebra | skipped | skipped | skipped | No ISBN |
| `book_967599cb4ac88187f696` | Linear algebra | skipped | skipped | skipped | No ISBN |
| `book_09c91e7b456682eb19fb` | Linear algebra. | skipped | skipped | skipped | No ISBN |

## Remaining gap and recommendation

The 25 unresolved books divide into three mutually exclusive groups:

| Cause | Books |
| --- | ---: |
| Missing ISBN | 3 |
| Confirmed canonical selection/identity issue | 4 |
| Exact-edition public evidence/access gap | 18 |

Selection cleanup is the first priority because three selected ISBNs represent solutions manuals
and a fourth record has an author/edition identity conflict. After that, continue exact-edition
publisher/public-web acquisition and lawful sample/preface discovery for the 18 genuine evidence
gaps. A production YES24 detail-enrichment feature is not justified by this sample (zero actionable
textbook gains), and Springer Meta should not be placed high in the unresolved waterfall for this
corpus (zero records in 22 lookups).

## Code and reproducibility changes

The patch adds `SPRINGER_API_KEY=` to `.env.example`, updates the stale YES24 limit note, raises
Springer's throttle to 0.65 seconds, records non-secret request/status/retry telemetry, distinguishes
`no_product`, `no_toc`, and `no_result`, and exposes a bounded YES24 detail fetch used only by the
probe. It does not add canonical description enrichment or another discovery path.
