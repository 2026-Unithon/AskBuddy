# CP-00B R 첫 항목: 답변 호출 계측 adapter

> 2026-09-15 후속: 제품 채팅·평가 API의 호출자 연결도 구현했다. 아래 2026-09-14 기록은 adapter 단계의 이력이며, 최신 범위는 문서 끝의 후속 인수를 따른다.

2026-09-14. 이번 범위는 `compose_grounded_answer`의 공통 usage 원장 접점이다.
근거: C0 원가 계획 §3·§4.1·§5·§7의 R answer 담당. embed/answer/metrics 사이에 별도 선행 순서는 없으므로 기존 비동기 sink와 직접 연결할 수 있는 answer부터 구현한다.

## 구현과 목적

- 기존 도메인 반환값을 유지하고 keyword-only trusted `UsageContext`/`UsageSink`를 받는다. context/sink 중 하나만 있거나 ANSWER가 아닌 stage, 명시적 NullSink는 거절한다.
- 공통 recorder가 STARTED를 기록한 뒤 공급자를 호출한다. 시작 실패는 `AnswerUsageStartError`로 전달하며 생성 실패 폴백으로 숨기지 않는다.
- SDK 재시도 횟수를 1로 제한한다. 호출자가 다음 실제 시도를 실행할 때 동일 logical_call_id의 attempt_no를 증가시켜야 한다. 이 adapter는 공급자를 재시도하지 않는다.
- 응답 usage를 파싱 전에 관측한다. 파싱 실패는 FAILED receipt와 관측 usage를 남기고 기존 폴백 반환을 유지한다. timeout은 FAILED/UNKNOWN이다.
- 공급자 usage 원형, 보고 모델/응답 ID, 실제 prompt hash·입력 bytes를 기록한다. 질문·카드·응답 본문은 원장에 복제하지 않는다.
- 누락은 null, 실제 0은 0이다. 추가 billable 필드의 과금 포함 관계가 미확정이면 원형을 남기고 PARTIAL로 표시한다. total과 부분 token을 더하거나 캐시 token을 이중 합산하지 않는다.
- 공통 recorder의 취소 처리도 보강했다. CancelledError가 SUCCEEDED receipt로 확정되지 않고 FAILED로 기록되며 취소 자체는 다시 전파된다.
- 최종 저장 실패는 공급자 재호출을 유발하지 않는다. 실제 저장 실패가 남으면 STARTED/UNKNOWN 상태이며 전체 비용 통과 근거로 사용할 수 없다.

## 인수와 범위

API 전체 334 tests / 66 subtests 통과. 정상 매장·평가 run 귀속, 미호출, 0/누락/추가 usage, 파싱 오류, timeout, 취소, 시작 저장 실패, 확정 저장 실패, 잘못된 context, DB sink 연결 해제 순서를 검증했다. DB sink는 fake pool로 호출 전 연결 반환과 기존 SQL adapter 연결을 검사했다. 실제 DB commit·경합·불변 제약 인수를 대신하지 않는다.

이 항목의 완료는 **호출 함수의 명시적 계측 adapter 완료**다. 아직 제품 router와 평가 runner가 context/sink를 전달하지 않으므로 현재 모든 실제 답변이 durable 원장에 저장된다고 주장하지 않는다. 인자를 생략하는 기존 경로는 호환을 위해 유지한다.

다음 항목은 R 호출자의 연결 수명을 정리하고 trusted 매장·질문/운영·평가 식별자와 DbUsageSink를 주입하는 작업이다. 기존 router/runner는 DB connection을 받은 상태에서 모델을 호출하므로 인자만 추가하면 원가 계획의 '외부 호출 동안 DB connection을 보유하지 않는다'를 어긴다. 이에 연결 획득/반환 범위를 함께 고친 후 실제 DB 인수를 수행해야 한다. 이어 embed 단일 진입점 계측, runner/metrics 원장 집계, CP-00C 운영 report 순으로 진행한다.

공통 W 저장 계층의 제한된 finalize 재시도와 tenant-scoped 확정 동작도 다음 연결 인수에서 확인·보강해야 한다. 이번에는 그 저장 계층의 완료를 선언하지 않는다. 실제 모델·요율·월 운영비 승격, R3 의미 판정 및 chat v2는 범위 밖이며 기존 C0 선행 조건을 유지한다.

## 2026-09-15 후속: 호출자 연결과 DB 연결 수명

- `/learn/chat`의 요청 전체 Db 의존성을 제거했다. JWT 검증 후 짧은 pool 획득으로 현재 회원·매장을 확인하고 반환한다. 검색/답변 후에는 다시 획득해 회원 자격과 member ID를 재확인하고 기존 대화·인용·pending 트랜잭션을 수행한다.
- `retrieve_question`은 기존 connection 호출 호환과 pool 호출을 지원한다. pool 경로에서는 임베딩 생성이 끝난 후 검색 SQL 동안만 연결을 획득한다. 검색 임계값·승인 조건은 유지한다.
- 채팅 답변에는 JWT로 확인한 store, OPERATING/PRODUCT, 서버 발급 operation ID와 ANSWER 호출 ID 및 DbUsageSink를 전달한다. 아직 없는 pending question ID를 지어내지 않는다. 이 operation ID는 v2의 영속 request/message 연결 완료를 뜻하지 않는다.
- `/team/evaluations`는 준비 조회/실행 생성, 결과·종료 상태의 원자 저장, 결과 조회에서만 연결을 획득한다. 문항 실행 동안은 pool을 runner에 전달하고 OPERATING/EVALUATION, run ID와 case별 호출 ID를 계측에 결속한다.
- 원장 시작 실패는 채팅에서 503 `USAGE_UNAVAILABLE`/retryable 오류이며 pending을 만들지 않는다. 평가에서는 ERROR와 답변 NOT_CALLED로 기록한다.
- 공통 finalize는 store·logical_call_id·attempt_no·STARTED 상태를 모두 한정한다. DB 저장만 최대 2회, 회당 0.2초 timeout으로 제한한다. 이미 확정된 행은 수정하지 않으며 모델을 다시 호출하지 않는다. 최종 DB 실패는 기존 STARTED/UNKNOWN으로 남는다.

검증: 전체 342 tests / 66 subtests 통과, 기존 의존성 deprecation warning 1건. 실제 FastAPI 채팅 JWT 경로에서 401/403, 타 매장 요청의 조회 귀속, 공급자 호출 중 연결 0개, 외부 호출 중 회원 탈퇴 후 저장 차단, 시작 실패 시 미저장을 확인했다. 검색의 임베딩 전후 연결 수명, 평가 API→runner의 run/case 귀속, finalize의 매장 한정/제한 재시도를 fake pool로 검증했다. `git diff --check` 통과.

정적 검사: 변경 파일 5개에서 기존 `_record_pending_occurrence`의 store_id 인자 누락 1건이 남는다. HEAD에도 동일한 선언이 있음을 확인했으며 이번 변경의 신규 위반은 아니다. 이 helper의 독립 매장 방어는 후속 pending 경계 검토 대상으로 남긴다. 위반 0건이라고 보고하지 않는다.

당시 실제 DB 인수는 Docker 엔진 미가동으로 수행하지 못했다. 사용자 Docker 시작 후 아래의 격리 DB 검증을 추가했다. 운영 DB를 대신 사용하지 않았다.

계획 대조: CP-00B의 기존 반환/API 호환·호출 전 durable 기록·공급자 호출 중 DB 연결 미보유 원칙에 맞춘 변경이다. legacy connection 기반 다른 소비자/스크립트까지 연결 수명이 개선된 것은 아니다. 임베딩 원장 계측, runner/metrics의 공통 원장 집계, 추가 usage 요율 해석은 다음 항목이며 CP-00B 전체 및 D21 비용 인수는 여전히 미완료다.

## Docker 시작 후 실제 원장 DB 검증

2026-09-15, `scripts/verify_r_answer_usage.py`: **14/14 PASS**, PostgreSQL 17.10.

실행 중인 AskBuddy DB가 없어 로컬에 있던 postgres:17-alpine 이미지로 일회용 DB를 만들었다. `stores`와 `extraction_runs`는 FK/ALTER 대상 최소 fixture이며, MC0 migration 원문 전체와 실제 repository/DbUsageSink/답변 함수를 사용했다. 외부 모델 응답만 fake다. 기존 컨테이너/데이터와 운영 DB는 변경하지 않았다.

확인한 것:

- STARTED가 공급자 호출 전에 별도 DB 연결에 보인다: 실제 commit 확인.
- 공급자 호출 동안 크기 1인 pool 연결이 반환돼 있다.
- 토큰·EVALUATION·run 귀속이 저장된다. 모르는 요율은 총액 null이다.
- 같은 시도의 재시작이 차단되고, 동일 호출 키는 매장별로 독립된다.
- 매장 B의 finalize로 매장 A 행이 바뀌지 않는다.
- 동시에 요청한 finalize가 하나의 행으로 유지된다(크기 1 pool의 직렬 SQL 처리).
- 확정 행의 직접 UPDATE/DELETE를 실제 DB trigger가 거절한다.
- 파싱 오류의 사용량 보존, 공급자 timeout/취소의 FAILED 기록, 실제 0과 미관측 null 구분.
- 실제 row lock을 걸어 finalize 재시도를 모두 실패시키면 제한 시간 내 종료하고 STARTED/UNKNOWN이 남는다.

한계: 이것은 실제 **원장 저장 계층 인수**다. 프로젝트 정본 PostgreSQL 15/pgvector의 전체 migration 재구축, 실제 채팅 테이블 저장·publication CAS와 원장 사이의 종단 인수를 대체하지 않는다. 그 범위는 여전히 별도다. 검증용 컨테이너는 실행 후 제거했다.
