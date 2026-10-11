# W → R 공개 연결 인계 (2026-09-27)

> **R 로컬 후속(2026-09-27):** §1~3의 REVIEW 완료·출처 소비는 [통합 검증](../review/R_OWNER_CITATION_INTEGRATION_20260927.md)을 진행했고, 사용자 요청으로 §5 재사용은 **A 방식**을 구현했다. 전체 manifest를 유지하며 현재 공개 색인과 카드 버전·블록·실제 입력 및 모델/사전/설정이 같은 벡터만 복사한다. [재사용 검증·제한](../review/R_INDEX_REUSE_20260927.md). 아래 “매번 전체 재임베딩”은 PR #24 당시 동작이며, 이번 로컬 변경 이후는 불일치 블록만 재임베딩한다. 아직 commit/push되지 않았고 §6의 옛 색인 호환 호출은 별개로 남아 있다.

> 받는 사람: 김선재 (R 담당). 이 문서만 읽고 R 쪽 변경을 시작할 수 있게 썼다.
> W 는 R 소유 파일(`api/app/reg/*`, `api/app/learn/router.py`, `answering.py`,
> `answer_storage.py`, `owner_handoff.py`, `owner_publication.py`, `approved_renderer.py`,
> `v2_router.py`)을 고치지 않았다. 아래 줄 번호는 2026-09-27 작업 트리 기준이다.
> 관련 계획: `docs/dev/plan/W_PUBLICATION_LINK_PLAN_20260927.md`.

## 0. 지금 W 쪽에 무엇이 생겼나

| 항목 | 위치 | 요약 |
|---|---|---|
| 공개 조정자 | `api/app/publish/approval.py` `publish_cards` | 카드 버전 → RAW 블록 고정 → R `prepare_index_request` (연결 없이) → 한 트랜잭션에서 공개판·카드 포인터·`activate_prepared_index`·hook 을 함께 커밋. 결과 `PUBLISHED / ALREADY_APPLIED / STALE / PREPARE_FAILED / NO_PROVENANCE / INVALID_CONTENT / EMPTY_MANIFEST`. manifest 는 **현재 카드 포인터**(`review_status='APPROVED'` 이고 `published_version_id` 있는 카드)로 만든다(5번). `changes=[]` 는 "현재 포인터 그대로 재발행" |
| 카드 승인 라우트 | `api/app/cards/router.py` `approve_card` | 옛 즉시 색인 대신 `publish_cards` 호출. `NO_PROVENANCE` → 409 `CARD_NO_PROVENANCE`, `INVALID_CONTENT` → 409 `CARD_CONTENT_INVALID`, `STALE` 과 `PREPARE_FAILED`(코드 `STALE_PUBLICATION`·`STALE_KNOWLEDGE`·`IDEMPOTENCY_CONFLICT`) → 409 `CARD_VERSION_CONFLICT`, 그 밖의 `PREPARE_FAILED` → 502 |
| 카드 제외·복원 라우트 | `api/app/cards/router.py` `exclude_card`·`restore_card` | 상태 변경 트랜잭션은 그대로 커밋하고, 그 뒤 best-effort 로 `publish_cards(changes=[], idempotency_key="exclude:{card}:{event}" / "restore:{card}:{event}")` 재발행. 실패는 로그만 남기고 요청은 성공(R 조회가 이미 `review_status` 로 거르고, 다음 공개가 현재 포인터로 스스로 회복) |
| 점주 답변 worker | `api/app/cards/owner_answer_worker.py` | `OWNER_ANSWER_SUBMITTED` claim → 관계 분석(plan) → `LINKED / REVIEW / PUBLISHED / FAILED` 로 R `finish_owner_event` 보고. PUBLISHED 보고는 **발행 트랜잭션 hook 안에서만** 한다(보고 실패 = 발행 롤백) |
| 나중 승인 함수 | `api/app/learn/knowledge_apply.py` `approve_owner_proposal` | 검수 대기(REVIEW) 제안을 점주가 승인할 때 `publish_cards` 로 공개. R 완료 접점 `notify_r` 을 hook 에서 부른다 |

W 플래그 (둘 다 기본 `false`, `api/app/config.py`):

- `W_OWNER_ANSWER_WORKER_ENABLED` — worker 를 켠다. 끄면 점주 답변 사건은 쌓이기만 한다.
  켜면 claim → plan → 결과별로
  - IDENTICAL 이고 대상이 현재 공개판에 있으면 `LINKED`
  - SUPPLEMENT·CONFLICT·공개판에 없는 IDENTICAL·자동 공개 불가 NEW 는 제안을 `PENDING_REVIEW` 로 남기고 `REVIEW`
  - 자동 공개 가능 NEW 는 초안 카드를 만들고 `publish_cards` → hook 안에서 `PUBLISHED`
  - 그 밖의 실패는 별도 트랜잭션에서 `FAILED`(재시도 여부는 `ERROR_TABLE`)
- `W_OWNER_ANSWER_RAW_PUBLISH` — 점주 답변이 출처인 카드 판의 RAW 블록을 `owner_answer_id` 출처로 공개할지.
  대상은 두 가지다: (a) 자료 출처가 없는 점주 답변 카드(`knowledge_cards.source_id` 없음),
  (b) **자료 출처가 있는 기존 카드에 얹은 점주 답변 판**(SUPPLEMENT·CONFLICT 승인, `card_versions.owner_answer_id` 있음).
  (b)도 카드의 원래 자료가 아니라 그 점주 답변을 출처로 싣는다 — 자료에 없는 내용을 자료 근거로 인용하지 않기 위해서다
  (`supabase/migrations/20260927130000_w_card_version_owner_answer.sql`, `app/publish/content.py` `ensure_raw_blocks`).
  **false 인 동안** 두 경우 모두 공개되지 않는다:
  worker 는 `NO_PROVENANCE` 를 받아 `REVIEW` 로 넘기고, 카드 승인 라우트는 409 `CARD_NO_PROVENANCE` 를, `approve_owner_proposal` 은 `NO_PROVENANCE` 를 돌려준다.
  다른 카드 승인 때 manifest 에 함께 실리는 이런 카드(예: 레거시 경로로 이미 공개된 점주 답변 카드)는 경고 로그와 함께 그 판에서만 빠진다.
  **켜면** manifest 가 현재 포인터로 만들어지므로 다음 공개(아무 카드 승인·제외·복원) 한 번에 그동안 빠졌던 카드가 저절로 다시 실린다 — 따로 재승인할 필요가 없다.
  R 이 3번 항목을 끝내기 전에는 켜지 말 것.

---

## 1. 옛 제안 승인 라우트를 `approve_owner_proposal` 로 교체

- **무엇을**: `POST /learn/knowledge-proposals/{proposal_id}/approve`
  (`api/app/learn/router.py:837` 데코레이터, `:838` `approve_knowledge_proposal`)의 본문을
  `prepare_proposal`(`:858`) + `publish_new_proposal`(`:861`) / `publish_existing_proposal`(`:865`) 대신
  `approve_owner_proposal` 호출로 바꾼다. `notify_r` 에 2번의 `finish_owner_review` 를 넘긴다.
- **왜**:
  - 옛 함수는 `publish_cards` 를 거치지 않아 공개판(snapshot)·새 색인이 오르지 않는다. R 답변 경로는 공개판만 보므로 승인해도 답에 반영되지 않는다.
  - worker 가 NEW 제안을 REVIEW 로 넘길 때(자동 공개 불가 또는 `NO_PROVENANCE`) **초안 카드를 이미 만들어 `owner_answers.card_id` 에 걸어 둔다.**
    옛 `publish_new_proposal` 은 무조건 새 카드를 만들므로, 교체 전까지는 같은 답변으로 **카드가 두 개** 생길 수 있다.
    `approve_owner_proposal` 은 그 카드를 재사용한다.
  - 옛 함수는 삭제하지 않았다(라우트가 import 한다). 교체가 끝나면 W 가 지운다.
- **W 쪽 준비된 함수** (`api/app/learn/knowledge_apply.py`):

  ```python
  OwnerReviewNotifier = Callable[[asyncpg.Connection, int, int, int, int], Awaitable[None]]
  # (conn, owner_answer_id, card_id, card_version_id, knowledge_revision)

  async def approve_owner_proposal(pool, *, store_id: int, member_id: int, actor_user_id: int,
                                   proposal_id: int, usage_context,
                                   notify_r: OwnerReviewNotifier | None = None) -> PublishCardsResult
  ```

  - `pool` 은 `app.deps.get_pool()`. 라우트의 `db` 커넥션에 트랜잭션을 연 채로 부르지 않는다(함수가 연결을 스스로 짧게 잡는다).
  - `member_id` 는 점주의 `store_members.member_id`, `actor_user_id` 는 JWT user_id. `store_id` 는 JWT 값.
  - `usage_context` 는 `UsageContext(stage="EMBED", cost_phase="OPERATING", cost_purpose="PRODUCT", ...)` 형식.
  - 동작: 짧은 트랜잭션(공개판 → 제안 → 카드 잠금)에서 승인 가능 상태(`ANALYZED / PENDING_REVIEW / FAILED`) 확인 후 초안 준비 → 커밋 →
    `publish_cards(idempotency_key=f"owner-proposal:{proposal_id}")`. NEW 는 worker 가 만든 카드를 재사용하거나 새로 만들고,
    NEW 는 실제로 쓴 카테고리(삭제·비활성이면 기타)를 제안에 되써 둔다.
    SUPPLEMENT·CONFLICT 는 대상 카드 공개판 위에 `change_source='OWNER_ANSWER'`, `owner_answer_id` 가 적힌 초안을 얹는다.
    - 제안 이후 대상 카드의 공개 판이 바뀌었으면(`published_version_id != target_version_id`) `ValueError` — 옛 기준 답으로 되돌리지 않는다.
    - 대상 카드에 이 제안의 것이 아닌 미공개 초안(점주 편집 등)이 있으면 `ValueError` — 덮지 않는다.
    - 앞선 시도(`STALE`·`PREPARE_FAILED`)가 얹은 이 제안의 초안(점주 답변 판, 같은 answer_id·제목·본문)이 있으면 재사용한다.
    hook 에서 제안을 다시 잠가 여전히 승인 가능한지 보고 `PUBLISHED`·`result_card_id`·`result_version_id` 를 기록한 뒤 `notify_r` 을 부른다.
  - 예외·결과 매핑(라우트에서):
    - `LookupError` → 404, `ValueError`(승인 불가 상태, 대상 카드 없음·제외, 공개 판 변경, 다른 미공개 초안) → 409
    - `PUBLISHED` → 성공
    - `ALREADY_APPLIED` → 성공(재요청). 이미 `PUBLISHED` 이고 result id 가 있는 제안이면 준비·공개 없이 곧바로 돌려준다.
      이때 `snapshot_id`·`knowledge_revision` 은 비어 있을 수 있으니 응답의 card_id/version_id 는 제안의
      `result_card_id`/`result_version_id` 를 읽어 채운다. `notify_r` 은 다시 부르지 않는다(첫 공개 트랜잭션에서 끝났다).
    - `NO_PROVENANCE` → 409 (3번 전까지 점주 답변 NEW 카드와 기존 카드의 점주 답변 판이 모두 여기 걸린다)
    - `INVALID_CONTENT` → 409 (제안 본문이 비었거나 RAW 블록 20개 상한을 넘는다. 다시 해도 같다)
    - `STALE` → 409 재시도. `PREPARE_FAILED` 중 `error_code` 가 `STALE_PUBLICATION`·`STALE_KNOWLEDGE`·`IDEMPOTENCY_CONFLICT` 이면
      경합에서 진 것이므로 409 재시도, 그 밖의 `PREPARE_FAILED` → 502 `retryable` (카드 승인 라우트와 같은 매핑)
    - 실패 결과에서 제안은 그대로 남아 다시 승인할 수 있다.
  - `notify_r=None` 이면 경고 로그 `R 완료 접점 미연결 — 인계 문서 참조` 를 남기고 공개만 한다.

## 2. R `finish_owner_review` 제공

- **무엇을**: `notify_r` 자리에 넘길 R 함수를 만든다. 권장 시그니처:

  ```python
  async def finish_owner_review(conn, *, store_id: int, owner_answer_id: int, card_id: int,
                                card_version_id: int, knowledge_revision: int) -> None
  ```

  라우트에서는 `lambda`/`functools.partial` 로 `OwnerReviewNotifier` 모양(위치 인자 5개, store_id 는 클로저)에 맞춘다.
- **요구 의미**:
  - REVIEW 로 보고된 owner_answer 만 PUBLISHED 로 전환한다. 다른 상태면 예외를 던진다(발행째 롤백된다).
  - 그 owner_answer 의 **최신 revision** 이 아니면 거절한다(점주가 답을 고친 뒤 옛 제안을 승인한 경우).
  - 대기 질문 상태·알림은 **같은 트랜잭션**(넘겨받은 `conn`)에 기록한다. 따로 커밋하지 않는다.
  - proposal 단위로 멱등이어야 한다. 같은 제안의 재호출(재시도)이 알림을 두 번 만들지 않는다.
- **왜**: worker 가 REVIEW 로 보고한 뒤 점주가 나중에 승인하면, 지금은 R 쪽 대기 질문·알림 상태를 닫을 경로가 없다.
  hook 안에서 부르므로 R 기록이 실패하면 공개도 되지 않아 둘이 어긋나지 않는다.
- **W 쪽 준비**: `approve_owner_proposal` 이 hook 에서 `notify_r(conn, owner_answer_id, card_id, card_version_id, knowledge_revision)` 를 부른다.
  잠금 순서는 경로마다 다르다:
  - 초안 준비 트랜잭션: 공개판 → 제안 → 카드
  - 발행 트랜잭션(hook 포함): 공개판 → 카드(manifest 전체, card_id 오름차순) → 제안 → `notify_r`
  둘 다 **공개판 행을 가장 먼저** 잠그므로 서로 엇갈려 기다리지 않는다. R 이 hook 안에서 잡는 잠금은 이 순서 뒤에 둔다.
  (옛 `/learn/knowledge-proposals/{id}/approve` 는 공개판 잠금 없이 제안 → 카드 순으로 잡으므로 1번 교체 전까지는 교착 가능성이 있다. PG 가 감지해 한쪽을 중단시킨다.)

## 3. `RawSpan.source_id` 가 None 일 수 있다 (점주 답변 출처)

- **무엇을**: 점주 답변이 출처인 RAW 구간은 `source_id=None`, `owner_answer_id=<답변 id>` 로 실린다
  (`api/app/contracts/snapshot.py` `RawSpan`, `source_id: EntityId | None`, 둘 중 하나만 둔다). 이 값을 가정한 R 소비자가 깨진다.
  - `api/app/learn/answer_storage.py:221` — `{int(r.source_id) for r in snapshot.raw_spans}` 가 None 에서 `TypeError`.
  - `api/app/learn/answer_storage.py:247` — `int(citation.source_id)` 에 None 방어가 없다(`r_answer_citations.source_id` 컬럼 nullable 여부도 확인).
  - `api/app/learn/approved_renderer.py:32-33` — `Citation(source_id=span.source_id)` 와 `availability.get(span.source_id, ...)`.
    `Citation.source_id` 가 필수 `EntityId` 라(`api/app/contracts/chat.py:89`) 검증 오류가 나고, availability 는 None 키로 찾게 된다.
    점주 답변 출처 인용을 어떻게 표시할지(예: `owner_answer_id` 필드 추가, availability 고정값) R 이 계약과 함께 정한다.
- **왜**: 점주 답변 카드도 공개판에 RAW 블록으로 실려야 R 이 근거로 답할 수 있다. 지금은 W 플래그로 막아 두었다.
- **W 쪽 준비**: RawSpan 계약·migration(`supabase/migrations/20260927120000_w_raw_span_owner_answer.sql`)·블록 고정은 끝났다.
  R 보완이 끝나면 `.env` 에 `W_OWNER_ANSWER_RAW_PUBLISH=true` 를 켠다. 켜기 전에는 이런 span 이 공개판에 실리지 않는다.

## 4. (선택) `expected_card_revisions` 카드별 매핑

- **무엇을**: `prepare_index_request` 의 `PrepareIndexRequest.expected_card_revisions` 를
  카드별 `{card_id, expected_draft_version_id, target_card_version_id}` 매핑으로 바꾸는 계약 변경을 검토한다.
- **왜**: 지금 W 는 빈 배열 `()` 을 보내고 CAS 는 `publish_cards` 가 준비 전·공개 트랜잭션 안에서 두 번 직접 확인한다.
  R 이 준비 단계에서도 카드 판을 확인하고 싶다면 이 모양이 W `CardChange` 와 1:1 로 맞는다.
- **W 쪽 준비**: `app.publish.approval.CardChange(card_id, expected_draft_version_id, target_card_version_id)`.
  계약이 바뀌면 `build_prepare_request` 한 곳만 고치면 된다.

## 5. 준비 단위가 전체 manifest 다

- **무엇을**: `publish_cards` 는 매번 **현재 카드 포인터**(`review_status='APPROVED'` 이고 `published_version_id` 있는 카드 전체, 그 포인터 버전) + 바뀐 카드로
  `KnowledgeContent` 를 만들어 `prepare_index_request` 에 넘긴다(`api/app/publish/content.py` `current_manifest`). 직전 snapshot 을 베끼지 않는다 —
  그래서 제외 뒤 복원된 카드, 레거시 경로(7번)로 포인터만 옮겨진 카드, 플래그 때문에 빠졌던 카드가 다음 공개에서 저절로 돌아온다.
  공개할 때마다 **전체 카드를 재임베딩** 한다. 바뀌지 않은 카드 버전의 색인을 재사용할지 R 이 판단한다.
  - 변경하지 않는 카드가 고정·조립에서 실패하면(출처 없음, 빈 원문, RAW 블록 20개 초과, 계약 검증 실패) 그 카드만 경고 로그와 함께 그 판에서 뺀다.
    낡은 레거시 카드 하나가 매장 전체 승인을 막지 않게 하기 위해서다. 바뀌는 카드의 같은 실패는 `NO_PROVENANCE`/`INVALID_CONTENT` 로 멈춘다.
  - 준비와 공개 트랜잭션 사이에 변경하지 않는 카드의 포인터가 옮겨졌거나 `APPROVED` 가 아니게 되면 `STALE` 로 되돌리고 옛 버전을 싣지 않는다.
  - `changes=[]` 재발행에서 실을 카드가 하나도 없으면(마지막 승인 카드를 제외) R 준비 계약(`card_ids` 1개 이상) 때문에 준비하지 않고
    `EMPTY_MANIFEST` 를 돌려준다. 이때 현재 snapshot 에는 제외된 카드가 남지만 R 조회가 `review_status` 로 거른다.
- **왜**: 카드가 늘면 공개 1회 비용·지연이 선형으로 는다(D21 원가·p95 5초 상한과 직결).
- **비용 귀속**: 전체 manifest 재임베딩 비용은 **그 공개를 일으킨 카드**의 `usage_context`(승인 라우트·제외·복원 모두 `card_usage_context(card_id)`)로 잡힌다.
  다른 카드의 재임베딩까지 그 카드의 원본 작업에 귀속되므로 카드별 원가 집계를 읽을 때 주의한다(원가 계측 문서 기준 알려진 한계).
- **W 쪽 준비**: 요청의 `card_ids`·`content` 는 버전 단위로 결정적이다. 같은 (card_id, card_version_id, 블록)이면 같은 입력이다.

### 5-1. W 요청: 벡터 복사 방식의 재사용 (2026-09-27 결정)

- **무엇을**: `prepare_index`가 문서를 임베딩하기 전에, 같은 매장의 **이전 준비본**에서
  `(card_id, card_version_id, block_id, retrieval_text 지문)`이 같은 문서를 찾는다. 있으면 그 벡터를 새 준비본에 **복사**하고,
  없는 문서만 `embed_texts`로 새로 임베딩한다. 준비 단위(공개 후 전체 manifest)와 활성화 검사 규칙은 **그대로** 둔다.
- **왜 증분 색인이 아니라 복사인가**: 카드 100~200장 규모를 기준으로 판단했다.
  - 두 방식 모두 새로 임베딩하는 것은 바뀐 카드뿐이라, 임베딩 API 비용은 같다.
  - 복사는 공개할 때 DB 내부 행 복사(수백 행, 수 MB)가 늘어나는 대신, 검색이 준비본 하나만 보면 되어 단순하고 빠르다.
  - 증분 색인은 검색할 때마다 여러 겹(기준 + 변경분)을 합쳐야 한다. 검색은 공개보다 훨씬 자주 일어나므로 이 규모에서는 복사가 유리하다.
  - 증분 색인은 카드가 수천 장 이상이거나 공개가 분 단위로 잦아질 때 다시 검토한다.
- **효과**: 카드 1장을 승인할 때 새 임베딩도 1장분만 나간다. 원가(D21)와 지연(p95 5초)에 직접 도움이 된다.
- **주의**: 복사 조건에 **글 지문**을 반드시 포함한다. 같은 카드 버전이라도 검색용 텍스트 생성 규칙(렌더러·사전 버전)이 바뀌었으면 다시 임베딩해야 한다.
  모델·차원 설정(`embedding_model`, `embedding_dim`)이 다른 벡터도 복사하지 않는다.

### 5-2. W 요청: 옛 준비본 정리 기준 (2026-09-27 결정)

벡터 복사를 하든 안 하든, 지금도 공개할 때마다 전체 색인 행이 새로 쌓인다. 그래서 정리 기준이 필요하다.

| 대상 | 기준 |
|---|---|
| 현재 켜진 준비본 (`r_index_publications`가 가리키는 것) | 삭제하지 않는다 |
| 준비 중이거나 유효시간 안의 준비본 (`PREPARING`, 만료 전 `PREPARED`) | 삭제하지 않는다 |
| 직전에 켜졌던 준비본 **N개** | 보관한다. 되돌리기·장애 조사 때 재임베딩 없이 쓰기 위해서다 |
| 그 밖의 준비본 중 **M일**이 지난 것 | 문서 행(벡터 포함)을 삭제한다 |

> **N(보관 개수)과 M(보관 일수)은 미정이다.** W·R이 운영 데이터를 보고 추후 함께 정한다. 구현은 두 값을 설정으로 받게 만들고,
> 값이 정해지기 전에는 정리를 켜지 않는다.
| 준비본 기록 행 (ID·hash·어느 공개판용이었는지) | 남긴다. 작고 추적에 필요하다. 보존 기간은 R의 기존 진단 정리 규칙을 따른다 |

- **왜 개수와 시간을 섞나**:
  - 시간만(예: 1년)이면 공개가 잦은 매장에서 사본이 수천 벌 쌓여 DB 저장 비용이 는다.
  - 개수만(예: 3개)이면 연속 승인 몇 번에 방금 교체된 준비본이 지워져, 진행 중이던 질문이 끊길 수 있다.
  - 개수는 되돌리기용 최소치를, 일수는 "방금 교체된 것을 바로 지우지 않는" 여유를 보장한다. 구체적인 값은 위 N·M 결정 때 정한다.
- **지워도 되는 근거**: 과거 답변의 인용 재현은 벡터가 아니라 카드 버전·블록·원문(`card_versions`, `knowledge_snapshots`, `snapshot_card_versions`)으로 한다.
  옛 벡터를 지워도 "그때 왜 그렇게 답했나"는 확인된다.
- **R이 설계할 것**: 색인 문서 표에는 수정·삭제를 막는 불변 trigger가 있다. "켜져 있지 않고 위 기준을 넘긴 준비본의 문서만 삭제 허용"하는 예외가 필요하다.
  정리는 이미 1시간마다 도는 R 진단 정리 루프(`R diagnostics retention sweep`)에 붙이는 것을 제안한다.

## 6. 옛 색인(`card_embeddings`) 호환 쓰기 — 제거됨 (2026-09-27, 브랜치 `w/legacy-embed-cleanup`)

R 이 점주 답변 후보 검색을 활성 공개 색인으로 옮겨(PR #26) W 가 호환 쓰기를 지웠다.

- **제거한 것**: `prepare_embedding`·`embed_card`·`PreparedEmbedding`, `ingest/repository.py` 의 `upsert_embedding`,
  `POST /ingest/embed`, 승인 라우트·`approve_owner_proposal` 의 옛 색인 hook, `scripts/seed_embeddings.py`.
  `card_usage_context`(비용 귀속)만 `app.ingest.embed` 에 남았다.
- **남긴 것(R 호출부 호환)**: `prepare_proposal`·`publish_new_proposal`·`publish_existing_proposal` 은 R `learn/router.py` 가 import 하므로 남겼다.
  옛 색인 쓰기와 임베딩 호출만 뺐고, `prepare_proposal` 의 두 번째 반환값은 `None` 이다.
- **R 에 남은 것**:
  - `learn/router.py:750` v1 점주 답변 경로가 NEW 를 `publish_new_proposal` 로 바로 공개한다. 이 카드는 **R 색인에 없다**
    (다음 `publish_cards` 가 현재 포인터로 manifest 를 만들 때 실린다). 점주 답변 사건 worker 또는 `approve_owner_proposal` 로 옮겨 달라.
    옮기면 W 가 위 세 함수를 지운다.
  - `card_embeddings` 를 아직 **읽는** 곳: `reg/retrieve.py` 의 `retrieve_question`(→ `match_cards`)을 쓰는 `POST /reg/retrieve`,
    평가 러너 `team/runner.py`·`team/baseline.py`, v1 채팅의 `_search_and_compose_chat`(라우트는 `V2_REQUIRED` 로 막혀 있다).
    이제 새로 쓰지 않으므로 이 경로들은 옛 데이터만 본다. 정리하거나 새 색인으로 옮긴 뒤 테이블 삭제 migration 을 함께 정한다.
  - **공개판이 없는 매장**(승인 카드 0장, 새 매장)은 `read_current_index` 가 `INDEX_UNAVAILABLE` 이라 첫 점주 답변을 분석할 수 없다.
    후보가 없는 것이 정상인 상태이므로 공개판이 없으면 빈 후보를 돌려주는 쪽을 제안한다. 그 전까지 W worker 는 이 매장의 사건을
    실패로 태우지 않고 미룬다(아래 §9).

## 7. 두 번째 공개 경로: 레거시 `/ingest/cards/*` — 제거됨 (2026-09-27, 브랜치 `w/publish-cleanup`)

- **무엇이었나**: `api/app/ingest/router.py` 의 옛 카드 엔드포인트 4개가 `publish_cards` 를 거치지 않고
  `is_verified`·공개 포인터·`card_embeddings` 만 직접 바꿨다.
  - `POST /ingest/cards/{card_id}/approve` (본문 `_approve_one`)
  - `POST /ingest/cards/approve` 일괄
  - `POST /ingest/cards/{card_id}/unapprove`
  - `PATCH /ingest/cards/{card_id}`
- **제거한 것**: 위 4개 라우트와 전용 helper `_approve_one`, 전용 schema `ApproveResult`·`BulkApproveRequest`·`CardUpdateRequest`,
  전용 저장 함수 `ingest/repository.py` 의 `update_card`·`set_card_verified`, 웹 클라이언트 `web/lib/api.ts` 의
  `approveCards`·`approveCard`·`unapproveCard`·`updateCard`·`ApproveResult` 타입. 화면에서 부르는 곳은 없었다.
- **검증**: `api/tests/test_w_legacy_ingest_cards_removed.py` — 네 경로가 404/405 이고 OpenAPI 에 `/ingest/cards*` 가 없다.
- **결과**: 카드 공개 경로는 `/cards/{id}/approve` 등 `publish_cards` 하나다. R 이 할 일은 없다.
- **남은 것**: 없음. `POST /ingest/embed` 는 §6 과 함께 제거했다.

## 8. 알려진 한계 (문서화, 후속)

- **점주 답변 판을 점주가 편집하면 출처가 바뀐다**: `card_repo.create_draft` 는 새 판에 `owner_answer_id` 를 복사하지 않는다.
  점주 답변 판(SUPPLEMENT·CONFLICT·NEW) 위에서 `/cards/{id}/draft` 로 고친 판은 `owner_answer_id` 가 없으므로, 승인 시 카드의 자료 출처
  (`knowledge_cards.source_id`)로 인용되거나, 자료가 없으면(NEW) 가장 이른 점주 답변(플래그 ON)으로, 둘 다 없으면 `NO_PROVENANCE` 로 멈춘다.
  편집본의 출처 규칙은 후속에서 정한다.
- **제외·복원 재발행은 best-effort** 다. 실패하면 다음 공개까지 snapshot 이 상태를 늦게 따라간다(제외는 R 조회 필터로 즉시 반영, 복원은 다음 공개 때 돌아온다).

## 9. worker 켜기 전 초기 색인 준비 (2026-09-27)

- 옛 색인 시절 승인만 된 매장은 공개판·R 색인이 없다. 검색·후보 검색이 `INDEX_UNAVAILABLE` 이다.
- `api/app/publish/bootstrap.py`: 매장 상태 `READY / MISSING / OUTDATED / EMPTY` 를 판정하고, MISSING·OUTDATED 면
  현재 승인 카드 그대로 한 번 재발행(`publish_cards(changes=[])`)해 색인을 만든다. 출처 없는 레거시 카드는 빠진다(경고 로그).
- `api/scripts/bootstrap_store_index.py`: 기본은 점검만 한다. `--apply` 를 붙여야 재발행한다(임베딩 비용).
  **`W_OWNER_ANSWER_WORKER_ENABLED=true` 전에 한 번 돌린다.** 데모 시드(`demo_seed.py`)는 카드 없이 매장·계정·로드맵 틀·대기 질문만 심고 색인은 만들지 않는다. **데모 카드는 자료 업로드로 만든다.**
- worker 는 READY 가 아닌 매장의 사건을 건너뛰고 상태가 바뀔 때만 한 번 경고한다. 사건은 소비하지 않고 남는다.
- 운영 점검 화면(`preflight`)의 "시드 임베딩" 항목을 "공개 색인"(승인 카드가 있는 매장 수 대비 색인 있는 매장 수)으로 바꿨다.

## 10. 자료 삭제(D20)와 인용 끊김 (2026-09-27)

- `DELETE /ingest/sources/{id}`(점주 전용): 자료를 `source_availability='DELETED'` tombstone 으로 남긴다.
  사실·카드·공개판·R 색인은 그대로이고 승인 카드를 자동 제외하지 않는다. 처리 중 자료는 409 `SOURCE_IN_PROGRESS`.
- 원본 접근 해제: 카드 근거의 열람 URL 을 발급하지 않고 `source.source_availability` 를 내려준다. 새 작업·재시도·옛 `/ingest/process` 가
  삭제된 자료를 다시 처리하지 않는다. Storage 원본 파일의 물리 삭제 여부는 추후 논의로 결정한다(2026-09-27 사용자).
- R 이 할 일은 없다. v2 인용은 이미 `sources.source_availability` 를 읽어 `인용 끊김` 을 표시한다.

## 11. W3a 사실 블록 공개판 (2026-10-08)

W3a 구현(브랜치 `w/w3a-fact-assembly`)을 R 이 확인해 주기를 요청한다. R 소유 파일은 고치지 않았다.

- 바뀌는 것: 플래그 `w_fact_assembly_enabled`(기본 꺼짐)로 만든 사실 카드 판은 블록(`QUANTITIES|STEPS|NOTES`)에 `fact_revision_ids` 를 싣고, 공개판 `fact_revisions` 에 그 판들이 근거(`FactProvenance`: 파일은 `source_id`+`occurrence_id`, 점주 답변은 `w_owner_answer_raw_publish` 일 때만)와 함께 실린다. 카드 `entity_id` 는 실제 대상 id, `variant` 는 카드 판 규격이 하나일 때 채운다(`api/app/publish/content.py` `_fact_card`). 레거시 카드는 그대로다(`entity_id=str(card_id)`, RAW, `fact_revisions` 없음, snapshot hash 불변). 사실 블록 여부는 플래그가 아니라 `card_block_facts` 행으로 가른다.
- 결정성: 근거는 카드 판에 고정(`card_version_fact_provenance`)되므로 같은 카드 판을 다시 실으면 같은 content 다(색인 벡터 재사용 키 유지). 선행(`requires`)은 같은 카드 판 안 같은 사실의 판으로 푼다. 근거는 사실당 최대 50.
- 카드 제목: 대상 정식 이름, 나뉜 카드만 ` i/n` 을 붙인다. 규격은 제목에 넣지 않는다(블록 머리 줄 `[수치 · ICE]` 와 `PublishedCard.variant`). R planner 가 카드 전체 제목 언급으로 대상을 찾기 때문이다.
- MESSAGE 근거 위치: 카톡 자료의 occurrence 는 `card_evidence` 에 `MESSAGE` 로 들어가며 locator 키는 `line`(`{"line": N}`)이다.
- **entity_id 이름공간 충돌(계약 변경 요청).** 레거시 카드의 `entity_id` 는 `card_id`(`knowledge_cards` 전역 identity)이고 사실 카드의 `entity_id` 는 실제 대상 id(`knowledge_entities` 전역 identity)다. 둘은 같은 숫자 범위를 쓰고 계약 `EntityId` 가 `^[0-9]+$` 라 접두어로도 못 가른다. 한 공개판에서 둘이 같으면 R planner 가 레거시 카드 질문에 다른 대상의 사실을 고르고 대상 일치 검사도 통과한다. **W 는 당분간 공개를 거절한다** — `build_knowledge_content` 가 같은 공개판의 레거시 카드 `entity_id` 와 사실 카드·사실 판 `entity_id` 가 겹치면 `InvalidContent` 로 멈춘다(fail closed, 레거시 판 내용·hash 불변). 섞인 매장에서 숫자가 겹치면 R 계약이 바뀔 때까지 승인 공개가 막힌다. 이미 공개된 레거시 hash 를 지키려면 레거시 쪽이 아니라 실제 대상 id 쪽 표현을 옮겨야 한다.
- 알려진 한계: 사실 카드를 점주가 자유 편집한 판(`OWNER_EDIT`, 블록 없음)은 RAW 로 공개되고 `entity_id` 가 카드 id 로 돌아가며 그 카드 사실은 `fact_revisions` 에서 빠진다(W3b 가 대체). 규격 없음 블록은 "공통" 이 아니라 미확정이다.
- W 가 확인한 것(합성 매장, `api/scripts/verify_w3a_fact_assembly.py`): B2 공개판 모양, B3 R `hybrid_search`·`decide`·`save_answer` 가 ANSWER 로 공개 사실을 인용(인용 fact_revision·source·block 이 공개판과 일치), B4 재공개 결정성, B5 점주 편집 판 한계. 실제 R 화면·운영 데이터는 확인하지 않았다.

---

## 12. W3b 점주 사실 편집 (2026-10-09)

W3b(브랜치 `w/w3b-card-review`)가 점주의 사실 단위 편집을 열었다. 플래그 `w_fact_card_edit_enabled` 기본 꺼짐. R 소유 파일과 `contracts/*` 는 고치지 않았다(사용자 결정 Q1 = A, 2026-10-09). R 이 확인해 주기를 요청한다.

- 편집한 카드 판의 공개 모양: 카드 판 `change_source` 는 `OWNER_EDIT` 이지만 **사실 블록 카드**다(사실 블록 여부는 W3a 와 같이 `card_block_facts` 행, 즉 데이터로 가른다). 공개판에 `fact_revisions` 가 실리고 `entity_id`·`variant` 도 W3a 와 같다. 점주 **자유 본문 PATCH** 로 사실 카드가 RAW 로 공개되고 사실이 빠지던 경로(§11 알려진 한계, R 이 할 일 10-b)는 막았다(사실 블록 카드의 자유 본문 PATCH 는 409 `FACT_CARD_TEXT_EDIT_BLOCKED`). **점주 답변 SUPPLEMENT/CONFLICT 승인 경로(`api/app/learn/knowledge_apply.py`)는 아직 사실 카드에 블록 없는 판을 올린다** — 승인되면 그 카드는 RAW 로 공개되고 `entity_id` 가 카드 id 로 돌아가며 사실이 `fact_revisions` 에서 빠진다(10-b 와 같은 결과). W 가 W3a 켜기 전에 막을 일로 남겼다(`docs/dev/plan/W_NEXT_PLAN_20260928.md` W3a 켜기 전 점검). 레거시 RAW 카드는 그대로다.
- 새 사실 판 종류: 고친 사실은 `OWNER_CORRECTION`(기존 판을 `supersedes`), 점주가 넣은 사실은 `OWNER_ADD`. 점주가 뺀 사실은 새 카드 판에서 참조만 빠지고 과거 판·과거 snapshot 은 그대로다.
- 근거: 점주 편집·입력 사실의 근거는 파일 없는 새 자료 종류 `sources.source_type='OWNER_TEXT'` 의 occurrence 다(`locator` 는 `LINE n`, 점주가 쓴 글의 줄). `file_url`·`content_hash` 는 비어 있다. `FactProvenance` 는 파일 출처 모양(`source_id`+`occurrence_id`) 그대로라 **계약 변경이 없다.** (Q1 = B 였다면 계약·검증기 변경이 필요했을 것이다. 고르지 않았다.)
- 과거 snapshot 불변: 편집·재승인 뒤에도 이미 공개된 snapshot 의 content/hash 는 바뀌지 않는다(실제 DB 시나리오 A3).
- 재승인 전에는 공개판이 그대로다. 점주가 승인해야 새 판이 공개된다(A1). R 답변이 편집된 사실을 ANSWER 로 인용하는 것을 합성 매장에서 확인했다(A2: `hybrid_search`·`decide`·`save_answer`, 실제 R 화면·운영 데이터는 확인하지 않음).
- 점주가 사실을 빼면 그 사실의 `fact_occurrences` 처분이 `EXCLUDED`(사유 `OWNER_REMOVED`)가 된다. 다른 카드 초안에 같은 사실이 있으면 그쪽으로 옮기고 `EXCLUDED` 로 두지 않는다.
- OWNER_TEXT 자료는 작업(`ingest_jobs`)이 없다. `POST /ingest/process` 는 OWNER_TEXT 를 409 로 거절하게 고쳤다. `POST /ingest/jobs` 에는 OWNER_TEXT 전용 분기가 없고, OWNER_TEXT 자료는 만들 때부터 상태가 `DONE` 이라 기존 `SOURCE_NOT_READY`(409)로 거절된다. R 읽기 경로(`answer_storage.current_source_overlay`, `v2_router.citation_detail`)는 `source_availability` 만 읽고 파일 링크를 내지 않아 깨지지 않음을 읽어서 확인했다.

R 이 할 일 목록(아래)에 11번을 더했다. 모두 `[ ]` 이며 R 확인 전에는 W 가 W3-4 를 완료로 표시하지 않는다.

---

## 13. 사실→카드 단일 경로 · 1회 삭제 · 입구 분류기 · 공지 (2026-10-10 계획)

W 가 다음 세 단계를 계획했다(아직 구현 전, 사용자 결정 2026-10-10). R 소유 파일과 `contracts/*` 는 고치지 않는다. 설계:
`W_PHASE_A_FACT_ONLY_DESIGN_20261010.md`(A), `W_PHASE_B_INTAKE_ROUTER_DESIGN_20261010.md`(B), `W_PHASE_C_NOTICE_KNOWLEDGE_TAB_DESIGN_20261010.md`(C). 시작 안내: `W_FACT_ONLY_ROADMAP_20261010.md`.

**Phase A — 레거시 RAW 제거(배포 전에 R 이 알아야 할 것)**
- W 는 **RAW 블록 카드를 더 공개하지 않는다.** 업로드 옛 조립, 점주 답변 RAW 카드(`create_owner_answer_card`), 점주 자유 본문 편집(`PATCH /cards/{id}/draft`)을 지우고, 블록 없는 판은 공개를 거절한다. 공개판의 모든 카드가 사실 블록 카드가 된다. W 플래그 `w_entity_revision_enabled`·`w_upload_proposals_enabled`·`w_fact_assembly_enabled`·`w_fact_card_edit_enabled`·`w_owner_answer_raw_publish` 는 없어진다(항상 켜진 동작).
- **점주 답변이 사실이 된다.** W worker 가 답변 글을 `OWNER_TEXT` 자료로 저장해 사실 추출 → 원장 → 조립으로 보낸다. 새 대상이면 사실 카드를 자동 공개, 이미 공개된 카드의 대상이면 그 카드의 새 초안 + 점주 승인 대기. W 는 R `knowledge_loop.build_knowledge_plan` 을 **더 부르지 않는다.** R 라우터가 부르는 `approve_owner_proposal(...)` 모양과 `ApplyOwnerAnswerResult` 계약은 그대로다.
- 점주 답변 근거는 `OWNER_TEXT` 자료 occurrence(`source_id`+`occurrence_id`)로 온다. 점주 답변 id 연결은 W 가 보존한다.
- **1회 삭제 migration(배포 때 한 번)**이 지식·자료와 함께 **R 표를 비운다**: `r_answer_citations`, `r_answer_receipts`, `message_citations`, `knowledge_snapshots`·`snapshot_card_versions`, `knowledge_publications`, `r_index_publications`·`r_index_preparations`·`r_index_documents`, 지워진 공개판을 가리키는 공개 멱등 기록(`r-initial-empty` 포함). 불변 트리거는 그 migration 트랜잭션 안에서만 잠깐 끈다. R 표 구조는 바꾸지 않는다. 질문·점주 답변·채팅 문장·비용 원장은 남는다. 되돌리기는 배포 워크플로의 migration 직전 DB 백업뿐이다.

**Phase B — 입구 분류기·정규화기·점주 답변 첨부**
- 업로드·점주 답변마다 싼 분류 호출 1회로 로직(`RECIPE`·`PROCEDURE`·`POLICY`·`REFERENCE`·`NOTICE`·`NONE`)을 정한다. 공개 계약은 그대로다.
- 새 자료 형식 docx·hwp(문서), avi(영상). 인용에 보이는 자료 종류가 늘어난다.
- **점주 답변에 파일 첨부**: web 이 W 업로드 경로로 올리고 W 새 API 가 그 자료를 **대기 질문 id** 에 묶는다(`owner_answer_attachments`). R 답변 제출 API 는 그대로다.
- 사실에 로직별 확장 칸 `ext`(예: 공지 기간)가 생기지만 원장에만 두고 **공개 계약에는 넣지 않는다.**

**Phase C — 공지사항·매장 지식 탭**
- 공지 자료의 지식 변경은 카드(새 초안 → 승인), 기간 있는 알림은 새 공지 표(`store_notices`)로 간다. 공지는 카드·snapshot 이 아니라 R 답변 근거가 아니다.
- 직원 화면 상단 공지 버튼·매장 지식 탭. 직원 화면 web 파일의 주 편집자는 계획 단계에서 확인한다.

R 이 할 일 12·13번을 더했다.

### Phase A 구현 (2026-10-10, 브랜치 `w/phase-a-fact-only`)

위 계획대로 구현했다(배포 전). R 이 확인·결정할 것은 "R 이 할 일" 12·14·15 에 모았다.

- **12-(d) 답: 코드로 확인 — Phase A 에서 지움(R 확인 대기).** R `learn/router.py` 는 옛 함수 3개(`publish_new_proposal`·`publish_existing_proposal`·`prepare_proposal`)를 import 하지 않는다. W 는 이 3개를 Phase A 의 다음 작업에서 지운다. R 이 틀렸다고 보면 지우기 전에 알려 달라.
- **v1 경로의 변화.** v1 `/learn/pending/{id}/answer`·`/learn/knowledge-proposals/{id}/approve` 는 이제 **사실 초안이 없는 제안**을 `approve_owner_proposal` 이 `ValueError` 로 거절하고 라우터가 409 로 바꾼다. 메시지: "예전 방식 제안이라 카드로 만들 수 없어요. 카드 화면에서 직접 고쳐 주세요." v1 로 새 점주 답변 제안을 만들면 `NEW` 는 `FAILED` 가 된다(점주 원문 전달은 그대로). 웹 `/owner/questions` 목록과 `/owner/cards/proposals` 가 아직 v1 을 쓴다 → **R 이 할 일 14.**
- **`relation_type` 의미 변화(12-(e) 답).** `NEW` = 새 카드(들), `SUPPLEMENT` = 이미 공개된 카드에 새 초안, `IDENTICAL` = 이미 공개된 같은 사실. `CONFLICT` 는 더 만들지 않는다. reason 에 `NO_FACTS`(답변에서 사실이 나오지 않음)·`FACTS_PENDING`(사실 추출·조립이 아직 안 끝남)이 생겼다. 승인하면 **그 답변이 만든 초안 카드를 전부 공개**한다. `approve_owner_proposal(...)` 모양과 `ApplyOwnerAnswerResult` 계약은 그대로다.
- **점주 답변 근거(12-(f) 표시 요청 유지).** `OWNER_TEXT` 자료 occurrence(`source_id`+`occurrence_id`)로 온다. 자료와 답변의 연결은 새 표 `owner_answer_sources`(migration `20261010090000`)가 쥔다. R 인용 표시는 "점주 답변" 으로 보여 달라.
- **점주 답변 검토 이유.** 대상 카드에 붙이는 점주 답변 검토 이유는 `NO_PROVENANCE`·`FACT_CONFLICT_OPEN`·`FALLBACK:*` 를 덮어쓰지 않는다. 공개된 카드의 재초안은 `needs_review_reason` 을 계산된 이유 또는 `NEW_FACTS` 로 둔다.
- **R 소유 검증 3개를 W 가 고쳤다(사용자 결정 P-3).** R 이 확인해 달라.
  - `verify_r_legacy_publication.py`: v1 `NEW` 가 이제 `FAILED` 인 것을 기대하도록 바꿨고, 지워진 설정을 패치하던 줄(오류 때 Settings repr 이 새어 나갈 수 있었다)을 지웠다.
  - `verify_r_w3_consumer.py`: 공개 호출에 `version=1` 을 명시했다.
  - `verify_r_owner_candidates.py`: 사실 카드 fixture 로 바꿨다. worker 검사는 이제 "DB 연결이 임베딩 중이 아니라 **모델·추출 호출 중에** 풀려 있음"을 증명한다 → **R 이 이 바뀐 의미가 맞는지 확인해 달라.**
  - 또 W 가 `verify_w_publication_flow.py` 에서 R `verify_r_owner_citations` 호출을 지웠다. 그 검증은 점주 답변 RAW span 이 있다고 전제했는데 이제 RAW 가 없다. `api/scripts/verify_r_owner_citations.py` 파일은 지우지 않았고 그대로 남아 있다. W 흐름이 더 부르지 않을 뿐이므로, R 이 쓸지(고칠지)·지울지 정해 달라.
- **1회 삭제 migration 에서 R 표 처리.** 비우는 R 표는 위 계획과 같다. 구현에서 달라진 점: `knowledge_publications` 행은 **지우지 않고** `current_snapshot_id` 만 비운다(revision 역행 방지, `ensure_initial_publication` 은 그대로 동작). `operations` 는 `operation='PUBLISH'`(`r-initial-empty` 포함)만 지우고 `VISIBILITY` 멱등 행은 남긴다. **R 표 중 `r_owner_knowledge_states` 등은 비우지 않아** 지워진 카드에 대한 상태 글이 남을 수 있다 → 14 에 포함.
- **알림 문구.** W 는 작업 `card_count` 의미를 "이 자료가 이어진 카드 수" 로 바꿨다. 알림 문구가 "새 카드" 라고 하면 틀리게 된다 → **R 이 할 일 15.**
- **12-(h) 처리.** 레거시 카드가 1회 삭제로 없어져 entity_id 이름공간 충돌 가드를 지웠다(블록 없는 판 공개 거절로 대체). 계약 분리를 할지는 R 이 정한다.
- 데모 시드는 이제 카드를 만들지 않는다(자료를 올려 카드를 만든다). 배포 절차는 `FACT_ONLY_ROLLOUT.md`.

---

## R 이 할 일 (우선순위 순)

1. ~~`finish_owner_review` 를 만들고 `/learn/knowledge-proposals/{id}/approve` 를 `approve_owner_proposal(..., notify_r=...)` 로 교체~~ — 완료(PR #25) (1·2번).
   중복 카드와 "승인했는데 답에 안 나옴"이 이 교체로 함께 사라진다.
2. **`RawSpan.source_id=None` 소비 경로 보완** (`answer_storage.py:221`, `:247`, `approved_renderer.py:32-33`, `Citation.source_id`) 뒤
   W 에 알려 `W_OWNER_ANSWER_RAW_PUBLISH=true` 로 켠다 (3번). 이 전에는 점주 답변 NEW 카드도, 기존 자료 카드에 얹은 점주 답변 판도 공개되지 않는다.
3. ~~준비 단계에 벡터 복사 재사용(5-1)~~ — 완료(PR #25, 현재 활성 공개판 재사용 범위). **옛 준비본 정리(5-2)는 R 후속, 구조만 만든다.** 카드 1장 승인에 전체 재임베딩이 나가는 비용을 없앤다.
   정리의 보관 개수·일수(N·M)는 W·R이 추후 함께 정하며, 그 전에는 정리를 켜지 않는다.
4. ~~점주 답변 후보 검색을 새 색인으로 이전~~ — 완료(PR #26). W 가 `card_embeddings` 호환 쓰기를 지웠다(§6).
   `expected_card_revisions` 계약 결정은 남았다.
5. **v1 점주 답변 경로의 `publish_new_proposal` 즉시 공개를 worker·`approve_owner_proposal` 로 옮긴다** (§6). W 가 2026-10-10 Phase A 에서 옛 함수 3개(와 `create_owner_answer_card`)를 지웠다(코드 확인: R `learn/router.py` 는 import 하지 않음, R 확인 대기).
6. **`card_embeddings` 를 읽는 옛 경로(`/reg/retrieve`, 평가 러너) 정리 후 테이블 삭제 migration** 을 함께 정한다 (§6).
7. **공개판이 없는 매장의 점주 답변 후보 검색은 빈 후보를 돌려준다** (§6). 새 매장의 첫 점주 답변이 막히지 않게 한다.
8. ~~`FactProvenance.source_id` 필수 · `owner_answer_id` FK `on delete restrict` 점검~~ — **닫힘, R 이 할 일 없음.**
   (a) R 이 `4bb145c`(2026-10-05)에서 `FactProvenance` 를 `source_id XOR owner_answer_id`(파일 출처면 `occurrence_id` 필수)로 바꿨다(`api/app/contracts/snapshot.py:35-55`).
   (b) W3-0 §3-4 확인(2026-10-07, 코드 변경 없음): R 트리거 `askbuddy_owner_original_immutable`(`supabase/migrations/20260917130000_m3_owner_answer_delivery.sql:43-56`)가 R revision 이 있는 점주 답변의 삭제·원문 수정을 막고, 앱 코드(`api/app`)에는 `owner_answers`·`pending_questions`(답변으로 cascade)를 지우는 경로가 없다. 따라서 W 링크(`fact_revision_meta.owner_answer_id`·`fact_owner_answer_links`)의 `on delete restrict` 가 새로 막는 앱 삭제 경로는 없다. 매장 삭제는 기존처럼 불변 원장 때문에 막히고, 데모 매장은 보관 방식으로 처리한다(현행 유지).
9. **새 `fact_revisions` 삽입은 W 서비스(`api/app/ingest/fact_ledger.py`·`fact_revisions.py`)를 거치기를 권한다.** W 는 revision 마다 `knowledge_facts`·`fact_revision_meta` 를 짝지어 두고 `fact_revisions.entity_id`·`fact_id` 에는 FK 가 없다. 권고일 뿐이며 임의 id 를 넣는 R 의 기존 verify 스크립트는 그대로 동작한다.
10. **R 필수 검토 — 미완료 (W3-4).** W3a 사실 블록 공개판(§11)을 R 쪽이 받는지 확인해 결과를 이 문서나 R 기록에 남기고 W 에 알린다. 그 전에는 W 가 W3-4 를 완료로 표시하지 않는다.
    (a) 분할 카드(제목 ` 2/3`)는 R planner 의 카드 전체 제목 언급 매칭(`planner.decide`)에 걸리지 않는다. 카드 제목이 아니라 대상 이름·별칭으로 대상을 찾도록 해 달라.
    (b) 점주가 편집한 사실 카드 판(블록 없음)은 RAW 로 공개되고 `entity_id` 가 카드 id 로 바뀐다. 같은 카드의 `entity_id` 가 판에 따라 바뀔 때 R 의 캐시·명확화 문맥·일반 의미 승인 설정이 영향을 받는지 확인해 달라(W3b 전 알려진 한계).
        W3b 뒤 상태(2026-10-10): 점주 **자유 본문 PATCH** 로 생기는 경로는 사실 블록 카드에서 막혔다(§12). 이 상황은 **레거시 RAW 카드**와 **점주 답변 SUPPLEMENT/CONFLICT 승인 판**(`knowledge_apply`, 사실 카드에도 블록 없는 판을 올림)으로 아직 생긴다. 확인 요청은 그대로다.
    (c) R 렌더러(`approved_renderer.render`)·색인(`documents()`)·인용 검증(`answer_storage`)이 사실 블록 snapshot(`fact_revisions`, 실제 `entity_id`, 채워진 `variant`, 파일 근거 `source_id`+`occurrence_id`)을 받는지 확인해 달라. 렌더러 머리줄과 블록 머리 줄의 규격 중복·규격 없음 표시도 정해 달라. D19 다규격 카드에서 CLARIFY 로 규격을 확정한 뒤 그 규격 블록만 인용하는지 포함한다.
    (d) 카톡 자료 근거의 MESSAGE locator 키가 `line`(`{"line": N}`)이다. 근거 패널·인용 표시가 이 키를 받는지 확인해 달라.
    (e) 과거 인용 재현: 사실 블록 카드의 과거 판에 대한 인용이 이후 재공개·새 판 뒤에도 같은 근거로 재현되는지 확인해 달라.
    (f) **계약 변경 요청 — entity_id 이름공간 분리(§11).** 레거시 카드 `entity_id`(=`card_id`)와 사실 대상 `entity_id` 가 같은 숫자 공간을 쓴다. W 는 지금 충돌 시 공개를 거절한다. 계약(`contracts/*`)·검증기(`contracts/validate.py`)에서 두 이름공간을 나누는 방식을 R 이 정해 달라. 정해질 때까지 W3a 플래그를 켜지 않는다.
11. **W3b 점주 사실 편집 확인 (§12).** `[ ]`
    (a) 인용·출처 표시에서 `source_type='OWNER_TEXT'` 를 "사장님 직접 입력" 으로 보이게 해 달라. 지금 v2 인용 상세·인용 칩 응답에는 `source_type` 이 없어 점주 직접 입력 근거가 일반 파일 자료(AVAILABLE)처럼 보이고 자료 제목 "카드 직접 입력 · …" 이 그대로 나온다. 깨지지는 않는 표시 문제이며 R 응답·화면 변경이 필요하다.
    (b) 점주 편집 판(`OWNER_CORRECTION`·`OWNER_ADD` 사실이 든 사실 블록 카드)이 실린 snapshot 을 R 렌더러·색인·인용 검증이 받는지 확인해 달라(10번 W3-4 필수 검토와 함께).
    (c) 점주 삭제로 생기는 `fact_occurrences` `EXCLUDED`(`OWNER_REMOVED`)가 R 쪽 계산에 영향이 없는지 확인해 달라.
12. **Phase A 배포 전 확인 (§13).** `[ ]`
    (a) **10번(W3-4 필수 검토)을 Phase A 배포 전에 끝내 달라.** 배포 뒤 모든 카드가 사실 블록 카드라 R 렌더러·색인·인용 검증이 그것을 받는지가 곧 서비스 전체 동작이다.
    (b) RAW 블록 처리(R 렌더러·색인·인용 검증, 계약 `BlockKind` 의 `RAW`)를 지울지 R 이 정한다. W 는 RAW 를 더 만들지 않는다. 계약 변경은 R 결정이다.
    (c) W 가 `knowledge_loop.build_knowledge_plan` 을 부르지 않게 된다. R 쪽에서 안 쓰이게 되는지 확인해 달라. 2번(`RawSpan.source_id=None`)·`W_OWNER_ANSWER_RAW_PUBLISH` 는 점주 답변 RAW 경로가 없어져 닫힌다.
    (d) 5번: W 가 Phase A 에서 `publish_new_proposal`·`publish_existing_proposal`·`prepare_proposal` 을 지운다. v1 `/pending/{id}/answer`(R `learn/router.py`)가 이 함수들이나 옛 승인 경로에 기대지 않는지 확인해 달라. 기대면 W 에 알려 달라(삭제 전에 맞춘다).
    (e) 지식 제안 화면이 제안의 관계 종류값(NEW·SUPPLEMENT·CONFLICT 등)에 기대면 바뀐 값이 맞는지 확인해 달라.
    (f) 인용 표시에서 점주 답변 근거(`OWNER_TEXT` 자료 + 점주 답변 연결)를 "점주 답변" 으로 보이게 해 달라(11-a 와 합침).
    (g) **1회 삭제 뒤**: ① 첫 직원 질문에서 `ensure_initial_publication` 이 빈 공개판을 만드는지, ② 카드 0개일 때 정상 빈 상태("아직 등록된 지식이 없어요")가 나오는지, ③ 인용이 지워진 옛 채팅 답변이 "근거 보기" 없이 깨지지 않고 보이는지, ④ 7번(공개판 없는 매장의 점주 답변 후보 검색 = 빈 후보)이 동작하는지 확인해 달라.
    (h) 10-f(entity_id 이름공간)는 레거시 카드가 없어져 데이터상 해소된다. 닫을지, 계약 분리를 그대로 할지 정해 달라.
13. **Phase B·C 확인 (§13).** `[ ]`
    (a) 점주 답변 화면이 R 소유면 첨부 UI 를 붙여 달라: 파일 선택 → W 업로드(`POST /ingest/upload-url`) → W 첨부 API → 업로드가 끝나야 제출 버튼을 켠다. W API 를 먼저 준비한다.
    (b) 인용 표시가 모르는 자료 종류(docx·hwp·avi 등)를 만나도 깨지지 않게(기본 이름표) 해 달라.
    (c) 사실의 `ext`(공지 기간 등)는 공개 계약에 없다. R 답변에 쓰려면 그때 계약을 검토한다(지금 할 일 없음).
    (d) 공지사항(`store_notices`)은 R 답변 근거가 아니다. 공지 내용을 답변에 쓰려면 그때 계약을 검토한다.
    (e) 직원 화면(상단 공지 버튼·매장 지식 탭)이 R 소유 파일이면 알려 달라. W 가 화면 요구를 인계로 넘긴다.
14. **v1 점주 답변·제안 화면을 v2 로 옮기거나 닫는다 (Phase A, 새 항목).** `[ ]`
    (a) 웹 `/owner/questions` 목록과 `/owner/cards/proposals` 가 v1 `/learn/pending/{id}/answer`·`/learn/knowledge-proposals/{id}/approve` 를 쓴다. 사실 초안이 없는 v1 제안은 승인 때 409 가 나고 v1 `NEW` 는 `FAILED` 가 된다. 화면을 v2 로 옮기거나 v1 을 닫아 달라.
    (b) 1회 삭제 뒤 R 표 `r_owner_knowledge_states` 등이 지워진 카드에 대한 상태 글을 가질 수 있다. 정리가 필요한지 정해 달라.
    (c) `verify_r_legacy_publication.py`·`verify_r_w3_consumer.py`·`verify_r_owner_candidates.py` 의 W 수정(Phase A 절 참고)을 확인해 달라.
15. **작업 완료 알림 문구를 바꿔 달라 (Phase A, 새 항목).** `[ ]` `notifications/service.py` 의 "새 카드가 준비됐어요 / 검토할 업무 카드 N개" 를 "카드 N장에 반영됐어요" 쪽으로. W 가 `card_count` 의미를 "이 자료가 이어진 카드 수" 로 바꿨다.
