# Collector 두 가지 동작 방식: Discovery vs Enrichment

이 저장소의 provider/collector는 목적에 따라 완전히 다른 두 가지 방식 중 하나로 동작한다.
새 provider를 추가할 때 이 문서를 먼저 읽고 어느 방식에 해당하는지 정하고 시작한다.

## ① Discovery(발굴) 방식 — 표본(책 종류)을 늘린다

topic으로 provider를 검색해서, **아직 데이터셋에 없는 새 책을 찾아 추가**한다.

```bash
uv run data-pipeline collect --topic operating-systems --provider open-library --limit 25
uv run data-pipeline collect --topic linear-algebra --provider google-books --limit 25
```

- 입력: topic (`configs/topics.json`에 정의된 검색어/패턴)
- 동작: provider API를 topic 검색어로 호출 → 결과를 `Book`/`Document`/`TocEntry`/`Source`로 정규화 →
  기존 데이터셋에 병합 (같은 `book_id`가 이미 있으면 자연스럽게 중복 제거될 뿐,
  "이미 있으니 건너뛴다"가 목적이 아니다)
- 해당 provider: `open_library.py`, `google_books.py`, `internet_archive.py`
- 목적: **책의 종류(표본 수)를 늘리는 것**

## ② Enrichment(보강) 방식 — 이미 아는 책의 빠진 증거만 채운다

**이미 데이터셋에 있는 책**만 대상으로, 그 책에 빠진 증거(주로 TOC)가 있으면 정확히 그 책(ISBN/edition)에
한해 다른 소스로 채운다. 새 책은 추가하지 않는다.

```bash
uv run data-pipeline enrich-toc --data-dir data --max-sources 10
uv run data-pipeline enrich-bibliography --isbn 9780132017992
```

- 입력: 없음(데이터셋 전체를 훑어 TOC 없는 책을 찾음) 또는 정확한 ISBN 1개
- 동작: 대상 책의 ISBN/edition과 정확히 일치하는 소스(publisher allowlist, HathiTrust 등)를 찾아
  `Document`/`TocEntry`/`Source`만 추가. `Book` 자체는 이미 존재하므로 새로 안 만듦
- 해당 provider: `enrich_toc`(publisher/public-page allowlist 재사용), `hathitrust.py`(`enrich-bibliography` 전용)
- 목적: **이미 채택된 책의 증거 커버리지(TOC/서지)를 높이는 것**, 표본 수는 그대로

## 구분 기준 요약

| | ① Discovery | ② Enrichment |
| --- | --- | --- |
| 새 책 추가? | 함 | 안 함 |
| 입력 | topic | 기존 책의 정확한 ISBN |
| 표본 수 변화 | 늘어남 | 그대로 |
| exact-edition 검증 | provider별로 다름(일반 검색은 없음) | 항상 필수(안전 경계) |
| 예시 | Open Library, Google Books, Internet Archive | HathiTrust(`enrich-bibliography`), publisher/OER allowlist(`enrich-toc`) |

## YES24 / 국립중앙도서관은 어느 쪽인가

- **YES24**: ① Discovery 방식으로 구현한다. `itemList` 검색이 topic 기반 새 책 발굴에 적합하고,
  `originalTranslation`/`originalTitle` 필드로 번역서 여부까지 기록할 수 있다
  (번역서도 표본으로 인정하는 방침, [[data-pipeline-scope-non-english-editions]] 참고).
- **국립중앙도서관 (ISBN서지정보 API)**: 목차가 URL로만 제공되고 텍스트가 아니므로,
  당장은 ① Discovery보다 ② Enrichment(서지 corroboration, HathiTrust와 같은 패턴)로
  구현하는 편이 API 특성에 더 맞는다. YES24 작업 완료 후 별도로 결정한다.
