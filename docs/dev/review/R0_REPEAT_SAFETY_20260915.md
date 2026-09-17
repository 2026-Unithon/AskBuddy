# R0 반복 평가 안전성 — 구현 검증

2026-09-15. 기준 HEAD c73549a + 이번 로컬 변경. 계획은 [R_IMPLEMENTATION_PLAN](../plan/R_IMPLEMENTATION_PLAN.md) 항목 1이며 W 계획 ③⑤와 C0 D18을 대조했다.

## 완료한 것

`app/team/answer_metrics.py::paired_gate`에 사전 필수 질문 ID 목록과 질문별 반복 안정성/미판정/관측 악화 검사를 추가했다. 기존 중앙값·문턱·2/3 방향·비용 게이트는 유지한다. 출력 버전은 r_paired_gate/v2이며 과거 결과를 덮어쓰지 않는다.

- ALL_SUCCESS→MIXED/ALL_FAILURE뿐 아니라 MIXED→MIXED에 숨어 있는 필수 질문의 짝별 True→False도 차단한다.
- 미판정(None)은 분모에서 빼거나 실패(False)로 변환하지 않는다. 영향을 받은 Δ와 대표 중앙값은 null이며 게이트는 보류한다.
- 필수 목록 None은 명시적 빈 목록과 다르다. 기존 호출자가 목록을 생략하면 승격 가능으로 판정하지 않는다.
- 외부 must_have_regressions=0을 보내도 관측한 악화를 덮을 수 없다. 이미 관측한 악화는 다른 반복의 미판정으로 지우지 않는다.
- 안정성 개선은 별도 보고하고 대표 개선량에 이중 가산하지 않는다.
- 문자열 'yes', None 같은 미확정 비용/원장 판정, NaN/Infinity 폭, bool 악화 건수, 누락·중복·분모 밖 ID는 거절한다.

## 직접 재현

일반 질문 8개는 baseline=False→candidate=True, 필수 질문 1개는 baseline 3회 모두 True, candidate=True/True/False로 두었다. 동일 입력과 외부 악화 건수 0에 대해 HEAD의 기존 함수를 읽어 실행하면 eligible=True였고, 새 함수는 median_delta=8을 그대로 유지하면서 eligible=False, MUST_HAVE_REGRESSION을 반환했다. 모델·DB 없이 합성 bool 입력으로 재현한 산술 검증이다.

## 검증 결과

- 전체 회귀 **386 passed / 83 subtests passed**, 기존 Starlette/AnyIO deprecation warning 1개.
- 새 반복 안전성 테스트 12개: 필수 안정성 저하·불안정 항목 악화·완전 실패·필수/일반 미판정·목록 누락·잘못된 ID/입력·정상 개선/비용·안정성 개선 이중계산·관측 악화 보존.
- 변경 API 모듈 1개 매장 격리 AST 검사 위반 0. diff 형식 검사 통과.
- 기존 PostgreSQL runner는 Docker Desktop Linux 엔진 파이프 부재로 시작하지 못했다. Docker Desktop 숨김 시작을 요청했지만 엔진 연결이 복구되지 않았다. 새 DB 통과 결과를 주장하지 않는다. 이번 변경은 DB 접근·migration·HTTP 경로를 추가/수정하지 않았다.

## 범위와 다음 항목

이것은 R0의 평가 **산술 기반** 완료이며 R0 전체·CP-05·실제 v2 평가 실행·운영 승격 완료가 아니다. 함수는 입력 truth의 정확성이나 사전등록 시점/동일 snapshot을 증명하지 않는다. 실제 runtime 결과를 True/False/None으로 변환하는 하네스와 manifest 동결이 다음 연결 작업이다.

다음은 계획 항목 2의 C0 fixture 기반 E0 결과·정답·버전 동결이다. 이후 stale 재검색/저장 경합과 M2/M3→R1~R5를 순차 진행한다. 적용 범위 4상태와 COMMON/축 확인 출처는 공동 계약에 합류해야 하며, null이나 미확정 값을 자동 승인으로 바꾸지 않는다. 이번 작업에서 commit/push·운영 배포·유료 모델 호출은 수행하지 않았다.
