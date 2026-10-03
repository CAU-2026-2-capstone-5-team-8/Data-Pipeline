# 저장된 영문 필드 연결과 비교, 2026-10-03

별도 작업 폴더의 미완성 영문 보강 작업에서 canonical 필드 계약만 분리했다. 원본 작업
폴더의 변경 파일과 번역 캐시는 그대로 두고, 최신 main 기반의 독립 브랜치에서 v3 exporter를
추가했다. 번역 API 실행·자동 영어 복사·전체 번역 명령의 통합은 이번 범위에 넣지 않았다.

기존 `english-linear-algebra-pilot-20261002/processed`의 10권, 목차 666행을 그대로 사용했다.
책·문서·목차·출처의 각 행에서 영문 필드만 제외하면 원본 Discovery 입력과 완전히 같음을
확인했다. 저장된 영문 문서는 0개이므로 이 자료로 본문 난이도 비교를 주장하지 않는다.

```bash
uv run data-pipeline export-ml-evidence \
  --contract-version book-evidence-v3 \
  --dataset-dir data/experiments/english-linear-algebra-pilot-20261002/processed \
  --output data/experiments/english-evidence-comparison-20261003/book-evidence-v3.jsonl
```

## 검증

- v3 exporter/validator와 ML reader가 10권, 목차 666행을 처리했다.
- 원문·영문·문서 범위·권리 정보와 해시를 함께 유지한다. 원문 해시는 번역 해시로 바꾸지 않는다.
- v3 내보내기 두 번이 같고, 실제 CLI 출력도 동일하다.
- 기존 원문 v1 98권, 범위 포함 v2 98권은 이전 출력과 바이트 단위로 같다.
- 실제 원문/영문 비교의 매칭 도서는 4→10권, 책·개념 연결은 13→131개다. 동일 설정과 동일
  목차 행만 비교했다. 정확도·추천 품질·번역 타당성 평가는 아니다.
- 전체 테스트 476개, Ruff 검사·포맷 통과. ML 대응 검사는 342개다.

[기계 판독 기록](english-evidence-comparison-2026-10-03.json)에 입력 네 파일, 저장된 번역 실행
기록, v3 출력, 비교 보고서의 해시를 담았다. 새 번역 API 호출은 0회다. 이전 번역 작업의
비용이나 모델 품질을 새로 검증한 것은 아니다. 실제 텍스트/번역 및 전체 행별 비교는
ignored 실험 폴더에 남긴다.

## 통합 순서

ML의 v3 reader를 먼저 반영한 뒤 exporter를 적용한다. 계정·개념 진단 기능이 포함된 기존
ML PR #32를 통합할 때는 이 v3 계약을 유지해야 한다. 그 브랜치의 실험용 v1 `en_text`
추가를 다시 가져오면 버전 경계가 무너지므로 해당 부분은 중복 통합하지 않는다.
실행 중인 서비스, DB, 원래 작업 폴더, 미완성 번역 명령은 변경하지 않았다.
