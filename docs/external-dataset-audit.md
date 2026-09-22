# External bibliographic dataset audit

Audit date: 2026-09-21

This audit separates datasets that can resolve a photographed commercial book from corpora that
are useful only for later concept-model research. Scale-50 remains a benchmark; it is not used as
the external database itself.

## Decision summary

| Source | Kind | Decision | Current release / date | Compressed size | ISBN | Work/Edition | TOC | Subjects / description | Why |
| --- | --- | --- | --- | ---: | --- | --- | --- | --- | --- |
| Open Library Editions + Works | bibliographic resolution | `adopt` | 2026-08-31 monthly dump | 12.59 GB + 4.06 GB | yes, edition | provider-native | edition `table_of_contents` | work and edition fields | Best current bulk base; exact ISBN and same-work fallback are both possible. |
| Library of Congress MDSConnect Books All | bibliographic fallback | `reject_for_now` for full import | unabridged 2016 retrospective | not stated on the official landing page; 43 MARCXML parts | MARC 020 when present | MARC manifestation record, not an OL-style Work graph | MARC 505; 856 is only a link candidate | MARC subjects and notes | Free bulk is old, while current records require a subscription. Scale-50 SRU testing added no unique usable TOC. Keep targeted SRU feasibility only. |
| OAPEN / DOAB | OA bibliographic corpus | `experiment_only` | continuously updated feeds | provider does not publish one stable aggregate size | often | no commercial-edition Work graph comparable to OL | not a guaranteed metadata field; public full text may expose it | rich OA metadata | Excellent OA corpus but weak direct coverage of arbitrary commercial shelf editions. |
| Open Textbook Library / OpenStax | concept/textbook corpus | `experiment_only` | continuously updated APIs/catalogs | small API/catalog feeds | sometimes | source-specific | frequently available in public book pages | yes | Useful for concept extraction and regression fixtures, not the primary commercial ISBN resolver. |
| Hugging Face textbook corpora | concept corpus | `reject_for_now` | dataset-specific | dataset-specific | generally absent or unreliable | no | generated/derived outlines | varies | Often synthetic or training-oriented; does not solve commercial ISBN/edition provenance. |

## Open Library

Official documentation says the dumps are generated monthly. Most files are gzip-compressed TSV
with five columns: record type, key, revision, last-modified timestamp, and the complete JSON
record. The official page documents compressed-stream querying with `rg -z`/`zgrep`, and also gives
a DuckDB example; a fully decompressed duplicate is unnecessary.

The pinned 2026-08-31 Archive.org item reports:

| File | Bytes | MD5 | SHA-1 |
| --- | ---: | --- | --- |
| `ol_dump_editions_2026-08-31.txt.gz` | 12,586,485,055 | `da4de1cca148aa85bea0707a63ffa212` | `e09e00630797598aab877ec542596b1b58f6b87c` |
| `ol_dump_works_2026-08-31.txt.gz` | 4,058,336,593 | `eda3a83f9dbc85a4d8f7cde838f070b5` | `c9362f345368cdc8bf64efcc05d6e4b590974cb6` |

The committed source manifest also records the local retrieval timestamp, gzip-TSV/JSON source
format, and parser version. The generated SQLite index embeds the complete manifest alongside its
scope and target ISBN list.

Edition records carry edition keys, ISBN arrays, title/subtitle, author references, publishers,
publish date, language references, Work references, source records, and sometimes
`table_of_contents`. Work records carry Work keys, title, author references, subjects, and an
optional description. The relationship direction needed by this project is Edition -> Work; a
local index supplies the reverse Work -> Editions lookup.

Open Library describes its API as suitable for infrequent real-time requests and its dumps as the
appropriate interface for bulk import. Internet Archive states that it asserts no new copyright
or proprietary rights over Open Library database material, while warning that individual
contributions can still have underlying rights. The pipeline therefore records the source and does
not infer a license for extracted book metadata or TOCs.

Official references:

- https://openlibrary.org/developers/dumps
- https://docs.openlibrary.org/developers/misc/searching-data-dumps.html
- https://openlibrary.org/developers
- https://openlibrary.org/dev/docs/api/books
- https://openlibrary.org/developers/licensing
- https://archive.org/metadata/ol_dump_2026-08-31

## Library of Congress

The free MDSConnect release is not a current rolling catalog dump. The official distribution page
describes it as nearly 25 million records from the unabridged **2016 retrospective** set, available
as UTF-8 MARC and MARCXML. The Books All page exposes 43 XML parts. Current-year MARC distribution
is a paid subscription product.

MARC 505 is a formatted contents note and can directly support TOC evidence after structural
validation. MARC 856 is electronic location/access metadata: even a value labelled “Table of
contents” is only a candidate until the public URL is reachable, confirmed as the target book, and
successfully extracted.

The current LC SRU endpoint supports `bath.isbn` and MARCXML. It is therefore a lower-storage,
targeted fallback for unresolved ISBNs. In the 2026-09-21 Scale-50 feasibility run it produced one
usable 505 already covered by the baseline, six 856 candidates, and zero reachable/confirmed 856
TOCs. Its unique gain was zero, so downloading the old full dump is not justified now.

Official references:

- https://www.loc.gov/cds/products/marcDist.php
- https://www.loc.gov/cds/products/MDSConnect-books_all.html
- https://www.loc.gov/standards/z3950/lcserver.html
- https://www.loc.gov/marc/bibliographic/bd505.html
- https://www.loc.gov/marc/856guide.html

## Other sources

OAPEN and DOAB publish free metadata feeds (MARCXML, ONIX, JSON/CSV and OAI-PMH); their metadata is
CC0. They cover open-access scholarly books, not arbitrary commercial textbook editions, so they
belong in a later OA/concept-corpus experiment rather than the first ISBN resolver.

Official references:

- https://www.oapen.org/article/metadata
- https://www.oapen.org/article/8185269-search-using-a-rest-api
- https://www.doabooks.org/en/researchers/full-faq

## Storage and workflow feasibility

At completion the repository filesystem had about 15 GB free. Only the 12.59 GB Edition dump was
downloaded after explicit approval; the 4.06 GB Work dump was not needed for the target projection.
No decompressed duplicate was created. Downloading both dumps now would leave an unsafe working
margin, so the Works dump remains deferred.

The proposed implementation avoids a decompressed copy:

1. Keep the pinned `.txt.gz` files under ignored `data/external/open_library/`.
2. Stream the Edition TSV from gzip and project only resolver fields.
3. Build an ignored SQLite index under `data/indexes/open_library/`.
4. Index ISBN -> Edition and Work -> Editions; retain TOC JSON only when present.
5. Resolve benchmark ISBNs from the index and emit ordinary canonical records. ML never reads the
   SQLite schema.

SQLite is preferred for the prototype because it is in the Python standard library, supports the
required point/range lookups, produces one portable file, and adds no server or heavy dependency.
DuckDB remains a valid ad-hoc inspection tool, but its dependency is not needed for these indexed
lookups. The index builder must use tiny fixtures in normal tests; large-dump integration remains
explicitly opt-in.

## Measured Scale-50 result

The pinned Edition dump was scanned twice in 106.076 seconds. The resulting 327,680-byte SQLite
projection contains 394 editions, 504 ISBN mappings, 51 Work keys, and 10 TOC-bearing editions.
Of 92 target ISBN-10/ISBN-13 identifiers, 66 appeared in the dump.

The bulk data found three usable exact-edition TOCs, all already present in the 14-book reviewed
baseline. Provider-native ISBN -> Edition -> Work traversal added one unique alternate-edition TOC,
raising coverage after the mixed reviewed baseline to 15/50. That baseline already includes ten
reviewed public/publisher pages, so it is not an API-only measure. Independently, the original four
canonical structured TOCs plus both usable bulk alternate resolutions yield 6/50 for the
structured/API-only path. The earlier title-search API proxy had suggested three unique gains; two
were correctly rejected once the dump showed no exact target-ISBN Edition from which to establish
a provider-native Work relation.

LOC was evaluated through the current SRU catalog rather than its 2016 bulk snapshot. It returned
32 exact records, one usable MARC 505 already covered by the baseline, and six MARC 856 candidates.
All six 856 URLs returned HTTP 403 to ordinary retrieval, so LOC added zero unique usable TOCs and
a production LOC bulk importer remains deferred.

Reviewed public-web discovery recorded 11 candidate pages. Five exact-edition eCampus pages were
reachable, passed ISBN/title/edition and chapter-structure validation, and added five unique books.
Two exact-book pages were discoverable by a human/search index but returned HTTP 403 to the
pipeline; four other pages exposed later-edition TOCs without a provider-native Work relation and
were conservatively rejected. Final usable TOC coverage is 20/50. The other 30 books retain
explicit metadata fallback, so total concept-evidence coverage is 50/50 while TOC coverage remains
20/50. See `docs/experiments/scale-50-toc-acquisition-2026-09-22.json` for per-book facts.
