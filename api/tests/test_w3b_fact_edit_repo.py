"""W3b-3 사실 카드 읽기 — 적재 SQL 의 매장 격리, head 분류, 상태 적재, 화면 변환.

DB 는 부르지 않는다. FakeConn 이 SQL 을 기록하고 미리 정한 행을 돌려준다.
실제 DB 동작은 scripts/verify_w3b_card_fact_edit.py 의 R1~R3 이 본다.
"""
import json
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.cards import fact_edit_repo as repo
from app.cards.router import build_facts_view, fact_row_view, requirement_labels
from app.ingest.card_plan import PlanFact

STORE = 7

# 비동기 테스트만 asyncio 표시가 필요하다(동기 테스트는 경고 없이 지나간다)
_async = pytest.mark.asyncio


def _fact(rid, fid=None, entity=9, **over) -> PlanFact:
    base = dict(
        fact_revision_id=rid, fact_id=fid if fid is not None else rid + 1000, entity_id=entity,
        subject="음료Z", predicate="물", variant_temperature="ICE", variant_size=None,
        quantity_value=Decimal("225.0"), quantity_unit="ml", value_text=None,
        polarity="AFFIRM", step_order=None, conditions=(), exceptions=(),
        original_assertion="합성 문장", assertion="합성 문장", requires_fact_ids=())
    base.update(over)
    return PlanFact(**base)


class FakeConn:
    """(SQL 조각, 답) 목록을 앞에서부터 맞춰 본다. 답이 함수면 인자로 부른다."""

    def __init__(self, answers):
        self.answers = answers
        self.calls: list[tuple[str, str, tuple]] = []

    def _answer(self, sql, args):
        for fragment, answer in self.answers:
            if fragment in sql:
                return answer(*args) if callable(answer) else answer
        return None

    async def fetch(self, sql, *args):
        self.calls.append(("fetch", sql, args))
        got = self._answer(sql, args)
        return got if isinstance(got, list) else []

    async def fetchrow(self, sql, *args):
        self.calls.append(("fetchrow", sql, args))
        return self._answer(sql, args)

    async def fetchval(self, sql, *args):
        self.calls.append(("fetchval", sql, args))
        return self._answer(sql, args)


def _assert_isolated(conn):
    assert conn.calls
    for _, sql, args in conn.calls:
        assert "store_id = $1" in sql, sql
        assert args[0] == STORE


# ── classify_head ────────────────────────────────────────────────────────────

def _head_conn(heads, chain):
    """heads: {fact_id: (head_rid, head_entity)}, chain: {rid: (supersedes, change_kind)}."""
    def heads_answer(store, fact_ids):
        return [dict(fact_id=f, head_revision_id=heads[f][0], head_entity_id=heads[f][1])
                for f in fact_ids if f in heads]

    def step_answer(store, rid):
        if rid not in chain:
            return None
        sup, kind = chain[rid]
        return dict(fact_revision_id=rid, supersedes_revision_id=sup, change_kind=kind)

    return FakeConn([("from knowledge_facts k", heads_answer),
                     ("from fact_revisions r", step_answer)])


@_async
async def test_classify_head_same_as_pinned():
    conn = _head_conn({1: (10, 9)}, {})
    got = await repo.classify_head(conn, STORE, {1: 10}, 9)
    assert got[1] == repo.HeadInfo(1, 10, 10, 9, 10, None)
    _assert_isolated(conn)


@_async
async def test_classify_head_relink_chain_is_editable_from_head():
    conn = _head_conn({1: (11, 9)}, {11: (10, "RELINK")})
    got = await repo.classify_head(conn, STORE, {1: 10}, 9)
    assert got[1].editable_base == 11 and got[1].edit_block is None
    assert got[1].head_revision_id == 11 and got[1].pinned_revision_id == 10
    _assert_isolated(conn)


@_async
async def test_classify_head_other_change_in_middle_blocks():
    chain = {12: (11, "RELINK"), 11: (10, "OWNER_CORRECTION")}
    conn = _head_conn({1: (12, 9)}, chain)
    got = await repo.classify_head(conn, STORE, {1: 10}, 9)
    assert got[1].editable_base is None and got[1].edit_block == "CHANGED_ELSEWHERE"


@_async
async def test_classify_head_other_entity_is_moved_and_wins():
    chain = {11: (10, "OWNER_CORRECTION")}
    conn = _head_conn({1: (11, 99)}, chain)
    got = await repo.classify_head(conn, STORE, {1: 10}, 9)
    assert got[1].edit_block == "MOVED_ENTITY" and got[1].editable_base is None
    assert got[1].head_entity_id == 99


@_async
async def test_classify_head_chain_limit_50():
    # 50단은 허용, 51단은 막는다
    def chain_of(n):
        chain = {}
        for i in range(n):
            rid = 100 + i
            chain[rid] = (rid - 1 if i else 10, "RELINK")
        return chain, 100 + n - 1

    chain, head = chain_of(50)
    got = await repo.classify_head(_head_conn({1: (head, 9)}, chain), STORE, {1: 10}, 9)
    assert got[1].edit_block is None and got[1].editable_base == head
    chain, head = chain_of(51)
    got = await repo.classify_head(_head_conn({1: (head, 9)}, chain), STORE, {1: 10}, 9)
    assert got[1].edit_block == "CHANGED_ELSEWHERE" and got[1].editable_base is None


@_async
async def test_classify_head_chain_never_reaches_pinned():
    conn = _head_conn({1: (11, 9)}, {11: (5, "RELINK"), 5: (None, "RELINK")})
    got = await repo.classify_head(conn, STORE, {1: 10}, 9)
    assert got[1].edit_block == "CHANGED_ELSEWHERE"


# ── load_card_fact_state ─────────────────────────────────────────────────────

def _plan_rows(rows):
    return [dict(fact_revision_id=f.fact_revision_id, fact_id=f.fact_id, entity_id=f.entity_id,
                 subject=f.subject, predicate=f.predicate,
                 variant_temperature=f.variant_temperature, variant_size=f.variant_size,
                 quantity_value=f.quantity_value, quantity_unit=f.quantity_unit,
                 value_text=f.value_text, polarity=f.polarity, step_order=f.step_order,
                 conditions=json.dumps(list(f.conditions)),
                 exceptions=json.dumps(list(f.exceptions)),
                 original_assertion=f.original_assertion, assertion=f.assertion)
            for f in rows]


def _state_conn(facts, block_facts, *, blocks=None, merged=None, card=True):
    blocks = blocks if blocks is not None else [
        dict(block_id="b1", kind="QUANTITIES", block_order=1),
        dict(block_id="b2", kind="STEPS", block_order=2)]
    entities = sorted({f.entity_id for f in facts})
    return FakeConn([
        ("from knowledge_cards k", dict(card_id=3, review_status="APPROVED",
                                        published_version_id=50, title="합성 카드") if card else None),
        ("from card_version_blocks", blocks),
        ("from card_block_facts", block_facts),
        ("from fact_revision_requires", []),
        ("from fact_revisions r", _plan_rows(facts)),
        ("from knowledge_entities", [dict(entity_id=e, canonical_name="음료Z",
                                          merged_into_entity_id=(merged or {}).get(e))
                                     for e in entities]),
        ("from knowledge_entity_aliases", [dict(alias_norm="zdrink")]),
    ])


@_async
async def test_state_without_block_facts_is_none():
    conn = _state_conn([], [])
    assert await repo.load_card_fact_state(conn, STORE, 3, 60) is None
    _assert_isolated(conn)


@_async
async def test_state_missing_card_is_none():
    conn = _state_conn([_fact(1)], [], card=False)
    assert await repo.load_card_fact_state(conn, STORE, 3, 60) is None


@_async
async def test_state_order_is_block_then_position():
    f1, f2, f3 = _fact(1), _fact(2), _fact(3)
    # DB 가 되돌린 순서가 섞여도 블록 순 → position 순으로 정렬한다
    bf = [dict(block_id="b2", fact_revision_id=3, position=1),
          dict(block_id="b1", fact_revision_id=2, position=2),
          dict(block_id="b1", fact_revision_id=1, position=1)]
    conn = _state_conn([f1, f2, f3], bf)
    state = await repo.load_card_fact_state(conn, STORE, 3, 60)
    assert [p.fact.fact_revision_id for p in state.pinned] == [1, 2, 3]
    assert [(p.block_id, p.kind, p.position) for p in state.pinned] == [
        ("b1", "QUANTITIES", 1), ("b1", "QUANTITIES", 2), ("b2", "STEPS", 1)]
    assert state.blocks == (("b1", "QUANTITIES", 1), ("b2", "STEPS", 2))
    assert state.entity_id == 9 and state.entity_problem is None
    assert state.entity_name == "음료Z" and state.title == "합성 카드"
    assert state.review_status == "APPROVED" and state.published_version_id == 50
    assert state.version_id == 60 and state.card_id == 3 and state.store_id == STORE
    assert "zdrink" in state.alias_norms
    _assert_isolated(conn)


@_async
async def test_state_keeps_raw_block_without_facts():
    blocks = [dict(block_id="b1", kind="QUANTITIES", block_order=1),
              dict(block_id="raw1", kind="RAW", block_order=2)]
    conn = _state_conn([_fact(1)], [dict(block_id="b1", fact_revision_id=1, position=1)],
                       blocks=blocks)
    state = await repo.load_card_fact_state(conn, STORE, 3, 60)
    assert state.blocks == (("b1", "QUANTITIES", 1), ("raw1", "RAW", 2))
    assert len(state.pinned) == 1


@_async
async def test_state_two_entities_is_mixed():
    f1, f2 = _fact(1, entity=9), _fact(2, entity=10)
    bf = [dict(block_id="b1", fact_revision_id=1, position=1),
          dict(block_id="b1", fact_revision_id=2, position=2)]
    state = await repo.load_card_fact_state(_state_conn([f1, f2], bf), STORE, 3, 60)
    assert state.entity_problem == "MIXED_ENTITY" and state.entity_id is None


@_async
async def test_state_merged_entity():
    bf = [dict(block_id="b1", fact_revision_id=1, position=1)]
    conn = _state_conn([_fact(1)], bf, merged={9: 12})
    state = await repo.load_card_fact_state(conn, STORE, 3, 60)
    assert state.entity_problem == "MERGED_ENTITY" and state.entity_id == 9


# ── load_plan_facts ──────────────────────────────────────────────────────────

@_async
async def test_plan_facts_requires_skip_own_fact():
    f = _fact(1, fid=100)
    conn = FakeConn([
        ("from fact_revision_requires", [dict(fact_revision_id=1, fact_id=100),
                                         dict(fact_revision_id=1, fact_id=200),
                                         dict(fact_revision_id=1, fact_id=150)]),
        ("from fact_revisions r", _plan_rows([f])),
    ])
    got = await repo.load_plan_facts(conn, STORE, [1])
    assert got[1].requires_fact_ids == (150, 200)
    _assert_isolated(conn)


@_async
async def test_plan_facts_empty_makes_no_query():
    conn = FakeConn([])
    assert await repo.load_plan_facts(conn, STORE, []) == {}
    assert conn.calls == []


# ── load_fact_rows 의 근거 종류 ──────────────────────────────────────────────

@_async
async def test_fact_rows_origin_kinds_and_order():
    state = _stub_state()
    t = datetime(2026, 10, 1, tzinfo=timezone.utc)
    conn = FakeConn([
        ("from card_version_fact_provenance", [
            dict(fact_revision_id=1, occurrence_id=None, owner_answer_id=8, created_at=t,
                 source_id=None, locator_type=None, locator=None, source_type=None,
                 source_title=None, source_availability=None),
            dict(fact_revision_id=1, occurrence_id=5, owner_answer_id=None, created_at=t,
                 source_id=2, locator_type="LINE", locator='{"line": 3}', source_type="OWNER_TEXT",
                 source_title="카드 직접 입력 · 합성", source_availability="AVAILABLE"),
            dict(fact_revision_id=1, occurrence_id=4, owner_answer_id=None, created_at=t,
                 source_id=1, locator_type="PAGE", locator={"page": 2}, source_type="SCAN",
                 source_title="합성 자료", source_availability="DELETED"),
        ]),
        ("from fact_revisions r", [dict(fact_revision_id=1, change_kind="OWNER_ADD",
                                        previous_sentence="이전 문장")]),
    ])
    rows = await repo.load_fact_rows(conn, STORE, state)
    one = rows[1]
    assert one["change_kind"] == "OWNER_ADD" and one["previous_sentence"] == "이전 문장"
    # 파일 근거 occurrence_id 순 → 점주 답변
    assert [(o["kind"], o["source_id"], o["owner_answer_id"]) for o in one["origins"]] == [
        ("SOURCE", 1, None), ("OWNER_TEXT", 2, None), ("OWNER_ANSWER", None, 8)]
    assert one["origins"][0]["source_availability"] == "DELETED"
    assert one["origins"][0]["locator"] == {"page": 2}
    assert one["origins"][1]["locator"] == {"line": 3}
    assert one["origins"][1]["source_type"] == "OWNER_TEXT"
    _assert_isolated(conn)


def _stub_state(pinned=None, **over):
    from app.cards.fact_edit_plan import CardFactState, PinnedFact
    pinned = pinned if pinned is not None else (PinnedFact(_fact(1), "b1", "QUANTITIES", 1),)
    base = dict(store_id=STORE, card_id=3, version_id=60, title="합성 카드",
                review_status="APPROVED", published_version_id=None, entity_id=9,
                entity_name="음료Z", alias_norms=frozenset(), entity_problem=None,
                blocks=(("b1", "QUANTITIES", 1),), pinned=pinned)
    base.update(over)
    return CardFactState(**base)


# ── 화면 변환(순수) ──────────────────────────────────────────────────────────

def test_row_numeric_value_strips_zeros_and_keeps_unit():
    row = fact_row_view(_fact(1, quantity_value=Decimal("20.0")), 1, {}, {}, None)
    assert row.value == "20" and row.unit == "ml"
    assert row.variant.temperature == "ICE" and row.position == 1


def test_row_text_value_has_no_unit():
    f = _fact(1, quantity_value=None, quantity_unit="ml", value_text="줄임")
    row = fact_row_view(f, 2, {}, {}, None)
    assert row.value == "줄임" and row.unit is None


def test_row_negate_conditions_exceptions_kept():
    f = _fact(1, polarity="NEGATE", conditions=("바쁠 때",), exceptions=("디카페인",),
              quantity_value=None, quantity_unit=None)
    row = fact_row_view(f, 1, {}, {}, "CHANGED_ELSEWHERE")
    assert row.polarity == "NEGATE" and row.conditions == ["바쁠 때"]
    assert row.exceptions == ["디카페인"] and row.edit_block == "CHANGED_ELSEWHERE"
    assert row.value is None and row.unit is None


def test_requirement_labels_rules():
    step = _fact(1, fid=11, step_order=2)
    note = _fact(2, fid=12, original_assertion="가" * 50, assertion="가" * 50)
    by_fact = {11: step, 12: note}
    assert [(r.fact_id, r.label) for r in requirement_labels((11, 12, 99), by_fact)] == [
        (11, "2번"), (12, "가" * 40), (99, "(다른 카드)")]


def test_row_extra_fields_and_origins_converted():
    extra = {"change_kind": "RELINK", "previous_sentence": "옛",
             "origins": [dict(kind="OWNER_ANSWER", owner_answer_id=4, source_id=None,
                              source_title=None, source_type=None, source_availability=None,
                              locator_type=None, locator={}, created_at=None)]}
    row = fact_row_view(_fact(1), 1, extra, {}, None)
    assert row.change_kind == "RELINK" and row.previous_sentence == "옛"
    assert row.origins[0].kind == "OWNER_ANSWER" and row.origins[0].owner_answer_id == 4


def test_view_blocks_variant_and_editable():
    from app.cards.fact_edit_plan import PinnedFact
    f1 = _fact(1, fid=11)
    f2 = _fact(2, fid=12, variant_temperature="HOT")
    pinned = (PinnedFact(f1, "b1", "QUANTITIES", 1), PinnedFact(f2, "b1", "QUANTITIES", 2))
    state = _stub_state(pinned=pinned,
                        blocks=(("b1", "QUANTITIES", 1), ("raw1", "RAW", 2)))
    view = build_facts_view(state, {}, {})
    assert [b.kind for b in view.blocks] == ["QUANTITIES", "RAW"]
    assert view.blocks[0].variant.temperature == "ICE"  # 첫 사실의 규격
    assert view.blocks[1].facts == [] and view.blocks[1].variant.temperature is None
    assert view.editable is True and view.version_id == 60 and view.entity_name == "음료Z"
    excluded = _stub_state(pinned=pinned, review_status="EXCLUDED",
                           blocks=(("b1", "QUANTITIES", 1),))
    assert build_facts_view(excluded, {}, {}).editable is False
    mixed = _stub_state(pinned=pinned, entity_problem="MIXED_ENTITY", entity_id=None,
                        blocks=(("b1", "QUANTITIES", 1),))
    v = build_facts_view(mixed, {}, {})
    assert v.editable is False and v.entity_problem == "MIXED_ENTITY"


def test_view_applies_head_edit_block_per_fact():
    from app.cards.fact_edit_plan import PinnedFact
    f1 = _fact(1, fid=11)
    state = _stub_state(pinned=(PinnedFact(f1, "b1", "QUANTITIES", 1),))
    heads = {11: repo.HeadInfo(11, 1, 5, 9, None, "CHANGED_ELSEWHERE")}
    view = build_facts_view(state, {}, heads)
    assert view.blocks[0].facts[0].edit_block == "CHANGED_ELSEWHERE"
    assert view.editable is True  # 줄 단위 막힘은 editable 을 끄지 않는다
