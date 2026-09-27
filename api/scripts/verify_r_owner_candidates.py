"""실제 공개 생산·새 색인만으로 점주 후보/관계 판단을 검증한다. 공급자만 합성이다."""
import asyncio
import asyncpg
from unittest.mock import patch

from app.config import get_settings
from app.contracts.usage import UsageContext
from app.db_session import ShortSession
from app.errors import ApiError
from app.learn.knowledge_loop import find_owner_answer_candidates, build_knowledge_plan
from app.publish.approval import publish_cards, CardChange
from app.reg.owner_candidates import published_owner_candidates
from app.usage import DbUsageSink


async def verify(pool, admin):
    passed = []
    def check(name, ok):
        assert ok, name
        passed.append(name)
        print('PASS owner candidates', name)
    uid = await admin.fetchval("insert into users(name,role) values('후보 합성 점주','OWNER') returning user_id")
    sid = await admin.fetchval("insert into stores(owner_id,store_name,business_type) values($1,'후보 합성','CAFE') returning store_id", uid)
    mid = await admin.fetchval("insert into store_members(store_id,user_id,member_role) values($1,$2,'OWNER') returning member_id", sid, uid)
    category = await admin.fetchval("select category_id from task_categories where store_id=$1 and is_system", sid)
    if category is None:
        category = await admin.fetchval("insert into task_categories(store_id,category_name,is_system) values($1,'기타',true) returning category_id", sid)
    context = UsageContext(store_id=str(sid), stage='RELATION', cost_phase='OPERATING',
                           logical_call_id='candidate-relation', operation_id='candidate-verification')
    sink = DbUsageSink(pool)
    db = ShortSession(pool)
    original = 'A 승인 원문\n' + '보존하는 긴 원문 ' * 550
    cards = []
    for title, text in [('카드 A', original), ('카드 B', 'B 승인 원문')]:
        source = await admin.fetchval("insert into sources(store_id,uploaded_by,source_type,status,title) values($1,$2,'KAKAO','DONE',$3) returning source_id", sid, uid, title)
        cid = await admin.fetchval('''insert into knowledge_cards(store_id,category_id,source_id,title,content,assignment_type)
            values($1,$2,$3,$4,$5,'MANUAL') returning card_id''', sid, category, source, title, text)
        vid = await admin.fetchval('select draft_version_id from knowledge_cards where store_id=$1 and card_id=$2', sid, cid)
        cards.append((cid, vid))
    async def vectors(texts, **kwargs):
        check('provider sees no held pool connection', pool.get_idle_size() == pool.get_size())
        return [([.8,.6]+[0.0]*1534 if text.startswith('카드 B') else [1.0]+[0.0]*1535) for text in texts]
    async def query():
        return await find_owner_answer_candidates(db, sid, '업무 질문', '점주 답변', 2,
                                                  usage_context=context, usage_sink=sink)
    with patch('app.reg.index_preparation.recorded_embeddings', vectors), \
            patch('app.learn.knowledge_loop.recorded_embeddings', vectors):
        try:
            await query()
        except ApiError as exc:
            check('missing active index is an error not empty candidates', exc.code == 'INDEX_UNAVAILABLE')
        else:
            raise AssertionError('missing index hidden')
        result = await publish_cards(pool, store_id=sid, member_id=mid, actor_user_id=uid,
            changes=[CardChange(cid, vid, vid) for cid, vid in cards], idempotency_key='candidate-first-publication',
            usage_context=context.model_copy(update=dict(stage='EMBED')))
        check('W publication succeeds', result.status == 'PUBLISHED')
        check('legacy embeddings are absent', await admin.fetchval('select count(*) from card_embeddings where store_id=$1', sid) == 0)
        rows = await query()
        check('multiple A blocks cannot crowd B out of top two', [r['id'] for r in rows] == [c[0] for c in cards])
        check('cosine score and manual category retained', abs(rows[1]['score']-.8) < .00001
              and rows[0]['assignment_type'] == 'MANUAL' and rows[0]['category_id'] == category)
        check('full immutable content returned not just winning block', rows[0]['content'] == original)
        a, av = cards[0]
        from app.cards.repository import create_draft
        async with admin.transaction():
            draft = await create_draft(admin, sid, a, title='미승인 제목', content='미승인 본문', actor_id=uid, source_version_id=av)
        check('draft edit never leaks into published candidate', (await query())[0]['content'] == original)
        await admin.execute("update knowledge_cards set review_status='EXCLUDED' where store_id=$1 and card_id=$2", sid, a)
        check('excluded card filtered immediately', [r['id'] for r in await query()] == [cards[1][0]])
        await admin.execute("update knowledge_cards set review_status='APPROVED',is_verified=true,published_version_id=$3 where store_id=$1 and card_id=$2", sid, a, draft)
        check('pointer outside active snapshot cannot become candidate', [r['id'] for r in await query()] == [cards[1][0]])
        await admin.execute('update knowledge_cards set published_version_id=$3 where store_id=$1 and card_id=$2', sid, a, av)
        plan = await build_knowledge_plan(db, sid, '동일 질문', original, usage_context=context, usage_sink=sink)
        check('exact published content yields IDENTICAL on new index', plan.relation_type == 'IDENTICAL' and plan.target_version_id == av)
        with patch.object(get_settings(), 'answer_mode', 'fallback'):
            plan = await build_knowledge_plan(db, sid, '보완 질문', '추가 안내', usage_context=context, usage_sink=sink)
        check('fallback cosine threshold retains review target', plan.relation_type == 'SUPPLEMENT' and not plan.auto_publish)
        # 실제 worker를 1-slot 풀로 돌려 모델 호출 중 연결 반환을 확인한다.
        from verify_r_answer_usage import DSN
        from app.learn.owner_delivery import submit_owner_answer
        from app.cards.owner_answer_worker import process_next_owner_event
        database = await admin.fetchval('select current_database()')
        single = await asyncpg.create_pool(DSN.rsplit('/', 1)[0]+'/'+database, min_size=1, max_size=1)
        try:
            question_id = await admin.fetchval('''insert into pending_questions
                (store_id,member_id,question_text,contract_version,semantic_key)
                values($1,$2,'후보 worker 검증','v2','candidate-worker') returning question_id''', sid, mid)
            reply = await submit_owner_answer(single, store_id=sid, member_id=mid, question_id=question_id,
                request_id='owner-candidate-worker', answer=original, expected_revision=0)
            async def single_embedding(texts, **kwargs):
                check('worker releases sole DB slot during embedding', single.get_idle_size() == 1)
                await asyncio.wait_for(single.fetchval('select 1'), timeout=2)
                return [[1.0]+[0.0]*1535 for _ in texts]
            with patch('app.learn.knowledge_loop.recorded_embeddings', single_embedding):
                status = await asyncio.wait_for(process_next_owner_event(single, store_id=sid), timeout=8)
            check('real worker links via new index without legacy vectors', status == 'LINKED' and
                await admin.fetchval('''select status from r_owner_knowledge_states
                    where store_id=$1 and owner_answer_id=$2''', sid, int(reply['owner_answer_id'])) == 'LINKED')
        finally:
            await single.close()
        for other_store, model in [(sid+99999, get_settings().embedding_model), (sid, 'different-model')]:
            try:
                await published_owner_candidates(db, store_id=other_store, query_vector=[1.0]+[0.0]*1535,
                                                   embedding_model=model, top_k=2)
            except ApiError as exc:
                check('foreign store or incompatible model rejected', exc.code == 'INDEX_UNAVAILABLE')
            else:
                raise AssertionError('invalid candidate index accepted')
    print(f'Verified {len(passed)} owner candidate checks')
