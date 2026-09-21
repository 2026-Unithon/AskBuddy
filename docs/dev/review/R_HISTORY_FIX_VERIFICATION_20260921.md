# R 이력·대기 갱신 수정 검증 — 2026-09-21

## 완료 범위

[R 우선 검토](R_ONLY_REVIEW_20260921.md)의 R-F01, R-F02, R-V01을 수정했다. 제품 코드 기준 `7f0e461` 이후의 로컬 변경이며 W 추출/발행/worker 제품 코드는 수정하지 않았다. 상세 인터페이스와 적용 순서는 [R 이력 조회 계약](../plan/R_HISTORY_READ_CONTRACT.md)을 따른다.

- **R-F01:** 새 UI는 `latest=true`로 최신 메시지를 먼저 받고 `before`로 과거를 추가 조회한다. 서버는 limit+1로 실제 다음 페이지를 판정한다. 새 답변이 이전 페이지에 가려지지 않고, 과거 기록이 남아 있어도 최신 CLARIFY/SAFE_ROUTE 선택을 표시한다. 기존 after 조회도 유지했다.
- **R-F02:** 서버가 매장/회원/세션 전체의 미해결 질문과 최신 점주 답변의 진행 상태를 계산해 `has_pending_updates`로 반환한다. UI는 이 값으로 5초 갱신을 시작/종료한다. 뒤 질문이 끝나도 앞 질문의 점주 답변을 기다리고, 모든 작업 완료/종료 시 불필요한 갱신을 멈춘다.
- **동시성:** history의 메시지와 요약을 repeatable-read transaction으로 읽는다. 메시지 조회 직후 별도 DB 연결에서 공개 완료를 커밋해도 옛 메시지+새 종료 요약이 섞이지 않음을 검증했다.
- **R-V01:** 브라우저의 오류 선택자를 R 채팅 컨테이너로 한정하여 Next 내부 route announcer와 충돌하지 않게 했다.
- **CI:** 기존 DB/API runner에 `verify_r_history.py`, browser job에 `verify_r_history_ui.cjs`를 연결했다. 원격 CI 실행 결과가 아니라 로컬에서 동일 실행 경로를 검증한 결과다.

## 실행 결과

| 검사 | 결과 |
|---|---|
| 전체 API 단위 | **913 passed, 4 xfailed, 119 subtests passed** |
| 매장 격리 AST | learn/reg/team **76개 파일, 위반 0건** |
| 프론트 `pnpm check` | lint `--max-warnings 0`, TypeScript, production build 모두 통과 |
| 기존 브라우저 | **40 checks 통과**. 원본 검증 파일의 선택자를 고친 정식 실행 |
| 신규 이력 브라우저 | **36 checks 통과** |
| 격리 PostgreSQL 17.11 | **29개 migration 재구축 및 전체 R handoff runner 통과** |
| v2 HTTP/DB | **157 checks 통과**. 기존 117개에서 이력/상태 관련 40개 추가 |
| 인접 DB 회귀 | 색인 44, 답변 저장 20, 점주 전달/완료 53, metadata 보존 13, 문맥/stale 21, reranker usage 13 checks 통과 |
| diff 공백 검사 | `git diff --check` 통과 |

단위의 4 xfailed는 기존에 공개 신규 질문 경로와 분리한 legacy 의미 취약성이다. 통과로 더하지 않는다. Starlette/anyio deprecation warning 1개는 기존 경고다.

DB는 runner가 생성·정리하는 일회용 Docker 컨테이너와 새 UUID DB만 사용했다. 운영 `.env` DB와 실제 모델은 사용하지 않았다. 로컬 비공개 실행 로그는 `api/tmp/r-history-db-final-20260921.log`다.

브라우저는 새 production build, Edge headless/Playwright 1.62.1 및 합성 API로 실행했다. 기존 검사에서 390/360px 레이아웃·오류/재시도·알림·권한/비활성 상태를 검사했고, 신규 검사는 390×844에서 이력과 상태 전환을 확인했다. 실제 W worker나 운영 Push 종단을 검증한 것은 아니다.

## 고정한 반례

- DB의 99/100/101/200/201개 메시지: 최신 100개, 정확한 cursor, 과거 기록 누락/중복 없음, 기존 오름차순 after 호환.
- 잘못된 cursor/방향·limit 및 타 회원 history/요약 접근 차단.
- 브라우저의 99/100/101/200개 메시지: 최신 명확화, 질문 성공 직후 답변, 안전 확인과 새로고침, 과거 페이지를 펼친 뒤 재질문/갱신.
- 화면 밖 앞 페이지의 ESCALATE 뒤에 완료 답변이 있어도 점주 답변이 자동 표시됨.
- 복수 pending 중 하나만 해결되면 갱신 유지, 전부 해결되면 갱신 종료.
- PENDING/REVIEW, 재시도 가능한 FAILED, 종료된 FAILED, LINKED/PUBLISHED와 과거 revision의 남은 PENDING 구분.
- 별도 연결의 공개 완료가 history 조회 중 커밋되는 경우 동일 판의 메시지/요약 반환. 다음 조회에서는 완료를 반영하고 갱신 종료.

## 적용 및 남은 외부 의존성

API를 먼저 반영하고 Web을 반영해야 한다. 신규 migration은 없다. 일반 의미 경로를 별도 활성화한 환경에서는 기존 코드 hash 인수 절차도 확인한다. 이번 작업에서 플래그·release hash를 자동 승격하지 않았다.

이번에 확인한 R 단독 결함 3건의 구현·회귀·CI 연결은 완료했다. W 실제 생산/발행/worker 연결은 W와 공동 인수할 항목으로 남는다. 사람 정답·외부 AI 판정 인정 방식·유료 예산은 기존 회의 대기를 유지하고, Railway 로그/접근/보존은 실제 환경 증거 확인이 필요하다.

이번 기록은 로컬 구현·검증 완료 기록이다. 커밋/push, PR 병합, 운영 배포를 완료한 기록이 아니다.
