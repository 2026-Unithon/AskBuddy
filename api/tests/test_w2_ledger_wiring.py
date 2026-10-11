"""W2-2 파이프라인 연결 — 원장 저장은 같은 conn 으로 판 연결을 항상 부른다.

설정은 필드가 몇 개뿐인 NS 로 patch 한다(F18). 모델·DB 는 부르지 않는다.
"""
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

import pytest

from app.ingest import fact_ledger, pipeline
from app.ingest.entity_names import parse_variant
from app.ingest.fact_keys import (REASON_UNASSEMBLED, REASON_VARIANT_MISMATCH,
                                  REASON_VARIANT_MULTI)
from app.ingest.schemas import LocatedAssertion, LocatedEvidence


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
async def test_ledger_returns_keys_and_links_with_the_same_conn_and_sorted_unique_ids():
    conn, link, out = await _run_ledger(_settings(), [78, 77, 78])
    link.assert_awaited_once()
    assert link.await_args.args == (conn, 3, 5, [77, 78])
    assert out == {"f1": 78, "f2": 77, "f3": 78}


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
