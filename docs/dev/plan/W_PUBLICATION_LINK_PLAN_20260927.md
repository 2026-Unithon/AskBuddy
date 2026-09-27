# W→R 공개 연결 구현 계획 — 2026-09-27

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 점주 승인·점주 답변 반영이 R의 색인 준비/활성화와 한 transaction으로 공개되도록 W 쪽 생산자를 연결한다.

**Architecture:**
- 카드 버전을 먼저 "승인 원문(RAW) 블록" 하나 이상으로 고정한다. 출처는 자료 또는 점주 답변이다.
- 공개 후 전체 manifest로 R `KnowledgeContent`를 만들어 `prepare_index_request`를 부른다.
- 짧은 transaction 안에서 publication 잠금 → 카드 CAS → `publish_knowledge` → 공개 포인터 → `activate_prepared_index` → (hook) → commit 순서로 처리한다.
- 점주 답변 worker와 나중 승인은 같은 공개 함수를 hook과 함께 쓴다.

**Tech Stack:** FastAPI, Python 3.12, asyncpg, PostgreSQL 17 + pgvector, pydantic v2, pytest(+pytest-asyncio).

**Spec:**
- `docs/dev/plan/W_CONTRACT_INPUT_20260927.md` (사용자가 "이 제안대로 간다"고 확정)
- `docs/dev/ASKBUDDY_MVP_CURRENT.md` §30·§31 (특히 31-4, 31-6, 31-7)

## Global Constraints

- 저장소 `CLAUDE.md`를 따른다.
  - 모든 DB 함수는 `store_id`를 필수 인자로 받는다. `WHERE store_id = ...` 없는 조회를 쓰지 않는다. store_id는 JWT/worker 신뢰 범위에서 온다.
  - 주석은 한국어이며 주변 코드의 밀도·관용구를 따른다. 상태 문자열은 대문자 상수다.
  - 모델명·차원·임계값은 `api/app/config.py`가 단일 출처다.
  - 실패하면 다음 단계로 넘어가지 말고 명확히 멈춘다. 예외를 삼키지 않는다.
- **R 소유 파일은 수정하지 않는다:** `api/app/reg/*`, `api/app/learn/router.py`, `api/app/learn/answering.py`, `api/app/learn/answer_storage.py`, `api/app/learn/owner_handoff.py`, `api/app/learn/owner_publication.py`, `api/app/learn/approved_renderer.py`, `api/app/learn/v2_router.py`, auth/notifications/team. **호출·import만 한다.** R이 바꿔야 할 것은 Task 6의 인계 문서에 적는다.
- W 주 편집 파일: `api/app/ingest/*`, `api/app/cards/*`, `api/app/learn/knowledge_apply.py`, `api/app/publish/*`(신규 모듈 포함), fact/card/publication migration.
- 공통 파일(`api/app/config.py`, `api/app/main.py`, `api/app/contracts/*`, `api/scripts/verify_r_schema_rebuild.py`)은 이 계획에 적힌 **가산 변경만** 한다.
- migration은 가산형만 쓴다. 기존 행을 파괴·덮어쓰지 않는다. 파일명은 `supabase/migrations/2026092712xxxx_*.sql`이다.
- 기존에 발행된 snapshot의 hash가 바뀌면 안 된다. canonical payload에는 새 필드를 **값이 있을 때만** 싣는다.
- 버전 상수: `glossary_version` 기본 `"glossary/v1"`이다(현재 공개판이 있으면 그 값을 유지한다). `renderer_version`은 `app.learn.approved_renderer.RENDERER_VERSION`이다(import만).
- **커밋·푸시를 하지 않는다**(사용자 규칙). 변경은 작업 트리에 둔다.
- 테스트:
  - 단위: `cd api && .venv/bin/python -m pytest -q <files>`
  - DB 통합: Task 7의 스크립트를 docker PG17 pgvector(127.0.0.1:55439)로 돌린다.

---

### Task 1: 점주 답변 출처를 RAW 원문 계약과 DB에 추가

**Files:**
- Create: `supabase/migrations/20260927120000_w_raw_span_owner_answer.sql`
- Modify: `api/app/contracts/snapshot.py` (`RawSpan`)
- Modify: `api/app/contracts/hashing.py` (`knowledge_content_payload`의 raw_spans 항목)
- Modify: `api/app/config.py` (설정 1개 추가)
- Regenerate: `api/scripts/export_contract_schemas.py`, `api/scripts/build_contract_fixtures.py` 산출물 (`--check` 없이 실행 후 `--check` 통과)
- Test: `api/tests/test_w_raw_span_owner_answer.py`

**Interfaces:**
- Produces:
  - `RawSpan(raw_span_id, source_id: EntityId | None = None, owner_answer_id: EntityId | None = None, text, locator)`. 둘 중 **정확히 하나**만 있어야 한다.
  - `Settings.w_owner_answer_raw_publish: bool = False` (env `W_OWNER_ANSWER_RAW_PUBLISH`)

- [ ] **Step 1: 실패 테스트 작성** — `test_w_raw_span_owner_answer.py`
  - `RawSpan(raw_span_id="1", source_id="2", text="a")`는 통과한다.
  - `RawSpan(raw_span_id="1", owner_answer_id="9", text="a")`는 통과한다.
  - 둘 다 있거나 둘 다 없으면 `ValidationError`다.
  - **기존 hash 불변:** `tests/fixtures/contracts/v1/snapshot.json`을 읽어 `verify_snapshot_hash(snapshot)`가 여전히 통과한다.
  - `knowledge_content_payload`의 source-only span 항목 키 집합이 `{"raw_span_id","source_id","text","locator"}` 그대로다.
  - owner-answer span 항목에는 `"owner_answer_id"`가 추가되고 `"source_id": None`이 실린다.
  - `get_settings().w_owner_answer_raw_publish is False`.
- [ ] **Step 2: 실행해 실패 확인** — `.venv/bin/python -m pytest -q tests/test_w_raw_span_owner_answer.py`
- [ ] **Step 3: 구현**
  - `RawSpan`에 `owner_answer_id`를 추가하고 `source_id`를 optional로 바꾼다. `model_validator(mode="after")`로 정확히 하나를 강제한다.
    - 오류 메시지 예: `"원문 구간은 자료나 점주 답변 중 정확히 하나를 출처로 가진다"`.
  - `hashing.knowledge_content_payload`의 raw_spans dict는 기존 4키를 유지한다. `r.owner_answer_id`가 있을 때만 `"owner_answer_id"` 키를 추가한다.
  - migration(`begin; … commit;`):
    ```sql
    alter table raw_spans alter column source_id drop not null;
    alter table raw_spans add column if not exists owner_answer_id bigint
      references owner_answers(answer_id) on delete restrict;
    alter table raw_spans add constraint raw_spans_one_origin_check
      check ((source_id is null) <> (owner_answer_id is null));
    ```
    - `owner_answers`에는 store_id가 없다. 매장 일치는 trigger로 강제한다. `raw_spans.store_id`가 `pending_questions.store_id`(owner_answers.question_id 경유)와 다르면 `raise exception`한다. insert/update 시 검사한다.
    - 기존 source FK `(store_id, source_id)`는 유지한다(null이면 FK 미적용).
    - 주석: `comment on column raw_spans.owner_answer_id is '점주 답변이 출처인 승인 원문. 자료 출처와 동시에 두지 않는다 (W 2026-09-27)'`.
  - `config.py` Settings에 `w_owner_answer_raw_publish: bool = False`를 추가한다. 주석은 "R이 출처 없는 원문 인용을 처리하기 전까지 점주 답변 출처 카드를 공개하지 않는다".
  - `cd api && .venv/bin/python scripts/export_contract_schemas.py && .venv/bin/python scripts/build_contract_fixtures.py` 후 두 스크립트의 `--check`가 통과해야 한다. 기존 fixture hash가 바뀌면 멈추고 보고한다.
- [ ] **Step 4: 테스트 통과 확인** — Step 2 명령 + `tests/test_contracts.py tests/test_fixtures_cp03.py tests/test_contracts_cp02.py`

---

### Task 2: 카드 버전 → RAW 블록 고정과 KnowledgeContent 조립

**Files:**
- Create: `api/app/publish/content.py`
- Test: `api/tests/test_w_publish_content.py`

**Interfaces:**
- Consumes: Task 1의 `RawSpan`, `Settings.w_owner_answer_raw_publish`
- Produces:
  ```python
  class NoProvenance(RuntimeError): ...   # 카드 버전에 공개 가능한 출처가 없다
  RAW_SPAN_MAX = 4000
  MAX_BLOCKS = 20

  async def ensure_raw_blocks(conn, *, store_id: int, card_id: int, card_version_id: int,
                              allow_owner_answer: bool) -> None
  async def current_manifest(conn, *, store_id: int) -> dict[int, int]      # {card_id: card_version_id}
  async def build_knowledge_content(conn, *, store_id: int, manifest: dict[int, int],
                                    glossary_version: str) -> KnowledgeContent
  ```

**동작 규칙:**
- `ensure_raw_blocks`
  - 해당 버전에 `card_version_blocks`가 이미 있으면 아무것도 하지 않는다(멱등, 불변).
  - 없으면 `card_versions`(store_id·card_id·version_id 일치 확인)의 `content`를 원문으로 쓴다.
    - 빈 줄(`\n\n`) 경계로 `RAW_SPAN_MAX`자 이하 조각을 만든다. 한 문단이 넘치면 문자 단위로 자른다. 원문 공백은 보존한다.
    - 조각마다 `raw_spans` 1행과 RAW 블록 1개를 만든다. `block_id = f"raw{n}"`, `block_order = n`.
    - 조각이 `MAX_BLOCKS`를 넘으면 `ValueError`로 멈춘다.
  - 출처 결정:
    - (1) `knowledge_cards.source_id`가 있으면 그 자료다. locator는 `WHOLE_SOURCE`다.
    - (2) 없고 `allow_owner_answer`면 `owner_answers.card_id = card_id`인 가장 이른 `answer_id`다. 같은 매장이어야 한다.
    - (3) 둘 다 없으면 `NoProvenance`.
- `current_manifest`
  - 현재 공개판(`knowledge_publications.current_snapshot_id`)이 있으면 그 `snapshot_card_versions` 중 지금 `review_status <> 'EXCLUDED'`인 카드다.
  - 없으면(첫 공개) `review_status='APPROVED' and published_version_id is not null`인 카드 전체다.
- `build_knowledge_content`
  - manifest의 각 버전에 대해 블록·원문을 읽어 `PublishedCard`를 만든다.
    - `entity_id = card_id`: 대상 테이블이 아직 없음. **Ruling**으로 기록한다.
    - `title`은 `card_versions.title`의 앞 120자, `variant`는 기본값.
  - `KnowledgeContent(store_id, glossary_version, renderer_version=RENDERER_VERSION, cards, fact_revisions=(), raw_spans)`를 만든다.
  - pydantic 검증을 통과해야 한다.

- [ ] **Step 1: 실패 테스트** — 가짜 conn(`AsyncMock`, `fetch/fetchrow/fetchval/execute` 기록)으로 검증한다.
  - 블록이 있는 버전 → insert 0회.
  - 5000자 본문(빈 줄 2개 포함) → raw_spans 2행 이상, 모두 4000자 이하, 이어 붙이면 원문과 동일.
  - source 없음 + `allow_owner_answer=False` → `NoProvenance`.
  - source 없음 + owner answer 있음 + True → owner_answer_id 출처.
  - `build_knowledge_content` 결과가 `KnowledgeContent`이고 `renderer_version == RENDERER_VERSION`.
  - 모든 SQL 인자에 store_id가 들어간다(`execute`/`fetch` 호출의 첫 인자 검사).
- [ ] **Step 2: 실패 확인** — `.venv/bin/python -m pytest -q tests/test_w_publish_content.py`
- [ ] **Step 3: 구현** (`app/publish/content.py`, 한국어 docstring)
- [ ] **Step 4: 통과 확인 + 격리 검사** — `python3 ../.claude/skills/store-isolation-check/check_store_id.py app/publish`

---

### Task 3: 공개 조정자 `publish_cards`

**Files:**
- Create: `api/app/publish/approval.py`
- Modify: `api/app/publish/__init__.py` (export 추가만)
- Test: `api/tests/test_w_publish_approval.py`

**Interfaces:**
- Consumes: Task 2 `ensure_raw_blocks`, `current_manifest`, `build_knowledge_content`, `NoProvenance`; `app.publish.service.publish_knowledge`; `app.reg.index_preparation.prepare_index_request`, `activate_prepared_index`(import만); `app.contracts.publication.PrepareIndexRequest/TrustedScope/IdempotencyKey`; `app.contracts.hashing.digest/knowledge_content_payload/snapshot_payload`.
- Produces:
  ```python
  @dataclass(frozen=True)
  class CardChange:
      card_id: int
      expected_draft_version_id: int
      target_card_version_id: int

  @dataclass(frozen=True)
  class PublishCardsResult:
      status: str          # PUBLISHED | ALREADY_APPLIED | STALE | PREPARE_FAILED | NO_PROVENANCE
      snapshot_id: int | None = None
      knowledge_revision: int | None = None
      error_code: str | None = None

  InTransactionHook = Callable[[asyncpg.Connection, int, int], Awaitable[None]]  # (conn, snapshot_id, knowledge_revision)

  async def publish_cards(pool, *, store_id: int, member_id: int, actor_user_id: int,
                          changes: list[CardChange], idempotency_key: str, usage_context,
                          in_transaction: InTransactionHook | None = None) -> PublishCardsResult
  ```

**순서 (W_CONTRACT_INPUT ③):**
1. **준비 (연결은 짧게):**
   - 한 연결에서 publication(`publication_revision`, `knowledge_revision`, `current_snapshot_id`)과 현재 glossary를 읽는다.
   - 각 change의 카드가 `draft_version_id == expected_draft_version_id`이고, `target == expected`이며, EXCLUDED가 아닌지 확인한다. 아니면 `STALE`.
   - manifest를 `current_manifest`로 만들고, changes로 교체·추가한다.
   - allow_owner_answer는 `get_settings().w_owner_answer_raw_publish`다.
   - 각 manifest 버전에 `ensure_raw_blocks`를 부른다(짧은 transaction).
     - **changed 카드**가 `NoProvenance`이면 `NO_PROVENANCE`로 멈춘다.
     - **기존 manifest 카드**가 `NoProvenance`이면 manifest에서 빼고 `logger.warning`한다. **Ruling**으로 기록한다.
   - `build_knowledge_content`를 부른다.
2. **R 준비 (연결 없이):**
   - `PrepareIndexRequest(scope=TrustedScope(store_id, member_id), idempotency=IdempotencyKey(key=idempotency_key, body_hash=digest(request_without_idempotency)), card_ids=all manifest card ids, content_hash=digest(knowledge_content_payload(content)), expected_publication_revision=..., expected_card_revisions=(), embedding_model=get_settings().embedding_model, glossary_version, renderer_version)`
   - body_hash는 R 규칙 `digest(request.model_dump(mode='json', exclude={'idempotency'}))`와 같다. 요청을 먼저 dummy hash로 만들고 계산한 뒤 교체한다.
   - `prepare_index_request(pool, request=..., content=..., usage_context=...)`. `PREPARED`가 아니면 `PREPARE_FAILED(error_code=result.error.code)`.
3. **공개 transaction (한 연결):**
   1. publication 행을 `for update`로 잠근다.
   2. 카드를 `card_id` 오름차순으로 `for update` 잠근 뒤 CAS를 다시 한다. 실패하면 `STALE`로 rollback한다.
   3. `snapshot_hash`를 계산한다: `knowledge_revision = 현재+1`인 snapshot payload digest(`digest(snapshot_payload(...))`와 같은 규칙; `PublishedKnowledgeSnapshot`을 임시 id로 만들 필요 없이 dict로 계산).
   4. `publish_knowledge(conn, store_id, member_id, idempotency_key, body_hash=digest([asdict(c) for c in changes]), expected_publication_revision, snapshot_hash, glossary_version, renderer_version, card_versions=manifest items)`.
      - `ALREADY_APPLIED`면 활성화 없이 그 결과를 반환한다(이미 커밋된 공개).
      - `STALE`면 rollback하고 `STALE`.
   5. changed 카드에 `published_version_id = target`, `review_status='APPROVED'`, `excluded_at/excluded_by/needs_review_reason = null`을 적고 `card_events`(repo.add_event, action `APPROVE`/`PUBLISH_EDIT`)를 남긴다.
   6. `activate_prepared_index(conn, store_id=, prepared_id=int(prepared.prepared_id), snapshot_id=)`
   7. `in_transaction`이 있으면 `await in_transaction(conn, snapshot_id, knowledge_revision)`.
   8. 예외는 삼키지 않는다. transaction 밖으로 올려 전체 rollback한다.

- [ ] **Step 1: 실패 테스트** — prepare/activate/publish_knowledge/content 함수를 patch한다.
  - 정상 → 호출 순서가 `prepare` → (tx) `publish_knowledge` → 카드 update → `activate` → hook이고, 결과는 `PUBLISHED`.
  - 준비 단계 CAS 불일치 → prepare 호출 0회, `STALE`.
  - tx 안 CAS 불일치(준비 후 draft 변경) → publish_knowledge 0회, `STALE`.
  - prepare 실패 → tx 진입 0회.
  - activate가 `ApiError` → 예외 전파, hook 0회.
  - hook 예외 → 전파.
  - `publish_knowledge`가 `ALREADY_APPLIED` → activate 0회, 결과 `ALREADY_APPLIED`.
  - changed 카드 NoProvenance → `NO_PROVENANCE`, prepare 0회.
  - PrepareIndexRequest의 `card_ids` 집합 == content 카드 집합, `expected_card_revisions == ()`.
- [ ] **Step 2: 실패 확인** — `.venv/bin/python -m pytest -q tests/test_w_publish_approval.py`
- [ ] **Step 3: 구현**
- [ ] **Step 4: 통과 확인 + 격리 검사**

---

### Task 4: 승인 버튼을 새 흐름으로 교체 (옛 즉시 공개 경로 제거)

**Files:**
- Modify: `api/app/cards/router.py` (`approve_card`)
- Test: `api/tests/test_w_approve_route.py`

**Interfaces:**
- Consumes: Task 3 `publish_cards`, `CardChange`, `PublishCardsResult`
- Produces: `POST /cards/{card_id}/approve`의 응답 타입(`CardMutationResult`)은 그대로다. 오류 매핑:
  - `STALE` → 409 `CARD_VERSION_CONFLICT`
  - `NO_PROVENANCE` → 409 `CARD_NO_PROVENANCE`("출처를 확인할 수 없는 카드는 아직 공개할 수 없습니다.")
  - `PREPARE_FAILED` → 502 `CARD_PUBLISH_FAILED`(retryable)
  - `ALREADY_APPLIED`/`PUBLISHED` → 현재 카드 mutation 반환

**규칙:**
- 기존 CAS 검사(404/409 DRAFT_MISSING/EXCLUDED)는 유지한다.
- `idempotency_key = f"approve:{card_id}:{draft_version_id}"`: 같은 초안의 재요청은 같은 공개로 수렴한다.
- `usage_context`는 기존 `card_usage_context(db, store_id, card_id)`를 쓴다(stage를 `EMBED`로 맞춘다).
- `member_id`는 JWT claims에서 꺼낸다. 없으면 `store_members`에서 (store_id, user_id)로 조회한다. 주변 코드 관례를 따른다.
- **옛 색인 호환:** `find_owner_answer_candidates`(R 파일이 아닌 `knowledge_loop.py`)의 `match_cards`가 아직 `card_embeddings`를 읽는다. 그래서 `in_transaction` hook 안에서 기존 `prepare_embedding`(tx 밖에서 미리 준비)과 `embed_card`로 **호환 쓰기만** 유지한다. 옛 색인에만 넣고 끝나던 즉시 공개 경로는 제거한다. **Ruling**으로 기록하고, 인계 문서에 "옛 색인 완전 제거는 점주답변 후보 검색이 새 색인으로 옮겨진 뒤"라고 적는다.

- [ ] **Step 1: 실패 테스트** — `publish_cards`를 patch하고 라우트 함수를 직접 호출(기존 cards 라우트 테스트 관례를 따른다. 없으면 함수 호출 + 가짜 db).
  - 결과 상태별 HTTP 코드 매핑 4종
  - `CardChange(expected=target=draft_version_id)`
  - 고정된 idempotency key 형식
- [ ] **Step 2~4:** 실패 확인 → 구현 → `tests/test_cards.py` 포함 통과

---

### Task 5: 점주 답변 반영 worker

**Files:**
- Create: `api/app/cards/owner_answer_worker.py`
- Modify: `api/app/config.py` (`w_owner_answer_worker_enabled: bool = False`, `w_owner_answer_worker_interval_sec: int = 10`)
- Modify: `api/app/main.py` (lifespan에서 플래그가 켜졌을 때만 loop task 시작·종료. 가산 변경)
- Test: `api/tests/test_w_owner_answer_worker.py`

**Interfaces:**
- Consumes:
  - `app.learn.owner_handoff.claim_owner_event/heartbeat_owner_event/finish_owner_event`(import만)
  - `app.learn.knowledge_loop.build_knowledge_plan`(import만)
  - Task 3 `publish_cards`
  - `ApplyOwnerAnswerResult`
- Produces:
  ```python
  async def process_next_owner_event(pool, *, store_id: int) -> str | None
      # 반환: None(할 일 없음) | 'STALE' | 'LINKED' | 'REVIEW' | 'PUBLISHED' | 'FAILED'
  async def run_owner_answer_worker(pool, *, stop: asyncio.Event) -> None
  ```

**동작:**
1. `claim_owner_event(pool, store_id=)`. None이면 None, `stale`이면 `'STALE'`.
2. 짧은 연결로 owner answer 원문과 질문을 읽는다. `r_owner_answer_revisions` → `owner_answers.answer_text`, `pending_questions.question_text` 계열이며 store_id로 제한한다. 실제 컬럼명은 migration을 확인한다.
3. `build_knowledge_plan(conn, store_id, question, answer, usage_context=OPERATING/PRODUCT/RELATION, operation_id=f"owner-event:{event_id}")`. 긴 단계 사이에 `heartbeat_owner_event`를 부르고, False면 중단(FAILED, retryable)한다.
4. 계획의 relation별 처리:
   - `IDENTICAL` → **LINKED**
     - 대상 카드가 현재 공개판 manifest에 있어야 한다. 없으면 REVIEW로 강등한다.
     - tx: `finish_owner_event(conn, ..., ApplyOwnerAnswerResult(status='LINKED', card_id=str(target), knowledge_revision=str(current)))`.
     - `knowledge_change_proposals`에 answer_id 1행(status `LINKED`, result_card_id·version)을 같은 tx에 멱등 insert한다(`on conflict (answer_id) do nothing`).
   - `SUPPLEMENT`/`CONFLICT` → **REVIEW**
     - tx: proposal(status `PENDING_REVIEW`)을 멱등 insert하고 `finish_owner_event(... status='REVIEW')`.
   - `NEW` → **PUBLISHED**
     - tx1: 새 카드를 만든다. `knowledge_cards` insert → 생성된 draft 버전의 `change_source='OWNER_ANSWER'`로 바꾸고 `owner_answers.card_id` 연결, proposal insert(status `ANALYZED`, answer_id).
     - 기존 `publish_new_proposal`의 카드 생성 SQL을 **함수로 추출해 공유**한다(`knowledge_apply.py`, W 파일). 중복 복사하지 않는다.
     - `publish_cards(changes=[CardChange(card, draft, draft)], idempotency_key=f"owner-answer:{owner_answer_id}", in_transaction=hook)`
     - hook: proposal을 `PUBLISHED`로 바꾸고 `finish_owner_event(conn, ..., ApplyOwnerAnswerResult(status='PUBLISHED', card_id=str(card), knowledge_revision=str(kr)))`.
     - 결과가 `NO_PROVENANCE`면 REVIEW로 처리한다(플래그 OFF일 때 자연 경로). `STALE`/`PREPARE_FAILED`면 FAILED(retryable)다.
   - 예외·실패 → 별도 tx에서 `finish_owner_event(... status='FAILED', retryable=..., error=ErrorDetail(code=..., message=...))`. 코드는 `app.contracts.errors.ERROR_TABLE`에 있는 값만 쓴다.
5. `run_owner_answer_worker`:
   - `interval`마다 미소비 `OWNER_ANSWER_SUBMITTED` 사건이 있는 store_id 목록을 읽고(store별로 제한된 조회), store마다 `process_next_owner_event`를 None이 나올 때까지 돈다.
   - 예외는 로깅하고 다음 주기로 넘어간다. `stop`이 설정되면 종료한다.
   - store 목록 조회는 매장 가로지르기 조회이므로 `# store-isolation-ok: worker 가 처리할 매장 목록만 읽는다` 주석을 단다.

- [ ] **Step 1: 실패 테스트** — owner_handoff 함수, build_knowledge_plan, publish_cards를 patch한다.
  - relation 4종 → 반환값 4종, finish 결과 status 일치.
  - NEW에서 finish가 publish_cards의 hook 안에서만 호출된다.
  - `NO_PROVENANCE` → REVIEW.
  - 예외 → FAILED finish가 별도 tx.
  - heartbeat False → FAILED.
  - claim None → None, stale → 'STALE' (finish 0회).
- [ ] **Step 2~4:** 실패 확인 → 구현 → 통과 + 격리 검사 + `tests/test_knowledge_loop.py` 회귀

---

### Task 6: 나중 승인(REVIEW → 공개) W 함수와 R 인계 문서

**Files:**
- Modify: `api/app/learn/knowledge_apply.py` (W 파일)
- Create: `docs/dev/plan/W_TO_R_PUBLICATION_HANDOFF_20260927.md`
- Test: `api/tests/test_w_owner_proposal_approval.py`

**Interfaces:**
- Consumes: Task 3 `publish_cards`, Task 5에서 추출한 카드 생성 함수
- Produces:
  ```python
  OwnerReviewNotifier = Callable[[asyncpg.Connection, int, int, int, int], Awaitable[None]]
  # (conn, owner_answer_id, card_id, card_version_id, knowledge_revision) — R 이 제공할 finish_owner_review 자리

  async def approve_owner_proposal(pool, *, store_id: int, member_id: int, actor_user_id: int,
                                   proposal_id: int, usage_context,
                                   notify_r: OwnerReviewNotifier | None = None) -> PublishCardsResult
  ```

**동작:**
- proposal을 잠그고 읽는다. status가 `PENDING_REVIEW`/`ANALYZED`/`FAILED`가 아니면 `ValueError`.
  - NEW → 새 카드 생성(Task 5 공유 함수).
  - SUPPLEMENT/CONFLICT → 대상 카드에 새 draft 버전을 만든다. `repo.create_draft`, change_source는 `OWNER_ANSWER`로 갱신하고 expected=현재 draft.
- `publish_cards(..., idempotency_key=f"owner-proposal:{proposal_id}", in_transaction=hook)`
- hook: proposal `PUBLISHED`·result ids를 적고, `notify_r`가 있으면 호출한다.
- `notify_r`가 None이면 경고 로그를 남긴다. "R 완료 접점 미연결 — 인계 문서 참조".
- 기존 `publish_new_proposal`/`publish_existing_proposal`(옛 즉시 공개)은 R 라우트가 부르므로 **삭제하지 않는다**. 인계 문서에 "라우트를 approve_owner_proposal로 교체"를 적는다.

**인계 문서 내용 (R이 할 일, 각 항목에 이유·파일·W 쪽 준비된 함수):**
1. `learn/router.py` `POST /learn/knowledge-proposals/{id}/approve` → `approve_owner_proposal` 호출로 교체한다. `notify_r`로 `finish_owner_review`를 넘긴다.
2. R `finish_owner_review(conn, *, store_id, owner_answer_id, card_id, card_version_id, knowledge_revision)`를 제공한다.
   - REVIEW 상태 owner_answer만 PUBLISHED로 전환한다.
   - 최신 revision이 아니면 거절한다.
   - 알림·상태를 같은 tx에 기록하고, proposal_id 단위로 멱등 처리한다.
3. `RawSpan.source_id`가 None일 수 있다(점주 답변 출처). `answer_storage.py:220` 부근의 source_id 수집과 `approved_renderer`의 `Citation(source_id=...)` 처리를 보완한다. 보완 뒤 W 플래그 `W_OWNER_ANSWER_RAW_PUBLISH=true`로 켠다.
4. `prepare_index_request` wrapper의 `expected_card_revisions`를 카드별 매핑(`card_id / expected_draft_version_id / target_card_version_id`)으로 바꾸는 계약 변경(선택). W는 현재 빈 배열 + 자체 CAS로 동작한다.
5. 준비 단위가 전체 manifest라 매 공개마다 전체 재임베딩이 된다. 바뀌지 않은 카드 색인 재사용 여부를 R이 판단한다.
6. 점주답변 후보 검색(`match_cards` → `card_embeddings`)을 새 색인으로 옮기면 W가 옛 색인 호환 쓰기를 제거한다.

- [ ] **Step 1: 실패 테스트** — NEW/SUPPLEMENT 각각의 publish_cards 인자, hook에서 notify_r 호출 인자, notify_r None → 경고 로그, 잘못된 status → ValueError.
- [ ] **Step 2~4:** 실패 확인 → 구현 → 통과 + 격리 검사
- [ ] **Step 5:** 인계 문서 작성

---

### Task 7: 합성 카드 2장 DB 통과 시험

**Files:**
- Create: `api/scripts/verify_w_publication_flow.py`
- Modify: `api/scripts/verify_r_schema_rebuild.py` (W 검증 호출 1줄 추가 — 기존 `verify_w_ingest_recovery` 호출 옆)

**Interfaces:**
- Consumes: Task 1~6 전부
- Produces: `async def verify(pool, admin) -> None`. 새 UUID DB에서 모든 migration이 적용된 상태를 받는다.

**시나리오 (각 `print("PASS W publish", name)`):**
1. 매장·점주·카드 A/B를 seed한다(source 있음). A/B 초안을 첫 승인 → 판 1, snapshot에 A·B, R `read_current_index`로 두 카드가 보인다.
2. A만 수정·재승인 → A는 새 버전, B는 기존 버전(snapshot_card_versions로 확인), knowledge_revision +1.
3. 준비 후 A가 다시 수정되면(prepare와 tx 사이에 draft 변경 주입) → `STALE`, 공개판 불변.
4. activate 실패 주입(`activate_prepared_index` patch로 ApiError) → 예외, 공개판·카드 포인터·snapshot 수 불변.
5. 같은 idempotency_key 재요청 → `ALREADY_APPLIED`, snapshot 수 불변.
6. A 제외 후 R 검색 조회 조건(`knowledge_cards.review_status='APPROVED'`)으로 A가 빠지고, 과거 snapshot의 A 행은 남아 있다.
7. 출처 없는 카드 승인 → `NO_PROVENANCE`(플래그 OFF). 플래그 ON(patch) + owner answer 연결 → 공개되고 raw_spans.owner_answer_id가 채워진다.
8. 다른 매장 answer로 raw_span insert 시도 → trigger 예외.
9. 점주 답변 worker (R의 owner outbox seed는 `verify_r_owner_delivery.py`의 seed 방식을 따른다):
   - IDENTICAL → LINKED, NEW → PUBLISHED(새 카드가 snapshot에 있음), SUPPLEMENT → REVIEW.
   - `build_knowledge_plan`은 합성 대역으로 relation을 고정한다.
- 임베딩: `prepare_index` 경로의 embedder·settings를 `verify_r_index.py`처럼 합성으로 patch한다(1536차원 벡터, 모델명 설정과 일치).

- [ ] **Step 1:** 스크립트 작성
- [ ] **Step 2:** 로컬 실행
  ```bash
  docker run -d --rm --name askbuddy-w-publish -p 127.0.0.1:55439:5432 \
    -e POSTGRES_PASSWORD=synthetic-local-test -e POSTGRES_DB=usage_verify pgvector/pgvector:pg17
  cd api && PYTHONPATH=. .venv/bin/python -B scripts/verify_r_schema_rebuild.py
  docker stop askbuddy-w-publish
  ```
  기대: 모든 migration PASS, 기존 R/W 검증 PASS, 새 `PASS W publish` 9개 이상.
- [ ] **Step 3:** 전체 단위 테스트 `.venv/bin/python -m pytest -q tests` 통과, 격리 검사 새 위반 0.
