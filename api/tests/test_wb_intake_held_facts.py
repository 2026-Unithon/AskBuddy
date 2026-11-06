# api/tests/test_wb_intake_held_facts.py
"""Phase B — NOTICE 보류 사실은 조립·재초안에 들어가지 않는다(Review Focus 3)."""
from unittest.mock import AsyncMock, patch

import pytest

from app.ingest import card_plan, fact_assembly, fact_cards, pipeline
from app.ingest.card_plan import EntityGroup
from app.ingest.fact_assembly import AssemblyInput, HeldFact
from app.ingest.fact_cards import WrittenEntity
from app.ingest.pipeline import PreparedAssembly
from tests.test_w3a_pipeline_wiring import _fact, _Patches, _persist, _planning, _Pool, _state

NOTICE = "INTAKE_NOTICE"


@pytest.mark.asyncio
async def test_prepare_removes_held_facts_and_adds_heldfact():
    group = EntityGroup(entity_id=1, canonical_name="합성대상1", facts=(_fact(1, 10), _fact(1, 11)))
    seen = {}

    async def plan(**kw):
        seen["revs"] = [f.fact_revision_id for g in kw["groups"] for f in g.facts]
        return _planning()

    with patch.object(fact_assembly, "entities_for_source", AsyncMock(return_value=[1])), \
         patch.object(fact_cards, "entity_card_state", AsyncMock(return_value=_state(1, "NEW"))), \
         patch.object(fact_assembly, "load_entity_groups",
                      AsyncMock(return_value=AssemblyInput(groups=(group,), held=()))), \
         patch.object(card_plan, "check_group", lambda g: None), \
         patch.object(fact_assembly, "plan_entities", plan):
        prepared = await pipeline._prepare_fact_assembly(
            _Pool(), 1, 7, categories=["기타"], glossary=[], usage_sink=None, usage_base=None,
            raw_sink=None, strict=True, held_fact_ids={110: NOTICE})
    assert seen["revs"] == [10]  # _fact(1, 11) 의 fact_id 는 110
    assert HeldFact(11, 110, 1, NOTICE) in prepared.held
    assert prepared.held_fact_ids == frozenset({110})


@pytest.mark.asyncio
async def test_prepare_drops_entity_whose_facts_are_all_held():
    group = EntityGroup(entity_id=1, canonical_name="합성대상1", facts=(_fact(1, 11),))
    with patch.object(fact_assembly, "entities_for_source", AsyncMock(return_value=[1])), \
         patch.object(fact_cards, "entity_card_state", AsyncMock(return_value=_state(1, "NEW"))), \
         patch.object(fact_assembly, "load_entity_groups",
                      AsyncMock(return_value=AssemblyInput(groups=(group,), held=()))), \
         patch.object(card_plan, "check_group", lambda g: None), \
         patch.object(fact_assembly, "plan_entities", AsyncMock(return_value=_planning())) as plan:
        prepared = await pipeline._prepare_fact_assembly(
            _Pool(), 1, 7, categories=["기타"], glossary=[], usage_sink=None, usage_base=None,
            raw_sink=None, strict=True, held_fact_ids={110: NOTICE})
    assert prepared.groups == {} and plan.await_args.kwargs["groups"] == []


@pytest.mark.asyncio
async def test_entity_with_only_held_facts_writes_nothing_even_if_redraft():
    # _Patches 의 entity_fact_ids 는 [entity_id * 1000] → 대상 8 의 사실은 8000 하나
    prepared = PreparedAssembly(
        entity_ids=(8,), states={8: _state(8, "REDRAFT")}, groups={},
        held=(HeldFact(801, 8000, 8, NOTICE),), data_errors={}, planning=_planning(),
        held_fact_ids=frozenset({8000}))
    with _Patches(now={8: _state(8, "REDRAFT")}) as p, \
         patch.object(fact_cards, "redraft_published_card", AsyncMock()) as redraft:
        await _persist(prepared)
    redraft.assert_not_awaited()
    p.write.assert_not_awaited()
    assert ("mark", (8000,), NOTICE) in p.calls


@pytest.mark.asyncio
async def test_redraft_excludes_held_fact_ids():
    prepared = PreparedAssembly(
        entity_ids=(8,), states={8: _state(8, "REDRAFT")}, groups={}, held=(),
        data_errors={}, planning=_planning(), held_fact_ids=frozenset({8001}))
    written = WrittenEntity(entity_id=8, card_ids=(1,), new_version_ids=(12,), linked_fact_ids=())
    with _Patches(now={8: _state(8, "REDRAFT")}), \
         patch.object(fact_cards, "entity_fact_ids", AsyncMock(return_value=[8000, 8001])), \
         patch.object(fact_cards, "redraft_published_card",
                      AsyncMock(return_value=written)) as redraft:
        created = await _persist(prepared)
    assert redraft.await_args.kwargs["exclude_fact_ids"] == frozenset({8001})
    assert created == 1


@pytest.mark.asyncio
async def test_partial_held_entity_not_stale():
    full = EntityGroup(entity_id=8, canonical_name="합성대상8", facts=(_fact(8, 80), _fact(8, 81)))
    kept = EntityGroup(entity_id=8, canonical_name="합성대상8", facts=(_fact(8, 80),))
    prepared = PreparedAssembly(
        entity_ids=(8,), states={8: _state(8, "NEW")}, groups={8: kept}, held=(),
        data_errors={}, planning=_planning(), held_fact_ids=frozenset({810}))
    with _Patches(now={8: _state(8, "NEW")}, reload={8: full}) as p, \
         patch.object(fact_cards, "entity_fact_ids", AsyncMock(return_value=[800, 810])):
        await _persist(prepared)
    p.write.assert_awaited_once()
    assert p.write.await_args.kwargs["group"] is kept
    assert not any(isinstance(c, tuple) and c[0] == "mark" and c[2] == fact_cards.REASON_STALE_INPUT
                   for c in p.calls)


# ── 매장 전체 기준 공지 보류 (최종 리뷰 I1) ───────────────────────────────

def _row(fid, *, notice=True, other=False, owner=False, current=False):
    return {"fact_id": fid, "notice_pending": notice, "other_occurrence": other,
            "owner_support": owner, "in_current": current}


def test_store_notice_hold_needs_notice_pending_and_no_other_support():
    rows = [_row(1), _row(2, notice=False), _row(3, other=True), _row(4, owner=True),
            _row(5, current=True), _row(6, current=True)]
    # 6 은 이 자료에서도 공지 범위에만 나온다 → 여전히 보류. 5 는 이 자료의 공지 밖 받침
    assert pipeline.store_notice_holds_of(rows, frozenset({6})) == frozenset({1, 6})


@pytest.mark.asyncio
async def test_store_notice_holds_query_is_store_scoped_and_skips_empty():
    from unittest.mock import MagicMock
    conn = MagicMock()
    conn.fetch = AsyncMock(return_value=[_row(9)])
    assert await pipeline._store_notice_holds(conn, 3, 5, [], frozenset()) == frozenset()
    conn.fetch.assert_not_awaited()
    got = await pipeline._store_notice_holds(conn, 3, 5, [9, 9], frozenset())
    sql, *args = conn.fetch.await_args.args
    assert "k.store_id = $1" in sql and "o.source_id <> $2" in sql and "'INTAKE_NOTICE'" in sql
    assert args == [3, 5, [9]] and got == frozenset({9})


@pytest.mark.asyncio
async def test_prepare_holds_store_wide_notice_fact_in_another_sources_run():
    """공지 자료 실행이 끝난 뒤 레시피 자료(공지 범위 없음)의 조립에서도 공지 사실을 뺀다."""
    group = EntityGroup(entity_id=1, canonical_name="합성대상1", facts=(_fact(1, 10), _fact(1, 11)))
    seen = {}

    async def plan(**kw):
        seen["revs"] = [f.fact_revision_id for g in kw["groups"] for f in g.facts]
        return _planning()

    with patch.object(fact_assembly, "entities_for_source", AsyncMock(return_value=[1])), \
         patch.object(fact_cards, "entity_card_state", AsyncMock(return_value=_state(1, "NEW"))), \
         patch.object(fact_assembly, "load_entity_groups",
                      AsyncMock(return_value=AssemblyInput(groups=(group,), held=()))), \
         patch.object(pipeline, "_store_notice_holds",
                      AsyncMock(return_value=frozenset({110}))) as store_holds, \
         patch.object(card_plan, "check_group", lambda g: None), \
         patch.object(fact_assembly, "plan_entities", plan):
        prepared = await pipeline._prepare_fact_assembly(
            _Pool(), 1, 7, categories=["기타"], glossary=[], usage_sink=None, usage_base=None,
            raw_sink=None, strict=True)
    assert store_holds.await_args.args[1:4] == (1, 7, [100, 110])
    assert seen["revs"] == [10]
    assert HeldFact(11, 110, 1, NOTICE) in prepared.held
    assert prepared.held_fact_ids == frozenset({110})
    # 저장 단계: 다시 읽은 묶음에 공지 사실이 있어도 같은 집합으로 걸러 STALE_INPUT 이 아니다
    full = EntityGroup(entity_id=1, canonical_name="합성대상1", facts=(_fact(1, 10), _fact(1, 11)))
    with _Patches(now={1: _state(1, "NEW")}, reload={1: full}) as p, \
         patch.object(fact_cards, "entity_fact_ids", AsyncMock(return_value=[100, 110])):
        await _persist(prepared)
    p.write.assert_awaited_once()
    assert [f.fact_id for f in p.write.await_args.kwargs["group"].facts] == [100]
    assert not any(isinstance(c, tuple) and c[0] == "mark" and c[2] == fact_cards.REASON_STALE_INPUT
                   for c in p.calls)
