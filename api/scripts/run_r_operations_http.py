"""Frozen operations challenge through real v2 ASGI HTTP and disposable PostgreSQL.

Fixed synthetic embeddings; semantic adapters OFF unless an explicitly approved
live evaluation plan is supplied. No production DB or gold-context injection.
"""
import argparse
import asyncio
from collections import Counter
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
import hashlib
import inspect
import json
from pathlib import Path
import subprocess
import sys
from time import perf_counter
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'api'))
import asyncpg
import httpx
from fastapi import FastAPI
from app.deps import create_token
from app.learn.v2_router import router, ChatRequest
from app.contracts.hashing import digest

from scripts.r_fact_evaluation import (seed, validate_challenge, candidate_fact_ids,
    cited_fact_ids, controls_challenge, positive_controls, FORMAT, evaluator_sources, validate_live_fixture_plan)

DSN='postgresql://postgres:synthetic-local-test@127.0.0.1:55440/operations_eval'
VECTOR=[1.]+[0.]*1535


def write_new(path,data):
    with path.open('x',encoding='utf-8') as stream:
        json.dump(data,stream,ensure_ascii=False,indent=2)
        stream.write('\n')


async def collect(client,db,seeded,headers,challenge,output,*,controls,stop_after_errors=0):
    validate_choice_scripts(challenge)
    sid=seeded['store_id']
    mapping=seeded['mapping']
    recorded=[]
    consecutive_errors=0
    stopped=None

    async def session(key):
        response=await client.post('/learn/v2/sessions',headers=headers,json=dict(request_id=key))
        response.raise_for_status()
        return response.json()['session_id']

    async def ask(session_id,key,question,choice=None):
        payload=dict(session_id=session_id,request_id=key,question=question,**(choice or {}))
        ChatRequest.model_validate(payload)
        start=perf_counter()
        response=await client.post('/learn/v2/chat',headers=headers,json=payload)
        body=response.json()
        row=dict(request=payload,http_status=response.status_code,response=body,
            elapsed_local_ms=round((perf_counter()-start)*1000,3),receipt_id=response.headers.get('x-answer-receipt-id'))
        if response.headers.get('x-context-revision'):
            row['context_revision']=int(response.headers['x-context-revision'])
        if response.status_code==200:
            receipt=await db.fetchrow('select response,original_question,execution_metadata from r_answer_receipts where store_id=$1 and receipt_id=$2',sid,int(row['receipt_id']))
            stored=json.loads(receipt['response']) if isinstance(receipt['response'],str) else receipt['response']
            assert body==stored and receipt['original_question']==question
            metadata=json.loads(receipt['execution_metadata']) if isinstance(receipt['execution_metadata'],str) else receipt['execution_metadata']
            row['receipt_verified']=True
            row['execution_metadata']=metadata
            if body.get('action')=='ANSWER':
                reads=[]
                for index,_ in enumerate(body.get('citations',[]),1):
                    citation=await client.get(f'/learn/v2/receipts/{row["receipt_id"]}/citations/{index}',headers=headers)
                    citation.raise_for_status()
                    reads.append(citation.json())
                row['citation_reads_verified']=bool(reads)
                row['citation_reads']=reads
        with (output/'turns.jsonl').open('a',encoding='utf-8') as stream:
            stream.write(json.dumps(row,ensure_ascii=False)+'\n')
        return row

    if not controls or not all(row['passed'] for row in controls):
        return controls,recorded,'POSITIVE_CONTROL_FAILED'

    for case in challenge['cases']:
        session_id=await session('ops-session-'+case['case_id'])
        turns=[]
        case_stop=None
        for n,expected in enumerate(case['turns'],1):
            choice=None
            if expected.get('select_option'):
                choice=offered_choice(turns[-1] if turns else None,expected['select_option'],
                    aliases=expected.get('select_option_aliases',()))
                if choice is None:
                    case_stop='REQUIRED_CHOICE_NOT_OFFERED'
                    break
            # Selecting an offered option is the whole user turn in the product
            # DTO. Keep the scripted shorthand in expected/choice_resolution.
            question=choice['option'] if choice else expected['question']
            row=await ask(session_id,f'ops-{case["case_id"]}-{n}',question,choice)
            row['turn_number']=n
            row['expected']=expected
            if choice:
                row['choice_resolution']=dict(scripted_option=expected['select_option'],
                    accepted_aliases=expected.get('select_option_aliases',[]),returned_option=choice['option'],
                    policy='frozen-exact-unique/v1')
            body=row['response']
            row['action_matches']=body.get('action')==expected['expected_action'] if row['http_status']==200 else False
            # No exact-text pseudo semantic grading. Action failures are definitive;
            # action matches require explicit output-specific semantic review later.
            row['semantic_correct']=None if row['action_matches'] else False
            candidates=row.get('execution_metadata',{}).get('candidates',[])
            row['candidate_fact_ids']=candidate_fact_ids(mapping,candidates)
            row['cited_fact_ids']=cited_fact_ids(mapping,body.get('citations',[]))
            row['required_facts_in_candidates']=set(expected['required_fact_ids'])<=set(row['candidate_fact_ids'])
            turns.append(row)
            consecutive_errors=consecutive_errors+1 if row['http_status']!=200 else 0
            if stop_after_errors and consecutive_errors>=stop_after_errors:
                stopped=f'CONSECUTIVE_API_ERRORS_{consecutive_errors}'
                break
        history=await client.get(f'/learn/v2/sessions/{session_id}/history',headers=headers)
        history.raise_for_status()
        assert all(t['request']['session_id']==session_id for t in turns)
        recorded.append(dict(case_id=case['case_id'],title=case['title'],kind=case['kind'],tier=case['tier'],
            stop_reason=case_stop,
            session_id=session_id,turns=turns,history=history.json(),
            all_actions_match=len(turns)==len(case['turns']) and all(t['action_matches'] for t in turns)))
        print(case['case_id']+': '+', '.join(t['response'].get('action',t['response'].get('error',{}).get('code','ERROR')) for t in turns),flush=True)
        if stopped:break
    return controls,recorded,stopped


def validate_choice_scripts(challenge):
    """Validate frozen aliases before any control or paid request is sent."""
    for case in challenge['cases']:
        for turn in case['turns']:
            option=turn.get('select_option');aliases=turn.get('select_option_aliases',[])
            if (not isinstance(aliases,list) or len(aliases)>10
                    or any(not isinstance(a,str) or not a.strip() or len(a)>1000 for a in aliases)
                    or len(aliases)!=len(set(aliases))):
                raise ValueError('invalid frozen case choice aliases')
            if aliases and not option:raise ValueError('case choice aliases require scripted option')
            if option is not None and (not isinstance(option,str) or not option.strip() or option in aliases):
                raise ValueError('invalid scripted case choice')


def offered_choice(previous,option,*,aliases=()):
    """Exact, unique match against pre-frozen spellings, never fuzzy inference."""
    if not previous or previous['http_status']!=200:return None
    body=previous['response']
    if (body.get('action')!='CLARIFY' or body.get('clarification_slot')!='case'
            or not body.get('context_id') or type(previous.get('context_revision')) is not int
            or previous['context_revision']<1):return None
    matches=[value for value in body.get('allowed_options',[]) if value in (option,*aliases)]
    if len(matches)!=1:return None
    return dict(option=matches[0],context_id=body['context_id'],context_revision=previous['context_revision'])


async def main(args, *, verification_hook=None):
    live_plan=None
    if args.live_plan:
        live_plan=json.loads(args.live_plan.read_text('utf-8'))
        if not args.approved_by or digest(live_plan)!=args.plan_hash:
            raise ValueError('explicit approved evaluator and exact evaluation-plan hash required')
        validate_live_fixture_plan(live_plan)
        from app.learn.general_semantics import source_hash
        if live_plan.get('source_hash')!=source_hash():
            raise ValueError('evaluation plan must pin the current source hash')
        if live_plan.get('thinking_level') not in ('minimal','low','medium','high'):
            raise ValueError('evaluation plan must specify thinking level')
    challenge=json.loads(args.input.read_text('utf-8'))
    validate_choice_scripts(challenge)
    validate_challenge(challenge)
    if live_plan and live_plan.get('challenge_hash')!=challenge['content_sha256']:
        raise ValueError('evaluation plan must pin the challenge hash')
    args.output.mkdir(parents=True,exist_ok=True)
    write_new(args.output/'frozen-challenge.json',challenge)
    source_manifest=evaluator_sources()
    write_new(args.output/'evaluator-sources.json',source_manifest)
    if live_plan:
        # D17·D18: 유료 실행은 사전등록한 분모·정답·채점기·반복·실패 처리 위에서만 돈다.
        # compare_campaign 은 registration_ref 문자열만 받으므로 입력 동일성은 여기서 막는다.
        from app.config import get_settings as _settings_for_prereg
        from app.team.prereg import CampaignRegistration, registration_hash, verify_live_plan
        if not getattr(args,'registration',None):
            raise ValueError('live run requires --registration (preregistration file)')
        registration=CampaignRegistration(**json.loads(args.registration.read_text('utf-8')))
        turn_ids=[f"{case['case_id']}#{index}"
                  for case in challenge['cases'] for index,_ in enumerate(case['turns'],start=1)]
        verify_live_plan(registration,challenge_hash=challenge['content_sha256'],
            source_manifest_hash=digest(source_manifest),
            model=_settings_for_prereg().gemini_model,turn_ids=turn_ids,
            max_krw=live_plan.get('max_krw'))
        write_new(args.output/'registration.json',dict(
            registration_ref=registration_hash(registration),
            registration=registration.model_dump(mode='json')))
    settings=SimpleNamespace(r_v2_enabled=True,r_reranker_enabled=False,r_reviewed_semantics_enabled=False,
        r_general_semantics_enabled=False,embedding_model='synthetic-fixed-1536',
        embedding_dim=1536,chat_deadline_seconds=5,search_deadline_seconds=1,chat_save_reserve_seconds=.5,
        llm_total_budget_seconds=3,request_store_per_minute=1000,request_member_per_minute=1000,
        request_member_concurrency=2,request_store_concurrency=8,
        jwt_secret='synthetic-operations-http-secret-'*3,jwt_algorithm='HS256')
    settings.gemini_model='not-called'
    if live_plan:
        settings.chat_deadline_seconds=live_plan.get('diagnostic_api_deadline_seconds',5)
        settings.llm_total_budget_seconds=live_plan.get('diagnostic_semantics_deadline_seconds',3)
    budget=None
    provider_events=[]
    async def embed(texts,**kwargs):return [VECTOR.copy() for _ in texts]
    admin=await asyncpg.connect(DSN,timeout=5)
    name='r_operations_'+uuid4().hex
    db=None
    pool=None
    created=False
    try:
        assert int(await admin.fetchval('show server_version_num'))//10000==17
        for role in ('anon','authenticated','service_role'):
            if not await admin.fetchval('select exists(select 1 from pg_roles where rolname=$1)',role):
                await admin.execute(f'create role "{role}" nologin')
        await admin.execute(f'create database "{name}"')
        created=True
        dsn=DSN.rsplit('/',1)[0]+'/'+name
        db=await asyncpg.connect(dsn,timeout=5)
        for schema in ('auth','storage','extensions','graphql'):await db.execute(f'create schema "{schema}"')
        migrations=sorted((ROOT/'supabase/migrations').glob('*.sql'))
        for migration in migrations:await db.execute(migration.read_text('utf-8'))
        print(f'Rebuilt {len(migrations)} migrations in disposable PG17 database.',flush=True)
        pool=await asyncpg.create_pool(dsn,min_size=1,max_size=3)
        with ExitStack() as stack:
            for target in ('app.deps.get_settings','app.learn.v2_router.get_settings','app.learn.request_limits.get_settings',
                'app.publish.approval.get_settings','app.reg.index_preparation.get_settings'):
                stack.enter_context(patch(target,return_value=settings))
            stack.enter_context(patch('app.learn.v2_router.get_pool',return_value=pool))
            stack.enter_context(patch('app.learn.v2_router.recorded_embeddings',embed))
            stack.enter_context(patch('app.reg.index_preparation.recorded_embeddings',embed))
            seeded=await seed(pool,db,challenge)
            control_seed=await seed(pool,db,controls_challenge())
            write_new(args.output/'fixture-manifest.json',dict(knowledge_format=FORMAT,
                challenge_hash=challenge['content_sha256'],snapshot_hash=seeded['snapshot'].snapshot_hash,
                evaluator_source_hash=digest(source_manifest),
                fixture_hash=seeded['fixture_hash'],comparability='NEW_FACT_CAMPAIGN_NOT_RAW_BASELINE'))
            write_new(args.output/'control-snapshot.json',control_seed['snapshot'].model_dump(mode='json'))
            write_new(args.output/'control-fact-map.json',control_seed['mapping'])
            write_new(args.output/'published-snapshot.json',seeded['snapshot'].model_dump(mode='json'))
            write_new(args.output/'fact-card-map.json',seeded['mapping'])
            print(f'Published {len(seeded["mapping"])} facts through actual W ledger/assembly/publication.',flush=True)
            if live_plan:
                from app.config import get_settings
                from app.learn.general_semantics import source_hash
                from app.learn.general_provider import generate
                from app.team.evaluation_budget import EvaluationBudget, evaluation_budget_scope
                from app.team.evaluation_usage import evaluation_usage_scope
                # Isolated quality diagnostic only: preserve every production
                # check and change this function's hard time cap in memory.
                # The exact evaluated function is exported for reproducibility.
                if settings.llm_total_budget_seconds != 3:
                    from app.learn import general_semantics
                    original=inspect.getsource(general_semantics.general_decision)
                    marker='asyncio.timeout(min(timeout,3.0))'
                    assert original.count(marker)==1
                    cap=float(settings.llm_total_budget_seconds)
                    if not 3 < cap <= 60:raise ValueError('diagnostic timeout outside 3..60 seconds')
                    evaluated=original.replace(marker,f'asyncio.timeout(min(timeout,{cap!r}))')
                    namespace=dict(vars(general_semantics))
                    exec(compile(evaluated,'<isolated-evaluation-timeout>','exec'),namespace)
                    stack.enter_context(patch('app.learn.general_semantics.general_decision',namespace['general_decision']))
                    write_new(args.output/'diagnostic-timeout-override.json',dict(
                        production_cap_seconds=3,evaluation_cap_seconds=cap,
                        original_sha256=hashlib.sha256(original.encode()).hexdigest(),
                        evaluated_sha256=hashlib.sha256(evaluated.encode()).hexdigest(),
                        original_source=original,evaluated_source=evaluated))
                actual=get_settings()
                if actual.gemini_model!=live_plan['paid_provider'] or not actual.gemini_api_key:
                    raise ValueError('configured model/key does not match evaluation plan')
                from google import genai
                real_client=genai.Client
                def observed_client(*client_args,**client_kw):
                    client=real_client(*client_args,**client_kw)
                    models=client.aio.models
                    async def counted(**kw):
                        result=await models.count_tokens(**kw)
                        with (args.output/'sdk-events.jsonl').open('a',encoding='utf-8') as stream:
                            stream.write(json.dumps(dict(method='count_tokens',model=kw['model'],total_tokens=result.total_tokens))+'\n')
                        return result
                    async def generated(**kw):
                        event=dict(method='generate_content',model=kw['model'],start=datetime.now(timezone.utc).isoformat())
                        started=perf_counter()
                        try:
                            result=await models.generate_content(**kw)
                            event['response']=result.model_dump(mode='json')
                            return result
                        except BaseException as exc:
                            event['exception_type']=type(exc).__name__
                            event['exception_message']=str(exc).replace(actual.gemini_api_key,'[REDACTED]')[:2000]
                            raise
                        finally:
                            event['elapsed_ms']=round((perf_counter()-started)*1000,3)
                            with (args.output/'sdk-events.jsonl').open('a',encoding='utf-8') as stream:
                                stream.write(json.dumps(event,ensure_ascii=False)+'\n')
                    return SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(
                        count_tokens=counted,generate_content=generated),aclose=client.aio.aclose))
                stack.enter_context(patch('google.genai.Client',observed_client))
                settings.gemini_model=actual.gemini_model
                settings.gemini_api_key=actual.gemini_api_key
                run_id=await db.fetchval("""insert into evaluation_runs
                    (store_id,label,code_version,prompt_version,answer_model,embedding_model,answer_mode,
                     retrieval_threshold,retrieval_strong_score)
                    values($1,'synthetic operations live','local','r-general/v2',$2,'fixed-1536','isolated',0,0)
                    returning run_id""",seeded['store_id'],settings.gemini_model)
                policy=dict(campaign_id=str(uuid4()),store_id=str(seeded['store_id']),evaluation_run_ids=[str(run_id)],
                    model=settings.gemini_model,max_calls=live_plan['max_generation_calls'],max_krw=live_plan['max_krw'],
                    max_input_tokens=live_plan['max_input_tokens_per_call'],max_output_tokens=live_plan['max_output_tokens_per_call'],
                    max_prompt_bytes=live_plan['max_prompt_bytes'],input_krw_per_million=live_plan['input_krw_per_million_ceiling'],
                    output_krw_per_million=live_plan['output_krw_per_million_ceiling'],
                    price_reference=live_plan['pricing_reference'],approved_by=args.approved_by,
                    valid_until=(datetime.now(timezone.utc)+timedelta(minutes=30)).isoformat())
                write_new(args.output/'budget-policy.json',policy)
                write_new(args.output/'evaluation-plan.json',live_plan)
                budget=EvaluationBudget(pool,policy)
                release=dict(store_id=str(seeded['store_id']),snapshot_hash=seeded['snapshot'].snapshot_hash,
                    response_style=live_plan.get('response_style','approved_original'),
                    source_hash=source_hash(),model=settings.gemini_model,thinking_level=live_plan['thinking_level'],
                    acceptance_reference='ISOLATED SYNTHETIC EVALUATION ONLY; NOT PRODUCTION ACCEPTANCE; plan '+args.plan_hash,
                    approved_by=args.approved_by,valid_until=policy['valid_until'],
                    max_input_tokens=policy['max_input_tokens'],max_output_tokens=policy['max_output_tokens'],max_prompt_bytes=policy['max_prompt_bytes'])
                write_new(args.output/'evaluation-release.json',release)
                settings.r_general_semantics_enabled=True
                settings.r_general_semantics_path=str((args.output/'evaluation-release.json').resolve())
                settings.r_general_semantics_hash=digest(release)
                stack.enter_context(patch('app.learn.general_provider.get_settings',return_value=settings))
                stack.enter_context(evaluation_usage_scope(store_id=seeded['store_id'],evaluation_run_id=str(run_id)))
                stack.enter_context(evaluation_budget_scope(budget))
                async def observed_generate(prompt,**kw):
                    event=dict(schema=kw['schema'].__name__,prompt=prompt,start=datetime.now(timezone.utc).isoformat())
                    from app.learn.general_wire import response_schema
                    event['wire_schema_hash']=digest(response_schema(kw['schema'],
                        conclusions_enabled=kw['release'].response_style=='grounded_conclusion',
                        calculation_fact_ids=kw.get('calculation_fact_ids'),question_quotes=kw.get('question_quotes')))
                    start=perf_counter()
                    try:
                        event['output']=await generate(prompt,**kw)
                        return event['output']
                    except BaseException as exc:
                        event['exception_type']=type(exc).__name__
                        event['exception_message']=str(exc).replace(actual.gemini_api_key,'[REDACTED]')[:2000]
                        raise
                    finally:
                        event['elapsed_ms']=round((perf_counter()-start)*1000,3)
                        provider_events.append(event)
                        with (args.output/'provider-events.jsonl').open('a',encoding='utf-8') as stream:
                            stream.write(json.dumps(event,ensure_ascii=False)+'\n')
                stack.enter_context(patch('app.learn.general_provider.generate',observed_generate))
            app=FastAPI()
            app.include_router(router,prefix='/learn')
            token=create_token(dict(store_id=seeded['store_id'],user_id=seeded['user_id'],role='STAFF',
                exp=datetime.now(timezone.utc)+timedelta(minutes=30)))
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://synthetic-eval') as client:
                control_token=create_token(dict(store_id=control_seed['store_id'],user_id=control_seed['user_id'],role='STAFF',
                    exp=datetime.now(timezone.utc)+timedelta(minutes=30)))
                with patch.object(settings,'r_general_semantics_enabled',False):
                    controls=await positive_controls(client,db,control_seed,{'Authorization':'Bearer '+control_token})
                from scripts.r_fact_semantic_control import semantic_control
                semantic=await semantic_control(client,db,control_seed,settings,{'Authorization':'Bearer '+control_token},args.output)
                controls.extend(semantic)
                if verification_hook is not None:
                    controls.extend(await verification_hook(client=client,db=db,pool=pool,seeded=seeded,
                        control_seed=control_seed,settings=settings,headers={'Authorization':'Bearer '+token},output=args.output))
                write_new(args.output/'controls.json',controls)
                controls,rows,stop_reason=await collect(client,db,seeded,{'Authorization':'Bearer '+token},challenge,args.output,
                    controls=controls,stop_after_errors=live_plan.get('stop_after_consecutive_api_errors',3) if live_plan else 0)
            if budget:
                account=await db.fetchrow('select reserved_calls,reserved_units,halted from r_evaluation_budgets where store_id=$1 and campaign_id=$2',seeded['store_id'],budget.policy.campaign_id)
                write_new(args.output/'budget-observation.json',dict(account) if account else {})
                usage_rows=await db.fetch("""select to_jsonb(a)-'prompt_hash' as data from ai_usage_attempts a
                    where store_id=$1 order by usage_attempt_id""",seeded['store_id'])
                write_new(args.output/'usage.json',[json.loads(r['data']) if isinstance(r['data'],str) else r['data'] for r in usage_rows])
        turns=[t for r in rows for t in r['turns']]
        sources=('api/scripts/run_r_operations_http.py','api/scripts/r_fact_evaluation.py',
            'api/scripts/r_fact_semantic_control.py','api/scripts/_fact_card_fixture.py','api/app/learn/v2_router.py','api/app/learn/planner.py',
            'api/app/learn/raw_quantity.py','api/app/learn/answer_storage.py','api/app/learn/approved_renderer.py',
            'api/app/reg/hybrid.py','api/app/publish/content.py')
        result=dict(schema_version='r_operations_http_run/v2',knowledge_format=FORMAT,
            evaluator_source_hash=digest(source_manifest),
            fixture_hash=seeded['fixture_hash'],snapshot_hash=seeded['snapshot'].snapshot_hash,comparison_group='W_FACT_ONLY',created_at=datetime.now(timezone.utc).isoformat(),
            input_hash=challenge['content_sha256'],commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
            source_hashes={f:hashlib.sha256((ROOT/f).read_bytes()).hexdigest() for f in sources},
            scope='ACTUAL_V2_ASGI_HTTP_POSTGRES_WITH_SYNTHETIC_FIXED_EMBEDDINGS',
            provider_mode='LIVE_GEMINI' if live_plan else 'NO_PAID_PROVIDER',
            settings={k:v for k,v in vars(settings).items() if not k.startswith('jwt_') and not k.endswith('_api_key')},
            migration_count=len(migrations),provider_adapter_invocations=len(provider_events),production_state_inspected=False,external_notifications_sent=False,
            scenario_count=len(rows),turn_count=len(turns),positive_controls=controls,rows=rows,
            planned_scenario_count=len(challenge['cases']),planned_turn_count=sum(len(c['turns']) for c in challenge['cases']),
            stop_reason=stop_reason,
            http_success=sum(t['http_status']==200 for t in turns),receipt_verified=sum(t.get('receipt_verified',False) for t in turns),
            action_matches=sum(t['action_matches'] for t in turns),action_counts=dict(Counter(t['response'].get('action','ERROR') for t in turns)),
            required_facts_in_candidates=sum(t['required_facts_in_candidates'] for t in turns),
            whole_chat_accuracy=None,semantic_score=None,
            limitations=['Synthetic policies and fixed embeddings; not real retrieval accuracy or W production acceptance.',
                'Semantics ON in isolated evaluation only.' if live_plan else 'Default v2 semantics flags OFF; deployed flags not inspected.',
                'Same-session follow-up questions; no gold or history injected by evaluator.',
                'Isolated elapsed time includes real model network calls when LIVE_GEMINI; fixed embeddings and diagnostic timeout differ from production.',
                'Matching action alone is not semantic success; needs output-specific review.'])
        write_new(args.output/'run.json',result)
        if stop_reason=='POSITIVE_CONTROL_FAILED':
            raise RuntimeError('fact controls failed; see controls.json and run.json')
        print(json.dumps({k:result[k] for k in ('scenario_count','turn_count','http_success','receipt_verified','action_matches','action_counts','required_facts_in_candidates')},ensure_ascii=False),flush=True)
    finally:
        # Preserve durable cost evidence even when collection raises; never erase
        # a paid attempt merely because its response/history path failed.
        if budget and db:
            for filename,query,params in (
                ('budget-observation.json','select to_jsonb(b) as data from r_evaluation_budgets b where store_id=$1 and campaign_id=$2',(seeded['store_id'],budget.policy.campaign_id)),
                ('usage.json',"select to_jsonb(a)-'prompt_hash' as data from ai_usage_attempts a where store_id=$1 order by usage_attempt_id",(seeded['store_id'],)),
                ('budget-reservations.json','select to_jsonb(r) as data from r_evaluation_reservations r where store_id=$1 and campaign_id=$2',(seeded['store_id'],budget.policy.campaign_id))):
                path=args.output/filename
                if not path.exists():
                    records=await db.fetch(query,*params)
                    data=[json.loads(r['data']) if isinstance(r['data'],str) else r['data'] for r in records]
                    write_new(path,data[0] if filename=='budget-observation.json' and data else data)
        if pool:await pool.close()
        if db:await db.close()
        if created:await admin.execute(f'drop database "{name}"')
        await admin.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--live-plan',type=Path)
    parser.add_argument('--plan-hash')
    parser.add_argument('--approved-by')
    # 유료 실행(--live-plan)에만 필요하다. scripts/register_r_campaign.py 가 만든다
    parser.add_argument('--registration',type=Path)
    asyncio.run(main(parser.parse_args()))
