"""W3b 텍스트 분석 단위 시험 — 모델 호출 없이 합성 결과·합성 대역으로만."""
from __future__ import annotations

import json
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest

from app.cards import fact_parse, router
from app.cards.fact_edit_plan import CardFactState, PinnedFact
from app.cards.fact_edit_schemas import FactParseRequest, FactParseResponse
from app.errors import ApiError
from app.ingest.card_plan import PlanFact
from app.ingest.extract import gemini, mock
from app.ingest.schemas import ExtractedAssertion, FactExtractionResult


def _fact(rid, fid, sentence, *, temp=None, size=None, qty=None, unit=None, step=None,
          predicate="양"):
    return PlanFact(
        fact_revision_id=rid, fact_id=fid, entity_id=7, subject="음료Z", predicate=predicate,
        variant_temperature=temp, variant_size=size,
        quantity_value=Decimal(qty) if qty is not None else None, quantity_unit=unit,
        value_text=None, polarity="AFFIRM", step_order=step, conditions=(), exceptions=(),
        original_assertion=sentence, assertion=sentence, requires_fact_ids=(),
    )


def _state(entity_problem=None) -> CardFactState:
    facts = [
        PinnedFact(_fact(1, 101, "ICE 물 225ml", temp="ICE", qty="225", unit="ml"), "b1", "QUANTITIES", 1),
        PinnedFact(_fact(2, 102, "ICE 먼저 컵을 채운다", temp="ICE", step=1, predicate="순서"),
                   "b2", "STEPS", 1),
    ]
    return CardFactState(
        store_id=3, card_id=5, version_id=11, title="음료Z", review_status="NEEDS_REVIEW",
        published_version_id=None, entity_id=None if entity_problem else 7, entity_name="음료Z",
        alias_norms=frozenset({"음료z", "합성음료"}), entity_problem=entity_problem,
        blocks=(("b1", "QUANTITIES", 1), ("b2", "STEPS", 2)), pinned=tuple(facts),
    )


def _a(sentence, *, subject="음료Z", value="", unit="", variant="", order=0, polarity="AFFIRM",
       attribute="", ref="o1"):
    return ExtractedAssertion(
        local_ref=ref, original_assertion=sentence, subject=subject, attribute=attribute,
        value=value, unit=unit, variant=variant, order=order, polarity=polarity, confidence=0.9)


def _result(*items):
    return FactExtractionResult(assertions=list(items))


def _run(result, *, mode="ADD", base=None, max_facts=10):
    return fact_parse.proposals_from_result(
        result, state=_state(), mode=mode, base=base, max_facts=max_facts)


# ── proposals_from_result ───────────────────────────────────────────────


def test_no_assertions_gives_no_fact():
    out = _run(_result())
    assert out.proposals == [] and out.warnings == ["NO_FACT"]


def test_blank_sentence_dropped():
    out = _run(_result(_a("   "), _a("물 20ml", value="20", unit="ml")))
    assert len(out.proposals) == 1 and out.warnings == []


def test_too_many_cut_to_max():
    out = _run(_result(_a("하나 1", ref="o1"), _a("둘 2", ref="o2"), _a("셋 3", ref="o3")), max_facts=2)
    assert [p.client_ref for p in out.proposals] == ["p1", "p2"]
    assert "TOO_MANY_FACTS" in out.warnings and "MULTIPLE_FACTS" in out.warnings


def test_variant_alias_maps_to_ice():
    p = _run(_result(_a("아이스 물 20ml", value="20", unit="ml", variant="아이스"))).proposals[0]
    assert p.fact.variant.temperature == "ICE" and p.fact.variant.size is None
    assert "VARIANT_UNRESOLVED" not in p.warnings and "NEW_VARIANT" not in p.warnings


def test_unknown_variant_unresolved_and_blank():
    p = _run(_result(_a("XL 물 20ml", value="20", unit="ml", variant="XL"))).proposals[0]
    assert "VARIANT_UNRESOLVED" in p.warnings
    assert p.fact.variant.temperature is None and p.fact.variant.size is None


def test_size_is_canonical_uppercase_and_new_variant_warned():
    p = _run(_result(_a("라지 물 30ml", value="30", unit="ml", variant="라지"))).proposals[0]
    assert p.fact.variant.size == "L"
    assert "NEW_VARIANT" in p.warnings


def test_subject_alias_match_no_warning_and_mismatch_warned():
    ok = _run(_result(_a("물 20ml", subject="합성음료", value="20", unit="ml", variant="ICE")))
    assert "SUBJECT_MISMATCH" not in ok.proposals[0].warnings
    bad = _run(_result(_a("물 20ml", subject="다른것", value="20", unit="ml", variant="ICE")))
    assert "SUBJECT_MISMATCH" in bad.proposals[0].warnings
    blank = _run(_result(_a("물 20ml", subject="", value="20", unit="ml", variant="ICE")))
    assert "SUBJECT_MISMATCH" not in blank.proposals[0].warnings


def test_value_not_in_sentence_warned():
    p = _run(_result(_a("물은 20ml", value="30", unit="ml", variant="ICE"))).proposals[0]
    assert "VALUE_NOT_IN_SENTENCE" in p.warnings


def test_empty_value_unit_become_none():
    f = _run(_result(_a("깨끗이 닦는다", variant="ICE"))).proposals[0].fact
    assert f.value is None and f.unit is None and f.step_order is None


def test_block_kind_rules():
    assert _run(_result(_a("물 20ml", value="20", unit="ml"))).proposals[0].block_kind == "QUANTITIES"
    assert _run(_result(_a("20ml 넣지 않는다", value="20", unit="ml",
                           polarity="NEGATE"))).proposals[0].block_kind == "NOTES"
    assert _run(_result(_a("먼저 컵", order=2))).proposals[0].block_kind == "STEPS"
    assert _run(_result(_a("깨끗이"))).proposals[0].block_kind == "NOTES"


def test_modify_split_keeps_base_variant_and_predicate():
    base = _state().pinned[0].fact
    out = _run(_result(_a("물 30ml", value="30", unit="ml", variant="HOT", ref="o1"),
                       _a("컵 2개", value="2", unit="개", ref="o2")), mode="MODIFY", base=base)
    assert "MODIFY_SPLIT" in out.warnings
    for p in out.proposals:
        assert p.fact.variant.temperature == "ICE" and p.fact.predicate == "양"
        assert "NEW_VARIANT" not in p.warnings


def test_modify_step_changed_keeps_base_order():
    base = _state().pinned[1].fact
    p = _run(_result(_a("컵을 채운다", order=0)), mode="MODIFY", base=base).proposals[0]
    assert p.fact.step_order == 1 and "STEP_CHANGED" in p.warnings
    q = _run(_result(_a("컵을 채운다", order=3)), mode="MODIFY", base=base).proposals[0]
    assert q.fact.step_order == 1 and "STEP_CHANGED" not in q.warnings


def test_modify_becoming_step_flagged():
    base = _state().pinned[0].fact
    p = _run(_result(_a("먼저 컵", order=2)), mode="MODIFY", base=base).proposals[0]
    assert p.fact.step_order is None and "STEP_CHANGED" in p.warnings


# ── 프롬프트 ────────────────────────────────────────────────────────────

PAYLOAD = {"entity_name": "음료Z", "card_variants": ["ICE"], "mode": "ADD",
           "base_sentence": None, "text": "물은 20ml 넣는다"}


def test_render_prompt_marker_then_json():
    prompt = gemini.render_owner_fact_prompt(PAYLOAD)
    head, _, tail = prompt.partition(gemini.PARSE_INPUT_MARKER + "\n")
    assert gemini.PARSE_INPUT_MARKER == "## 점주 입력" and head and "\n## 점주 입력" not in head
    assert json.loads(tail) == PAYLOAD
    assert not any("id" in k.lower().split("_") for k in json.loads(tail))


def test_render_prompt_stable():
    assert gemini.render_owner_fact_prompt(PAYLOAD) == gemini.render_owner_fact_prompt(dict(PAYLOAD))


# ── mock ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_mock_extracts_value_unit_and_negation():
    r = await mock.parse_owner_facts(payload={**PAYLOAD, "text": " 시럽은 20 ml 넣지 않는다 "})
    (a,) = r.assertions
    assert (a.local_ref, a.value, a.unit, a.polarity) == ("o1", "20", "ml", "NEGATE")
    assert a.original_assertion == "시럽은 20 ml 넣지 않는다" and a.subject == "음료Z"
    assert a.attribute == "" and a.variant == "" and a.confidence == 1.0


@pytest.mark.asyncio
async def test_mock_no_number_and_deterministic():
    p = {**PAYLOAD, "text": "컵을 닦는다"}
    a1 = (await mock.parse_owner_facts(payload=p)).model_dump()
    a2 = (await mock.parse_owner_facts(payload=p)).model_dump()
    assert a1 == a2 and a1["assertions"][0]["value"] == "" and a1["assertions"][0]["unit"] == ""
    assert a1["assertions"][0]["polarity"] == "AFFIRM"


# ── 라우터 ──────────────────────────────────────────────────────────────


class _NoDb:
    def __getattr__(self, name):
        raise AssertionError(f"db.{name} 을 부르면 안 된다")


class _Settings:
    w_fact_card_edit_enabled = True
    card_fact_parse_max_chars = 1000
    card_fact_parse_max_facts = 10


CARD = {"review_status": "NEEDS_REVIEW", "draft_version_id": 11}


async def _route(req, *, settings=_Settings, card=CARD, state=None, db=None, parse=None,
                 get_card=None, load_state=None):
    get_card = get_card or AsyncMock(return_value=card)
    load_state = load_state or AsyncMock(return_value=state)
    patches = [
        patch("app.config.get_settings", lambda: settings),
        patch.object(router, "_identity", return_value=(1, 3, "OWNER")),
        patch.object(router.repo, "get_card", get_card),
        patch.object(router.fact_repo, "load_card_fact_state", load_state),
        patch.object(router, "get_pool", lambda: "POOL"),
        patch.object(router.fact_parse, "parse_card_text", parse or AsyncMock(
            return_value=FactParseResponse(mode="ADD", proposals=[]))),
    ]
    for p in patches:
        p.start()
    try:
        return await router.parse_card_facts(5, req, db or _NoDb(), {"role": "OWNER"})
    finally:
        for p in patches:
            p.stop()


REQ = FactParseRequest(text="물 20ml")


@pytest.mark.asyncio
async def test_flag_off_is_403_before_any_db_read():
    class Off(_Settings):
        w_fact_card_edit_enabled = False
    get_card, load_state = AsyncMock(), AsyncMock()
    with pytest.raises(ApiError) as e:
        await _route(REQ, settings=Off, get_card=get_card, load_state=load_state)
    get_card.assert_not_called()
    load_state.assert_not_called()
    assert e.value.status_code == 403 and e.value.code == "FACT_EDIT_DISABLED"


@pytest.mark.asyncio
async def test_text_too_long_422():
    class Short(_Settings):
        card_fact_parse_max_chars = 3
    get_card, load_state = AsyncMock(), AsyncMock()
    with pytest.raises(ApiError) as e:
        await _route(REQ, settings=Short, get_card=get_card, load_state=load_state)
    get_card.assert_not_called()
    load_state.assert_not_called()
    assert e.value.status_code == 422 and e.value.code == "PARSE_TEXT_TOO_LONG"
    assert e.value.details == {"max_chars": 3}


@pytest.mark.asyncio
async def test_missing_flag_attr_means_off():
    class Bare:
        pass
    with pytest.raises(ApiError) as e:
        await _route(REQ, settings=Bare)
    assert e.value.code == "FACT_EDIT_DISABLED"


@pytest.mark.asyncio
async def test_card_missing_excluded_notfact():
    with pytest.raises(ApiError) as e:
        await _route(REQ, card=None)
    assert e.value.code == "CARD_NOT_FOUND"
    with pytest.raises(ApiError) as e:
        await _route(REQ, card={"review_status": "EXCLUDED", "draft_version_id": 11})
    assert e.value.code == "CARD_EXCLUDED"
    with pytest.raises(ApiError) as e:
        await _route(REQ, state=None)
    assert e.value.status_code == 409 and e.value.code == "NOT_FACT_CARD"


@pytest.mark.asyncio
async def test_entity_problem_rejected_before_parse():
    parse = AsyncMock()
    with pytest.raises(ApiError) as e:
        await _route(REQ, state=_state("MIXED_ENTITY"), parse=parse)
    assert e.value.code == "CARD_ENTITY_MOVED"
    assert e.value.details == {"entity_problem": "MIXED_ENTITY"}
    parse.assert_not_called()


@pytest.mark.asyncio
async def test_modify_base_not_in_card_422():
    req = FactParseRequest(text="물 30ml", mode="MODIFY", base_fact_revision_id=999)
    parse = AsyncMock()
    with pytest.raises(ApiError) as e:
        await _route(req, state=_state(), parse=parse)
    assert e.value.status_code == 422 and e.value.code == "PARSE_BASE_INVALID"
    parse.assert_not_called()


@pytest.mark.asyncio
async def test_happy_path_calls_parse_with_base():
    parse = AsyncMock(return_value=FactParseResponse(mode="MODIFY", proposals=[]))
    req = FactParseRequest(text="물 30ml", mode="MODIFY", base_fact_revision_id=1)
    out = await _route(req, state=_state(), parse=parse)
    assert out.mode == "MODIFY"
    kwargs = parse.call_args.kwargs
    assert kwargs["store_id"] == 3 and kwargs["card_id"] == 5 and kwargs["req"] is req


@pytest.mark.asyncio
async def test_model_error_is_502_retryable():
    with patch.object(fact_parse, "parse_owner_facts", AsyncMock(side_effect=RuntimeError("boom"))), \
            patch.object(fact_parse, "DbUsageSink", lambda pool: None), \
            patch.object(fact_parse, "DbRawResponseSink", lambda pool: None):
        with pytest.raises(ApiError) as e:
            await fact_parse.parse_card_text(
                "POOL", store_id=3, card_id=5, state=_state(), req=REQ)
    assert e.value.status_code == 502 and e.value.code == "FACT_PARSE_FAILED"
    assert e.value.retryable is True


@pytest.mark.asyncio
async def test_parse_card_text_mock_end_to_end_no_conn():
    with patch("app.config.get_settings", lambda: _Settings), \
            patch.object(fact_parse, "DbUsageSink", lambda pool: None), \
            patch.object(fact_parse, "DbRawResponseSink", lambda pool: None), \
            patch("app.ingest.extract.get_settings",
                  lambda: type("S", (), {"ingest_mode": "mock"})()):
        out = await fact_parse.parse_card_text(
            "POOL", store_id=3, card_id=5, state=_state(), req=FactParseRequest(text="ICE 물 20ml"))
    (p,) = out.proposals
    assert p.fact.value == "20" and p.fact.unit == "ml" and p.client_ref == "p1"


@pytest.mark.asyncio
async def test_gemini_parse_owner_facts_with_synthetic_call():
    """실제 경로 함수를 합성 _call 대역으로 직접 돌린다 — 프롬프트에 DB id 없음, 사용량 기록."""
    from types import SimpleNamespace as NS

    seen = {}

    async def fake_call(prompt, media, schema=None, max_output_tokens=None):
        seen["prompt"] = prompt
        seen["schema"] = schema
        body = FactExtractionResult(assertions=[_a("물 20ml", value="20", unit="ml")])
        return gemini.CallResult(body.model_dump_json(), {"prompt_tokens": 5}, "STOP")

    class Sink:
        def __init__(self):
            self.started, self.finalized = 0, 0

        async def start(self, attempt):
            self.started += 1
            return 1

        async def finalize(self, *a, **k):
            self.finalized += 1

    from app.contracts.usage import UsageContext
    ctx = UsageContext(store_id="3", cost_phase="OPERATING", stage="EXTRACT",
                       logical_call_id="card-parse:5:x")
    sink = Sink()
    settings = NS(gemini_api_key="synthetic", gemini_model="gemini-synthetic",
                  ingest_mode="real", extract_temperature=0.0, extract_locator_hints=False)
    with patch.object(gemini, "get_settings", lambda: settings), \
            patch.object(gemini, "_call", fake_call):
        out = await gemini.parse_owner_facts(payload=PAYLOAD, usage_sink=sink, usage_context=ctx)
    assert seen["schema"] is FactExtractionResult
    tail = seen["prompt"].split(gemini.PARSE_INPUT_MARKER + "\n", 1)[1]
    assert set(json.loads(tail)) == {"entity_name", "card_variants", "mode", "base_sentence", "text"}
    assert len(out.assertions) == 1
    assert sink.started == 1 and sink.finalized == 1
