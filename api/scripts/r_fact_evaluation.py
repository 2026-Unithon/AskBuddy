"""Versioned synthetic evaluation input → actual W fact publication. No provider calls."""
from collections import defaultdict
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from app.contracts.hashing import digest
from app.ingest.schemas import ExtractedAssertion
from app.reg.hybrid import read_current_index
from scripts._fact_card_fixture import seed_fact_card, publish_card

FORMAT='w-fact-ledger/v1'


def evaluator_sources():
    """Bind W/R code, prompts, schema and fixture recipe, including uncommitted edits."""
    root=Path(__file__).resolve().parents[2]
    paths=[*(root/'api/app').rglob('*.py'),*(root/'api/prompts').glob('*.txt'),
           *(root/'supabase/migrations').glob('*.sql')]
    paths.extend(root/'api/scripts'/name for name in (
        'run_r_operations_http.py','r_fact_evaluation.py','r_fact_semantic_control.py',
        '_fact_card_fixture.py','build_r_fact_challenge.py','verify_r_p4_case_context.py','verify_r_p4_split_context.py'))
    return {p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}


def validate_live_fixture_plan(plan):
    if plan.get('knowledge_format')!=FORMAT or plan.get('evaluator_source_hash')!=digest(evaluator_sources()):
        raise ValueError('live plan must pin the W fact format and current evaluator source hash')


def challenge_hash(value):
    return hashlib.sha256(json.dumps({k:v for k,v in value.items() if k!='content_sha256'},
                                    ensure_ascii=False,sort_keys=True).encode()).hexdigest()


def freeze_challenge(original):
    if original.get('content_sha256')!=challenge_hash(original):
        raise ValueError('source challenge hash mismatch')
    result=deepcopy(original)
    result.update(schema_version='r_operations_challenge/v2',knowledge_format=FORMAT,
        parent_challenge_hash=original['content_sha256'],status='FACT_FIXTURE_NOT_EVALUATED')
    for fact in result['facts']:
        # Preserve the entire approved rule; do not guess new structured conditions.
        fact['w_assertion']=dict(local_ref=fact['fact_id'],subject=fact['category'],
            attribute='rule_'+fact['fact_id'],value=fact['assertion'],
            original_assertion=fact['assertion'],confidence=1.0)
    result['representation_note']='Synthetic extraction fixture; actual W ledger/assembly/publication. Not extraction quality or comparable to historical RAW scores.'
    result['content_sha256']=challenge_hash(result)
    validate_challenge(result)
    return result


def validate_challenge(challenge):
    if challenge.get('knowledge_format')!=FORMAT or challenge.get('content_sha256')!=challenge_hash(challenge):
        raise ValueError('frozen W fact challenge and matching hash required; convert historical input first')
    seen=set()
    for fact in challenge['facts']:
        if fact['fact_id'] in seen:raise ValueError('duplicate evaluation fact id')
        seen.add(fact['fact_id'])
        item=ExtractedAssertion.model_validate(fact['w_assertion'])
        if item.original_assertion!=fact['assertion'] or item.local_ref!=fact['fact_id']:
            raise ValueError('fixture must preserve approved assertion and evaluation id')
    for case in challenge['cases']:
        for turn in case['turns']:
            if not set(turn['required_fact_ids'])<=seen:raise ValueError('unknown required fact id')


async def seed(pool,db,challenge):
    validate_challenge(challenge)
    uid=await db.fetchval("insert into users(name,role) values('합성 평가 점주','OWNER') returning user_id")
    sid=await db.fetchval("insert into stores(owner_id,store_name,business_type) values($1,'합성 사실 평가','CAFE') returning store_id",uid)
    mid=await db.fetchval("insert into store_members(store_id,user_id,member_role) values($1,$2,'OWNER') returning member_id",sid,uid)
    await db.execute("insert into task_categories(store_id,category_name) values($1,'기타') on conflict do nothing",sid)
    groups=defaultdict(list)
    for fact in challenge['facts']:groups[fact['category']].append(fact)
    for category,facts in groups.items():
        await seed_fact_card(pool,store_id=sid,owner_user_id=uid,title=category+' 합성 정책',
            assertions=[ExtractedAssertion.model_validate(f['w_assertion']) for f in facts])
    cards=await db.fetch('select card_id from knowledge_cards where store_id=$1 order by card_id',sid)
    for card in cards:
        await publish_card(pool,store_id=sid,member_id=mid,actor_user_id=uid,card_id=card['card_id'])
    snapshot,_,_=await read_current_index(db,store_id=sid)
    if snapshot.raw_spans or not snapshot.fact_revisions:raise ValueError('actual W fact-only publication required')
    mapping=[]
    for item in challenge['facts']:
        authored=item['w_assertion']
        matches=[f for f in snapshot.fact_revisions if f.subject==authored['subject']
                 and f.predicate==authored['attribute'] and f.original_assertion==item['assertion']]
        if len(matches)!=1:raise ValueError('evaluation fact must map to exactly one approved revision: '+item['fact_id'])
        fact=matches[0]
        references=[dict(card_id=c.card_id,card_version_id=c.card_version_id,block_id=b.block_id,
                         fact_revision_id=fact.fact_revision_id)
                    for c in snapshot.cards for b in c.blocks if fact.fact_revision_id in b.fact_revision_ids]
        if not references:raise ValueError('unpublished evaluation fact')
        mapping.append(dict(fact_id=item['fact_id'],fact_revision_id=fact.fact_revision_id,
            entity_id=fact.entity_id,assertion=fact.assertion,references=references,
            provenance=[p.model_dump(mode='json') for p in fact.provenance]))
    mapped={m['fact_revision_id'] for m in mapping}
    if mapped!={f.fact_revision_id for f in snapshot.fact_revisions}:raise ValueError('unmapped facts in fixture')
    staff=await db.fetchval("insert into users(name,role) values('합成 평가 직원','STAFF') returning user_id")
    await db.execute("insert into store_members(store_id,user_id,member_role) values($1,$2,'STAFF')",sid,staff)
    return dict(store_id=sid,user_id=staff,snapshot=snapshot,mapping=mapping,
        fixture_hash=digest(dict(knowledge_format=FORMAT,challenge_hash=challenge['content_sha256'],
            snapshot_hash=snapshot.snapshot_hash,mapping=mapping)))


def candidate_fact_ids(mapping,candidates):
    refs={(str(c.get('card_id')),str(c.get('card_version_id')),c.get('block_id')) for c in candidates}
    return sorted(m['fact_id'] for m in mapping if any(
        (r['card_id'],r['card_version_id'],r['block_id']) in refs for r in m['references']))


def cited_fact_ids(mapping,citations):
    refs={(str(c.get('card_id')),str(c.get('card_version_id')),c.get('block_id'),c.get('fact_revision_id')) for c in citations}
    return sorted(m['fact_id'] for m in mapping if any(
        (r['card_id'],r['card_version_id'],r['block_id'],r['fact_revision_id']) in refs for r in m['references']))


def controls_challenge():
    facts=[]
    for key,temp,value in [('CONTROL_HOT','HOT','225'),('CONTROL_ICE','ICE','250')]:
        text=f'{temp} 검증음료 우유 {value}ml'
        facts.append(dict(fact_id=key,category='검증음료',assertion=text,w_assertion=dict(
            local_ref=key,subject='검증음료',attribute='milk_amount',value=value,unit='ml',
            variant=temp,original_assertion=text,confidence=1.0)))
    result=dict(schema_version='r_operations_controls/v1',knowledge_format=FORMAT,facts=facts,cases=[])
    result['content_sha256']=challenge_hash(result)
    return result


async def positive_controls(client,db,seeded,headers):
    """Separate store: control facts never enter the scored challenge's retrieval universe."""
    response=await client.post('/learn/v2/sessions',headers=headers,json={'request_id':'fact-control-session'})
    response.raise_for_status()
    session=response.json()['session_id']
    results=[]
    choice={}
    for n,(question,action,fids) in enumerate([
        ('HOT 검증음료 우유 얼마나?','ANSWER',['CONTROL_HOT']),
        ('검증음료 우유 얼마나?','CLARIFY',[]),('ICE','ANSWER',['CONTROL_ICE'])]):
        body=dict(request_id=f'fact-control-{n}',session_id=session,question=question,**choice)
        response=await client.post('/learn/v2/chat',headers=headers,json=body)
        if response.status_code!=200:
            # 상태 코드만 던지면 유료 실행에서 무엇이 막았는지 알 수 없다. 서버 오류 코드를 싣는다
            raise RuntimeError(f'control turn {n} failed: HTTP {response.status_code} {response.text[:800]}')
        data=response.json();receipt=response.headers['x-answer-receipt-id']
        saved=await db.fetchrow('select response,original_question from r_answer_receipts where store_id=$1 and receipt_id=$2',seeded['store_id'],int(receipt))
        stored=json.loads(saved['response']) if isinstance(saved['response'],str) else saved['response']
        ok=data==stored and saved['original_question']==question and data['action']==action
        if action=='CLARIFY':
            ok=ok and 'ICE' in data['allowed_options'] and data['clarification_slot']=='temperature'
            if ok:choice=dict(context_id=data['context_id'],context_revision=int(response.headers['x-context-revision']),option='ICE')
        else:
            ok=ok and cited_fact_ids(seeded['mapping'],data.get('citations',[]))==fids
            for order,citation in enumerate(data.get('citations',[]),1):
                detail=await client.get(f'/learn/v2/receipts/{receipt}/citations/{order}',headers=headers)
                ok=ok and detail.status_code==200 and detail.json()['source_kind']=='OWNER_TEXT'
        results.append(dict(request=body,response=data,passed=ok,receipt_id=receipt))
        if not ok:break
    return results
