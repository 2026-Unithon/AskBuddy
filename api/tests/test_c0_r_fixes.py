"""R 자체 회귀: 발급/검증·선택 경계·비용·출력의 연결을 검사한다."""
import json
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.deps import get_claims
from app.learn.answering import compose_grounded_answer
from app.learn.answer_validation import validate_answer_plan
from app.team.metrics import aggregate
from app.team.repository import list_results, _restore_answer_cost
from app.team.runner import _execute, estimate_cost
from scripts.dev_token import mint
from scripts.run_eval import _markdown, _summary_text
from tests.test_c0_read_contract import answer, snapshot, QUERY
from tests import test_evaluations as baseline


class TokenFixTest(unittest.IsolatedAsyncioTestCase):
    async def test_real_minter_round_trip_including_team(self):
        settings = SimpleNamespace(env="local", supabase_db_url="unused", jwt_expire_minutes=15,
                                   jwt_secret="synthetic-review-key-" * 4, jwt_algorithm="HS256")
        conn = SimpleNamespace(fetchrow=AsyncMock(return_value=dict(store_id=1, user_id=10, member_id=20)),
                               close=AsyncMock())
        with patch("scripts.dev_token.get_settings", return_value=settings), \
             patch("app.deps.get_settings", return_value=settings), \
             patch("scripts.dev_token.asyncpg.connect", AsyncMock(return_value=conn)):
            for team in (False, True):
                started = datetime.now(timezone.utc).timestamp()
                token = await mint(slug="synthetic-store", force=True, team=team)
                claims = await get_claims("Bearer " + token)
                self.assertEqual(claims["user_id"], 10)
                self.assertLessEqual(abs(claims["exp"] - started - 900), 2)
                self.assertEqual(claims.get("scope"), "team" if team else None)


class SelectionFixTest(unittest.TestCase):
    def test_unrelated_block_rejected_but_required_block_allowed(self):
        snap = snapshot()
        snap.fact_revisions.append(snap.fact_revisions[0].model_copy(update={
            "fact_revision_id": "7", "predicate": "preparation", "assertion": "필수 준비"}))
        snap.cards[0].blocks.append(snap.cards[0].blocks[0].model_copy(update={
            "block_id": "preparation", "fact_revision_ids": ["7"]}))
        plan = answer(selected_blocks=[dict(card_id="3", card_version_id="4", block_id="preparation",
                                           fact_revision_ids=["7"]), *answer().selected_blocks])
        with self.assertRaisesRegex(ValueError, "INVALID_REFERENCE"):
            validate_answer_plan(plan, snap, QUERY, store_id=1)
        snap.fact_revisions[0].requires = ["7"]
        validate_answer_plan(plan, snap, QUERY, store_id=1)

    def test_conditions_and_exceptions_fail_closed_until_supported(self):
        for field in ("conditions", "exceptions"):
            snap = snapshot()
            setattr(snap.fact_revisions[0], field, ["포장 주문"])
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "UNSUPPORTED_SCHEMA"):
                validate_answer_plan(answer(), snap, QUERY, store_id=1)


class CostFixTest(unittest.IsolatedAsyncioTestCase):
    async def test_provider_timeout_is_not_marked_not_called(self):
        client = SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(
            generate_content=AsyncMock(side_effect=TimeoutError))))
        with patch("app.learn.answering.get_settings", return_value=SimpleNamespace(
            answer_mode="grounded_llm", gemini_api_key="fake", gemini_model="fake")), \
             patch("google.genai.Client", return_value=client):
            result = await compose_grounded_answer("합성 질문", [dict(id=1, content="승인 원문")])
        self.assertEqual(result.model_call_status, "UNKNOWN")
        self.assertIsNone(result.usage)

    async def test_saved_report_restores_precision_and_scope_on_read(self):
        rows = [dict(baseline.AggregateTest()._rows()[0], cost_usd=Decimal("0.0000004"),
                     case_id=i + 1, answer_usage_status="OBSERVED") for i in range(1000)]
        stored = json.loads(json.dumps(aggregate(rows)))
        # DB의 NUMERIC 표시값은 0이어도 같은 run에 저장된 정밀 금액으로 복원한다.
        dbrows = [dict(row, cost_usd=Decimal("0.000000"), answer_cost_schema="r_answer_cost/v1",
                       exact_answer_cost=json.dumps(stored["answer_cost_details"]["cases"][str(row["case_id"])]))
                  for row in rows]
        db = SimpleNamespace(fetch=AsyncMock(return_value=dbrows))
        restored = await list_results(db, store_id=7, run_id=8)
        self.assertEqual(aggregate(restored)["cost_usd_total"], .0004)
        sql, *args = db.fetch.call_args.args
        self.assertEqual(args, [7, 8, False])
        self.assertIn("e.store_id = r.store_id", sql)
        self.assertIn("r.store_id = $1 and r.run_id = $2", sql)
        self.assertEqual(restored[0]["answer_usage_status"], "OBSERVED")
        self.assertNotIn("exact_answer_cost", restored[0])

    def test_legacy_cost_is_not_backfilled_and_corrupt_reports_are_rejected(self):
        legacy = _restore_answer_cost(dict(case_id=1, cost_usd=None,
                                          answer_cost_schema=None, exact_answer_cost=None))
        self.assertIsNone(legacy["cost_usd"])
        self.assertEqual(legacy["answer_usage_status"], "UNKNOWN")
        for entry in (None, dict(cost_usd="NaN", answer_usage_status="OBSERVED"),
                      dict(cost_usd="0.1", answer_usage_status="NOT_CALLED")):
            with self.subTest(entry=entry), self.assertRaises(ValueError):
                _restore_answer_cost(dict(case_id=1, cost_usd=0, answer_cost_schema="r_answer_cost/v1",
                                          exact_answer_cost=entry))

    def test_small_costs_are_summed_before_rounding(self):
        cost = estimate_cost(1, 0, {"input": .0004, "output": 0})
        self.assertIsInstance(cost, Decimal)
        self.assertEqual(cost, Decimal("0.0000004"))
        rows = [dict(baseline.AggregateTest()._rows()[0], cost_usd=cost, case_id=i + 1,
                     answer_usage_status="OBSERVED") for i in range(1000)]
        result = aggregate(rows)
        self.assertEqual(result["cost_usd_total"], .0004)
        self.assertEqual(result["answer_cost_details"]["cases"]["1"]["cost_usd"], "0.0000004")
        json.dumps(result, allow_nan=False)

    async def test_miss_is_zero_only_for_answer_stage(self):
        with patch("app.team.runner.retrieve_question", AsyncMock(return_value=dict(kind="miss", reason="no_match"))), \
             patch("app.team.runner.compose_grounded_answer", AsyncMock()) as compose:
            result = await _execute(None, 1, "합성 질문", top_k=5, cost_per_1k=None)
        compose.assert_not_called()
        self.assertEqual(result.answer_usage_status, "NOT_CALLED")
        self.assertEqual(result.cost_usd, Decimal(0))
        self.assertEqual((result.prompt_tokens, result.completion_tokens), (0, 0))

    async def test_extractive_and_missing_key_are_not_called_but_timeout_unknown(self):
        candidate = dict(id=1, content="합성 승인 원문")
        for mode, key in (("extractive", "fake"), ("grounded_llm", "")):
            with patch("app.team.runner.retrieve_question", AsyncMock(return_value=dict(kind="hit", candidates=[candidate]))), \
                 patch("app.learn.answering.get_settings", return_value=SimpleNamespace(answer_mode=mode, gemini_api_key=key)):
                result = await _execute(None, 1, "질문", top_k=5, cost_per_1k=None)
            self.assertEqual(result.answer_usage_status, "NOT_CALLED")
            self.assertEqual(result.cost_usd, 0)
        with patch("app.team.runner.retrieve_question", AsyncMock(return_value=dict(kind="hit", candidates=[candidate]))), \
             patch("app.team.runner.compose_grounded_answer", AsyncMock(side_effect=TimeoutError)):
            result = await _execute(None, 1, "질문", top_k=5, cost_per_1k=None)
        self.assertEqual(result.answer_usage_status, "UNKNOWN")
        self.assertIsNone(result.cost_usd)

    def test_partial_report_displays_known_unknown_and_scope(self):
        metrics = aggregate(baseline.AggregateTest()._rows())
        run = dict(run_id=1, label="합성", status="SUCCEEDED", started_at=datetime.now(timezone.utc),
                   code_version="test", prompt_version="test", answer_model="fake", embedding_model="fake",
                   answer_mode="grounded_llm", retrieval_threshold=.35, retrieval_strong_score=.62)
        output = _markdown(run, [], metrics, None)
        for expected in ("PARTIAL", "UNKNOWN", "0.001", "누락", "ANSWER_MODEL_ONLY"):
            self.assertIn(expected, output)
        for expected in ("PARTIAL", "0.001", "UNKNOWN"):
            self.assertIn(expected, _summary_text(metrics))
