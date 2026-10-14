# RAW 계산·필수 근거 보완과 실제 Gemini 연결 검증

사용자가 승인한 `RAW 계산 제한 → 근거 누락 방지 → 소수 실제 질문 검증`을 수행했다. **최종 3턴에서 실제 API 응답·receipt·대화 저장이 모두 성공했고 2건은 승인 출처 답변을 반환했다.** 정정 후속 질문은 불필요한 업무 선택 재질문으로 돌아갔다. 전체 24턴 품질 평가나 운영 인수 완료는 아니다.

## 구현

- 실제 검색 후보에서 AFFIRM 수량 fact와 지원 단위를 가진 ID만 계산 후보로 제공한다. 없으면 모델 전송 schema에서 `calculations`와 연산 정의를 제거한다. RAW 숫자/카드 ID를 수량 사실로 바꾸지 않는다. typed 수량이 있는 경로의 ADD/SUBTRACT/SCALE 지원과 서버 연산 검사는 보존했다.
- 계산 후보가 없고 모델이 `unsupported_calculation=true`, ESCALATE, unresolved로 명시한 경우, 서버의 고정 `INSUFFICIENT_KNOWLEDGE` 사유로 기존 점주 전달 경로에 연결한다. 계산·parts 동시 제출, ANSWER/CLARIFY 조합, 실제 계산 가능 수량이 있는 후보에서는 해당 표지를 거절한다. 모델의 기술 설명을 직원에게 표시하지 않는다. 이 분기는 답변 검증을 우회해 사실 답변을 생성하지 않으며 별도 감사 상태를 남긴다.
- 상위/부분별 slots와 해석 필드를 모델 schema에서 필수화한다. slots의 question_quote는 현재 질문·저장된 이전 사용자 발화의 정확한 문자열 중 선택한다. 카드 제목이나 동의어는 인용 선택지로 제공하지 않으며 서버의 원문 포함 검사도 유지한다.
- 첫 실제 실행에서 고정 schema_version을 `v1`/`1.0`으로 생성하는 오류를 발견했다. 버전을 모델 출력에서 제외하고 기존 DTO 기본값으로 관리한다. 명시적으로 잘못된 버전을 보낸 경우를 정상으로 고쳐주지 않는다. 공개 DTO의 literal 제약은 그대로다.
- 평가 러너에 답변 receipt별 실제 citation detail GET 검증과 각 호출의 동적 schema hash 기록을 추가했다.

## 실제 실행 — 실패를 포함한 두 단계

동일 Gemini `gemini-3.6-flash`, low, temperature 0, 출력 상한 4,000. 실제 ASGI API·격리 PG17/migration 41개·승인 합성 RAW 카드 9개·고정 임베딩이다. 운영 설정은 변경하지 않았고 W 실제 산출물 평가가 아니다.

| 단계 | 사전 범위 | 실제 생성 | API 결과 | 확인 |
|---|---|---:|---|---|
| 01 | 원래 O01/O02/O03/OD01 6턴 | 6회 | ERROR 5, CLARIFY 1 | 계산 생성·근거 누락 대신 버전 literal 오류 5건 발견. O03은 기존 대상 선택으로 복귀 |
| 02 | O02 + OD01 첫 2턴, 총 3턴 | 6회(제안 3 + 검증 3) | ANSWER 2, CLARIFY 1, ERROR 0 | receipt/history 3/3, 답변 2건의 인용 상세 3개 모두 조회 성공 |

01의 실패를 02로 덮어쓰지 않았다. 02는 수정 후 일부 질문의 연결 진단이며 두 결과를 합쳐 9개 독립 질문의 정확도처럼 표시하지 않는다. OD01의 원래 세 번째 턴은 02에서 실행하지 않았다. 01/02의 원문 조회 대조군은 각각 3/3 통과했다.

### 후속 질문의 실제 한계

1. 사용자: 오늘 매장에서 직접 결제한 18,000원, 영수증 있음, POS 마감 전 환불 방법.
2. 사용자 정정: 직접 결제가 아니라 어제 배달앱 결제였고 금액은 같음.

첫 응답은 정확한 환불 정책과 출처를 전달했다. 두 번째 모델 입력에는 정상 저장된 첫 사용자 발화가 포함됐고, 제안도 구조 검사를 통과했다. 그러나 검증 모델은 `supported=false`를 반환했고 구체적인 unresolved 사유는 비어 있었다. API는 기존 경로의 `환불/오픈/근무/...` 9개 업무 선택으로 되돌아갔다. 이미 환불 맥락과 정정 내용이 있으므로 **필요한 재질문으로 인정하지 않았다.** 이력이 아예 전달되지 않았던 과거 실패와 구분한다.

### 출력 품질의 해석

- O02: 오픈 인증·열쇠·현장 인계의 필수 사실 4개, 승인 카드 출처 2개는 정확하다.
- OD01 첫 턴: 직원 환불 조건과 원거래 확인 규칙·출처가 정확하다.
- 두 답변 모두 승인 RAW 원문을 나열한다. 상황별 적용 결론을 직접 정리하지 않으므로 사전에 정한 엄격한 완결 답변 기준에서는 INCOMPLETE_ANSWER로 잠정 분류했다. 사실 전달 성공을 오답/환각이라고 부르지 않으며, API 성공 3/3을 정답률 100%라고 부르지도 않는다.
- 02의 필요한 재질문 인정 0, 불필요한 재질문 1. 독립 사람 채점·Gemini 단독 추론 정확도·일반 맥락 이해율은 측정하지 않았다.
- unsupported_calculation의 점주 전달 변경은 단위 검증했다. 변경 후 O03을 실제 모델로 다시 실행하지 않아 실제 발생 성공률을 주장하지 않는다.

## 비용·지연·검증

- 처음 정한 총 생성 상한 **12회 / 예약 상한 1,296원** 유지. 01의 6회와 02의 6회를 모두 포함하며 자동 재시도 없음.
- 공급자 usage 기준 01 **$0.03126825**, 02 **$0.02607225**, 합계 **$0.05734050**. $1=1,500원 가정 시 **약 86원**. 이번 12회 usage는 모두 확인됐고 예약 상태 OBSERVED. 과거 진단의 미확인 비용과 별도다.
- [공식 Standard 요율](https://ai.google.dev/gemini-api/docs/pricing) 입력 $0.75/M, 출력·추론 $3.75/M 적용. 청구서 금액이나 실시간 환율이 아니며 W·실제 임베딩·Storage·서버/DB 비용 제외.
- 02의 API 지연 p50 **9.65초**, p95 **11.48초**, 5초 이내 **0/3**. 3개 표본뿐이며 진단은 API 30초/모델 27초로 운영의 5초/3초보다 길게 허용했다. 운영 속도 기준은 통과하지 못했다.
- 전체 Python **1,787 passed / 4 xfailed / 131 subtests passed**. 보고서 변경 후 관련 2개 추가 재실행 통과.
- 격리 PG17의 41개 migration과 R/W 전체 API/DB 통합 검증 통과. 합성 모델 경로이며 실제 Gemini 검증 결과와 분리한다.

## 다음 순서

1. 검증 모델의 거절 사유를 구체적으로 관찰하고, 대상이 명확한 대화 정정을 다시 전체 업무 선택으로 돌리는 fallback을 개선한다. 검증 거절을 무시하거나 강제로 답변으로 승격하지 않는다.
2. 승인 원문 전달과 상황별 결론 제시의 차이를 제품 계약에 맞춰 해결한다. 특히 RAW 카드에서 자유 답변을 허용할지 여부를 무단 변경하지 않는다.
3. 최종 RAW 계산 전달 분기까지 소수 실제 검증 후 기존 24턴 전체를 고정 분모로 재평가한다. 현재 결과로 운영을 활성화하지 않는다.

## 재현 근거

- [01 계획](../../../output/r-operations-challenge-20261006/gemini-raw-capabilities-plan.json), [01 결과](../../../output/r-operations-challenge-20261006/gemini-raw-capabilities-01/run.json)
- [02 계획](../../../output/r-operations-challenge-20261006/gemini-raw-capabilities-followup-plan.json), [02 공유 보고서](../../../output/r-operations-challenge-20261006/gemini-raw-capabilities-02/AskBuddy-Gemini-live-evaluation.html)
- [02 출력 결속 판정](../../../output/r-operations-challenge-20261006/gemini-raw-capabilities-02/review.json), [02 요약](../../../output/r-operations-challenge-20261006/gemini-raw-capabilities-02/live-summary.json)
- 각 폴더 provider-events.jsonl / sdk-events.jsonl / usage.json / budget-reservations.json / run.json의 citation_reads 및 history.
- 테스트 로그: `api/tmp/r-raw-caps-full-02.log`, `api/tmp/r-raw-caps-pg17-01.log`.
