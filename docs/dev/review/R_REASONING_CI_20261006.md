# R 복합 질문 보완 — 통합 검증 추가 기록

[구현 기록](R_REASONING_IMPROVEMENTS_20261006.md) 이후 PR #43에서 확인한 결과다.

- 최초 변경 `559534f`: [CI 37435832626](https://github.com/2026-Unithon/AskBuddy/actions/runs/37435832626) 전체 성공.
- 최신 W 추출/UI main `ba58da2` 반영 후 `47c9ffc`: [CI 37436268662](https://github.com/2026-Unithon/AskBuddy/actions/runs/37436268662) 전체 성공. 로컬도 새 main 의존성 설치 후 **1735 passed, 4 xfailed, 131 subtests passed**.
- PostgreSQL 전체 schema 재구축과 실제 API 호출을 수행했다. 새 대화 이력 조회, 다른 매장/회원/세션의 404, 동일 문맥의 동시 요청 중 1개만 저장, stale 요청 receipt 없음, 기존 응답 replay, 일반 의미 제안에 과거 사용자 원문 전달 검사가 통과했다.
- LLM/임베딩 응답은 합성으로 대체했다. API·DB 통합 통과를 실제 모델 정확도나 추론 품질로 보고하지 않는다. 로컬 Docker는 여전히 실행되지 않으며 PostgreSQL 검증은 CI 환경에서 수행했다.
- 최종 점검에서 새 `STALE_DIALOGUE` 코드의 공유 오류 표 등록이 빠진 것을 발견해 Literal/HTTP·retryable 표와 3개 schema export에 추가했다. 이 추가는 409/retryable=true 오류 계약이며 AnswerPlan·ChatResponse·snapshot·DB schema는 그대로다. 오류 계약을 포함한 62개 선택 테스트도 통과했다.

새 일반 의미 기능은 기본 OFF다. 운영 질문 24발화의 기본 경로 재실행은 CLARIFY 14 / ESCALATE 10 / 실행 오류 0, 기대 행동 일치 1/24로 이전과 같다. 이는 독립 입력 진단이며 신규 의미 경로의 실제 세션 품질은 아직 측정하지 않았다. 운영 활성화에는 버전에 맞는 평가·승인 설정이 필요하다.
