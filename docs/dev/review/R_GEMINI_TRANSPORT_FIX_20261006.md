# Gemini 400 요청 거절 해결 및 남은 답변 계약 문제

2026-10-06 사용자 `확인해서 해결해보자` 요청에 따라 기존 중단 캠페인을 보존하고 별도 전송 호환성 진단을 수행했다. **기존 GeneralProposal schema의 중첩 `maxItems`를 모델 전송 schema에서 제거하자 Google의 400 거절이 해소됐다.** 실제 채팅 API도 생성 응답을 받았으나 이번 출력은 잘못된 계산 참조 때문에 서버가 거절했다. 통신 해결과 최종 답변 성공을 구분한다.

## 실제 원인 분리

동일한 합성 질문·후보·모델 `gemini-3.6-flash`, `low`, temperature 0, 출력 상한 4,000으로 아래 순서로 요청했다. 자동 재시도는 없다.

| 진단 | 변경 | 실제 결과 |
|---|---|---|
| minimal-low | 최소 `{ok:boolean}` schema | STOP, 정상 JSON |
| original-low | 이전에 거절된 전체 schema | 400 INVALID_ARGUMENT 재현 |
| supported-low | default/문자열 길이/pattern 제거, const→enum | 400 재현 |
| unbounded-low | 위 schema에서 배열·수치 범위 제약 제거 | STOP, 정상 JSON |
| no-maxitems-low | **원래 schema에서 maxItems만 제거** | STOP, 정상 JSON |
| verification-low | 수정된 Verification schema로 실제 제안 검증 | STOP, 정상 검증 JSON |

따라서 단순 키/모델/low 설정 문제가 아니라 **해당 전체 schema의 배열 상한 구성이 요청 거절을 유발하는 것**으로 좁혔다. 특정 maxItems 하나 또는 Google 내부 decoder 구현까지 확인한 것은 아니다. 모든 maxItems가 일반적으로 미지원이라는 주장도 아니다. [공식 API](https://ai.google.dev/api/generate-content)는 maxItems 지원을 명시하고, [구조화 출력 문서](https://ai.google.dev/gemini-api/docs/structured-output)는 큰/깊은 schema 거절 가능성을 설명한다.

## 수정

1. `general_wire.response_schema`에서 모델 전송 schema에만 `maxItems`를 제거한다. Pydantic/서버의 배열 길이, 고정 tuple 길이, 승인 참조, 숫자 연산, 문맥 검증은 유지한다. context ID도 계속 서버가 발급한다.
2. 모델용 question_quote 설명에 사용자 원문의 연속 문자열을 그대로 복사하라는 규칙을 명시한다. 후보 제목·동의어를 사용자 인용으로 인정하지 않는다.
3. 실제 성공 응답은 `thoughts_token_count`를 생략하기도 한다. **보고된 total = prompt + visible이고 tool 토큰이 없을 때에만** 생략된 추론 토큰을 0으로 산정한다. 전체 usage 누락·합계 불일치·음수는 여전히 미확인이다. 원장 raw_usage는 덮어쓰지 않는다.
4. 비용 분석기도 같은 토큰 정합성 함수를 사용한다. 최소 요청의 과도한 중단은 성공 응답 원본의 합계로 정정했으며 예약 횟수/금액은 환불하지 않았다. 기존 live-02의 400 미확인 비용은 정정하거나 0원 처리하지 않았다.

## 실제 채팅 API 확인과 한계

이전 24턴 중 원래 O01 질문 하나만 별도 계약 확인으로 실행했다. 실제 ASGI/PG17, migration 41개와 합성 RAW 카드 9개, 원문 조회 대조군 3/3 통과.

- Google 실제 생성: 1회, STOP, 400 없음. 토큰 usage 정합성 통과·예산 reservation OBSERVED.
- 모델이 `calculations=[{operator:ADD,fact_ids:[1]}]`를 만들었다. RAW 자료에는 이 계산을 뒷받침하는 typed 수량 fact가 없고 ADD에는 피연산자 2개가 필요하므로 엄격한 schema 검사에서 거절됐다. `GENERAL_INVALID_PROPOSAL` 1건.
- 제안에 slots도 누락됐다. 계산만 제거해도 이 출력이 정답으로 승격되는 것은 아니다.
- 다른 진단 출력에서는 질문에 없는 `환불`을 사용자 인용으로 넣어 서버가 거절했다. 두 실제 실패 출력을 실패 회귀 fixture로 고정했다. 잘못된 모델 출력을 수리하거나 정답으로 세지 않았다.
- unbounded-low 출력은 로컬 참조/해석/렌더 검사를 통과했고, 별도 검증 응답도 request hash/선택 RAW 참조와 일치했다. 이것은 특정 응답의 계약 검증이며 일반 답변 정확도나 채팅 API 성공률이 아니다.

**현재 해결:** 공급자 400 호환성 오류, 생략된 0 추론 토큰의 잘못된 미확인 처리.

**미해결:** 모델이 RAW 질문에 불필요한 계산을 만들거나 필수 슬롯을 생략하는 출력 계약 신뢰성. 다음에는 후보가 RAW뿐인 경우 모델에 허용할 연산 표현과 필수 슬롯 표현을 구체화하고, typed 계산 지원을 유지하면서 실제 원래 24턴을 다시 검증해야 한다. 운영 플래그는 계속 OFF, 5초 운영 지연·W 실제 출력 인수·모델 정확도는 미측정이다.

## 비용과 검증

- 이번 총 생성 요청 **7회**: 전송 진단 6 + API 계약 확인 1. 총 허용 상한 8회/864원 중 사용 예약액 **756원**. 예약은 청구액이 아니다.
- usage가 확인된 5회의 토큰 기준 합계 **$0.01865625**, 1,500원/USD 가정 시 **약 28원**. HTTP400 두 요청은 usage 미확인으로 별도 남는다. 따라서 28원을 전체 청구액이라고 부르지 않는다. [공식 Standard 요율](https://ai.google.dev/gemini-api/docs/pricing): 입력 $0.75/M, 출력·추론 $3.75/M.
- 이전 live-02의 1회 미확인 요청/108원 예약은 별도 보존. 두 작업을 합쳐 실제 예약한 상한은 864원이다.
- 최종 전체 `pytest tests`: **1,781 passed, 4 xfailed, 131 subtests passed**. 기존 Starlette deprecation 경고 1개. 처음 `pytest`를 디렉터리 없이 실행한 수집은 api/tmp의 접근 제한된 임시 의존성까지 수집해 실패했고, 정식 tests 디렉터리로 재실행해 통과했다.
- 실제 잘못된 인용/RAW 연산 거절, 서버 배열/tuple 제한 유지, usage 누락/불일치/음수/전체 합계, SDK 전송 검증 포함.

## 근거

- [호환성 진단](../../../output/r-operations-challenge-20261006/gemini-transport-01/plan.json), 각 `*-request.json`/`*-result.json`, `usage-0.json`, `usage-reconciliation.json`, `closed.json`.
- [실제 API 계약 확인](../../../output/r-operations-challenge-20261006/gemini-contract-smoke-01/run.json), [원인 분석](../../../output/r-operations-challenge-20261006/gemini-contract-smoke-01/diagnostic-analysis.json).
- 테스트 로그 `api/tmp/r-wire-fix-full-02.log`; API 로그 `api/tmp/r-gemini-contract-smoke-01.log`.
- 진단 runner의 native HTTP hook은 설치 SDK가 실제로 선택한 transport에서 실행되지 않았다. 따라서 `*-wire.json` 캡처는 없으며 request JSON은 SDK에 전달한 설정이다. 실제 수락/거절은 SDK 응답 원본 및 DB receipt로 확인한다. 로컬 MockTransport만으로 공급자 수락을 확인했다고 주장하지 않는다.
