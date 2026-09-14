"""R 구현 검토용 offline 반례. 제품 코드·DB·외부 모델을 변경하거나 호출하지 않는다."""
from __future__ import annotations

import asyncio
from decimal import Decimal
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import HTTPException
from app.deps import get_claims
from app.learn.answer_validation import validate_answer_plan
from app.team.runner import estimate_cost, _execute
from app.team.metrics import aggregate
from scripts.dev_token import mint
from tests.test_c0_read_contract import answer, snapshot, QUERY
from tests.test_evaluations import AggregateTest


async def main():
    results = []
    settings = SimpleNamespace(env="local", supabase_db_url="unused", jwt_expire_minutes=15,
                               jwt_secret="synthetic-review-key-" * 4, jwt_algorithm="HS256")
    connection = SimpleNamespace(fetchrow=AsyncMock(return_value=dict(store_id=1, user_id=10, member_id=20)),
                                 close=AsyncMock())
    with patch("scripts.dev_token.get_settings", return_value=settings), \
         patch("app.deps.get_settings", return_value=settings), \
         patch("scripts.dev_token.asyncpg.connect", AsyncMock(return_value=connection)):
        token = await mint(slug="synthetic-store", force=True, team=True)
        try:
            await get_claims("Bearer " + token)
            status = 200
        except HTTPException as exc:
            status = exc.status_code
    results.append(dict(case="existing_dev_token", expected_status=200, actual_status=status))

    snap = snapshot()
    unrelated = snap.fact_revisions[0].model_copy(update={
        "fact_revision_id": "7", "predicate": "other", "assertion": "별도 업무 사실"})
    snap.fact_revisions.append(unrelated)
    snap.cards[0].blocks.append(snap.cards[0].blocks[0].model_copy(update={
        "block_id": "unrelated", "fact_revision_ids": ["7"]}))
    plan = answer(selected_blocks=[*answer().selected_blocks, dict(
        card_id="3", card_version_id="4", block_id="unrelated", fact_revision_ids=["7"])])
    try:
        validate_answer_plan(plan, snap, QUERY, store_id=1)
        actual = "accepted"
    except ValueError as exc:
        actual = str(exc)
    results.append(dict(case="unrelated_predicate_without_dependency", expected="INVALID_REFERENCE", actual=actual))

    snap = snapshot()
    snap.fact_revisions[0].conditions = ["포장 주문에만 적용"]
    snap.fact_revisions[0].exceptions = ["특별 행사일 제외"]
    try:
        validate_answer_plan(answer(), snap, QUERY, store_id=1)
        actual = "accepted"
    except ValueError as exc:
        actual = str(exc)
    results.append(dict(case="conditions_and_exceptions", expected="UNSUPPORTED_SCHEMA", actual=actual))

    rates = {"input": 0.0004, "output": 0}
    single = estimate_cost(1, 0, rates)
    rows = [dict(AggregateTest()._rows()[0], cost_usd=single) for _ in range(1000)]
    results.append(dict(case="rounding_before_sum", actual=aggregate(rows)["cost_usd_total"],
                        expected=0.0004))

    with patch("app.team.runner.retrieve_question", AsyncMock(return_value=dict(kind="miss", reason="no_anchor"))):
        outcome = await _execute(None, 1, "합성 질문", top_k=5, cost_per_1k=rates)
    results.append(dict(case="no_answer_call", prompt_tokens=outcome.prompt_tokens,
                        completion_tokens=outcome.completion_tokens, answer_cost=str(outcome.cost_usd),
                        actual=outcome.answer_usage_status, expected="NOT_CALLED"))
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
