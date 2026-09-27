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
  **`W_OWNER_ANSWER_WORKER_ENABLED=true` 전에 한 번 돌린다.** 데모 시드(`demo_seed.py`)도 이 함수로 색인을 만든다.
- worker 는 READY 가 아닌 매장의 사건을 건너뛰고 상태가 바뀔 때만 한 번 경고한다. 사건은 소비하지 않고 남는다.
- 운영 점검 화면(`preflight`)의 "시드 임베딩" 항목을 "공개 색인"(승인 카드가 있는 매장 수 대비 색인 있는 매장 수)으로 바꿨다.

## 10. 자료 삭제(D20)와 인용 끊김 (2026-09-27)

- `DELETE /ingest/sources/{id}`(점주 전용): 자료를 `source_availability='DELETED'` tombstone 으로 남긴다.
  사실·카드·공개판·R 색인은 그대로이고 승인 카드를 자동 제외하지 않는다. 처리 중 자료는 409 `SOURCE_IN_PROGRESS`.
- 원본 접근 해제: 카드 근거의 열람 URL 을 발급하지 않고 `source.source_availability` 를 내려준다. 새 작업·재시도·옛 `/ingest/process` 가
  삭제된 자료를 다시 처리하지 않는다. Storage 원본 파일의 물리 삭제는 개인정보 삭제 절차로 남겼다.
- R 이 할 일은 없다. v2 인용은 이미 `sources.source_availability` 를 읽어 `인용 끊김` 을 표시한다.

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
5. **v1 점주 답변 경로의 `publish_new_proposal` 즉시 공개를 worker·`approve_owner_proposal` 로 옮긴다** (§6). 옮기면 W 가 옛 함수 3개를 지운다.
6. **`card_embeddings` 를 읽는 옛 경로(`/reg/retrieve`, 평가 러너) 정리 후 테이블 삭제 migration** 을 함께 정한다 (§6).
7. **공개판이 없는 매장의 점주 답변 후보 검색은 빈 후보를 돌려준다** (§6). 새 매장의 첫 점주 답변이 막히지 않게 한다.
