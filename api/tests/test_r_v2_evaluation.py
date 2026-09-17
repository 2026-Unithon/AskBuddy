import asyncio
import unittest

import httpx

from app.contracts.hashing import digest
from app.team.v2_evaluation import EvaluationManifest,collect_v2_run,build_v2_report


def manifest():
    return EvaluationManifest(truth_kind='SYNTHETIC',truth_version='test/v1',snapshot_id='1',
        knowledge_revision='1',snapshot_hash='sha256:'+'0'*64,cases=[dict(question_id='q1',question='합성 질문',
            expected_action='ANSWER',must_have=True,required_facts=['합성 사실'],forbidden_claims=[])])


def answer(request_id):
    return dict(contract_version='v2',request_id=request_id,action='ANSWER',message='합성 사실',snapshot_id='1',
        knowledge_revision='1',citations=[dict(card_id='1',card_version_id='1',block_id='b',fact_revision_id='1',source_id='1')])


class V2EvaluationTest(unittest.IsolatedAsyncioTestCase):
    async def collect(self,mode='ok'):
        async def handle(request):
            import json
            if request.url.path.endswith('/sessions'):return httpx.Response(200,json={'session_id':'1'})
            if mode=='timeout':raise httpx.ReadTimeout('must not leak secrets')
            if mode=='error':return httpx.Response(503,json={'error':{'code':'MODEL_UNAVAILABLE'}})
            body=answer(json.loads(request.content)['request_id'])
            if mode=='mismatch':body['knowledge_revision']='2'
            if mode=='invalid':body['citations']=[]
            if mode=='escalate':body.update(action='ESCALATE',citations=[],pending_id='1')
            if mode=='cancel':raise asyncio.CancelledError()
            return httpx.Response(200,json=body,headers={'x-answer-receipt-id':'9'})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle),base_url='http://synthetic') as client:
            return await collect_v2_run(client,manifest(),headers={'Authorization':'must not leak secrets'},
                                        configuration={'planner':'synthetic'},provider_mode='SYNTHETIC')

    async def test_answer_action_is_not_automatic_truth(self):
        run=await self.collect()
        report=build_v2_report(run)
        self.assertEqual(report['metrics']['action_accuracy'],1)
        self.assertIsNone(report['grounded_answer_rate'])
        self.assertEqual(report['paired_gate_input'],{'q1':None})
        self.assertEqual(report['cost_status'],'UNKNOWN')
        self.assertNotIn('must not leak secrets',str(run))

    async def test_matching_human_review_enables_semantic_result(self):
        run=await self.collect()
        label=dict(question_id='q1',row_hash=run['rows'][0]['row_hash'],reviewer='synthetic-reviewer',
                   reason='합성 인용과 필수 사실 대조',semantic_correct=True)
        report=build_v2_report(run,[label])
        self.assertEqual(report['grounded_answer_rate'],1)
        self.assertFalse(report['production_promotion'])
        label['semantic_correct']=False
        self.assertEqual(build_v2_report(run,[label])['grounded_answer_rate'],0)
        label['row_hash']='wrong'
        with self.assertRaises(ValueError):build_v2_report(run,[label])

    async def test_all_failures_preserve_denominator(self):
        for mode in ('error','timeout','invalid','mismatch'):
            with self.subTest(mode=mode):
                run=await self.collect(mode)
                report=build_v2_report(run)
                self.assertEqual(report['question_count'],1)
                self.assertEqual(report['metrics']['error_count'],1)
                self.assertEqual(report['paired_gate_input']['q1'],False if mode in ('error','timeout') else None)
                self.assertNotIn('must not leak secrets',str(run))

    async def test_missing_rows_even_with_updated_outer_hash_rejected(self):
        run=await self.collect()
        run['rows']=[]
        run['run_hash']=digest({k:v for k,v in run.items() if k!='run_hash'})
        with self.assertRaises(ValueError):build_v2_report(run)

    async def test_mutated_output_rejected(self):
        run=await self.collect()
        run['rows'][0]['response']['message']='바뀐 출력'
        with self.assertRaises(ValueError):build_v2_report(run)

    async def test_duplicate_and_foreign_judgments_rejected(self):
        run=await self.collect()
        label=dict(question_id='q1',row_hash=run['rows'][0]['row_hash'],reviewer='reviewer',reason='검토')
        with self.assertRaises(ValueError):build_v2_report(run,[label,label])
        label['question_id']='foreign'
        with self.assertRaises(ValueError):build_v2_report(run,[label])

    async def test_cancellation_propagates(self):
        with self.assertRaises(asyncio.CancelledError):await self.collect('cancel')

    async def test_block_precision_requires_separate_review(self):
        run=await self.collect('escalate')
        self.assertIsNone(build_v2_report(run)['metrics']['block_precision'])
        label=dict(question_id='q1',row_hash=run['rows'][0]['row_hash'],reviewer='reviewer',reason='합성 차단 검토',
                   knowledge_block=True,block_correct=False)
        self.assertEqual(build_v2_report(run,[label])['metrics']['block_precision'],0)
        label['semantic_correct']=True
        with self.assertRaises(ValueError):build_v2_report(run,[label])

    async def test_source_change_blocks_report(self):
        run=await self.collect()
        run['source_unchanged']=False
        run['run_hash']=digest({k:v for k,v in run.items() if k!='run_hash'})
        with self.assertRaises(ValueError):build_v2_report(run)

    def test_duplicate_manifest_rejected(self):
        data=manifest().model_dump()
        data['cases']*=2
        with self.assertRaises(ValueError):EvaluationManifest.model_validate(data)
