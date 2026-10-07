"""공급자 계층 — 모델 지정 해석, Anthropic 응답 변환, 예산 상한, 계측 경로 공통화."""
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import BaseModel, ConfigDict

from app.ingest import providers
from app.ingest.providers import anthropic_call, budget
from app.ingest.providers.types import CallResult


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: str


def test_parse_model_spec():
    s = providers.parse_model_spec("anthropic:claude-sonnet-5-5")
    assert (s.provider, s.model) == ("anthropic", "claude-sonnet-5-5")
    with pytest.raises(ValueError):
        providers.parse_model_spec("claude-sonnet-5-5")
    with pytest.raises(ValueError):
        providers.parse_model_spec("openai:gpt")


def _resp(text, stop="end_turn"):
    usage = NS(input_tokens=11, output_tokens=7, cache_read_input_tokens=0,
               model_dump=lambda: {"input_tokens": 11, "output_tokens": 7})
    return NS(content=[NS(type="text", text=text)], stop_reason=stop,
              stop_details=None, usage=usage)


@pytest.mark.asyncio
async def test_anthropic_call_maps_usage_and_stop(tmp_path):
    img = tmp_path / "a.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n")
    fake = AsyncMock(return_value=_resp('{"value": "1"}', "max_tokens"))
    client = NS(messages=NS(create=fake))
    st = NS(anthropic_api_key="k", layout_anthropic_effort="low", layout_max_output_tokens=100)
    with patch.object(anthropic_call, "get_settings", return_value=st), \
         patch.object(anthropic_call, "_client", return_value=client):
        out = await anthropic_call.call("claude-sonnet-5-5", "p", [img], _Out, None)
    assert out.text == '{"value": "1"}'
    assert out.finish_reason == "MAX_TOKENS"
    assert out.usage["prompt_tokens"] == 11 and out.usage["completion_tokens"] == 7
    kwargs = fake.call_args.kwargs
    assert kwargs["output_config"]["effort"] == "low"
    assert kwargs["output_config"]["format"]["type"] == "json_schema"
    assert kwargs["messages"][0]["content"][0]["type"] == "image"


@pytest.mark.asyncio
async def test_anthropic_haiku_has_no_effort(tmp_path):
    fake = AsyncMock(return_value=_resp('{"value": "1"}'))
    st = NS(anthropic_api_key="k", layout_anthropic_effort="low", layout_max_output_tokens=100)
    with patch.object(anthropic_call, "get_settings", return_value=st), \
         patch.object(anthropic_call, "_client", return_value=NS(messages=NS(create=fake))):
        await anthropic_call.call("claude-haiku-4-5", "p", [], _Out, None)
    assert "effort" not in fake.call_args.kwargs["output_config"]


@pytest.mark.asyncio
async def test_anthropic_refusal_raises():
    fake = AsyncMock(return_value=_resp("", "refusal"))
    st = NS(anthropic_api_key="k", layout_anthropic_effort=None, layout_max_output_tokens=100)
    with patch.object(anthropic_call, "get_settings", return_value=st), \
         patch.object(anthropic_call, "_client", return_value=NS(messages=NS(create=fake))):
        with pytest.raises(RuntimeError, match="거절"):
            await anthropic_call.call("claude-sonnet-5-5", "p", [], _Out, None)


def test_budget_accumulates_and_blocks(monkeypatch):
    card = NS(model_rate=lambda m: {"input_per_1m": Decimal("2"), "output_per_1m": Decimal("10")}
              if m == "claude-sonnet-5-5" else {"input_per_1m": None, "output_per_1m": None})
    monkeypatch.setattr(budget, "load_rate_card", lambda: card)
    budget.set_limit(Decimal("0.00003"))
    budget.check_before_call()
    budget.add_usage("claude-sonnet-5-5", {"prompt_tokens": 10, "completion_tokens": 1})
    assert budget.spent() == Decimal("0.00003")
    with pytest.raises(budget.BudgetExceeded):
        budget.check_before_call()
    budget.add_usage("gemini-3.6-flash", {"prompt_tokens": 10})
    assert "gemini-3.6-flash" in budget.unpriced()
    budget.set_limit(None)
    budget.check_before_call()


@pytest.mark.asyncio
async def test_measured_generate_mock_mode_uses_builder():
    st = NS(ingest_mode="mock")
    with patch.object(providers, "get_settings", return_value=st):
        out = await providers.measured_generate(
            providers.parse_model_spec("anthropic:claude-sonnet-5-5"), "p", [], _Out,
            what="테스트", mock_build=lambda: _Out(value="m"))
    assert out.value == "m"


@pytest.mark.asyncio
async def test_measured_generate_real_parses_and_charges(monkeypatch):
    st = NS(ingest_mode="real")
    budget.set_limit(None)
    seen = {}
    async def fake_call(model, prompt, images, schema, max_output_tokens):
        seen["model"] = model
        return CallResult('{"value": "ok"}', {"prompt_tokens": 1, "completion_tokens": 1}, "STOP")
    monkeypatch.setattr(anthropic_call, "call", fake_call)
    with patch.object(providers, "get_settings", return_value=st):
        out = await providers.measured_generate(
            providers.parse_model_spec("anthropic:claude-sonnet-5-5"), "p", [], _Out, what="테스트")
    assert out.value == "ok" and seen["model"] == "claude-sonnet-5-5"


def test_layout_requires_anthropic_key():
    from app.config import Settings
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
        Settings(_env_file=None, ingest_mode="real", scan_extract_mode="LAYOUT", anthropic_api_key="")
    Settings(_env_file=None, ingest_mode="real", scan_extract_mode="SINGLE", anthropic_api_key="")


def test_layout_schemas_have_no_additional_properties_for_gemini():
    """Gemini response_schema 는 additionalProperties 를 거절한다(실호출 400) — 스키마 자체엔 없어야 한다."""
    from app.ingest.layout import schemas as ls

    def walk(node):
        if isinstance(node, dict):
            assert "additionalProperties" not in node
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
    for model in (ls.RegionMap, ls.BandRows, ls.ProseLines, ls.RecheckTurn, ls.ExpandResult):
        walk(model.model_json_schema())


def test_anthropic_schema_is_strict_everywhere():
    """Anthropic 으로 보낼 때만 모든 object 에 additionalProperties:false 를 붙인다."""
    from app.ingest.layout import schemas as ls
    out = anthropic_call.strict_schema(ls.RegionMap)
    objects = []

    def walk(node):
        if isinstance(node, dict):
            if node.get("type") == "object":
                objects.append(node)
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
    walk(out)
    assert objects and all(o.get("additionalProperties") is False for o in objects)
    # 원본 모델의 스키마는 바뀌지 않는다
    assert "additionalProperties" not in ls.RegionMap.model_json_schema()
