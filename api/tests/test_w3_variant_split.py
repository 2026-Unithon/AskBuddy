"""W3-0 §3-1 — HOT/ICE 가 함께 적힌 사실을 원장에서 규격별 두 사실로 나눈다.

순수 함수와 파이프라인 연결(_persist_ledger·_persist)을 본다. 설정은 필드가 몇 개뿐인
NS 로 patch 한다(F18). 모델·DB 는 부르지 않는다. 실제 DB 동작은
scripts/verify_w3_flag_readiness.py 의 T2·T8 이 본다.
"""
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

import pytest

from app.ingest import fact_ledger, pipeline, variant_split
from app.ingest.entity_names import strip_temperature
from app.ingest.schemas import (ExtractedCard, ExtractedFact, ExtractionResult,
                                LocatedAssertion, LocatedEvidence)


def _a(ref, *, variant="HOT/ICE", requires=(), value="2"):
    return LocatedAssertion(local_ref=ref, original_assertion=f"음료Z 에스프레소 {value}샷",
                            subject="음료Z", attribute="에스프레소", value=value, unit="샷",
                            variant=variant, requires=list(requires),
                            conditions=["바쁠 때"], exceptions=["디카페인"], order=0,
                            confidence=.9, evidence=LocatedEvidence(timestamp_sec=12))


# ── 순수 함수 ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw, rest", [
    ("HOT/ICE L", "L"),
    ("핫/아이스", ""),
    ("따뜻한/차가운 R", "R"),
    ("HOT/ICE L/R", "L R"),
    (None, ""),
])
def test_strip_temperature_keeps_other_spec_words(raw, rest):
    assert strip_temperature(raw) == rest


def test_split_hot_ice_makes_two_facts_with_same_values():
    out = variant_split.split_hot_ice([_a("f1")])
    assert [a.local_ref for a in out] == ["f1~HOT", "f1~ICE"]
    assert [a.variant for a in out] == ["HOT", "ICE"]
    for a in out:
        assert (a.subject, a.attribute, a.value, a.unit, a.polarity, a.conditions,
                a.exceptions, a.order, a.original_assertion, a.evidence.timestamp_sec) == (
            "음료Z", "에스프레소", "2", "샷", "AFFIRM", ["바쁠 때"], ["디카페인"], 0,
            "음료Z 에스프레소 2샷", 12)


def test_split_keeps_size_words():
    out = variant_split.split_hot_ice([_a("f1", variant="HOT/ICE L")])
    assert [a.as_variant() for a in out] == ["HOT L", "ICE L"]


@pytest.mark.parametrize("variant", ["", "HOT", "ICE", "L/R", "ice/iced"])
def test_non_multi_temperature_passes_through_as_the_same_objects(variant):
    items = [_a("f1", variant=variant), _a("f2", variant=variant, value="3", requires=["f1"])]
    out = variant_split.split_hot_ice(items)
    assert len(out) == 2 and all(x is y for x, y in zip(out, items))


def test_requires_pointing_to_split_fact_points_to_both():
    out = variant_split.split_hot_ice([_a("f1"), _a("f2", variant="", requires=["f1"])])
    assert [a.local_ref for a in out] == ["f1~HOT", "f1~ICE", "f2"]
    assert out[2].requires == ["f1~HOT", "f1~ICE"]


def test_split_dependent_requires_only_the_same_temperature():
    out = variant_split.split_hot_ice([
        _a("f1"), _a("f2", requires=["f1", "f0"]), _a("f0", variant="", value="1")])
    by_ref = {a.local_ref: a for a in out}
    assert by_ref["f2~HOT"].requires == ["f1~HOT", "f0"]
    assert by_ref["f2~ICE"].requires == ["f1~ICE", "f0"]
    assert by_ref["f0"].requires == []


def test_private_attributes_are_copied_and_marker_added_only_to_copies():
    original = _a("f1")
    original._raw_response_id = 55
    original._layout_locator = {"page": 2, "region": "r1"}
    original._check_flags.append({"field": "variant", "verdict": "UNGROUNDED_TEXT",
                                  "value": "HOT/ICE"})
    out = variant_split.split_hot_ice([original])
    marker = {"field": "variant", "verdict": "VARIANT_SPLIT", "value": "HOT/ICE",
              "variant_split": "HOT_ICE", "from_ref": "f1"}
    for a in out:
        assert a.raw_response_id == 55
        assert a._layout_locator == {"page": 2, "region": "r1"}
        assert a.check_flags == [original.check_flags[0], marker]
    assert out[0].check_flags is not out[1].check_flags
    assert out[0]._layout_locator is not original._layout_locator
    # 입력은 그대로 — 조립 입력과 복구 캐시가 같은 객체를 쓴다
    assert (original.local_ref, original.variant, len(original.check_flags)) == (
        "f1", "HOT/ICE", 1)


def test_long_local_ref_stays_within_40_chars_and_distinct():
    ref = "seg10.2.1:" + "r" * 35   # 45자
    out = variant_split.split_hot_ice([_a(ref)])
    refs = [a.local_ref for a in out]
    assert all(len(r) <= 40 for r in refs) and refs[0][:40] != refs[1][:40]
    assert tuple(refs) == variant_split.split_refs(ref)


# ── 파이프라인 연결 ───────────────────────────────────────────────────────────

def _settings(**extra):
    return NS(gemini_model="gemini-synthetic", extract_temperature=0.0, ingest_mode="mock",
              extract_locator_hints=False, **extra)


async def _ledger(settings, assertions, ids):
    insert = AsyncMock(return_value=ids)
    occ = AsyncMock()
    with patch.object(pipeline.repo, "insert_source_facts", insert), \
         patch.object(pipeline.occurrences, "insert_occurrences", occ), \
         patch.object(fact_ledger, "link_source_facts", AsyncMock()), \
         patch("app.config.get_settings", return_value=settings):
        out = await pipeline._persist_ledger(object(), 3, 5, "VIDEO", assertions)
    return insert.await_args.args[3], occ.await_args.args[2], out


@pytest.mark.asyncio
async def test_persist_ledger_flag_off_keeps_multi_variant_row():
    rows, occ, out = await _ledger(_settings(w_entity_revision_enabled=False), [_a("f1")], [70])
    assert [(r["local_ref"], r["variant"]) for r in rows] == [("f1", "HOT/ICE")]
    assert out == {"f1": 70} and len(occ) == 1


@pytest.mark.asyncio
async def test_persist_ledger_flag_on_splits_rows_and_occurrences():
    rows, occ, out = await _ledger(_settings(w_entity_revision_enabled=True), [_a("f1")],
                                   [70, 71])
    assert [(r["local_ref"], r["variant"]) for r in rows] == [("f1~HOT", "HOT"),
                                                              ("f1~ICE", "ICE")]
    assert out == {"f1~HOT": 70, "f1~ICE": 71}
    # 근거 위치는 두 사실 모두 원래 자리 그대로
    assert [(o["fact_id"], o["locator_type"], o["locator"]) for o in occ] == [
        (70, "TIMESTAMP", {"timestamp_sec": 12}), (71, "TIMESTAMP", {"timestamp_sec": 12})]
    assert all(o["check_flags"][-1]["verdict"] == "VARIANT_SPLIT" for o in occ)


@pytest.mark.asyncio
async def test_persist_ledger_flag_on_without_multi_is_identical_to_off():
    def items():
        return [_a("f1", variant="HOT"), _a("f2", variant="", requires=["f1"])]
    off = await _ledger(_settings(w_entity_revision_enabled=False), items(), [70, 71])
    on = await _ledger(_settings(w_entity_revision_enabled=True), items(), [70, 71])
    assert on == off


@pytest.mark.asyncio
async def test_persist_links_card_ref_to_both_split_facts():
    conn = NS(fetchval=AsyncMock(return_value="SCAN"))
    link = AsyncMock()
    state = AsyncMock()
    card = ExtractedCard(category_name="기타", title="음료Z", content="에스프레소 2샷",
                         confidence=.9, facts=[ExtractedFact(
                             object_name="음료Z", attribute="에스프레소", value="2",
                             confidence=.9, ref="f1")])
    with patch.object(pipeline.repo, "insert_card", AsyncMock(return_value=9)), \
         patch.object(pipeline.repo, "insert_facts", AsyncMock()), \
         patch.object(pipeline.repo, "link_card_facts", link), \
         patch.object(pipeline.repo, "insert_card_evidence", AsyncMock()), \
         patch.object(pipeline.repo, "set_assembly_state", state), \
         patch("app.config.get_settings", return_value=_settings()):
        await pipeline._persist(conn, 3, 5, {"기타": 1}, ExtractionResult(cards=[card]),
                                job_id=None, category_version=1,
                                ledger_ids={"f1~HOT": 70, "f1~ICE": 71, "f2": 72})
    assert link.await_args.args == (conn, 3, 9, [70, 71])
    assert [c.args for c in state.await_args_list] == [
        (conn, 3, [70, 71], "LINKED"), (conn, 3, [72], "DROPPED")]


@pytest.mark.asyncio
async def test_persist_ledger_rerun_under_retry_is_idempotent_and_keeps_input():
    """retry_io 가 같은 입력으로 _persist_ledger 를 다시 돌려도 같은 행이고 입력은 그대로다."""
    items = [_a("f1"), _a("f2", variant="HOT", requires=["f1"])]
    snapshot = [a.model_dump() for a in items]
    first = await _ledger(_settings(w_entity_revision_enabled=True), items, [70, 71, 72])
    second = await _ledger(_settings(w_entity_revision_enabled=True), items, [70, 71, 72])
    assert first == second
    assert [a.model_dump() for a in items] == snapshot
    assert items[0].check_flags == [] or all(
        f.get("verdict") != "VARIANT_SPLIT" for f in items[0].check_flags)
