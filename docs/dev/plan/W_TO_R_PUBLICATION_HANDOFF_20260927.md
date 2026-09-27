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

## 6. 옛 색인(`card_embeddings`) 호환 쓰기 제거 조건

- **무엇을**: 점주 답변 후보 검색 `knowledge_loop.find_owner_answer_candidates`(`api/app/learn/knowledge_loop.py:68`)가
  `match_cards` (knowledge_loop.py:88) → `card_embeddings` 를 읽는다. 이를 새 공개판 색인으로 옮긴다.
- **왜**: 그 전까지 W 는 모든 승인 경로(`approve_card`, `approve_owner_proposal`)에서 `prepare_embedding` 을 트랜잭션 밖에서,
  `embed_card` 를 발행 hook 안에서 불러 옛 색인도 채운다. 임베딩 호출이 공개마다 한 번 더 든다.
- **W 쪽 준비**: 두 경로 모두 `# 옛 색인 호환` 주석으로 표시해 두었다. R 이 옮기면 W 가 그 호출을 지운다.

## 7. 두 번째 공개 경로: 레거시 `/ingest/cards/*` (W 후속 제거 대상)

- **무엇을**: `api/app/ingest/router.py` 의 옛 카드 엔드포인트가 아직 살아 있다. 모두 `publish_cards` 를 거치지 않고
  `is_verified`·공개 포인터·`card_embeddings` 만 직접 바꾼다.
  - `POST /ingest/cards/{card_id}/approve` (`:641`, 본문 `_approve_one` `:616`)
  - `POST /ingest/cards/approve` 일괄 (`:711`)
  - `POST /ingest/cards/{card_id}/unapprove` (`:653`)
  - `PATCH /ingest/cards/{card_id}` (`:665`, 승인 카드 글을 고치고 옛 색인만 다시 만든다)
- **영향**: 이 경로로 바뀐 카드는 바로 공개판에 오르지 않는다. manifest 가 현재 포인터를 따르므로 **다음 `publish_cards` 공개에서 따라잡는다**.
  그 사이 R `hybrid` 는 `published_version_id = snapshot 판` 조건 때문에 포인터만 옮겨진 카드를 보지 못할 수 있다.
- **W 후속**: 이 엔드포인트들은 W 파일이라 이 브랜치 밖 후속 작업에서 W 가 제거(또는 `/cards/*` 로 위임)한다. R 이 할 일은 없다.

## 8. 알려진 한계 (문서화, 후속)

- **점주 답변 판을 점주가 편집하면 출처가 바뀐다**: `card_repo.create_draft` 는 새 판에 `owner_answer_id` 를 복사하지 않는다.
  점주 답변 판(SUPPLEMENT·CONFLICT·NEW) 위에서 `/cards/{id}/draft` 로 고친 판은 `owner_answer_id` 가 없으므로, 승인 시 카드의 자료 출처
  (`knowledge_cards.source_id`)로 인용되거나, 자료가 없으면(NEW) 가장 이른 점주 답변(플래그 ON)으로, 둘 다 없으면 `NO_PROVENANCE` 로 멈춘다.
  편집본의 출처 규칙은 후속에서 정한다.
- **제외·복원 재발행은 best-effort** 다. 실패하면 다음 공개까지 snapshot 이 상태를 늦게 따라간다(제외는 R 조회 필터로 즉시 반영, 복원은 다음 공개 때 돌아온다).

---

## R 이 할 일 (우선순위 순)

1. **`finish_owner_review` 를 만들고 `/learn/knowledge-proposals/{id}/approve` 를 `approve_owner_proposal(..., notify_r=...)` 로 교체** (1·2번).
   중복 카드와 "승인했는데 답에 안 나옴"이 이 교체로 함께 사라진다.
2. **`RawSpan.source_id=None` 소비 경로 보완** (`answer_storage.py:221`, `:247`, `approved_renderer.py:32-33`, `Citation.source_id`) 뒤
   W 에 알려 `W_OWNER_ANSWER_RAW_PUBLISH=true` 로 켠다 (3번). 이 전에는 점주 답변 NEW 카드도, 기존 자료 카드에 얹은 점주 답변 판도 공개되지 않는다.
3. **점주 답변 후보 검색을 새 색인으로 이전**하고 준비 재사용·`expected_card_revisions` 계약을 결정한다 (4·5·6번).
   이전이 끝나면 W 가 `card_embeddings` 호환 쓰기와 옛 `publish_new_proposal`/`publish_existing_proposal` 을 지운다.
