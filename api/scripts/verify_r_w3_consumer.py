"""Actual W2 ledger -> synthetic W3 DTO -> actual R DB consumer.

Run by the disposable schema harness. This does not claim W3 assembly/model quality.
"""
from unittest.mock import patch

import asyncpg

from app.config import get_settings
from app.contracts.snapshot import KnowledgeContent, FactRevision, FactProvenance, PublishedCard
from app.contracts.card import CardBlock
from app.contracts.usage import UsageContext
from app.ingest.fact_ledger import record_owner_answer_fact
from app.learn.answer_storage import save_answer
from app.learn.approved_renderer import RENDERER_VERSION
from app.learn.owner_delivery import submit_owner_answer
from app.learn.planner import decide
from app.learn import v2_router
from app.publish.empty import ensure_initial_publication
from app.publish.approval import snapshot_hash_for
from app.publish.service import publish_knowledge
from app.reg.hybrid import SearchResult, read_current_index, hybrid_search
from app.reg.index_preparation import prepare_index, activate_prepared_index


async def verify(pool, db):
    uid = await db.fetchval("insert into users(name,role) values('합성 출처 점주','OWNER') returning user_id")
    sid = await db.fetchval("insert into stores(owner_id,store_name,business_type) values($1,'합성 출처 매장','CAFE') returning store_id", uid)
    mid = await db.fetchval("insert into store_members(store_id,user_id,member_role) values($1,$2,'OWNER') returning member_id", sid, uid)
    session = await db.fetchval("insert into chat_sessions(store_id,member_id,contract_version) values($1,$2,'v2') returning session_id", sid, mid)
    await ensure_initial_publication(pool, store_id=sid, member_id=mid, user_id=uid)
    empty, _, revision = await read_current_index(db, store_id=sid)
    assert not empty.cards
    question = 'HOT 라테 우유 얼마나?'

    async def save(found, key):
        decision = decide(found, store_id=sid, question=question)
        return await save_answer(pool, store_id=sid, member_id=mid, session_id=session,
            request_id=key, question=question, snapshot=found.snapshot, plan=decision.plan,
            resolved=decision.resolved, confirmed_slots=decision.confirmed_slots,
            semantic_context=decision.semantic_context)

    pending = await save(SearchResult(empty, revision, (), question), 'w3-empty-first-question')
    assert pending.response.action == 'ESCALATE' and pending.response.pending_id
    assert await db.fetchval('select count(*) from r_index_documents where store_id=$1', sid) == 0
    print('PASS W3 consumer initial empty publication -> durable first pending without embedding')
    answer = await submit_owner_answer(pool, store_id=sid, member_id=mid,
        question_id=int(pending.response.pending_id), request_id='w3-owner-first-answer',
        answer='HOT 라테 우유 225ml', expected_revision=0)
    aid = int(answer['owner_answer_id'])
    async with db.transaction():
        fid, rid = await record_owner_answer_fact(db, sid, owner_answer_id=aid, subject='라테',
            attribute='milk_amount', value='225', unit='ml', variant='HOT', polarity='AFFIRM',
            conditions=[], exceptions=[], step_order=None, original_assertion='HOT 라테 우유 225ml', actor_id=uid)
    row = await db.fetchrow('select * from fact_revisions where store_id=$1 and fact_revision_id=$2', sid, rid)
    assert await db.fetchval('select count(*) from fact_occurrences where store_id=$1', sid) == 0
    fact = FactRevision(fact_revision_id=str(rid), fact_id=str(fid), entity_id=str(row['entity_id']),
        original_assertion=row['original_assertion'], assertion=row['assertion'],
        subject=row['subject'], predicate=row['predicate'],
        variant=dict(temperature=row['variant_temperature'], size=row['variant_size']),
        quantity=dict(value=str(row['quantity_value']), unit=row['quantity_unit']),
        provenance=(FactProvenance(owner_answer_id=str(aid)),))
    cid = await db.fetchval("insert into knowledge_cards(store_id,title,content) values($1,'라테',$2) returning card_id", sid, fact.assertion)
    vid = await db.fetchval('select draft_version_id from knowledge_cards where store_id=$1 and card_id=$2', sid, cid)
    await db.execute("insert into card_version_blocks(store_id,card_version_id,block_id,kind,block_order) values($1,$2,'b','QUANTITIES',1)", sid, vid)
    await db.execute("insert into card_block_facts(store_id,card_version_id,block_id,fact_revision_id,position) values($1,$2,'b',$3,1)", sid, vid, rid)
    content = KnowledgeContent(store_id=str(sid), glossary_version='glossary/v1', renderer_version=RENDERER_VERSION,
        cards=(PublishedCard(card_id=str(cid), card_version_id=str(vid), entity_id=fact.entity_id,
            title='라테', blocks=(CardBlock(block_id='b', kind='QUANTITIES', order=1, fact_revision_ids=(str(rid),)),)),),
        fact_revisions=(fact,))
    async def vectors(texts, **kwargs):
        return [[1.] + [0.]*1535 for _ in texts]
    prepared = await prepare_index(pool, store_id=sid, member_id=mid, idempotency_key='w3-ledger-prepare',
        expected_publication_revision=1, content=content, embedder=vectors,
        usage_context=UsageContext(store_id=str(sid), stage='EMBED', cost_phase='REGISTRATION',
            cost_purpose='DEVELOPMENT', logical_call_id='w3-synthetic-embed'))
    assert prepared.status == 'PREPARED'
    async with db.transaction():
        published = await publish_knowledge(db, store_id=sid, member_id=mid,
            idempotency_key='w3-ledger-publish', body_hash=prepared.payload_hash,
            expected_publication_revision=1, snapshot_hash=snapshot_hash_for(content, 2),
            glossary_version=content.glossary_version, renderer_version=content.renderer_version,
            card_versions=[(cid, vid)])
        await db.execute("update knowledge_cards set review_status='APPROVED',is_verified=true,published_version_id=$3 where store_id=$1 and card_id=$2", sid, cid, vid)
        await activate_prepared_index(db, store_id=sid, prepared_id=int(prepared.prepared_id), snapshot_id=published.snapshot_id)
    found = await hybrid_search(pool, store_id=sid, question=question, query_vector=[1.]+[0.]*1535)
    reply = await save(found, 'w3-typed-requestion')
    assert reply.response.action == 'ANSWER' and reply.response.citations[0].owner_answer_id == str(aid)
    assert reply.response.citations[0].source_id is None
    assert (await save(found, 'w3-typed-requestion')).replayed
    with patch.object(v2_router, 'get_pool', return_value=pool), patch.object(get_settings(), 'r_v2_enabled', True):
        detail = await v2_router.citation_detail(reply.receipt_id, 1, dict(store_id=sid, user_id=uid, role='OWNER'), uid)
    assert detail['owner_answer_id'] == str(aid) and detail['text'] == fact.assertion
    print('PASS W3 consumer W ledger fact -> search -> answer -> typed owner citation -> history replay/detail')
    for sql, args in [
        ('''insert into r_answer_citations(store_id,receipt_id,citation_order,card_id,card_version_id,
            block_id,fact_revision_id,owner_answer_id) values($1,$2,2,$3,$4,'b',$5,$6)''',
            (sid,int(reply.receipt_id),cid,vid,rid,aid+999999)),
        ('delete from owner_answers where answer_id=$1', (aid,)),
    ]:
        try:
            async with db.transaction():
                await db.execute(sql, *args)
        except asyncpg.ForeignKeyViolationError:
            pass
        except asyncpg.RaiseError as exc:
            assert sql.startswith('delete from owner_answers') and 'owner original is immutable' in str(exc)
        else:
            raise AssertionError('owner provenance constraint bypassed')
    print('PASS W3 consumer forged fact origin and referenced owner deletion blocked')
