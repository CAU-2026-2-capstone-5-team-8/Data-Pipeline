# Scale-50 TOC acquisition result — 2026-09-22

This benchmark measures unique additional coverage. Provider hits are never added together when
they refer to the same book.

| Stage | Unique usable TOC |
| --- | ---: |
| Existing exact-edition baseline | 14/50 |
| Open Library same-Work alternate | +1 |
| LOC MARC 505 | +0 |
| Other structured sources | +0 |
| Coverage after mixed baseline + structured additions | 15/50 |
| Reviewed public-web enrichment | +5 |
| **Final usable TOC** | **20/50** |

The existing 14-book baseline is deliberately retained for the before/after benchmark, but it
already contains ten reviewed public/publisher pages. For the independent architecture comparison,
the structured/API-only path resolves 6/50 (four original canonical TOCs plus two usable bulk
same-Work resolutions), while structured sources plus reviewed public-web evidence resolve 20/50.

All remaining 30 books have at least canonical title/author bibliographic metadata, so metadata
fallback makes 50/50 analyzable for coarse concept evidence. This does not turn inferred metadata
into TOC evidence: 30/50 remain TOC-unresolved.

The local Open Library projection used the official 2026-08-31 Edition dump. It took 106.076
seconds to build and occupied 327,680 bytes. Three exact-edition TOCs were found but overlapped the
baseline. One same-Work alternate (*Modern Operating Systems*) was new. Similar titles without a
target-ISBN Edition -> Work link were rejected, as were solution manuals, workbooks, different
volumes, and public-web alternate editions lacking an authoritative relation.

LOC SRU returned one usable MARC 505 that overlapped the baseline and six MARC 856 link candidates;
none of the six was publicly retrievable by ordinary HTTP in this environment. The old 2016 LOC
bulk distribution therefore did not justify a multi-file download or importer.

Public-web discovery recorded 11 candidates. Five exact-edition eCampus pages passed ISBN, title,
edition, and TOC-structure checks. Two exact-book pages (Xinu 2e and Bretscher) were visible through
normal search discovery but returned HTTP 403 to direct retrieval, making them the measured human
search gap. Four accessible or indexed later-edition pages were retained as rejected candidates,
not silently attached to older targets.

The corresponding per-book machine-readable report is
[`scale-50-toc-acquisition-2026-09-22.json`](scale-50-toc-acquisition-2026-09-22.json).
