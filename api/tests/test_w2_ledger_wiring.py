"""W2-2 파이프라인 연결 — 플래그 꺼짐이면 이전과 같고, 켜면 같은 conn 으로 판 연결을 부른다.

설정은 필드가 몇 개뿐인 NS 로 patch 한다(F18). 모델·DB 는 부르지 않는다.
"""
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

import pytest

from app.ingest import entities, fact_ledger, pipeline
from app.ingest.entity_names import parse_variant
from app.ingest.fact_keys import (REASON_UNASSEMBLED, REASON_VARIANT_MISMATCH,
                                  REASON_VARIANT_MULTI)
from app.ingest.schemas import (ExtractedCard, ExtractedFact, ExtractionResult,
                                LocatedAssertion, LocatedEvidence)


def _settings(**extra):
    return NS(gemini_model="gemini-synthetic", extract_temperature=0.0, ingest_mode="mock",
              extract_locator_hints=False, **extra)


def _a(ref, value="10"):
    return LocatedAssertion(local_ref=ref, original_assertion=f"음료Z 물 {value}ml",
                            subject="음료Z", attribute="물", value=value, unit="ml",
                            confidence=.9, evidence=LocatedEvidence())


class _Conn:
    async def execute(self, query, *args):
        return "INSERT 0 1"


async def _run_ledger(settings, ids):
    conn = _Conn()
    link = AsyncMock()
    with patch.object(pipeline.repo, "insert_source_facts", AsyncMock(return_value=ids)), \
         patch.object(fact_ledger, "link_source_facts", link), \
         patch("app.config.get_settings", return_value=settings):
        out = await pipeline._persist_ledger(conn, 3, 5, "SCAN",
                                             [_a("f1"), _a("f2", "20"), _a("f3", "10")])
    return conn, link, out


@pytest.mark.asyncio
async def test_flag_absent_does_not_link():
    _, link, out = await _run_ledger(_settings(), [78, 77, 78])
    link.assert_not_awaited()
    assert out == {"f1": 78, "f2": 77, "f3": 78}


@pytest.mark.asyncio
async def test_flag_off_does_not_link():
    _, link, _ = await _run_ledger(_settings(w_entity_revision_enabled=False), [78, 77, 78])
    link.assert_not_awaited()


@pytest.mark.asyncio
async def test_flag_on_links_with_the_same_conn_and_sorted_unique_ids():
    conn, link, _ = await _run_ledger(_settings(w_entity_revision_enabled=True), [78, 77, 78])
    link.assert_awaited_once()
    assert link.await_args.args == (conn, 3, 5, [77, 78])


def _card():
    return ExtractedCard(category_name="기타", title="음료Z", content="물 10ml", confidence=.9,
                         facts=[ExtractedFact(object_name="음료Z", attribute="물", value="10",
                                              confidence=.9, ref="f1")])


async def _run_persist(settings, entity, calls=None):
    conn = NS(fetchval=AsyncMock(return_value="SCAN"))
    calls = [] if calls is None else calls
    insert_card = AsyncMock(return_value=9, side_effect=lambda *a, **k: calls.append("card") or 9)
    card_entity = AsyncMock(return_value=entity)
    lock = AsyncMock(side_effect=lambda *a, **k: calls.append("lock"))
    with patch.object(pipeline.repo, "insert_card", insert_card), \
         patch.object(entities, "lock_store_knowledge", lock), \
         patch("app.ingest.impact.record_upload_proposals", AsyncMock()), \
         patch.object(pipeline.repo, "insert_facts", AsyncMock()), \
         patch.object(pipeline.repo, "link_card_facts", AsyncMock()), \
         patch.object(pipeline.repo, "insert_card_evidence", AsyncMock()), \
         patch.object(pipeline.repo, "set_assembly_state", AsyncMock()), \
         patch.object(fact_ledger, "card_entity_for", card_entity), \
         patch("app.config.get_settings", return_value=settings):
        await pipeline._persist(conn, 3, 5, {"기타": 1}, ExtractionResult(cards=[_card()]),
                                job_id=None, category_version=1,
                                ledger_ids={"f1": 77, "f2": 78})
    _run_persist.last_lock = lock
    return conn, insert_card, card_entity


@pytest.mark.asyncio
async def test_persist_flag_absent_inserts_card_without_entity():
    _, insert_card, card_entity = await _run_persist(_settings(), 42)
    card_entity.assert_not_awaited()
    assert insert_card.await_args.kwargs["entity_id"] is None


@pytest.mark.asyncio
async def test_persist_flag_on_passes_card_entity_to_insert_card():
    conn, insert_card, card_entity = await _run_persist(
        _settings(w_entity_revision_enabled=True), 42)
    assert card_entity.await_args.args == (conn, 3, [77])
    assert insert_card.await_args.kwargs["entity_id"] == 42


@pytest.mark.asyncio
async def test_persist_flags_off_takes_no_store_lock():
    calls = []
    await _run_persist(_settings(w_entity_revision_enabled=False,
                                 w_upload_proposals_enabled=False), 42, calls)
    _run_persist.last_lock.assert_not_awaited()
    assert calls == ["card"]


@pytest.mark.asyncio
async def test_persist_flags_absent_takes_no_store_lock():
    calls = []
    await _run_persist(_settings(), 42, calls)
    _run_persist.last_lock.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("flags", [
    {"w_entity_revision_enabled": True},
    {"w_entity_revision_enabled": True, "w_upload_proposals_enabled": True},
    {"w_upload_proposals_enabled": True},
])
async def test_persist_flag_on_takes_store_lock_before_insert_card(flags):
    # 매장 잠금 → 대상 행 순서 (merge_entities 와 같은 순서라야 교착하지 않는다)
    calls = []
    conn, _, _ = await _run_persist(_settings(**flags), 42, calls)
    assert calls[0] == "lock" and calls.index("lock") < calls.index("card")
    assert _run_persist.last_lock.await_args.args == (conn, 3)


def _row(variant=""):
    return {"subject": "음료Z", "attribute": " 물 ", "value": "275", "unit": "ml",
            "polarity": "AFFIRM", "step_order": None, "conditions": "[]", "exceptions": "[]",
            "original_assertion": "음료Z 물 275ml", "variant": variant}


def test_shape_variant_empty_field_takes_the_name_hint():
    shape, reason = fact_ledger.shape_from_ledger(_row(), parse_variant(""), "ICE", "L")
    assert (shape.variant_temperature, shape.variant_size) == ("ICE", "L")
    assert reason == REASON_UNASSEMBLED
    assert shape.predicate == "물" and shape.quantity_unit == "ml"


def test_shape_variant_same_field_and_hint():
    shape, reason = fact_ledger.shape_from_ledger(_row("ICE"), parse_variant("ICE"), "ICE", None)
    assert shape.variant_temperature == "ICE" and reason == REASON_UNASSEMBLED


def test_shape_variant_field_and_hint_differ_keeps_field():
    shape, reason = fact_ledger.shape_from_ledger(_row("HOT"), parse_variant("HOT"), "ICE", None)
    assert shape.variant_temperature == "HOT" and reason == REASON_VARIANT_MISMATCH


def test_shape_variant_multi_temperature():
    shape, reason = fact_ledger.shape_from_ledger(_row("HOT/ICE"), parse_variant("HOT/ICE"),
                                                  None, None)
    assert shape.variant_temperature is None and reason == REASON_VARIANT_MULTI


def test_shape_missing_original_builds_a_fallback_sentence():
    row = _row() | {"original_assertion": "  "}
    shape, _ = fact_ledger.shape_from_ledger(row, parse_variant(""), None, None)
    assert shape.original_assertion == shape.assertion == "음료Z 물 275ml"


@pytest.mark.asyncio
async def test_link_empty_list_does_not_touch_the_db():
    out = await fact_ledger.link_source_facts(object(), 3, 5, [])
    assert out == fact_ledger.LinkOutcome(0, 0, (), 0, 0)


@pytest.mark.asyncio
async def test_card_entity_empty_list_does_not_touch_the_db():
    assert await fact_ledger.card_entity_for(object(), 3, []) is None


class _OwnerConn:
    """record_owner_answer_fact 의 같은 사실 경로를 흉내 낸다. 쓴 SQL 을 모은다."""

    def __init__(self):
        self.writes: list[tuple[str, tuple]] = []

    async def execute(self, query, *args):
        self.writes.append((query, args))
        return "INSERT 0 1"

    async def fetchval(self, query, *args):
        assert "owner_answers" in query and args == (11, 3)
        return 3   # 이 매장의 답변

    async def fetchrow(self, query, *args):
        assert "from knowledge_facts" in query and args[0] == 3
        return {"fact_id": 70, "head_revision_id": 700, "entity_id": 5}


@pytest.mark.asyncio
async def test_owner_answer_matching_existing_fact_still_records_its_source():
    from app.ingest.entities import EntityResolution
    conn = _OwnerConn()
    entity = EntityResolution(entity_id=5, name_norm="음료z", created=False,
                              temperature_hint=None, size_hint=None, candidate_ids=())
    with patch.object(fact_ledger, "lock_store_knowledge", AsyncMock()), \
         patch.object(fact_ledger, "resolve_entity", AsyncMock(return_value=entity)):
        out = await fact_ledger.record_owner_answer_fact(
            conn, 3, owner_answer_id=11, subject="음료Z", attribute="얼음", value="5",
            unit="개", variant=None, polarity="AFFIRM", conditions=[], exceptions=[],
            step_order=None, original_assertion="음료Z 얼음은 5개", actor_id=1)
    assert out == (70, 700)
    # 같은 사실이라 새 판·메타는 없고, 점주 답변 출처 연결만 멱등 insert 한다
    assert not any("fact_revisions" in q or "fact_revision_meta" in q for q, _ in conn.writes)
    links = [(q, a) for q, a in conn.writes if "fact_owner_answer_links" in q]
    assert len(links) == 1
    query, args = links[0]
    assert "on conflict (store_id, fact_id, owner_answer_id) do nothing" in query
    assert args == (3, 70, 700, 11)
    assert not any("fact_occurrences" in q for q, _ in conn.writes)


def test_ledger_sql_filters_by_store():
    import inspect
    src = inspect.getsource(fact_ledger)
    # 모든 조회·쓰기가 매장으로 좁혀진다 (D1)
    assert src.count("store_id = $1") >= 12
