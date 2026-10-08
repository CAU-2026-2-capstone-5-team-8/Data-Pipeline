# Scale-50 public-evidence coverage — 2026-09-29

This run re-measures the relevance-gated Scale-50 selection at `main`
`569840bc1d1628d9debe81f832a81711650b0dd2`. It distinguishes table-of-contents
evidence from prose and counts a book once even when several sources support it. The companion
[machine-readable report](scale-50-public-evidence-coverage-2026-09-29.json) records every reviewed
target, source limitation, raw path, and reproducibility hash.

## Result

| Stage | Usable TOC books | TOC entries |
| --- | ---: | ---: |
| Historical 2026-09-22 report | 20/50 | — |
| Latest `main`, actually replayed (three later eCampus sources included) | 23/50 | 2,445 |
| Purdue Xinu second-edition TOC | +1 | +492 |
| Springer Greub second-edition TOC | +1 | +17 |
| **Final** | **25/50** | **2,954** |

The final topic split is Linear Algebra 11/25 and Operating Systems 14/25. Twenty-four books have
same-edition TOCs; *Modern Operating Systems* is the one explicitly labeled provider-native
same-Work alternate-edition TOC. The source view is 21 reviewed public-web books (eCampus 18,
Wiley 1, Purdue 1, Springer 1) plus four Open Library structured/dump books (three exact edition,
one same-Work alternate).

The 23/50 starting point is measured, not the unexecuted projection left in the earlier README.
The Springer Nature and YES24 API collectors are present on `main`, but `SPRINGER_API_KEY` and
`YES24_API_KEY` were both unset. This report therefore claims no speculative API gain.

## TOC and prose are separate

| Evidence | Rows | Books |
| --- | ---: | ---: |
| TOC | 2,954 entries | 25 |
| Description | 30 documents | 25 |
| Preface | 1 document | 1 |
| Introduction | 0 | 0 |
| Preview | 0 | 0 |
| Sample chapter | 0 | 0 |
| Other prose | 0 | 0 |
| Any prose document | 31 documents | 26 |
| No prose document | — | 24 |

TOC headings are not counted as prose. The only newly acquired prose is Comer's four-page preface;
the Xinu TOC and Springer chapter list emit no `Document` rows.

## Discovery method

All 27 books unresolved on the replayed latest-`main` baseline were checked by exact ISBN where
available, and by exact title + author + publication year for the four ISBN-less records. The
equivalent query set covered `table of contents`, `contents`, `preview`, `sample chapter`, and
`pdf`. Eighteen durable direct candidate URLs were recorded; search-visible candidates without a
stable/retrievable URL are still recorded by provider type and rejection reason. Candidate material
was then classified by edition identity, completeness, ordinary HTTP
availability, access restrictions, and whether it was a lawful public source. Search snippets
alone, hidden preview sections, unauthorized mirrors, and unlinked alternate editions were not
imported.

| Target | Best public candidate | HTTP | Exact-edition confidence | TOC / prose | Decision |
| --- | --- | --- | --- | --- | --- |
| Comer, *Operating System Design*, 2e, 9781498712439 | [official Purdue TOC](https://xinu.cs.purdue.edu/cont.html) and preface | 200 HTML / 200 PDF | High | Complete 492 / preface | **Accepted**: explicit second edition, official author/university site, platform markers, reviewed shape |
| Greub, *Linear Algebra*, 2e, 1963, no target ISBN | [official Springer page](https://link.springer.com/book/10.1007/978-3-662-01545-2) | Public 303 identity chain → 200 HTML | High | Complete 17 / none | **Accepted**: exact title, author, edition, year, DOI/eISBN, and shape |
| Deitel, *An Introduction to Operating Systems*, 9780201509397 | exact-ISBN limited preview | Yes | High identity | Partial / restricted | Reject: most sections hidden |
| Peek et al., *Learning the UNIX Operating System*, 9781565920606 | public O'Reilly contents | Yes | Low for target | Later-edition TOC / none | Reject: no provider-native target-edition relation |
| Easter Science/Kumar, *Operating System*, 9781549660115 | retailer metadata | Yes | Low | None / none | Reject: no trustworthy exact-edition evidence; selection review needed |
| Madnick/Donovan, *Operating Systems*, 9780070394551 | exact-edition limited preview | Yes | High identity | Partial / restricted | Reject: incomplete contents |
| Nutt, *Operating Systems*, 9780201612516 | exact-ISBN library-catalog TOC | No; timeout | High in indexed page | Full search-visible / none | Reject: could not preserve or test ordinary HTTP response |
| Tanenbaum/Woodhull, *Operating Systems*, 9780136374060 | exact-ISBN catalog/marketplace contents | Yes | Conflicting | Contents / none | Reject: exact edition is attributed to Tanenbaum alone; canonical author conflict |
| Stallings, *Operating Systems*, 9788131703045 | regional-edition retailer metadata | Yes | Medium | None / none | Reject: no complete exact Indian-edition TOC |
| Davis, *Operating Systems*, 9780201111859 | retailer/Open Library metadata | Yes | Conflicting prose | None / mismatched description | Reject: description names another edition |
| Milenkovic, *Operating Systems*, 9780070419209 | exact-ISBN retailer preview | Yes | High identity | None / unavailable | Reject: legitimate preview has no contents; unauthorized copies rejected |
| Dhamdhere, *Systems Programming and Operating Systems*, 9780074630839 | retailer/bibliographic metadata | Yes | Low | None / none | Reject: no high-confidence evidence source |
| Flynn/McHoes, *Understanding Operating Systems*, 9780534950934 | exact Open Library restricted preview | Metadata only | High identity | None / restricted | Reject: no complete public TOC or prose |
| Noble, *Applied Linear Algebra*, 1969, no ISBN | later-edition records | Yes | Low | Other edition / none | Reject: target identity cannot be proven |
| Edwards/Penney, *Differential Equations and Linear Algebra*, 9780136054276 | exact-ISBN record | Yes | Wrong target | Solutions manual / none | Reject: selection repair required |
| Kolman/Hill, *Elementary Linear Algebra*, 9780023660450 | metadata/restricted preview | Metadata only | High identity | None / restricted | Reject: no complete public evidence |
| Grossman, *Elementary Linear Algebra*, 9780534074227 | another-edition contents | Yes | Low | Other edition / none | Reject: no native Work relation |
| Johnson/Riess, *Introduction to Linear Algebra*, 9780201033922 | exact-ISBN limited preview | Yes | High identity | Partial / restricted | Reject: completeness unprovable |
| Kolman, *Introductory Linear Algebra With Applications*, 9780132819824 | exact-ISBN record | Yes | Wrong target | Solutions manual / none | Reject: selection repair required |
| Friedberg/Insel/Spence, *Linear Algebra*, 9780135370193 | restricted exact preview; public fifth edition | Exact restricted; alternate public | Low for usable source | Later-edition TOC / restricted | Reject: target first edition incomplete |
| Curtis, *Linear Algebra*, 1963, no ISBN | later publisher edition | Yes | Low | Other edition / none | Reject: exact target identity cannot be proven |
| Fraleigh/Beauregard, *Linear Algebra*, 9780201119497 | exact Open Library restricted preview | Metadata only | High identity | None / restricted | Reject: no complete public TOC |
| Jacob, *Linear Algebra*, 9780716721772 | exact-ISBN record | Yes | Wrong target | Solutions manual / none | Reject: main-book TOC would be false evidence |
| Strang, *Linear Algebra and Its Applications*, 9780126736502 | restricted exact preview; public publisher 2e | Exact restricted; alternate public | Low for usable source | Later-edition TOC / restricted | Reject: publisher TOC is another edition |
| Leon, *Linear Algebra with Applications*, 9780138493080 | restricted exact record; later-edition contents | Exact restricted; alternate public | Low for usable source | Later-edition TOC / restricted | Reject: no complete exact-edition TOC |
| Bretscher, *Linear Algebra with Applications*, 9780131907294 | search-visible catalog; eCampus digital SKU | Catalog blocked; SKU public | Conflicting | Search-visible TOC / none | Reject: no retrievable exact edition; eCampus is a different SKU |
| Lang, *Linear Algebra*, 1966, no ISBN | later Springer/PDF editions | Yes | Low | Other edition / none | Reject: no exact-edition identifier |

Final unresolved coverage is 25/50. Four selected records have no ISBN (Greub, Noble, Curtis,
Lang); Greub could be matched safely from the official publisher's title/author/edition/year/DOI
combination, but its canonical author typo (`Hildbert` vs `H. Greub`) still warrants correction.
Three ISBN selections identify solution manuals rather than the named textbook
(`9780136054276`, `9780132819824`, `9780716721772`). Tanenbaum/Woodhull is another explicit
identity conflict. These are selection repairs, not reasons to weaken source matching.

## Implemented evidence and fail-closed behavior

`purdue-xinu-os-design2` accepts only the official page headed “Table of Contents For Xinu 2nd
Edition”, its reviewed Galileo/BeagleBone markers, 31 roots, 492 entries, chapter/appendix sequence,
and complete child/descendant counts. The page itself has no ISBN, so provenance records no claimed
source ISBN and names the reviewed 2015 second-edition source identity. A separate official-site
collector emits the four-page preface only when the official link, page count, and text markers
match.

`springer-greub-linear-algebra2` requires the official Springer page's visible and JSON-LD title,
Werner H. Greub author identity, `2nd edition`, 1963 copyright, DOI/eISBN, 17-entry root sequence,
page ranges, canonical chapter links, and complete labels 1–15. Springer currently uses an identity
redirect; collection follows the server-provided public chain at most five times, only over HTTPS,
and only within the explicitly reviewed `springer.com` host boundary. It does not fabricate,
extract, or replay tokens/cookies. Other sources still reject redirects. Neither accepted page carries
a reuse license; only the publicly displayed metadata/TOC is normalized, and restricted chapter
PDFs are not fetched.

Tests cover successful normalization and rejection of wrong title, author, ISBN/eISBN, edition,
year, missing markers, truncated entries, malformed hierarchy, missing page ranges, hostile
redirects, unexpected content types, empty responses, wrong PDF page count, and wrong preface text.

## Raw evidence and offline reproduction

The six new ignored raw artifacts are listed in the JSON report: three latest-`main` eCampus
snapshots, the Xinu TOC, the Xinu preface, and the Springer page. They remain under
`data/experiments/scale-50-public-evidence-20260929/raw/` and are not committed.

The canonical dataset was independently rebuilt twice from the two preserved Scale-50 Open
Library artifacts plus the experiment raw artifacts, using `--relevance-gate topic-evidence-v1`,
then enriched offline from the pinned 2026-08-31 target index. Both builds were byte-identical:

| File | SHA-256 |
| --- | --- |
| `books.jsonl` | `9ada88e82d80936520d103aa55e291927ad5aeb85bf6ac4dca26384b020dd127` |
| `documents.jsonl` | `014586a6893f8cc2bbee6bdc99cd567f900d25190cf28eed008a59f640627dc0` |
| `toc.jsonl` | `2d7ea2f05a0523c50966be94874353ca7e9993cfe8658c1a736b009ceec73028` |
| `sources.jsonl` | `686112dcc33854eae7a69c7c8dc673953e71ed1523e044de6c605a1f4311917a` |

The lower-level `build` command now accepts the already-defined `topic-evidence-v1` gate so these
preserved Scale-50 API artifacts can be replayed directly. Omitting the option preserves previous
behavior. No ML schema, score, or recommendation code changed.

The unchanged `book-evidence-v1` exporter was also run against the final offline rebuild. It
emitted 50 valid records, 25 with TOC evidence and 25 metadata-fallback-only, with zero validation
errors. Greub contributes 17 `toc_public_web_exact` rows; Xinu contributes 492 such rows plus one
`document` row typed `preface`. This verifies propagation inside Data-Pipeline only—no concept
matching, difficulty scoring, or ranking was run.
