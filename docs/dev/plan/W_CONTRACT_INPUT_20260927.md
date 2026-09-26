# W → R 첫 계약 검토 자료 — 2026-09-27

R의 요청 5가지에 대한 W 쪽 현재 상태다. 기준은 main `8220af8`이다.
**[현재]**는 코드에 있는 것이고, **[예정]**은 아직 구현하지 않은 W 제안이다. 제안은 합의 전이다.

## 먼저 알아둘 것 (요약)

1. **W 승인은 아직 옛 경로다.** 점주가 `POST /cards/{id}/approve`를 누르면 카드 한 장의 공개 포인터만 옮기고, 옛 임베딩 색인(`embed_card`)에 바로 넣는다. `publish_knowledge`, snapshot, R `prepare`/`activate`를 거치지 않는다.
2. **W는 아직 R이 읽는 카드 내용을 만들지 못한다.** R의 `PublishedCard`에는 `blocks`와 `fact_revisions`가 필요하다. 하지만 `card_version_blocks`, `card_block_facts`, `fact_revisions`를 쓰는 W 코드는 없다(R 쪽 읽기 코드에만 있다). W 카드 버전은 `title`과 `content` 문자열뿐이다.
3. 그래서 5개 항목 모두 "구조는 있음, W 호출부는 예정"이다. 1번 병목은 **카드 버전 → `PublishedCard`(blocks·fact revision) 변환**이다.

## ① 카드의 수정·검수·공개 버전 필드와 비교 코드

**[현재] 필드** (`supabase/migrations/20260910133000_mvp_contract_v1.sql`)

| 위치 | 필드 | 뜻 |
|---|---|---|
| `card_versions` | `version_id`(PK), `card_id`, `version_no`, `title`, `content`, `change_source`(EXTRACTION / OWNER_EDIT / OWNER_ANSWER) | **불변 행.** 수정할 때마다 새 행이 생긴다 |
| `knowledge_cards` | `draft_version_id` | 지금 검수 중인 판 (= 가장 최근 수정본) |
| `knowledge_cards` | `published_version_id` | 직원에게 공개된 판 |
| `knowledge_cards` | `review_status` | PENDING / NEEDS_REVIEW / APPROVED / EXCLUDED |
| `snapshot_card_versions` | `(snapshot_id, card_id, card_version_id)` | 그 판에 실린 카드 버전 (W가 아직 채우지 않음) |

W에는 draft용 "revision 번호"가 따로 없다. **초안 자체가 불변 `card_versions` 행이고, 그 `version_id`가 곧 revision이다.** 승인은 `published_version_id = draft_version_id`로 포인터만 옮긴다. 새 버전을 복사하지 않는다.

**[현재] 비교 코드**
- 수정: `api/app/cards/router.py` `update_draft`
  - `select … for update`로 잠근 뒤 `card.draft_version_id != req.expected_version_id`이면 409 `CARD_VERSION_CONFLICT`
- 승인: 같은 파일 `approve_card`
  - 트랜잭션 밖에서 draft를 읽고 임베딩을 준비한다.
  - 트랜잭션 안에서 다시 잠근 뒤 `draft_version_id`, `published_version_id`, `review_status`가 준비 때와 같은지 비교하고, 다르면 409.

**[예정] 매핑 제안** — 위 구조 때문에 두 값이 대부분 같다.
```json
{ "card_id": "1001", "expected_draft_version_id": "2003", "target_card_version_id": "2003" }
```
- `expected_draft_version_id`는 준비 시점의 `knowledge_cards.draft_version_id`다. 공개 트랜잭션에서 잠그고 같은지 CAS한다.
- `target_card_version_id`는 공개할 불변 버전이다. 현재 모델에서는 위와 같다. 필드를 나눠 두는 이유는 나중에 "공개용 버전을 따로 찍는" 구조로 바뀌어도 계약을 유지하기 위해서다.
- 기존 `expected_card_revisions: tuple[RevisionId]`는 이 배열로 대체하자. 호환 방식은 "빈 배열만 허용, 값이 있으면 거절"인 현재 R wrapper 동작을 유지하는 것을 제안한다.

## ② 카드 A만 수정했을 때의 준비 요청과 전체 snapshot 예시

**[현재] R 코드의 제약** (`api/app/reg/index_preparation.py`)
- `prepare_index_request`: `request.card_ids`가 `content.cards` 전체와 같아야 한다.
- `activate_prepared_index`: `content.cards`의 (card, version) 집합이 `snapshot_card_versions`와 **정확히 같아야** 한다.
- 즉 지금 R은 **준비 단위 = 공개 후 전체 manifest**로 동작한다. "변경 카드만 준비"하면 activate에서 `HASH_MISMATCH`가 난다.

**[예정] 합성 예시** — 카드 A(1001)는 v2003으로 수정됐고, B(1002)는 공개된 v1500을 그대로 둔다.
```json
{
  "changed_cards": [
    { "card_id": "1001", "expected_draft_version_id": "2003", "target_card_version_id": "2003",
      "previous_published_version_id": "1999" }
  ],
  "manifest": [
    { "card_id": "1001", "card_version_id": "2003" },
    { "card_id": "1002", "card_version_id": "1500" }
  ],
  "expected_publication_revision": "7"
}
```
- `manifest`는 현재 snapshot의 카드 목록에서 `changed_cards`를 교체하고, 제외(EXCLUDED)된 카드를 뺀 것이다.
- R에 넘기는 `KnowledgeContent.cards`는 **manifest 전체**다(현재 R 제약에 맞춤).
- **R에 확인할 것:** 매번 전체 manifest를 다시 임베딩하면 비용이 든다(D21). 바뀌지 않은 카드는 기존 색인을 재사용하는 방식을 R 쪽에서 할 수 있는가? 아니면 W가 `changed_cards`만 따로 표시해 주면 되는가?

## ③ 승인 transaction의 시작·종료와 R activate 위치

**[현재]** `api/app/cards/router.py` `approve_card`
```
(트랜잭션 밖)  draft 읽기 → prepare_embedding
(트랜잭션)     카드 잠금 → CAS → published_version_id = draft_version_id
              → embed_card(옛 색인) → 이벤트 기록 → commit
```
`api/app/publish/service.py` `publish_knowledge`(publication 잠금 → 판 CAS → snapshot → `snapshot_card_versions` → 포인터 → outbox)는 있다. 하지만 **이 승인 경로에서 호출하지 않는다.**

**[예정] 새 흐름** (파일 위치는 제안)
```
(밖)  ① 승인 대상 draft들과 현재 snapshot 읽기 → manifest·KnowledgeContent 만들기
      ② R prepare_index_request(pool, …)   ← DB 연결 없이, 임베딩은 R
(tx)  ③ publication 잠금 → 카드 잠금(card_id 순) → 카드별 expected_draft_version_id CAS
      ④ publish_knowledge(…, card_versions=manifest) → snapshot_id
      ⑤ knowledge_cards.published_version_id / review_status 갱신
      ⑥ R activate_prepared_index(conn, store_id, prepared_id, snapshot_id)   ← 여기
      ⑦ commit (하나라도 실패하면 전체 rollback)
```
- 잠금 순서는 R 문서와 같게 publication → card → pending → lease로 한다.
- `embed_card`(옛 색인)는 새 경로에서 빼는 것을 제안한다. 이중 색인이 되기 때문이다.
- 그 전에 **② 앞의 변환(카드 버전 → `PublishedCard` blocks·fact_revisions)이 W에 없다.** 그래서 이 흐름의 선행 작업은 W3(참조 카드 조립)다.

## ④ 점주 답변의 LINKED / REVIEW / PUBLISHED / FAILED 결과 예시

**[현재] 두 갈래가 따로 있다**
- 옛 W 경로 (`api/app/learn/router.py`, `knowledge_apply.py`)
  - `knowledge_change_proposals.status`: ANALYZED / LINKED / PENDING_REVIEW / PUBLISHED / FAILED / DISMISSED
  - `answer_id`로 `owner_answers`를 가리킨다.
  - 옛 색인에 바로 공개하며, R `finish`를 부르지 않는다.
- R 접점 (`api/app/learn/owner_handoff.py`)
  - `claim_owner_event` / `heartbeat_owner_event` / `finish_owner_event(conn, …, result: ApplyOwnerAnswerResult)`
  - `ApplyOwnerAnswerResult`: `status`, `fact_revision_id`, `card_id`, `knowledge_revision`, `retryable`, `error`

**[예정] 결과 예시** (`ApplyOwnerAnswerResult` 형식)
```json
{ "status": "LINKED",    "card_id": "1002", "fact_revision_id": "501", "knowledge_revision": "7" }
{ "status": "REVIEW",    "card_id": null,   "fact_revision_id": null,  "knowledge_revision": null }
{ "status": "PUBLISHED", "card_id": "1003", "fact_revision_id": "502", "knowledge_revision": "8" }
{ "status": "FAILED",    "retryable": true, "error": { "code": "INDEX_PREPARE_TIMEOUT", "message": "…" } }
```
- **LINKED:** 이미 공개된 카드 1002에 같은 내용이 있다. 새로 공개하지 않고, 현재 판(7)을 확인한 뒤 `finish`한다.
- **REVIEW:** 기존 카드와 충돌하거나 보충이 필요해 점주 검수가 필요하다. 공개하지 않는다.
- **PUBLISHED:** 새 카드 1003을 ③의 흐름으로 판 8에 공개한다. 같은 트랜잭션에서 `activate` → `finish`.
- **FAILED:** 공개 전체를 rollback한다. 실패 기록은 별도 트랜잭션에 남긴다.
- `fact_revision_id`는 W가 아직 fact revision을 만들지 못해 채울 수 없다. **[예정]**

## ⑤ REVIEW 제안을 나중에 승인하는 함수와 owner_answer_id 연결

**[현재]**
- 나중에 승인하는 함수: `POST /learn/knowledge-proposals/{proposal_id}/approve` → `publish_new_proposal` / `publish_existing_proposal` (`api/app/learn/knowledge_apply.py`)
- 연결 고리: `knowledge_change_proposals.answer_id` = `owner_answers.answer_id` = R의 `r_owner_answer_revisions.owner_answer_id`. **같은 ID라서 추적은 된다.**
- 문제: 이 승인은 옛 색인에 공개하고 R에게 아무것도 알리지 않는다. 그리고 R `finish_owner_event(REVIEW)`는 원래 사건을 이미 소비 완료로 기록한다. 그래서 **나중 승인을 R에 전달할 길이 없다.**

**[예정] W 제안** — R과 결정할 부분
1. 나중 승인도 ③과 같은 흐름(prepare → tx → activate)으로 공개한다.
2. 같은 트랜잭션에서 R에 완료를 알린다. 선택지는 둘이다.
   - (a) **새 outbox 사건** `OWNER_KNOWLEDGE_APPROVED(owner_answer_id, proposal_id)`를 W가 넣고, R이 소비해 `r_owner_knowledge_states`를 PUBLISHED로 바꾼다.
   - (b) **R 전용 접점** `finish_owner_review(conn, store_id, owner_answer_id, result)`를 R이 제공하고, W가 공개 트랜잭션 안에서 직접 호출한다.
   - W는 (b)를 제안한다. `finish_owner_event`와 같은 방식(같은 트랜잭션, 현재판 검사)이라 이해하기 쉽고, 사건 재소비 문제가 없다.
3. 중복 방지: `proposal_id` 단위 멱등 키, 그리고 "상태가 REVIEW인 owner_answer만 PUBLISHED로 전환 가능"한 조건부 갱신.
4. 점주가 그 사이에 새 답변을 줬다면 `finish_owner_event`처럼 최신 `revision_no`가 아니면 거절한다.

## R과 결정할 목록

| # | 결정할 것 | W 제안 |
|---|---|---|
| 1 | 카드 매핑 필드 이름·형식 | `card_id / expected_draft_version_id / target_card_version_id` |
| 2 | 준비 단위 | 공개 후 전체 manifest(현재 R 제약). 바뀌지 않은 카드의 색인 재사용 여부는 R이 판단 |
| 3 | 공개 transaction 안의 순서 | 위 ③의 ③~⑦ |
| 4 | 나중 승인 완료 전달 | (b) R 전용 `finish_owner_review` |
| 5 | 옛 경로 정리 | 새 경로가 붙은 뒤 `embed_card` 즉시 공개와 옛 proposal 공개를 막는다 |

## W 선행 작업 (계약과 별도)

- **W3:** 카드 버전 → `PublishedCard`(blocks·fact_revisions) 생산. 이게 없으면 ②와 ③을 실제로 돌릴 수 없다.
- 첫 통과 사례(합성 카드 2장)는 W3의 최소 형태(카드당 block 1개)로 먼저 맞추는 것을 제안한다.
