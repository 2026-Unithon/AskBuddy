# R 점주 답변 통합 — 2026-10-13

기준: `w/kakao-auth`, HEAD `770659b` 및 이전 pull에서 보존한 로컬 R 변경. [실행 계획](../plan/RW_NEXT_EXECUTION_20261012.md)의 P0/P1, 첨부 IMG-R3/R4 일부에 해당한다. P2~P5나 실자료 품질 인수 완료 기록은 아니다.

## 변경

- `/owner/questions`는 v1/v2 질문을 ID별로 보여 주고 동일 상세 화면으로 이동한다. 같은 문장도 다른 문맥/질문 ID면 합치지 않는다. 서버 WAITING 필터와 페이지 단위 조회로 예전 답변 뒤의 대기 질문도 조회한다. 이전 Buddy 응답 이력은 전체 이력에 유지한다.
- 기존 `?question_id=` 알림 링크도 상세로 이동한다. 상세 API는 v1 질문·발생 이력·과거 원문을 읽는다. 기존 행의 `contract_version`, 과거 원문, 카드 이력을 일괄 이관/수정하지 않는다.
- 두 답변 API 모두 `submit_owner_answer`를 사용한다. 원문 저장·전달·outbox가 하나의 트랜잭션이다. v1 수신자는 해당 질문의 발생 이력과 원래 질문자이며, 기존 v1 규약대로 최근 이전 대화 세션에 전달한다. 다른 질문을 문장만으로 묶지 않고 탈퇴자는 제외한다.
- v1 기존 답변은 별도 `legacy_answers`로 보존한다. 새 처리기의 revision은 1부터 시작한다(`expected_revision=0`). v1 호환 POST는 질문 ID+본문 해시 기반 멱등 키와 revision 0을 쓰며, 수정은 상세의 v2 API에서 최신 revision으로 제출한다. 같은 키/다른 본문, 오래된 revision은 거절한다.
- 제품 v1 답변 라우트의 `build_knowledge_plan` 호출을 제거했다. `knowledge_loop` 모듈 자체는 기존 평가/검사에서 사용하므로 삭제하지 않았다. 답변 접수는 `PENDING`이며 지식 공개 성공으로 표현하지 않는다.
- 원문 도착과 공개 완료 알림은 실제 전달 원장에 연결한다. v1은 `/staff/chat`, v2는 해당 세션으로 이동한다. 자료 처리 알림은 “새 카드” 대신 “자료가 반영된 카드” 수를 안내한다.
- 제안 목록 응답에 `can_approve`, `approval_block_reason`, `affected_cards`를 추가했다. 새 대상/기존 카드 변경/이미 반영/사실 없음/보류/옛 제안을 구분한다. 공개 가능한 사실 카드가 없는 제안에는 공개 버튼을 제공하지 않는다. 여러 카드가 연결됐으면 모든 카드 링크와 함께 현재 초안을 함께 공개한다는 설명을 표시한다. 실제 권한·초안·승인 검사와 공개는 기존 W 서비스가 담당한다.
- 상세 응답의 `proposal_status`로 닫힌 제안을 구분한다. 승인·제안 닫기 후 관련 Query를 무효화한다. 통신 재시도는 요청 ID와 revision을 포함한 최초 본문을 유지하고, 명시적 충돌 갱신 뒤 새 요청을 만든다. 자동 worker 재시도 중에는 상태 조회를 계속한다.

## 검증

검증은 로컬 합성 입력이다. DB는 PostgreSQL 17의 일회용 컨테이너와 새 UUID DB를 사용하며 외부 모델 호출은 합성 대역으로 치환한다. 운영 자료·유료 모델 평가는 실행하지 않는다.

- API 최종 전체 회귀: **2,371 passed, 6 skipped, 4 xfailed, 188 subtests passed**. 기존 Starlette deprecation warning 1개.
- DB: migration 50개 재구축, 기존 W/R 통합 검사와 `verify_r_legacy_owner_flow.py`. 과거 원문 보존, 직원 2명 전달, 동시 재시도 멱등, 다른 동일 문장 질문 유지, 실제 W 사실 신규 공개/기존 카드 검토, 승인 멱등, R 상태, 사실 없음/옛 제안 차단, 수정 충돌, 매장·탈퇴 권한 검사를 포함한다. 추가로 공개 완료 알림·승인 후 직원 재질문·제안 닫기 표시를 검사한다.
- 웹: 최종 `pnpm check` **통과**(lint·TypeScript·build). Edge headless 합성 API 검증과 구분하며 웹 단위 테스트 러너 통과라고 표현하지 않는다.
- 브라우저: **8개 시나리오 그룹 통과**, 390×844/360×800. 같은 문장 질문 분리, 실패 입력 보존·동일 요청 재시도, 새로고침 후 상태, 검토 제안별 버튼, 과거 링크, 제안 닫힘, 빈 상태/오류/재시도, 로딩 및 접근 불가 상태. 실제 API/Push 연결 검증과 구분한다.
- DB 첫 전체 실행은 migration **50개**와 W/R 시나리오 전체 통과. 재질문 검사를 추가한 후의 전체 실행은 온도 없는 레시피를 ANSWER로 기대한 합성 검사에서 실패했다. 실제 결과는 `UNVERIFIED_VARIANT_SCOPE`로 이관하는 기존 안전 동작이다. 이 차단을 음성 회귀로 보존하고, 별도의 HOT 사실→공개→직원 재질문→ANSWER·인용 시나리오를 추가했다. 이후 **새 UUID DB에서 최종 P1 22개 검사 통과**. 수정 뒤 전체 DB suite를 다시 실행한 결과로 합산하지 않는다.
- 저장소 `store-isolation-check`: R 파일 38개에서 위반 없음. `web-async-state-check`: 변경 화면에 직접 fetch/useEffect 폴링·서버 응답 로컬 저장·lint 억제 없음, Query의 매장/사용자/필터 키와 mutation 후 무효화 확인. `ui-state-walkthrough`: 위 브라우저 검사와 모바일 스크린샷 확인.

실행 로그·모바일 화면·브라우저 검증 스크립트: [보존 디렉터리](../../../output/r-owner-flow-20261013). API/DB 검증은 `api/scripts/verify_r_schema_rebuild.py`가 새 P1 시나리오를 포함하므로 이후 CI에서도 실행한다.

## 운영 기록과 남은 범위

[Deploy API 38102036997](https://github.com/2026-Unithon/AskBuddy/actions/runs/38102036997): 기준 `770659b`, 2026-10-11 10:32 KST에 운영 DB 백업·migration·서버 배포·health 단계 성공. 현재 운영 서버와 DB를 직접 읽어 대조한 결과는 아니다. 이번 변경은 배포하지 않았다.

다음은 P2: 실제 W 출력 전체 소비 검토, OWNER_TEXT 점주 답변/직접 입력 구분, 과거 인용·수정·삭제와 초기화 후 잔여 상태. P3 평가 fixture 전환과 RAW 호환 정리, P4 실제 실패 개선, W 후속·운영 인수는 별도다. 이 작업에서 공통 RAW enum이나 과거 migration을 삭제/변경하지 않았다.
