"""관호 — OpenAI 임베딩 (D4 고정). ingest 도 이 모듈을 호출한다."""
from __future__ import annotations

import hashlib
import asyncio
import json
import logging
import time

from openai import OpenAI

from app.config import get_settings
from app.contracts.usage import UsageContext
from app.usage import UsageSink, NullSink, attempt
from app.team.evaluation_budget import BudgetDenied, provider_budget

logger = logging.getLogger(__name__)


def embed_texts(texts: list[str], *, recording=None, timeout_seconds: float | None = None) -> list[list[float]]:
    """text-embedding-3-small / 1536. 빈 입력이면 빈 리스트."""
    if not texts:
        return []
    s = get_settings()
    if not s.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY 가 비어 있다")
    timeout = s.embedding_timeout_seconds if timeout_seconds is None else timeout_seconds
    if not 0 < timeout <= 30:
        raise ValueError("embedding timeout must be between 0 and 30 seconds")
    client = OpenAI(api_key=s.openai_api_key, max_retries=0, timeout=timeout)
    t0 = time.perf_counter()
    try:
        resp = client.embeddings.create(model=s.embedding_model, input=texts)
    finally:
        try:
            client.close()
        except Exception as exc:
            # 정리 오류로 이미 수신한 응답/usage 또는 원래 공급자 오류를 덮지 않는다.
            logger.warning("embedding client cleanup failed type=%s", type(exc).__name__)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    usage = getattr(resp, "usage", None)
    if recording is not None:
        raw = usage.model_dump(mode="json") if hasattr(usage, "model_dump") else (vars(usage).copy() if usage else None)
        prompt = getattr(usage, "prompt_tokens", None)
        prompt = prompt if type(prompt) is int and prompt >= 0 else None
        recording.reported_model = getattr(resp, "model", None)
        recording.provider_request_id = getattr(resp, "_request_id", None)
        recording.observe(prompt_tokens=prompt, raw=raw)
        if prompt is not None and raw and any(v not in (None, 0, {}, []) for k, v in raw.items()
                                              if k not in ("prompt_tokens", "total_tokens")):
            recording.partial("추가 임베딩 과금 항목 확인 필요")
    tokens = getattr(usage, "total_tokens", None) if usage else None
    logger.info(
        "embedding model=%s n=%s tokens=%s elapsed_ms=%.1f",
        s.embedding_model,
        len(texts),
        tokens,
        elapsed_ms,
    )
    by_idx = {item.index: item.embedding for item in resp.data}
    if len(resp.data) != len(texts) or set(by_idx) != set(range(len(texts))):
        raise RuntimeError("embedding response indices mismatch")
    vectors = [by_idx[i] for i in range(len(texts))]
    dim = s.embedding_dim
    for v in vectors:
        if len(v) != dim:
            raise RuntimeError(f"embedding dim {len(v)} != {dim}")
    return vectors


async def recorded_embeddings(texts: list[str], *, context: UsageContext, sink: UsageSink):
    """비동기 계측 adapter. 공급자 호출은 기존 embed_texts 한 곳에서만 수행한다."""
    context = UsageContext.model_validate(context.model_dump())
    if context.stage not in ("EMBED", "QUERY") or sink is None or isinstance(sink, NullSink):
        raise ValueError("임베딩에는 EMBED/QUERY context와 저장 sink가 필요하다")
    if not texts:
        return []
    context, budget = provider_budget(context,get_settings().embedding_model)
    if not get_settings().openai_api_key:
        raise RuntimeError("OPENAI_API_KEY 가 비어 있다")
    payload = json.dumps(texts, ensure_ascii=False, separators=(",", ":"))
    size = sum(len(t.encode('utf-8')) for t in texts)
    reservation = None
    rec = None
    if budget is not None:
        # D4's fixed model uses byte BPE: UTF-8 bytes bound input tokens from above.
        # Do not silently generalize this bound to another tokenizer/model.
        if (get_settings().embedding_model != 'text-embedding-3-small'
                or size > min(budget.policy.max_input_tokens,budget.policy.max_prompt_bytes)):
            raise BudgetDenied('embedding model or conservative byte/token bound not approved')
        reservation = await budget.reserve(context,get_settings().embedding_model)
    try:
        async with attempt(sink, context, model=get_settings().embedding_model,
                           prompt_hash="sha256:" + content_hash(payload)) as rec:
            rec.measure_input(input_bytes=size)
            settings = get_settings()
            # W 등록 준비와 R 질문 검색의 시간 예산을 섞지 않는다.
            timeout = settings.query_embedding_timeout_seconds if context.stage == "QUERY" else settings.embedding_timeout_seconds
            return await asyncio.to_thread(embed_texts, texts, recording=rec, timeout_seconds=timeout)
    finally:
        if reservation is not None:
            await asyncio.wait_for(budget.finish(reservation,
                input_tokens=rec.usage.prompt_tokens if rec is not None and rec.usage_status=='COMPLETE' else None,
                output_tokens=0),.2)


def embed_text(text: str) -> list[float]:
    return embed_texts([text])[0]


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def vector_literal(embedding: list[float]) -> str:
    return "[" + ",".join(f"{x:.8f}" for x in embedding) + "]"
