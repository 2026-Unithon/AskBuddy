"""W 분류/관계의 Gemini 단일 시도 계측. 본문은 해시/bytes만 남긴다."""
import hashlib
import json
import logging

from app.contracts.usage import UsageContext
from app.usage.recorder import NullSink, attempt

logger = logging.getLogger(__name__)


class UsageStartError(RuntimeError):
    """유료 호출 전 원장 시작 저장 실패. 비즈니스 폴백으로 숨기지 않는다."""


def checked_context(context, sink, stage, *, store_id=None):
    if context is None or sink is None or isinstance(sink, NullSink):
        raise ValueError("유료 분류/관계에는 trusted usage context와 저장 sink가 필요하다")
    context = UsageContext.model_validate(context.model_dump())
    if context.stage != stage or (store_id is not None and context.store_id != str(store_id)):
        raise ValueError("usage stage 또는 매장 귀속 불일치")
    return context


def _hash(value):
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def observe(recording, response):
    recording.reported_model = getattr(response, "model_version", None)
    recording.provider_request_id = getattr(response, "response_id", None)
    meta = getattr(response, "usage_metadata", None)
    raw = (meta.model_dump(mode="json") if hasattr(meta, "model_dump")
           else vars(meta).copy() if meta is not None else {})
    def token(name):
        value = raw.get(name)
        return value if type(value) is int and value >= 0 else None
    recording.observe(prompt_tokens=token("prompt_token_count"),
        completion_tokens=token("candidates_token_count"),
        cached_tokens=token("cached_content_token_count"),
        thought_tokens=token("thoughts_token_count"), raw=raw)
    if recording.usage.is_empty():
        return
    if token("prompt_token_count") is None or token("candidates_token_count") is None:
        recording.partial("입력 또는 출력 token 관측 누락")
    if any(value not in (None, 0, [], {}) for key, value in raw.items()
           if key not in {"prompt_token_count", "candidates_token_count", "total_token_count"}):
        recording.partial("추가 공급자 usage의 과금 포함 관계 확인 필요")


async def recorded_generate(prompt, schema, settings, *, context, sink):
    from google import genai
    from google.genai import types

    config = json.dumps(dict(model=settings.gemini_model, temperature=0.0,
        schema=schema.model_json_schema(), retry_attempts=1, timeout_ms=30000), sort_keys=True)
    manager = attempt(sink, context, model=settings.gemini_model,
                      prompt_hash=_hash(prompt), config_hash=_hash(config))
    try:
        recording = await manager.__aenter__()
    except Exception as exc:
        raise UsageStartError("분류/관계 호출 전 usage 기록 실패") from exc
    client = None
    try:
        recording.measure_input(input_bytes=len(prompt.encode("utf-8")))
        # SDK 숨은 재시도는 끈다. 업무 재시도는 별도 context/receipt로 호출한다.
        client = genai.Client(api_key=settings.gemini_api_key,
            http_options=types.HttpOptions(timeout=30000,
                retry_options=types.HttpRetryOptions(attempts=1)))
        response = await client.aio.models.generate_content(model=settings.gemini_model,
            contents=prompt, config=types.GenerateContentConfig(response_mime_type="application/json",
                response_schema=schema, temperature=0.0))
        observe(recording, response)
        # parsing 실패도 받은 usage를 보존한 FAILED receipt로 끝낸다.
        result = schema.model_validate_json(response.text or "")
    except BaseException as exc:
        await manager.__aexit__(type(exc), exc, exc.__traceback__)
        raise
    else:
        await manager.__aexit__(None, None, None)
        return result
    finally:
        if client is not None:
            try:
                await client.aio.aclose()
                client.close()
            except Exception as exc:
                logger.warning("Gemini client cleanup failed type=%s", type(exc).__name__)
