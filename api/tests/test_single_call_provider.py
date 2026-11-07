"""한 번 호출 추출 — Anthropic 추출 통로(call_extract): PDF·이미지 블록, 스트리밍, effort, 종료 사유."""
import asyncio
from types import SimpleNamespace as NS
from unittest.mock import patch

import pytest
from pydantic import BaseModel

from app.ingest.providers import anthropic_call


class _Out(BaseModel):
    x: int


def _final(text='{"x": 1}', stop="end_turn"):
    return NS(stop_reason=stop, stop_details=None,
              content=[NS(type="thinking", thinking=""), NS(type="text", text=text)],
              usage=NS(input_tokens=10, output_tokens=5, cache_read_input_tokens=0,
                       model_dump=lambda: {"input_tokens": 10, "output_tokens": 5}))


class _Stream:
    def __init__(self, final, seen, kwargs):
        self.final, self.seen, self.kwargs = final, seen, kwargs

    async def __aenter__(self):
        self.seen.append(self.kwargs)
        return self

    async def __aexit__(self, *a):
        return False

    async def get_final_message(self):
        return self.final


def _client(final, seen):
    return NS(messages=NS(stream=lambda **kw: _Stream(final, seen, kw)))


def _settings():
    return NS(anthropic_api_key="k", gemini_request_timeout_sec=300)


def _run(coro):
    return asyncio.run(coro)


def test_pdf_and_image_become_document_and_image_blocks(tmp_path):
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF-1.4 x")
    img = tmp_path / "b.jpg"
    img.write_bytes(b"\xff\xd8x")
    seen = []
    with patch.object(anthropic_call, "get_settings", return_value=_settings()), \
         patch.object(anthropic_call, "_client", return_value=_client(_final(), seen)):
        _run(anthropic_call.call_extract("claude-sonnet-5-5", "p", [pdf, img], _Out,
                                         effort="high", max_tokens=64000))
    content = seen[0]["messages"][0]["content"]
    assert [b["type"] for b in content] == ["document", "image", "text"]
    assert content[0]["source"]["media_type"] == "application/pdf"
    assert content[1]["source"]["media_type"] == "image/jpeg"
    assert content[2]["text"] == "p"


def test_effort_max_tokens_and_schema_are_sent():
    seen = []
    with patch.object(anthropic_call, "get_settings", return_value=_settings()), \
         patch.object(anthropic_call, "_client", return_value=_client(_final(), seen)):
        out = _run(anthropic_call.call_extract("claude-sonnet-5-5", "p", [], _Out,
                                               effort="high", max_tokens=64000))
    kw = seen[0]
    assert kw["max_tokens"] == 64000
    assert kw["output_config"]["effort"] == "high"
    assert kw["output_config"]["format"]["schema"]["additionalProperties"] is False
    # Sonnet 5.5 는 기본값이 아닌 sampling 값을 거절한다 — temperature 를 보내지 않는다
    assert "temperature" not in kw
    assert out.text == '{"x": 1}' and out.finish_reason == "STOP"
    assert out.usage["prompt_tokens"] == 10 and out.usage["completion_tokens"] == 5


def test_max_tokens_stop_maps_to_truncated():
    with patch.object(anthropic_call, "get_settings", return_value=_settings()), \
         patch.object(anthropic_call, "_client", return_value=_client(_final(stop="max_tokens"), [])):
        out = _run(anthropic_call.call_extract("claude-sonnet-5-5", "p", [], _Out,
                                               effort="high", max_tokens=10))
    assert out.finish_reason == "MAX_TOKENS"


def test_refusal_raises():
    final = _final(stop="refusal")
    final.stop_details = NS(category="cyber")
    with patch.object(anthropic_call, "get_settings", return_value=_settings()), \
         patch.object(anthropic_call, "_client", return_value=_client(final, [])):
        with pytest.raises(RuntimeError, match="거절"):
            _run(anthropic_call.call_extract("claude-sonnet-5-5", "p", [], _Out,
                                             effort="high", max_tokens=10))


def test_unsupported_media_raises(tmp_path):
    bad = tmp_path / "a.mp4"
    bad.write_bytes(b"x")
    with patch.object(anthropic_call, "get_settings", return_value=_settings()):
        with pytest.raises(ValueError, match="지원하지 않는"):
            _run(anthropic_call.call_extract("claude-sonnet-5-5", "p", [bad], _Out,
                                             effort="high", max_tokens=10))


def test_fact_schema_sent_without_numeric_bounds():
    """2026-11-07 회귀 — 숫자 칸의 minimum/maximum 을 보내면 API 가 400 으로 거절한다."""
    import json
    from app.ingest.schemas import SingleCallExtractionResult
    seen = []
    with patch.object(anthropic_call, "get_settings", return_value=_settings()), \
         patch.object(anthropic_call, "_client", return_value=_client(_final('{"assertions": []}'), seen)):
        _run(anthropic_call.call_extract("claude-sonnet-5-5", "p", [], SingleCallExtractionResult,
                                         effort="high", max_tokens=100))
    sent = json.dumps(seen[0]["output_config"]["format"]["schema"])
    assert '"minimum"' not in sent and '"maximum"' not in sent
    assert '"additionalProperties": false' in sent
