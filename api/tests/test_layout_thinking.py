"""레이아웃 Gemini 호출의 사고 수준 — 설정으로 낮추고, 재사용 키가 수준을 가른다."""
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import BaseModel

from app.ingest import providers, reuse
from app.ingest.extract import gemini
from app.ingest.providers import budget
from app.ingest.providers.types import CallResult


class _Out(BaseModel):
    value: str


def _gst(**kw):
    return NS(**({"gemini_api_key": "k", "gemini_model": "gemini-x", "ingest_mode": "real",
                  "extract_temperature": 0.0, "gemini_request_timeout_sec": 300} | kw))


async def _call_config(thinking_level):
    res = NS(text="{}", usage_metadata=None, candidates=[])
    gen = AsyncMock(return_value=res)
    client = NS(aio=NS(models=NS(generate_content=gen)))
    with patch.object(gemini, "get_settings", return_value=_gst()), \
         patch("google.genai.Client", return_value=client):
        await gemini._call("p", [], _Out, thinking_level=thinking_level)
    return gen.call_args.kwargs["config"]


@pytest.mark.asyncio
async def test_call_sets_thinking_level_when_given():
    config = await _call_config("LOW")
    assert str(config.thinking_config.thinking_level).upper().endswith("LOW")


@pytest.mark.asyncio
async def test_call_leaves_thinking_default_when_none():
    config = await _call_config(None)
    assert config.thinking_config is None


@pytest.mark.asyncio
async def test_layout_gemini_calls_pass_setting(monkeypatch):
    seen = {}

    async def fake_call(prompt, media, schema, max_output_tokens=None, model=None, thinking_level=None):
        seen["level"], seen["model"] = thinking_level, model
        return CallResult('{"value": "ok"}', {"prompt_tokens": 1, "completion_tokens": 1}, "STOP")
    monkeypatch.setattr(gemini, "_call", fake_call)
    budget.set_limit(None)
    st = NS(ingest_mode="real", layout_gemini_thinking_level="MINIMAL")
    with patch.object(providers, "get_settings", return_value=st):
        out = await providers.measured_generate(
            providers.parse_model_spec("gemini:gemini-3.8-flash"), "p", [], _Out, what="테스트")
    assert out.value == "ok" and seen == {"level": "MINIMAL", "model": "gemini-3.8-flash"}


def test_reuse_key_separates_thinking_level_only_when_set():
    base = dict(store_id=1, source_id=2, stage="EXTRACT", model="m", mode="real", prompt="p",
                media_digests=[], schema_version="v", temperature=0.0, max_output_tokens=None,
                pdf_input_mode=None, video_input_mode=None)
    plain = reuse.reuse_key(**base)
    assert reuse.reuse_key(**base, thinking_level=None) == plain       # 기존 키 불변
    low = reuse.reuse_key(**base, thinking_level="LOW")
    assert low != plain and low != reuse.reuse_key(**base, thinking_level="HIGH")
