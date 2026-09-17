"""격리 실제 DB/API에서 평가 수집·출력 보존·미판정을 함께 인수한다."""
import json
from pathlib import Path
from unittest.mock import patch

from app.team.v2_evaluation import EvaluationManifest,collect_v2_run,build_v2_report
from app.team.v2_campaign import compare_campaign,run_signature
from app.team.dialogue_evaluation import collect_dialogue
from app.team.evaluation_usage import evaluation_usage_scope
from app.usage.recorder import attempt


async def verify(client,admin,seed,headers,question,title):
    from app.learn import v2_router
    cases=[]
    for key,text,action in (
        ('answer',question,'ANSWER'),('clarify',f'{title} 물 얼마나?','CLARIFY'),
        ('escalate','존재하지 않는 업무의 위치 알려줘','ESCALATE'),
        ('refuse','직원 집 주소 알려줘','REFUSE'),('safe','알레르기 있어도 먹어도 돼?','SAFE_ROUTE'),
        ('timeout','합성 평가 장애 질문','ANSWER')):
        cases.append(dict(question_id=key,question=text,expected_action=action,must_have=key=='answer',
            required_facts=[seed['snapshot'].fact_revisions[0].fact_revision_id] if key=='answer' else [],forbidden_claims=[]))
    snapshot=seed['snapshot']
    dialogue=await collect_dialogue(client,dict(case_id='synthetic-clarification',turns=[
        dict(turn_id='ask',question=f'{title} 물 얼마나?',expected_action='CLARIFY'),
        dict(turn_id='choose',question=snapshot.fact_revisions[0].variant.temperature,
            option=snapshot.fact_revisions[0].variant.temperature,expected_action='ANSWER')]),headers=headers,
        expected_snapshot=dict(snapshot_id=snapshot.snapshot_id,knowledge_revision=snapshot.knowledge_revision),
        provider_mode='SYNTHETIC',configuration=dict(embedding='SYNTHETIC_FIXED_VECTOR',reranker=False))
    assert dialogue['action_sequence_matches'] and dialogue['recorded_turns']==2
    for row in dialogue['rows']:
        stored=await admin.fetchval('select response from r_answer_receipts where store_id=$1 and receipt_id=$2',
            int(snapshot.store_id),int(row['receipt_id']))
        assert (json.loads(stored) if isinstance(stored,str) else stored)==row['response']
    print('PASS v2 dialogue server context and two durable turn receipts agree')
    manifest=EvaluationManifest(truth_kind='SYNTHETIC',truth_version='r-v2-db-fixture/v1',
        snapshot_id=snapshot.snapshot_id,knowledge_revision=snapshot.knowledge_revision,
        snapshot_hash=snapshot.snapshot_hash,cases=cases)
    original_embed=v2_router.recorded_embeddings
    async def embed(texts,**kwargs):
        async with attempt(kwargs['sink'],kwargs['context'],model='synthetic-evaluation-embedding',mode='mock'):
            if texts==['합성 평가 장애 질문']:raise TimeoutError('synthetic failure')
            return await original_embed(texts,**kwargs)
    with evaluation_usage_scope(store_id=int(snapshot.store_id),evaluation_run_id='1'),patch('app.learn.v2_router.recorded_embeddings',embed):
        runs=[]
        for _ in range(9):
            runs.append(await collect_v2_run(client,manifest,headers=headers,provider_mode='SYNTHETIC',
                configuration=dict(planner_version=v2_router.PLANNER_VERSION,reranker_enabled=False,
                    embedding='SYNTHETIC_FIXED_VECTOR',scope='DISPOSABLE_DB')))
    run=runs[0]
    answer_row=next(row for row in run['rows'] if row['question_id']=='answer')
    purpose=await admin.fetchval("""select u.cost_purpose from r_answer_receipts r
        join ai_usage_attempts u on u.store_id=r.store_id
            and u.logical_call_id=r.execution_metadata->>'query_logical_call_id'
        where r.store_id=$1 and r.receipt_id=$2""",int(snapshot.store_id),int(answer_row['receipt_id']))
    assert purpose=='EVALUATION'
    print('PASS v2 HTTP evaluation embedding is attributed to EVALUATION')
    signature=run_signature(run)
    plan=dict(schema_version='r_v2_campaign_plan/v1',manifest_hash=run['manifest_hash'],repeat_count=3,control_count=3,
        baseline_signature=signature,candidate_signature=signature,cost_neutral=False,registration_ref='SYNTHETIC_INTEGRATION_ONLY')
    campaign=compare_campaign(plan,baseline=runs[:3],candidate=runs[3:6],control=runs[6:])
    assert campaign['control_width'] is None and not campaign['gate']['eligible']
    assert 'COST_UNVERIFIED' in campaign['gate']['blocking_reasons'] and 'CONTROL_UNJUDGED' in campaign['gate']['blocking_reasons']
    assert len(campaign['reports'])==9
    print('PASS v2 campaign nine distinct HTTP runs retain unknown control and external gates')
    report=build_v2_report(run)
    assert [r['actual_action'] for r in run['rows']]==['ANSWER','CLARIFY','ESCALATE','REFUSE','SAFE_ROUTE','ERROR']
    print('PASS v2 evaluation five actions and ERROR retained')
    assert report['question_count']==6 and report['paired_gate_input']=={'answer':None,'timeout':False}
    assert report['grounded_answer_rate'] is None and report['cost_status']=='UNKNOWN'
    print('PASS v2 evaluation failed denominator and unjudged semantic answer preserved')
    for row in run['rows']:
        if row['status']!='RECORDED':continue
        receipt=await admin.fetchrow('select response,original_question,execution_metadata from r_answer_receipts where store_id=$1 and receipt_id=$2',
            seed['store_id'],int(row['receipt_id']))
        assert json.loads(receipt['response'])==row['response']
        assert receipt['original_question']==next(c.question for c in manifest.cases if c.question_id==row['question_id'])
    print('PASS v2 evaluation outputs agree with durable DB receipts')
    out=Path(__file__).resolve().parents[1]/'tmp/r-v2-evaluation'
    out.mkdir(parents=True,exist_ok=True)
    for suffix,data in (('run',run),('report',report)):
        with (out/f"{run['run_id']}-{suffix}.json").open('x',encoding='utf-8') as handle:
            json.dump(data,handle,ensure_ascii=False,indent=2)
    bundle=dict(plan=plan,baseline=runs[:3],candidate=runs[3:6],control=runs[6:])
    for suffix,data in (('campaign',campaign),('bundle',bundle)):
        with (out/f"{run['run_id']}-{suffix}.json").open('x',encoding='utf-8') as handle:
            json.dump(data,handle,ensure_ascii=False,indent=2)
    print('PASS v2 evaluation immutable run/report artifacts written to api/tmp/r-v2-evaluation')
