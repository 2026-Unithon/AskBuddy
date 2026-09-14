# C0 결정서와 W/R 병렬 구현 계획

> 작성일: 2026-09-14. 기준: pull `8b8e447 → 65c2403` 및 현재 사용자 위임.
> 상태: 사용자 원가 회신까지 반영한 C0 설계·실행 계획 확정. 원가 계측 CP-00A~C를 선행한다. 실제 구현·측정·통합 검증 완료는 별도다.
> R 구현 진행: [2026-09-14 구현 기록](C0_R_IMPLEMENTATION_20260914.md). CP-01 R typed 계약/참조 검증·인증 및 기존 읽기 계측 결함을 보강했다. 공통 usage/RAW·DB 선행은 미완료이며 C0 전체 완료가 아니다.
> 제품·데이터 정본은 [MVP §31](ASKBUDDY_MVP_CURRENT.md#31-ai-파이프라인-공통-계약--이번-개정의-기술-정본), 작업 상태는 [TODO](DEV_TODO_CURRENT.md), 평가 방법은 [실험설계](이관경계_실험설계.md)를 따른다. 이 문서는 C0의 상세 결정·담당·인수 조건을 제공한다.

## 1. 이번 pull에서 이어받는 결정

| 결정 | 유지할 내용 | 이번 구체화 |
|---|---|---|
| D18 | 순증 ≥ 대조군 폭 × 1.5, 최소 5건; must_have 악화 0, 원장 재현율 하락 없음, 3회 중 2회 같은 방향; 원가 중립은 대조군 폭 문턱 | §10에서 계산 단위·반복·원가 중립·안전 조건을 정의. 통계적 유의성 증명으로 사용하지 않음 |
| D19 | 같은 메뉴의 여러 규격을 한 카드에 표시하고 fact는 규격별 분리 | 카드의 entity는 하나, fact/block에서 규격 결합 유지. 규격이 미확정이면 되묻고 확정된 규격의 값만 답변 |
| D20 | 자료 삭제 후에도 사실·카드·과거 인용 관계 보존, `인용 끊김` 표시 | source tombstone과 원본 파일 접근 해제, 사실·승인 버전은 유지. 카드 제외와 분리. 개인정보 삭제는 기존 별도 절차 |
| D21 | 매장당 월 운영 변동비 3,000원, 답변 p95 5초, 카드 생성 지연 상한 보류 | AI 전 단계·Storage 저장/전송 포함, 서버/DB 고정비 제외. 초기 등록비는 별도 추적·예산환산/잔여 예산 보전 개월 보고. 사용량은 첫 달/안정기 시나리오 |

`api/app/contracts/`와 기존 계약 테스트 22개는 재사용한다. 공개·답변 런타임은 아직 이 모듈을 소비하지 않는다. 새 타입 존재와 C0 전체 완료를 구분한다. [검토 결과](C0_REVIEW_20260914.md)에 재현 근거를 남긴다.

원가 세부 계약·코드 접점·검증은 [C0_COST_MEASUREMENT_PLAN.md](C0_COST_MEASUREMENT_PLAN.md), 입력 시나리오는 [c0_cost_scenarios.json](c0_cost_scenarios.json)에 고정한다. U1 비용 범위는 해결됐고 U2는 미래 사용량 회신 대기 대신 시나리오 + 실제 메타데이터 계측으로 전환했다.

## 2. 책임과 코드 변경 규칙

| 영역 | 주 구현자 | 검토자 | 접점 |
|---|---|---|---|
| 추출·원장·revision·카드·검수·공개 | W | R | 승인 snapshot 생산 |
| 질문·인증·문맥·검색·답변·인용 | R | W | 승인 snapshot 소비 |
| 공통 사실/RAW 렌더러 | W | R | 순수 함수, I/O 없음; R은 질문별 선택과 비사실적 연결 문구 담당 |
| 색인 준비·검색 스키마 | R | W | PrepareIndex 요청/결과; 공개 가시성 전환은 W |
| 점주 원문·occurrence·pending·앱 알림 | R | W | 원문 저장 트랜잭션 + outbox |
| 공통 원가 receipt·rate/phase·등록 계측·Storage | W | R | CP-00A~C, 등록/운영/평가 비용 분리 |
| 임베딩·질문 usage·읽기 집계·운영 원가 report | R | W | 기존 embed_texts 단일 진입점, 공통 receipt 소비 |
| ApplyOwnerAnswer·proposal·지식 발행 | W | R | owner_answer_id를 멱등 명령으로 소비 |
| 계약 common/extraction/card/snapshot·배포 migration 순서 | W | R | `api/app/contracts/`, migration 등록표 |
| 계약 answer/chat/error·API/OpenAPI·TS 타입 | R | W | `learn/router.py`, `answering.py`, auth/notifications |
| config·의존성 파일·평가 manifest | W | R | R의 변경 요청을 포함한 한 PR에서 편집 |
| main.py·deps.py·공통 Web types/query keys/layout | R | W | W는 인터페이스 요청 전달 |

위 배정은 초기 주 편집자다. 변경 전에 PR에 주 편집자 한 명을 기록하면 인계할 수 있다. 두 사람이 같은 공유 파일을 동시에 편집하지 않는다. 외부 메시지 전송은 이 문서의 작업에 포함되지 않는다.

각 담당자는 자신의 API·DB·프롬프트·UI·평가를 끝까지 맡는다. 별도 브랜치/작업 디렉터리에서 공통 계약 PR을 먼저 반영하고 작은 기능 PR로 합친다. Git 이력·사용자 작업을 덮어쓰지 않는다.

계약 변경은 schema diff + 정상/거절 fixture + 생산자/소비자 테스트를 같은 변경 묶음으로 제출한다. W/R 모두 검토한다. C0 최초 동결 전 현재 `*/v1`을 함께 보강할 수 있다. 동결 후 `extra=forbid` 소비자가 거절할 필드 추가도 호환 변경으로 가정하지 않는다. 기존 필드 집합 그대로 읽을 수 있는 adapter 또는 새 major version을 제공한다. 과거 fixture는 해당 버전 디렉터리에서 재현한다.

## 3. 데이터 계약: 지금 고정할 것

### 3.1 ID·시간·원문·버전

- 기존 DB bigint ID를 유지한다. 신규 DB entity도 bigint, wire에서는 `1..9223372036854775807`의 선행 0 없는 decimal string. `0`, 음수, float, bool, 범위 초과는 거절한다.
- `knowledge_revision/index_revision`도 bigint counter이며 wire는 0 이상 decimal string으로 통일한다. 현재 Python int 계약은 최초 동결 전에 producer/consumer/fixture와 함께 변경한다. JSON 숫자로 JS 정밀도를 잃지 않게 한다.
- request/event/idempotency/context의 opaque token은 서버 UUID로 구분한다. 기존 `chat_sessions.session_id`, `owner_answers.answer_id`는 재발급하지 않고 wire 이름만 명시 매핑한다.
- 모든 저장 시간은 UTC timezone-aware, wire는 UTC ISO 8601이다. timezone 없는 입력은 거절한다.
- 원문 assertion·점주 답변·RAW span은 공백과 줄바꿈까지 보존한다. ID·사용자 검색어의 정규화는 별도 필드에서 수행한다. 공통 `str_strip_whitespace`가 원문을 변경하지 않도록 타입을 분리한다.
- schema_version, renderer_version, glossary_version, query_normalizer_version, policy_version, 모델·프롬프트 버전을 각각 기록한다. ID와 버전 문자열의 의미를 섞지 않는다.

### 3.2 assertion·fact revision·occurrence

- `original_assertion`이 의미의 권위 기준이다. subject 원문과 서버 확정 entity_id를 함께 둔다. predicate, variant, quantity/value_text, polarity, conditions, exceptions, order, requires, provenance를 손실 없이 전달한다.
- typed 값은 quantity와 value_text 중 최대 하나. 모르는 단위/부정/규격을 추정해 채우지 않는다. quantity 단위 미확정이면 수량 템플릿의 자동 답변은 금지하고 승인 RAW 적합성을 별도 판단한다.
- 미확정 variant와 명시적으로 규격 비적용인 사실은 다르다. 적용 범위는 `UNKNOWN / SPECIFIC / ALL_APPROVED_VARIANTS / NOT_APPLICABLE`로 명시하고 서버·점주가 확인한다. 모델이 ALL을 선언했다는 이유만으로 통용하지 않는다.
- 수정·typed 해석 변경·업무 의미가 달라지는 제목/문구 변경은 새 fact/card revision이다. 같은 의미의 근거 추가도 새 evidence occurrence와 연결 이력을 만들며 과거 snapshot은 변경하지 않는다.
- occurrence는 `(store_id, source_or_owner_answer_id, segment_id, logical_attempt_id, local_ref)`로 유일하게 식별한다. 같은 사실의 여러 출처를 canonical fact 하나로 묶어도 occurrence는 각각 남긴다.
- disposition은 occurrence_id가 주체이며 canonical fact/revision은 검증 후 연결한다. schema 탈락 주장도 raw attempt와 local_ref로 추적한다. LINKED에는 카드 버전/블록 연결, REVIEW_PENDING/EXCLUDED에는 reason·결정자·시각이 필요하다.
- extraction request의 source/segment/attempt는 서버가 확정한다. 모델 응답에 echo가 있어도 요청과 대조한다. 유효한 NO_RESULT는 빈 assertions와 명시 result 상태로 표현하고, 빈 JSON·missing segment·잘림은 성공 처리하지 않는다.
- locator는 source type와 함께 검증한다. 문서 page/BBOX 좌표계·page 범위, 영상/음성 시간 범위, 대화 line 범위를 확인한다. WHOLE_SOURCE는 전체 원문 RAW/OWNER_ANSWER 호환에만 허용하고 상세 locator 누락을 감추지 않는다.
- 원문·조건·블록의 개수 상한에 걸리면 분할 또는 명시적 오류/검수 대기로 보존한다. list를 자르거나 조건을 버려 성공시키지 않는다. 세그먼트 간 선행관계는 원문에 남기고 W2에서 서버 revision으로 연결한다.

### 3.3 카드와 RAW

- D19를 따라 하나의 카드에는 하나의 확정 entity와 여러 규격을 표시할 수 있다. 카드 수준 `variant=null`을 fact의 wildcard로 해석하지 않는다.
- QUANTITIES는 규격별 하위 블록/행을 별도 ID로 만들고 값·단위·조건을 같이 둔다. STEPS는 순서·필수 주의와 dependency closure를 보존한다. 조건을 떼어낸 선택은 거절한다.
- 사용자가 HOT/ICE 비교를 명시하면 질문의 요청 규격 집합을 양쪽으로 확정해 두 값을 각 규격과 함께 인용할 수 있다. 한 규격의 값을 묻는데 규격이 미정인 경우에 CLARIFY한다. 카드가 여러 규격이라는 이유만으로 이미 명확한 비교 질문을 반복해서 되묻지 않는다.
- `CardBlock`은 typed reference block과 승인 RAW reference block의 구별 가능한 union으로 보강한다. typed는 fact_revision_ids, RAW는 immutable raw_span_id·card_version_id·원문 hash·provenance를 사용한다. RAW를 표현하려고 역추출 fact를 자동 승인하지 않는다.
- 제목은 승인된 entity 이름/규격에 연결된 서버 표현 또는 점주가 확인한 title revision이다. 모델 자유 title이 수량·금지·업무 의미를 추가하는 우회로가 되지 않게 한다.
- 렌더 결과가 달라지면 새 renderer_version을 낸다. 직원에게 보이는 업무 표현 변경은 새 draft와 재승인 대상이다. CSS만 바꾸는 경우에는 지식 version을 변경하지 않는다.

### 3.4 snapshot·hash·불변성

- snapshot은 한 매장의 특정 공개 상태 전체를 식별하는 논리적 불변 manifest다. 물리적으로 매번 사실/임베딩을 모두 복제하지 않고 version ID 참조를 재사용한다. R은 요청마다 전체 manifest를 전송받지 않고 같은 revision의 승인 색인을 조회한다.
- 필수 envelope는 store_id, schema_version, knowledge_revision, snapshot_id/hash, created_at, glossary/renderer version, cards, fact_revisions, raw_spans, provenance다. provenance는 immutable 출처 식별·locator·hash를 담고 원본 접근 가능 상태는 현재 권한 조회에서 overlay한다.
- fact/card/card_version/occurrence 식별자는 해당 범위에서 중복 금지, block_id는 card_version 안에서 유일하다. 참조한 사실과 RAW span은 승인 카드 버전의 실제 허용 집합에 속해야 한다. 어디에도 승인 연결이 없는 orphan fact는 snapshot에 포함하지 않는다.
- requires는 누락·자기참조·순환을 거절한다. 필요한 사실이 같은 snapshot에 있다는 것뿐 아니라 선택한 답변 블록까지 transitive closure가 닫혀 있어야 한다. 공통 선행조건을 다른 entity에서 참조하려면 승인된 명시 dependency 관계가 필요하다.
- DTO는 frozen + 내부 tuple 등 불변 컬렉션을 사용한다. DB에서는 승인 version에 UPDATE하지 않고 새 version을 INSERT한다. cache도 검증 후 복제 또는 불변 객체만 저장한다.
- hash는 `sha256:<64 lowercase hex>`로 표시한다. canonical payload는 schema/매장/revision/버전/승인 cards·facts·raw·provenance이며 snapshot_id, created_at, snapshot_hash 자체와 가변 접근상태는 제외한다.
- canonical JSON은 UTF-8, sort_keys, 공백 없는 separators, NaN 금지, 숫자 값은 decimal string으로 고정한다. ID 집합·facts·cards는 규정된 ID 순서로 정렬하고 의미 있는 block/step/conditions 순서는 보존한다. 원문 Unicode/공백을 정규화하지 않는다. 서버 Python canonicalizer 하나로 계산하고 고정 test vector를 JSON export에 포함한다.
- 최초 빈 매장은 revision `0`, 빈 cards/facts가 유효하다. 무근거 ANSWER는 금지한다. 실제 snapshot export의 초기 한도는 10 MiB이며 초과 시 전체를 자르지 않고 명시 오류; 기능 확장이 필요하면 chunk manifest 계약을 별도 추가한다.

## 4. 발행·색인·삭제의 구현 결정

### 4.1 서비스 접점

새 외부 서비스 없이 기존 PostgreSQL+pgvector와 FastAPI를 사용한다. 아래 이름은 구현할 내부 DTO/서비스 계약이며 현재 공개 endpoint가 아니다.

| 접점 | 입력 | 출력/소유 |
|---|---|---|
| PrepareIndex | trusted store scope, proposed immutable content/hash, expected publication/card revisions, model/glossary/renderer versions, idempotency key | R: PREPARED 또는 FAILED, prepared_id, payload_hash, index config version, expires_at, 구조화 오류 |
| PublishKnowledge | prepared_id, 예상 draft/card/publication revision, owner approval, idempotency key | W: PUBLISHED / ALREADY_APPLIED 또는 STALE/FAILED; 최종 snapshot/revision |
| Exclude/RestoreCard | store, card, expected publication revision, idempotency key | W: 동일 공개 조정 서비스 사용, 검색/학습/FAQ 가시성 변경 |
| ValidateAndSaveAnswer | trusted user/member/session/store, expected snapshot/revision, 검증된 선택, request idempotency | R: 현재 권한·공개 재검사 + 메시지/인용 저장 |
| ApplyOwnerAnswer | trusted store, owner_answer_id, event_id | W: LINKED / REVIEW / PUBLISHED / FAILED; 연결된 revision/proposal·retryable |

PrepareIndex는 async Python 호출로 제공하고 C0에서는 fake 구현, R1부터 실제 어댑터로 교체한다. 준비 단위는 공개 요청의 변경 카드 묶음 전체다. 일부 성공은 staged 상태로만 남기고 전체 준비 전 공개하지 않는다. 준비 토큰 TTL은 15분, durable staging과 operation ID로 재시작/중복을 복구한다.

### 4.2 발행 성공 단위와 경합

1. 트랜잭션 밖에서 proposed content·승인 preview hash·임베딩을 준비한다. 아직 공개할 최종 knowledge_revision을 발급하지 않는다.
2. 짧은 트랜잭션에서 매장 publication row를 잠그고 예상 draft/card/publication revision, prepared hash/TTL, 현재 승인 권한을 검사한다. 실패하면 기존 공개본 유지.
3. 성공 시 knowledge_revision을 1 증가시키고 최종 snapshot/hash, fact/raw refs, 카드 공개 포인터, 같은 버전 index visibility, outbox event를 함께 commit한다.
4. R 소비자는 outbox로 캐시를 무효화하지만 신규 답변의 권한·현재 공개 확인은 DB 정본으로 보장한다. event 지연에 안전성을 맡기지 않는다.
5. 답변 저장도 같은 매장 publication row의 잠금 규칙을 사용해 검증과 저장 사이 TOCTOU를 닫는다. lock 순서는 publication → card ID 오름차순 → request/session. 외부 모델 호출 중 lock/DB connection을 보유하지 않는다.

공개·제외·복원·승인 업무 내용 변경 때 knowledge_revision이 증가한다. 동일 멱등 재시도와 실패는 증가시키지 않는다. glossary 변경은 새 index 준비와 원자 pointer 전환 시 적용하며 knowledge_revision도 증가한다. 같은 내용의 검색 구현 재색인은 별도 index_revision을 바꾸고 knowledge_revision은 유지한다. cache key에는 둘 다 포함한다.

stale 답변은 전체 요청 deadline 안에서 최대 1회 재검색한다. 계속 경합하거나 budget이 부족하면 `STALE_KNOWLEDGE` retryable ERROR다. 지식 부족으로 pending을 생성하지 않는다. 저장 성공 후 미래 공개 변경은 당시 응답을 소급 변경하지 않는다. 멱등 재조회는 당시 응답을 이력으로 표시하고, 새 질문은 현재 revision으로 처리한다.

### 4.3 outbox와 멱등성

- event payload는 version, server event_id, store_id, type, aggregate ID, knowledge_revision 또는 owner_answer_id, occurred_at만 담는다. 원문·직원 목록은 권한 있는 DB 조회로 가져온다.
- 전송은 at-least-once, 소비 결과는 `(store, consumer, event_id)` unique와 업무 키로 중복 방지한다. 순서가 뒤집히면 낮은 revision을 재활성화하지 않는다. version gap/누락은 현재 manifest로 재동기화한다.
- DB outbox claim/lease worker를 초기 접점부터 둔다. BackgroundTasks 단독에 전달 보장을 맡기지 않는다. J2는 W의 전체 추출 job worker/복구를 완성한다.
- 요청 멱등성은 `(store, member, operation, idempotency_key)`와 body_hash로 검사한다. 같은 키·다른 본문은 409. 응답 캐시는 24시간, 업무 operation ID·owner answer/event dedupe는 이력 수명 동안 보존한다. 재시도는 기존 operation을 조회하며 신규 시도와 구분한다.
- 응답 유실·commit 결과 불명확은 새 업무를 만들지 않고 기존 operation 상태를 조회한다. v2 GET에 operation_id 조회를 제공하고 동일 store/member/session 소유권을 검사한다. 저장된 응답 재조회에서는 현재 접근권한과 인용의 source 상태를 다시 적용하되 당시 본문·version은 이력으로 유지한다.
- publication event는 `(store, knowledge_revision, event_type)`도 unique로 둔다. worker는 lease 60초/heartbeat 20초, 최대 10시도·exponential backoff 최대 60초 후 FAILED와 운영 알림; 같은 업무 키로 수동 재처리한다. 의미 오류·권한 오류는 자동 재시도하지 않는다.

### 4.4 D20 자료 삭제

- source 행은 tombstone으로 남기고 `source_availability=DELETED`와 deleted_at을 기록한다. 실제 원본 파일 삭제/URL 폐기는 권한 있는 삭제 workflow에서 처리한다. facts·card_versions·message_citations를 cascade 삭제하지 않는다.
- provenance locator/hash와 승인 원문은 보존한다. source 미가용은 새 사실 해석·재추출을 막지만 승인 카드 자체를 자동 제외하지 않는다. 기존 승인 snapshot으로 신규 답변은 가능하고 인용 칩에 `인용 끊김` 및 `원본 자료가 삭제되었어요. 승인된 카드 내용은 확인할 수 있어요.`를 표시한다.
- 여러 원본 중 일부만 삭제된 경우 occurrence별 상태를 보여주며 살아 있는 다른 근거는 유지한다. source 상태는 current overlay로 조회해 과거 immutable snapshot을 수정하지 않는다. 일시 장애는 `UNAVAILABLE`로 구분하고 DELETED로 기록하지 않는다.
- 기존 migration의 `source_facts.source_id ON DELETE CASCADE`가 남아 있으므로 신규 migration에서 보존 FK/삭제 서비스로 전환하고 재구축 검증한다. source 삭제 endpoint를 먼저 켜지 않는다.
- 개인정보 삭제 요청은 D20 일반 삭제와 구별해 운영 절차에서 처리한다. 이 문서가 자동 개인정보 삭제·법정 보존기간을 정하지 않는다.

## 5. 질문·답변·점주 전달

### 5.1 질문과 context

- JWT의 store/user claim과 현재 store_members membership/role을 확인한다. 요청 store는 권한 근거로 쓰지 않는다. 대상 타 매장/타 사용자 조회는 404, 인증 없음은 401, 현재 역할 부족은 403이다. 내부 worker는 trusted store scope를 필수로 전달한다.
- context는 서버 UUID이며 `(store_id, member_id, chat_session_id, contract_version)`에 묶는다. TTL은 마지막으로 수락한 사용자 턴부터 10분. 유효 회원이 같은 서버 대화 session을 재접속한 경우 계속할 수 있으나 다른 session으로 복사하지 않는다. JWT 재발급만으로 대화 이력을 잃지 않는다.
- context에 최근 확정 entity/variant/속성/조건·원문 질문을 보존한다. 모델 추정 슬롯과 사용자 확인 슬롯을 분리하고 이전 모델 답변을 사실로 사용하지 않는다. knowledge_revision 변경은 확정 사용자 슬롯만 유지하고 후보 근거를 재검색한다.
- 한 요청은 한 개의 미확정 슬롯을 먼저 묻는다. CLARIFY 최대 2턴 후에도 불명확하면 이유 `UNRESOLVED_CONTEXT`로 ESCALATE하고 미확정 상태 그대로 개별 pending에 보존한다. TTL 만료는 `CONTEXT_EXPIRED` ERROR와 원문 재질문 안내; 자동 pending 없음.

### 5.2 AnswerPlan과 최종 검증

- 다섯 action은 action별 필드를 엄격하게 배타 검증한다. ANSWER에 context/options/escalation 전용 필드, CLARIFY에 escalation 필드, 정책 action에 질문 슬롯/선택 블록이 섞이면 거절한다.
- 모델의 선택 제안과 서버가 소유권을 확정한 chat 응답 DTO를 분리한다. 모델이 context ID·snapshot ID를 새로 발급하지 못한다. 서버가 현재 snapshot을 고정해 허용 후보 밖 참조를 거절한다.
- `validate_answer_plan(plan, snapshot, resolved_query, trusted_scope)`는 card/version/block/fact/raw 소속, entity·variant·predicate, 조건·예외·dependency closure를 검사한다. Pydantic shape 검사와 DB의 현재 승인/권한 검사는 각각 수행한다.
- D19의 혼합 규격 카드에서도 선택한 fact의 규격만 렌더링한다. dependency나 공통 주의는 함께 출력한다. 한 블록 일부를 선택할 때도 필수 closure가 빠지면 거절하고, 정합하게 쪼갤 수 없는 블록은 승인 전체 의미 단위를 사용한다.
- ANSWER는 적어도 하나의 typed 또는 RAW 승인 block citation이 필요하다. citation_count는 중복을 제거한 실제 저장 인용 행 기준이며 fact 개수를 인용 개수로 부풀리지 않는다.
- 구조 검증 실패 시 충분성이 별도 확인된 승인 RAW만 fallback한다. 대체 근거가 없고 입력 지식이 부족한 경우 ESCALATE, 모델/서비스 실패는 ERROR다. renderer가 의미 정확성을 보장한다는 주장은 하지 않는다.

### 5.3 pending·원문·알림

- 의미 중복키는 store + 정상화 버전 + 확정 entity/predicate/variant/conditions + 정책 범위의 canonical hash다. 슬롯이 충분히 확정되지 않으면 occurrence UUID를 추가해 별도 pending을 만든다. 검색 유사도나 모델 단독 판정으로 여러 직원 질문을 합치지 않는다.
- 사용자 원문, resolved_query, 확정/미확정 슬롯, context snapshot을 occurrence마다 보존한다. 점주에게 문맥을 함께 보여준다. 원문이 같아도 대상이 다르면 별도 pending이다.
- ESCALATE 성공은 질문 occurrence + WAITING pending 연결 + durable notification event/outbox의 한 트랜잭션 commit이다. Push는 후속 비동기 전달이며 실패해도 질문 저장은 유지한다. CLARIFY/정책/ERROR는 이 쓰기를 하지 않는다.
- 점주 답변 제출은 기존 `owner_answers.answer_id`를 wire `owner_answer_id`로 사용한다. 원문·답변자·occurrence 연결·직원 앱 알림·OWNER_ANSWER outbox를 한 트랜잭션에 남긴다. 현재 pending 잠금 하에서 답변 대상 occurrence를 확정한다.
- 원문 전파 상태와 지식화 상태를 한 enum에 섞지 않는다. 직원 전달은 저장된 OWNER_ANSWER 이력과 recipient별 notification 상태, 지식화는 `PENDING / LINKED / REVIEW / PUBLISHED / FAILED`다. Push 요청 성공은 읽음이 아니다.
- 제출 원문은 불변. 수정 요청은 새 owner answer revision과 supersedes 연결로 처리하고 기존 메시지를 조용히 바꾸지 않는다. 이미 W에서 처리 중이면 expected revision 검사를 통해 구 답변을 새 지식으로 stale 발행하지 않는다.
- W는 확인된 IDENTICAL을 현재 승인 카드에 연결, NEW는 점주 원문 RAW로만 기존 예외 경로에 공개한다. 모델 파생 fact·SUPPLEMENT·CONFLICT·관계 미확정은 REVIEW. LLM 관계 판정 실패를 NEW로 간주하지 않는다.
- 공개 성공 event 이후 FAQ·학습·검색을 갱신한다. 동일 pending에 동시 유입한 새 occurrence도 현재 문맥과 membership을 확인해 원문 답변을 받을 수 있게 재조회한다. 알림 unique 키로 중복 전파를 막는다.

### 5.4 정책과 API 오류

정책 `policy/v1`은 개인정보·제3자 비업무 개인 정보에 REFUSE, 안전 판정을 요구하는 질문에 SAFE_ROUTE를 사용한다. 모델은 전문적인 안전 판단을 생성하지 않는다. 직원에게 다음 고정 문구를 쓰고 기대 action fixture에 넣는다.

- REFUSE: `개인정보에 관한 내용은 안내할 수 없어요. 업무상 확인이 필요하면 사장님에게 직접 확인해 주세요.`
- SAFE_ROUTE: `안전 여부는 여기서 판단할 수 없어요. 현장의 안전 지침과 담당자의 확인을 따라 주세요.`
- 사용자가 별도 확인 전달을 요청하면 명시적 ESCALATE로 이어진다. 제3자 개인정보 원문을 알림 preview에 복제하지 않고 전달 목적만 표시한다.

v2 오류 envelope는 `{contract_version, error:{code,message,retryable,request_id,operation_id?,retry_after_ms?}}`다. 정상 action에 ERROR enum을 추가하지 않는다. validation 422, 동일 키 다른 요청·stale 승인 409, context 만료 410, rate limit 429, 일시 장애 503, deadline 504를 사용한다. 타 매장 ID나 내부 SQL/모델 원문은 details에 노출하지 않는다.

최소 code: INVALID_CONTRACT, UNSUPPORTED_SCHEMA, INVALID_REFERENCE, STALE_DRAFT, STALE_PUBLICATION, STALE_KNOWLEDGE, HASH_MISMATCH, INDEX_PREPARE_FAILED, INDEX_PREPARE_TIMEOUT, CONTEXT_EXPIRED, IDEMPOTENCY_CONFLICT, RATE_LIMITED, MODEL_UNAVAILABLE, STORAGE_FAILED. PREPARED/ALREADY_APPLIED는 실패 code가 아니다.

## 6. 기술 초기값과 관측

아래 값은 구현·부하 시험의 조정 가능한 초기 설정이다. 운영 계약 달성 결과가 아니며 `config.py`에 단일 정의한다. D21 상한을 바꾸는 조정은 사용자 결정이 필요하다.

| 항목 | 초기값/규칙 |
|---|---|
| 답변 p95 | 서버가 인증 요청을 받은 시점부터 응답 전체 생성·DB commit을 끝내는 시점까지 5초. network/client RTT 별도 보고 |
| chat deadline | 전체 5초; 최종 DB 검증·저장에 0.5초 예산 예약. 모든 단계는 남은 absolute deadline을 공유 |
| LLM | 한 요청의 전체 모델 예산 최대 3초; SDK 자체 retry도 합산. 선택적 reranker 기본 OFF, 모델/embedding 동기 호출은 connection/lock 밖 |
| 검색 | lexical/vector 합계 최대 1초; 임베딩·권한·저장도 전체 5초에 포함. timeout을 억지 miss로 바꾸지 않음 |
| stale 재검색 | 최대 1회, 기존 deadline 이내. 추가 5초를 다시 부여하지 않음 |
| 공개 인덱스 준비 | 시도당 30초, 최대 3시도(첫 시도 포함), transient만 2초·10초 backoff; 백그라운드 상태로 노출 |
| 질문 유입 | 회원 20회/분, 매장 120회/분; 동시 회원 2/매장 8. 429 + retry_after. DB atomic limiter를 공유하여 다중 worker에서 우회되지 않게 함 |
| 재사용 | 임베딩 키는 tenant + 승인 내용 hash + 모델/config/version. 답변 캐시는 권한/session scope·snapshot/index/정규화/policy version 포함 |
| 운영 로그 | 기본은 ID·오류·시간·토큰·비용 메타데이터만 30일. 질문/점주 원문은 업무 DB에 보존하고 일반 로그 중복 저장 OFF |
| 민감 접근 | 원본·인용·대량 조회·export는 현재 membership/role 검사와 access log. 직원 export 기본 미제공, 점주만 승인된 기능으로 제공 |

짧은 deadline 때문에 정상 답변을 ERROR로 보내 p95만 낮추지 못하도록 전체 요청 오류율·완전답변률·coverage를 함께 게이트한다. W job 지연 상한은 D21대로 보류하되 phase timeout/checkpoint/재시도는 반드시 구현한다.

## 7. migration·호환·롤백

물리 테이블명은 아래 논리 모듈을 기준으로 PR에서 확정하되 중복 원장을 만들지 않고 기존 source_facts/card_versions/owner_answers와 연계한다. 적용된 migration은 수정하지 않는다.

| 순서 | 주 담당 | 추가/검증할 내용 | 선행 |
|---|---|---|---|
| MC0 | W 원가 원장, R 집계 검토 | usage attempt·nullable extraction summary·가격/Storage report; 기존 run freeze 보존 | CP-00A 최소 원가 계약, 신규 publication schema에 독립 |
| M0 | W, R 검토 | 공통 operation/outbox/consumer dedupe·lease; store scope unique/FK 규칙 | 동결 schema, MC0 이후 |
| M1 | W | fact revisions, occurrence/provenance, raw spans, version-block refs, source tombstone·보존 FK, publication/snapshot manifest | M0 |
| M2 | R, W 검토 | versioned index staging/visible refs; `(store, card_version, block, index_config)` 유일성 | M1 |
| M3 | R | v2 session/action/context, question occurrence semantic key, message block/raw citation, owner answer revision/상태 | M1; M2와 작성 병렬 |
| M4 | 공동, W 통합 | legacy 승인 본문의 immutable RAW adapter/backfill, 검증 건수·누락·재실행, 제한된 rollout | M1~M3 |

기존 `card_embeddings`의 카드/청크 unique key만으로는 승인 구/신 버전 병존이 충분하지 않다. 가산형 versioned index를 먼저 만들고 legacy index를 유지한다. source FK 삭제 정책과 기존 지식/인용 FK도 로컬 재구축에서 검사한다. 다른 매장에 연결되는 것을 DB composite FK/unique와 API 검증으로 함께 막는다.

읽기 경로의 안전 shim → additive DB → API producer/consumer adapters → v2 Web → 독립 플래그 활성화 순서다. 지원 조합은 MVP §31-7을 그대로 따른다. v1에서 CLARIFY를 WAITING으로 바꾸지 않고 전환 안내를 반환한다. session에 API contract version을 고정하고 v2 이력에 없는 legacy action을 발명하지 않는다.

v1 제거는 Web v2 전환·지원 클라이언트 조사·사용 0 확인·별도 제거 PR 이후다. 이 작업은 제거 날짜를 임의로 약속하지 않는다. 롤백은 새 이력 삭제 없이 호환 reader/index로 전환하며 인증·승인·현재 버전 확인은 항상 유지한다.

## 8. W/R 병렬 PR 계획

아래 `CP-*`는 새 구현 PR ID다. 이전 대화의 질문 C0-01~47 및 TODO C0-1~5와 다른 namespace다. 각 PR은 구현+검증 근거로 완료하며 이 계획 작성으로 체크하지 않는다.

| PR | 담당 | 구현 산출물 | 선행 | 완료 테스트 |
|---|---|---|---|---|
| CP-00A | W usage/schema·migration, R 소비 검토 | UsageContext·호출 receipt·rate/phase/purpose·nullable extraction summary·MC0 | 독립 착수 | fake usage/요율·결측/0·store 귀속·기존 freeze |
| CP-00B | W extract/STT/storage, R embed/answer/metrics | 현재 호출부의 시도별 durable usage·Storage inventory·unknown 집계 | CP-00A | parsing 실패/timeout/retry/cache·직접 Storage 전송 누락 구분 |
| CP-00C | W 등록/manifest, R 운영/report | 첫 달/안정기 시나리오·등록/운영 비용·예산환산·Storage 대조·원가 회귀셋 | CP-00B | offline/격리 DB 집계 인수, 실제 비용은 계측된 첫 dev 캠페인에서 별도 확인 |
| CP-01 | W/R 각 소유 모듈 | ID/원문/불변성/중복/closure/RAW/occurrence 보강, action 배타성, 서버 validation 경계 | 없음 | 기존 22개 유지 + 검토 반례를 목표 불변식 테스트로 전환 |
| CP-02 | W snapshot, R chat/event | publication/index/owner command/error/chat DTO·JSON schema export·hash canonicalizer | CP-00C·CP-01 | JSON schema 왕복, bigint/시간/hash test vector, version 호환 거절 |
| CP-03 | W 생산, R 소비 | versioned synthetic fixture+질문 manifest+fake renderer/indexer/outbox | CP-02 | 생산자/소비자가 같은 fixture로 독립 통과, 5 action·ERROR |
| CP-04 | W 조정, R DB 접점 | M0~M3 migration 초안·단위 transaction 서비스·삭제/멱등/race 시나리오 | CP-02; CP-03와 병행 | 격리 DB 재구축·rollback 범위·composite FK·중복/동시성 |
| CP-05 | R runner/metrics, W manifest 편집·쓰기 검토 | CP-00의 원가 계측을 새 품질 manifest·D18/D21·분모·CI에 통합 | CP-03·CP-00C | 손으로 계산한 짝비교/원가/오류 fixture와 일치; 계측 재구현 없음 |
| W-A / R-A | 각각 | W0/W1 원장 선저장 / R0/R1 인증·기준선·snapshot 소비 | CP-01~03 | J0-A: 합성 입력→승인 fixture→검색 계약 |
| W-B / R-B | 각각 | W2/W3 revision·통합·카드 검수 / R2/R3 질문·hybrid·충분성 | A + CP-04 | J0-B: 실제 producer의 합성 snapshot을 consumer에 연결 |
| W-C / R-C | 각각 | W4/W5 공개·쓰기 평가 / R4/R5 답변·인용·점주 루프 | B + CP-04~05 | J0-C: 공개/제외/동시수정/OWNER_ANSWER 왕복 |
| J1 | 공동 | 실제 원본 truth·W snapshot·R version 고정 종단 실험 | 양쪽 C | W만/R만/W+R 비교, 안전·품질·원가·지연 게이트 |
| J2/J3 | W worker, R E2E/알림 | 전체 영속 worker·CI·롤백·실기기·운영 인수 | J1와 관련 구현 | 복구/재시작/데이터 보존 + 별도 권한 있는 배포 |

C0-4의 계측 CP-00A→B→C를 C0-2/3 본구현보다 먼저 완료한다. 그동안 CP-01 계약 오류 보강·R 인증 정리·W 메타데이터 진단은 별도 파일에서 병행한다. 이후 CP-02→03으로 계약/fixture를 동결하고 W/R 독립 개발·CP-04 DB 시퀀스·CP-05 품질 판정을 진행한다. C0 계획은 확정됐으며 구현 완료는 CP-00A~C와 CP-01~05의 인수 근거로 판정한다. 실자료 원가/품질 승격에는 관측된 dev 캠페인이 추가로 필요하다.

계약 PR마다 상대가 필수 검토한다. 기능 PR마다 자신의 계약 테스트, 주요 병합마다 J0를 실행한다. 계약 변경은 schema+fixture+양쪽 테스트 동시 갱신, 미결 이슈는 이 문서 결정 ID/담당/막히는 PR에 연결한다. 일정은 일수 대신 위 선행·합류 조건으로 관리한다.

## 9. fixture와 검증 인수 기준

공유 synthetic fixture는 `api/tests/fixtures/contracts/v1/`에 구현한다(현재 계획 경로). schema, snapshot, expected answer/action, event sequence, manifest/hash를 함께 둔다. 실제 상호·고유 메뉴·원본·비밀값을 Git에 넣지 않는다.

| 묶음 | 필수 사례 | 담당/판정 |
|---|---|---|
| F01~F08 | 단일 수량, HOT/ICE 한 카드, 크기 차이, 조건, 부정, 예외, 순서, 여러 블록 closure | W 작성/R 답변 기대 검토 |
| F09~F13 | legacy RAW, 대상 모호, 규격 모호, 근거 없음, 미해결 충돌 | R 작성/W 승인 범위 검토 |
| F14~F20 | 교차 매장, 초안, 승인 취소, 과거 버전, stale cache, 잘못된 참조, schema 미지원 | 공동 |
| F21~F25 | outbox 중복/역순/누락, 모델 timeout, pending 저장 실패, owner answer 중복, prompt injection | R/W 접점별 |
| F26~F31 | source 삭제 overlay, 혼합 규격 선택, 중복 ID/순환, TTL/다른 session, CAS/hash 변조, v1/v2 네 조합 | 공동 |
| F32~F35 | 원문 공백 보존, occurrence별 disposition, token/비용 관측 누락, membership 제거/인용 재조회 | 공동 |

CP-00A~C는 이 제품 fixture 동결 이전에 독립된 fake provider/가상 요율·Storage 사용량 원가 fixture를 먼저 작성한다. 원가 계획 §8의 14개 반례를 F34에 연결하며 C0-3 완료에 원가 계측을 종속시키지 않는다.

각 fixture는 expected action 외에 필수/금지 fact/raw/block·조건·인용·pending/알림 생성 여부·오류 코드·후속 사용자 슬롯을 갖는다. 기대 행동은 snapshot별 결과를 보고 바꾸지 않는다. 정답 근거의 동등 대안도 사전 기록한다.

검증 계층: schema/unit → producer/consumer → 격리 DB/API/outbox → 축소 J0 E2E → 실제 J1/반복 평가. 현재 22개 unit 통과는 첫 계층 일부의 증거다. mock 결과를 실제 Gemini 품질·비용으로 보고하지 않는다. snapshot source truth는 점주/사람 평가자가 확인하고 검색 관련성은 팀이 평가한다. 판정 불일치는 근거를 재검토하고 미확정을 분모에서 빼지 않는다.

## 10. D18/D21 평가 규칙

### 10.1 D18 계산

- 동일한 고정 truth/질문 집합에서 각 run의 성공 개수 S를 센다. W는 원본 truth를 정확히 보존한 개수, R은 고정 Q_A의 완전한 grounded ANSWER 개수, J1은 고정 Q_source_A의 완전한 ANSWER 개수다. 서로 다른 단위의 숫자를 비교하지 않는다.
- A/B를 각각 최소 3회 같은 조건으로 짝짓고 Δ_i=S(B_i)−S(A_i), 대표 순증 Δ=median(Δ_i)로 고정한다. 별도 동일 설정 A/A run들의 성공 개수 max−min을 대조군 폭 w로 사용한다. 실행 순서는 교차/사전 무작위화한다.
- 일반 변경 문턱은 Δ≥max(5, ceil(1.5w)). 동일 workload/rate에서 포함 변동비(등록·운영 구분)가 증가하지 않는 원가 중립 변경은 Δ≥max(5, ceil(w))로 한다. 고정비를 제외해도 DB/서버 부하·지연·오류 회귀는 별도 gate로 검사한다. 기존 최소 5건을 유지하며 적은 fixture에서는 승격 대신 계약 검증/탐색으로 표시한다.
- 최소 3회 중 2회 Δ_i>0, must_have/safety 사례의 악화 0, W의 ledger recall 하락 없음이 동시에 필요하다. R 독립 평가는 동일 승인 fixture이므로 원장 조건은 입력 동일성으로 확인하며 W 원장 품질 개선을 주장하지 않는다.
- 완전답변/precision/coverage·정책 정확도는 관측상 하락 0, 오류·unsafe/leak/false abstention은 관측상 증가 0을 초기 비열등 기준으로 둔다. 더 넓은 허용 마진이 필요하면 결과를 보기 전에 별도 변경 기록을 남긴다.
- D18은 운영 채택 heuristic이다. A/A 범위·2/3 방향·최소 3회가 유의성 또는 일반화 증명이 되지는 않는다. 모든 반복·실패·불안정 사례를 보고하고, 매장/질문 의존성을 보존한 불확실성 분석과 holdout 캠페인을 함께 사용한다. 불명확하면 승격 보류.
- 분석 단위·주 지표는 변경 가설별 manifest에서 사전 지정한다. 답변 단위 성과와 전체 Q의 올바른 행동을 함께 보고해 모호한 질문을 억지 ANSWER하는 퇴행을 막는다. W 누락 때문에 올바르게 ESCALATE한 질문도 J1의 ANSWER 성공이 아니다.

### 10.2 D21 측정

- 월 운영 변동비 상한 3,000원과 답변 p95 5초를 유지한다. AI 전 단계·STT·임베딩·재시도 및 Storage 저장/전송을 포함하고 Railway/Vercel/DB 고정비는 제외한다. 고정비가 규모에 따라 바뀌면 별도 재검토한다.
- 최초 등록비 I와 월 운영비 O_m을 별도 측정한다. 첫 달 지출은 I+O_1이며 D21의 월 gate는 O_m이다. 초기 등록 파일의 지속 보관/조회는 해당 월 O_m에 한 번만 포함한다. 추가 자료·수정·점주 답변 지식화도 O_m에 포함한다.
- 등록 예산환산 개월 I/3,000과 실제 운영비를 뺀 잔여 예산으로의 보전 개월을 구분한다. 실제 매출 회수기간으로 오인하지 않게 표시한다. 가격/환율은 실제 평가 시점의 rate manifest에 고정한다.
- 관측 누락은 0이 아니라 UNKNOWN. 알려진 부분합이 3,000원을 초과하면 FAIL, 그 이하이면서 미확정이면 UNKNOWN, 필요한 포함 비용이 완전할 때만 PASS다. 추정·실제 청구를 분리한다. 초기/운영/평가 지출을 이중 합산하지 않는다.
- p95는 서버 전체 질문 응답 시간의 nearest-rank, n·실패·timeout 포함 여부를 명시하고 전체 요청과 ANSWER만의 값을 모두 보고한다. 오류율/coverage/완전답변 게이트도 통과해야 한다. 사용자 네트워크를 포함한 체감 시간은 별도 기록한다.
- 사용량은 LOW/BASE/HIGH의 첫 달 450/960/1,500 기본 질문과 안정기 27/60/135 질문, 최초 영상 20/30/40분으로 시작한다. 이들은 실측 평균이 아닌 설계 가정이다. 음성 분·문서 페이지·추가 자료·정확 bytes는 자동 계측 전 null이며 부분 추정을 전체 원가로 보고하지 않는다.
- 첫 주 집중·CLARIFY 후속·재시도·1/3/6/12개월 저장 증가를 별도 검증한다. 첫 달 초과를 안정기 평균으로 상쇄하지 않는다. 자세한 수집·리포트·인수는 원가 계측 계획을 따른다.

## 11. 사용자 회신 반영과 남은 관측값

| ID | 회신에 따른 결정 | 후속 처리 | 상태 |
|---|---|---|---|
| U1 | 운영 변동비 3,000원, AI+Storage 포함, 서버/DB 고정비 제외, 등록비 별도 추적 | CP-00의 phase/purpose·예산환산·원가 report 구현 | 제품 결정 완료 |
| U2 | 미래 사용량은 단일 확정치 대신 첫 달/안정기 범위와 store-a 사용자 보고 표본에서 시작 | 6개 입력틀·세 시나리오 확정, 누락 메타데이터·실제 사용량은 CP-00/W0/R0에서 수집 | 계획 결정 완료; 실제 측정 대기 |

현재 C0 계획을 막는 사용자 질문은 없다. Storage 직접 전송의 매장별 귀속 자료는 가용성을 확인해야 하는 구현/관측 항목이다. 귀속 불가하면 UNKNOWN으로 남기고 운영 비용 PASS를 보류한다. 실측 후 등록비 상한/회수 목표·자동 사용량 제한·범위 변경이 필요해지는 경우에만 근거와 대안을 제시해 다시 결정한다.

## 12. 이전 47개 질문의 처리 위치

이 표의 번호는 대화의 C0-01~47을 가리킨다. 실행 TODO의 C0-1~5와 구분한다.

| 질문 | 결정/근거 위치 | 상태 |
|---|---|---|
| 01 책임 경계 | §2 | 결정 |
| 02 공통 기능 소유자 | §2·§4.1 | 결정 |
| 03 공유 파일 | §2 | 결정 |
| 04 계약 변경 | §2 | 결정 |
| 05 snapshot 범위·필드 | §3.4 | 결정 |
| 06 ID 형식 | §3.1 | 결정 |
| 07 knowledge_revision | §4.2 | 결정 |
| 08 fact 불변성 | §3.2 | 결정 |
| 09 승인 범위 | §3.3~3.4 | 결정 |
| 10 RAW | §3.3 | 결정 |
| 11 미확정·충돌 | §3.2·§5.1~5.2 | 결정 |
| 12 삭제·보존 | D20·§4.4 | 결정; 개인정보 별도 절차 유지 |
| 13 index adapter | §4.1 | 결정 |
| 14 공개 주체 | §4.2 | 결정 |
| 15 CAS | §4.2 | 결정 |
| 16 실패 코드 | §5.4 | 결정 |
| 17 event 복구 | §4.3 | 결정 |
| 18 cache | §4.2·§6 | 결정 |
| 19 stale 응답 | §4.2·§6 | 결정 |
| 20 ANSWER 근거 | §5.2 | 결정 |
| 21 CLARIFY/ESCALATE | §5.1~5.2 | 결정 |
| 22 context | §5.1 | 결정 |
| 23 되묻기 상한 | §5.1 | 결정 |
| 24 pending 중복 | §5.3 | 결정 |
| 25 ESCALATE 성공 | §5.3 | 결정 |
| 26 정책 문구 | §5.4 | 결정 |
| 27 ERROR | §5.4 | 결정 |
| 28 점주 원문 상태 | §5.3 | 결정 |
| 29 OWNER_ANSWER | §4.3·§5.3 | 결정 |
| 30 ApplyOwnerAnswer | §4.1·§5.3 | 결정 |
| 31 occurrence 전파 | §5.3 | 결정 |
| 32 인증 범위 | §5.1 | 결정 |
| 33 로그 | §6 | 결정 |
| 34 제한·timeout | §6·원가 계획 | 기술 초기값·원가 범위·시나리오 결정 |
| 35 chat v1 | §7 | 결정 |
| 36 migration | §7 | 순서 결정; 실제 migration 구현·검증 CP-04 |
| 37 flag 조합 | §7·MVP §31-7 | 결정 |
| 38 rollback | §7 | 결정 |
| 39 fixture | §9 | 결정 |
| 40 테스트 계층 | §9 | 결정 |
| 41 hash·버전 | §2·§3.4 | 결정 |
| 42 안전 게이트 | §9~10 | 결정 |
| 43 품질 기준 | D18·§10 | 계산·비용 정책 결정; 실측 승격은 CP-00/05·J1 |
| 44 질문셋·판정자 | §9·TODO R0/R5 | 범위 결정; 실명/실자료 판정은 해당 캠페인 담당 |
| 45 반복·holdout | §10·실험설계 §7 | 결정 |
| 46 동기화 | §8 | 결정 |
| 47 분쟁 처리 | §2·§11 | 계약 공동검토, 사실은 사람 truth, 권한·승인 위반은 차단 |

## 13. 계획 검토와 C0 종료

검토 결과의 발견 사항마다 CP 작업과 검증 사례를 연결했다. C0 계획 결정은 사용자 회신까지 반영해 완료했다. C0 구현 종료는 CP-00A~C 원가 계측과 CP-01~05 schema/fixture·계약 테스트·격리 DB 시퀀스·평가 manifest·소유권의 인수 근거로 판정한다. 실자료 비용·품질 승격은 실제 관측과 고정 workload/rate 결과로 별도 판정한다.

양쪽의 실제 구현·실자료 품질·운영 배포는 C0 결정서 작성과 별도 완료다. 이후 계약 반례가 추가되면 fixture와 해당 생산자/소비자 테스트를 함께 갱신한다.
