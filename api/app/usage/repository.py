"""원가 원장 저장 (CP-00B).

계약이 요구하는 것 둘:
  - **모델 호출 동안 DB connection/lock 을 잡지 않는다.** 풀에서 잠깐 빌려 쓰고 돌려준다.
    38분 영상 추출이 10분 걸리는데 그동안 연결을 붙들면 풀이 마른다.
  - **계측 실패로 유료 호출을 반복하지 않는다.** 시작 receipt 저장이 실패하면
    호출하기 전에 멈춘다. 응답 뒤 저장이 실패하면 DB 저장만 재시도하고
    공급자를 다시 부르지 않는다 — 돈은 이미 나갔다.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import asyncpg

from app.contracts.usage import UsageAttempt

logger = logging.getLogger(__name__)


class UsageWriteError(RuntimeError):
    """계측 저장 실패. 유료 호출 전이면 호출을 멈춘다."""


async def start_attempt(pool: asyncpg.Pool, attempt: UsageAttempt) -> int:
    """호출 전에 STARTED 로 먼저 남긴다.

    먼저 남겨야 프로세스가 죽어도 "돈은 나갔는데 기록이 없는" 구멍이 안 생긴다.
    """
    c = attempt.context
    try:
        async with pool.acquire() as conn:
            return int(await conn.fetchval(
                """
                insert into ai_usage_attempts (
                  store_id, cost_phase, cost_purpose, stage,
                  logical_call_id, attempt_no,
                  registration_campaign_id, operation_id,
                  job_id, source_id, segment_id, question_id,
                  extraction_run_id, evaluation_run_id,
                  status, requested_model, mode,
                  prompt_hash, config_hash, rate_card_version, started_at
                )
                values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,
                        'STARTED',$15,$16,$17,$18,$19, now())
                returning usage_attempt_id
                """,
                int(c.store_id), c.cost_phase, c.cost_purpose, c.stage,
                c.logical_call_id, c.attempt_no,
                c.registration_campaign_id, c.operation_id,
                _maybe_int(c.job_id), _maybe_int(c.source_id), c.segment_id,
                _maybe_int(c.question_id), _maybe_int(c.extraction_run_id),
                _maybe_int(c.evaluation_run_id),
                attempt.requested_model, attempt.mode,
                attempt.prompt_hash, attempt.config_hash, attempt.rate_card_version,
            ))
    except asyncpg.UniqueViolationError:
        # 같은 논리 호출의 같은 시도가 이미 있다. 중복 호출을 막는 게 이 제약의 목적이다
        raise UsageWriteError(
            f"이미 기록된 시도다 (call={c.logical_call_id} attempt={c.attempt_no})")
    except Exception as exc:
        raise UsageWriteError(f"시작 receipt 저장 실패: {exc}") from exc


async def finalize_attempt(
    pool: asyncpg.Pool, usage_attempt_id: int, attempt: UsageAttempt,
    *, known_cost: Decimal | None, cost: Decimal | None, price_status: str,
) -> None:
    """응답이나 실패를 확정한다.

    여기서 실패해도 공급자를 다시 부르지 않는다. 돈은 이미 나갔고, 다시 부르면 두 번 낸다.
    저장만 재시도하고 끝내 안 되면 STARTED 로 남아 UNKNOWN 으로 집계된다.
    """
    u, s = attempt.usage, attempt.scale
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                update ai_usage_attempts set
                  status=$2, reported_model=$3, provider_request_id=$4,
                  finished_at=$5, latency_ms=$6, error_code=$7, cache_state=$8,
                  prompt_tokens=$9, completion_tokens=$10, cached_tokens=$11,
                  thought_tokens=$12, billable_units=$13, billable_unit_name=$14,
                  raw_usage=$15::jsonb,
                  input_bytes=$16, media_duration_sec=$17, page_count=$18, frame_count=$19,
                  usage_status=$20, missing_reason=$21,
                  known_cost_usd=$22, cost_usd=$23, price_status=$24
                where usage_attempt_id=$1
                """,
                usage_attempt_id, attempt.status, attempt.reported_model,
                attempt.provider_request_id,
                attempt.finished_at or datetime.now(timezone.utc),
                attempt.latency_ms, attempt.error_code, attempt.cache_state,
                u.prompt_tokens, u.completion_tokens, u.cached_tokens,
                u.thought_tokens, u.billable_units, u.billable_unit_name,
                json.dumps(u.raw, ensure_ascii=False) if u.raw else None,
                s.input_bytes, s.media_duration_sec, s.page_count, s.frame_count,
                attempt.usage_status, attempt.missing_reason,
                known_cost, cost, price_status,
            )
    except Exception as exc:
        # 돈은 이미 나갔다. 기록만 잃는다 — STARTED 로 남아 UNKNOWN 으로 집계된다
        logger.error("원가 기록 확정 실패 id=%s: %s", usage_attempt_id, exc)


async def rollup_extraction_run(
    pool: asyncpg.Pool, store_id: int, extraction_run_id: int
) -> dict[str, Any]:
    """원장에서 실행 단위 summary 를 만든다.

    부분 관측은 known_cost 로만 더하고, 하나라도 미확정이면 총액은 null 이다.
    """
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            select
              count(*)                                            as attempts,
              count(*) filter (where attempt_no > 1)               as retries,
              count(*) filter (where usage_status = 'UNKNOWN')     as unknown,
              sum(prompt_tokens)                                   as prompt_tokens,
              sum(completion_tokens)                               as completion_tokens,
              sum(input_bytes)                                     as submitted_bytes,
              sum(media_duration_sec)                              as media_sec,
              sum(page_count)                                      as pages,
              sum(known_cost_usd)                                  as known_cost,
              bool_and(usage_status in ('COMPLETE','NOT_BILLABLE')) as all_observed,
              sum(cost_usd)                                        as cost
            from ai_usage_attempts
            where store_id = $1 and extraction_run_id = $2
            """,
            store_id, extraction_run_id,
        )
        attempts = int(row["attempts"] or 0)
        all_observed = bool(row["all_observed"]) if attempts else False
        summary = {
            "ai_attempt_count": attempts,
            "retry_count": int(row["retries"] or 0),
            "unknown_attempt_count": int(row["unknown"] or 0),
            "prompt_tokens": row["prompt_tokens"],
            "completion_tokens": row["completion_tokens"],
            "submitted_input_bytes": row["submitted_bytes"],
            "media_duration_sec": row["media_sec"],
            "document_pages": row["pages"],
            "known_cost_usd": row["known_cost"],
            # 하나라도 못 재면 총액을 주장하지 않는다
            "cost_usd": row["cost"] if all_observed else None,
            "cost_status": ("COMPLETE" if all_observed
                            else "UNKNOWN" if attempts == int(row["unknown"] or 0)
                            else "PARTIAL"),
        }
        await conn.execute(
            """
            update extraction_runs set
              ai_attempt_count=$3, retry_count=$4, unknown_attempt_count=$5,
              prompt_tokens=$6, completion_tokens=$7, submitted_input_bytes=$8,
              media_duration_sec=$9, document_pages=$10,
              known_cost_usd=$11, cost_usd=$12, cost_status=$13
            where run_id=$2 and store_id=$1
            """,
            store_id, extraction_run_id,
            summary["ai_attempt_count"], summary["retry_count"],
            summary["unknown_attempt_count"], summary["prompt_tokens"],
            summary["completion_tokens"], summary["submitted_input_bytes"],
            summary["media_duration_sec"], summary["document_pages"],
            summary["known_cost_usd"], summary["cost_usd"], summary["cost_status"],
        )
    return summary


def _maybe_int(value: str | None) -> int | None:
    return int(value) if value is not None else None
