# Discovery 471권: 도서 선정 신호와 텍스트 근거 점검

2026-10-03, 보존된 `discovery-600-20260929`의 6분야 canonical 자료를 오프라인으로 검사했다.
새 수집이나 원본 수정은 하지 않았다. 집계와 입력/출력 해시는
[실측 JSON](selection-signals-2026-10-03.json)에 있다. 이 자료는 별도 계정 검증 DB의 실도서 3권과 다르다.

## 확인한 범위

| 분야 | 도서 | 목차 있음 | 서문·서론·미리보기·샘플 문서 | 추가 검토 신호 |
| --- | ---: | ---: | ---: | ---: |
| 알고리즘 | 70 | 69 | 0 | 5 |
| 데이터베이스 | 93 | 90 | 0 | 0 |
| 이산수학 | 92 | 84 | 0 | 0 |
| 선형대수 | 98 | 83 | 0 | 0 |
| 운영체제 | 54 | 49 | 0 | 0 |
| 확률과 통계 | 64 | 64 | 0 | 37 |
| 합계 | 471 | 439 | 0 | 42 |

자료 형태는 목차+소개 350권, 목차만 89권, 소개만 4권, 메타데이터만 28권이다.
본문에 해당하는 document_type이 없는 이 스냅샷에서 소개나 목차를 본문으로 바꾸어 독해 난이도를 만들지 않는다.
다른 curated/영어 pilot 자료의 본문 확보 여부는 이 결과로 판단할 수 없다.

## 자동 신호와 실제 판단의 차이

문제집·내신 등 명시적인 제목/부제 신호는 5권, 기존 분야 설정의 충돌 단어는 39권에서 발견됐다.
중복을 제외한 합계가 42권이다. 예를 들어 알고리즘 교재 설명의 ‘기출’ 언급도 패턴에 걸렸다.
책 전체가 다른 분야라는 판정이 아니므로 `wrong_subject` 대신 `review_required`로 표시한다.

ISBN 부재는 조회 불가를 뜻하지 않고, 목차 보유도 적합한 교재나 추천 후보의 충분조건이 아니다.
정규식은 모든 문제집/해설집/일반서를 판별하지 못한다. `evidence_present` 401권도 교재 적합성이 승인된 것이 아니다.
사람 검토란은 모두 비어 있으며 precision/recall을 계산할 gold label은 없다.

## 구현과 검증

- 기존 PR #40의 audit-selection을 schema v2로 보완했다. canonical four-JSONL 계약은 바꾸지 않았다.
- 한국어·부제 마커와 실제 텍스트별 출처/위치, 판본 근거, document 종류/길이를 보존한다.
- 수학 상위 분야 대신 설정된 leaf를 선택하고 여러 leaf가 있으면 각각 기록한다.
- 기존 canonical topic 배정을 다시 적합성 근거로 사용하지 않는다.
- 잘못 연결된 책/문서/출처는 보고 전 거부한다. 기존 사람 검토 파일 및 입력 파일 덮어쓰기도 거부한다.
- 6분야를 각각 두 번 실행해 JSON/CSV가 바이트 단위로 동일함을 확인했다. 원본 24개 파일의 해시는 실행 전후 동일했다.
- 로컬 전체 pytest 433개 및 Ruff/형식 검사를 통과했다. worktree의 `src`를 명시해 기존 checkout을 잘못 검사하지 않도록 했다.

상세 보고서와 빈 검토 시트는 로컬 ignored
`Data-Pipeline/data/experiments/selection-audit-v2-20261003/{first,second}/<topic>/`에 있다.

재현 예시(동일 입력 자료가 있는 checkout):

```sh
uv run data-pipeline audit-selection \
  --data-dir data/experiments/discovery-600-20260929/topics/probability-statistics \
  --report data/experiments/new-selection-audit/probability-statistics/audit.json \
  --review data/experiments/new-selection-audit/probability-statistics/review.csv
```

## 다음 수집·연결 순서

1. 42권의 검토 신호를 출처와 함께 확인해 실제 분야 오류와 문제집/시험 대비/교재를 구분한다.
2. 선형대수의 현재 연결 후보를 우선으로 동일 판본의 공개 서문/샘플 확보 가능성을 조사한다.
3. 확보된 실제 텍스트의 출처·판본·언어·권리 정보를 유지한 채 기존 canonical 경로로 추가한다.
4. 검토 결과를 자동 승인으로 바꾸지 않고, ML/Backend 추천 후보 변경은 별도 실험으로 전후 비교한다.
