"""공급자 중립 계측 호출 — 원가 receipt · 원래 응답 기록 · 재사용 키 (W1-1·W1-3·CP-00B).

`gemini._measured_call` 에 있던 본문을 옮겼다. 모델 이름과 원시 호출만 바깥에서 받는다.
settings 는 호출부가 넘긴다(테스트 대역이 호출부 모듈의 get_settings 를 바꾼다).
"""
import logging
from pathlib import Path
from typing import Awaitable, Callable

from app.ingest import raw_responses
from app.ingest.providers.types import CallResult
from app.ingest.resilience import limited, transient, backoff, setting

logger = logging.getLogger(__name__)


@limited("ingest_model_concurrency")
async def measured_call(*, settings, model: str, caller: Callable[[], Awaitable[CallResult]],
                        prompt: str, media: list[Path], schema, sink, context,
                        prompt_hash: str | None, raw_sink, max_output_tokens: int | None,
                        thinking_level: str | None = None) -> CallResult:
    """계측을 감싼 호출. context 가 없으면 계측·원래 응답 기록 없이 그대로 부른다.

    원래 응답은 **호출이 끝나고 파싱하기 전에** 남긴다 (W1-1). 저장은 짧은 연결로 하고
    모델 호출 동안에는 연결을 쥐지 않는다. 저장이 실패하면 멈춘다 — 기록 없는 추출은
    되짚을 수 없다 (`RawResponseWriteError` 가 그대로 올라간다).
    """
    from app.ingest import reuse
    from app.usage import recorder

    s = settings
    # 재사용 키 (W1-3) — 기록할 곳이 있으면 언제나 계산해 남긴다. 조회는 플래그가 켜졌을 때만
    key = None
    if raw_sink is not None and context is not None:
        key = await reuse.key_for(context, s, model=model, mode=s.ingest_mode,
                                  prompt=prompt, media=media, schema=schema,
                                  max_output_tokens=max_output_tokens,
                                  thinking_level=thinking_level)
        if reuse.lookup_allowed(context, s):
            hit = await reuse.find(raw_sink, context, key, schema)
            if hit is not None:
                await _ledger_reuse(sink, context, s, model, prompt_hash, hit)
                return CallResult(hit.response_text, {}, hit.finish_reason,
                                  hit.raw_response_id, reused=True)
    from app.ingest.providers import budget
    retries = setting("ingest_stage_retries")
    for retry in range(retries + 1):
        budget.check_before_call()
        call_context = (context.model_copy(update={"attempt_no": context.attempt_no + retry})
                        if context is not None else None)
        # 저장 자체만 재시도한다. 공급자 오류만 다음 유료 시도로 간다.
        provider_error = None
        try:
            if call_context is None:
                try:
                    reply = await caller()
                except Exception as exc:
                    provider_error = exc
                    raise
            else:
                async with recorder.attempt(sink, call_context, model=model,
                                            mode=s.ingest_mode, prompt_hash=prompt_hash) as rec:
                    rec.measure_input(
                        input_bytes=len(prompt.encode("utf-8")) + sum(
                            m.stat().st_size for m in media if m.exists()),
                        frame_count=len(media) or None,
                    )
                    try:
                        reply = await caller()
                    except Exception as exc:
                        provider_error = exc
                        raise
                    rec.reported_model = model
                    if reply.usage:
                        rec.observe(**reply.usage)
                    else:
                        rec.partial("공급자가 usage 를 보고하지 않았다")
        except Exception as exc:
            if provider_error is None or not transient(exc) or retry == retries:
                raise
            await backoff(retry, stage="provider", exc=exc)
            continue
        budget.add_usage(model, reply.usage)
        break

    # 원가 receipt 를 확정한 뒤에 남긴다. 여기서 실패해도 호출 자체는 SUCCEEDED 다
    raw_id = await raw_responses.record(
        raw_sink, context, model=model, mode=s.ingest_mode,
        prompt_hash=prompt_hash, schema=schema, finish_reason=reply.finish_reason,
        response_text=reply.text, usage=reply.usage, reuse_key=key)
    return reply._replace(raw_response_id=raw_id)


async def _ledger_reuse(sink, context, s, model, prompt_hash, hit) -> None:
    """재사용을 원장에 남긴다 — 이번 실행의 논리 호출로, 비용 0(NOT_BILLABLE).

    원래 응답 행은 새로 만들지 않는다. 사유에 되쓴 행 ID 를 적어 어느 응답을 썼는지 잇는다.
    """
    from app.ingest.reuse import CACHE_STATE_REUSED
    from app.usage import recorder

    async with recorder.attempt(sink, context, model=model,
                                mode=s.ingest_mode, prompt_hash=prompt_hash) as rec:
        rec.not_billable(f"재사용: raw_response_id={hit.raw_response_id}")
        rec.cache_state = CACHE_STATE_REUSED
    logger.info("재사용 call=%s raw_response_id=%s — 모델을 부르지 않았다",
                context.logical_call_id, hit.raw_response_id)
