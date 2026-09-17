import unittest
from uuid import uuid4

from app.contracts.hashing import digest
from app.team.v2_campaign import compare_campaign,run_signature,campaign_input_hash
from app.team.v2_evaluation import EvaluationManifest


def bundle():
    manifest=EvaluationManifest(truth_kind='SYNTHETIC',truth_version='test/v1',snapshot_id='1',
        knowledge_revision='1',snapshot_hash='sha256:'+'0'*64,cases=[dict(question_id=str(i),question=f'합성 질문 {i}',
            expected_action='ANSWER',must_have=i==0,required_facts=['합성 사실'],forbidden_claims=[]) for i in range(7)]).model_dump(mode='json')
    labels={}
    def run(arm):
        rid=uuid4().hex
        rows=[]
        for i in range(7):
            row=dict(question_id=str(i),request_id=f'{rid}-{i}',actual_action='ANSWER',status='RECORDED',receipt_id=str(i+1),
                response=dict(contract_version='v2',request_id=f'{rid}-{i}',action='ANSWER',message='합성 사실',
                    snapshot_id='1',knowledge_revision='1',citations=[dict(card_id='1',card_version_id='1',block_id='b',fact_revision_id='1',source_id='1')]))
            rows.append(dict(row,row_hash=digest(row)))
        result=dict(schema_version='r_v2_run/v1',run_id=rid,manifest=manifest,manifest_hash=digest(manifest),
            source_unchanged=True,source_hashes={'synthetic':digest(arm)},provider_mode='SYNTHETIC',scope='ISOLATED_SINGLE_TURN_HTTP',
            configuration={'arm':arm},configuration_hash=digest({'arm':arm}),rows=rows)
        result['run_hash']=digest(result)
        labels[result['run_hash']]=[dict(question_id=r['question_id'],row_hash=r['row_hash'],reviewer='synthetic',
            reason='합성 산술 fixture',semantic_correct=arm=='b' or r['question_id']=='0') for r in rows]
        return result
    a=[run('a') for _ in range(3)]
    b=[run('b') for _ in range(3)]
    c=[run('a') for _ in range(3)]
    plan=dict(schema_version='r_v2_campaign_plan/v1',manifest_hash=digest(manifest),repeat_count=3,control_count=3,
        baseline_signature=run_signature(a[0]),candidate_signature=run_signature(b[0]),cost_neutral=False,registration_ref='SYNTHETIC_TEST_ONLY')
    evidence=dict(input_hash=campaign_input_hash(plan,a,b,c),cost_gate_passed=True,ledger_recall_regressed=False,
        reviewer='synthetic',reference='synthetic-cost-ledger-review')
    return dict(plan=plan,baseline=a,candidate=b,control=c,judgments=labels,evidence=evidence)


class CampaignTest(unittest.TestCase):
    def test_required_clarification_needs_semantic_action_review(self):
        for judgment in (None,False,True):
            with self.subTest(judgment=judgment):
                b=bundle()
                for run in [*b['baseline'],*b['candidate'],*b['control']]:
                    old=run['run_hash']
                    run['manifest']['cases'][0]['expected_action']='CLARIFY'
                    row=run['rows'][0]
                    row['actual_action']='CLARIFY'
                    row['response']=dict(contract_version='v2',request_id=row['request_id'],action='CLARIFY',message='선택',
                        snapshot_id='1',knowledge_revision='1',context_id=str(uuid4()),clarification_slot='temperature',allowed_options=['HOT','ICE'])
                    row['row_hash']=digest({k:v for k,v in row.items() if k!='row_hash'})
                    run['manifest_hash']=digest(run['manifest'])
                    run['run_hash']=digest({k:v for k,v in run.items() if k!='run_hash'})
                    labels=b['judgments'].pop(old)
                    labels[0]=dict(question_id='0',row_hash=row['row_hash'],reviewer='synthetic',reason='선택 적절성',action_correct=judgment)
                    b['judgments'][run['run_hash']]=labels
                b['plan']['manifest_hash']=b['baseline'][0]['manifest_hash']
                b['evidence']['input_hash']=campaign_input_hash(b['plan'],b['baseline'],b['candidate'],b['control'])
                result=compare_campaign(**b)
                self.assertEqual('MUST_HAVE_NONANSWER_REVIEW_REQUIRED' in result['gate']['blocking_reasons'],judgment is None)
                self.assertEqual('MUST_HAVE_ACTION_FAILURE' in result['gate']['blocking_reasons'],judgment is False)
    def test_pinned_arm_difference_allowed_and_gate_connected(self):
        report=compare_campaign(**bundle())
        self.assertTrue(report['gate']['eligible'])
        self.assertEqual(report['gate']['median_delta'],6)
        self.assertEqual(report['control_width'],0)
        self.assertFalse(report['production_promotion'])

    def test_missing_external_evidence_is_not_pass(self):
        b=bundle();b['evidence']=None
        result=compare_campaign(**b)
        self.assertFalse(result['gate']['eligible'])
        self.assertIn('LEDGER_UNVERIFIED',result['gate']['blocking_reasons'])

    def test_unjudged_answer_blocks_gate(self):
        b=bundle();b['judgments'][b['candidate'][0]['run_hash']]=[]
        self.assertIn('UNJUDGED_RESULTS',compare_campaign(**b)['gate']['blocking_reasons'])

    def test_control_unjudged_has_no_zero_width_or_threshold(self):
        b=bundle();b['judgments'][b['control'][0]['run_hash']]=[]
        result=compare_campaign(**b)
        self.assertIsNone(result['control_width'])
        self.assertIsNone(result['gate']['threshold'])
        self.assertFalse(result['gate']['eligible'])

    def test_one_required_regression_blocks_positive_median(self):
        b=bundle();b['judgments'][b['candidate'][2]['run_hash']][0]['semantic_correct']=False
        result=compare_campaign(**b)
        self.assertEqual(result['gate']['median_delta'],6)
        self.assertEqual(result['gate']['must_have_regression_ids'],['0'])
        self.assertFalse(result['gate']['eligible'])

    def test_duplicate_or_missing_run_rejected(self):
        for kind in ('duplicate','missing'):
            with self.subTest(kind=kind):
                b=bundle()
                if kind=='duplicate':b['control'][0]=b['baseline'][0]
                else:b['candidate'].pop()
                with self.assertRaises(ValueError):compare_campaign(**b)

    def test_configuration_source_provider_or_manifest_drift_rejected(self):
        for key,value in (('configuration_hash','wrong'),('source_hashes',{'changed':'hash'}),
                          ('provider_mode','LIVE'),('manifest_hash','wrong')):
            with self.subTest(key=key):
                b=bundle();r=b['candidate'][1];old=r['run_hash'];r[key]=value
                r['run_hash']=digest({k:v for k,v in r.items() if k!='run_hash'})
                b['judgments'][r['run_hash']]=b['judgments'].pop(old)
                with self.assertRaises(ValueError):compare_campaign(**b)

    def test_foreign_evidence_and_judgments_rejected(self):
        b=bundle();b['evidence']['input_hash']='wrong'
        with self.assertRaises(ValueError):compare_campaign(**b)
        b=bundle();b['judgments']['foreign']=[]
        with self.assertRaises(ValueError):compare_campaign(**b)

    def test_observed_control_width_sets_threshold(self):
        b=bundle()
        for label in b['judgments'][b['control'][0]['run_hash']]:label['semantic_correct']=True
        result=compare_campaign(**b)
        self.assertEqual(result['control_width'],6)
        self.assertEqual(result['gate']['threshold'],9)
        self.assertFalse(result['gate']['eligible'])

    def test_required_policy_is_not_lost_outside_answerable_denominator(self):
        b=bundle()
        for run in [*b['baseline'],*b['candidate'],*b['control']]:
            old=run['run_hash']
            run['manifest']['cases'][0]['expected_action']='SAFE_ROUTE'
            run['manifest_hash']=digest(run['manifest'])
            run['run_hash']=digest({k:v for k,v in run.items() if k!='run_hash'})
            b['judgments'][run['run_hash']]=b['judgments'].pop(old)
        b['plan']['manifest_hash']=b['baseline'][0]['manifest_hash']
        b['evidence']['input_hash']=campaign_input_hash(b['plan'],b['baseline'],b['candidate'],b['control'])
        self.assertIn('MUST_HAVE_ACTION_FAILURE',compare_campaign(**b)['gate']['blocking_reasons'])
