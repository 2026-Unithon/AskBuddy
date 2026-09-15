"""호출부에 붙이는 계측 (CP-00B).

순수 함수(extract·audio)에 DB 를 끌고 들어가지 않는다. 호출부는 `UsageSink` 만 받고,
실제 저장은 pipeline 이 만든 `DbUsageSink` 가 한다. sink 가 없으면 계측 없이 그냥 돈다 —
기존 호출 계약을 깨지 않는다.

    async with recorder.attempt(ctx, model="gemini-3.6-flash") as rec:
        res = await client.generate_content(...)
        rec.observe(prompt_tokens=..., completion_tokens=...)
"""
from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Protocol

from app.contracts.usage import (
    InputScale,
    ModelUsage,
    UsageAttempt,
    UsageContext,
    UsageStatus,
)
from app.usage.pricing import price_attempt
from app.usage.rates import load_rate_card

logger = logging.getLogger(__name__)


class UsageSink(Protocol):
    async def start(self, attempt: UsageAttempt) -> int: ...
    async def finalize(self, attempt_id: int, attempt: UsageAttempt,
                       known_cost: Decimal | None, cost: Decimal | None,
                       price_status: str) -> None: ...


class NullSink:
    """계측하지 않는다. 기존 호출 경로가 그대로 돌게 하는 기본값."""

    async def start(self, attempt: UsageAttempt) -> int:
        return 0

    async def finalize(self, *args, **kwargs) -> None:
        return None


class DbUsageSink:
    """원장에 쓴다. pool 을 잠깐씩만 빌린다."""

    def __init__(self, pool) -> None:
        self._pool = pool

    async def start(self, attempt: UsageAttempt) -> int:
        from app.usage.repository import start_attempt
        return await start_attempt(self._pool, attempt)

    async def finalize(self, attempt_id: int, attempt: UsageAttempt,
                       known_cost, cost, price_status) -> None:
        from app.usage.repository import finalize_attempt
        await finalize_attempt(self._pool, attempt_id, attempt,
                               known_cost=known_cost, cost=cost,
                               price_status=price_status)


class _Recording:
    """호출 한 번의 관측값을 모은다."""

    def __init__(self) -> None:
        self.usage = ModelUsage()
        self.scale = InputScale()
        self.usage_status: UsageStatus = "UNKNOWN"
        self.missing_reason: str | None = None
        self.reported_model: str | None = None
        self.provider_request_id: str | None = None
        self.cache_state: str | None = None

    def observe(self, *, prompt_tokens: int | None = None,
                completion_tokens: int | None = None,
                cached_tokens: int | None = None,
                thought_tokens: int | None = None,
                billable_units: Decimal | None = None,
                billable_unit_name: str | None = None,
                raw: dict[str, Any] | None = None) -> None:
        """공급자가 보고한 값을 담는다. **못 받은 값은 넘기지 않는다** — 0 으로 채우지 않는다."""
        self.usage = ModelUsage(
            prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
            cached_tokens=cached_tokens, thought_tokens=thought_tokens,
            billable_units=billable_units, billable_unit_name=billable_unit_name,
            raw=raw,
        )
        self.usage_status = "UNKNOWN" if self.usage.is_empty() else "COMPLETE"
        if self.usage.is_empty():
            self.missing_reason = "공급자가 usage 를 보고하지 않았다"

    def partial(self, reason: str) -> None:
        """일부만 받았다. known_cost 로만 더해진다."""
        self.usage_status = "PARTIAL"
        self.missing_reason = reason

    def not_billable(self, reason: str = "mock 모드") -> None:
        self.usage = ModelUsage()
        self.usage_status = "NOT_BILLABLE"
        self.missing_reason = reason

    def measure_input(self, **kw) -> None:
        self.scale = InputScale(**kw)


@asynccontextmanager
async def attempt(
    sink: UsageSink | None, context: UsageContext, *,
    model: str, mode: str = "real",
    prompt_hash: str | None = None, config_hash: str | None = None,
):
    """유료 호출 한 번을 감싼다.

    시작 receipt 를 먼저 남긴다 — 프로세스가 죽어도 "돈은 나갔는데 기록이 없는" 구멍을 막는다.
    시작 저장이 실패하면 **호출하기 전에** 예외가 올라간다. 계측 없이 돈을 쓰지 않는다.
    """
    sink = sink or NullSink()
    card = load_rate_card()
    base = UsageAttempt(
        context=context, requested_model=model, mode=mode,
        prompt_hash=prompt_hash, config_hash=config_hash,
        rate_card_version=card.version,
        started_at=datetime.now(timezone.utc),
    )
    attempt_id = await sink.start(base)

    rec = _Recording()
    started = time.perf_counter()
    error_code: str | None = None
    status = "SUCCEEDED"
    try:
        yield rec
    except BaseException as exc:
        status = "FAILED"
        error_code = type(exc).__name__
        # 실패해도 과금될 수 있다. 기록은 남긴다
        raise
    finally:
        final = base.model_copy(update={
            "status": status,
            "reported_model": rec.reported_model,
            "provider_request_id": rec.provider_request_id,
            "cache_state": rec.cache_state,
            "finished_at": datetime.now(timezone.utc),
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "error_code": error_code,
            "usage": rec.usage,
            "scale": rec.scale,
            "usage_status": rec.usage_status,
            "missing_reason": rec.missing_reason,
        })
        known, cost, price_status = price_attempt(final, card)
        try:
            await sink.finalize(attempt_id, final, known, cost, price_status)
        except Exception as exc:
            logger.error("원가 기록 확정 실패: %s", exc)
