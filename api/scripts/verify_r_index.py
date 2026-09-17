"""재구축한 일회용 전체 schema에서 M2와 실제 W publish 서비스 접점을 검사한다.

verify_r_schema_rebuild가 발급한 연결만 받는다. 모델은 합성 adapter로 대체한다.
"""
import asyncio
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

import asyncpg
from app.contracts.snapshot import KnowledgeContent, PublishedKnowledgeSnapshot
from app.contracts.usage import UsageContext
from app.contracts.hashing import snapshot_digest
from app.learn.approved_renderer import RENDERER_VERSION
from app.errors import ApiError
from app.publish.service import publish_knowledge
from app.reg.index_preparation import prepare_index, activate_prepared_index
from app.reg.hybrid import hybrid_search
from app.team.retrieval_collection import collect_retrieval_pool
from app.reg.lexicon import LexiconEntry,approve_lexicon,load_lexicon


async def verify(pool, admin):
    passed = []
    def check(name, ok):
        assert ok, name
        passed.append(name)
        print("PASS M2",name)
    uid = await admin.fetchval("insert into users(name,role) values('합성 M2 점주','OWNER') returning user_id")
    sid = await admin.fetchval("""insert into stores(owner_id,store_name,business_type)
        values($1,'합성 M2 매장','CAFE') returning store_id""",uid)
    mid = await admin.fetchval("""insert into store_members(store_id,user_id,member_role)
        values($1,$2,'OWNER') returning member_id""",sid,uid)
    snap = PublishedKnowledgeSnapshot.model_validate_json((Path(__file__).resolve().parents[1]/
        "tests/fixtures/contracts/v1/snapshot.json").read_text(encoding="utf-8"))
    # 새 renderer를 승인한 합성 producer 판. 원본 fixture 파일은 바꾸지 않는다.
    snap=snap.model_copy(update={"renderer_version":RENDERER_VERSION})
    # 기본 planner용 별도 합성 정답: 승인된 명시적 물 수량 사실 하나를 추가 정의한다.
    first=snap.fact_revisions[0]
    title=next(c.title for c in snap.cards if c.entity_id==first.entity_id)
    entries=(LexiconEntry(layer='STORE',term=title,variants=('합성별칭',)),)
    lexversion=await approve_lexicon(pool,store_id=sid,member_id=mid,entries=entries)
    check('same approved dictionary reuses version',await approve_lexicon(pool,store_id=sid,member_id=mid,entries=entries)==lexversion)
    snap=snap.model_copy(update={'glossary_version':lexversion})
    try:await load_lexicon(admin,store_id=sid+1,version=lexversion)
    except ApiError as exc:check('dictionary cannot cross store',exc.code=='INDEX_UNAVAILABLE')
    else:raise AssertionError('cross store dictionary')
    try:await admin.execute("update r_search_lexicons set entries='[]'::jsonb where store_id=$1 and version=$2",sid,lexversion)
    except Exception as exc:check('approved dictionary immutable','immutable' in str(exc))
    else:raise AssertionError('mutable dictionary')
    assertion=f"{first.variant.temperature} {title} 물 {first.quantity.value}{first.quantity.unit} 넣는다."
    first=first.model_copy(update=dict(predicate="water_amount",assertion=assertion,original_assertion=assertion,
                                      conditions=(),exceptions=(),requires=()))
    snap=snap.model_copy(update={"fact_revisions":(first,*snap.fact_revisions[1:])})
    snap=snap.model_copy(update={"snapshot_hash":snapshot_digest(snap)})
    assert sid == int(snap.store_id), "requires fresh UUID database"
    content = KnowledgeContent(**{k:v for k,v in snap.model_dump().items() if k in KnowledgeContent.model_fields})
    for card in snap.cards:
        await admin.execute("""insert into knowledge_cards(card_id,store_id,title,content)
            overriding system value values($1,$2,$3,'합성 승인 본문')""",int(card.card_id),sid,card.title)
        await admin.execute("""insert into card_versions(version_id,store_id,card_id,version_no,title,content,change_source)
            overriding system value values($1,$2,$3,2,$4,'합성 승인 본문','OWNER_EDIT')""",
            int(card.card_version_id),sid,int(card.card_id),card.title)
        await admin.execute("""update knowledge_cards set published_version_id=$3,review_status='APPROVED',is_verified=true
            where store_id=$1 and card_id=$2""",sid,int(card.card_id),int(card.card_version_id))
    await admin.execute("insert into knowledge_publications(store_id,publication_revision,knowledge_revision) values($1,6,6)",sid)
    usage = UsageContext(store_id=str(sid),cost_phase="REGISTRATION",cost_purpose="DEVELOPMENT",
                         stage="EMBED",logical_call_id="synthetic-m2")
    args = dict(store_id=sid,member_id=mid,expected_publication_revision=6,content=content,usage_context=usage)
    calls = []
    async def embed(texts, **kwargs):
        check("provider runs without pool connection",pool.get_idle_size()==pool.get_size())
        check("preparation commits before provider",await admin.fetchval(
            "select count(*) from r_index_preparations where store_id=$1 and state='PREPARING'",sid)>0)
        calls.append(kwargs["context"])
        return [[1.0]+[0.0]*1535 for _ in texts]
    with patch("app.reg.index_preparation.get_settings",return_value=SimpleNamespace(
            embedding_dim=1536,embedding_model="synthetic-1536")):
        prepared = await prepare_index(pool,**args,idempotency_key="m2-first-prepare",embedder=embed)
        check("prepared complete",prepared.status=="PREPARED")
        pid = int(prepared.prepared_id)
        check("staging is not active",await admin.fetchval("select count(*) from r_index_publications")==0)
        replay = await prepare_index(pool,**args,idempotency_key="m2-first-prepare",embedder=embed)
        check("same request reuses result without provider",replay==prepared and len(calls)==1)
        changed = dict(args,expected_publication_revision=7)
        conflict = await prepare_index(pool,**changed,idempotency_key="m2-first-prepare",embedder=embed)
        check("same key different request rejected",conflict.error.code=="IDEMPOTENCY_CONFLICT")
        async with admin.transaction():
            try:
                await activate_prepared_index(admin,store_id=sid+1,prepared_id=pid,snapshot_id=100)
            except ApiError:
                check("other store cannot activate",True)
            else:
                raise AssertionError("cross store activation")
        try:
            async with admin.transaction():
                await admin.execute("update r_index_preparations set content_hash=$2 where prepared_id=$1",pid,"changed")
        except asyncpg.RaiseError:
            check("preparation content immutable",True)
        else:
            raise AssertionError("mutable preparation")
        try:
            async with admin.transaction():
                await admin.execute("update r_index_documents set approved_text='changed' where prepared_id=$1",pid)
        except asyncpg.RaiseError:
            check("prepared documents immutable",True)
        else:
            raise AssertionError("mutable document")
        versions=[(int(c.card_id),int(c.card_version_id)) for c in snap.cards]
        try:
            async with admin.transaction():
                wrong = await publish_knowledge(admin,store_id=sid,member_id=mid,idempotency_key="m2-wrong-publish",
                    body_hash="sha256:"+"1"*64,expected_publication_revision=6,snapshot_hash="sha256:"+"2"*64,
                    glossary_version=snap.glossary_version,renderer_version=snap.renderer_version,card_versions=versions)
                await activate_prepared_index(admin,store_id=sid,prepared_id=pid,snapshot_id=wrong.snapshot_id)
        except ApiError as exc:
            check("W mismatched publication rolls back",exc.code=="HASH_MISMATCH")
        else:
            raise AssertionError("bad hash accepted")
        check("failed publication retains prior revision",await admin.fetchval(
            "select knowledge_revision from knowledge_publications where store_id=$1",sid)==6)
        async with admin.transaction():
            published = await publish_knowledge(admin,store_id=sid,member_id=mid,idempotency_key="m2-good-publish",
                body_hash="sha256:"+"3"*64,expected_publication_revision=6,snapshot_hash=snap.snapshot_hash,
                glossary_version=snap.glossary_version,renderer_version=snap.renderer_version,card_versions=versions)
            await activate_prepared_index(admin,store_id=sid,prepared_id=pid,snapshot_id=published.snapshot_id)
            await activate_prepared_index(admin,store_id=sid,prepared_id=pid,snapshot_id=published.snapshot_id)
        check("W publication and index commit once",await admin.fetchval(
            "select count(*) from r_index_publications where store_id=$1",sid)==1)
        lexical_question = snap.cards[0].title
        query_vector = [0.0,1.0]+[0.0]*1534
        found = await hybrid_search(pool,store_id=sid,question=lexical_question,query_vector=query_vector)
        check("current index reads assigned W snapshot",found.snapshot.snapshot_id==str(published.snapshot_id))
        check("lexical match survives zero vector similarity",any(
            c.lexical_score is not None and c.vector_score==0 for c in found.candidates))
        sentence=await hybrid_search(pool,store_id=sid,question=f'{title} 물은 얼마나 넣나요?',query_vector=query_vector)
        check('Korean question retains lexical candidate with particle',any(
            c.card_id==snap.cards[0].card_id and c.lexical_score is not None for c in sentence.candidates))
        aliased=await hybrid_search(pool,store_id=sid,question='합성별칭',query_vector=query_vector)
        check('pinned approved alias expands lexical only',aliased.alias_terms==(title,) and any(c.lexical_score is not None for c in aliased.candidates))
        collection_args=dict(store_id=sid,question_id='synthetic-search-q1',question=lexical_question,
            query_vector=query_vector,embedding_metadata=dict(provider='fixture',model='synthetic-1536',
                mode='SYNTHETIC',reference='verify_r_index.py'),
            expected_snapshot={k:getattr(found.snapshot,k) for k in ('snapshot_id','knowledge_revision','snapshot_hash')},
            oracle=[],sample_size=100,seed='synthetic-before-review',channel_limit=1)
        collected=await collect_retrieval_pool(pool,**collection_args)
        review=collected['review_pool']
        check('evaluation audits complete snapshot independently of cutoff',
            collected['universe_audit']['complete'] and
            collected['universe_audit']['expected_count']==sum(len(c.blocks) for c in snap.cards))
        check('evaluation collects independent ranked channels',len(collected['vector'])==1
            and len(collected['lexical'])==1 and review['pooled_size']<=2)
        check('evaluation samples beyond channel cutoff',review['sampling']['selected']>0
            and len(review['entries'])==review['universe_size'])
        check('evaluation labels remain unknown',all(r['relevance'] is None for r in review['entries']))
        drift=dict(collection_args,expected_snapshot=dict(collection_args['expected_snapshot'],knowledge_revision='999'))
        try:await collect_retrieval_pool(pool,**drift)
        except ValueError:check('evaluation rejects changed publication',True)
        else:raise AssertionError('evaluation accepted wrong snapshot')
        await admin.execute("update knowledge_cards set review_status='EXCLUDED' where store_id=$1 and card_id=$2",
                            sid,int(snap.cards[0].card_id))
        filtered = await hybrid_search(pool,store_id=sid,question=lexical_question,query_vector=query_vector)
        check("both channels reject excluded card",all(c.card_id!=snap.cards[0].card_id for c in filtered.candidates))
        excluded=await collect_retrieval_pool(pool,**collection_args)
        check('revocation does not shrink immutable snapshot audit denominator',
            excluded['universe_audit']==collected['universe_audit'] and
            excluded['review_pool']['universe_size']<review['universe_size'])
        check('evaluation excludes revoked card from sample universe',all(
            r['reference'][0]!=snap.cards[0].card_id for r in excluded['review_pool']['entries']))
        revoked_ref=[snap.cards[0].card_id,snap.cards[0].card_version_id,snap.cards[0].blocks[0].block_id]
        try:await collect_retrieval_pool(pool,**dict(collection_args,oracle=[revoked_ref]))
        except ValueError:check('evaluation rejects revoked oracle',True)
        else:raise AssertionError('revoked oracle accepted')
        try:await collect_retrieval_pool(pool,**dict(collection_args,store_id=sid+1))
        except ApiError as exc:check('evaluation cannot read another store index',exc.code=='INDEX_UNAVAILABLE')
        else:raise AssertionError('evaluation crossed stores')
        await admin.execute("update knowledge_cards set review_status='APPROVED',is_verified=true where store_id=$1 and card_id=$2",
                            sid,int(snap.cards[0].card_id))
        try:
            await hybrid_search(pool,store_id=sid+1,question=lexical_question,query_vector=query_vector)
        except ApiError as exc:
            check("other store cannot read active index",exc.code=="INDEX_UNAVAILABLE")
        else:
            raise AssertionError("cross store search")
        args["expected_publication_revision"] = 7
        entered, release = asyncio.Event(),asyncio.Event()
        async def slow(texts,**kw):
            entered.set()
            await release.wait()
            return await embed(texts,**kw)
        task=asyncio.create_task(prepare_index(pool,**args,idempotency_key="m2-concurrent",embedder=slow))
        try:
            await asyncio.wait_for(entered.wait(),3)
            other = await prepare_index(pool,**args,idempotency_key="m2-concurrent",embedder=embed)
            check("concurrent request does not duplicate provider",other.status=="FAILED" and len(calls)==1)
        finally:
            release.set()
            result = await task
        check("first concurrent request completes",result.status=="PREPARED")
        await admin.execute("""insert into r_index_preparations(store_id,member_id,idempotency_key,
            request_hash,content_hash,content,expected_publication_revision,embedding_model,index_config_version,
            state,claim_id,lease_expires_at,expires_at)
            select store_id,member_id,'m2-expired-case',request_hash,content_hash,content,expected_publication_revision,
              embedding_model,index_config_version,state,claim_id,lease_expires_at,clock_timestamp()-interval '1 second'
            from r_index_preparations where store_id=$1 and idempotency_key='m2-concurrent'""",sid)
        expired = await prepare_index(pool,**args,idempotency_key="m2-expired-case",embedder=embed)
        check("expired preparation not reused or rebilled",expired.error.code=="INDEX_PREPARE_TIMEOUT" and len(calls)==2)
        async def broken(*a,**kw):
            raise TimeoutError()
        failed = await prepare_index(pool,**args,idempotency_key="m2-timeout-case",embedder=broken)
        check("timeout persists failure",failed.error.code=="INDEX_PREPARE_TIMEOUT")
        again = await prepare_index(pool,**args,idempotency_key="m2-timeout-case",embedder=embed)
        check("failed request not silently billed again",again.error.code=="INDEX_PREPARE_TIMEOUT" and len(calls)==2)
        # claim을 남긴 프로세스 중단을 재현한다. 자동 공급자 재시도는 하지 않는다.
        entered.clear()
        release.clear()
        task=asyncio.create_task(prepare_index(pool,**args,idempotency_key="m2-crash-case",embedder=slow))
        await asyncio.wait_for(entered.wait(),3)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        await admin.execute("""update r_index_preparations set lease_expires_at=clock_timestamp()-interval '1 second'
            where store_id=$1 and idempotency_key='m2-crash-case'""",sid)
        recovered = await prepare_index(pool,**args,idempotency_key="m2-crash-case",embedder=embed)
        check("expired claim recovers as next accounted attempt",recovered.status=="PREPARED" and calls[-1].attempt_no==2)
    print(f"Verified {len(passed)} M2 DB checks")
    from app.reg.hybrid import read_current_index
    current,_,_=await read_current_index(admin,store_id=sid)
    return dict(store_id=sid,member_id=mid,user_id=uid,snapshot=current)
