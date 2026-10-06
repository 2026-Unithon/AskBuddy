"""역할별 모델 호출. `공급자:모델` 지정을 해석해 같은 계측 경로로 부른다."""
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal

from pydantic import BaseModel

from app.config import get_settings
from app.ingest import raw_responses
from app.ingest.providers import anthropic_call, budget, measured

_PROVIDERS = ("gemini", "anthropic")


@dataclass(frozen=True)
class ModelSpec:
    provider: Literal["gemini", "anthropic"]
    model: str


def parse_model_spec(text: str) -> ModelSpec:
    provider, sep, model = (text or "").partition(":")
    if not sep or not model or provider not in _PROVIDERS:
        raise ValueError(f"모델 지정은 '공급자:모델' 이고 공급자는 {_PROVIDERS} 중 하나다: {text!r}")
    return ModelSpec(provider, model)  # type: ignore[arg-type]


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


async def measured_generate(spec: ModelSpec, prompt: str, images: list[Path], schema: type[BaseModel],
                            *, usage_sink=None, usage_context=None, raw_sink=None,
                            max_output_tokens: int | None = None, what: str,
                            mock_build: Callable[[], BaseModel] | None = None) -> BaseModel:
    """한 번 부르고 스키마로 검증해 돌려준다. 잘림·파싱 실패는 예외다(raw_responses 규칙)."""
    s = get_settings()
    if s.ingest_mode == "mock":
        if mock_build is None:
            raise RuntimeError(f"{what}: mock 모드인데 합성 결과가 없다")
        from app.ingest.extract import mock
        return await mock._as_recorded(mock_build, schema, raw_sink=raw_sink,
                                       usage_context=usage_context, prompt=prompt, media=images)

    budget.check_before_call()
    # 레이아웃 Gemini 호출의 사고 수준(None 이면 모델 기본). 재사용 키도 이 값으로 갈린다
    thinking = getattr(s, "layout_gemini_thinking_level", None) if spec.provider == "gemini" else None
    if spec.provider == "gemini":
        from app.ingest.extract import gemini

        async def caller():
            return await gemini._call(prompt, images, schema,
                                      max_output_tokens=max_output_tokens, model=spec.model,
                                      thinking_level=thinking)
    else:
        async def caller():
            return await anthropic_call.call(spec.model, prompt, images, schema, max_output_tokens)

    reply = await measured.measured_call(
        settings=s, model=spec.model, caller=caller, prompt=prompt, media=images, schema=schema,
        sink=usage_sink, context=usage_context, prompt_hash=_hash(prompt), raw_sink=raw_sink,
        max_output_tokens=max_output_tokens, thinking_level=thinking)
    if not reply.reused:
        budget.add_usage(spec.model, reply.usage)
    sink = None if reply.reused else raw_sink
    return await raw_responses.parse_checked(
        sink, usage_context, reply.raw_response_id, reply.finish_reason,
        lambda: schema.model_validate_json(reply.text), what=what)
