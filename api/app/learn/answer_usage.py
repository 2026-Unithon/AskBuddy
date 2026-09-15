"""R 답변 호출의 공통 원장 adapter. 질문/근거/응답 본문은 원장에 복제하지 않는다."""
from contextlib import asynccontextmanager

from app.contracts.usage import UsageContext
from app.usage.recorder import NullSink, UsageSink, attempt


class AnswerUsageStartError(RuntimeError):
    """호출 전 계측 실패. 답변 폴백으로 삼키거나 모델을 재호출하지 않는다."""


def checked_context(context: UsageContext | None, sink: UsageSink | None):
    if context is None and sink is None:
        return None
    if context is None or sink is None or isinstance(sink, NullSink):
        raise ValueError("답변 계측에는 trusted context와 저장 sink가 함께 필요하다")
    context = UsageContext.model_validate(context.model_dump())
    if context.stage != "ANSWER":
        raise ValueError("답변 호출의 usage stage는 ANSWER여야 한다")
    return context


@asynccontextmanager
async def answer_attempt(sink, context, *, model, prompt_hash):
    if context is None:
        yield None
        return
    # __aenter__의 오류만 구분한다. 공급자 오류는 공통 recorder가 FAILED로 기록한다.
    manager = attempt(sink, context, model=model, prompt_hash=prompt_hash)
    try:
        recording = await manager.__aenter__()
    except Exception as exc:
        raise AnswerUsageStartError("답변 호출 전 usage 기록 실패") from exc
    try:
        yield recording
    except BaseException as exc:
        await manager.__aexit__(type(exc), exc, exc.__traceback__)
        raise
    else:
        await manager.__aexit__(None, None, None)


def observe_answer(recording, response):
    if recording is None:
        return
    recording.reported_model = getattr(response, "model_version", None)
    recording.provider_request_id = getattr(response, "response_id", None)
    meta = getattr(response, "usage_metadata", None)
    if meta is None:
        recording.observe()
        return
    raw = meta.model_dump(mode="json") if hasattr(meta, "model_dump") else vars(meta).copy()
    def tokens(name):
        value = raw.get(name)
        return value if type(value) is int and value >= 0 else None
    recording.observe(prompt_tokens=tokens("prompt_token_count"),
                      completion_tokens=tokens("candidates_token_count"), raw=raw)
    if recording.usage.is_empty():
        return
    if tokens("prompt_token_count") is None or tokens("candidates_token_count") is None:
        recording.partial("입력 또는 출력 token 관측 누락")
    # 공통 요율 adapter가 포함/중복 관계를 확정하기 전에는 추가 항목을 합산하지 않는다.
    # 원형은 남겨 후속 report에서 다시 해석하며 완전 원가 판정을 막는다.
    if any(value not in (None, 0, [], {}) for key, value in raw.items()
           if key not in {"prompt_token_count", "candidates_token_count", "total_token_count"}):
        recording.partial("추가 공급자 usage의 과금 포함 관계 확인 필요")
