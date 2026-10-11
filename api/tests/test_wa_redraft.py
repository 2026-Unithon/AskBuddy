"""Phase A Task 4 — 공개 카드에 새 사실을 결정적으로 붙인다."""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.ingest import fact_cards
from app.ingest.card_plan import EntityGroup, PlanFact, PlanInvalid, append_facts


def _fact(rid, fid, *, predicate="물", qty=None, step=None, temp=None, polarity="AFFIRM"):
    return PlanFact(fact_revision_id=rid, fact_id=fid, entity_id=4, subject="음료Z",
                    predicate=predicate, variant_temperature=temp, variant_size=None,
                    quantity_value=Decimal(qty) if qty else None,
                    quantity_unit="ml" if qty else None,
                    value_text=None if qty else "가득", polarity=polarity, step_order=step,
                    conditions=(), exceptions=(), original_assertion=f"음료Z {predicate}",
                    assertion=f"음료Z {predicate}")


def test_append_facts_keeps_published_layout():
    a, b, c = _fact(10, 1, qty="225"), _fact(11, 2, predicate="얼음", step=1), _fact(12, 3, qty="30", predicate="시럽")
    group = EntityGroup(entity_id=4, canonical_name="음료Z", facts=(a, b, c))
    card = append_facts([("QUANTITIES", (10,)), ("STEPS", (11,))], group, [12], category_name="기타")
    assert [(blk.kind, blk.fact_revision_ids) for blk in card.blocks] == [
        ("QUANTITIES", (10, 12)), ("STEPS", (11,))]


def test_append_step_resorts_by_order():
    s2, s1 = _fact(20, 1, predicate="젓기", step=2), _fact(21, 2, predicate="붓기", step=1)
    group = EntityGroup(entity_id=4, canonical_name="음료Z", facts=(s1, s2))
    card = append_facts([("STEPS", (20,))], group, [21], category_name="기타")
    assert [blk.fact_revision_ids for blk in card.blocks] == [(21, 20)]


def test_append_new_kind_goes_to_new_block():
    q, note = _fact(10, 1, qty="225"), _fact(13, 4, predicate="주의", polarity="NEGATE")
    group = EntityGroup(entity_id=4, canonical_name="음료Z", facts=(q, note))
    card = append_facts([("QUANTITIES", (10,))], group, [13], category_name="기타")
    assert [(blk.kind, blk.fact_revision_ids) for blk in card.blocks] == [
        ("QUANTITIES", (10,)), ("NOTES", (13,))]


def test_append_rejects_fact_outside_group():
    group = EntityGroup(entity_id=4, canonical_name="음료Z", facts=(_fact(10, 1, qty="225"),))
    with pytest.raises(PlanInvalid):
        append_facts([("QUANTITIES", (10,))], group, [99], category_name="기타")


def _row(**over):
    row = dict(card_id=5, published_version_id=50, draft_version_id=50,
               assignment_type="AUTOMATIC", review_status="APPROVED", change_source="EXTRACTION",
               has_block_facts=True, in_merged=True)
    row.update(over)
    return row


@pytest.mark.parametrize("over, mode", [
    ({}, "REDRAFT"),
    ({"change_source": "OWNER_EDIT"}, "REDRAFT"),
    # 승인 전 시스템 재초안(EXTRACTION) — 그 초안 위에 이어 붙인다(최종 리뷰 I5)
    ({"draft_version_id": 51}, "REDRAFT"),
    ({"draft_version_id": 51, "change_source": "OWNER_EDIT"}, "DEFER"),  # 점주가 고치던 초안
    ({"draft_version_id": 51, "change_source": "OWNER_ANSWER"}, "DEFER"),
    ({"draft_version_id": 51, "has_block_facts": False}, "DEFER"),
    ({"draft_version_id": 51, "assignment_type": "MANUAL"}, "DEFER"),
    ({"draft_version_id": 51, "review_status": "NEEDS_REVIEW"}, "DEFER"),
    ({"assignment_type": "MANUAL"}, "DEFER"),     # 불변식 12
    ({"has_block_facts": False}, "DEFER"),
    ({"published_version_id": None, "draft_version_id": 51, "review_status": "PENDING"}, "REASSEMBLE"),
])
def test_classify_rows(over, mode):
    assert fact_cards._classify_rows(4, [_row(**over)]).mode == mode


def test_two_published_cards_defer():
    rows = [_row(), _row(card_id=6, published_version_id=60, draft_version_id=60)]
    assert fact_cards._classify_rows(4, rows).mode == "DEFER"


def test_no_rows_is_new():
    assert fact_cards._classify_rows(4, []).mode == "NEW"


# ── 파이프라인 연결 — REDRAFT 는 모델 입력에서 빠지고 결정적 새 초안으로 간다 ──────────

from contextlib import ExitStack  # noqa: E402
from unittest.mock import AsyncMock, patch  # noqa: E402

from app.ingest import entities, fact_assembly, impact, pipeline  # noqa: E402
from app.ingest.fact_assembly import AssemblyInput, PlanningOutcome  # noqa: E402
from app.ingest.fact_cards import DispositionCounts, EntityCardState, WrittenEntity  # noqa: E402
from app.ingest.pipeline import PreparedAssembly  # noqa: E402


def _state(entity_id, mode):
    return EntityCardState(entity_id, mode, (entity_id * 10,) if mode != "NEW" else (),
                           "EXISTING_CARD" if mode == "DEFER" else None)


def _planning():
    return PlanningOutcome(proposals={}, failed_entity_ids=(), unresolved=(), batch_count=0,
                           errors=())


class _Pool:
    def acquire(self):

        class _Ctx:
            async def __aenter__(self):
                return object()

            async def __aexit__(self, *exc):
                return False
        return _Ctx()


@pytest.mark.asyncio
async def test_prepare_skips_redraft_input():
    seen = {}

    async def load(conn, store_id, ids):
        seen["load"] = list(ids)
        return AssemblyInput(groups=(), held=())

    async def plan(**kw):
        seen["groups"] = [g.entity_id for g in kw["groups"]]
        return _planning()

    states = {1: _state(1, "REDRAFT"), 2: _state(2, "NEW"), 3: _state(3, "DEFER")}
    with patch.object(fact_assembly, "entities_for_source", AsyncMock(return_value=[1, 2, 3])), \
         patch.object(fact_cards, "entity_card_state",
                      AsyncMock(side_effect=lambda c, s, e: states[e])), \
         patch.object(fact_assembly, "load_entity_groups", load), \
         patch.object(fact_assembly, "plan_entities", plan):
        prepared = await pipeline._prepare_fact_assembly(
            _Pool(), 1, 7, categories=["기타"], glossary=[], usage_sink=None,
            usage_base=None, raw_sink=None, strict=True)
    assert seen["load"] == [2]  # REDRAFT·DEFER 대상은 입력을 읽지 않는다(모델에 보내지 않는다)
    assert seen["groups"] == []
    assert prepared.states[1].mode == "REDRAFT"


@pytest.mark.asyncio
async def test_persist_redraft_branch():
    calls = []

    async def mark(conn, store_id, *, source_id, fact_ids, reason):
        calls.append(("mark", tuple(fact_ids), reason))
        return 1

    async def redraft(conn, store_id, *, source_id, state):
        calls.append(("redraft", state.entity_id))
        if state.entity_id == 4:
            return WrittenEntity(4, (), (), (), deferred_reason="EXISTING_CARD")
        return WrittenEntity(state.entity_id, (state.entity_id * 10,), (77,), ())

    async def noop(*a, **k):
        return 0

    before = {1: "REDRAFT", 2: "REDRAFT", 3: "NEW", 4: "REDRAFT"}
    now = {1: "REDRAFT", 2: "NEW", 3: "REDRAFT", 4: "REDRAFT"}
    prepared = PreparedAssembly(entity_ids=(1, 2, 3, 4),
                                states={e: _state(e, m) for e, m in before.items()},
                                groups={}, held=(), data_errors={}, planning=_planning())
    counts = DispositionCounts(total=1, missing=0, linked=1, review_pending={}, excluded={})
    with ExitStack() as stack:
        for obj, name, value in [
            (entities, "lock_store_knowledge", noop),
            (fact_cards, "record_unresolvable_occurrences", noop),
            (fact_cards, "entity_card_state",
             AsyncMock(side_effect=lambda c, s, e: _state(e, now[e]))),
            (fact_cards, "entity_fact_ids", AsyncMock(side_effect=lambda c, s, e: [e * 1000])),
            (fact_cards, "mark_pending", mark),
            (fact_cards, "redraft_published_card", redraft),
            (fact_cards, "write_entity_cards", AsyncMock(side_effect=AssertionError)),
            (fact_cards, "disposition_counts", AsyncMock(return_value=counts)),
            (impact, "record_upload_proposals", noop),
        ]:
            stack.enter_context(patch.object(obj, name, value))
        created = await pipeline._persist_fact_cards(object(), 3, 5, {"기타": 1}, prepared,
                                                     job_id=9, category_version=1)
    assert created == 1  # 대상 1 의 새 판 하나. 보류된 대상 4 는 세지 않는다
    assert ("redraft", 1) in calls and ("redraft", 4) in calls
    assert ("mark", (2000,), fact_cards.REASON_CONCURRENT) in calls
    assert ("mark", (3000,), fact_cards.REASON_CONCURRENT) in calls
    assert ("redraft", 2) not in calls and ("redraft", 3) not in calls
