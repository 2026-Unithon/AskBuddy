"""P2: 실제 W 원장/조립/편집/공개 → R 검색/저장/출처. 외부 모델만 합성.

verify_r_schema_rebuild의 일회용 UUID DB에서 실행한다. 운영 DB에서 실행 금지.
"""
from types import SimpleNamespace
from unittest.mock import patch

from _fact_card_fixture import assertion, seed_fact_card, publish_card, edit_fact_value
from verify_w_fact_only import _store, _owner_answer, _process
from app.cards import router as cards
from app.cards.fact_edit_schemas import FactEditRequest
from app.db_session import ShortSession
from app.errors import ApiError
from app.learn import v2_router
from app.learn.answer_storage import save_answer
from app.learn.knowledge_availability import knowledge_availability
from app.learn.planner import decide
from app.publish.service import delete_source
from app.reg.hybrid import hybrid_search, read_current_index


async def verify(pool, db):
    def check(name, ok):
        assert ok, name
        print('PASS P2',name)

    w=await _store(db)
    other=await _store(db)
    claims=dict(store_id=w.store,user_id=w.user,role='OWNER')
    session=await db.fetchval("insert into chat_sessions(store_id,member_id,contract_version) values($1,$2,'v2') returning session_id",w.store,w.member)
    facts=[assertion('hot','라테','milk_amount','225',unit='ml').model_copy(update={'variant':'HOT','original_assertion':'HOT 라테 우유 225ml'}),
           assertion('ice','라테','milk_amount','250',unit='ml').model_copy(update={'variant':'ICE','original_assertion':'ICE 라테 우유 250ml'}),
           assertion('water','라테','water_amount','100',unit='ml').model_copy(update={'variant':'HOT','original_assertion':'HOT 라테 물 100ml'})]
    # 작은 상한으로 실제 W 분할 로직을 실행한다. snapshot을 수동 생성하지 않는다.
    with patch('app.ingest.card_plan.MAX_FACTS_PER_BLOCK',1),patch('app.ingest.card_plan.MAX_BLOCKS_PER_CARD',1):
        await seed_fact_card(pool,store_id=w.store,owner_user_id=w.user,assertions=facts)
    ids=await db.fetch('select card_id from knowledge_cards where store_id=$1 order by card_id',w.store)
    check('W assembler produces three numbered fact cards',len(ids)==3)
    for row in ids:
        await publish_card(pool,store_id=w.store,member_id=w.member,actor_user_id=w.user,card_id=row['card_id'])

    async def ask(question,key,limit=1):
        found=await hybrid_search(pool,store_id=w.store,question=question,query_vector=[1.]+[0.]*1535,candidate_limit=limit,channel_limit=1)
        decision=decide(found,store_id=w.store,question=question)
        saved=await save_answer(pool,store_id=w.store,member_id=w.member,session_id=session,request_id=key,
            question=question,snapshot=found.snapshot,plan=decision.plan,resolved=decision.resolved,
            confirmed_slots=decision.confirmed_slots,semantic_context=decision.semantic_context)
        return found,decision,saved

    with patch.object(v2_router,'get_pool',return_value=pool),patch.object(v2_router,'get_settings',return_value=SimpleNamespace(r_v2_enabled=True)):
        found,decision,old=await ask('HOT 라테 우유 얼마나?','p2-original')
        check('rank limit 1 expands three approved split cards',len(found.candidates)==3 and not found.snapshot.raw_spans)
        check('split title consumed by subject, exact HOT assertion only',old.response.action=='ANSWER' and '225ml' in old.response.message and '250ml' not in old.response.message)
        cold=decide(found,store_id=w.store,question='ICE 라테 우유 얼마나?')
        check('ICE selects only ICE fact',cold.plan.action=='ANSWER' and all(found.snapshot.fact(fid).variant.temperature=='ICE' for b in cold.plan.selected_blocks for fid in b.fact_revision_ids))
        check('missing temperature clarifies',decide(found,store_id=w.store,question='라테 우유 얼마나?').plan.action=='CLARIFY')
        detail=await v2_router.citation_detail(old.receipt_id,1,claims,w.user)
        check('direct OWNER_TEXT source identified',detail['source_kind']=='OWNER_TEXT' and detail['related_owner_answer_id'] is None)
        for wrong in (dict(store_id=other.store,user_id=other.user,role='OWNER'),):
            try:await v2_router.citation_detail(old.receipt_id,1,wrong,wrong['user_id'])
            except ApiError as exc:check('cross-store citation is 404',exc.code=='NOT_FOUND')
            else:raise AssertionError('cross-store citation exposed')
        cid=int(old.response.citations[0].card_id)
        await edit_fact_value(pool,store_id=w.store,owner_user_id=w.user,card_id=cid,value='230',key='p2-modify')
        _,_,draft=await ask('HOT 라테 우유 얼마나?','p2-draft-hidden')
        check('unapproved edit is hidden',draft.response.message==old.response.message)
        await publish_card(pool,store_id=w.store,member_id=w.member,actor_user_id=w.user,card_id=cid)
        _,_,new=await ask('HOT 라테 우유 얼마나?','p2-new-version')
        check('reapproval serves corrected fact',new.response.action=='ANSWER' and '230ml' in new.response.message)
        new_detail=await v2_router.citation_detail(new.receipt_id,1,claims,w.user)
        check('direct edit preserves occurrence and line',new_detail['source_kind']=='OWNER_TEXT' and new_detail['source_locations'][0]['locator']['line']==1)
        check('old citation frozen after correction',await v2_router.citation_detail(old.receipt_id,1,claims,w.user)==detail)

        # ADD + REORDER, 다음 저장에서 기존 사실 DELETE. 승인 전/후를 각각 확인한다.
        view=await cards.get_card_facts(cid,ShortSession(pool),claims)
        current=view.blocks[0].facts[0].fact_revision_id
        body=FactEditRequest.model_validate(dict(expected_version_id=view.version_id,idempotency_key='p2-add-reorder',blocks=[dict(kind='QUANTITIES',items=[
            dict(op='ADD',client_ref='water',fact=dict(sentence='HOT 라테 물 120ml',value='120',unit='ml',predicate='water_amount',variant=dict(temperature='HOT'))),
            dict(op='KEEP',fact_revision_id=current)])]))
        await cards.save_card_facts(cid,body,ShortSession(pool),claims)
        await publish_card(pool,store_id=w.store,member_id=w.member,actor_user_id=w.user,card_id=cid)
        snapshot=(await read_current_index(db,store_id=w.store))[0]
        block=snapshot.card(str(cid)).blocks[0]
        check('ADD and reordered approved block persist',snapshot.fact(block.fact_revision_ids[0]).assertion=='HOT 라테 물 120ml' and block.fact_revision_ids[1]==str(current))
        # 중복 water 카드의 충돌은 답변으로 통과시키지 않는다.
        _,conflict,_=await ask('HOT 라테 물 얼마나?','p2-conflicting-add')
        check('conflicting added quantities escalate',conflict.plan.action=='ESCALATE')
        view=await cards.get_card_facts(cid,ShortSession(pool),claims)
        await cards.save_card_facts(cid,FactEditRequest.model_validate(dict(expected_version_id=view.version_id,idempotency_key='p2-delete-old',
            blocks=[dict(kind='QUANTITIES',items=[dict(op='KEEP',fact_revision_id=view.blocks[0].facts[0].fact_revision_id)])],deleted_fact_revision_ids=[current])),ShortSession(pool),claims)
        _,_,before_delete=await ask('HOT 라테 우유 얼마나?','p2-delete-draft')
        check('draft removal does not remove current approved fact',before_delete.response.action=='ANSWER')
        await publish_card(pool,store_id=w.store,member_id=w.member,actor_user_id=w.user,card_id=cid)
        _,_,after_delete=await ask('HOT 라테 우유 얼마나?','p2-deleted-fact')
        check('approved removal no longer answers HOT milk',after_delete.response.action!='ANSWER')
        historical=await v2_router.citation_detail(new.receipt_id,1,claims,w.user)
        check('OWNER_REMOVED preserves historical citation',historical['text']==new_detail['text'])
        await delete_source(db,store_id=w.store,source_id=int(new_detail['source_id']))
        deleted=await v2_router.citation_detail(new.receipt_id,1,claims,w.user)
        check('deleted original keeps frozen text and source label',deleted['source_availability']=='DELETED' and deleted['text']==new_detail['text'] and deleted['source_kind']=='OWNER_TEXT')

        answer_text='HOT 모카 물 180ml'
        aid=await _owner_answer(pool,db,w,key='p2-owner',question='모카 물 얼마나?',answer=answer_text)
        fact=assertion('owner','모카','water_amount','180',unit='ml').model_copy(update={'variant':'HOT','original_assertion':answer_text})
        check('actual W owner worker publishes',await _process(pool,w,fact)=='PUBLISHED')
        _,_,reply=await ask('HOT 모카 물 얼마나?','p2-owner-citation',10)
        check('new owner fact consumed',reply.response.action=='ANSWER')
        origin=await v2_router.citation_detail(reply.receipt_id,1,claims,w.user)
        check('OWNER_TEXT answer relationship additive; citation XOR unchanged',origin['source_kind']=='OWNER_ANSWER' and origin['related_owner_answer_id']==str(aid) and origin['source_id'] and origin['owner_answer_id'] is None)
        state=await knowledge_availability(db,store_id=w.store,owner_answer_ids=[aid])
        check('published current state and cross-store isolation',state[aid]=='CURRENT' and not await knowledge_availability(db,store_id=other.store,owner_answer_ids=[aid]))
        owner_card=int(reply.response.citations[0].card_id)
        await edit_fact_value(pool,store_id=w.store,owner_user_id=w.user,card_id=owner_card,value='190',key='p2-owner-change')
        await publish_card(pool,store_id=w.store,member_id=w.member,actor_user_id=w.user,card_id=owner_card)
        check('later publication separates historic completion from current version',(await knowledge_availability(db,store_id=w.store,owner_answer_ids=[aid]))[aid]=='CHANGED')
    print('Verified P2 actual W fact consumption and citation origins')
