# Data-Pipeline 저장소 가이드

이 문서는 CAU 캡스톤 8조 도서 추천 프로젝트의 `Data-Pipeline` 저장소가 **무엇을, 왜,
어떻게** 하는지 처음부터 끝까지 설명한다. 레퍼런스 표가 아니라 실제로 코드를 읽지
않고도 "이 시스템이 어떻게 동작하는가"를 이해할 수 있게 하는 것이 목적이다.

권위 있는 설계 사양은 여전히 `AGENTS.md`다. 이 문서와 내용이 어긋나면 `AGENTS.md`가
맞다. 이 문서는 그 사양이 실제 코드에서 어떻게 구현되어 있는지를 설명한다. 최근 진행
중인 작업의 배경/의사결정 기록은 `docs/expansion-roadmap.md`에 별도로 있다.

---

## 1. 이 저장소는 무엇을 하는가

책 추천 시스템 전체 파이프라인은 다음과 같이 3단계로 나뉜다.

```text
Data-Pipeline          →    ML 저장소               →   Backend
공개 자료 수집·정규화        개념 추출, 난이도 산정,        서비스 DB, 추천 API,
                            독자 프로필, 추천 로직          사용자 앱
```

이 저장소는 **첫 번째 단계만** 책임진다: 공개적으로 접근 가능한 책 정보(서지 메타데이터,
목차, 서문, 서론, 미리보기/샘플 텍스트)를 여러 출처에서 모아, 출처가 무엇이었는지 하나도
잃어버리지 않으면서, provider(수집 출처)에 무관한 하나의 공통 스키마로 정규화하는 것.

이 저장소는 다음을 **절대 하지 않는다** (`AGENTS.md` 21절 Non-Goals):

- 개념 추출, 난이도 산정, 추천 랭킹/스코어링 — ML 저장소의 책임
- 사용자 데이터, 서비스 DB, 추천 API — Backend의 책임
- 인증/paywall/CAPTCHA/rate-limit 우회 — 절대 금지 (`AGENTS.md` 5절)

---

## 2. 핵심 설계 원칙

이 네 가지 원칙이 이 저장소의 거의 모든 설계 결정의 근거다. 뒤에 나오는 각 기능을
읽을 때 "이게 왜 이렇게 복잡하게 되어 있지?"라는 의문이 들면 대개 아래 원칙 중 하나
때문이다.

1. **증거 우선, 추론은 나중에 (Evidence first, infer later)** — 원본 응답(raw)과
   정규화 결과(processed)를 분리 보관하고, provenance(어느 provider, 어느 URL, 언제
   조회했는지)를 절대 파괴하지 않는다.
2. **결측은 정상 데이터** — 모든 책이 서문·미리보기를 가질 필요는 없다. 없으면
   명시적으로 "없음"으로 나타내고, 절대 지어내지 않는다. 라이선스 정보를 모르면
   `null`이지 추측이 아니다.
3. **소규모 검증 우선** — 처음부터 대량 수집을 하지 않는다. 10권으로 파이프라인
   전체를 검증한 뒤 50권 규모로 확장하고, 그다음에야 더 늘린다.
4. **재현성** — 같은 raw 데이터로 다시 빌드하면 항상 byte-identical한 결과가 나와야
   한다. 네트워크 없이 오프라인으로 재현 가능해야 한다.

---

## 3. 전체 데이터 흐름

```text
1. 외부 소스 (공개 API, 출판사/저자 공식 페이지, OER, 공개 서점 카탈로그)
        ↓  Collector가 HTTP로 요청
2. Raw Response 보존
        data/raw/<provider>/<topic>/<타임스탬프>_<해시12자리>.json
        한 번 쓰면 절대 덮어쓰지 않음 (파일을 "x" 모드로 열어서, 이미 있으면 에러)
        ↓  Normalizer가 파싱
3. Parsing / Normalization
        provider별 응답 구조 → 공통 Book/Document/TocEntry/Source 모델
        ↓  기존 데이터와 병합
4. Merge (여러 번의 collect 실행 결과를 하나로 합침)
        같은 ID인데 내용이 다르면 자동으로 아무거나 선택하지 않고 즉시 에러
        ↓  pydantic + 교차 참조 검증
5. Validation
        스키마 검증(pydantic) + 참조 무결성/중복/TOC 계층 검증(validation.py)
        ↓  원자적으로 파일 교체
6. Canonical Dataset
        data/processed/{books,documents,toc,sources}.jsonl
        ↓
7. ML 저장소가 이 4개 파일만 보고 그 이후를 처리
```

이 흐름에서 실패는 **항상 눈에 보이게** 난다. 어느 단계에서 실패하든 부분적으로
쓰여진 파일을 남기지 않고(아래 6절), 조용히 레코드 하나를 버리지 않는다.

---

## 4. Canonical 데이터 모델 (`models.py`)

`data/processed/`에 4개의 JSONL 파일이 있고, 이게 ML 저장소와의 **유일한 계약**이다.
모두 pydantic 모델(`extra="forbid"` — 정의 안 된 필드가 있으면 검증 실패)이라 잘못된
모양의 레코드는 파일에 쓰이기 전에 걸러진다.

### `books.jsonl` — 한 줄 = 책 한 권

| 필드 | 의미 |
| --- | --- |
| `book_id` | `isbn13:9780...` / `isbn10:...` / `book_<20자리 hex>`(ISBN이 없을 때 결정적 fallback) 중 하나. ISBN이 있으면 `book_id`가 반드시 그 ISBN과 일치해야 한다(검증됨). |
| `isbn_10`, `isbn_13` | 체크디지트까지 검증됨(`identifiers.py`의 `is_valid_isbn_10/13`). |
| `title`, `subtitle`, `authors`, `publisher`, `published_year` | 서지 정보. `title`은 공백만 있으면 거부. |
| `language` | `^[a-z]{2,3}$` 패턴만 검증(실제 언어코드인지는 형식만 확인). |
| `topics` | 예: `["computer-science", "operating-systems"]`. 항상 상위 domain → 하위 topic 순서. |

### `documents.jsonl` — 텍스트 근거

`document_type`은 `description` / `publisher_summary` / `preface` / `introduction` /
`preview` / `sample_chapter` / `index` / `other` 중 하나(Literal로 강제). `text`는
빈 문자열/공백만 있으면 거부. `content_hash`는 `sha256:<64자리 hex>` 형식이 강제된다.

### `toc.jsonl` — 계층형 목차

**부동소수점을 정렬 키로 쓰지 않는다.** `level`(정수, 1부터), `order_index`(정수),
`parent_entry_id`로 명시적 트리 구조를 만든다. `"4.2 세마포어"`라면 `label="4.2"`,
`title="세마포어"`, `parent_entry_id`가 "4장" 항목을 가리킨다.

### `sources.jsonl` — 출처/provenance

모든 수집된 자료는 `sources.jsonl`의 레코드 하나를 가리켜야 한다. `provider`,
`source_type`, `url`, `retrieved_at`(타임존 필수), `license`(모르면 `null`, 절대
추측하지 않음), `content_hash`를 담는다.

---

## 5. Raw 데이터 보존과 재현성 (`storage.py`)

- `RawArtifact`: provider의 원본 JSON 응답을 감싼 불변 객체. `content_hash`는
  응답 본문의 SHA-256으로 **자동 계산되며**, 누가 다른 값을 넣으려 하면 검증에서
  걸린다.
- `write_raw_response()`는 파일을 `"x"` 모드(exclusive create)로 연다 — **같은 경로에
  이미 파일이 있으면 무조건 실패**한다. 즉 raw 데이터는 한 번 쓰이면 그 이후 어떤
  코드로도 덮어쓸 수 없다.
- 경로 규칙: `data/raw/<provider>/<topic>/<YYYYmmddTHHMMSSffffffZ>_<해시12자리>.json`.
  타임스탬프+해시 조합이라 같은 요청을 여러 번 해도 매번 새 파일이 생긴다.
- `write_dataset()`(canonical JSONL 4개 파일을 쓰는 함수)은 **원자적 교체**를 한다:
  임시 파일에 먼저 쓰고, 기존 파일이 있으면 `.bak`로 백업한 뒤, `os.replace()`로
  한 번에 교체한다. 중간에 실패하면 백업에서 롤백하거나(기존 파일이 있었던 경우)
  새로 생긴 파일을 지운다(원래 없었던 경우). **4개 파일 중 일부만 존재하는 상태는
  절대 만들지 않는다** — 하나라도 있는데 나머지가 없으면 `partial dataset` 에러.
- `data/raw/`, `data/processed/`, `data/experiments/`는 Git에서 제외된다(재현
  가능한 산출물이므로). 커밋되는 건 `tests/fixtures/`의 소규모 테스트 fixture뿐이다.

---

## 6. Collector 아키텍처 — 6가지 수집 방식

소스 우선순위(`AGENTS.md` 4절): **공식/공개 API → 출판사·저자 공식 페이지 → 오픈
교육자료(OER) → 일반 공개 HTML → 브라우저 자동화(최후 수단, 현재 미사용)**.

### 6.1 일반 메타데이터 API (모든 책에 자동 적용 가능)

- **Open Library** (`--provider open-library`, 기본값): 무인증 검색 + 편집본(edition)
  + 작품(work) API. 검색 결과 중 영어 편집본을 찾아 편집본/작품 상세를 **개별적으로**
  추가 조회하는데, 이 상세 조회 하나가 실패해도(rate limit, 네트워크 오류 등) 그
  실패만 기록(`detail_failures`)하고 나머지는 계속 진행한다 — 책 1권 문제로 전체
  수집이 죽지 않는다.
- **Google Books** (`--provider google-books`): 결과 40건 제한을 넘으면 `startIndex`
  페이지로 나눠서 순차 수집한다. Open Library와 달리, 페이지 하나가 실패하면 이미
  모은 페이지까지 포함해 **전체 검색이 실패**한다(부분 결과를 발행하지 않음).

두 provider 모두 topic별 검색어를 `configs/topics.json`(7절)에서 가져오므로, 코드
자체에는 topic 이름이 하드코딩되어 있지 않다.

### 6.2 Allowlist 기반 exact-edition 수집 (책 1권씩 검토된 것만)

나머지 4가지는 **특정 책 한 권**을 정확히 겨냥한, 사람이 검토한 소스다. 이유는
저작권: 임의 URL을 CLI로 넘겨서 아무 책이나 긁어올 수 없게 만들어져 있다 — 새 책을
추가하려면 반드시 `configs/sources/<kind>/<slug>.json`에 항목을 추가해야 하고
(8절), 그 항목이 실제로 그 책과 일치하는지(ISBN, edition, 제목, 목차 구조, PDF
매직바이트, 텍스트 마커 등)를 정규화 단계에서 검증한다. 검증에 실패하면 조용히
넘어가지 않고 명시적으로 실패한다.

| Collector | CLI 명령 | 무엇을 수집하나 | 검증 |
| --- | --- | --- | --- |
| `publisher_pages.py` | `collect-publisher` | 출판사 공식 정체성/목차 페이지 (예: Wiley) | ISBN, edition, 목차 제목 목록 |
| `publisher_documents.py` | `collect-publisher-document` | 출판사가 공개한 PDF(샘플 챕터, 부록 등) | ISBN, PDF 매직바이트(`%PDF-`), 크기 상한, 텍스트 마커 |
| `public_book_pages.py` | `collect-public-page` | eCampus 등 서점 카탈로그의 완전한 목차 HTML | ISBN, edition, 목차 전체 개수, root/child 제목·개수, (최근 추가) 자손(descendant) 개수 |
| `open_textbooks.py` | `collect-open-textbook` | OSTEP·Hefferon·xv6 등 오픈 교재 전체(PDF 또는 HTML) | 저자, 버전, ISBN, 목차 구조, PDF 페이지 수, identity/preface/sample 텍스트 마커, 소스별 크기 상한 |

모든 allowlist 기반 수집은 **exact-edition 검증**을 통과해야만 canonical 데이터를
발행한다 — 예를 들어 7판을 요청했는데 페이지 내용이 8판 것이면 그 응답은 거부된다.

### 6.3 Collector 공통 패턴

모든 네트워크 collector는 같은 관례를 따른다: `httpx.Client`를 주입 가능한 형태로
생성(테스트에서 `MockTransport`로 대체 가능), 일시적 오류(429, 5xx, 타임아웃)에만
`tenacity`로 최대 3회 재시도, 응답이 성공했지만 쓸 수 없는 모양이면
`InvalidProviderResponse`를 던진다.

---

## 7. Topic Registry — `configs/topics.json` + `topics.py`

topic(예: `operating-systems`)마다 다음이 필요하다: 어느 domain에 속하는지, Open
Library에 검색할 제목 문자열, Google Books에 검색할 subject 값, scale 실험에서
"이 후보가 진짜 이 topic인지" 판정할 정규식(relevance pattern), 경쟁 분야로
판단해서 거부할 정규식(선택).

이 모든 것이 **`configs/topics.json` 한 파일**에 있다. `src/data_pipeline/topics.py`가
이 파일을 로드해서 `TOPIC_REGISTRY`를 만들고, `normalizers.py`/`relevance.py`/
`collectors/open_library.py`/`collectors/google_books.py`/`manifest.py`가 전부
여기서 값을 가져다 쓴다. **새 topic을 추가하는 건 이 JSON 파일에 항목 하나를 더하는
것뿐이다** — 코드 변경이 필요 없다 (예전에는 5개 파일에 흩어져 있었다).

```json
{
  "operating-systems": {
    "domain": "computer-science",
    "title": "Operating Systems",
    "open_library_title": "operating systems",
    "google_books_subject": "Operating systems",
    "relevance_term_pattern": "\\boperating\\s+systems?\\b",
    "conflicting_subjects_pattern": "\\b(?:robotics?|electric\\s+power|...)\\b"
  }
}
```

---

## 8. Source Registry — `configs/sources/` + `source_registry.py`

6.2절의 4가지 allowlist collector가 쓰는 "책 1권의 검증 규칙"도 마찬가지로
데이터로 분리되어 있다. 예전에는 `open_textbook_sources.py` 같은 파일 안에 파이썬
딕셔너리로 668줄씩 박혀 있었는데(책 1권 추가 = 코드 수정), 지금은:

- 각 `.py` 파일(`publisher_sources.py`, `publisher_document_sources.py`,
  `public_book_sources.py`, `open_textbook_sources.py`)은 **dataclass 정의와
  `<kind>_source(slug)` 조회 함수만** 갖고 있다.
- 실제 데이터는 `configs/sources/<kind>/<slug>.json`(책 1권 = 파일 1개)에 있다.
- `src/data_pipeline/source_registry.py`의 `load_registry_dir(cls, directory)`가
  모듈 import 시점에 그 디렉터리의 모든 JSON을 읽어 dataclass 인스턴스로 만든다.
  타입 힌트를 보고 `tuple[...]`, `X | None`, 중첩 dataclass를 재귀적으로 변환하는
  범용 로더라, 4개 kind 전부가 이 함수 하나를 공유한다.
- JSON 파일명은 반드시 그 안의 `slug` 필드와 같아야 한다(다르면 로딩 시 에러) —
  파일 이름만 바꾸고 내용을 안 바꾸는 실수를 방지.

**새 exact-edition 책을 추가하는 것도 이제 코드 변경이 아니라 JSON 파일 추가다.**
`<kind>_source("slug")` 같은 조회 함수의 시그니처는 그대로라 collector/normalizer
쪽 코드는 전혀 건드릴 필요가 없다.

---

## 9. Merge — 여러 번의 수집 결과를 하나로 (`datasets.py`)

`collect` 계열 명령을 여러 번 실행하면(예: operating-systems 수집 후
linear-algebra 수집) 매번 기존 `data/processed/`와 새 결과를 합친다.

- **같은 ID인데 내용이 다르면 조용히 하나를 선택하지 않고 즉시 `DatasetMergeError`를
  던진다.** (raw 응답은 이미 디스크에 남아있으니 데이터가 사라지진 않지만, canonical
  출력은 만들어지지 않는다.)
- 책(`Book`)은 예외적으로 `topics` 필드만은 합집합으로 허용한다 — 같은 책이 여러
  topic 검색에 다 걸릴 수 있기 때문. 그 외 필드가 다르면 충돌로 처리.
- 출처(`Source`)는 같은 URL을 다시 수집했을 때 최신 `retrieved_at` 스냅샷으로
  교체하되, **같은 시각에 내용이 다른 두 응답**은 명백한 버그로 보고 에러 처리한다.
- `merge_datasets()`는 이 규칙들을 적용해 `documents`/`toc`도 "그 시점에 선택된
  source snapshot"에 속한 레코드만 유지한다.

---

## 10. Validation — 눈에 보이는 실패 (`validation.py`)

pydantic이 레코드 하나하나의 모양을 검증한다면, `validate_dataset()`은 **레코드
사이의 관계**를 검증한다:

- 중복 ID(book_id/source_id/document_id/toc_entry_id), 중복 ISBN
- 모든 `source`/`document`/`toc` 항목이 실제 존재하는 `book`을 가리키는지, 그리고
  같은 book 소유인지(다른 책 소유의 source를 잘못 참조하지 않는지)
- 모든 `book`이 최소 하나의 `source`를 갖고 있는지
- **TOC 계층 정합성**: 자식의 `level`이 부모의 `level + 1`인지, 루트는 `level == 1`
  인지, 그리고 부모 참조가 순환(cycle)을 만들지 않는지 — 순환 탐지는 스택 오버플로우
  없이 반복문으로 구현되어 있다(악의적이거나 손상된 깊은 트리에도 안전).

검증에서 나온 에러는 리스트로 반환되고, `collect`/`build` 계열 CLI 명령은 이 리스트가
비어있지 않으면 **파일을 쓰지 않고** 종료 코드 1로 실패한다.

---

## 11. CLI 명령어 전체 (`uv run data-pipeline ...`)

### 11.1 수집

| 명령어 | 역할 |
| --- | --- |
| `search --topic <topic> --limit N [--provider ...]` | 실제로 저장하지 않고 후보만 미리 확인 |
| `collect --topic <topic> --limit N [--provider ...] [--detail-limit N] [--data-dir ...]` | 일반 API로 수집, raw 저장, 정규화, 기존 데이터와 병합, 검증 통과 시에만 저장 |
| `collect-publisher --source <slug>` | 출판사 정체성/목차 페이지 수집 (allowlist) |
| `collect-publisher-document --source <slug>` | 출판사 PDF 수집 (allowlist) |
| `collect-public-page --source <slug>` | 서점 카탈로그 HTML 수집 (allowlist) |
| `collect-open-textbook --source <slug>` | 오픈 교재 수집 (allowlist) |
| `enrich-toc --data-dir <dir> [--max-sources N] [--dry-run]` | **새 네트워크 소스를 만들지 않고**, 기존 canonical dataset에서 TOC가 없는 책만 골라 이미 있는 publisher/public-page allowlist로 채운다. `--dry-run`은 실제로 수집하지 않고 계획만 출력. |

### 11.2 빌드 (오프라인, 네트워크 없이 raw → canonical)

| 명령어 | 역할 |
| --- | --- |
| `build --raw <artifact> [--raw ...]` | 지정한 raw 아티팩트들만으로 canonical 재빌드. 재현성 검증용. |
| `build-manifest --manifest <json> --data-dir <dir>` | `configs/mvp.json` 같은 매니페스트가 가리키는 "최신" raw 아티팩트들을 자동으로 찾아 빌드하고, 최종 book_id 집합이 매니페스트와 정확히 일치하는지 검증 |

### 11.3 리포트

| 명령어 | 역할 |
| --- | --- |
| `report [--data-dir ...]` | 4개 canonical 파일 기준 커버리지를 사람이 읽기 좋은 텍스트로 출력 (topic별 + 책별) |
| `report-scale --manifest <json> --data-dir <dir>` | 대규모 실험용 상세 리포트. `scale-report.json`(discovery/dedup/coverage/failure 원인 분류/무결성 지표) + `scale-audit.csv`(사람이 검토할 빈 칸 포함) 생성 |
| `compare-scale --v1-report ... --v2-report ... --v1-audit ... --v2-audit ...` | 두 scale 실험을 비교. **사람이 채운 `topic_relevant` 라벨이 없으면 precision은 `null`** — 자동으로 정확도를 꾸며내지 않는다 |

### 11.4 사람 검수(Human Review) 워크플로 (12절 참고)

| 명령어 | 역할 |
| --- | --- |
| `prepare-relevance-review --v1-report ... --v2-report ... --v1-audit ... --v2-audit ... --output <csv>` | v1/v2에 선택된 책 전체를 합쳐 중복 없는 검수용 CSV 1개 생성 |
| `finalize-relevance-review --review <csv> --v1-output ... --v2-output ...` | 사람이 다 채운 검수 CSV를 다시 v1/v2 형식의 audit CSV 2개로 분리 (→ `compare-scale`에 입력) |

---

## 12. Scale Pilot과 Relevance Gate — 대규모 실험이 실제로 어떻게 검증되는가

10권 golden dataset(`configs/mvp.json`)은 사람이 각 책을 검토해서 정확하다. 문제는
"이 방식이 50권, 200권으로 늘어나도 통할까?"인데, 이걸 확인하는 게 Scale Pilot이다.

1. **Scale-50 (v1)**: `configs/experiments/scale-50.json`. 일반 API(Open Library)로
   topic당 25권씩 자동 수집. Allowlist는 전혀 쓰지 않는다 — 순수하게 "일반적인
   방법으로 얼마나 잘 되는가"를 보기 위해서다. 결과: metadata는 잘 모이지만 TOC/본문
   커버리지가 낮고, 제목만으로 검색하면 주제와 무관한 책(예: *Robot Operating
   System*)이 섞여 들어온다.
2. **Scale-50 v2 (relevance gate)**: `configs/experiments/scale-50-v2.json`.
   **같은 raw 응답**에 대해 `topic-evidence-v1`이라는 추가 필터(`relevance.py`)만
   켜서 재정규화한다. Open Library가 준 subject 메타데이터가 topic과 관련 있는지
   정규식으로 확인하고, subject 정보가 아예 없으면 제목만으로 판단하되
   `title_only_unverified`로 표시해 "확인 안 됨"을 숨기지 않는다. 경쟁 분야
   subject(로보틱스, 전력공학 등)가 보이면 거부.
3. **`report-scale`**이 만드는 `scale-report.json`은 discovery(후보 몇 개 찾았고 몇
   개가 정규화됐는지), coverage(topic/책별 증거 종류), failure 원인 분류(왜 이
   evidence가 없는지 — 아예 지원 안 하는 소스인지, provider가 없다고 답했는지, 조회
   자체가 실패했는지), 무결성 지표(끊어진 참조, 중복 ID, 재현성)까지 전부 담는다.
4. **`scale-audit.csv`**는 같은 정보를 스프레드시트로 보기 좋게 만든 것으로,
   `identity_ok`/`topic_relevant`/`toc_matches_book`/`prose_matches_book`/
   `edition_ok`/`notes` 열이 **항상 빈칸**으로 생성된다 — 시스템이 자기가 맞다고
   주장하지 않고, 사람이 채워야 할 자리로 명시적으로 남겨둔다. `=`, `+`, `-`, `@`로
   시작하는 값은 CSV 포뮬러 인젝션 방지를 위해 앞에 작은따옴표가 자동으로 붙는다
   (`scale_reporting.spreadsheet_safe_csv_value`).

---

## 13. 사람 검수 워크플로 상세 (`relevance_review.py`)

v1과 v2 모두 별도 `scale-audit.csv`를 만들기 때문에, 같은 책을 두 번 검토하게 될
위험이 있다. 이를 막기 위한 게 통합 검수 워크플로다.

1. `prepare-relevance-review`가 v1/v2의 `scale-report.json` + `scale-audit.csv`를
   입력받아, **v1과 v2에 선택된 책 전체의 합집합**을 중복 없이 CSV 한 장으로 만든다.
   각 행에는 "v1에도 선택됐는지", "v2에도 선택됐는지", "선택이 바뀌었는지", 그리고
   relevance gate가 왜 이 책을 선택/거부했는지 근거(subject evidence 등)가 같이
   보인다. `topic_relevant`, `notes` 칸만 비어 있다.
2. 사람이 이 CSV 하나에 대해서만 `topic_relevant`(yes/no)를 채운다.
3. `finalize-relevance-review`가 이 완료된 CSV를 다시 원래의 v1용/v2용 두 개
   `scale-audit.csv`로 쪼개서 각 라벨을 채워 넣는다. 이 함수는 입력값(책 제목, 저자,
   출판연도, 선택 여부 플래그)이 원본 리포트와 정확히 일치하는지 재검증한 뒤에만
   진행하고, 두 출력 모두를 원자적으로(임시 파일 → `os.replace`) 써서 한쪽만
   생성되는 상태를 만들지 않는다.
4. 그렇게 완성된 두 audit CSV를 `compare-scale`에 넘기면, v1과 v2 중 어느 필터가
   실제로 더 정확했는지(precision) 처음으로 숫자로 나온다. 사람 라벨이 모든 책에
   대해 없으면 여전히 `null`을 반환한다 — 절반만 채운 라벨로 정확도를 계산하지
   않는다.

---

## 14. 테스트와 CI

- `tests/`는 네트워크 없이 결정적으로 도는 것이 기본 원칙이다.
  `httpx.MockTransport`로 실제 HTTP 요청 없이 collector를 테스트한다
  (`tests/test_collectors.py` 참고).
- `.github/workflows/checks.yml`: push/PR마다 `uv run pytest`,
  `uv run ruff check .`, `uv run ruff format --check .`를 자동으로 돌린다.
- 로컬에서 같은 걸 그대로 돌리려면:

  ```bash
  uv sync
  uv run pytest
  uv run ruff check .
  uv run ruff format --check .
  ```

---

## 15. 디렉터리 구조

```text
Data-Pipeline/
├── AGENTS.md                      # 권위 있는 설계 사양
├── README.md                      # 실행 방법, 실제 수집 결과 로그
├── docs/
│   ├── data-pipeline-guide.md     # 이 문서
│   └── expansion-roadmap.md       # 최근 리팩터링 작업의 배경/진행 상태
├── .github/workflows/checks.yml   # CI (pytest + ruff)
├── configs/
│   ├── mvp.json                   # 10권 golden dataset 매니페스트
│   ├── topics.json                # topic taxonomy (7절)
│   ├── sources/                   # exact-edition allowlist 데이터 (8절)
│   │   ├── publisher/<slug>.json
│   │   ├── publisher-document/<slug>.json
│   │   ├── public-book-page/<slug>.json
│   │   └── open-textbook/<slug>.json
│   └── experiments/
│       ├── scale-50.json          # Scale Pilot v1 매니페스트
│       └── scale-50-v2.json       # Scale Pilot v2(relevance gate) 매니페스트
├── src/data_pipeline/
│   ├── cli.py                     # Typer 기반 CLI 진입점 (11절)
│   ├── collectors/                # provider별 수집기 (6절)
│   │   ├── base.py                # 공용 헬퍼(재시도 판정, JSON 파싱)
│   │   ├── open_library.py
│   │   ├── google_books.py
│   │   ├── publisher_pages.py
│   │   ├── publisher_documents.py
│   │   ├── public_book_pages.py
│   │   └── open_textbooks.py
│   ├── topics.py                  # topics.json 로더 (7절)
│   ├── source_registry.py         # configs/sources/*.json 범용 로더 (8절)
│   ├── open_textbook_sources.py   # dataclass 정의 + 조회 함수 (데이터는 JSON에)
│   ├── publisher_sources.py
│   ├── publisher_document_sources.py
│   ├── public_book_sources.py
│   ├── models.py                  # canonical 스키마 (4절)
│   ├── normalizers.py             # provider 응답 → canonical 변환 (가장 큰 파일)
│   ├── identifiers.py             # ISBN 검증, 결정적 ID/해시 생성
│   ├── validation.py              # 교차 참조·무결성 검증 (10절)
│   ├── datasets.py                # 여러 수집 결과 병합 (9절)
│   ├── storage.py                 # raw/processed 파일 입출력 (5절)
│   ├── manifest.py                # mvp.json/experiments 매니페스트 빌드
│   ├── reporting.py                # `report` 명령의 커버리지 텍스트 생성
│   ├── scale_reporting.py         # `report-scale`의 상세 리포트/audit CSV (12절)
│   ├── scale_comparison.py        # `compare-scale` (12절)
│   ├── relevance.py               # topic-evidence-v1 relevance gate (12절)
│   ├── relevance_review.py        # 사람 검수 워크플로 (13절)
│   └── diagnostics.py             # 정규화 단계 통계 수집
└── tests/                          # provider 응답 fixture 기반 결정적 테스트
```

---

## 16. 현재 진행 단계

1. **1차 마일스톤(완료)**: OS 5권 + 선형대수 5권, 총 10권 golden dataset
   (`configs/mvp.json`). 현재 10권, 31개 문서, 1,163개 TOC 엔트리, 52개 source
   레코드.
2. **2차 마일스톤 — Scale Pilot(완료)**: 주제당 25권, 총 50권 규모 파일럿(12절).
3. **Scale Pilot v2 — 관련성 게이트 + 사람 검수(완료)**: `topic-evidence-v1` 필터와
   통합 사람 검수 워크플로(13절)까지 완료.
4. **TOC 커버리지 지속 확장(진행 중)**: 새 exact-edition public-book-page 소스를
   계속 추가하며 `enrich-toc`로 기존 dataset의 빈 TOC를 채우는 작업이 여러 PR로
   계속 이어지고 있다(예: Larson/Penney/Nutt 선형대수·운영체제 TOC).
5. **topic/allowlist 데이터화(완료, 7·8절)**: topic 상수와 allowlist를 코드에서
   config 파일로 분리. 새 topic·새 curated 책 추가가 코드 변경 없이 가능해짐.
6. **다음 계획**: 신규 topic 4개(자료구조/알고리즘, 데이터베이스, 이산수학, 확률과
   통계) 및 신규 provider(Internet Archive, HathiTrust) 추가 — 자세한 배경과 진행
   상태는 `docs/expansion-roadmap.md` 참고.

---

## 17. 하지 않는 것 (Non-Goals)

리더 프로필 계산, 개념 숙련도 추정, 필요 개념 추론, 학습목표 매칭, 추천 랭킹/스코어링,
어휘·구문 난이도 산정, LLM 문항 생성, 사용자 평가, Spring Boot 연동, 프로덕션 DB
설계, OCR, 모바일 기능 — 이 모든 것은 `ML` 저장소(또는 그 이후 Backend)의 책임이다.
