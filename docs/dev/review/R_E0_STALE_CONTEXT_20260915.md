# R E0·stale·문맥 저장 후속 구현 검증

기준 HEAD c73549a, 기존 R 반복 안전성 변경 위에 수행. **R 전체 완료 기록이 아니다.** 운영 DB 적용·유료 모델 실행·commit/push는 하지 않았다.

## 구현 범위

1. `api/app/team/baseline.py`와 `scripts/record_r_baseline.py`: W fixture 원본을 바꾸지 않고 승인 assertion/조건/예외/RAW를 고정 후보로 투영해 기존 retrieve/compose 함수를 실행한다. 모델은 호출하지 않는다. `R_E0_FIXTURE_20260915.json`에 37행, 질문 16개, 실행 오류 0개와 원문 입력/정답/소스 hash를 보존했다. 정책 질문 2개는 별도 합성 fixture다. 비질문 계약 사례는 NOT_A_QUESTION으로 남긴다. `semantic_correct=null`, 실제 v2 action=null이므로 정답률/정책 동작 성공을 주장하지 않는다. 고정 score=1은 실제 검색 성능을 측정하지 않는다. 출력 파일은 exclusive create로 기존 동결본을 덮어쓰지 않는다.
2. `api/app/learn/router.py`: stale이면 기존 사용자 요청의 절대 deadline·총 모델 예산을 유지한 채 최대 한 번 재검색한다. 같은 operation 아래 별도 logical call ID로 실제 비용을 중복 누락 없이 귀속한다. 계속 stale·근거 소실·재검색 timeout·바깥 deadline 소진은 retryable STALE_KNOWLEDGE다. 이 분기는 message/pending/알림을 쓰지 않는다. 저장 완료 뒤 lease 정리 timeout으로 성공 응답을 실패로 뒤집지 않는 기존 보강도 유지한다. publication share lock 뒤 card ID 오름차순 share lock으로 검증과 저장을 묶는다. empty/duplicate 후보를 거절한다.
3. `20260917100000_m3_question_context.sql`과 `question_contexts.py`: 기존 session은 v1, 새 v2 session과 서버 UUID 문맥은 store/member/session/version composite FK로 묶는다. session 소유권·계약 변경은 trigger로 막는다. 서버가 제시한 선택지만 확정하고 추정 슬롯은 별도로 저장한다. 공개 판 변경 때 추정은 버리고 사용자 확정 슬롯만 유지한다. TTL은 수락한 사용자 턴에서만 10분 연장한다. 조회/되묻기 출력/잘못된 선택/만료 문맥은 연장하지 않는다. 최대 두 번 되묻기 후 ClarificationLimit을 반환하며 호출자가 UNRESOLVED_CONTEXT ESCALATE를 원자 저장해야 한다. 아직 그 v2 호출자는 구현되지 않았다.
4. 기존 v1의 session 선택/채팅 조회/질문 이력과 pending message 참조에 v1 경계를 추가했다. pending message는 같은 회원 소유도 검사한다. 이 코드 배포에는 새 migration 선적용이 필요하다.
5. `contracts/chat.py`: non-CLARIFY context/빈 slot 필드, non-ESCALATE pending, 중복 citation 행, 중복/빈 선택지를 차단한다. 원문 질문의 앞뒤 공백·줄바꿈을 보존한다. 이는 C0 §5.1~5.2의 누락 검사 보강이며 4상태 적용 범위 계약을 임의 확정한 것은 아니다. 공동 계약 변경이므로 W 검토 대상이다.

## 검증 결과

- 전체 API 단위 회귀: **406 passed, 95 subtests passed**, 기존 Starlette/AnyIO deprecation warning 1개.
- 변경 DB 코드 정적 매장 격리: router/question_contexts/baseline **3개 파일, 위반 0개**. 정적 검사가 실제 DB/API 격리 검증의 대체는 아니다.
- E0 fixture: 37행/질문 16개/실행 오류 0개. 평가 미판정은 유지했다.
- `verify_r_context_stale.py`를 작성해 M3 실제 migration 적용, v1 불변, 문맥 scope FK, 원문 공백, TTL, 최대 2턴, 중복 수락, 별도 연결 경합, publication/card lock 및 매장 독립 시나리오를 기존 일회용 PG15 runner에 추가했다. **이번에는 미실행**이다.
- `verify_r_handoff.ps1` 실행 결과는 DB 생성 단계 실패다. Docker Desktop backend 로그의 sailor-ingest.sock 접근 실패와 엔진 named pipe 부재를 확인했고, Desktop 재시작도 정상 엔진을 복구하지 못했다. 기다리던 재시작 CLI는 중단했다. factory reset/데이터 삭제는 하지 않았다. 기존 다른 날짜의 29/29 DB 성공을 이번 변경의 성공으로 재사용하지 않는다.

재현(저장소 루트, 사용 가능한 Python 및 의존성 필요):

```powershell
./api/scripts/verify_r_handoff.ps1 -Python <python.exe> -IncludeUnitTests
```

새 검증 스크립트는 localhost:55439/usage_verify의 무작위 schema만 사용하고 정리한다. 기존 서비스 DB/.env를 사용하지 않는다. 최소 부모 schema에서 새 migration/서비스를 검사하는 것이며 전체 앱 migration 재구축과 실제 W 공개 서비스 왕복은 추가로 필요하다.

## 엄밀 검토에서 남긴 경계

- M3는 context 첫 단위다. chat request 멱등성, context 수락+message/citation+pending/outbox의 원자 저장, v2 route, owner answer revision은 미완료다. 내부 함수는 transaction을 강제하지만 이것만으로 전체 요청 멱등성·인증을 보장하지 않는다.
- R0의 E0는 oracle 후보 extractive 기계적 재현이고, R2 hybrid/실제 R3 충분성/모델 품질의 기준선이 아니다.
- W prepared manifest 및 원자 색인 pointer 인계는 현재 DTO/DB 서비스만으로 확정되지 않는다. `R_IMPLEMENTATION_PLAN.md`에 필요한 입력과 권장 접점을 명시했다.
- 기존 v1 점주 루프가 knowledge_loop/knowledge_apply를 직접 소유하는 구조를 이번에 R5 완료로 바꾸지 않았다. W command/event 연결이 남아 있다.
- 전체 기능을 미완성 helper나 fake의 통과 개수로 완료 처리하지 않는다. 다음 gate는 새 DB 시나리오 실측과 전체 migration 재구축이다.
