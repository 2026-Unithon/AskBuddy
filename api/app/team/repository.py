"""평가 하네스 DB 접근. 모든 함수가 store_id 를 필수 인자로 받는다 (D1)."""
from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from typing import Any

import asyncpg

_CASE_COLUMNS = """
  case_id, store_id, case_key, question, expected_kind,
  expected_card_ids, expected_facts, expected_category, expected_miss_reason,
  question_style, qa_relation, notes, is_active, created_at, updated_at
"""

_RUN_COLUMNS = """
  run_id, store_id, label, status, started_at, finished_at,
  code_version, prompt_version, answer_model, embedding_model, answer_mode,
  retrieval_threshold, retrieval_strong_score, feature_flags, settings,
  metrics, case_count, notes, created_by, created_at
"""


# ── 골든셋 문항 ────────────────────────────────────────────────────────────

async def upsert_case(
    db: asyncpg.Connection,
    store_id: int,
    payload: dict[str, Any],
) -> asyncpg.Record:
    """case_key 기준 덮어쓰기. 문항은 정답지라 갱신 가능하다 (결과 이력과 다르다)."""
    return await db.fetchrow(
        f"""
        insert into evaluation_cases (
          store_id, case_key, question, expected_kind, expected_card_ids,
          expected_facts, expected_category, expected_miss_reason,
          question_style, qa_relation, notes, is_active
        )
        values ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
        on conflict (store_id, case_key) do update set
          question = excluded.question,
          expected_kind = excluded.expected_kind,
          expected_card_ids = excluded.expected_card_ids,
          expected_facts = excluded.expected_facts,
          expected_category = excluded.expected_category,
          expected_miss_reason = excluded.expected_miss_reason,
          question_style = excluded.question_style,
          qa_relation = excluded.qa_relation,
          notes = excluded.notes,
          is_active = excluded.is_active
        returning {_CASE_COLUMNS}
        """,
        store_id,
        payload["case_key"],
        payload["question"],
        payload["expected_kind"],
        payload.get("expected_card_ids") or [],
        payload.get("expected_facts") or [],
        payload.get("expected_category"),
        payload.get("expected_miss_reason"),
        payload.get("question_style") or "CANONICAL",
        payload.get("qa_relation"),
        payload.get("notes"),
        payload.get("is_active", True),
    )


async def list_cases(
    db: asyncpg.Connection,
    store_id: int,
    *,
    active_only: bool = True,
    case_keys: list[str] | None = None,
) -> list[asyncpg.Record]:
    return await db.fetch(
        f"""
        select {_CASE_COLUMNS}
        from evaluation_cases
        where store_id = $1
          and ($2::boolean is false or is_active = true)
          and ($3::text[] is null or case_key = any($3::text[]))
        order by case_key
        """,
        store_id,
        active_only,
        case_keys,
    )


# ── 실행 ──────────────────────────────────────────────────────────────────

async def create_run(
    db: asyncpg.Connection,
    store_id: int,
    payload: dict[str, Any],
) -> asyncpg.Record:
    return await db.fetchrow(
        f"""
        insert into evaluation_runs (
          store_id, label, code_version, prompt_version, answer_model,
          embedding_model, answer_mode, retrieval_threshold,
          retrieval_strong_score, feature_flags, settings, case_count,
          notes, created_by
        )
        values ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10::jsonb, $11::jsonb, $12, $13, $14)
        returning {_RUN_COLUMNS}
        """,
        store_id,
        payload["label"],
        payload["code_version"],
        payload["prompt_version"],
        payload["answer_model"],
        payload["embedding_model"],
        payload["answer_mode"],
        payload["retrieval_threshold"],
        payload["retrieval_strong_score"],
        json.dumps(payload.get("feature_flags") or {}, ensure_ascii=False),
        json.dumps(payload.get("settings") or {}, ensure_ascii=False),
        payload.get("case_count", 0),
        payload.get("notes"),
        payload.get("created_by"),
    )


async def insert_results(
    db: asyncpg.Connection,
    run_id: int,
    store_id: int,
    rows: list[dict[str, Any]],
) -> None:
    """결과는 추가만 한다. 트리거가 UPDATE·DELETE 를 막는다."""
    if not rows:
        return
    await db.executemany(
        """
        insert into evaluation_results (
          run_id, store_id, case_id, case_key, question,
          expected_kind, actual_kind, kind_correct, miss_reason,
          expected_card_ids, retrieved_card_ids, citation_card_ids,
          expected_hit_rank, reciprocal_rank, ndcg, ndcg_k,
          top_card_id, wrong_card,
          answer_source, grounding_status, answer_text, citation_count,
          citation_precision, fact_coverage, ungrounded,
          retrieve_latency_ms, answer_latency_ms, total_latency_ms,
          prompt_tokens, completion_tokens, cost_usd,
          passed, failure_kind, error
        )
        values (
          $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15,
          $16, $17, $18, $19, $20, $21, $22, $23, $24, $25, $26, $27, $28,
          $29, $30, $31, $32, $33, $34
        )
        """,
        [
            (
                run_id,
                store_id,
                r["case_id"],
                r["case_key"],
                r["question"],
                r["expected_kind"],
                r["actual_kind"],
                r["kind_correct"],
                r["miss_reason"],
                r["expected_card_ids"],
                r["retrieved_card_ids"],
                r["citation_card_ids"],
                r["expected_hit_rank"],
                r["reciprocal_rank"],
                r["ndcg"],
                r["ndcg_k"],
                r["top_card_id"],
                r["wrong_card"],
                r["answer_source"],
                r["grounding_status"],
                r["answer_text"],
                r["citation_count"],
                r["citation_precision"],
                r["fact_coverage"],
                r["ungrounded"],
                r["retrieve_latency_ms"],
                r["answer_latency_ms"],
                r["total_latency_ms"],
                r["prompt_tokens"],
                r["completion_tokens"],
                r["cost_usd"],
                r["passed"],
                r["failure_kind"],
                r["error"],
            )
            for r in rows
        ],
    )


async def finish_run(
    db: asyncpg.Connection,
    run_id: int,
    store_id: int,
    *,
    status: str,
    metrics: dict[str, Any],
    case_count: int,
) -> asyncpg.Record:
    """RUNNING 인 동안만 가능하다. 종료 후에는 트리거가 변경을 막는다."""
    return await db.fetchrow(
        f"""
        update evaluation_runs
        set status = $3,
            finished_at = now(),
            metrics = $4::jsonb,
            case_count = $5
        where run_id = $1 and store_id = $2
        returning {_RUN_COLUMNS}
        """,
        run_id,
        store_id,
        status,
        json.dumps(metrics, ensure_ascii=False),
        case_count,
    )


async def get_run(
    db: asyncpg.Connection,
    store_id: int,
    run_id: int,
) -> asyncpg.Record | None:
    return await db.fetchrow(
        f"select {_RUN_COLUMNS} from evaluation_runs where store_id = $1 and run_id = $2",
        store_id,
        run_id,
    )


async def list_runs(
    db: asyncpg.Connection,
    store_id: int,
    *,
    label: str | None,
    limit: int,
    before_id: int | None,
) -> list[asyncpg.Record]:
    return await db.fetch(
        f"""
        select {_RUN_COLUMNS}
        from evaluation_runs
        where store_id = $1
          and ($2::text is null or label = $2)
          and ($3::bigint is null or run_id < $3)
        order by run_id desc
        limit $4
        """,
        store_id,
        label,
        before_id,
        limit,
    )


async def list_results(
    db: asyncpg.Connection,
    store_id: int,
    run_id: int,
    *,
    failed_only: bool = False,
) -> list[dict[str, Any]]:
    rows = await db.fetch(
        """
        select r.*,
          e.metrics -> 'answer_cost_details' ->> 'schema_version' as answer_cost_schema,
          e.metrics -> 'answer_cost_details' -> 'cases' -> r.case_id::text as exact_answer_cost
        from evaluation_results r
        join evaluation_runs e on e.run_id = r.run_id and e.store_id = r.store_id
        where r.store_id = $1 and r.run_id = $2
          and ($3::boolean is false or r.passed = false)
        order by r.case_key
        """,
        store_id,
        run_id,
        failed_only,
    )
    return [_restore_answer_cost(dict(row)) for row in rows]


def _restore_answer_cost(row: dict[str, Any]) -> dict[str, Any]:
    """같은 store/run의 불변 보고서로 표시용 NUMERIC 컬럼의 정밀도를 보완한다."""
    schema = row.pop("answer_cost_schema", None)
    entry = row.pop("exact_answer_cost", None)
    if schema is None and entry is None:
        # 과거 run의 미계측 상태를 0으로 backfill하지 않는다.
        row["answer_usage_status"] = "UNKNOWN"
        return row
    if schema != "r_answer_cost/v1":
        raise ValueError("unsupported answer cost report")
    if entry is None:
        raise ValueError("missing answer cost report case")
    if isinstance(entry, str):
        entry = json.loads(entry)
    status = entry["answer_usage_status"]
    if status not in ("NOT_CALLED", "OBSERVED", "UNKNOWN"):
        raise ValueError("invalid answer usage status")
    raw = entry["cost_usd"]
    try:
        cost = Decimal(raw) if isinstance(raw, str) else None
    except InvalidOperation as exc:
        raise ValueError("invalid answer cost") from exc
    if (raw is not None and cost is None) or (cost is not None and (not cost.is_finite() or cost < 0)):
        raise ValueError("invalid answer cost")
    if status == "NOT_CALLED" and cost != 0:
        raise ValueError("nonzero or unknown cost for uncalled answer")
    row["cost_usd"] = cost
    row["answer_usage_status"] = status
    return row
