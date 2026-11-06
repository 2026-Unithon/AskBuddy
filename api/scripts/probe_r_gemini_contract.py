"""Explicitly bounded provider-protocol diagnosis, not a quality evaluation.

One unique configuration per invocation, no retries. A new diagnostic campaign
allows inspected HTTP 400 rejections to remain UNKNOWN while another distinct
configuration is tested. All attempts consume their full reservation (108 KRW),
including 400s, crashes and unknown usage. Other unknown failures halt it.
Uses a disposable local PG17 database and durable common usage receipts.
"""
import argparse
import asyncio
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import sys
from time import perf_counter
from uuid import uuid4

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'api'))
import asyncpg
from app.config import get_settings
from app.contracts.hashing import digest
from app.contracts.usage import UsageContext
from app.learn.answer_usage import observe_answer
from app.learn.general_provider import usage_tokens
from app.usage.recorder import DbUsageSink,attempt
from scripts.run_r_operations_http import DSN


def save(path,data):
    with path.open('x',encoding='utf-8') as f:json.dump(data,f,ensure_ascii=False,indent=2)


async def main(args):
    from google import genai
    from google.genai import types
    settings=get_settings()
    root=args.output.resolve()
    if args.initialize:
        root.mkdir(parents=True,exist_ok=False)
        admin=await asyncpg.connect(DSN)
        for role in ('anon','authenticated','service_role'):
            if not await admin.fetchval('select exists(select 1 from pg_roles where rolname=$1)',role):
                await admin.execute(f'create role "{role}" nologin')
        name='r_transport_'+uuid4().hex
        await admin.execute(f'create database "{name}"')
        await admin.close()
        db=await asyncpg.connect(DSN.rsplit('/',1)[0]+'/'+name)
        try:
            for schema in ('auth','storage','extensions','graphql'):await db.execute(f'create schema "{schema}"')
            for p in sorted((ROOT/'supabase/migrations').glob('*.sql')):await db.execute(p.read_text('utf-8'))
            uid=await db.fetchval("insert into users(name,role) values('합성 호환성 점주','OWNER') returning user_id")
            sid=await db.fetchval("insert into stores(owner_id,store_name,business_type) values($1,'합성 전송 진단','CAFE') returning store_id",uid)
            run=await db.fetchval("""insert into evaluation_runs(store_id,label,code_version,prompt_version,answer_model,embedding_model,answer_mode,retrieval_threshold,retrieval_strong_score)
                values($1,'transport diagnosis only','local','protocol',$2,'not-called','isolated',0,0) returning run_id""",sid,settings.gemini_model)
            await db.execute('create table transport_probe_budget(store_id bigint primary key, reserved_calls int not null default 0, halted boolean not null default false)')
            await db.execute('create table transport_probe_calls(store_id bigint not null, label text not null, request_hash text not null, primary key(store_id,label), unique(store_id,request_hash))')
            await db.execute('insert into transport_probe_budget(store_id) values($1)',sid)
            save(root/'plan.json',dict(kind='PROTOCOL_DIAGNOSTIC_NOT_QUALITY',database=name,store_id=sid,run_id=run,model=settings.gemini_model,
                approved_by='User: investigate and fix after rejected real Gemini test',max_calls=8,max_reserved_krw=864,
                max_input_tokens=16000,max_output_tokens=4000,max_prompt_bytes=100000,
                input_krw_per_million_ceiling=3000,output_krw_per_million_ceiling=15000,
                input_usd_per_million='.75',output_usd_per_million='3.75',
                previous_unknown_reservation_krw=108,authorization='New bounded protocol diagnosis, preserving the previous halted run; below the previously selected KRW10000 ceiling.',
                stop_policy='Every unique config costs a full 108 KRW reservation. Expected HTTP400 rejections remain UNKNOWN, not zero. Other unknown/errors/overages halt. No retries; max 8 attempts across invocations.',
                created_at=datetime.now(timezone.utc).isoformat()))
        finally:await db.close()
        print('Initialized bounded diagnostic, 8 unique requests / KRW864 ceiling.')
        return
    plan=json.loads((root/'plan.json').read_text('utf-8'))
    assert plan['model']==settings.gemini_model and settings.gemini_api_key
    assert plan['database'].startswith('r_transport_') and len(plan['database'])==44
    pool=await asyncpg.create_pool(DSN.rsplit('/',1)[0]+'/'+plan['database'],min_size=1,max_size=2)
    client=None
    try:
        sid=plan['store_id']
        if args.close:
            async with pool.acquire() as db:await db.execute('update transport_probe_budget set halted=true where store_id=$1',sid)
            save(root/'closed.json',dict(reason='Diagnosis complete. No further requests; counters/reservations retained.'))
            print('Diagnostic closed.')
            return
        if args.reconcile:
            # Correct a diagnosed observation bug using the original successful
            # response, never a 400, timeout, or invented zero. Counters stay put.
            records=[json.loads(p.read_text('utf-8')) for p in root.glob('*-result.json')]
            assert records and all(r['status']=='RESPONSE' for r in records)
            for r in records:
                tokens=usage_tokens(r['usage'])
                assert all(type(n)is int and n>=0 for n in tokens)
                assert tokens[0]<=16000 and sum(tokens[1:])<=4000
            async with pool.acquire() as db:await db.execute('update transport_probe_budget set halted=false where store_id=$1',sid)
            save(root/'usage-reconciliation.json',dict(reason='Omitted zero thoughts proven by prompt+visible=provider total; original observations retained.',records=[r['label'] for r in records],reservations_refunded=False))
            print('Reconciled successful provider total; no counters or original results reset.')
            return
        if args.export:
            async with pool.acquire() as db:
                data=await db.fetch("select to_jsonb(a) data from ai_usage_attempts a where store_id=$1 order by usage_attempt_id",sid)
                save(root/f'usage-{len(list(root.glob("usage-*.json")))}.json',[json.loads(x['data']) for x in data])
                print(dict(await db.fetchrow('select * from transport_probe_budget where store_id=$1',sid)))
            return
        assert args.label and args.config
        cfg=json.loads(args.config.read_text('utf-8'))
        config=types.GenerateContentConfig.model_validate(cfg)
        assert config.max_output_tokens==4000 and config.temperature==0 and config.response_mime_type=='application/json'
        assert config.automatic_function_calling.disable and not config.tools and not config.cached_content
        prompt=args.prompt.read_text('utf-8') if args.prompt else json.loads((ROOT/'output/r-operations-challenge-20261006/gemini-live-02/provider-events.jsonl').read_text('utf-8').splitlines()[0])['prompt']
        counted_prompt=prompt+'\nJSON schema:\n'+json.dumps(config.response_json_schema,ensure_ascii=False)
        assert len(counted_prompt.encode())<=100000
        request=dict(model=settings.gemini_model,prompt=prompt,config=cfg)
        key=digest(request)
        async with pool.acquire() as db,db.transaction():
            account=await db.fetchrow('select * from transport_probe_budget where store_id=$1 for update',sid)
            assert not account['halted'] and account['reserved_calls']<8,'diagnostic halted/exhausted'
            await db.execute('insert into transport_probe_calls(store_id,label,request_hash) values($1,$2,$3)',sid,args.label,key)
            await db.execute('update transport_probe_budget set reserved_calls=reserved_calls+1 where store_id=$1',sid)
        save(root/(args.label+'-request.json'),request)
        async def capture(request):
            if request.url.path.endswith(':generateContent'):
                save(root/(args.label+'-wire.json'),json.loads(request.content))
        client=genai.Client(api_key=settings.gemini_api_key,http_options=types.HttpOptions(timeout=45000,
            retry_options=types.HttpRetryOptions(attempts=1),async_client_args={'event_hooks':{'request':[capture]}}))
        context=UsageContext(store_id=str(sid),stage='ANSWER',cost_phase='OPERATING',cost_purpose='EVALUATION',
            logical_call_id='protocol-'+args.label,evaluation_run_id=str(plan['run_id']))
        result=dict(label=args.label,reserved_krw=108,usage=None,request_hash=key)
        halted=False;started=perf_counter()
        try:
            async with attempt(DbUsageSink(pool),context,model=settings.gemini_model,prompt_hash=digest(prompt),config_hash=digest(cfg)) as rec:
                counted=await client.aio.models.count_tokens(model=settings.gemini_model,contents=counted_prompt)
                result['counted_tokens']=counted.total_tokens
                assert type(counted.total_tokens)is int and counted.total_tokens*1.1<=16000
                response=await client.aio.models.generate_content(model=settings.gemini_model,contents=prompt,config=config)
                observe_answer(rec,response)
                result.update(status='RESPONSE',text=response.text,usage=response.usage_metadata.model_dump(mode='json') if response.usage_metadata else None,
                    model_version=response.model_version,finish_reasons=[c.finish_reason for c in response.candidates or []])
                usage=result['usage'] or {}
                tokens=usage_tokens(usage)
                halted=not all(type(n)is int and n>=0 for n in tokens)
                if not halted:halted=tokens[0]>16000 or sum(tokens[1:])>4000
        except Exception as exc:
            code=getattr(exc,'code',None)
            result.update(status='REJECTED' if code==400 else 'FAILED',error_code=code,error_type=type(exc).__name__,
                error=str(exc).replace(settings.gemini_api_key,'[REDACTED]')[:1500])
            halted=code!=400
        finally:
            result['elapsed_ms']=round((perf_counter()-started)*1000,3)
            result['halted']=halted
            save(root/(args.label+'-result.json'),result)
            if halted:
                async with pool.acquire() as db:await db.execute('update transport_probe_budget set halted=true where store_id=$1',sid)
        print(json.dumps({k:v for k,v in result.items() if k not in ('text','usage')},ensure_ascii=False))
    finally:
        if client:await client.aio.aclose()
        await pool.close()


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--initialize',action='store_true');p.add_argument('--export',action='store_true');p.add_argument('--reconcile',action='store_true');p.add_argument('--close',action='store_true');p.add_argument('--label');p.add_argument('--config',type=Path);p.add_argument('--prompt',type=Path)
    asyncio.run(main(p.parse_args()))
