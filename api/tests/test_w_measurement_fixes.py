from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch
import importlib.util
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import unittest

from app.db_session import ShortSession
from app.ingest.embed.service import PreparedEmbedding, embed_card, prepare_embedding, card_usage_context
from app.team.extraction import applicability, match_fact, aggregate
from app.team.repeat_metrics import compare_repeats
from app.team.answer_metrics import paired_gate


class ScorerTest(unittest.TestCase):
    def test_card_counterexamples_are_not_covered(self):
        fact = dict(subject="음료A", variant="ICE", attribute="우유량", value="225ml")
        for content in ("음료A HOT 우유 225ml, ICE 우유 275ml", "ICE 음료A 우유 225g",
                        "ICE 음료A 우유 225ml는 잘못된 값이고 275ml를 넣는다",
                        "ICE 음료A 우유는 넣지 않는다 225ml"):
            with self.subTest(content=content):
                self.assertEqual(match_fact(fact, [dict(card_id=1, content=content)]).verdict, "UNDETERMINED")

    def test_scope_missing_is_not_common(self):
        self.assertEqual(applicability({}, True), "UNKNOWN")
        self.assertEqual(applicability({}, False), "NOT_APPLICABLE")
        with self.assertRaises(ValueError):
            applicability(dict(applicability=None), True)

    def test_unknown_is_not_success_or_missing(self):
        m = match_fact(dict(subject="음료A", value="225ml", applicability="UNKNOWN"),
                       [dict(card_id=1, content="음료A 우유 225ml")])
        report = aggregate([dict(verdict=m.verdict, must_have=True, fact_id="t", source_type="SCAN", reason=m.reason)])
        self.assertEqual((report["covered"], report["missing"], report["undetermined"]), (0, 0, 1))


class RepeatTest(unittest.TestCase):
    truth = [dict(fact_id=str(i), must_have=i==0) for i in range(10)]

    def test_rotating_success_has_median_gain(self):
        a = [{str(i): "MISSING" for i in range(10)} for _ in range(3)]
        b = [{str(i): "COVERED" if i in win else "MISSING" for i in range(10)}
             for win in (range(5), range(3,8), range(5,10))]
        result = compare_repeats(a,b,self.truth)
        self.assertEqual(result["deltas"], [5,5,5])
        self.assertEqual(result["median_delta"],5)

    def test_stable_success_to_variable_blocks(self):
        a = [{"0":"COVERED"} for _ in range(3)]
        b = [{"0":v} for v in ("COVERED","COVERED","MISSING")]
        result = compare_repeats(a,b,[dict(fact_id="0",must_have=True)])
        self.assertFalse(result["safety_passed"])
        self.assertEqual(result["stability_degraded"],["0"])

    def test_missing_repeat_stays_in_denominator_and_blocks(self):
        result = compare_repeats([{"0":"COVERED"}]*3,[{}, {"0":"COVERED"}, {}],
                                 [dict(fact_id="0",must_have=True)])
        self.assertEqual(result["denominator"],1)
        self.assertEqual(result["must_have_unjudged"],["0"])

    def test_r_checks_all_repeats_with_must_have_ids(self):
        pairs = []
        for repeat in range(3):
            a={str(i):i==0 for i in range(10)}
            b={str(i):i!=0 or repeat!=2 for i in range(10)}
            pairs.append((a,b))
        result=paired_gate(pairs,control_width=0,must_have_regressions=0,
                           ledger_recall_regressed=False,cost_gate_passed=True,must_have_ids=["0"])
        self.assertFalse(result["eligible"])


class CliTest(unittest.IsolatedAsyncioTestCase):
    async def test_detail_cli_uses_median_and_reports_variable_facts(self):
        script=Path(__file__).resolve().parents[1]/"scripts/compare_runs.py"
        spec=importlib.util.spec_from_file_location("compare_runs_test",script)
        module=importlib.util.module_from_spec(spec)
        with patch("dotenv.load_dotenv"):
            spec.loader.exec_module(module)
        truth=[dict(fact_id="t",must_have=True,attribute="시간")]
        a=dict(per_run={1:{"t":"COVERED"},2:{"t":"COVERED"},3:{"t":"COVERED"}},failed=[],settings_hashes=["same"])
        b=dict(per_run={4:{"t":"COVERED"},5:{"t":"COVERED"},6:{"t":"MISSING"}},failed=[],settings_hashes=["same"])
        out=io.StringIO()
        with patch.object(module,"fetch_group",new_callable=AsyncMock,side_effect=[([1,2,3],a),([4,5,6],b)]), \
             patch.object(module.asyncpg,"connect",new_callable=AsyncMock,return_value=NS(close=AsyncMock())), \
             patch.object(module,"get_settings",return_value=NS(supabase_db_url="synthetic")), \
             patch.object(module.sys,"argv",["compare","--store","store-b","--a","BASE","--b","W1","--detail","--noise","0"]), \
             patch.object(module.Path,"read_text",return_value=json.dumps(dict(facts=truth))),redirect_stdout(out):
            self.assertEqual(await module.main(),0)
        self.assertIn("중앙값",out.getvalue())
        self.assertIn("VARIABLE",out.getvalue())
        self.assertIn("차단",out.getvalue())

    def test_rescore_rejects_old_judgments_without_inputs(self):
        script=Path(__file__).resolve().parents[1]/"scripts/rescore_extract_report.py"
        spec=importlib.util.spec_from_file_location("rescore_test",script)
        module=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with self.assertRaises(ValueError):
            module.rescore(dict(results=[dict(verdict="COVERED")]))
        data=dict(run_id=1,store="eval-b",label="synthetic",inputs=dict(
            truth=[dict(fact_id="t",subject="예시",attribute="사용기한",value="14일",must_have=True,source_key="s")],
            cards=[dict(card_id=1,title="예시",content="사용기한 14일")],
            ledger=[dict(fact_id=1,subject="예시",attribute="발주주기",value="14일")],source_types={"s":"SCAN"}))
        result=module.rescore(data)
        self.assertEqual(result["metrics"]["output"]["MATCHED"],0)
        self.assertEqual(result["metrics"]["ledger_recall"],0)
        self.assertEqual(result["metrics"]["covered"],1)
        self.assertEqual(data["label"],"synthetic")


class EmbedTest(unittest.IsolatedAsyncioTestCase):
    async def test_card_context_keeps_upstream_registration_and_evaluation(self):
        db=NS(fetchrow=AsyncMock(side_effect=[dict(source_id=12),dict(
            cost_phase="REGISTRATION",cost_purpose="EVALUATION",registration_campaign_id="test",job_id=4)]))
        context=await card_usage_context(db,1,2)
        self.assertEqual((context.source_id,context.job_id,context.cost_phase,context.cost_purpose),
                         ("12","4","REGISTRATION","EVALUATION"))

    async def test_missing_source_attribution_blocks_before_paid_call(self):
        db=NS(fetchrow=AsyncMock(side_effect=[dict(source_id=12),None]))
        with patch("app.ingest.embed.service.recorded_embeddings",new_callable=AsyncMock) as provider:
            with self.assertRaises(ValueError):
                await card_usage_context(db,1,2)
            provider.assert_not_awaited()

    async def test_prepare_injects_trusted_context_and_single_call(self):
        sink=object()
        with patch("app.ingest.embed.service.recorded_embeddings", new_callable=AsyncMock,return_value=[[1.]]) as call, \
             patch("app.ingest.embed.service.get_settings",return_value=NS(embedding_model="synthetic",embedding_dim=1)):
            result=await prepare_embedding(1,"예시","본문",cost_phase="REGISTRATION",cost_purpose="DEVELOPMENT",sink=sink)
        self.assertEqual(result.store_id,1)
        context=call.call_args.kwargs["context"]
        self.assertEqual((context.stage,context.store_id,context.cost_phase,context.cost_purpose),
                         ("EMBED","1","REGISTRATION","DEVELOPMENT"))
        self.assertIs(call.call_args.kwargs["sink"],sink)
        call.assert_awaited_once()

    async def test_stale_or_other_store_is_not_saved(self):
        db=NS(fetchrow=AsyncMock(return_value=dict(title="예시",content="새 내용",is_verified=True)))
        with patch("app.ingest.embed.service.repo.upsert_embedding",new_callable=AsyncMock) as write:
            for prepared in (PreparedEmbedding(1,"예시\n옛 내용",[1.],"synthetic",1),
                             PreparedEmbedding(2,"예시\n새 내용",[1.],"synthetic",1)):
                with self.assertRaises(ValueError):
                    await embed_card(db,1,1,prepared=prepared)
            write.assert_not_awaited()

    async def test_short_session_does_not_hold_connection_between_queries(self):
        pool=NS(fetchval=AsyncMock(return_value=1))
        session=ShortSession(pool)
        await session.fetchval("select 1")
        self.assertIsNone(session.connection)
