"""W3a 대상 단위 조립 입력·사실 조립 호출 단위 테스트. 모델·DB 는 합성 대역이다(비용 0)."""
import asyncio
import json
from decimal import Decimal
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

import pytest

import app.config
from app.ingest import card_plan as cp
from app.ingest import extract
from app.ingest import fact_assembly as fa
from app.ingest.card_plan import EntityGroup, PlanFact
from app.ingest.extract import gemini, mock
from app.ingest.schemas import CardPlanBatch, PlannedBlock, PlannedCard


def _fact(rev, fact_id, *, t=None, s=None, step=None, q=None, unit="ml", neg=False, cond=(),
          exc=(), req=(), text=None, entity=7, value_text=None):
    text = text if text is not None else f"합성 사실 {rev}"
    return PlanFact(
        fact_revision_id=rev, fact_id=fact_id, entity_id=entity, subject="음료Z", predicate="물",
        variant_temperature=t, variant_size=s,
        quantity_value=Decimal(q) if q is not None else None,
        quantity_unit=unit if q is not None else None, value_text=value_text,
        polarity="NEGATE" if neg else "AFFIRM", step_order=step,
        conditions=tuple(cond), exceptions=tuple(exc),
        original_assertion=text, assertion=text, requires_fact_ids=tuple(req),
    )


def _group(entity_id, facts, name="음료Z"):
    return EntityGroup(entity_id, name, tuple(sorted(facts, key=cp.fact_sort_key)))


def _example():
    """Task 2 예시 묶음 — 판·사실·대상 id 를 큰 수로 둔다(페이로드에 새지 않는지 본다)."""
    e = 9001
    return _group(e, [
        _fact(4001, 5001, t="ICE", q="225", text="ICE 음료Z 물 225ml", entity=e),
        _fact(4002, 5002, t="HOT", q="275", text="HOT 음료Z 물 275ml", entity=e),
        _fact(4003, 5003, t="ICE", step=1, text="컵에 얼음을 채운다", entity=e),
        _fact(4004, 5004, t="ICE", step=2, text="샷을 붓는다", cond=("매장 컵일 때",),
              req=(5003,), entity=e),
        _fact(4005, 5005, neg=True, text="음료Z 에는 시럽을 넣지 않는다",
              exc=("손님 요청 시",), entity=e),
        _fact(4006, 5006, q="100", unit="g", text="얼음 100g", entity=e),
    ])


def _sized(entity_id, n, start):
    return _group(entity_id, [_fact(start + i, start + i, q=str(i + 1), entity=entity_id)
                              for i in range(n)], name=f"합성음료{entity_id}")


def _settings(**kw):
    return NS(**{"assemble_batch_facts": 200, "assemble_concurrency": 1, **kw})


def _planned_reply(**kwargs):
    return mock._planned(kwargs["entities"], kwargs["category_names"])


# 1
def test_build_batches_keeps_entity_whole():
    g1, g2, g3 = _sized(1, 3, 100), _sized(2, 3, 200), _sized(3, 5, 300)
    batches = fa.build_plan_batches([g1, g2, g3], limit=5)
    assert [[g.entity_id for g in b.groups] for b in batches] == [[1], [2], [3]]
    g1, g2, g3 = _sized(1, 2, 100), _sized(2, 2, 200), _sized(3, 7, 300)
    batches = fa.build_plan_batches([g1, g2, g3], limit=5)
    assert [[g.entity_id for g in b.groups] for b in batches] == [[1, 2], [3]]
    assert [b.index for b in batches] == [0, 1]
    for b in batches:
        assert b.payload[0]["대상"] == "E1"
        assert b.payload[0]["사실"][0]["id"] == "F1"
    assert batches[0].entity_handles == {"E1": 1, "E2": 2}
    assert list(batches[0].fact_handles) == ["F1", "F2", "F3", "F4"]
    assert batches[1].fact_handles["F7"] == 306


# 2
def test_payload_shape_and_no_db_ids():
    group = _example()
    (batch,) = fa.build_plan_batches([group], limit=200)
    (entity,) = batch.payload
    assert set(entity) == {"대상", "이름", "사실"}
    assert (entity["대상"], entity["이름"]) == ("E1", "음료Z")
    facts = {batch.fact_handles[f["id"]]: f for f in entity["사실"]}
    for f in entity["사실"]:
        assert set(f) == {"id", "규격", "속성", "값", "부정", "조건", "예외", "순서", "선행", "원문"}
    # 순서는 fact_sort_key 순 — HOT, ICE(단계1·단계2·수치), 규격 없음
    assert [batch.fact_handles[f["id"]] for f in entity["사실"]] == [
        4002, 4003, 4004, 4001, 4005, 4006]
    assert facts[4001] == {"id": "F4", "규격": "ICE", "속성": "물", "값": "225 ml", "부정": False,
                           "조건": [], "예외": [], "순서": 0, "선행": [],
                           "원문": "ICE 음료Z 물 225ml"}
    assert facts[4006]["값"] == "100 g" and facts[4006]["규격"] == ""
    step1 = next(h for h, rid in batch.fact_handles.items() if rid == 4003)
    assert facts[4004]["선행"] == [step1] and facts[4004]["순서"] == 2
    assert facts[4004]["조건"] == ["매장 컵일 때"]
    assert facts[4005]["부정"] is True and facts[4005]["예외"] == ["손님 요청 시"]
    text = json.dumps(batch.payload, ensure_ascii=False)
    for secret in ["9001", *map(str, range(4001, 4007)), *map(str, range(5001, 5007))]:
        assert secret not in text


def test_payload_value_formats_decimal_and_text():
    group = _group(1, [_fact(1, 1, q="100", unit=None), _fact(2, 2, value_text="뜨겁게"),
                       _fact(3, 3, q="2.50", unit="샷")])
    (batch,) = fa.build_plan_batches([group], limit=200)
    assert [f["값"] for f in batch.payload[0]["사실"]] == ["100", "뜨겁게", "2.5 샷"]


# 3
def test_proposals_from_output_maps_handles():
    g1 = _group(1, [_fact(11, 11, entity=1), _fact(12, 12, entity=1)])
    g2 = _group(2, [_fact(21, 21, entity=2)])
    (batch,) = fa.build_plan_batches([g1, g2], limit=200)
    out = CardPlanBatch(cards=[
        PlannedCard(entity="E1", category_name="레시피", blocks=[
            PlannedBlock(kind="QUANTITIES", facts=["F1", "F99", "F3"])]),
        PlannedCard(entity="E9", category_name="레시피", blocks=[
            PlannedBlock(kind="NOTES", facts=["F2"])]),
    ], unresolved=["값 확인 필요"])
    proposals, notes = fa.proposals_from_output(batch, out)
    assert proposals[1] == (cp.ProposedCard("레시피", (
        cp.ProposedBlock("QUANTITIES", (11, "F99", 21)),)),)
    assert proposals[2] == ()
    assert notes == ["알 수 없는 대상 이름표 E9", "값 확인 필요"]


# 4
def test_card_plan_prompt_marker_and_determinism():
    raw = gemini.CARD_PLAN_PROMPT_PATH.read_text(encoding="utf-8")
    assert raw.count(fa.PLAN_INPUT_MARKER) == 1
    (batch,) = fa.build_plan_batches([_example()], limit=200)
    kwargs = dict(entities=batch.payload, category_names=["레시피", "마감"],
                  glossary=[{"term": "샷", "description": "에스프레소 한 번"}])
    prompt = gemini.render_card_plan_prompt(**kwargs)
    assert prompt == gemini.render_card_plan_prompt(**kwargs)
    assert json.loads(prompt.split(fa.PLAN_INPUT_MARKER, 1)[1]) == batch.payload
    assert "- 레시피\n- 마감" in prompt and "- 샷: 에스프레소 한 번" in prompt
    assert "{categories}" not in prompt and "{glossary}" not in prompt


# 5
@pytest.mark.asyncio
async def test_plan_entities_same_outcome_any_concurrency():
    groups = [_sized(i, 2, i * 100) for i in range(1, 7)]  # 한도 2 → 배치 6
    seen, running, peak = [], [0], [0]

    async def fake(**kwargs):
        index = kwargs["usage_context"]
        seen.append(index)
        running[0] += 1
        peak[0] = max(peak[0], running[0])
        await asyncio.sleep(0.005 * (6 - index))  # 뒤 배치일수록 빨리 끝난다
        running[0] -= 1
        return _planned_reply(**kwargs)

    outcomes = {}
    for c in (1, 3):
        seen.clear()
        peak[0] = 0
        with patch.object(app.config, "get_settings",
                          lambda c=c: _settings(assemble_batch_facts=2, assemble_concurrency=c)), \
                patch("app.ingest.extract.assemble_card_plan", fake):
            outcomes[c] = await fa.plan_entities(
                source_id=1, groups=groups, categories=["레시피"], glossary=[],
                context_for=lambda i: i, strict=True)
        assert set(seen) == set(range(6))
        assert peak[0] == (1 if c == 1 else 3)
    assert outcomes[1] == outcomes[3]
    assert outcomes[1].batch_count == 6 and set(outcomes[1].proposals) == set(range(1, 7))


def _failing(fail_index):
    async def fake(**kwargs):
        if kwargs["usage_context"] == fail_index:
            raise ValueError("합성 실패")
        return _planned_reply(**kwargs)
    return fake


# 6
@pytest.mark.asyncio
async def test_plan_entities_partial_failure_non_strict():
    groups = [_sized(i, 2, i * 100) for i in range(1, 4)]
    with patch.object(app.config, "get_settings",
                      lambda: _settings(assemble_batch_facts=2, assemble_concurrency=2)), \
            patch("app.ingest.extract.assemble_card_plan", _failing(1)):
        out = await fa.plan_entities(source_id=1, groups=groups, categories=["레시피"],
                                     glossary=[], context_for=lambda i: i, strict=False)
    assert out.failed_entity_ids == (2,)
    assert set(out.proposals) == {1, 3} and out.proposals[1]
    assert len(out.errors) == 1 and out.errors[0].startswith("plan1: ValueError: 합성 실패")


# 7
@pytest.mark.asyncio
async def test_plan_entities_strict_raises():
    groups = [_sized(i, 2, i * 100) for i in range(1, 4)]
    with patch.object(app.config, "get_settings",
                      lambda: _settings(assemble_batch_facts=2)), \
            patch("app.ingest.extract.assemble_card_plan", _failing(1)):
        with pytest.raises(RuntimeError, match="카드 조립 실패") as e:
            await fa.plan_entities(source_id=1, groups=groups, categories=["레시피"],
                                   glossary=[], context_for=lambda i: i, strict=True)
    assert isinstance(e.value.__cause__, ValueError)


# 8
@pytest.mark.asyncio
async def test_plan_entities_no_groups_no_call():
    fake = AsyncMock()
    with patch.object(app.config, "get_settings", lambda: _settings()), \
            patch("app.ingest.extract.assemble_card_plan", fake):
        out = await fa.plan_entities(source_id=1, groups=[], categories=[], glossary=[],
                                     strict=True)
    assert fake.await_count == 0 and out.batch_count == 0 and out.proposals == {}


# 9
def test_mock_plan_passes_server_validation():
    group = _example()
    (batch,) = fa.build_plan_batches([group], limit=200)
    out = mock._planned(batch.payload, ["레시피"])
    proposals, notes = fa.proposals_from_output(batch, out)
    assert notes == []
    result = cp.plan_entity(group, proposals[group.entity_id])
    assert result.model_error is None and result.pending_reason is None
    placed = {rid for card in result.cards for rid in card.fact_revision_ids()}
    assert placed == {f.fact_revision_id for f in group.facts}
    assert {c.category_name for c in result.cards} == {"레시피"}
    assert mock._planned(batch.payload, []).cards[0].category_name == "기타"


# 10
@pytest.mark.asyncio
async def test_gemini_assemble_plan_schema():
    (batch,) = fa.build_plan_batches([_example()], limit=200)
    got = {}

    async def fake_call(prompt, media, schema=None, max_output_tokens=None):
        got["schema"] = schema
        body = mock._planned(json.loads(prompt.split(fa.PLAN_INPUT_MARKER, 1)[1]), ["레시피"])
        return gemini.CallResult(body.model_dump_json(), {}, "STOP")

    real = NS(gemini_api_key="synthetic", gemini_model="gemini-synthetic", ingest_mode="real",
              extract_temperature=0.0)
    with patch.object(gemini, "get_settings", return_value=real), \
            patch.object(gemini, "_call", fake_call):
        out = await gemini.assemble_plan(source_id=1, entities=batch.payload,
                                         category_names=["레시피"], glossary=[])
        empty = await gemini.assemble_plan(source_id=1, entities=[],
                                           category_names=["레시피"], glossary=[])
    assert got["schema"] is CardPlanBatch
    assert isinstance(out, CardPlanBatch) and len(out.cards) == 1
    assert empty.cards == []
    with patch.object(gemini, "get_settings", return_value=NS(gemini_api_key="")):
        with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
            await gemini.assemble_plan(source_id=1, entities=batch.payload,
                                       category_names=[], glossary=[])


# 11
@pytest.mark.asyncio
async def test_dispatcher_selects_mode():
    calls = []

    async def fake_mock(**kwargs):
        calls.append(("mock", "usage_sink" in kwargs))
        return CardPlanBatch()

    async def fake_real(**kwargs):
        calls.append(("real", "usage_sink" in kwargs))
        return CardPlanBatch()

    kwargs = dict(source_id=1, entities=[], category_names=[], glossary=[], usage_sink=object())
    with patch.object(mock, "assemble_plan", fake_mock), \
            patch.object(gemini, "assemble_plan", fake_real):
        with patch.object(extract, "get_settings", lambda: NS(ingest_mode="mock")):
            await extract.assemble_card_plan(**kwargs)
        with patch.object(extract, "get_settings", lambda: NS(ingest_mode="real")):
            await extract.assemble_card_plan(**kwargs)
    assert calls == [("mock", False), ("real", True)]
