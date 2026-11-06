# R Gemini 보완 후 실제 호출 재평가 — 요청 거절로 중단

2026-10-06 사용자 `정리하고 진행` 요청에 따라 별도 1회 진단을 실행했다. 이전 선택과 같은 최대 10,000원, 기존 12개 시나리오/24턴, 자동 재시도 없음이다. **실제 generateContent 요청 1회가 Google 400 INVALID_ARGUMENT로 거절되어 답변 품질은 측정하지 못했다.** 이전 결과를 덮어쓰거나 실패를 분모에서 제외하지 않았다.

## 준비와 실제 실행

- 평가 러너: 현재 코드/source hash·질문 hash·thinking low를 계획에 고정하고, 연속 API 오류 3회에 중단한다. 공급자 usage가 미확인이면 기존 영속 예산 장치가 즉시 후속 공급자 호출을 막는다.
- 보고서: 완전한 답변, 필요한 재질문, 적절한 점주 전달, 불완전/오답, 불필요한 재질문, 부적절한 전달, API 오류, 미판정, 미실행을 구분한다. 필요한 재질문은 적절한 대응이지만 마지막 질문까지 해결되지 않으면 완결로 세지 않는다.
- 고정 질문의 요구를 만족하지 못하는 RAW 계산·임의 사건 선택도 분모에서 제외하지 않는다. 규칙 원문 나열만으로 질문의 구체적 판단/계산을 해결했다고 세지 않는다.
- 격리 PostgreSQL 17, migration 41개, 합성 승인 RAW 카드 9개와 고정 1536차원 벡터. 운영 DB·플래그 변경 없음. W 실제 출력/실제 임베딩 평가 아님.
- 평가 전 무과금 회귀: 러너/분모/결과 hash 검증과 실제 모델 계약 테스트 37개 통과. 이는 Google 서비스의 실제 요청 수락을 보장하지 않는다.

## 결과

| 항목 | 관찰 |
|---|---|
| 모델 요청 | gemini-3.6-flash / low / native response_json_schema |
| 원문 조회 대조군 | 3/3 통과, 비채점 |
| 직원 질문 API 시도 | 3/24 |
| 실제 countTokens | 1회 성공 |
| 실제 generateContent | 1회, 400 INVALID_ARGUMENT |
| 후속 모델 호출 | 0회. O02/O03은 EVALUATION_BUDGET_DENIED |
| 미실행 | 21/24 |
| 최종 정상 답변 / 검증 호출 | 0 / 0 |
| 답변 정확도·대화 맥락·인용 정확도 | 측정 불가. 모델 오답 24개로 집계하지 않음 |
| usage 및 청구 비용 | 응답 usage 없음, 미확인 1회. 0원으로 단정하지 않음 |
| 보수적 최대 비용 예약 | 108원 × 1회. 청구액 아님 |
| 예산 상태 | halted=true, reservation UNKNOWN |

400 응답 본문은 `Request contains an invalid argument.`만 제공한다. 신규 구조화 출력 또는 생성 설정의 호환성 문제를 우선 의심하지만 **어느 필드가 원인인지는 확정하지 못했다**. countTokens 성공은 생성 설정을 검사하지 않는다. SDK MockTransport 검증은 직렬화만 검사하며 서비스 수락 검증을 대신하지 않는다.

공식 문서는 구조화 출력의 지원 범위와 큰/깊은 스키마의 거절 가능성을 설명하고 low 추론 수준을 해당 모델에서 지원한다고 명시한다. 따라서 낮은 추론 설정 자체가 원인이라고 단정하거나 전체 Pydantic 계약을 무조건 완화하지 않는다.

- [Google 구조화 출력](https://ai.google.dev/gemini-api/docs/structured-output)
- [Google 추론 설정](https://ai.google.dev/gemini-api/docs/thinking)
- [Google 공식 요금](https://ai.google.dev/gemini-api/docs/pricing): 당시 Standard 입력 $0.75/M, 출력·추론 $3.75/M. 이번에는 usage가 없어 실제 합계 산출 불가.

## 후속 순서

1. 기존 중단 캠페인은 재개/재사용하지 않는다. 미확인 비용을 0으로 정산하거나 DB를 바꿔 예산 중단을 우회하지 않는다.
2. 후속 진단은 최소 JSON schema만 있는 요청 → low 설정 추가 → 실제 제안 schema → 검증 schema 순서로 변수 하나씩 분리해 서비스 수락을 확인해야 한다. 각 호출과 실패의 비용/상한을 별도 새 계획에 포함한다.
3. 거절 원인을 확인해 모델 전용 전송 계약만 수정하고 서버의 승인 참조·조건·확정 문맥 검증을 유지한다.
4. 서비스 수락 후에 기존 24턴을 같은 고정 분모로 재평가한다. 현재 5초 이내 수치는 빠른 오류/예산 차단의 시간이며 정상 답변 속도 개선 근거가 아니다.

## 근거

- [새 평가 계획](../../../output/r-operations-challenge-20261006/gemini-live-plan-02.json)
- [공유 HTML](../../../output/r-operations-challenge-20261006/gemini-live-02/AskBuddy-Gemini-live-evaluation.html)
- [실행 결과](../../../output/r-operations-challenge-20261006/gemini-live-02/run.json), [요약](../../../output/r-operations-challenge-20261006/gemini-live-02/live-summary.json)
- [출력에 결속된 판정](../../../output/r-operations-challenge-20261006/gemini-live-02/review.json), [실행된 schema](../../../output/r-operations-challenge-20261006/gemini-live-02/evaluated-wire-schemas.json)
- sdk-events.jsonl: 실제 요청 거절 및 countTokens 기록. provider-events.jsonl: 로컬 어댑터 3회 중 2회가 예산에서 차단된 근거. usage.json 및 budget-reservations.json: 영속 계측.
- 실행 결과 SHA256: `9471419b58de377c6cbca0028f07aa9e5848e722ea3cf5206a29ece0bd4cb80d`.

원시 실행·이전 보고서는 변경하지 않았다. 이번 보고서의 후처리는 비용 미확인 표시를 보완했으므로 평가 전 계획에 기록한 보고서 코드 hash와 최종 보고서 코드 hash는 다르며, 모델 실행 코드·질문·raw 출력은 그대로다.
