# R v2 실행·점주 전달 구현 검증

기준: c73549a 이후 작업 트리. C0 결정서 §4~6, DEV_TODO R0~R5와 R_IMPLEMENTATION_PLAN을 대조했다. **R 전체 완료 또는 운영 승격 기록이 아니다.** 이전 검증 문서와 동결 E0 결과는 덮어쓰지 않았다.

## 구현한 경로

| 범위 | 산출물 | 검증된 경계 |
|---|---|---|
| M2/R1 | KnowledgeContent, durable index preparation, PREPARING/PREPARED/FAILED/CONSUMED, 공개 transaction의 activate_prepared_index | 같은 요청·다른 본문, 매장/hash/config/version/TTL, 중복 provider 방지, 만료 claim 복구, W publish와 색인 전환 rollback/commit |
| R2 | 실제 PostgreSQL lexical + pgvector 독립 회수, RRF, 한국어 질문 토큰 OR·조사 변형, 승인 사전 manifest | vector 공통 하한 없음, 승인 취소 후보 배제, COMMON/STORE 구분, 공개 웹 출처/수집일/이용 근거, 버전 불변성·매장 격리, 별칭 대상은 사용자 확인 |
| R3 | 명시 슬롯 planner, 수량/단위 대응, 제한된 문맥, 선택형 reranker | 임의 후보 ID·중복·timeout, null 규격·미확인 조건/RAW fail closed. reranker는 순서만 바꾸며 충분성 승인 권한 없음 |
| M3/R4 | v2 session/chat, 승인 renderer, immutable receipt·exact citations, 되묻기 CAS, 현재 공개 재검사 | 5 action·별도 ERROR, 최대 두 번 되묻기, 5초 기한/최대 1회 stale 재검색, 중복 요청과 실패 rollback |
| R4 조회 | 자기 세션 이력, 당시 승인 인용 내용, 조회 시 source availability overlay, access log | 다른 회원 인용/이력 거절, 삭제 원본의 인용 끊김, 당시 본문·version 보존 |
| R5 | 점주 원문 revision·직원 OWNER_ANSWER 이력·앱 알림·outbox 원자 저장 | 원문 공백/줄바꿈 보존, 중복 제출·수정 CAS, 알림 실패 전체 rollback, 다른 문맥 전파 금지 |
| R5 W 인계 | claim_owner_event / heartbeat_owner_event / finish_owner_event | lease 60초, 만료 재시도 attempt 증가, 오래된 worker 차단, superseded 사건 건너뛰기, 지식화 상태 별도 기록 |
| 화면 | /staff/chat/v2, /owner/questions/v2 | 서버 Query 기반 이력 복원·인용 펼치기·되묻기·실패 입력 보존·점주 원문 전달. v1 이력과 별도 세션 |

검색 실행 메타데이터에 planner/normalization/lexical/RRF 버전, index revision, 후보별 lexical/vector/RRF 점수와 rerank 적용 상태를 저장한다. 일반 로그에 질문·점주 원문을 추가하지 않는다. RERANK 공급자 adapter도 usage 원장을 통과하며 기본 설정은 OFF다.

사전 승인은 POST /learn/v2/search-dictionaries의 현재 OWNER 전용 경계다. 같은 내용 hash는 같은 rlex 버전을 재사용한다. W가 다음 승인 snapshot의 glossary_version에 이 버전을 고정해야 활성화된다. 사전 승인만으로 현재 공개판을 바꾸지 않는다. 수량/레시피 문장은 term으로 받지 않는다. 공개 웹 자동 수집이나 외부 레시피 지식화는 이번에 실행하지 않았다.

## 계획과 달라진 구현 선택과 판단

1. 발행 전 데이터에 미래 snapshot ID를 붙이지 않는다. `KnowledgeContent`를 불변 준비 payload로 만들고 기존 PublishedKnowledgeSnapshot의 필드 순서·hash·fixture는 유지했다. W가 승인할 내용을 R durable staging에 넘기는 내부 함수 접점이며, 기존 불완전한 PrepareIndexRequest wire DTO를 준비 완료의 근거로 사용하지 않는다. W 실제 draft/approval CAS를 대신 구현한 것은 아니다.
2. 캐시를 추가하지 않고 매 요청 DB 현재 공개 정본을 조회한다. 따라서 캐시 사건 지연 때문에 오래된 근거를 승인하는 경로는 없다. 캐시를 도입할 때 인증·snapshot/index/version key와 outbox 무효화 인수가 필요하다.
3. R3 첫 runtime은 명시 슬롯만 처리한다. 일반 자연어의 RAW 충분성·복잡한 조건·명시 NOT_APPLICABLE/ALL_APPROVED_VARIANTS 승인 계약이 갖춰지지 않은 사례를 임의로 자동 통과시키지 않는다. 이는 안전성 경계이며 의미 정확도·차단율 개선의 증거가 아니다.
4. 점주 답변 수정은 새 owner_answers.answer_id와 revision/supersedes로 보존한다. 원문 전달과 W PENDING/LINKED/REVIEW/PUBLISHED/FAILED는 별도다. W는 발행 transaction 안에서 finish_owner_event를 호출해야 하며, finish의 stale/lease 오류를 삼키면 안 된다. W가 이 접점을 호출하는 실제 worker/발행 경로는 공동 연결 항목이다.
5. v2 화면은 별도 주소로 추가했다. 기존 사용자 대화를 자동 전환하지 않는다. r_v2_enabled와 r_reranker_enabled는 모두 기본 false이며 이번 검증에서 운영 설정을 켜지 않았다.
6. 새 의존성 설치 환경에서 기존 PageProps 생성 전에 lint가 실패했다. `pnpm check` 앞에 `next typegen`을 두어 기존 화면의 타입 정의도 먼저 생성하게 했다. 기존 PageProps 사용을 삭제하거나 lint를 억제하지 않았다.

## 검증

2026-09-16 최종 API 실행:

- 단위 회귀 **432 passed / 95 subtests**, 기존 Starlette/AnyIO deprecation warning 1개.
- PostgreSQL **17.11**, migration 원문 **25/25** 재구축.
- 실제 DB/API 체크 **153 PASS**: 기존 원장·보안·임베딩·문맥 50 + M2/hybrid/사전 31 + M3 저장 16 + v2 HTTP 35 + 점주 전달/lease 21. 반복된 provider 경계 체크를 포함하므로 153개 독립 사용자 시나리오라는 뜻은 아니다.
- 변경 DB 서비스 7개 및 알림/reranker/사전 3개 매장 격리 정적 검사 위반 0. 기존 Push 전달 상태 UPDATE 세 곳에도 store_id 조건을 보강하고 전체 회귀를 다시 확인했다.
- 프런트 `pnpm check`: typegen/lint/typecheck/build. 브라우저 검증과 별개다.
- `verify_r_ui.cjs`: 실제 Edge, **합성 API**로 12개 체크. 빈 화면 안내, 되묻기 새로고침, 인용 펼치기, 제출 실패 입력 보존·재시도, 점주 원문 전달·직원 새로고침, 390/360px 가로 넘침, JS runtime exception 검사. screenshot은 api/tmp/r-ui에 생성하고 시각 확인했다.

브라우저 12개는 실제 PostgreSQL과 연결한 전체 E2E가 아니다. SQL/HTTP는 별도 실제 DB 테스트다. Gemini/OpenAI 호출은 테스트 adapter로 대체했고 유료 호출·실자료 품질/원가 측정을 하지 않았다. 테스트 count를 정답률이나 검색 성능으로 변환하지 않는다.

실행 중 발견해서 고친 문제: 알림 종류·직원 destination DB 제약, source tombstone fixture의 deleted_at 누락, 한국어 문장 AND 검색 회수 소실, 세션 FOR UPDATE와 점주 메시지 FK의 불필요한 잠금 경합, v2 이력의 문맥 revision 누락, 인용 열람 상태의 조회 시점 overlay 누락, 프런트 JSON unknown 검사 및 typegen 순서.

## 남은 R 완료 조건

### W와 무관하게 남은 구현·검증

- R2 사전 승인·버전 저장·runtime 연결은 구현했다. 실제 매장 별칭/STT 표본의 검토·등록, 공개 용어 수집 adapter와 이용 범위 확인, 사전의 독립/통합 효과 비교는 남아 있다. 합성 별칭 한 건으로 실제 사전 품질을 주장하지 않는다.
- R0/R3 30~50개 이상 고정 질문·pooling·oracle·reranker 독립/통합 비교를 v2 실행 결과 수집에 연결하고 사람 의미 판정/미판정을 유지. 선택형 reranker unit은 효과 비교가 아니다.
- R3 복잡한 조건·절차·RAW 충분성의 평가된 판단, 미확정 규격의 적절한 후속 행동, 동일 의미 ESCALATE 자동 묶음. 현재 runtime semantic_context는 보수적으로 비워 두므로 grouping 서비스 테스트 통과와 자동 grouping 완료는 다르다.
- 정책 응답 뒤 사용자 명시 확인 요청 흐름, 알림 목록의 직원 화면 연결·Push 구독/재전달 worker 운영 연결, FAQ/학습 갱신의 v2 종단 인수.
- UI 전체 DB E2E, 모바일 초기 로딩/네트워크 재연결/다중 페이지·동시 탭·대량 이력 인수, SDK 실제 RERANK 계측 실패/취소 DB 인수. 현재 브라우저 12개로 전부 닫지 않는다.
- 실행 metadata에 실제 provider model/prompt hash/전체 단계 지연을 묶은 평가 보고와 J1 승격표 연결.

### W 공동 연결·사람 판단이 필요한 조건

- W 승인 변경 묶음의 실제 draft CAS→카드 공개 pointer→publish_knowledge→activate_prepared_index 동일 transaction. 테스트는 승인 카드 pointer를 합성 seed로 구성하고 W 공개 header 함수와 R activation을 연결했다.
- W ApplyOwnerAnswer 구현에서 원문 관계 판단·proposal/NEW/IDENTICAL 정책과 R finish_owner_event를 같은 발행 성공 단위로 연결. 실제 W 코드를 대체하는 가짜 PUBLISHED 처리를 넣지 않았다.
- 4상태 적용 범위 승인 근거/버전 계약, 실제 W snapshot의 의미 truth와 질문별 판정, 실제 비용·지연·반복 품질 인수.

이 미완료 목록이 있으므로 DEV_TODO의 R0~R5 전체 checkbox를 일괄 완료로 바꾸지 않는다.

## 재현

PowerShell, workspace root:

```powershell
$env:PYTHONPATH='C:\project\AskBuddy\api\tmp\test-deps'
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
./api/scripts/verify_r_handoff.ps1 -Python '<Python 실행 파일>' -IncludeSchemaRebuild -IncludeUnitTests
```

위 runner는 loopback 55439의 무작위 이름 일회용 Docker container와 UUID DB만 생성/정리한다. 운영 .env와 운영 DB를 쓰지 않는다. 코드 배포보다 M2/M3 migration 적용이 선행해야 한다. `owner_handoff`는 내부 W 접점이며 공개 사용자 API로 노출하지 않았다.
