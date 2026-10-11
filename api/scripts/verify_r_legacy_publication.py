"""Actual v1 answer/approval, empty exclusion, restoration and failed preparation.

Phase A: v1 NEW 답변은 사실 초안이 없어 승인이 거절된다(FAILED, 공개판 불변).
제외·복원 단계의 공개 카드는 사실 카드 픽스처(seed_fact_card + publish_card)로 만든다.
"""
from unittest.mock import AsyncMock, patch

from _fact_card_fixture import assertion, publish_card, seed_fact_card
from app.db_session import ShortSession
from app.learn import router
from app.learn.knowledge_loop import KnowledgePlan
from app.cards import router as cards
from app.reg.hybrid import read_current_index


async def verify(pool, db):
    uid = await db.fetchval("insert into users(name,role) values('합성 v1 점주','OWNER') returning user_id")
    sid = await db.fetchval("insert into stores(owner_id,store_name,business_type) values($1,'합성 v1 매장','CAFE') returning store_id", uid)
    mid = await db.fetchval("insert into store_members(store_id,user_id,member_role) values($1,$2,'OWNER') returning member_id", sid, uid)
    category = await db.fetchval("select category_id from task_categories where store_id=$1 and is_system", sid)
    if category is None:
        category = await db.fetchval("insert into task_categories(store_id,category_name,is_system) values($1,'기타',true) returning category_id", sid)
    claims = dict(store_id=sid, user_id=uid, role='OWNER')
    session = ShortSession(pool)
    async def answer(key):
        question = await db.fetchval("""insert into pending_questions(store_id,member_id,question_text,contract_version)
            values($1,$2,$3,'v1') returning question_id""", sid, mid, key)
        plan = KnowledgePlan('NEW', None, None, category, '기타', key, '합성 점주 원문', 'synthetic', True)
        with patch.object(router, 'build_knowledge_plan', AsyncMock(return_value=plan)):
            return await router.answer_pending(question, router.AnswerPendingRequest(answer_text=plan.proposed_content),
                session, claims, sid, uid)
    async def vectors(texts, **kwargs):
        return [[1.] + [0.]*1535 for _ in texts]
    async def snapshots():
        return await db.fetchval('select count(*) from knowledge_snapshots where store_id=$1', sid)
    with patch.object(router, 'get_pool', return_value=pool), patch.object(cards, 'get_pool', return_value=pool), \
            patch('app.reg.index_preparation.recorded_embeddings', vectors):
        before = await snapshots()
        result = await answer('합성 첫 답변 질문')
        assert result['knowledge']['status'] == 'FAILED' and result['card_id'] is None, result
        assert await snapshots() == before
        assert await db.fetchval("select count(*) from knowledge_cards where store_id=$1 and published_version_id is not null", sid) == 0
        assert await db.fetchval('select count(*) from r_owner_answer_revisions where store_id=$1', sid) == 0
        print('PASS legacy v1 NEW without fact draft fails closed (Phase A)')
        cid, _ = await seed_fact_card(pool, store_id=sid, owner_user_id=uid,
                                      assertions=[assertion('f1', '음료Z', '물', '225', unit='ml')],
                                      title='합성 v1 매장 자료')
        # 제외·복원 라우트의 재발행은 원본 자료 작업의 비용 귀속을 이어받는다(card_usage_context).
        # 픽스처 조립은 원가를 기록하지 않으므로 합성 귀속 행을 남긴다
        source = await db.fetchval('select source_id from knowledge_cards where store_id=$1 and card_id=$2', sid, cid)
        await db.execute("""insert into ai_usage_attempts(store_id,cost_phase,stage,logical_call_id,requested_model,source_id)
            values($1,'REGISTRATION','EXTRACT',$2,'synthetic-extract',$3)""", sid, f'synthetic-extract:{source}', source)
        published = await publish_card(pool, store_id=sid, member_id=mid, actor_user_id=uid, card_id=cid)
        assert published.status == 'PUBLISHED', published
        snapshot, _, _ = await read_current_index(db, store_id=sid)
        assert snapshot.card(str(cid))
        await cards.exclude_card(cid, session, claims)
        empty, _, _ = await read_current_index(db, store_id=sid)
        assert not empty.cards and int(empty.knowledge_revision) > int(snapshot.knowledge_revision)
        await cards.restore_card(cid, session, claims)
        restored, _, _ = await read_current_index(db, store_id=sid)
        assert restored.card(str(cid))
        print('PASS legacy publication last exclusion publishes empty snapshot and restoration returns card')
        with patch('app.reg.index_preparation.recorded_embeddings', AsyncMock(side_effect=RuntimeError('synthetic outage'))):
            failed = await answer('합성 실패 답변 질문')
        assert failed['knowledge']['status'] == 'FAILED' and failed['card_id'] is None
        current, _, _ = await read_current_index(db, store_id=sid)
        assert current.snapshot_id == restored.snapshot_id
        assert await db.fetchval("select count(*) from knowledge_cards where store_id=$1 and review_status='APPROVED'", sid) == 1
        print('PASS legacy publication failed preparation keeps old snapshot and cannot expose new card')
