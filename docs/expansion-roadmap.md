# 확장 로드맵: topic/allowlist 데이터화 + 신규 provider (로컬 DB는 드롭됨)

이 문서는 Data-Pipeline을 인수받은 뒤 진행 중인 확장 작업의 배경, 현재 상태, 남은 작업을
기록한다. 이 저장소를 다시 열어보는 사람(나 자신을 포함한 어떤 AI 세션이든, 팀원이든)이
`git log`/`git status`만으로는 알 수 없는 **왜 이 구조로 가고 있는지**와 **다음에 뭘 해야
하는지**를 여기서 확인할 수 있어야 한다.

이 문서는 계획 문서이며, 실제 구현 결정을 내리는 권위 있는 사양은 여전히 `AGENTS.md`다.
둘이 충돌하면 `AGENTS.md`가 우선한다.

## 배경

서정민님으로부터 Data-Pipeline 유지보수를 인수받으면서 전체 코드베이스(약 7,500줄)를
검토했다. 가장 큰 구조적 문제는 **"책 1권 추가 = 코드 몇 줄 하드코딩"** 패턴이
collector allowlist(`open_textbook_sources.py` 668줄 등)뿐 아니라 **topic 자체**에도
퍼져 있었다는 점이다: `normalizers.TOPICS`, `relevance.py`의 정규식 2곳,
`open_library.TOPIC_TITLES`, `google_books`의 subject 쿼리맵, `manifest.py`의
`Literal[...]` 등 최소 7곳에 topic 문자열이 중복 정의되어 있었다.

이 상태로 신규 topic 4개(자료구조/알고리즘, 데이터베이스, 이산수학, 확률과 통계)를
추가하면 28곳 이상을 손으로 맞춰야 한다.

### 하고자 하는 것 (사용자 요청 원문 기준)

1. ~~책 데이터를 하드코딩 대신 DB에 저장해서 조회/탐색을 더 쉽게 한다.~~ → **드롭됨**,
   아래 "Phase 1 드롭 결정" 참고.
2. **다른 API를 추가**해서라도 더 많은 책 데이터를 기존과 동일한 형식
   (title/TOC/description/preface 등)으로 확보한다.
3. **새로운 topic 4개** 추가: 자료구조/알고리즘, 데이터베이스(CS) / 이산수학,
   확률과 통계(수학).

### 설계 제약 (AGENTS.md와의 정합성)

- `models.py`의 `Book`/`Document`/`TocEntry`/`Source` 캐노니컬 스키마는 바꾸지 않는다.
  새 provider·새 topic 모두 기존 스키마로 정규화되어야 한다.
- AGENTS.md는 "PostgreSQL 같은 서비스 DB는 Backend가 소유한다"고 명시한다. 이
  원칙은 애초에 Data-Pipeline이 서비스 DB에 관여하지 않는다는 뜻이었고, 로컬 조회용
  SQLite(Phase 1)를 둘러싼 논의 끝에 **그 로컬 DB 자체도 만들지 않기로 결정했다**
  (아래 "Phase 1 드롭 결정" 참고). 이 저장소는 canonical JSONL만 만든다.
- allowlist(publisher/public-page/open-textbook/publisher-document)는 **내용은 그대로
  두고 저장 위치만** Python 코드 → 버전관리되는 config 파일로 옮긴다. "작고
  버전관리되는 allowlist"라는 AGENTS.md 원칙은 유지한다(SQLite처럼 git-diff 불가능한
  바이너리로 옮기지 않는다).
- 서정민님이 인수인계 문서에 남긴 "generic evidence discovery"(링크 그래프 크롤러로
  미지의 URL을 발견하는 대규모 작업)는 **이 로드맵에 포함하지 않는다** — 별도의 더 큰
  작업이며, 지금은 기존 curated/API 패턴을 확장하는 데 집중한다.

## Phase 1(로컬 SQLite) 드롭 결정 — 해결됨, 재논의 불필요

원래 "SQLite를 로컬 조회용(Option A)으로 할지, Backend와 같은 서비스 Postgres에
직접 적재(Option B)할지"를 미해결 사항으로 남겨뒀었다. 이후 대화에서 사용자가
"Backend가 DB에 연동해서 서버에 책 데이터를 저장하는 방식으로 가면, Data-Pipeline이
굳이 따로 저장 안 해도 되는 거 아니냐"고 물었고, 이 질문을 계기로 정리됐다:

- **서비스용 DB**(추천 API가 실제로 참조하는 DB)는 원래도 Data-Pipeline이 관여할
  일이 아니었다 — Backend importer가 canonical JSONL을 읽어 Backend 소유
  PostgreSQL에 적재하는 흐름은 애초 설계 그대로다. 이건 Option B가 필요했던 적이
  없다.
- Phase 1이 원래 해결하려던 건 그것과 별개로, **파이프라인을 개발하는 사람이 로컬에서
  수집 결과를 SQL로 조회하고 싶다**(예: "TOC 없는 책 목록", "이 책 preface 내용")는
  개발 편의 문제였다(Option A). 그런데 이 필요가 지금 당장 급하지 않다고 판단해,
  **사용자가 Phase 1 자체를 스킵하기로 결정했다.**
- 결론: **Phase 1은 진행하지 않는다.** SQLite/DB 관련 코드는 만들지 않는다. 다시
  필요해지면(조회가 실제로 불편해지면) 이 문서의 이전 버전에 있던 설계를 참고해
  새로 시작하면 된다 — git 이력(`git log -- docs/expansion-roadmap.md`)에서 이전
  버전을 볼 수 있다.

## 현재 상태

### 2026-09-21 — origin/main 업데이트 pull 완료

로컬이 `68eabce`(구 HEAD)에 머물러 있는 동안 origin/main에 8개 PR, 커밋 11개가 먼저
merge되어 있어 pull해서 반영했다(`3756d82`). 주요 내용:

- **TOC 커버리지 보강**: 신규 exact-edition allowlist 소스 추가(Larson/Penney 선형대수,
  Operating System Concepts 10판 — `public_book_sources.py` +280줄), flat/table/
  paragraph/bold 형태의 TOC를 파싱하는 범용 파서 추가, 기존 canonical dataset에서
  누락된 TOC만 채우는 신규 `enrich-toc` CLI 명령.
- **TOC 무결성 검증 강화**: `validation.py`에 레벨 정합성 검사(자식 레벨 = 부모 레벨+1,
  루트는 레벨 1)와 부모 참조 순환(cycle) 탐지 추가.
- **사람 검수(human audit) 워크플로 신설**: `relevance_review.py` 신규 +
  `prepare-relevance-review`/`finalize-relevance-review` CLI 명령 — Scale-50 v1/v2의
  topic relevance 판정을 사람이 한 번에 검수하는 기능. 서정민님 인수인계 문서에서
  "마지막 정리 작업"이라던 바로 그 작업이 여기서 마무리됨.
- **CI 신설**: `.github/workflows/checks.yml` — push/PR마다 pytest + ruff 자동 실행.
- `collect` 명령에 `--detail-limit` 옵션 추가.

병합 방법: 로컬 Phase 0 변경(`normalizers.py`)과 업스트림 변경이 같은 파일을 건드렸지만
diff hunk 위치가 서로 멀리 떨어져 있어(로컬은 파일 맨 앞 import/상수, 업스트림은 3253행
이후) `git stash push -u` → `git pull --ff-only origin main` → `git stash pop`으로
충돌 없이 자동 병합됨. 병합 후 `uv sync` + `uv run ruff check .` +
`uv run pytest` 재확인 — **193개 전체 통과**(기존 142개 + 업스트림 신규 51개).

아래 "참고: 인수 시점 코드 리뷰에서 나온 이슈" 목록은 이번 pull로 해결된 항목이 없다
(TOC 검증/relevance 검수는 이 로드맵이 추적하던 이슈 목록과 다른 주제). Phase 2에서
전환 대상인 `public_book_sources.py`는 이번 pull로 오히려 280줄 더 늘어났으므로,
allowlist를 config로 옮기는 작업의 필요성이 더 커졌다.

### Phase 0 — Topic Registry를 config로 통합 — ✅ 완료 (#26)

반영된 변경/신규 파일:

- 신규 `configs/topics.json` — topic별 domain, provider별 검색어 템플릿
  (`open_library_title`, `google_books_subject`), `relevance_term_pattern`,
  `conflicting_subjects_pattern`을 담는다. 기존 2개 topic
  (`operating-systems`, `linear-algebra`)만 들어있음.
- 신규 `src/data_pipeline/topics.py` — `configs/topics.json`을 로드해
  `TOPIC_REGISTRY`(pydantic `TopicSpec` dict), 하위 호환용 `TOPICS: dict[str, list[str]]`,
  `topic_choices()`, `topic_open_library_title()`, `topic_google_books_query()`,
  `topic_relevance_pattern()`, `topic_conflicting_subjects_pattern()`을 제공.
- 수정: `src/data_pipeline/normalizers.py` (하드코딩된 `TOPICS` dict 제거,
  `topics.py`에서 import — `cli.py`는 `normalizers`를 통한 재수출 덕분에 무변경),
  `src/data_pipeline/relevance.py` (`TOPIC_TERMS`/`CONFLICTING_SUBJECTS` 제거,
  helper 함수 사용), `src/data_pipeline/collectors/open_library.py`
  (`TOPIC_TITLES` 제거), `src/data_pipeline/collectors/google_books.py`
  (`TOPIC_QUERIES` 제거), `src/data_pipeline/manifest.py`
  (`RawArtifactSelector.topic`을 정적 `Literal[...]`에서 `str` +
  `topic_choices()` 멤버십 검증 `field_validator`로 교체).

검증 완료:

- `uv run ruff check .` 통과, `uv run pytest` 142개 전체 통과(2026-09-19, origin/main
  pull 이전 기준). pull 이후 재확인: 193개 전체 통과(2026-09-21, 아래 "2026-09-21"
  항목 참고).
- 리팩터링 전/후 회귀 확인(네트워크 없이): Open Library/Google Books 검색
  파라미터가 리팩터링 전과 byte-for-byte 동일, relevance gate(충돌 subject 거부,
  title-only 매칭) 동작 동일, manifest topic 검증 동일하게 동작.
- **아직 하지 않은 것**: 실제 네트워크로 `collect --topic operating-systems`/
  `linear-algebra` 커맨드를 돌려보는 end-to-end 회귀(정적 파라미터 비교로 충분하다고
  판단해 생략했음 — 필요하면 재개 시 수행).

### Phase 2 — Allowlist를 config 파일로 전환 — ✅ 완료 (#26)

**설계 변경 사항 (계획 대비)**: 계획에서는 YAML을 가정했지만, 이 저장소는 이미
`configs/mvp.json`/`configs/topics.json`처럼 JSON만 쓰고 있고 `pyproject.toml`에
PyYAML 의존성도 없어서 **JSON으로 진행**했다(불필요한 의존성 추가 금지라는
AGENTS.md 15절 원칙과 기존 관례를 따름). 나머지 설계(책 1권 = 파일 1개, 조회 함수
시그니처 불변)는 계획대로다.

변경/신규 파일:

- 신규 `src/data_pipeline/source_registry.py` — Pydantic `TypeAdapter` 기반 dataclass
  타입 검증과 `load_registry_dir(cls, directory) -> dict[str, T]`를 제공한다. 설정
  디렉터리의 존재·비어 있지 않음, 파일명과 `slug` 일치, 중복 slug, 미지원 필드를
  검증한다.
- 신규 `configs/sources/{publisher,publisher-document,public-book-page,open-textbook}/`
  — 기존 4개 allowlist 파일의 딕셔너리 리터럴을 `<slug>.json` 파일 18개로 분리
  (publisher 2, publisher-document 2, public-book-page 7, open-textbook 7).
- 수정: `publisher_sources.py`, `publisher_document_sources.py`,
  `public_book_sources.py`, `open_textbook_sources.py` — 각각 dataclass 정의는
  그대로 두고, 딕셔너리 리터럴을 `load_registry_dir(SpecClass, CONFIG_DIR)` 호출로
  교체. `publisher_source()`/`open_textbook_source()` 등 조회 함수 시그니처는
  불변이라 `collectors/*.py`, `normalizers.py`, `cli.py`는 무변경.

마이그레이션 방법(수작업 전사로 인한 오타 위험 제거): 기존 하드코딩된 dict를
`dataclasses.asdict()`로 JSON 덤프 → 새 `load_registry_dir()`로 다시 읽어 **원본과
`==` 비교(frozen dataclass 자동 `__eq__`)로 당시 이관한 18개 항목의 dataclass 필드
값이 모두 동일함을 스크립트로 확인한 뒤에만** 원본 `.py` 파일의 dict 리터럴을
제거함(스크립트는 scratchpad의 일회성 도구, 저장소에는 포함하지 않음).

검증 완료:

- `uv run ruff check .` / `uv run ruff format --check .` 통과,
  `uv run pytest` 193개 전체 통과(pull 이후와 동일 — Phase 2가 아무것도 깨지 않음).
- 4개 조회 함수(`open_textbook_source`, `publisher_source`, `public_book_source`,
  `publisher_document_source`) 전부 실제 slug로 스팟 체크: 중첩 `documents` tuple,
  `preface_page_range` 같은 `tuple[int, int]`, 존재하지 않는 slug에 대한
  `ValueError` 메시지까지 리팩터링 전과 동일하게 동작 확인.
- PR #26으로 병합됨. 이후 추가된 exact-edition source와 preferred-TOC 설정도 JSON
  registry로 함께 이관했고, 203개 테스트와 설치 wheel의 registry import를 확인했다.

### Phase 1 — ❌ 드롭됨 (위 "Phase 1(로컬 SQLite) 드롭 결정" 참고, 재논의 불필요)

### Phase 3 — ✅ 완료: 신규 topic 4개 등록

`configs/topics.json`에 `algorithms`/`databases`/`discrete-mathematics`/
`probability-statistics` 4개 추가. 각 topic을 실제 Open Library `search`로
5권씩 검증: databases/discrete-mathematics/probability-statistics는 5/5 정확히
관련 있는 교과서, algorithms는 5개 중 3개가 교과서급이고 나머지 2개는 대중서(추후
50권 규모로 늘릴 때 relevance gate로 걸러질 부분, 지금 당장 문제 아님). 이어서
4개 topic 전부 `collect --limit 5`까지 실행해 canonical 데이터 생성·병합·`report`
출력까지 코드 변경 없이 정상 동작 확인. 최신 main 통합 후 208개 테스트도 통과했다.
`README.md`에 새 "Topic taxonomy" 절로 이 4개 topic과 검증 결과를 기록.

**중요**: 이 4개는 아직 `configs/mvp.json`이나 scale pilot 매니페스트에는 포함되지
않았다 — `search`/`collect`로 바로 쓸 수 있는 topic만 추가된 것이고, 10권/50권
curated 데이터셋에 새 분야를 넣는 건 별도 작업(사람이 각 책을 검토해
`configs/sources/`에 allowlist 항목을 추가하는 과정, `docs/data-pipeline-guide.md`
8절 참고)이 필요하다.

### Phase 4 — 미착수

아래 "남은 작업" 참고.

## 남은 작업

### Phase 1 — ❌ 드롭됨, 계획 없음

이전에 여기 있던 SQLite 설계(별도 `sqlite_export.py`, `build-sqlite` CLI 명령,
FTS5 전문 탐색 등)는 더 이상 유효한 계획이 아니다. Data-Pipeline은 canonical
JSONL만 만들고, 조회는 Backend가 가져갈 서비스 DB나 필요시 `jq`/텍스트 편집기로
충분하다고 판단했다. 다시 필요해지면 git 이력(`git log -p -- docs/expansion-roadmap.md`)
에서 이전 설계를 되찾아 참고할 수 있다.

### Phase 2 — ✅ 완료. 위 "현재 상태 > Phase 2" 참고 (YAML 대신 JSON으로 진행됨).

### Phase 3 — ✅ 완료. 위 "현재 상태 > Phase 3" 참고.

### Phase 4 — 신규 provider collector 추가 (Internet Archive, HathiTrust)

- 신규 `collectors/internet_archive.py`: `open_library.py`와 동일 구조(httpx.Client
  + User-Agent, tenacity retry, `InvalidProviderResponse`, `detail_failures`).
  `https://archive.org/advancedsearch.php`(키 불필요)로 topic 검색,
  `https://archive.org/metadata/<identifier>`로 상세 메타데이터/가능한 경우
  TOC·설명 수집.
- 신규 `collectors/hathitrust.py`:
  `https://catalog.hathitrust.org/api/volumes/brief/json/isbn:<isbn>` 서지 조회
  (키 불필요). 저작권 있는 책은 본문 접근이 제한적이므로 **주로 서지/edition 정보
  보강**(서정민님이 남긴 "edition resolver 고도화" 과제에 직접 도움)에 기여하고,
  preface/sample 커버리지 향상은 기대하지 않는다 — README에 이 한계를 명시할 것.
- 두 provider 모두 `normalizers.py`에 기존 `_normalize_<provider>_response` 패턴으로
  추가, `identifiers.py`의 ISBN 검증과 기존 edition-mismatch 방어 로직 재사용
  (약화 금지).
- `cli.py`의 `--provider` 옵션과 `_collect_payload`/`_normalize` 분기에 6줄 내외 추가.
- 신규 테스트: `tests/test_internet_archive.py`, `tests/test_hathitrust.py`
  (`test_collectors.py`의 `httpx.MockTransport` 패턴 재사용).
- 추가 후보(이번엔 미포함, 추천만): **DOAB**(Directory of Open Access Books — OER
  전문 텍스트 확보에 유리), **Library of Congress loc.gov API**(무료 서지 메타데이터).

## 실행 순서

Phase 0(완료) → ~~Phase 1~~(드롭) → Phase 2(완료) → Phase 3(완료) → Phase 4(다음)

## 검증 방법 (매 phase 공통 + phase별)

공통: `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`

- Phase 0: `OpenLibraryCollector.search_parameters(...)` /
  `GoogleBooksCollector.search_parameters(...)` 출력이 리팩터링 전과 동일한지 정적 비교
  (완료). 필요하면 실제 네트워크로 `collect --limit 5` 1회 실행해 최종 확인.
- Phase 1: 드롭됨, 검증 대상 없음.
- Phase 2: 4개 조회 함수를 실제 slug로 호출해 리팩터링 전과 동일한 값이 나오는지
  확인(완료 — 위 "현재 상태 > Phase 2" 참고). 새 소스를 추가할 때는
  `configs/sources/<kind>/<slug>.json` 파일 하나만 추가하고 `slug` 필드와 파일명이
  일치하는지 확인.
- Phase 3(완료): 신규 4개 topic을 `search --limit 5`로 관련성 확인 →
  `collect --limit 5`로 실제 수집 → `report`에서 기존 2개와 함께 coverage row로
  나오는지 확인. 4개 전부 통과, 코드 변경 없음.
- Phase 4: 신규 collector로 실제 네트워크 1회 수집 → `report`에서 metadata
  coverage가 0이 아닌지 확인. 기존 10권 MVP/50권 scale pilot의 `report-scale`
  byte-identical 오프라인 재현 테스트가 그대로 통과하는지(회귀) 확인.

## 참고: 인수 시점 코드 리뷰에서 나온 이슈 (이 로드맵과 별개, 언젠가 처리)

- provider 간 장애 격리 비대칭: `google_books.py`의 `search_books`는 페이지네이션
  중 마지막 페이지 실패 시 이미 모은 페이지까지 버리고 전체 실패, `open_library.py`는
  개별 실패만 기록하고 계속 진행 — 신규 provider(Phase 4) 추가 시 `open_library.py`
  방식으로 통일할 것.
- `normalizers.py`의 `_authors_from_by_statement`가 "edited by"/"translated by" 같은
  표기를 저자 이름으로 잘못 삽입할 수 있음.
- `normalizers.py` 1,235~2,965행 부근, provider별 정규화 함수 6개가 base64 디코딩→
  PDF 매직바이트 검증→크기 제한→TOC 추출 패턴을 거의 그대로 복붙 — 새 provider
  추가 시 공용 헬퍼로 추출하는 것을 고려.
- `cli.py`의 `report` 명령 `--data-dir` 의미가 `collect`/`report-scale`과 다름
  (전자는 processed 디렉터리 자체, 후자는 루트 디렉터리).
- `validate_dataset`에 AGENTS.md가 명시한 "최소 1명 저자" 검증이 일반 경로에는 없음
  (scale-report 경로에만 경고로 존재).
