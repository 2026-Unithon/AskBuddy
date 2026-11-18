# 계획 10: 카드는 모델이 쓰고 서버는 거짓말만 막는다 (+ 남은 백로그, 대기 화면 로그아웃)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** 레시피·업무 카드가 자료 모양과 상관없이 사람이 읽을 수 있게 나온다. 카드 보기·수정은 어디서나 같은 모양이고, 수정은 줄 타일을 끌어 옮긴다. 남은 화면 백로그와 알바생 대기 화면 로그아웃까지 끝낸다.

**Architecture:** 카드 조립 모델이 구역(제목)·순서·줄 글을 쓰고, 줄마다 근거 사실 번호를 단다. 서버는 줄의 숫자·단위가 근거 사실에 있는지(지어냄), 사실 값이 빠지지 않았는지(빠뜨림)만 문자열로 검사한다. 실패한 줄만 사실 원문으로 바꾼다. 사실 원장·공개 snapshot 의 블록·사실 인용(R 계약)은 그대로 두고, 줄 글은 W 표시용으로 새 표에 저장한다. 사실 모양으로 추측해 다른 보기로 떨어지는 로직은 지운다.

**Tech Stack:** FastAPI, asyncpg, PostgreSQL 15(로컬 일회용 pg17 `plan7-pg`), Gemini(조립 모델은 `config.py` 의 기존 설정), Next.js 16, Playwright 합성 API(`ui_fixture.cjs`).

**Spec:** 2026-11-11 대화의 사용자 결정(아래 표), `docs/dev/plan/UI_REDESIGN_BACKLOG_20261106.md` '다음 계획(계획 10)' 절, `docs/dev/ASKBUDDY_MVP_CURRENT.md`.

## 사용자 결정 (2026-11-11)

| # | 결정 |
|---|---|
| 1 | 카드 모양(구역·순서·말투·규격 나누기)은 모델에게 맡긴다. 규칙은 '지어냄·빠뜨림' 검사만 |
| 2 | 레시피 카드는 사장님 상세·직원 화면·수정 화면 어디서나 같은 보기. 사실 모양으로 추측해 예전 목록 보기로 떨어지는 로직은 삭제 |
| 3 | 수정은 보기 모양 그대로. 줄을 듀오링고 단어 타일처럼 끌어 옮긴다. 모션이 중요하다 |
| 4 | 표현 예시 '2샷', '꿀 2래들 투입 (샷잔 1/4선)' 은 예시일 뿐 규칙으로 하드코딩하지 않는다 |
| 5 | 자료 모양(표·음성·영상·카톡·문서)을 가정하지 않는다. 단계는 짧으면 화살표 줄, 길면 번호 목록 |
| 6 | 남은 백로그 화면 항목을 이 계획에서 함께 끝낸다 |
| 7 | 알바생 '사장님 승인을 기다리고 있어요' 화면에 로그아웃을 붙인다 |
| 9 | **직원 레시피 목록과 카드 화면은 사장님 카드 목록·카드 상세와 똑같이** 만든다(카테고리 구역 + 굵은 밑줄, 레시피는 2열 타일, 상세는 같은 보기). 직원에게 없는 것은 사장님 전용 동작(밀기·선택·수정·공개)뿐이다 |
| 8 | 표현은 모델이 쓰고 서버가 검사한다(질문 A 의 (2)). 검사는 모델 호출이 아니다 |

## 바뀌는 확정 결정

MVP 31-3 과 `api/app/contracts/card.py` 머리말 "블록은 사실을 고를 뿐 새 문장을 만들지 않는다" 를 이렇게 바꾼다(Task 1): **블록은 사실을 고르고, 모델이 쓴 표시 줄을 함께 가진다. 줄은 근거 사실을 인용하고, 숫자·단위는 근거 사실에 있어야 한다. 답변(R)은 줄이 아니라 사실을 인용한다.** D12(답변은 사실 인용·서버 렌더링)는 그대로다.

## Global Constraints

- 매장 격리: 새 쿼리는 `store_id` 필수 인자, `WHERE store_id = $1`. 끝낼 때 `python3 .claude/skills/store-isolation-check/check_store_id.py api/app` 위반 수 16(시작 값) 그대로.
- 프롬프트는 `api/prompts/` 파일. 코드에 지시문을 두지 않는다. 모델명·임계값은 `api/app/config.py`.
- 특정 낱말·메뉴·단위로 분기하는 코드 금지(사용자 결정 4). `NUMBER_UNIT = {"컵": "온즈"}` 같은 표는 지운다.
- 평가 자료의 상호·메뉴 고유명을 fixture·테스트·문서·커밋에 쓰지 않는다. 테스트는 '합성 꿀 커피', '합성 알갱이' 같은 합성 이름.
- migration 은 가산. 파일명 `20261112090000_card_display_lines.sql` 하나. `verify_r_schema_rebuild.py` FAIL 0.
- 실모델 호출은 실행마다 토큰·USD 를 `api/eval/data/single-call-set/spend.jsonl` 형식으로 남긴다(사용자 규칙). 사용자 승인 없이 실모델을 돌리지 않는다.
- 화면 글: 중간점 금지, 회색 설명 추가 금지, % 금지, `eslint-disable` 금지. `prefers-reduced-motion` 이면 모션을 끈다.
- 커밋하지 않는다(사용자 규칙). 검증 결과는 ledger 에 남긴다.
- 실데이터·운영 DB·배포판을 건드리지 않는다. 운영 반영(재조립 실행 포함)은 사용자가 한다.

## Review Focus

1. 줄에 근거 사실에 없는 숫자가 있으면 그 줄은 사실 원문으로 바뀐다(Task 3 `test_invented_number_rejected`, Task 4 `test_bad_line_falls_back_to_assertions`).
2. 모델이 사실 값을 빠뜨리면 빠진 사실이 줄로 덧붙는다(Task 3 `test_uncovered_values`, Task 4 `test_missing_fact_appended`).
3. 줄이 없는 옛 카드(배포판 기존 카드)도 같은 보기로 나온다 — 블록마다 사실 원문 줄(Task 7 `test_lines_fallback_for_old_version`, Task 8 `VIEW-3`).
4. 사장님이 줄 글을 고치면 그 줄의 사실이 새 판이 되고 줄은 그 판을 인용한다(Task 7 `test_owner_line_edit_rewrites_facts`).
5. 끌어 옮기다 놓지 않고 밖으로 나가면 순서가 바뀌지 않는다(Task 9 `TILE-3`).

---

## 파일 구조

| 파일 | 책임 |
|---|---|
| `supabase/migrations/20261112090000_card_display_lines.sql` | `card_version_blocks.heading`, 표 `card_version_lines` |
| `api/app/contracts/card.py` | `DisplayLine`, `CardBlock.heading`·`lines`(W 표시용, snapshot 에는 싣지 않음) |
| `api/app/ingest/line_check.py` (새) | `numbers_in`, `check_line`, `uncovered_facts` — 순수 함수 |
| `api/app/ingest/schemas.py` | `PlannedLine`, `PlannedBlock.heading`·`lines` |
| `api/app/ingest/card_plan.py` | 검증 완화, 줄 검사 적용, 줄 없는 대체 계획 |
| `api/app/ingest/fact_assembly.py` | 출력 → 줄 제안 |
| `api/app/ingest/fact_cards.py` | 새 판에 머리글·줄 저장, `content` = 줄 |
| `api/app/ingest/fact_normalize.py` (새) | 표 칸 order 지우기, 화살표 통문장 나누기 |
| `api/prompts/assemble_card_plan.ko.txt` | 다시 씀 |
| `api/prompts/extract_facts.ko.txt`, `extract_facts_locator.ko.txt` | 본문 하나로(`extract_facts_body.ko.txt`) + 근거 위치 부분만 둘 |
| `api/app/cards/router.py`, `fact_edit_schemas.py`, `fact_edit.py` | 보기 응답에 줄, 저장 요청에 줄 |
| `api/app/learn/recipe_blocks.py`(`published_fact_blocks`, 직원 레시피 읽기) | 직원 응답에 줄 |
| `api/scripts/reassemble_cards.py` (새) | 저장된 사실로 다시 조립(옛 카드에 줄 만들기) |
| `web/components/owner/fact-card/card-lines-view.tsx` (새) | 보기(어디서나) |
| `web/components/owner/fact-card/line-tiles-editor.tsx` (새) | 수정(타일 끌기) |
| `web/lib/tile-order.ts` (새) | 끌기 중 자리 계산 순수 함수 |
| `web/components/owner/fact-card/fact-group.ts`, `recipe-view.tsx` | `compactRecipe`·`RecipeView`·`FactGroupList` 경로 삭제 |
| `web/app/staff/pending/page.tsx` | 로그아웃, 알림 실패 이유 |

---

### Task 1: 결정 문서

**Files:** Modify `docs/dev/ASKBUDDY_MVP_CURRENT.md`(31-3 절), `CLAUDE.md`(D23 추가), `api/app/contracts/card.py` 머리말.

- [ ] **Step 1:** MVP 31-3 의 "블록은 사실을 고를 뿐 새 문장을 만들지 않는다" 뒤에 위 '바뀌는 확정 결정' 문단을 넣는다.
- [ ] **Step 2:** `CLAUDE.md` 결정 표에 한 줄: `| D23 | **카드 표시는 모델이 쓰고 서버가 검사한다.** 줄마다 근거 사실 인용, 줄의 숫자·단위는 근거 사실에 있어야 하고 사실 값은 빠지면 안 된다(문자열 검사). 실패한 줄만 사실 원문으로. 답변은 줄이 아니라 사실을 인용한다(D12 유지). 사실 모양으로 보기를 고르는 규칙은 두지 않는다 |`
- [ ] **Step 3:** `grep -n "D23" CLAUDE.md docs/dev/ASKBUDDY_MVP_CURRENT.md`. Expected: 둘 다 1줄 이상.

### Task 2: 표시 줄 저장소와 계약

**Files:** Create migration, Test `api/tests/test_plan10_lines_db.py`. Modify `api/app/contracts/card.py`, `api/app/bootstrap/purge.py`(`PURGE_ORDER` 에 `card_version_lines` 를 `card_version_blocks` 앞에), `.claude/skills/store-isolation-check/check_store_id.py`(`TENANT_TABLES` 에 추가).

**Interfaces — Produces:**
- 표 `card_version_lines(store_id bigint, card_version_id bigint, block_id varchar(40), line_no int >= 1, text varchar(300) not null check(btrim(text) <> ''), fact_revision_ids bigint[] not null check(cardinality >= 1), primary key(store_id, card_version_id, block_id, line_no), foreign key (store_id, card_version_id, block_id) references card_version_blocks on delete cascade)`. `card_version_blocks` 와 같은 불변 트리거(수정·삭제 금지, 파기 `WHEN not askbuddy_purging(old.store_id)`).
- 칸 `card_version_blocks.heading varchar(40)` null 허용.
- `DisplayLine(FrozenContract): text: str(1..300), fact_revision_ids: tuple[EntityId, ...](min 1)`; `CardBlock.heading: str | None = None`, `CardBlock.lines: tuple[DisplayLine, ...] = ()`. 줄의 사실은 그 블록 `fact_revision_ids` 안에 있어야 한다(검증기). snapshot 직렬화(`publish/content.py`)는 `heading`·`lines` 를 싣지 않는다(R 계약 불변).

- [ ] **Step 1: 실패하는 테스트**

```python
@unittest.skipUnless(ENABLED, SKIP_REASON)
class LinesSchemaTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.conn, self.name = await fresh_db()
        self.store = await seed_store(self.conn)
        self.version = await self.conn.fetchval(
            "insert into card_versions (store_id, card_id, version_no, title, content, change_source) "
            "values ($1, 1, 1, '합성 꿀 커피', '-', 'EXTRACTION') returning version_id", self.store)
        await self.conn.execute(
            "insert into card_version_blocks (store_id, card_version_id, block_id, kind, block_order, heading) "
            "values ($1, $2, 'b1', 'STEPS', 1, 'HOT')", self.store, self.version)
        await self.conn.execute("set session_replication_role = origin")

    async def asyncTearDown(self):
        await drop_db(self.conn, self.name)

    async def test_line_needs_text_and_facts(self):
        ins = "insert into card_version_lines (store_id, card_version_id, block_id, line_no, text, fact_revision_ids) values ($1, $2, 'b1', 1, $3, $4)"
        with self.assertRaises(Exception):
            await self.conn.execute(ins, self.store, self.version, " ", [1])
        with self.assertRaises(Exception):
            await self.conn.execute(ins, self.store, self.version, "2샷", [])

    async def test_lines_are_immutable_while_store_active(self):
        await self.conn.execute(
            "insert into card_version_lines (store_id, card_version_id, block_id, line_no, text, fact_revision_ids) "
            "values ($1, $2, 'b1', 1, '2샷', '{1}')", self.store, self.version)
        with self.assertRaises(Exception):
            await self.conn.execute("update card_version_lines set text = 'x' where store_id = $1", self.store)

    async def test_purge_lists_lines(self):
        from app.bootstrap import purge
        self.assertLess(purge.PURGE_ORDER.index("card_version_lines"), purge.PURGE_ORDER.index("card_version_blocks"))
```

계약 단위 테스트(`api/tests/test_plan10_contract.py`):

```python
from app.contracts.card import CardBlock, DisplayLine
import pytest

def test_line_must_cite_fact_of_its_block():
    with pytest.raises(ValueError):
        CardBlock(block_id="b1", kind="STEPS", order=1, fact_revision_ids=("1",),
                  lines=(DisplayLine(text="2샷", fact_revision_ids=("9",)),))

def test_snapshot_card_has_no_display_fields():
    from app.publish.content import snapshot_block_payload  # Task 2 가 이름을 붙여 뽑는다
    block = CardBlock(block_id="b1", kind="STEPS", order=1, fact_revision_ids=("1",), heading="HOT",
                      lines=(DisplayLine(text="2샷", fact_revision_ids=("1",)),))
    assert set(snapshot_block_payload(block)) == {"block_id", "kind", "order", "fact_revision_ids"}
```

- [ ] **Step 2:** 틀 DB 지우고 실행. Expected: 모두 FAIL(표·칸·함수 없음).
- [ ] **Step 3:** migration, 계약, `snapshot_block_payload(block: CardBlock) -> dict`(지금 snapshot 이 블록을 싣는 코드를 이 함수로 뽑는다), purge, TENANT_TABLES.
- [ ] **Step 4:** Expected: 통과. `test_plan9_purge_db.py` 의 `test_every_table_is_classified` 통과. `verify_r_schema_rebuild.py` FAIL 0.

### Task 3: 줄 검사(지어냄·빠뜨림)

**Files:** Create `api/app/ingest/line_check.py`, Test `api/tests/test_plan10_line_check.py`.

**Interfaces — Produces:**
- `numbers_in(text: str) -> set[str]`: 숫자 덩어리를 정규화해 모은다. 천 단위 쉼표 제거(`3,900`→`3900`), 소수(`1.5`), 분수(`1/4`), 범위의 각 끝(`3~5`→`3`,`5`). 원문자(`②`)는 숫자가 아니다.
- `check_line(text: str, facts: Sequence[PlanFact]) -> str | None`: 줄 숫자 ⊆ 근거 사실(`assertion`, `original_assertion`, `value_text`, `quantity_value`, `conditions`, `exceptions`)의 숫자. 아니면 `"LINE_INVENTED_NUMBER"`. 단위 검사는 숫자 바로 뒤 글자(공백 무시, 한 낱말)가 근거 사실 글 어딘가에 있어야 한다. 아니면 `"LINE_INVENTED_UNIT"`. 빈 줄은 `"LINE_EMPTY"`.
- `uncovered_facts(lines: Sequence[tuple[str, Sequence[int]]], facts: Sequence[PlanFact]) -> list[int]`: 어느 줄에도 인용되지 않았거나, 인용됐지만 그 사실의 숫자가 인용한 줄들에 하나도 없는 사실의 `fact_revision_id`(입력 순서).

- [ ] **Step 1: 실패하는 테스트**

```python
from app.ingest.line_check import numbers_in, check_line, uncovered_facts
from tests.helpers_plan_fact import pf  # PlanFact 를 짧게 만드는 테스트 도우미(Task 3 이 만든다)

def test_numbers_in():
    assert numbers_in("가격 3,900원, 꿀 2래들 (샷잔 1/4선), 1.5P, 3~5분, ② 얼음") == {"3900", "2", "1/4", "1.5", "3", "5"}

def test_grounded_line_passes():
    facts = [pf(1, "샷=2", value="2"), pf(2, "재료=꿀 2래들 (샷잔 1/4선)", conditions=("샷잔 1/4선",))]
    assert check_line("2샷 내리고 꿀 2래들 투입 (샷잔 1/4선)", facts) is None

def test_invented_number_rejected():
    assert check_line("꿀 3래들 투입", [pf(2, "재료=꿀 2래들")]) == "LINE_INVENTED_NUMBER"

def test_invented_unit_rejected():
    assert check_line("물 1000g", [pf(3, "물 1000ml를 끓인다", value="1000", unit="ml")]) == "LINE_INVENTED_UNIT"

def test_unit_from_label_is_allowed():
    # '샷=2' 의 '샷' 은 사실 글에 있으니 '2샷' 이 된다(낱말로 분기하지 않는다)
    assert check_line("2샷", [pf(1, "샷=2", value="2")]) is None

def test_uncovered_values():
    facts = [pf(1, "샷=2", value="2"), pf(2, "금액=2,700원", value="2700"), pf(3, "얼음=가득")]
    lines = [("2샷", [1]), ("얼음 가득", [3]), ("가격", [2])]
    assert uncovered_facts(lines, facts) == [2]
```

- [ ] **Step 2:** FAIL 확인. **Step 3:** 구현(정규식, 낱말 표 없음). **Step 4:** 6 passed.

### Task 4: 조립 프롬프트와 검증 다시 쓰기

**Files:** Modify `api/prompts/assemble_card_plan.ko.txt`, `api/app/ingest/schemas.py`, `api/app/ingest/fact_assembly.py`, `api/app/ingest/card_plan.py`. Test `api/tests/test_plan10_assembly.py`, 기존 `api/tests/test_w3a_fact_assembly.py`(지워지는 규칙의 테스트는 함께 지운다 — ledger 에 이름을 적는다).

**Interfaces**
- Consumes: Task 3 `check_line`, `uncovered_facts`.
- Produces:
  - `PlannedLine(BaseModel): text: str, facts: list[str]`; `PlannedBlock: kind, heading: str | None = None, lines: list[PlannedLine]`(옛 `facts` 칸은 지운다. 블록 사실 = 줄 사실의 합집합, 줄 순서)
  - `ProposedLine(text: str, refs: tuple[int | str, ...])`, `ProposedBlock(kind, heading, lines)`
  - `ValidatedBlock.heading: str | None`, `ValidatedBlock.lines: tuple[tuple[str, tuple[int, ...]], ...]`
  - `validate_proposals` 가 거르는 것: `PLAN_EMPTY`, `PLAN_UNKNOWN_REF`, `PLAN_OUTSIDE_GROUP`, `PLAN_UNPLACED`(줄 검사 뒤 덧붙인 것 포함 기준). **지우는 규칙:** `PLAN_KIND_MISMATCH`(종류↔step_order), `PLAN_STEP_ORDER`, `PLAN_STEPS_INCOMPLETE`, `PLAN_REQUIRES_MISSING`, `PLAN_VARIANT_MIXED`, `PLAN_DUPLICATE_IN_CARD`(한 사실을 두 줄이 인용해도 된다; 블록 `fact_revision_ids` 는 중복 없이 모은다).
  - 줄 처리: `check_line` 실패한 줄은 그 줄이 인용한 사실마다 사실 원문(`_assertion`) 한 줄로 바꾼다. `uncovered_facts` 는 그 사실이 있는 블록(없으면 마지막 블록) 끝에 원문 줄로 덧붙인다.
  - `fallback_cards` 는 모델이 실패했을 때만: 규격마다 블록 하나, 줄 = 사실 원문, `heading` = 규격 이름(없으면 None), 카드 `needs_review_reason='AUTO_LAYOUT'`.
- 프롬프트(다시 씀) 내용 요구:
  1. 너는 사실 목록을 읽고 직원이 바로 따라 할 수 있는 카드를 쓴다.
  2. 구역(`heading`)은 내용으로 정한다: 규격이 있으면 규격 이름(HOT, ICE), 아니면 '만들기', '보관', '해동' 처럼 하는 일. 정해진 목록이 아니다.
  3. 순서가 있는 일은 실제 하는 순서대로 `kind=STEPS` 한 구역에 줄 하나씩. 순서 없는 값·주의는 `NOTES`/`QUANTITIES`.
  4. 줄은 짧게, 그 단계에서 쓰는 양을 녹여 쓴다. 예시(규칙 아님): 사실 '샷=2' → '2샷', 단계 '재료 투입' 과 사실 '재료=꿀 2래들 (샷잔 1/4선)' → '꿀 2래들 투입 (샷잔 1/4선)'.
  5. 줄의 숫자·단위는 인용한 사실에 있는 것만. 새 값·새 단계·새 주의를 만들지 않는다. 모든 사실을 어느 줄이든 인용한다.
  6. 여러 메뉴에 걸친 주의는 각 메뉴 카드에 넣는다.
  7. 출력 JSON 모양(`cards[].blocks[].{kind, heading, lines[].{text, facts}}`).

- [ ] **Step 1: 실패하는 테스트**

```python
from app.ingest import card_plan
from app.ingest.card_plan import ProposedBlock, ProposedCard, ProposedLine
from tests.helpers_plan_fact import pf, group

def test_free_layout_is_accepted():
    # 표 칸에 order 가 붙어 있어도(배포판 딸기 카드 모양) 모델이 쓴 구역·줄을 그대로 받는다
    g = group(1, "합성 딸기 음료", [pf(1, "구분=스무디", step=1), pf(2, "금액=3,900원", step=3, value="3900"),
                                   pf(3, "블랜더(액상,재료,얼음)", step=1), pf(4, "믹싱", step=2)])
    p = ProposedCard(category_name="음료제작", blocks=(
        ProposedBlock(kind="STEPS", heading="만들기", lines=(ProposedLine("블랜더에 액상, 재료, 얼음", (3,)), ProposedLine("믹싱", (4,)))),
        ProposedBlock(kind="NOTES", heading=None, lines=(ProposedLine("가격 3,900원", (2,)), ProposedLine("스무디", (1,)))),))
    result = card_plan.plan_entity(g, [p])
    assert [b.heading for b in result.cards[0].blocks] == ["만들기", None]
    assert result.cards[0].blocks[0].lines[0] == ("블랜더에 액상, 재료, 얼음", (3,))

def test_bad_line_falls_back_to_assertions():
    g = group(1, "합성 꿀 커피", [pf(1, "샷=2", value="2")])
    p = ProposedCard(category_name="음료제작", blocks=(ProposedBlock(kind="NOTES", heading=None, lines=(ProposedLine("3샷", (1,)),)),))
    lines = card_plan.plan_entity(g, [p]).cards[0].blocks[0].lines
    assert lines == (("샷=2", (1,)),)

def test_missing_fact_appended():
    g = group(1, "합성 꿀 커피", [pf(1, "샷=2", value="2"), pf(2, "얼음=가득")])
    p = ProposedCard(category_name="음료제작", blocks=(ProposedBlock(kind="NOTES", heading=None, lines=(ProposedLine("2샷", (1,)),)),))
    lines = card_plan.plan_entity(g, [p]).cards[0].blocks[0].lines
    assert lines[-1] == ("얼음=가득", (2,))

def test_model_failure_uses_fallback_with_lines():
    g = group(1, "합성 알갱이", [pf(1, "물 1000ml를 끓인다", step=1, value="1000"), pf(2, "보관은 24시간")])
    card = card_plan.plan_entity(g, []).cards[0]
    assert card.needs_review_reason == "AUTO_LAYOUT"
    assert [l[0] for b in card.blocks for l in b.lines] == ["물 1000ml를 끓인다", "보관은 24시간"]

def test_prompt_rules_present():
    text = open("prompts/assemble_card_plan.ko.txt", encoding="utf-8").read()
    for needle in ["heading", "lines", "2샷", "꿀 2래들 투입 (샷잔 1/4선)", "예시", "인용한 사실에 있는 것만", "모든 사실"]:
        assert needle in text, needle
    assert "새 문장·제목·값·숫자·단위·조건·예외를 쓰지 않는다" not in text  # 옛 규칙 제거
```

(`ValidatedCard.needs_review_reason: str | None` 을 더한다. 이 계획에서 처음 쓰는 이름이다.)

- [ ] **Step 2:** FAIL 확인. **Step 3:** 구현. 지운 옛 테스트 이름을 ledger 에 적는다. **Step 4:** `pytest tests/test_plan10_assembly.py tests/test_w3a_fact_assembly.py -q` 통과.

### Task 5: 새 판에 머리글·줄 저장

**Files:** Modify `api/app/ingest/fact_cards.py`(판·블록 쓰는 곳), Test `api/tests/test_plan10_lines_db.py`(추가).

**Interfaces — Produces:** `write_card_blocks(conn, store_id: int, *, version_id: int, blocks: Sequence[ValidatedBlock]) -> None` — `card_version_blocks`(heading 포함)·`card_block_facts`·`card_version_lines` 를 한 번에. 판 `content` = 블록 순서대로 `heading` 줄(있으면) + 줄 글, 줄바꿈으로 잇는다(검색·임베딩이 이 글을 쓴다).

- [ ] **Step 1: 실패하는 테스트**

```python
    async def test_write_blocks_stores_heading_lines_and_content(self):
        from app.ingest.fact_cards import write_card_blocks
        from app.ingest.card_plan import ValidatedBlock
        blocks = [ValidatedBlock(block_id="b1", kind="STEPS", order=1, fact_revision_ids=(11, 12), variant=(None, None),
                                 heading="만들기", lines=(("물 끓이기", (11,)), ("15분 삶기", (12,))))]
        # 판과 사실 판(11, 12)은 합성으로 미리 넣는다(fixture 도우미)
        await write_card_blocks(self.conn, self.store, version_id=self.version, blocks=blocks)
        rows = await self.conn.fetch("select line_no, text, fact_revision_ids from card_version_lines where store_id = $1 order by line_no", self.store)
        self.assertEqual([(r["line_no"], r["text"], list(r["fact_revision_ids"])) for r in rows], [(1, "물 끓이기", [11]), (2, "15분 삶기", [12])])
        content = await self.conn.fetchval("select content from card_versions where store_id = $1 and version_id = $2", self.store, self.version)
        self.assertEqual(content, "만들기\n물 끓이기\n15분 삶기")
```

- [ ] **Step 2–4:** FAIL → 구현(기존 블록 쓰기를 이 함수로 모은다) → 통과. 전체 pytest(실 DB) 통과, `verify_r_schema_rebuild.py` FAIL 0, `verify_w_fact_only.py`·`verify_w3a_fact_assembly.py` 는 rebuild 안에서 통과.

### Task 6: 추출 정리 — 프롬프트 한 벌, 표 칸·화살표 보정

**Files:** Create `api/prompts/extract_facts_body.ko.txt`, `api/prompts/extract_facts_evidence_basic.ko.txt`, `api/prompts/extract_facts_evidence_locator.ko.txt`; Delete `extract_facts.ko.txt`, `extract_facts_locator.ko.txt`; Modify `api/app/ingest/extract/gemini.py`(`render_facts_prompt`), 이 두 파일 이름을 부르는 코드·테스트(`grep -rn "extract_facts.ko.txt\|extract_facts_locator" api` 의 모든 자리). Create `api/app/ingest/fact_normalize.py`, Modify 추출 결과를 원장에 넣기 직전(`fact_cards.py` 의 추출 결과 처리 입구). Test `api/tests/test_plan10_extract_prompt.py`, `api/tests/test_plan10_fact_normalize.py`.

**Interfaces — Produces:**
- `render_facts_prompt(...)`(시그니처 그대로) = body 의 `{evidence_rules}` 자리에 basic/locator 중 하나.
- `normalize_extracted(facts: list[ExtractedAssertion]) -> list[ExtractedAssertion]`:
  - 화살표가 없고 `이름=값` 모양(첫 `=` 앞이 비지 않음)인 사실은 `order=None`.
  - 같은 `assertion` 이 화살표를 가진 채 여러 사실에 반복되고 각 `value` 가 화살표로 나눈 조각 하나와 같으면, 각 사실의 `assertion` 을 그 조각으로 바꾸고 `order` 를 조각 순서로 다시 매긴다. 원문은 `original_assertion` 에 남는다.

- [ ] **Step 1: 실패하는 테스트**

```python
# test_plan10_extract_prompt.py
from app.ingest.extract.gemini import render_facts_prompt

def test_one_body_two_evidence_parts():
    a = render_facts_prompt(source_type="SCAN", text="x", glossary=[], locator_hints=False)
    b = render_facts_prompt(source_type="SCAN", text="x", glossary=[], locator_hints=True)
    assert a.split("## 매장 용어 사전")[0].replace(a[a.index("8. **근거 위치"):a.index("9. `local_ref`")], "") == \
           b.split("## 매장 용어 사전")[0].replace(b[b.index("8. **근거 위치"):b.index("9. `local_ref`")], "")
    assert "[3쪽]" in b and "[3쪽]" not in a

def test_multi_menu_note_rule():
    assert "여러 메뉴에 걸친" in render_facts_prompt(source_type="SCAN", text="x", glossary=[])

# test_plan10_fact_normalize.py
from app.ingest.fact_normalize import normalize_extracted
from tests.helpers_plan_fact import ea   # ExtractedAssertion 짧게

def test_table_cell_loses_order():
    out = normalize_extracted([ea("구분=스무디", order=1), ea("금액=3,900원", order=3)])
    assert [f.order for f in out] == [None, None]

def test_repeated_arrow_sentence_is_split():
    s = "제조순서=블랜더 → 믹싱 → 토핑"
    out = normalize_extracted([ea(s, order=1, value="블랜더"), ea(s, order=2, value="믹싱"), ea(s, order=5, value="토핑")])
    assert [(f.assertion, f.order) for f in out] == [("블랜더", 1), ("믹싱", 2), ("토핑", 3)]

def test_arrow_step_keeps_order():
    out = normalize_extracted([ea("블랜더(재료,얼음)", order=1)])
    assert out[0].order == 1
```

- [ ] **Step 2–4:** FAIL → 구현 → 통과. 전체 pytest 통과. 렌더 결과가 바뀌므로 추출 재사용 키가 바뀐다 — ledger 에 '재사용 키 갱신, D16 비교 기준은 Task 12 실측의 새 기준선' 으로 적는다.

### Task 7: 보기 응답에 줄, 저장 요청에 줄

**Files:** Modify `api/app/cards/router.py`(`GET /{card_id}/facts`, `PUT /{card_id}/facts`), `api/app/cards/fact_edit_schemas.py`, `api/app/cards/fact_edit.py`, 직원 레시피 읽기(`api/app/learn/recipe_blocks.py` 의 `published_fact_blocks` — `learn/` 아래라 R 담당에 알린다). Test `api/tests/test_plan10_lines_api.py`(실 DB).

**Interfaces — Produces:**
- 보기: `CardFactsView.blocks[].heading: str | None`, `.lines: list[{line_no: int, text: str, fact_revision_ids: list[int]}]`. 줄이 없는 옛 판은 서버가 블록 사실마다 원문 한 줄을 만들어 준다(`heading` = 규격 이름 또는 None).
- 저장: `EditBlock.heading: str | None = None(max 40)`, `EditBlock.lines: list[EditLine] | None = None`. `EditLine(text: str 1..300, fact_revision_ids: list[int] = [], client_refs: list[str] = [])` — 둘 합쳐 1개 이상, 모두 그 블록 `items` 안의 판 id 또는 ADD `client_ref`. `lines` 가 없으면 서버가 블록 사실마다 원문 줄을 만든다. 사장님 줄은 `check_line` 을 하지 않는다(사장님이 원천이다). `save_fact_edit` 이 새 판을 만든 뒤 `write_card_blocks` 로 쓴다(`client_ref` 는 새 판 id 로 바꿔 쓴다).
- 새 오류: 400 `LINE_REF_OUTSIDE_BLOCK`.

- [ ] **Step 1: 실패하는 테스트**

```python
    async def test_lines_fallback_for_old_version(self):
        # 줄 없이 블록·사실만 있는 옛 판(배포판 카드)
        view = await get_card_facts(self.card, self.conn, self.owner_claims)
        self.assertEqual([(l.line_no, l.text) for l in view.blocks[0].lines], [(1, "샷=2"), (2, "얼음=가득")])

    async def test_owner_line_edit_rewrites_facts(self):
        req = FactEditRequest(expected_version_id=self.version, idempotency_key="plan10-edit-1", blocks=[EditBlock(
            kind="STEPS", heading="HOT",
            items=[EditModify(op="MODIFY", fact_revision_id=self.f_shot, fact=FactFields(sentence="샷=3", value="3")),
                   EditKeep(op="KEEP", fact_revision_id=self.f_ice)],
            lines=[EditLine(text="얼음 가득", fact_revision_ids=[self.f_ice]), EditLine(text="3샷", fact_revision_ids=[self.f_shot])])])
        result = await put_card_facts(self.card, req, self.conn, self.owner_claims)
        rows = await self.conn.fetch("select line_no, text, fact_revision_ids from card_version_lines where store_id = $1 and card_version_id = $2 order by line_no",
                                     self.store, result.version_id)
        self.assertEqual([r["text"] for r in rows], ["얼음 가득", "3샷"])
        self.assertNotIn(self.f_shot, list(rows[1]["fact_revision_ids"]))  # 고친 사실은 새 판을 인용한다

    async def test_line_ref_outside_block_rejected(self):
        req = FactEditRequest(expected_version_id=self.version, idempotency_key="plan10-edit-2", blocks=[EditBlock(
            kind="NOTES", items=[EditKeep(op="KEEP", fact_revision_id=self.f_ice)],
            lines=[EditLine(text="2샷", fact_revision_ids=[self.f_shot])])])
        with self.assertRaises(ApiError) as err:
            await put_card_facts(self.card, req, self.conn, self.owner_claims)
        self.assertEqual(err.exception.code, "LINE_REF_OUTSIDE_BLOCK")

    async def test_staff_view_has_lines_of_published_version_only(self):
        from app.learn.recipe_blocks import published_fact_blocks
        # setUp 이 공개 판(self.published, 줄 '2샷')과 그 뒤 초안 판(self.version, 줄 '3샷')을 만들어 둔다
        blocks = await published_fact_blocks(self.conn, self.store, self.card, self.published)
        self.assertEqual([l["text"] for b in blocks for l in b["lines"]], ["2샷"])
        self.assertEqual(blocks[0]["heading"], "HOT")
```

(`get_card_facts`·`put_card_facts` 는 지금 라우트 함수 이름으로 맞춘다.)

- [ ] **Step 2–4:** FAIL → 구현 → 통과. `check_store_id.py api/app` 16 그대로.

### Task 8: 보기는 어디서나 하나

**Files:** Create `web/components/owner/fact-card/card-lines-view.tsx`, `web/lib/line-layout.ts`, `web/tests/line-layout.test.mjs`. Modify `web/components/owner/fact-card/fact-card-panel.tsx`, `web/app/owner/cards/[cardId]/page.tsx`, `web/app/staff/recipes/[itemId]/page.tsx`, `web/lib/api.ts`(타입), `api/scripts/ui_fixture.cjs`. Delete `compactRecipe`·`RecipeView`·`FactGroupList`·`NUMBER_UNIT` 와 그 테스트(`web/tests/compact-recipe.test.mjs`).

**Interfaces — Produces:** `lineLayout(lines: string[], kind: string): "ARROW" | "NUMBERED" | "LIST"` — `STEPS` 이고 모든 줄이 16자 이하면 `ARROW`, `STEPS` 면 `NUMBERED`, 아니면 `LIST`. 가격은 제목 옆에 따로 두지 않는다(모델이 줄로 쓴다).

- [ ] **Step 1: 실패하는 테스트**

```js
// web/tests/line-layout.test.mjs
import assert from "node:assert/strict";
import { test } from "node:test";
import { lineLayout } from "../lib/line-layout.ts";
test("16자 넘는 줄이 하나라도 있으면 번호 목록", () => assert.equal(lineLayout(["2샷", "얼음 가득", "꿀 2래들 투입 (샷잔 1/4선)"], "STEPS"), "NUMBERED"));
test("모두 짧으면 화살표", () => assert.equal(lineLayout(["2샷", "얼음 가득", "물 붓기"], "STEPS"), "ARROW"));
test("순서 아닌 구역은 목록", () => assert.equal(lineLayout(["24시간 보관"], "NOTES"), "LIST"));
```

```js
// verify_ui_plan10.cjs
test('VIEW-1 사장님 상세: 구역 제목과 줄, 화살표 단계', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/cards/1', { overrides: { lineCard: 'short' } });
  await page.getByRole('heading', { name: 'HOT' }).waitFor();
  assert.equal(await page.locator('[data-layout="ARROW"] [data-line]').count(), 3);
  assert.equal(await page.getByText('수치').count(), 0);
  await ctx.close();
});
test('VIEW-2 긴 단계는 번호 목록, 보관은 목록', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/cards/1', { overrides: { lineCard: 'long' } });
  await page.locator('[data-layout="NUMBERED"]').waitFor();
  await page.getByRole('heading', { name: '보관' }).waitFor();
  await ctx.close();
});
test('VIEW-3 줄 없는 옛 카드도 같은 보기', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/cards/1', { overrides: { lineCard: 'legacy' } });
  await page.locator('[data-line]').first().waitFor();
  await ctx.close();
});
test('VIEW-4 직원 레시피도 같은 보기', async (b) => {
  const { page, ctx } = await open(b, 'STAFF', '/staff/recipes/11', { overrides: { lineCard: 'short' } });
  await page.locator('[data-layout="ARROW"]').waitFor();
  await ctx.close();
});
```

- [ ] **Step 2–4:** FAIL → 구현(fixture 에 `lineCard` 세 모양) → 통과. 기존 묶음(`verify_ui_cards`, `verify_w3b_card_facts_ui`, `verify_ui_staff`)에서 옛 보기를 보던 단언은 새 보기로 바꾼다(ledger 에 이름). `pnpm check` 통과.

### Task 8b: 직원 레시피 목록·카드도 사장님과 똑같이

**Files:** Create `web/components/cards/card-section-grid.tsx`(사장님 카드 목록의 구역·격자를 뽑는다). Modify `web/app/owner/cards/page.tsx`(이 부품을 쓴다), `web/app/staff/recipes/page.tsx`(ListGroup·ListRow 목록을 이 부품으로), `web/app/staff/recipes/[itemId]/page.tsx`(`splitVariants`·`parts` 글 경로 삭제, 사장님 상세와 같은 머리·`CardLinesView`). Test `verify_ui_plan10.cjs`.

**Interfaces**
- Consumes: Task 8 `CardLinesView`, `lineLayout`.
- Produces: `CardSectionGrid<T>({ items: T[], sectionOf: (t: T) => string, kindOf: (t: T) => "RECIPE" | "TASK" | "INFO" | null, renderTile: (t: T) => ReactNode })` — 구역마다 `<section aria-labelledby>` + `<h2 class="border-b-2 border-ink ...">`, 레시피 구역은 `grid-cols-2`, 나머지 `grid-cols-1`. 사장님 목록과 직원 목록이 같은 부품을 쓴다. 직원 타일은 `CardTile` 을 `status="approved"`, `left`/`right`/`select` 없이 쓰고 누르면 `/staff/recipes/{item_id}`.

- [ ] **Step 1: 실패하는 테스트**

```js
test('STAFF-LIST-1 직원 레시피 목록은 사장님 카드 목록과 같은 구역·격자', async (b) => {
  const { page, ctx } = await open(b, 'STAFF', '/staff/recipes');
  const section = page.getByRole('region', { name: '음료 레시피' });
  await section.getByRole('heading', { name: '음료 레시피' }).waitFor();
  assert.match(await section.locator('h2').getAttribute('class'), /border-b-2 border-ink/);
  assert.match(await section.locator('> div').getAttribute('class'), /grid-cols-2/);
  assert.equal(await page.locator('main li').count(), 0, 'ListRow 목록이 아니다');
  await ctx.close();
});
test('STAFF-LIST-2 같은 부품: 사장님 구역 머리와 직원 구역 머리의 class 가 같다', async (b) => {
  const owner = await open(b, 'OWNER', '/owner/cards?status=approved');
  const ownerClass = await owner.page.getByRole('heading', { name: '음료 레시피' }).getAttribute('class');
  await owner.ctx.close();
  const staff = await open(b, 'STAFF', '/staff/recipes');
  assert.equal(await staff.page.getByRole('heading', { name: '음료 레시피' }).getAttribute('class'), ownerClass);
  await staff.ctx.close();
});
test('STAFF-LIST-3 직원 타일에는 밀기·선택이 없다', async (b) => {
  const { page, ctx } = await open(b, 'STAFF', '/staff/recipes');
  assert.equal(await page.getByRole('button', { name: /삭제$|미공개$|공개$/ }).count(), 0);
  assert.equal(await page.getByRole('button', { name: '선택' }).count(), 0);
  await ctx.close();
});
test('STAFF-CARD-1 직원 카드 상세는 사장님 상세와 같은 보기, 수치·순서·목록 머리와 근거 줄이 없다', async (b) => {
  const { page, ctx } = await open(b, 'STAFF', '/staff/recipes/11', { overrides: { lineCard: 'long' } });
  await page.locator('[data-layout="NUMBERED"]').waitFor();
  for (const old of ['수치', '순서', '목록']) assert.equal(await page.getByRole('heading', { name: old, exact: true }).count(), 0, old);
  assert.equal(await page.getByText(/^근거:/).count(), 0);
  await page.getByRole('button', { name: '확인했어요' }).waitFor();   // 직원 동작은 그대로
  await ctx.close();
});
test('STAFF-CARD-2 줄 없는 옛 공개 카드도 같은 보기', async (b) => {
  const { page, ctx } = await open(b, 'STAFF', '/staff/recipes/11', { overrides: { lineCard: 'legacy' } });
  await page.locator('[data-line]').first().waitFor();
  assert.equal(await page.getByRole('heading', { name: '수치', exact: true }).count(), 0);
  await ctx.close();
});
```

(fixture: 로드맵 항목에 카테고리 `kind` 를 싣고, `/learn/items/{id}` 의 `fact_blocks` 를 Task 7 모양(`heading`·`lines`)으로. `lineCard` 는 Task 8 과 같은 세 모양.)

- [ ] **Step 2–4:** FAIL → 구현 → 통과. 기존 `verify_ui_staff.cjs` 의 목록·상세 단언은 새 모양으로 바꾼다(이름을 ledger 에). `pnpm check` 통과.

### Task 9: 수정은 타일 끌기 (모션 선택 먼저)

**Files:** Create `web/lib/tile-order.ts`, `web/tests/tile-order.test.mjs`, `web/components/owner/fact-card/line-tiles-editor.tsx`, `web/components/owner/fact-card/line-edit-sheet.tsx`. Modify `fact-card-panel.tsx`(수정 모드가 이 편집기를 쓴다), `use-fact-edit-draft.ts`(초안이 줄을 가진다), `ui_fixture.cjs`(PUT 본문 기록).

- [ ] **Step 0 (사용자 선택):** 모션 후보 3개를 artifact 로 보여 주고 고르게 한다. 후보: (A) 듀오링고처럼 들린 타일이 손가락을 따라오고 다른 타일이 자리로 미끄러짐(220ms, `--ease-spring`), (B) A + 놓을 때 살짝 튕김, (C) A + 화살표가 타일 사이를 따라 움직임. 고른 값을 ledger 에 적고 그 값으로 구현한다.

**Interfaces — Produces:** `moveTile(order: string[], from: number, to: number): string[]`, `slotAt(centers: number[], x: number, y: number, rowOf: number[]): number`(손가락 위치에서 들어갈 자리). 편집기는 `onChange(sections: DraftSection[])`. 줄을 누르면 시트에서 글을 고치고, 저장 때 고친 줄은 `/facts/parse` 로 사실 후보를 받아 MODIFY/ADD 로 바꾼 뒤 `PUT /facts` 에 `lines` 와 함께 보낸다.

- [ ] **Step 1: 실패하는 테스트**

```js
// tile-order.test.mjs
import assert from "node:assert/strict";
import { test } from "node:test";
import { moveTile, slotAt } from "../lib/tile-order.ts";
test("앞으로 옮기기", () => assert.deepEqual(moveTile(["a", "b", "c"], 2, 0), ["c", "a", "b"]));
test("제자리면 그대로", () => assert.deepEqual(moveTile(["a", "b"], 1, 1), ["a", "b"]));
test("두 줄로 감긴 타일에서 아래 줄 첫 자리", () => assert.equal(slotAt([40, 120, 40], 10, 70, [0, 0, 1]), 2));
```

```js
// verify_ui_plan10.cjs
test('TILE-1 끌어서 단계 순서를 바꾸고 저장', async (b) => {
  const { page, ctx, api } = await open(b, 'OWNER', '/owner/cards/1', { overrides: { lineCard: 'short' } });
  await page.getByRole('button', { name: '수정하기' }).click();
  const tiles = page.locator('[data-tile]');
  const from = await tiles.nth(2).boundingBox(), to = await tiles.nth(0).boundingBox();
  await page.mouse.move(from.x + 10, from.y + 10); await page.mouse.down();
  await page.mouse.move(to.x + 5, to.y + 10, { steps: 12 }); await page.mouse.up();
  assert.deepEqual(await tiles.allTextContents(), ['물 붓기', '2샷', '얼음 가득']);
  await page.getByRole('button', { name: '수정 완료' }).click();
  const body = api.calls.find((c) => c.method === 'PUT' && c.path === '/cards/1/facts').body;
  assert.deepEqual(body.blocks[0].lines.map((l) => l.text), ['물 붓기', '2샷', '얼음 가득']);
  await ctx.close();
});
test('TILE-2 키보드로도 옮긴다', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/cards/1', { overrides: { lineCard: 'short' } });
  await page.getByRole('button', { name: '수정하기' }).click();
  await page.getByRole('button', { name: '물 붓기 옮기기' }).focus();
  await page.keyboard.press('ArrowLeft');
  assert.equal((await page.locator('[data-tile]').allTextContents())[1], '물 붓기');
  await ctx.close();
});
test('TILE-3 화면 밖에서 놓으면 그대로', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/cards/1', { overrides: { lineCard: 'short' } });
  await page.getByRole('button', { name: '수정하기' }).click();
  const before = await page.locator('[data-tile]').allTextContents();
  const box = await page.locator('[data-tile]').nth(0).boundingBox();
  await page.mouse.move(box.x + 5, box.y + 5); await page.mouse.down();
  await page.mouse.move(-50, -50, { steps: 8 }); await page.mouse.up();
  assert.deepEqual(await page.locator('[data-tile]').allTextContents(), before);
  await ctx.close();
});
test('TILE-4 줄을 눌러 글을 고치면 다시 분석해 저장', async (b) => {
  const { page, ctx, api } = await open(b, 'OWNER', '/owner/cards/1', { overrides: { lineCard: 'short' } });
  await page.getByRole('button', { name: '수정하기' }).click();
  await page.locator('[data-tile]').nth(0).click();
  const sheet = page.getByRole('dialog', { name: '이 줄 고치기' });
  await sheet.getByRole('textbox').fill('3샷');
  await sheet.getByRole('button', { name: '바꾸기' }).click();
  await page.getByRole('button', { name: '수정 완료' }).click();
  assert.ok(api.calls.some((c) => c.path === '/cards/1/facts/parse' && c.body.text === '3샷'));
  await ctx.close();
});
test('TILE-5 모션 줄이기 설정이면 옮김 모션이 없다', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/cards/1', { overrides: { lineCard: 'short' } });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.getByRole('button', { name: '수정하기' }).click();
  const d = await page.locator('[data-tile]').first().evaluate((el) => getComputedStyle(el).transitionDuration);
  assert.equal(d, '0s');
  await ctx.close();
});
```

- [ ] **Step 2–4:** FAIL → 구현(포인터 이벤트 + FLIP, 라이브러리 추가 없음) → 통과. 360·390 폭 가로 넘침 없음(LAY 검사 하나 추가).

### Task 10: 알바생 대기 화면 로그아웃, 알림 실패 이유

**Files:** Modify `web/app/staff/pending/page.tsx`, `web/lib/push.ts`(`enablePersonalPush` 가 실패 이유를 돌려준다). Test `verify_ui_plan10.cjs`.

**Interfaces — Produces:** `enablePersonalPush(token) -> "enabled" | "denied" | "unsupported" | "not_configured" | { failed: string }` — 서버 오류면 `apiErrorMessage`, 브라우저 구독 실패면 '이 기기에서 알림 구독을 만들지 못했어요.'.

- [ ] **Step 1: 실패하는 테스트**

```js
test('WAIT-1 대기 화면에서 로그아웃', async (b) => {
  const { page, ctx, api } = await open(b, 'STAFF', '/staff/pending', { overrides: { noStore: true } });
  await page.getByRole('button', { name: '로그아웃' }).click();
  await page.getByRole('dialog', { name: '로그아웃할까요?' }).getByRole('button', { name: '로그아웃' }).click();
  await page.waitForURL((u) => u.pathname === '/');
  assert.ok(api.calls.some((c) => c.path === '/auth/logout'));
  await ctx.close();
});
test('WAIT-2 알림 실패는 이유를 보인다', async (b) => {
  const { page, ctx } = await open(b, 'STAFF', '/staff/pending', { overrides: { noStore: true, pushEnv: { permission: 'granted' }, failMySubscription: true } });
  await page.getByRole('button', { name: '승인되면 알림 받기' }).click();
  await page.getByText('알림 설정에 실패했어요.').waitFor();
  await page.getByText('구독 저장 실패').waitFor();   // fixture 가 돌려준 서버 문구
  await ctx.close();
});
```

- [ ] **Step 2–4:** FAIL → 구현 → 통과. 배포판의 실패 원인 확인은 사용자 단계(아래)로: 배포판 `GET /notifications/push-key` 응답의 `push_configured` 가 false 면 VAPID 값이 env 에 없는 것이다.

### Task 11: 남은 화면 백로그

백로그의 '테스트 빈 곳' 두 줄(83줄, 123줄)은 이미 테스트가 있다: Q-1(`verify_ui_backlog.cjs`), GAP-1~4(`verify_ui_plan7.cjs`). 체크만 안 됐다. 남은 화면 항목은 선택 모드 자동 스크롤 하나다.

**Files:** Modify 카드 목록 끌어 고르기(`web/lib/drag-select.ts` 와 그것을 쓰는 `web/app/owner/cards/page.tsx`), `docs/dev/plan/UI_REDESIGN_BACKLOG_20261106.md`. Test `verify_ui_plan10.cjs`, `web/tests/drag-select.test.mjs`(추가).

**Interfaces — Produces:** `edgeScrollSpeed(y: number, top: number, bottom: number, edge = 48, max = 18): number` — 위 가장자리 안이면 음수, 아래면 양수, 가장자리에 가까울수록 크다(선형, 최대 `max` px/프레임). 끌기 중 `requestAnimationFrame` 마다 이 값만큼 `main` 을 스크롤하고, 스크롤한 만큼 고르기 범위를 넓힌다.

- [ ] **Step 1: 실패하는 테스트**

```js
// drag-select.test.mjs 에 추가
import { edgeScrollSpeed } from "../lib/drag-select.ts";
test("가장자리 밖이면 멈춤", () => assert.equal(edgeScrollSpeed(400, 0, 800), 0));
test("아래 가장자리 끝이면 최대 속도", () => assert.equal(edgeScrollSpeed(800, 0, 800), 18));
test("위 가장자리 중간이면 반 속도로 위로", () => assert.equal(edgeScrollSpeed(24, 0, 800), -9));
```

```js
// verify_ui_plan10.cjs
test('BL-1 선택 모드에서 아래 가장자리로 끌면 저절로 스크롤하고 계속 고른다', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/cards?status=all', { overrides: { manyCards: 40 } });
  await page.getByRole('button', { name: '선택' }).click();
  const first = await page.locator('[data-card-tile]').first().boundingBox();
  const vh = page.viewportSize().height;
  await page.mouse.move(first.x + 20, first.y + 20); await page.mouse.down();
  await page.mouse.move(first.x + 20, vh - 4, { steps: 10 });
  await page.waitForTimeout(800);
  assert.ok(await page.evaluate(() => document.querySelector('main').scrollTop) > 0);
  await page.mouse.up();
  assert.ok(await page.locator('[data-card-tile][aria-pressed="true"]').count() > 8);
  await ctx.close();
});
```

(fixture 에 `manyCards: n` — 합성 카드 n 장을 '음료 레시피' 에 만든다.)

- [ ] **Step 2–4:** FAIL → 구현 → 통과. 백로그 83·123줄을 `[x]`(근거: Q-1, GAP-1~4), 156줄(자동 스크롤)을 `[x]`, 61줄(삭제된 카드에 걸린 제안 수)을 `[x]`(근거: `learn/router.py` 의 `target_review_status`, `owner/cards/page.tsx` 199줄 필터 — 2026-11-08 이미 고침).

### Task 12: 실모델 실측(사용자 승인 뒤)

**Files:** `api/scripts/run_extract_eval.py`(기존), 결과는 `api/eval/data/plan10/`(Git 제외 경로 여부 확인 후).

- [ ] **Step 1:** 사용자 승인 받기(비용 상한 USD 를 함께 정한다).
- [ ] **Step 2:** 바꾸기 전(`main` 작업 트리)과 후(이 브랜치)로 매장 A~D 의 레시피가 든 자료(영상·음성·카톡·스캔)를 추출+조립. 실행마다 토큰·USD 를 spend 에 남긴다.
- [ ] **Step 3:** 카드마다 줄 JSON 과 390px 화면 캡처(합성 API 에 결과를 넣어 렌더)를 만들고, 표로 비교: 줄 검사로 바뀐 줄 수, 덧붙은 빠진 사실 수, 대체 계획(AUTO_LAYOUT) 카드 수.
- [ ] **Step 4:** 사용자에게 캡처를 보여 주고 프롬프트를 고친다(고칠 때마다 Step 2 의 '후'만 다시). 끝난 값을 ledger 에.

### Task 13: 옛 카드 다시 조립 도구

**Files:** Create `api/scripts/reassemble_cards.py`, Test `api/tests/test_plan10_reassemble.py`(실 DB, 모델은 가짜).

**Interfaces — Produces:** `reassemble_store(conn, store_id: int, *, plan_call, dry_run: bool) -> dict`(`{"cards": n, "new_drafts": n, "skipped_published_only": n}`). 저장된 사실로 조립만 다시 하고 **초안 판**을 새로 만든다. 공개 판은 그대로(사장님이 다시 공개해야 바뀐다). `--store`, `--dry-run` 인자. 운영 실행은 사용자가 한다.

- [ ] **Step 1: 실패하는 테스트**

```python
    async def test_reassemble_makes_draft_with_lines_and_keeps_published(self):
        from scripts.reassemble_cards import reassemble_store
        out = await reassemble_store(self.conn, self.store, plan_call=self.fake_plan, dry_run=False)
        self.assertEqual(out["new_drafts"], 1)
        row = await self.conn.fetchrow("select draft_version_id, published_version_id from knowledge_cards where store_id = $1 and card_id = $2", self.store, self.card)
        self.assertNotEqual(row["draft_version_id"], row["published_version_id"])
        self.assertEqual(row["published_version_id"], self.published)
        self.assertGreater(await self.conn.fetchval("select count(*) from card_version_lines where store_id = $1 and card_version_id = $2", self.store, row["draft_version_id"]), 0)

    async def test_dry_run_writes_nothing(self):
        from scripts.reassemble_cards import reassemble_store
        before = await self.conn.fetchval("select count(*) from card_versions where store_id = $1", self.store)
        await reassemble_store(self.conn, self.store, plan_call=self.fake_plan, dry_run=True)
        self.assertEqual(await self.conn.fetchval("select count(*) from card_versions where store_id = $1", self.store), before)
```

- [ ] **Step 2–4:** FAIL → 구현 → 통과. `check_store_id.py api/scripts` 에 새 위반 없음.

### Task 14: 마무리

- [ ] 전체 pytest(실 DB), `verify_r_schema_rebuild.py` FAIL 0, `node --test web/tests`, 전체 `run-ui.sh`(OLD=1) 통과를 ledger 에.
- [ ] `store-isolation-check`, `web-async-state-check`, `ui-state-walkthrough` 스킬.
- [ ] 백로그 문서의 계획 10 절 항목을 `[x]` 로, 남은 서버·R 항목은 담당·이유와 함께 남긴다.

## 담당과 맞출 것(R)

- Task 2: snapshot 블록 직렬화를 `snapshot_block_payload` 로 뽑는다(내용 불변).
- Task 7: 직원 레시피 읽기가 줄을 준다(공개 판만).
- 남은 R 백로그(이 계획에서 코드로 하지 않음, 담당 합의 뒤 따로): '몇 번 물어봤어요' 횟수(`/learn/v2/pending`), 같은 질문 중복, 엉뚱한 되묻기, `general_semantics` 의 `USAGE_UNAVAILABLE` 이 CI 에서 가끔 나는 원인(로그 한 줄을 넣었다).

## 사용자 단계

1. 계획 9·8 PR 머지(배포 순서는 앞서 정리한 대로). 머지되면 배포판에 `avatars` 버킷이 생겨 사진 바꾸기가 된다.
2. `api/app/learn/general_semantics.py` 로그 한 줄 커밋·푸시.
3. 배포판 `GET /notifications/push-key` 확인(Task 10).
4. Task 12 실모델 비용 상한 승인.
5. 계획 10 머지·배포 뒤 `python scripts/reassemble_cards.py --store <id> --dry-run` 으로 확인하고 실제 실행.
6. 계획 8 Task 9(약관)는 운영자 값이 오면.

## 이 계획이 하지 않는 것

- 답변(R)이 줄을 인용하게 하는 것. 답변은 계속 사실을 인용한다.
- 표현 줄을 위한 별도 모델 호출. 조립 호출 하나가 쓴다.
- 비용 대시보드(제안만 함, 사용자 결정 대기).
