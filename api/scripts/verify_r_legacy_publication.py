"""Actual v1 answer/approval, empty exclusion, restoration and failed preparation."""
from unittest.mock import AsyncMock, patch

from app.config import get_settings
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
    with patch.object(router, 'get_pool', return_value=pool), patch.object(cards, 'get_pool', return_value=pool), \
            patch.object(get_settings(), 'w_owner_answer_raw_publish', True), \
            patch('app.reg.index_preparation.recorded_embeddings', vectors):
        result = await answer('합성 첫 답변 질문')
        assert result['knowledge']['status'] == 'PUBLISHED', result
        snapshot, _, _ = await read_current_index(db, store_id=sid)
        cid = result['card_id']
        assert snapshot.card(str(cid)).card_version_id == str(result['version_id'])
        assert await db.fetchval('select count(*) from r_owner_answer_revisions where store_id=$1', sid) == 0
        print('PASS legacy publication v1 NEW uses indexed approval without fabricated v2 revision')
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
