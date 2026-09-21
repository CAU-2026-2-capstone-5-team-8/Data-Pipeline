# Data-Pipeline 폴더 작동 방식

CAU 캡스톤 8조 도서 추천 프로젝트의 **데이터 수집·정규화 파이프라인**이다. 공개 소스에서
책 메타데이터와 텍스트 근거(목차, 서문, 서론, 미리보기 등)를 수집해 provider-독립적인
canonical 데이터셋으로 만들어 `ML` 저장소에 넘겨주는 역할만 담당한다.

이 저장소는 추천 로직, 개념 추출, 난이도 산정, ML 추론을 절대 수행하지 않는다
(`AGENTS.md` 21절 Non-Goals). 그 책임은 전부 `ML` 저장소에 있다.

## 1. 핵심 설계 원칙

- **증거 우선, 추론은 나중에**: 원본 응답(raw)과 정규화 결과(processed)를 분리 보관하고,
  provenance(출처)를 절대 파괴하지 않는다.
- **결측은 정상 데이터**: 모든 책이 서문·미리보기를 가질 필요는 없다. 없으면 `false`/누락으로
  명시하고, 절대 지어내지 않는다.
- **출처는 필수 추적 정보**: provider, URL, 조회 시각, 라이선스, content hash를 최대한 보존한다.
- **소규모 검증 우선**: 처음부터 대량 수집을 하지 않고 10권(주제별 5권)으로 파이프라인
  전체를 검증한 뒤 50권 규모로 확장한다.

## 2. 전체 파이프라인 흐름

```text
External Sources (공개 API, 출판사/저자 페이지, OER, 공개 HTML)
        ↓
Collectors (provider별 어댑터)
        ↓
Raw Responses (data/raw/, 불변·타임스탬프·해시 기반 저장)
        ↓
Parsing / Normalization
        ↓
Validation / Deduplication
        ↓
Canonical Dataset (data/processed/*.jsonl)
        ↓
ML 저장소로 전달
```

## 3. 디렉터리 구조

```text
Data-Pipeline/
├── AGENTS.md                      # 저장소 설계 원칙·마일스톤 상세 (권위 있는 사양서)
├── README.md                      # 실행 방법, 실제 수집 결과 로그
├── docs/
│   ├── data-pipeline-guide.md     # 이 문서
│   └── expansion-roadmap.md       # topic/source config 리팩터링 배경과 진행 상태
├── .github/workflows/checks.yml   # push/PR마다 pytest + ruff 자동 실행하는 CI
├── configs/
│   ├── mvp.json                   # 10권 골든 데이터셋 매니페스트(고정 raw 아티팩트 + 최종 book_id)
│   ├── topics.json                # topic별 domain·provider 검색어·relevance 정규식(1곳에서 관리)
│   ├── sources/                   # allowlist 데이터. 책 1권 = 파일 1개, 코드 변경 없이 추가 가능
│   │   ├── publisher/<slug>.json
│   │   ├── publisher-document/<slug>.json
│   │   ├── public-book-page/<slug>.json
│   │   └── open-textbook/<slug>.json
│   └── experiments/
│       ├── scale-50.json          # 50권 규모 파일럿 매니페스트
│       └── scale-50-v2.json       # 주제 관련성 게이트를 적용한 실험 매니페스트
├── src/data_pipeline/
│   ├── cli.py                     # Typer 기반 CLI 진입점
│   ├── collectors/                # provider별 수집기
│   │   ├── base.py
│   │   ├── open_library.py        # 기본 메타데이터 API
│   │   ├── google_books.py        # 페이지네이션 지원 대체 메타데이터 API
│   │   ├── publisher_pages.py     # Wiley 등 출판사 정체성/목차 페이지
│   │   ├── publisher_documents.py # 출판사 PDF(샘플 챕터 등) 수집
│   │   ├── public_book_pages.py   # eCampus 등 서점 카탈로그 HTML
│   │   └── open_textbooks.py      # OSTEP, Hefferon 등 오픈 교재
│   ├── topics.py                  # configs/topics.json 로더 — topic 관련 상수의 유일한 출처
│   ├── source_registry.py         # configs/sources/*.json 로더(범용, 타입 힌트 기반 변환)
│   ├── open_textbook_sources.py   # 오픈 교재 allowlist dataclass 정의 + 로드
│   ├── publisher_sources.py       # 출판사 페이지 allowlist dataclass 정의 + 로드
│   ├── publisher_document_sources.py
│   ├── public_book_sources.py
│   ├── models.py                  # canonical 스키마 (Book/Document/TocEntry/Source)
│   ├── normalizers.py             # provider 응답 → canonical 변환
│   ├── identifiers.py             # ISBN 검증, book_id/결정적 fallback ID 생성
│   ├── validation.py              # 교차 참조·중복·무결성 검증
│   ├── storage.py                 # raw/processed 파일 입출력
│   ├── manifest.py                # mvp.json/experiments 매니페스트 빌드
│   ├── reporting.py                # 커버리지 리포트(report)
│   ├── scale_comparison.py        # v1/v2 실험 비교(compare-scale)
│   ├── scale_reporting.py         # 대규모 실험 리포트(report-scale)
│   ├── relevance.py               # 주제 관련성 게이트(topic-evidence-v1)
│   ├── relevance_review.py        # v1/v2 relevance 사람 검수 워크플로
│   └── diagnostics.py
└── tests/                          # provider 응답 fixture 기반 결정적 테스트
```

`open_textbook_sources.py` 등 4개 allowlist 모듈은 더 이상 데이터를 직접 담지 않는다 —
dataclass 정의와 `<kind>_source(slug)` 조회 함수만 갖고 있고, 실제 데이터는
`configs/sources/<kind>/<slug>.json`에서 `source_registry.load_registry_dir()`로
로드한다. 새 책 하나를 allowlist에 추가하는 건 이제 코드 변경이 아니라 JSON 파일
추가다. 자세한 배경은 `docs/expansion-roadmap.md` 참고.

## 4. Canonical 데이터 모델 (핵심 산출물)

`data/processed/` 아래 4개의 JSONL 파일을 생성한다. 이 스키마가 `ML` 저장소와의 **유일한 계약**이다.

| 파일 | 내용 | 핵심 필드 |
| --- | --- | --- |
| `books.jsonl` | 정규화된 서지 정보 | `book_id`(isbn13/isbn10/결정적 fallback), ISBN, 제목, 저자, 출판사, 연도, 언어, `topics` |
| `documents.jsonl` | 텍스트 근거 | `document_id`, `book_id`, `document_type`(description/preface/introduction/preview/sample_chapter/index/other 등), `text`, `source_id`, `content_hash` |
| `toc.jsonl` | 계층형 목차 | `toc_entry_id`, `book_id`, `parent_entry_id`, `level`, `order_index`(정수, 부동소수점 금지), `title`, `source_id` |
| `sources.jsonl` | 출처/provenance | `source_id`, `book_id`, `provider`, `source_type`, `url`, `retrieved_at`, `license`, `rights_note`, `content_hash` |

- `book_id`는 ISBN-13 우선, 없으면 ISBN-10, 그것도 없으면 결정적 fallback ID를 사용한다.
- 라이선스 정보는 확인되지 않으면 절대 지어내지 않고 `null`로 둔다.
- TOC 계층은 절대 평탄화하지 않는다.

## 5. 수집기(Collector) 종류와 우선순위

소스 우선순위는 `AGENTS.md` 4절 기준으로: **공식/공개 API → 출판사·저자 공식 페이지 → 오픈
교육자료(OER) → 일반 공개 HTML → 브라우저 자동화(최후 수단, 현재 미사용)**.

- **Open Library** (`--provider open-library`, 기본값): 무인증 검색/편집본/작품 API.
- **Google Books** (`--provider google-books`): 40건 제한을 넘는 검색은 `startIndex` 페이지로
  분할 수집. 일부 페이지 실패 시 부분 결과를 발행하지 않고 전체 실패 처리.
- **출판사 페이지/문서** (`collect-publisher`, `collect-publisher-document`): Wiley 등 소수
  출판사에 대해 ISBN·edition·목차 제목·PDF 시그니처까지 검증하는 소규모 버전관리
  allowlist 기반. 새 URL은 CLI로 임의 지정 불가하며 반드시 allowlist에 추가해야 한다.
- **공개 서점 카탈로그** (`collect-public-page`): eCampus 등, `source_type: other`로 명시.
- **오픈 교재** (`collect-open-textbook`): OSTEP, Hefferon, Understanding Linear Algebra,
  Nicholson, Think OS, Hailperin, xv6 등. 저자/버전/ISBN/목차 구조/텍스트 마커까지 검증하며,
  소스별 파일 크기 상한이 다르게 설정되어 있다(예: Hefferon PDF 10 MiB, xv6 PDF 2 MiB).

모든 allowlist 기반 수집기는 **exact-edition 검증**(제목, 저자, 버전, ISBN, 목차 구조 일치)을
통과해야만 canonical 데이터를 발행하며, 실패 시 조용히 넘어가지 않고 명시적으로 실패한다.

## 6. 원본(raw) 데이터 보존 방식

```text
data/raw/<provider>/<topic>/<timestamp>_<hash>.json   # 불변, 재현 가능한 오프라인 재빌드용
data/processed/*.jsonl                                 # canonical 산출물
data/experiments/...                                   # 스케일 파일럿 raw/processed
```

- 동일 raw 아티팩트로 다시 `build`하면 항상 byte-identical 결과가 나와야 한다(재현성 검증됨).
- `data/raw`, `data/processed`는 Git에서 제외된다. 커밋되는 것은 `tests/fixtures/`의
  소규모 합성/공개 fixture뿐이다.

## 7. 주요 CLI 명령어 (`uv run data-pipeline ...`)

| 명령어 | 역할 |
| --- | --- |
| `search --topic <topic> --limit N` | 메타데이터 검색만 수행(수집 없이 확인용) |
| `collect --topic <topic> --limit N [--provider ...] [--detail-limit N]` | 메타데이터 API로 수집 및 raw 저장. `--detail-limit`으로 Open Library 상세 조회 개수를 직접 조절 가능 |
| `collect-publisher --source <slug>` | 출판사 정체성/목차 페이지 수집 (allowlist) |
| `collect-publisher-document --source <slug>` | 출판사 PDF(샘플 챕터 등) 수집 (allowlist) |
| `collect-public-page --source <slug>` | 서점 카탈로그 HTML 수집 (allowlist) |
| `collect-open-textbook --source <slug>` | 오픈 교재 수집 (allowlist) |
| `enrich-toc --data-dir <dir> [--dry-run]` | 기존 canonical dataset에서 TOC가 없는 책만, 이미 검토된 publisher/public-page allowlist 소스로 채움 |
| `build --raw <artifact> [--raw ...]` | 지정한 raw 아티팩트들로 오프라인 canonical 재빌드 |
| `build-manifest --manifest <json> --data-dir <dir>` | 매니페스트가 가리키는 최신 raw로 canonical 빌드, 최종 book_id 집합 검증 |
| `report` | 4개 canonical 파일 기준 커버리지 리포트(주제/책 단위) |
| `report-scale --manifest <json> --data-dir <dir>` | 대규모 실험 리포트(JSON+CSV, discovery/dedup/coverage 등) |
| `compare-scale --v1-report ... --v2-report ...` | 두 스케일 실험 결과 비교(주제 관련성 게이트 등) |
| `prepare-relevance-review --v1-report ... --v2-report ... --output <csv>` | v1/v2 relevance 판정을 사람이 한 번에 검수할 수 있는 통합 review 파일 생성 |
| `finalize-relevance-review --review <csv> --v1-output ... --v2-output ...` | 완료된 사람 검수 결과를 `compare-scale` 입력용 v1/v2 audit로 분리 |

## 8. 검증(Validation) 규칙

`AGENTS.md` 18절 기준 최소 검증 항목:

- `book_id` 유효성, 제목 비어있지 않음, 가능하면 저자 최소 1명
- 언어 표기 유효성, source 참조 유효성, book/source 관계 유효성
- 결정적 ID 생성, ISBN 중복 검출, source 중복 검출
- 빈 문서 텍스트 금지, 깨진 TOC parent 관계 금지
- TOC 레벨 정합성(자식 레벨 = 부모 레벨 + 1, 루트는 레벨 1)과 부모 참조 순환(cycle) 탐지

검증 오류는 절대 조용히 버려지지 않고 명시적으로 드러난다.

## 9. 현재 진행 단계

1. **1차 마일스톤(완료)**: OS 5권 + 선형대수 5권, 총 10권 골든 데이터셋(`configs/mvp.json`).
   현재 10권, 31개 문서, 1,163개 TOC 엔트리, 52개 source 레코드.
2. **2차 마일스톤 — Scale Pilot(완료)**: `configs/experiments/scale-50.json`으로 주제당 25권,
   총 50권 규모 파일럿. Open Library 단일 소스로는 TOC/본문 커버리지가 낮고, 제목만으로는
   주제 무관 후보(예: *Robot Operating System*)가 섞이는 문제를 확인.
3. **Scale Pilot v2 — 관련성 게이트(완료)**: `scale-50-v2.json`에서 주제 관련성 검사
   (`topic-evidence-v1`)를 옵션으로 추가해 경쟁 주제 후보를 제거. `prepare-relevance-review`/
   `finalize-relevance-review`로 v1/v2를 한 번에 사람이 검수하는 워크플로까지 완료.
4. **topic/allowlist 데이터화(완료, 이 문서의 3절 참고)**: topic 상수를
   `configs/topics.json` 한 곳으로, allowlist를 `configs/sources/`로 이동. 새 topic이나
   새 curated 책을 추가할 때 더 이상 여러 파일의 코드를 고칠 필요가 없다.
5. **다음: 신규 topic 4개(자료구조/알고리즘, 데이터베이스, 이산수학, 확률과 통계) 및
   신규 provider(Internet Archive, HathiTrust) 추가** — 진행 상태는
   `docs/expansion-roadmap.md` 참고.

## 10. 하지 않는 것 (Non-Goals)

리더 프로필 계산, 개념 숙련도 추정, 필요 개념 추론, 학습목표 매칭, 추천 랭킹/스코어링,
어휘·구문 난이도 산정, LLM 문항 생성, 사용자 평가, Spring Boot 연동, 프로덕션 DB 설계,
OCR, 모바일 기능 — 이 모든 것은 `ML` 저장소(또는 그 이후 Backend)의 책임이다.
