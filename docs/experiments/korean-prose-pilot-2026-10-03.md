# 한국어 본문 근거 후속 조사, 2026-10-03

기존 98권과 머리말 발췌 1건을 유지한 별도 사본에 **기초선형대수의 공식 머리말 발췌
230자**를 추가했다. 본문 유형 보유 도서는 1권에서 2권이 됐지만, 두 문서는 모두 발췌이며
완전한 장 본문 확보는 여전히 0건이다. 목차 보유 도서는 83권으로 같다.

## 수집기 수정과 조사 경계

[기초선형대수 공식 페이지](https://www.kyungmoon.com/shop/item.php?it_id=1698302408&device=pc)는
기존 canonical의 ISBN `9791160736571`과 일치한다. 발췌 표시가 `머리말 中에서`이고 HTML
요소 사이에서 줄바꿈이 생겨 기존 수집기가 거절했다. `중`/`中` 및 그 사이의 공백·줄바꿈만
허용하도록 수정했다. 실제 원문, 해시, 표시 근거를 보존하며 임의의 소개글을 승격하지 않는다.
기존 `머리말 중에서` 출력의 근거 문구는 유지한다.

추가 확인한 공식 페이지:

| ISBN | 관찰 | 처리 |
| --- | --- | --- |
| 9791160736571 | 명시적 머리말 발췌, 230자 | 재생성 사본에 추가 |
| 9791160737615 | 일반 소개, 직접 연결된 학습자료·정오표 PDF | 소개는 본문으로 승격하지 않음 |
| 9791190017183 | 일반 소개, 명시적 머리말 발췌 표시 없음 | 본문으로 승격하지 않음 |

[AI 시대를 위한 기초 선형대수학 공식 페이지](https://www.kyungmoon.com/shop/item.php?it_id=1739843960&device=pc)가
직접 연결한 학습자료 PDF는 42쪽이다. 1·2·42쪽의 텍스트와 첫 페이지 렌더링에서 문제별
답안 형식을 확인했으며 장 본문 표본으로 넣지 않았다. 수식의 일부 문자는 텍스트 추출 시
private-use 문자로 나와 그대로 난이도 분석에 넣어도 적절하지 않다. 원문 PDF와 요청 시각,
해시는 로컬 실험 폴더에 보존했다. 다른 공개 본문이 전혀 없다고 단정하지 않는다.

## 재현 및 검증

원본은 `data/experiments/text-extent-handoff-20261003/replay1`이다. 새 실험은
`data/experiments/korean-prose-pilot-20261003` 아래에 보존한다. 실패한 최초 수집의 raw도
남아 있으며, 같은 raw를 `enrich-publisher-excerpt --raw`로 두 번 재생한 `replay1`,
`replay2`의 canonical 네 파일과 v2 export가 바이트 단위로 같다. 원본 네 파일도 변하지 않았다.
책별 URL은 collector allowlist가 아니라 [실험 조사 목록](../../configs/experiments/korean-prose-pilot-v1.json)이다.

```bash
uv run data-pipeline enrich-publisher-excerpt \
  --data-dir data/experiments/text-extent-handoff-20261003/replay1 \
  --output-dir data/experiments/korean-prose-pilot-20261003/new-replay \
  --isbn 9791160736571 --topic linear-algebra \
  --raw <preserved-raw-artifact.json>
```

동일 사본의 ML 진단에서 새 문서는 49토큰으로 기존 50토큰 기준보다 짧아 점수를 생성하지
않았다. 기존 1,362자 발췌는 점수가 계산되지만 영어 용어 사전의 개념 매칭은 0건이었다.
수집량 증가와 한국어 난이도 품질 개선은 구분한다. [측정·해시 기록](korean-prose-pilot-2026-10-03.json)에
canonical, raw, PDF, ML 보고서 해시를 담았다. 원문·PDF·생성된 전체 데이터는 Git에 넣지 않는다.

전체 테스트 471개, Ruff 검사·포맷 통과. 합성 fixture로 한자 표기·줄바꿈을 허용하고,
불완전한 표시나 뒤에 문구가 더 붙는 소개를 거절하는 경계를 검사했다.
