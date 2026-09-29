# Discovery-600 evidence availability — 2026-09-29

This independent pilot tests whether Scale-50 evidence coverage is primarily constrained
by acquisition capability or by freezing older/out-of-print targets before checking
evidence availability. It does not modify or merge into Scale-50. The companion
[machine-readable report](discovery-600-evidence-availability-2026-09-29.json) contains aggregate and per-book results without
raw descriptions or TOC text.

## Method and collection

The existing YES24 collector, topic configuration, ISBN handling, relevance checks, and
normalizer were used unchanged for six configured topics. Each successful search requested
at most 100 provider items and normalized at most 100 books. Topic outputs stayed isolated;
no result was merged into the current canonical Scale-50 dataset.

- Requested maximum: 6 topics × 100 = 600 books
- Raw provider items: 600
- Normalized topic rows / unique books: 471 / 471
- Existing-filter exclusions: 129
- Cross-topic duplicate rows: 0
- YES24 requests: 12 total (6×200, 6×400, 0 retries)

The first bounded run reused the generic `collect --limit 100` 4× oversampling plan, so
it sent `pageSize=400`; YES24 rejected all six topic requests with HTTP 400 and wrote no
raw responses. One fallback request per topic used `pageSize=100` and succeeded. Both sets
of calls are included above. No topic was called again after a successful raw response.

## Topic coverage

| Topic | Books | TOC | TOC% | Description | Desc% | Both | Both% |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Linear Algebra | 98 | 83 | 84.69% | 61 | 62.24% | 59 | 60.20% |
| Operating Systems | 54 | 49 | 90.74% | 35 | 64.81% | 35 | 64.81% |
| Algorithms | 70 | 69 | 98.57% | 64 | 91.43% | 64 | 91.43% |
| Databases | 93 | 90 | 96.77% | 76 | 81.72% | 76 | 81.72% |
| Discrete Mathematics | 92 | 84 | 91.30% | 59 | 64.13% | 57 | 61.96% |
| Probability/Statistics | 64 | 64 | 100.00% | 59 | 92.19% | 59 | 92.19% |
| **TOTAL (unique)** | 471 | 439 | 93.21% | 354 | 75.16% | 350 | 74.31% |

The six topic sets contained no duplicate book IDs, so topic rows and unique books are
both 471. Percentages use each topic's normalized candidate count as denominator.

## Publication-year coverage

| Publication year | Books | TOC | TOC% | Description | Desc% | Both | Both% |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| <= 2000 | 8 | 6 | 75.00% | 1 | 12.50% | 1 | 12.50% |
| 2001-2010 | 77 | 70 | 90.91% | 44 | 57.14% | 43 | 55.84% |
| 2011-2020 | 147 | 136 | 92.52% | 101 | 68.71% | 99 | 67.35% |
| 2021+ | 238 | 227 | 95.38% | 208 | 87.39% | 207 | 86.97% |
| unknown | 1 | 0 | 0.00% | 0 | 0.00% | 0 | 0.00% |

Evidence availability rises with recency in this observed pool. The 2021+ group has
95.38% TOC and 87.39% description coverage; the eight pre-2001 books have 75% TOC but
only 12.5% description coverage. These are descriptive rates, not causal or statistical
significance claims.

## Frozen Scale-50 comparison

These datasets are not interchangeable: Scale-50 is a frozen English-heavy benchmark
with reviewed public sources, while Discovery-600 is a current YES24 Korean-market
discovery pool. The comparison is descriptive only.

| Pool | Books | TOC | TOC% | Description | Desc% | Both | Both% |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Frozen Scale-50 | 50 | 25 | 50.00% | 25 | 50.00% | 20 | 40.00% |
| Discovery-600 | 471 | 439 | 93.21% | 354 | 75.16% | 350 | 74.31% |

Frozen Scale-50 has any prose for 26/50 books. YES24 discovery emits only description
documents in this path, so Discovery-600 any-prose coverage equals 354/471 descriptions.

Scale-50 has 32/50 books published by 2000 and only 1/50 from 2021 onward. Discovery-600
has 8/471 books published by 2000 and 238/471 from 2021 onward. The age mix is therefore
materially different, matching the experiment's target-selection hypothesis.

## Pool-quality caveat

Current title-based relevance rules admit meaningful topic noise: 57/64 probability/statistics books
are categorized by YES24 as high-school study books, and
25/70 algorithm books fall
outside the post-hoc university-textbook/IT/natural-science category set. This is an
observed distribution, not a new filter.

As a non-production sensitivity check, the 352 books in those three major-like provider
categories still show 325/352 TOC coverage (92.33%), 244/352 description coverage
(69.32%), and 243/352 both (69.03%). High coverage is therefore not explained solely by
the obvious school/general-interest category noise, although recommendation quality
still needs a separately reviewed gate.

Translation status is deliberately conservative: 27 books have a provider-supplied
original title and are marked translated; 444 remain unknown. Unknown is not treated as
non-translated.

## Interpretation

**Hypothesis A is better supported, with a pool-quality caveat.** Discovery-600 reaches
439/471 TOC books (93.21%) versus Scale-50's 25/50 (50%). All six topics exceed 84% TOC
coverage, recent books are best covered, and the major-like sensitivity set remains at
92.33%. Within this measured workflow, freezing older/less commercially visible targets
before testing evidence availability is a much larger bottleneck than the collector's
ability to obtain YES24 TOCs for currently discoverable books.

This does not prove that acquisition is solved. Description coverage is lower than TOC
coverage, pre-2001 prose is especially sparse, YES24 reflects a current Korean retail
catalog, and the current relevance rule is not a sufficient production quality policy.

## Recommendation

Keep **Scale-50** frozen as a longitudinal acquisition benchmark, including its known
age and identity limitations. Build the **production recommendation pool** separately:
require relevant metadata and a valid ISBN, then require either a usable TOC or strong
prose evidence, followed by a reviewed education-level/technical-book quality gate. Do
not silently replace hard benchmark books with easier ones, and do not apply the
post-hoc provider-category sensitivity set as production policy without review.

No selection policy, collector, normalizer, Scale-50 record, ML component, or other
repository was changed by this experiment.
