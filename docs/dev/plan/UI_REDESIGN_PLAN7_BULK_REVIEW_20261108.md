# 계획 7: 서버 기능 묶음 B + 카드 선택 모드 + 바로 고르는 검수

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** 백로그에 남은 서버 필요 기능과 2026-11-08 사용자 결정 13건을 닫고, 카드 여러 장을 한 번에 다루는 선택 모드와 들어가자마자 고르는 검수 화면을 만든다.

**Architecture:** 서버는 기존 라우터(`api/app/cards`, `api/app/categories`, `api/app/checklist`, `api/app/learn`)에 끝점을 더하고, 공개는 모두 `publish_cards` 하나로 올린다(한 번에 한 판). 화면은 합성 API(`api/scripts/ui_fixture.cjs`)에 같은 계약을 더해 브라우저 묶음 `verify_ui_plan7.cjs` 로 확인한다. 순수 규칙은 `web/tests/*.test.mjs`, 서버는 pytest, SQL 은 일회용 pg17 로 실제 스키마에서 돌린다.

**Spec:** `docs/dev/plan/UI_REDESIGN_BACKLOG_20261106.md`(남은 18건·새 기능 요청·다시 볼 것), 이 문서 '사용자 결정' 표.

## 사용자 결정 (2026-11-08)

| # | 결정 |
|---|---|
| 1 | 카테고리 종류(레시피/할 일/정보)는 AI 판단(입구 분류 `source_logic`)으로 정하고 사장님이 고칠 수 있다. 이름 규칙은 AI 판단이 없는 옛 카테고리에만 |
| 2 | 미공개: 직원 레시피·검색·답변에서 바로 빠진다. 학습 기록·근무조 연결은 남고 다시 공개하면 이어진다 |
| 3 | 충돌은 '맞는 것을 골라 주세요!' 와 두 값 버튼. 고르지 않은 값은 지우지 않고 '틀린 값'으로 남긴다. 단위만 다른 같은 양인지도 사장님이 고른다(서버가 묶지 않는다). 고르는 게 아닌 사유는 그 자리에 글 입력칸 |
| 4 | 수정 되돌리기는 수정 완료 알림의 '되돌리기' 글자 하나(5초) |
| 5 | 직원 레시피에는 '인용 끊김'을 보이지 않는다. 사장님 카드 상세에만. D20 문서에 예외로 적는다 |
| 6 | 직원 오늘 할 일 아래 '다른 근무조 할 일 보기'(접힘) |
| 7 | 근무조별 현황 화면(o01b)은 하지 않는다 |
| 8 | `/staff/chat` 은 지우고 `/staff/ask` 에 지난 대화 목록(검색, 눈에 덜 띄는 '새 대화'). 대화 기록은 그대로 |
| 9 | 설정 이름 고치기, 합류 승인 되돌리기, 카테고리 순서·이름 고치기를 넣는다 |
| 10 | 수정 모드는 같은 문장을 묶지 않고 한 덩어리로 붙여 보인다 |
| 11 | 끝난 단계만 과거형(올렸어요, 읽었어요, 카드 만들었어요) |
| 12 | 추천 질문 칩은 어디서나 누르면 바로 보낸다 |
| 13 | '새 답' 점은 그 대화를 열어도 꺼진다 |
| 새 | 카드 목록 '선택' 모드: 하나씩 또는 끌어서 여러 장, 전체 선택, 이동·공개·미공개·삭제 |

## Global Constraints

- 매장 격리: 모든 새 쿼리는 `store_id` 필수, JWT 의 store_id. `check_store_id.py` 결과가 변경 전과 같아야 한다.
- migration 은 가산만(`supabase/migrations/2026110812xxxx_*.sql`), 일회용 pg17 `verify_r_schema_rebuild.py` 통과.
- 공개·미공개·되돌리기는 `publish_cards` 로만 판을 바꾼다(D13). 여러 장은 한 번 호출 한 판.
- 화면 글: 중간점 금지, 회색 설명 추가 금지, % 금지, `eslint-disable` 금지.
- 프롬프트 변경은 실제 모델로 측정하지 않는다(사용자 지시). 계획 문서에 '측정 전'으로 적는다(D16).
- 실데이터·운영 DB·배포판을 건드리지 않는다. 커밋하지 않는다.

## Review Focus

1. 선택 모드에서 끌어 고르는 손가락이 목록 스크롤·밀기·길게 누르기와 겹치면 안 된다(세로로 끌면 스크롤, 가로로 시작하면 고르기).
2. 일괄 공개에서 몇 장만 실패하면(출처 없음 등) 실패한 카드만 선택된 채 남고 이유가 보여야 한다.
3. 충돌을 고른 뒤 같은 자료를 다시 올려도 같은 충돌이 다시 열리면 안 된다(틀린 값 기억).
4. 미공개한 카드는 직원 검색·답변 근거에 다시 나오면 안 된다(공개 판에서 빠짐).
5. 지난 대화 목록에서 다른 직원의 대화가 보이면 안 된다(user 격리).

---

### Task 1: 표 칸 사실의 이름을 지키는 프롬프트 (계획 6 되돌림 일부)

계획 6 규칙 1('그 부분만 옮긴다')이 표 칸에서 칸 이름까지 떼어 '20', '3,700원'만 남겼다. 그래서 같은 카드가 한눈에 보기와 예전 보기로 갈린다.

**Files:** `api/prompts/extract_facts.ko.txt`, `api/prompts/extract_facts_locator.ko.txt`, `api/tests/test_extract_prompt_rules.py`(새로).

- [ ] 테스트 `test_table_cell_keeps_column_name`: 두 프롬프트에 '표 칸에서 뽑은 사실은 `칸 이름=값` 그대로' 규칙과 예시 `컵=20`(맞음) / `20`(틀림)이 있다.
- [ ] 테스트 `test_step_split_rule_still_present`: 계획 6 규칙 1의 화살표 단계 예시는 그대로 있다.
- [ ] 프롬프트 고침 → 테스트 통과. 문서에 '측정 전'.

### Task 2: 카테고리 종류

**Files:** migration `..._category_kind.sql`(`task_categories.kind varchar(10) null check in ('RECIPE','TASK','INFO')`, `kind_source varchar(10) null check in ('AI','OWNER')`), `api/app/categories/repository.py`, `api/app/categories/router.py`, 카드 분류 경로(`classify_cards` 를 부르는 곳), `api/app/checklist/repository.py`(`add_default_link`), `web/lib/recipe-category.ts` → `web/lib/card-kind.ts`.

**Interfaces:**
- Produces: `GET /categories` 항목에 `kind: "RECIPE" | "TASK" | "INFO" | null`; `PATCH /categories/{id}` 에 `kind`(사장님, `kind_source='OWNER'`); 카드 목록·상세의 `category.kind`.
- Produces: `card_kind(category) -> "RECIPE" | "TASK" | "INFO"`(web): kind 가 있으면 그것, 없으면 이름 규칙.

- [ ] pytest `test_ai_sets_kind_from_source_logic`: 분류가 카드를 kind 없는 카테고리에 넣을 때 그 카드 자료의 `source_logic` 이 RECIPE 면 RECIPE, PROCEDURE 면 TASK, 그 밖은 INFO.
- [ ] pytest `test_owner_kind_is_not_overwritten`: `kind_source='OWNER'` 면 분류가 바꾸지 않는다.
- [ ] pytest `test_default_link_uses_kind`: `add_default_link` 는 kind 가 RECIPE 면 넣지 않고, kind 가 없을 때만 이름 규칙.
- [ ] 일회용 pg17 에서 `add_default_link` 실제 실행(레시피 종류·이름 규칙·다른 매장 3경우).
- [ ] node `card-kind.test.mjs`: kind 우선, 없으면 이름 규칙.
- [ ] 브라우저 `KIND-1 카테고리 화면에서 종류를 바꾸면 카드 상세의 근무조 칸이 생기거나 사라진다`.

### Task 3: 미공개(공개 내리기)

**Files:** `api/app/cards/router.py`(`POST /cards/{id}/unpublish`), `api/app/publish`(카드 빼기 판), 테스트 `api/tests/test_card_unpublish.py`.

**Interfaces:** Produces `POST /cards/{id}/unpublish` → `CardMutationResult`(`review_status: PENDING`, `published_version_id: null`). 공개였거나 검수 필요였던 카드 모두. 학습 기록·`checklist_cards` 는 손대지 않는다.

- [ ] pytest `test_unpublish_removes_card_from_snapshot`: publish_cards 가 그 카드를 뺀 판으로 불리고(changes 에 제거), 커밋 뒤 호출.
- [ ] pytest `test_unpublish_keeps_learning_and_checklist`: 학습·근무조 표에 쓰지 않는다.
- [ ] pytest `test_unpublish_needs_review_goes_pending`: NEEDS_REVIEW → PENDING, 이유 칸은 남긴다.
- [ ] 직원 오늘 할 일·레시피 조회가 공개 포인터 없는 카드를 빼는지 확인(이미 그렇다면 그 쿼리를 단언하는 테스트만).
- [ ] 화면: 카드 목록 공개 탭에서 왼쪽 밀기 '미공개', 검수 필요 상세 하단 '공개 / 미공개' 좌우 버튼(o07b). 브라우저 `UNPUB-1`, `UNPUB-2`.

### Task 4: 일괄 API

**Files:** `api/app/cards/router.py`(`POST /cards/bulk`), `api/app/cards/schemas.py`.

**Interfaces:** `POST /cards/bulk {action: "approve"|"unpublish"|"exclude"|"restore"|"move", card_ids: int[1..200], category_id?: int}` → `{results: [{card_id, ok, review_status?, error?: {code, message}}], undo_token?: string}`. approve·unpublish 는 `publish_cards` 한 번(한 판). exclude 는 `undo_token` 으로 restore 일괄.

- [ ] pytest `test_bulk_approve_publishes_once`: 카드 3장 → publish_cards 1회, changes 3개.
- [ ] pytest `test_bulk_partial_failure_reports_each`: 출처 없는 1장은 `ok: false, error.code = CARD_NO_PROVENANCE`, 나머지는 공개.
- [ ] pytest `test_bulk_rejects_other_store_cards`: 다른 매장 card_id 가 섞이면 그 카드만 `CARD_NOT_FOUND`.
- [ ] pytest `test_bulk_move_skips_nothing_and_marks_manual`: 이동은 `assignment_type='MANUAL'`.

### Task 5: 카드 선택 모드(화면)

**Files:** `web/app/owner/cards/page.tsx`, `web/components/owner/card-select.tsx`(새로), `web/lib/drag-select.ts`(새로, 순수 함수), `web/tests/drag-select.test.mjs`.

**Interfaces:** Consumes Task 4 `POST /cards/bulk`. Produces `rangeSelect(order: number[], anchor: number, current: number, base: Set<number>, adding: boolean) -> Set<number>`.

- [ ] node `drag-select.test.mjs`: 끌기 시작한 카드가 안 골라져 있으면 범위를 더하고, 골라져 있으면 범위를 뺀다. 되돌아 끌면 지나친 칸은 처음 상태로.
- [ ] 브라우저 `SEL-1 '선택'을 누르면 밀기·길게 누르기가 꺼지고 아래 동작 줄`(이동, 공개, 미공개, 삭제, 전체 선택).
- [ ] `SEL-2 하나씩 누르면 체크가 바뀌고 머리에 'N장 선택'`.
- [ ] `SEL-3 가로로 끌어 시작하면 지나간 카드가 골라지고, 세로로 끌면 스크롤`(Playwright 마우스 끌기, 카드 4장).
- [ ] `SEL-4 전체 선택은 지금 필터에 보이는 카드만, 한 번 더 누르면 전체 해제`.
- [ ] `SEL-5 일괄 공개가 일부 실패하면 실패한 카드만 선택된 채 남고 이유 한 줄`.
- [ ] `SEL-6 일괄 삭제 뒤 스낵바 '되돌리기'로 모두 돌아온다`.
- [ ] `SEL-7 이동은 카테고리 시트에서 고르고, 끝나면 선택 모드를 닫는다`.
- [ ] 화면 캡처 확인(390px): 선택 모드 목록, 동작 줄. 캡처를 보고 맞춘다.

### Task 6: 들어가자마자 고르는 검수(충돌·입력)

**Files:** 서버 `api/app/cards/router.py`(`GET /cards/{id}/facts` 응답에 `review_items`, `POST /cards/{id}/review-items/{item_id}`), `api/app/ingest/fact_revisions.py`(`choose_conflict`), `api/app/ingest/fact_ledger.py`(틀린 값 기억), 화면 `web/components/owner/fact-card/review-picker.tsx`(새로), `recipe-view.tsx`·`fact-card-panel.tsx`.

**Interfaces:**
- `review_items: [{item_id, kind: "CHOOSE", conflict_id, label, options: [{fact_id, text}] } | {item_id, kind: "WRITE", fact_revision_id, label, text}]`.
- `POST /cards/{id}/review-items/{item_id}` `{choose_fact_id}` 또는 `{text}` → 카드 다시 조립, 남은 항목이 없으면 `NEEDS_REVIEW → PENDING`(공개는 사장님이 따로).
- `choose_conflict(conn, store_id, conflict_id, *, keep_fact_id, actor_id)`: 충돌 RESOLVED, 고르지 않은 사실은 '틀린 값'(새 판 `change_kind='OWNER_REJECTED'`, 카드 조립에서 뺀다). 같은 값이 다시 들어와도 그 사실 identity 로 다시 열지 않는다.

- [ ] pytest `test_choose_keeps_one_and_marks_other_rejected`.
- [ ] pytest `test_rejected_value_does_not_reopen_on_reupload`(같은 값의 사실이 다시 들어와도 OPEN 없음).
- [ ] pytest `test_unit_variants_still_ask_owner`(0.5oz·15ml 은 충돌로 남는다, 서버가 묶지 않는다).
- [ ] pytest `test_write_item_updates_fact_and_clears_review`.
- [ ] pytest `test_review_items_only_for_this_store`.
- [ ] 일회용 pg17 에서 choose_conflict 실제 실행.
- [ ] 브라우저 `PICK-1 검수 필요 카드를 열면 내용 속 충돌 자리에 '맞는 것을 골라 주세요!'와 두 값 버튼`(수정하기 없이).
- [ ] `PICK-2 하나를 누르면 그 값으로 내용이 바뀌고 확인 상자가 사라진다`.
- [ ] `PICK-3 입력 항목은 그 자리에 글 입력칸, 저장하면 내용에 들어간다`.
- [ ] `PICK-4 저장이 실패하면 고른 버튼이 풀리고 이유가 그 자리에`.
- [ ] 검수 화면(작업 결과)의 확인 필요 카드도 같은 고르기.
- [ ] 화면 캡처 확인: 사용자 스케치(두 값 버튼이 내용 위에 강조)와 비교.

### Task 7: 수정 되돌리기

**Files:** `api/app/cards/router.py`(`POST /cards/{id}/facts/edits/{edit_id}/revert`), `web/components/owner/fact-card/fact-card-panel.tsx`.

- [ ] pytest `test_revert_restores_previous_heads_as_new_revisions`(판은 지우지 않고 옛 값으로 새 판).
- [ ] pytest `test_revert_only_latest_edit_within_window`(다른 수정이 뒤에 있으면 409).
- [ ] 브라우저 `UNDO-1 수정 완료 알림의 '되돌리기'를 누르면 예전 내용`.

### Task 8: 지난 대화 목록

**Files:** `api/app/learn`(`GET /learn/v2/sessions` 에 `title`(첫 질문 40자), `last_at`, `q` 검색), `web/components/staff/ask-screen.tsx`, `web/components/staff/chat-list-sheet.tsx`(새로), `web/app/staff/chat/` 지우고 `/staff/ask` 로 넘김.

- [ ] pytest `test_sessions_list_has_title_and_last_at`, `test_sessions_search`, `test_sessions_only_mine`.
- [ ] 브라우저 `CHAT-1 머리의 '지난 대화'를 누르면 목록 시트, 검색으로 걸러진다`.
- [ ] `CHAT-2 목록에서 고르면 그 대화가 열린다`.
- [ ] `CHAT-3 '새 대화'는 목록 시트 안 맨 위 작은 글자 버튼`(입력창 근처에 두지 않는다).
- [ ] `CHAT-4 /staff/chat 은 /staff/ask 로 간다`.

### Task 9: 작은 서버 기능 3

- [ ] 이름 고치기: `PATCH /me {name}`, `PATCH /store {store_name}`(사장님만). pytest 2개, 브라우저 `NAME-1` 설정 연필 → 시트 → 저장.
- [ ] 합류 승인 되돌리기: 승인 응답에 `user_id`, `POST /members/{user_id}/revoke-approval`(승인 10초 안). pytest 2개, 브라우저 `JOIN-1` 스낵바 '되돌리기'.
- [ ] 카테고리 순서·이름: `PUT /categories/order {ids}`, `PATCH /categories/{id} {name}`(같은 이름 대소문자 무시 409). pytest 3개, 브라우저 `CAT-1` 끌어서 순서, `CAT-2` 이름 고치기.

### Task 10: 직원 화면 결정 반영

- [ ] `OTHER-1 오늘 할 일 아래 '다른 근무조 할 일 보기'를 펼치면 다른 근무조 줄`(서버 오늘 할 일에 `other_shifts` 가 없으면 추가, pytest 1개).
- [ ] `CHIP-1 오늘 할 일·레시피 추천 칩을 누르면 바로 보내고 답이 온다`.
- [ ] `DOT-1 새 답이 온 대화를 열면 입력창의 '새 답' 점이 꺼진다`(그 대화 알림을 읽음으로).
- [ ] 옛 화면 3개 키트로: `/staff/pending`, `/join/[token]`, `/auth/role`. 브라우저 `OLD-1~3` 로딩·오류·다시.

### Task 11: 작은 결정

- [ ] node `job-steps.test.mjs`: 끝난 단계는 '올렸어요, 읽었어요, 카드 만들었어요', 진행 중은 '올리는 중, 읽는 중, 카드 제작 중'.
- [ ] 수정 모드: 같은 문장에서 나온 줄은 사이 줄 없이 한 덩어리(`data-same-sentence`). 브라우저 `EDIT-1`.
- [ ] D20 예외 문서: `docs/dev/ASKBUDDY_MVP_CURRENT.md` 인용 끊김 절에 '직원 화면 제외' 한 줄, TODO 동기화.

### Task 12: 다시 볼 실화면 문제 중 이 계획에 걸리는 것

- [ ] '*'·'//' 표시: 화면 한눈에 보기에서 문장 앞 각주 표시를 떼고 `//` 는 쉼표로(node 테스트). 원장 문장은 그대로.
- [ ] '수치·순서·목록' 머리글: 한눈에 보기가 아닌 카드는 규격이 없으면 머리글을 두지 않는다.
- [ ] 직원 레시피 화면도 한눈에 보기: 레시피 상세가 사실 목록(`/cards/{id}/facts` 의 직원판)을 받아 `RecipeView` 로 그린다. 서버에 직원용 읽기 끝점이 없으면 추가(공개 판의 사실만, pytest 격리 1개).

## 검증

- pytest 전부, node --test 전부, `pnpm check`.
- 브라우저 묶음 전부 + 옛 스크립트(`OLD=1`) + `verify_ui_plan7.cjs`.
- 일회용 pg17: `verify_r_schema_rebuild.py`와 새 SQL 실제 실행 스크립트.
- 매장 격리 검사 변경 전과 비교.
- 화면 캡처(390px): 선택 모드, 검수 고르기, 지난 대화, 레시피(사장님·직원) — 캡처를 직접 보고 맞춘다.

## 순서

1 → 2 → 3 → 4 → 5(선택 모드, 4 필요) → 6(검수 고르기) → 7 → 8 → 9 → 10 → 11 → 12. 각 Task 끝에 해당 묶음과 이전 묶음을 다시 돌린다.
