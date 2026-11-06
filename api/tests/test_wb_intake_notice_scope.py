"""Phase B — 공지(NOTICE) 보류는 occurrence 단위다(Task 9 fix round 1 controller 판정).

- 이 자료에서 공지 범위에만 나온 사실: 이 자료의 그 occurrence 는 어느 경로로도 LINKED 가 되지 않고
  INTAKE_NOTICE 검수 대기로 남는다(공개판에 고정된 사실 포함).
- 그중 다른 받침(다른 자료 원장 행)이 없는 사실만 조립 묶음에서 뺀다.
- 같은 자료에서 RECIPE 구간에도 나온 사실은 보통 사실이다.
모델·DB 는 부르지 않는다.
"""
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.cards import fact_edit_repo
from app.ingest import card_plan, fact_assembly, fact_cards, pipeline
from app.ingest.card_plan import EntityGroup, EntityPlanResult, ValidatedBlock, ValidatedCard
from app.ingest.fact_assembly import AssemblyInput
from app.ingest.fact_cards import EntityCardState, WrittenEntity
from app.ingest.pipeline import PreparedAssembly
from tests.test_w3a_pipeline_wiring import _fact, _Patches, _persist, _planning, _Pool, _state

NOTICE = fact_cards.REASON_INTAKE_NOTICE


def _occ(fid, seg, other=False):
    return {"fact_id": fid, "segment_id": seg, "other_support": other}


# ── 보류 대상 가르기 ─────────────────────────────────────────────────────

def test_same_source_fact_in_recipe_and_notice_is_normal():
    # 사실 1 은 seg1(RECIPE)·seg2(NOTICE) 둘 다에 나온다 → 보통 사실(이어진다)
    rows = [_occ(1, "seg1"), _occ(1, "seg2"), _occ(2, "seg2"), _occ(3, "seg1")]
    notice_only, unsupported = pipeline.notice_holds_of(rows, ["seg2"])
    assert notice_only == {2} and unsupported == {2}


def test_notice_only_fact_with_other_source_support_is_not_removed_from_assembly():
    rows = [_occ(2, "seg2", other=True), _occ(4, "seg2")]
    notice_only, unsupported = pipeline.notice_holds_of(rows, ["seg2"])
    assert notice_only == {2, 4} and unsupported == {4}


def test_hold_all_notice_takes_every_occurrence():
    rows = [_occ(7, None), _occ(8, "seg1", other=True)]
    assert pipeline.notice_holds_of(rows, None) == ({7, 8}, {7})


@pytest.mark.asyncio
async def test_notice_holds_reads_occurrences_not_ledger_first_segment():
    conn = MagicMock()
    conn.fetch = AsyncMock(return_value=[_occ(1, "seg1"), _occ(1, "seg2")])
    got = await pipeline._notice_holds(conn, 3, 5, ["seg2"])
    sql, *args = conn.fetch.await_args.args
    assert "from source_fact_occurrences o" in sql and "o.store_id = $1" in sql
    assert args == [3, 5]
    assert got == (frozenset(), frozenset())


# ── 조립 준비: 받침 있는 공지 사실은 묶음에 남는다 ─────────────────────────

@pytest.mark.asyncio
async def test_prepare_keeps_supported_notice_fact_in_group():
    group = EntityGroup(entity_id=1, canonical_name="합성대상1", facts=(_fact(1, 10), _fact(1, 11)))
    with patch.object(fact_assembly, "entities_for_source", AsyncMock(return_value=[1])), \
         patch.object(fact_cards, "entity_card_state", AsyncMock(return_value=_state(1, "NEW"))), \
         patch.object(fact_assembly, "load_entity_groups",
                      AsyncMock(return_value=AssemblyInput(groups=(group,), held=()))), \
         patch.object(card_plan, "check_group", lambda g: None), \
         patch.object(fact_assembly, "plan_entities", AsyncMock(return_value=_planning())):
        prepared = await pipeline._prepare_fact_assembly(
            _Pool(), 1, 7, categories=["기타"], glossary=[], usage_sink=None, usage_base=None,
            raw_sink=None, strict=True, held_fact_ids={}, notice_fact_ids=frozenset({110}))
    assert prepared.groups[1] is group  # 사실 110(_fact(1, 11)) 이 묶음에 남는다
    assert prepared.held == () and prepared.held_fact_ids == frozenset()
    assert prepared.notice_fact_ids == frozenset({110})


@pytest.mark.asyncio
async def test_new_entity_with_supported_notice_fact_writes_card_and_marks_occurrence():
    group = EntityGroup(entity_id=8, canonical_name="합성대상8", facts=(_fact(8, 80), _fact(8, 81)))
    prepared = PreparedAssembly(
        entity_ids=(8,), states={8: _state(8, "NEW")}, groups={8: group}, held=(),
        data_errors={}, planning=_planning(), notice_fact_ids=frozenset({810}))
    with _Patches(now={8: _state(8, "NEW")}, reload={8: group}) as p, \
         patch.object(fact_cards, "entity_fact_ids", AsyncMock(return_value=[800, 810])):
        await _persist(prepared)
    p.write.assert_awaited_once()
    kw = p.write.await_args.kwargs
    assert kw["group"] is group and kw["notice_fact_ids"] == frozenset({810})
    # 대상 사유 뒤에 이 자료 occurrence 를 공지 보류로 둔다
    assert ("mark", (810,), NOTICE) in p.calls
    assert p.calls.index(("write", 8)) < p.calls.index(("mark", (810,), NOTICE))


@pytest.mark.asyncio
async def test_write_entity_cards_does_not_link_this_sources_notice_occurrence():
    facts = (_fact(8, 80), _fact(8, 81))  # 사실 800·810
    group = EntityGroup(entity_id=8, canonical_name="합성대상8", facts=facts)
    block = ValidatedBlock("b1", "NOTES", 1, (80, 81), (None, None))
    card = ValidatedCard(8, "음료Z", "기타", (None, None), (block,))
    result = EntityPlanResult(8, (card,), None, None)
    state = EntityCardState(8, "NEW", (), None)
    rendered = NS(content="본문", confidence=0.9, reason=None)
    conn = MagicMock()
    conn.fetchval = AsyncMock(return_value=33)
    conn.execute = AsyncMock()
    link = AsyncMock(return_value={800, 810})
    set_state = AsyncMock()
    with patch.object(fact_cards, "_card_state", AsyncMock(return_value=state)), \
         patch.object(fact_cards, "_render_context", AsyncMock(return_value=NS())), \
         patch.object(fact_cards, "_render_one", lambda *a, **k: rendered), \
         patch.object(fact_cards, "_fix_version", AsyncMock()), \
         patch.object(fact_cards.repo, "insert_card", AsyncMock(return_value=5)), \
         patch.object(fact_cards.repo, "set_assembly_state", set_state), \
         patch.object(fact_cards, "_link_placed", link), \
         patch.object(fact_cards, "_source_fact_ids", AsyncMock(return_value=[1, 2, 3])), \
         patch.object(fact_cards, "_source_fact_ids_of_source",
                      AsyncMock(return_value=[2])) as own:
        written = await fact_cards.write_entity_cards(
            conn, 1, source_id=7, job_id=9, category_version=1, categories={"기타": 1},
            state=state, group=group, result=result, notice_fact_ids=frozenset({810}))
    kw = link.await_args.kwargs
    assert kw["hold_source_id"] == 7 and kw["hold_fact_ids"] == [810]
    own.assert_awaited_once_with(conn, 1, 7, [810])
    assert set_state.await_args.args[2] == [1, 3]  # 이 자료의 공지 원장 행(2)은 LINKED 로 두지 않는다
    assert written.card_ids == (5,)


@pytest.mark.asyncio
async def test_link_placed_sql_skips_held_source_occurrences():
    conn = MagicMock()
    conn.fetch = AsyncMock(return_value=[])
    await fact_cards._link_placed(conn, 1, {810: (5, "b1"), 800: (5, "b1")},
                                  hold_source_id=7, hold_fact_ids=[810])
    sql, *args = conn.fetch.await_args.args
    assert "not ($6::bigint is not null and o.source_id = $6" in sql
    assert args[0] == 1 and args[5:] == [7, [810]]
    # 보류가 없으면 조건이 아무것도 거르지 않는다($6 null)
    await fact_cards._link_placed(conn, 1, {800: (5, "b1")})
    assert conn.fetch.await_args.args[6:] == (None, [])


# ── REDRAFT: 공개판에 고정된 사실을 이 자료가 공지에서만 말했다 ────────────────

def _redraft_patches(notice):
    pinned = NS(fact=_fact(8, 80), block_id="b1")  # 공개판 고정 사실 800
    base = NS(pinned=[pinned], blocks=[("b1", "NOTES", None)], entity_problem=None,
              entity_name="합성대상8")
    state = EntityCardState(8, "REDRAFT", (5,), None)
    conn = MagicMock()
    conn.fetchrow = AsyncMock(return_value={"published_version_id": 50, "draft_version_id": 50,
                                            "category_name": "기타"})
    link = AsyncMock(return_value=set())
    patches = [
        patch.object(fact_cards, "entity_fact_ids", AsyncMock(return_value=[800])),
        patch.object(fact_cards, "_card_state", AsyncMock(return_value=state)),
        patch.object(fact_edit_repo, "load_card_fact_state", AsyncMock(return_value=base)),
        patch.object(fact_cards, "new_fact_ids_for_source", AsyncMock(return_value=[])),
        patch.object(fact_cards, "_link_placed", link),
        patch.object(fact_cards, "_source_fact_ids_of_source", AsyncMock(return_value=[])),
        patch.object(fact_cards.repo, "set_assembly_state", AsyncMock()),
    ]
    return conn, state, link, patches


@pytest.mark.asyncio
@pytest.mark.parametrize("notice, placed", [(frozenset(), {800: (5, "b1")}),
                                            (frozenset({800}), {})])
async def test_redraft_does_not_link_pinned_fact_stated_only_in_notice(notice, placed):
    conn, state, link, patches = _redraft_patches(notice)
    for p in patches:
        p.start()
    try:
        written = await fact_cards.redraft_published_card(
            conn, 1, source_id=7, state=state, notice_fact_ids=notice)
    finally:
        for p in reversed(patches):
            p.stop()
    assert link.await_args.args[2] == placed
    assert written.new_version_ids == ()


@pytest.mark.asyncio
async def test_persist_redraft_marks_pinned_notice_fact_intake_notice():
    # 대상 8: 사실 800(공개판 고정, 이 자료는 공지에서만 말함) + 다른 자료 사실 801 → 대상은 건너뛰지 않는다
    prepared = PreparedAssembly(
        entity_ids=(8,), states={8: _state(8, "REDRAFT")}, groups={}, held=(),
        data_errors={}, planning=_planning(), notice_fact_ids=frozenset({800}))
    written = WrittenEntity(entity_id=8, card_ids=(5,), new_version_ids=(), linked_fact_ids=())
    with _Patches(now={8: _state(8, "REDRAFT")}) as p, \
         patch.object(fact_cards, "entity_fact_ids", AsyncMock(return_value=[800, 801])), \
         patch.object(fact_cards, "redraft_published_card",
                      AsyncMock(return_value=written)) as redraft:
        await _persist(prepared)
    kw = redraft.await_args.kwargs
    assert kw["notice_fact_ids"] == frozenset({800}) and kw["exclude_fact_ids"] == frozenset()
    assert ("mark", (800,), NOTICE) in p.calls
