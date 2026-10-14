"""P4 actual W fact + HTTP context controls. Synthetic adapters, zero paid calls."""
import argparse
import asyncio
from datetime import datetime,timedelta,timezone
import json
from pathlib import Path
import sys
from time import perf_counter
from types import SimpleNamespace
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'api'))
from app.contracts.hashing import digest
from app.deps import create_token
from app.learn.general_semantics import GeneralProposal,source_hash
from scripts.r_fact_evaluation import freeze_challenge,challenge_hash
from scripts import run_r_operations_http as runner

ORIGINAL='A는 결제 상태 미확인, B는 환불 승인 대기야. 둘 다 다음 담당자에게 넘길 때 뭘 적어?'
AMBIGUOUS='그 건은 메시지 읽었대. 인계 완료로 해도 돼?'
CORRECTION='A는 결제 완료로 정정해. B는 그대로 두고 둘 다 인계해줘.'


def challenge():
    facts=[dict(fact_id=fid,category=subject,assertion=text) for fid,subject,text in (
        ('HANDOFF','인계기록','인계에는 사건번호, 현재 상태, 다음 조치, 기한, 담당자를 적는다. 읽음만으로 완료가 아니며 지정 인수자의 업무 인수 확인이 필요하다.'),
        ('PAYMENT','결제확인','결제 상태 미확인 건은 대기를 유지하고 당직 관리자에게 확인을 요청한다. 결제 완료로 확인되면 완료 상태를 기록한다.'),
        ('REFUND','환불확인','환불 승인 대기 건은 승인 대기를 유지하고 점주 승인 확인을 다음 조치로 기록한다.'))]
    raw=dict(facts=facts,cases=[]);raw['content_sha256']=challenge_hash(raw)
    return freeze_challenge(raw)


async def verify(*,client,db,pool,seeded,control_seed,settings,headers,output):
    snap=seeded['snapshot'];sid=seeded['store_id'];checks=[];turns=[];calls=[];mode='both'
    mapping={m['fact_id']:m for m in seeded['mapping']}
    refs={k:dict(card_id=m['references'][0]['card_id'],card_version_id=m['references'][0]['card_version_id'],
        block_id=m['references'][0]['block_id'],fact_revision_ids=[m['fact_revision_id']],raw_span_id=None) for k,m in mapping.items()}
    def check(name,ok):
        checks.append(dict(control=name,passed=bool(ok)))
        assert ok,name
    def ev(payload,text):
        texts=[*payload['user_turns'],payload['question']]
        at=max(i for i,t in enumerate(texts) if text in t)
        return dict(turn_id=at,quote=text)
    async def provider(prompt,*,schema,**unused):
        req=json.loads(prompt.rsplit('\n',1)[1]);calls.append(dict(mode=mode,schema=schema.__name__,request=req))
        if schema is GeneralProposal:
            p=req['input'];base=dict(snapshot_id=p['snapshot_id'],knowledge_revision=p['knowledge_revision'])
            raw=dict(input_hash=p['input_hash'],snapshot_hash=p['snapshot_hash'],slots=[],parts=[],obligations=[],interpretation=None)
            if mode=='clarify':
                at=ev(p,ORIGINAL)['turn_id']
                return dict(raw,plan=dict(**base,action='CLARIFY',clarification_slot='case',allowed_options=['A','B']),
                    case_options=[dict(label=x,turn_id=at,question_quote=ORIGINAL) for x in ('A','B')])
            if mode=='selected':
                check('selected case and original A/B evidence preserved',req['confirmed_slots']=={'case':'A'} and ORIGINAL in p['user_turns'])
            if mode=='recovery':check('failed correction preserved as user evidence',CORRECTION in p['user_turns'])
            current=mode in ('correction-fail','recovery')
            state='결제 완료' if current else '결제 상태 미확인'
            cases=[] if mode=='topic' else [('A',state)] if mode=='selected' else [('A',state),('B','환불 승인 대기')]
            required=[];conclusions=[]
            for name,state in cases:
                evidence=[ev(p,name),ev(p,state)]
                required.append(dict(subject=evidence[0],state=evidence[1]))
                keys=['HANDOFF','PAYMENT' if name=='A' else 'REFUND']
                text=(f'A는 {state} 상태를 기록하고 '+('결제 완료 기록을 인계하세요.' if current else '대기를 유지하며 당직 관리자에게 확인을 요청하세요.')) if name=='A' else 'B는 환불 승인 대기를 유지하고 점주 승인 확인을 다음 조치로 기록하세요.'
                if mode=='selected':
                    evidence.append(ev(p,'메시지 읽었대'))
                    required[0]['state']=evidence[-1]
                    text+=' A의 메시지를 읽었다는 사실만으로 인계 완료가 아니며 지정 인수자의 업무 인수 확인이 필요합니다.'
                conclusions.append(dict(statement=text,question_quote=p['question'],user_evidence=evidence,references=[refs[k] for k in keys]))
            if mode=='topic':
                conclusions=[dict(statement='사건번호, 현재 상태, 다음 조치, 기한, 담당자를 기록하세요.',question_quote=p['question'],
                    user_evidence=[ev(p,p['question'])],references=[refs['HANDOFF']])]
            selected_keys=['HANDOFF'] if mode=='topic' else ['HANDOFF','PAYMENT'] if mode=='selected' else list(refs)
            raw.update(plan=dict(**base,action='ANSWER',selected_blocks=[refs[k] for k in selected_keys]),conclusions=conclusions,
                case_requirements=dict(scope='CASE_ACTIONS' if cases else 'NOT_APPLICABLE',rationale='Synthetic question-first requirements',cases=required))
            for key in selected_keys:
                fact=snap.fact(mapping[key]['fact_revision_id'])
                raw['parts'].append(dict(plan=dict(**base,action='ANSWER',selected_blocks=[refs[key]]),
                    interpretation=dict(entity_id=fact.entity_id,predicate=fact.predicate,variants=[],
                        target_fact_ids=[fact.fact_revision_id],not_applicable_fact_ids=[fact.fact_revision_id]),
                    slots=[dict(slot=k,value=v,question_quote=p['question']) for k,v in [('entity',fact.entity_id),('predicate',fact.predicate)]]))
            return raw
        p=req['proposal'];cs=p['conclusions'];selected={f for b in p['plan']['selected_blocks'] for f in b['fact_revision_ids']}
        verdict=dict(request_hash=req['request_hash'],supported=True,unresolved=[],**req['selected_reference_check'],
            checked_user_turn_ids=[t['turn_id'] for t in req['dialogue_turns']],checked_conclusion_ids=list(range(len(cs))),
            candidate_coverage=[dict(reference=r,required=bool(set(r['fact_revision_ids'])&selected),rationale='Synthetic required references') for r in req['candidate_reference_units']],
            rule_coverage=[],situation_review=[],case_action_review=None)
        if mode=='clarify':return verdict
        for rule in req['selected_rules']:
            fid=rule['reference']['fact_revision_ids'][0]
            n=next(i for i,c in enumerate(cs) if any(fid in r['fact_revision_ids'] for r in c['references']))
            verdict['rule_coverage'].append(dict(rule_id=rule['rule_id'],required=True,conclusion_unit_id=f'c{n}s0',rationale='Synthetic application, not semantic truth'))
        verdict['situation_review']=[dict(conclusion_unit_id=u['unit_id'],status='NO_CASE_FACTS' if mode=='topic' else 'GROUNDED_CASE_FACTS',
            user_evidence=[] if mode=='topic' else cs[u['conclusion_id']]['user_evidence'],rationale='Synthetic grounded state audit') for u in req['conclusion_units']]
        required=p['case_requirements']
        verdict['case_action_review']=dict(scope=required['scope'],rationale='Synthetic independent question audit',cases=[
            dict(c,conclusion_id=n,next_action_quote=cs[n]['statement'],
                state_unit_id='c0s1' if mode=='selected' else f'c{n}s0') for n,c in enumerate(required['cases'])])
        if mode in ('scope-fail','correction-fail'):verdict['case_action_review']=dict(scope='NOT_APPLICABLE',rationale='Deliberately narrowed to general fields',cases=[])
        if mode=='unsupported':verdict['situation_review'][0]['status']='UNSUPPORTED_CASE_FACTS'
        return verdict

    release=dict(store_id=str(sid),snapshot_hash=snap.snapshot_hash,source_hash=source_hash(),model='synthetic-p4',
        response_style='grounded_conclusion',acceptance_reference='LOCAL SYNTHETIC CONTRACT CHECK ONLY',approved_by='synthetic fixture',
        valid_until=(datetime.now(timezone.utc)+timedelta(minutes=30)).isoformat(),max_input_tokens=100000,max_output_tokens=1000,max_prompt_bytes=200000)
    path=output/'p4-release.json';runner.write_new(path,release)
    from app.learn import v2_router
    original_save=v2_router.save_answer;original_search=v2_router.hybrid_search;timing={}
    async def timed_save(*a,**kw):
        start=perf_counter()
        try:return await original_save(*a,**kw)
        finally:timing['save_ms']=round((perf_counter()-start)*1000,3)
    async def timed_search(*a,**kw):
        start=perf_counter()
        try:return await original_search(*a,**kw)
        finally:timing['search_ms']=round((perf_counter()-start)*1000,3)
    async def session(key):
        r=await client.post('/learn/v2/sessions',headers=headers,json=dict(request_id=key));r.raise_for_status();return r.json()['session_id']
    async def ask(session_id,key,q,choice=None,expected=200):
        key='verify-'+key
        timing.clear();start=perf_counter();at=len(calls)
        request=dict(session_id=session_id,request_id=key,question=q,**(choice or {}))
        r=await client.post('/learn/v2/chat',headers=headers,json=request)
        row=dict(request=request,http_status=r.status_code,response=r.json(),timings=dict(timing,total_ms=round((perf_counter()-start)*1000,3)))
        turns.append(row);check(key+' HTTP',r.status_code==expected)
        if expected==200:
            rid=int(r.headers['x-answer-receipt-id']);row['receipt_id']=rid
            saved=await db.fetchrow('select response,original_question,execution_metadata from r_answer_receipts where store_id=$1 and receipt_id=$2',sid,rid)
            check(key+' receipt equality',json.loads(saved['response'])==r.json() and saved['original_question']==q)
            meta=json.loads(saved['execution_metadata']);row['execution_metadata']=meta
            audit=meta.get('general_semantics') or {}
            row['replayed']=r.headers.get('x-answer-replayed')=='true'
            if not row['replayed']:
                row['timings'].update(proposal_ms=audit.get('proposal_ms'),verification_ms=audit.get('verification_ms'))
            for n,c in enumerate(r.json().get('citations',[]),1):
                d=await client.get(f'/learn/v2/receipts/{rid}/citations/{n}',headers=headers)
                check(key+f' fact citation {n}',d.status_code==200 and d.json()['source_kind']=='OWNER_TEXT' and c['fact_revision_id'] is not None and c['raw_span_id'] is None)
        else:
            check(key+' no receipt or pending',not await db.fetchval('select exists(select 1 from r_answer_receipts where store_id=$1 and request_id=$2)',sid,key)
                and await db.fetchval('select count(*) from pending_questions where store_id=$1',sid)==0)
        row['adapter_calls']=len(calls)-at
        return r
    with patch.multiple(settings,r_general_semantics_enabled=True,gemini_model='synthetic-p4'), \
         patch.object(settings,'r_general_semantics_path',str(path.resolve()),create=True), \
         patch.object(settings,'r_general_semantics_hash',digest(release),create=True), \
         patch('app.learn.general_provider.generate',provider),patch.object(v2_router,'save_answer',timed_save),patch.object(v2_router,'hybrid_search',timed_search):
        try:
            s=await session('p4-session')
            first=await ask(s,'p4-both',ORIGINAL)
            check('A and B have separate next actions','당직 관리자' in first.json()['message'] and '점주 승인' in first.json()['message'])
            mode='clarify';clarify=await ask(s,'p4-clarify',AMBIGUOUS)
            check('case options from user only',clarify.json()['allowed_options']==['A','B'])
            choice=dict(context_id=clarify.json()['context_id'],context_revision=int(clarify.headers['x-context-revision']),option='A')
            mode='selected';selected=await ask(s,'p4-selected','A',choice)
            check('paraphrase and outstanding payment action preserved','메시지를 읽었다는' in selected.json()['message'] and '당직 관리자' in selected.json()['message'])
            replay_calls=len(calls);replay=await ask(s,'p4-selected','A',choice)
            check('replay does not regenerate',replay.headers.get('x-answer-replayed')=='true' and len(calls)==replay_calls)
            await ask(s,'p4-stale-choice','A',choice,expected=422)
            mode='correction-fail';await ask(s,'p4-correction-fail',CORRECTION,expected=503)
            mode='recovery';recovered=await ask(s,'p4-recovery','그 상태대로 다시 알려줘.')
            check('recovery uses failed correction without changing B','결제 완료' in recovered.json()['message'] and 'B는 환불 승인 대기' in recovered.json()['message']
                and bool(turns[-1]['execution_metadata']['dialogue_failed_turn_ids']))
            mode='topic';topic=await ask(s,'p4-topic','사건과 무관하게 일반 인계 양식의 항목만 알려줘.')
            check('new topic does not inherit named case requirements',turns[-1]['execution_metadata']['general_semantics']['case_requirements']['scope']=='NOT_APPLICABLE')
            for mode in ('scope-fail','unsupported'):
                bad=await ask(await session('p4-'+mode),'p4-'+mode,ORIGINAL,expected=503)
                check(mode+' rejection envelope',bad.json()['error']['code']=='GENERAL_VERIFICATION_REJECTED')
            foreign=create_token(dict(store_id=control_seed['store_id'],user_id=control_seed['user_id'],role='STAFF',exp=datetime.now(timezone.utc)+timedelta(minutes=10)))
            for url in (f'/learn/v2/sessions/{s}/history',f'/learn/v2/receipts/{turns[0]["receipt_id"]}/citations/1'):
                r=await client.get(url,headers={'Authorization':'Bearer '+foreign});check('foreign '+url,r.status_code==404)
            history=await client.get(f'/learn/v2/sessions/{s}/history',headers=headers);check('own history accessible',history.status_code==200)
            from scripts.verify_r_p4_split_context import verify_split
            checks.extend(await verify_split(client,db,pool,settings,output))
        finally:
            runner.write_new(output/'p4-turns.json',turns);runner.write_new(output/'p4-checks.json',checks)
            runner.write_new(output/'p4-synthetic-adapter.json',calls)
    return checks


async def main(output):
    output.mkdir(parents=True,exist_ok=False)
    p=output/'challenge.json';runner.write_new(p,challenge())
    args=SimpleNamespace(input=p,output=output/'run',live_plan=None,approved_by=None,plan_hash=None)
    with patch('google.genai.Client',side_effect=AssertionError('No external SDK allowed')):
        await runner.main(args,verification_hook=verify)
    print('PASS P4 real fact HTTP case/selection/correction/recovery controls; zero paid calls')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    asyncio.run(main(parser.parse_args().output))
