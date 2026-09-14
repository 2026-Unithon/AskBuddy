"""골든셋 한 벌을 실제 검색·답변 경로에 태우고 결과를 채점한다.

제품 엔드포인트(/learn/chat)를 부르지 않고 같은 내부 함수를 직접 부른다.
평가가 chat_messages·pending_questions·알림을 만들면 그게 곧 운영 데이터 오염이다.
읽기만 하는 평가는 몇 번을 돌려도 매장 상태를 바꾸지 않는다.
"""
from __future__ import annotations

import logging
import time
from decimal import Decimal, InvalidOperation
from typing import Any

import asyncpg

from app.learn.answering import compose_grounded_answer
from app.reg.retrieve import retrieve_question
from app.team.metrics import NDCG_K, CaseOutcome, score_case

logger = logging.getLogger(__name__)

# 실행 1회가 통째로 죽지 않도록 문항 단위로 예외를 가둔다
_MAX_QUESTION_LEN = 500


async def run_case(
    db: asyncpg.Connection,
    store_id: int,
    case: dict[str, Any],
    *,
    top_k: int,
    cost_per_1k: dict[str, float] | None,
) -> dict[str, Any]:
    """문항 하나를 실행하고 채점된 행을 돌려준다. 실패해도 예외를 올리지 않는다."""
    question = str(case["question"]).strip()[:_MAX_QUESTION_LEN]
    outcome = await _execute(db, store_id, question, top_k=top_k, cost_per_1k=cost_per_1k)

    score = score_case(
        expected_kind=case["expected_kind"],
        expected_card_ids=case["expected_card_ids"] or [],
        expected_facts=case["expected_facts"] or [],
        expected_miss_reason=case.get("expected_miss_reason"),
        outcome=outcome,
    )

    return {
        "case_id": int(case["case_id"]),
        "case_key": case["case_key"],
        "question": question,
        "expected_kind": case["expected_kind"],
        "expected_card_ids": [int(c) for c in (case["expected_card_ids"] or [])],
        "actual_kind": outcome.actual_kind,
        "kind_correct": score.kind_correct,
        "miss_reason": outcome.miss_reason,
        "retrieved_card_ids": outcome.retrieved_card_ids,
        "citation_card_ids": outcome.citation_card_ids,
        "expected_hit_rank": score.expected_hit_rank,
        "reciprocal_rank": score.reciprocal_rank,
        "ndcg": score.ndcg,
        "ndcg_k": NDCG_K if score.ndcg is not None else None,
        "top_card_id": score.top_card_id,
        "wrong_card": score.wrong_card,
        "answer_source": outcome.answer_source,
        "grounding_status": outcome.grounding_status,
        "answer_text": outcome.answer_text,
        "citation_count": score.citation_count,
        "citation_precision": score.citation_precision,
        "fact_coverage": score.fact_coverage,
        "ungrounded": score.ungrounded,
        "retrieve_latency_ms": outcome.retrieve_latency_ms,
        "answer_latency_ms": outcome.answer_latency_ms,
        "total_latency_ms": score.total_latency_ms,
        "prompt_tokens": outcome.prompt_tokens,
        "completion_tokens": outcome.completion_tokens,
        "cost_usd": outcome.cost_usd,
        "answer_usage_status": outcome.answer_usage_status,
        "passed": score.passed,
        "failure_kind": score.failure_kind,
        "error": outcome.error,
    }


async def _execute(
    db: asyncpg.Connection,
    store_id: int,
    question: str,
    *,
    top_k: int,
    cost_per_1k: dict[str, float] | None,
) -> CaseOutcome:
    started = time.perf_counter()
    try:
        result = await retrieve_question(db, store_id, question, top_k)
    except Exception as exc:  # 문항 하나의 실패가 실행 전체를 죽이지 않는다
        logger.warning("evaluation retrieve failed: %s", exc)
        return CaseOutcome(
            actual_kind="ERROR",
            retrieve_latency_ms=_elapsed_ms(started),
            prompt_tokens=0, completion_tokens=0, cost_usd=Decimal(0),
            answer_usage_status="NOT_CALLED",
            error=f"retrieve: {exc}",
        )
    retrieve_ms = _elapsed_ms(started)

    if result["kind"] == "miss":
        # 불변식 5 — miss 면 답변 LLM 을 부르지 않는다. 평가도 예외가 아니다
        return CaseOutcome(
            actual_kind="MISS",
            miss_reason=result.get("reason"),
            retrieve_latency_ms=retrieve_ms,
            prompt_tokens=0, completion_tokens=0, cost_usd=Decimal(0),
            answer_usage_status="NOT_CALLED",
        )

    candidates = result["candidates"]
    retrieved_ids = [int(c["id"]) for c in candidates]

    answer_started = time.perf_counter()
    try:
        composition = await compose_grounded_answer(question, candidates)
    except Exception as exc:
        logger.warning("evaluation answer failed: %s", exc)
        return CaseOutcome(
            actual_kind="ERROR",
            retrieved_card_ids=retrieved_ids,
            retrieve_latency_ms=retrieve_ms,
            answer_latency_ms=_elapsed_ms(answer_started),
            error=f"answer: {exc}",
        )
    answer_ms = _elapsed_ms(answer_started)

    usage = composition.usage or {}
    prompt_tokens = usage.get("prompt_tokens")
    completion_tokens = usage.get("completion_tokens")
    not_called = composition.model_call_status == "NOT_CALLED"
    if not_called:
        prompt_tokens = completion_tokens = 0

    return CaseOutcome(
        actual_kind="HIT",
        retrieved_card_ids=retrieved_ids,
        citation_card_ids=[int(c["id"]) for c in composition.candidates],
        answer_text=composition.content,
        answer_source=composition.source,
        grounding_status=composition.grounding_status,
        retrieve_latency_ms=retrieve_ms,
        answer_latency_ms=answer_ms,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cost_usd=Decimal(0) if not_called else estimate_cost(prompt_tokens, completion_tokens, cost_per_1k),
        answer_usage_status=composition.model_call_status,
    )


def estimate_cost(
    prompt_tokens: int | None,
    completion_tokens: int | None,
    cost_per_1k: dict[str, float] | None,
) -> Decimal | None:
    """단가를 준 실행만 비용을 계산한다. 모르는 단가를 코드에 박아 추정하지 않는다."""
    if not cost_per_1k or prompt_tokens is None or completion_tokens is None:
        return None
    if any(type(n) is not int or n < 0 for n in (prompt_tokens, completion_tokens)):
        return None
    try:
        inp = Decimal(str(cost_per_1k.get("input")))
        out = Decimal(str(cost_per_1k.get("output")))
        if not all(rate.is_finite() and rate >= 0 for rate in (inp, out)):
            return None
        total = (prompt_tokens * inp + completion_tokens * out) / Decimal(1000)
        return total
    except (InvalidOperation, ValueError):
        return None


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)
