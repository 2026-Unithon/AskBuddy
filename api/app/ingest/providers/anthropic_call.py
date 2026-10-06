"""Anthropic 원시 호출. 이미지(base64) + 지시문 → 구조화 출력(json_schema).

레이아웃 스키마는 모두 strict(extra=forbid, 기본값 없음)라 pydantic schema 를 그대로 쓴다.
temperature 는 보내지 않는다 — Sonnet 5.5 는 기본값이 아닌 sampling 값을 거절한다.
"""
import base64
import logging
from pathlib import Path

import anthropic

from app.config import get_settings
from app.ingest.providers.types import CallResult

logger = logging.getLogger(__name__)

_MEDIA = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}
_FINISH = {"end_turn": "STOP", "max_tokens": "MAX_TOKENS"}


def _client(api_key: str):
    return anthropic.AsyncAnthropic(api_key=api_key)


def _image_block(path: Path) -> dict:
    media_type = _MEDIA.get(path.suffix.lower())
    if media_type is None:
        raise ValueError(f"지원하지 않는 이미지 형식: {path.name}")
    data = base64.standard_b64encode(path.read_bytes()).decode("utf-8")
    return {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": data}}


def strict_schema(schema) -> dict:
    """Anthropic json_schema 용. 모든 object 에 additionalProperties:false 를 붙인 사본.

    스키마 모델 자체에는 넣지 않는다 — Gemini 가 그 키를 거절하기 때문이다.
    """
    def walk(node):
        if isinstance(node, dict):
            out = {k: walk(v) for k, v in node.items()}
            if out.get("type") == "object":
                out["additionalProperties"] = False
            return out
        if isinstance(node, list):
            return [walk(v) for v in node]
        return node
    return walk(schema.model_json_schema())


async def call(model: str, prompt: str, images: list[Path], schema,
               max_output_tokens: int | None) -> CallResult:
    s = get_settings()
    if not s.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY 가 없다")
    output_config: dict = {"format": {"type": "json_schema", "schema": strict_schema(schema)}}
    # Haiku 4.5 는 effort 를 받지 않는다
    if s.layout_anthropic_effort and not model.startswith("claude-haiku"):
        output_config["effort"] = s.layout_anthropic_effort
    resp = await _client(s.anthropic_api_key).messages.create(
        model=model,
        max_tokens=max_output_tokens or s.layout_max_output_tokens,
        messages=[{"role": "user",
                   "content": [*(_image_block(p) for p in images), {"type": "text", "text": prompt}]}],
        output_config=output_config,
    )
    if resp.stop_reason == "refusal":
        category = getattr(resp.stop_details, "category", None) if resp.stop_details else None
        raise RuntimeError(f"모델이 거절했다 category={category}")
    text = next((b.text for b in resp.content if b.type == "text"), "")
    u = resp.usage
    usage = {"prompt_tokens": int(u.input_tokens), "completion_tokens": int(u.output_tokens)}
    cached = getattr(u, "cache_read_input_tokens", None)
    if cached is not None:
        usage["cached_tokens"] = int(cached)
    usage["raw"] = u.model_dump()
    return CallResult(text, usage, _FINISH.get(resp.stop_reason, resp.stop_reason))
