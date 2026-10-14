"""P1 실제 DB: v1 이력 보존 → 공통 전달 → W 사실 처리 → R 검토/공개.

외부 모델만 합성으로 바꾼다. rebuild의 일회용 UUID DB에서만 실행한다.
"""
import asyncio
from types import SimpleNamespace
from unittest.mock import patch
from fastapi import HTTPException

from _fact_card_fixture import assertion, _mock_settings, _vectors
from verify_w_fact_only import _extracting
from app.cards.owner_answer_worker import process_next_owner_event
from app.db_session import ShortSession
from app.errors import ApiError
from app.learn import router, v2_router
from app.learn.owner_delivery import submit_owner_answer
from app.reg.hybrid import hybrid_search, read_current_index
from app.learn.planner import decide
from app.learn.answer_storage import save_answer


async def verify(pool, db):
    uid = await db.fetchval("insert into users(name,role) values('P1 점주','OWNER') returning user_id")
    sid = await db.fetchval("insert into stores(owner_id,store_name,business_type) values($1,'P1','CAFE') returning store_id", uid)
    mid = await db.fetchval("insert into store_members(store_id,user_id,member_role) values($1,$2,'OWNER') returning member_id", sid, uid)
    await db.execute("insert into task_categories(store_id,category_name,is_system) values($1,'기타',true) on conflict do nothing", sid)
    claims = dict(store_id=sid, user_id=uid, role='OWNER')
    short = ShortSession(pool)
    staff = []
    for i in range(2):
        user = await db.fetchval("insert into users(name,role) values($1,'STAFF') returning user_id", f'P1 직원 {i}')
        staff.append(await db.fetchval("insert into store_members(store_id,user_id,member_role) values($1,$2,'STAFF') returning member_id", sid, user))

    async def question(text, historical=False):
        qid = await db.fetchval("""insert into pending_questions(store_id,member_id,question_text,contract_version)
            values($1,$2,$3,'v1') returning question_id""", sid, staff[0], text)
        for member in staff:
            await db.execute("insert into pending_question_occurrences(question_id,member_id) values($1,$2)", qid, member)
        if historical:
            await db.execute("insert into owner_answers(question_id,answered_by,answer_text) values($1,$2,'보존할 이전 원문')", qid, uid)
            await db.execute("update pending_questions set status='ANSWERED' where store_id=$1 and question_id=$2", sid, qid)
        return qid

    async def submit(qid, text, key, revision=0, store=sid):
        return await submit_owner_answer(pool, store_id=store, member_id=mid, question_id=qid,
            request_id=key, answer=text, expected_revision=revision)

    async def process(*facts):
        with patch('app.ingest.extract.extract_facts', _extracting(*facts)), \
                patch('app.ingest.extract.get_settings', return_value=_mock_settings()), \
                patch('app.reg.index_preparation.recorded_embeddings', _vectors):
            return await process_next_owner_event(pool, store_id=sid)

    def check(name, ok):
        assert ok, name
        print('PASS P1 legacy', name)

    with patch.object(router, 'get_pool', return_value=pool), \
            patch.object(v2_router, 'get_pool', return_value=pool), \
            patch.object(v2_router, 'get_settings', return_value=SimpleNamespace(r_v2_enabled=True)), \
            patch('app.reg.index_preparation.recorded_embeddings', _vectors):
        qid = await question('음료P 물 얼마나?', historical=True)
        detail = await v2_router.pending_detail(str(qid), claims, uid)
        check('old original and occurrences readable without rewriting', len(detail['legacy_answers']) == 1 and len(detail['occurrences']) == 2)
        other = await question('음료P 물 얼마나?')
        request = router.AnswerPendingRequest(answer_text='음료P 물 225ml')
        first, repeated = await asyncio.gather(
            router.answer_pending(qid, request, short, claims, sid, uid),
            router.answer_pending(qid, request, short, claims, sid, uid))
        aid = int(first['owner_answer_id'])
        check('legacy endpoint retry replays one answer to two staff', first == repeated and first['delivered_sessions'] == 2)
        check('same text in other question remains waiting', await db.fetchval('select status from pending_questions where store_id=$1 and question_id=$2', sid, other) == 'WAITING')
        check('legacy destinations open readable history', await db.fetchval("select count(*) from notification_events where store_id=$1 and aggregate_id=$2 and destination='/staff/chat'", sid, aid) == 2)
        fact = assertion('f1','음료P','water_amount','225',unit='ml').model_copy(update={'original_assertion':'음료P 물은 225ml'})
        check('W publishes new facts from legacy answer', await process(fact) == 'PUBLISHED')
        check('publication notification reaches both legacy recipients', await db.fetchval(
            "select count(*) from notification_events where store_id=$1 and aggregate_id=$2 and dedupe_key like 'r-knowledge-ready:%' and destination='/staff/chat'", sid, aid) == 2)
        detail = await v2_router.pending_detail(str(qid), claims, uid)
        check('detail retains old answer beside published revision', detail['answers'][-1]['knowledge_status'] == 'PUBLISHED' and detail['legacy_answers'][0]['answer'] == '보존할 이전 원문')
        snapshot, _, _ = await read_current_index(db, store_id=sid)
        check('R consumes actual fact publication', bool(snapshot.cards) and not snapshot.raw_spans)

        changed = await submit(qid, '음료P 시럽 30ml', 'p1-legacy-edit', 1)
        check('existing card goes to review', await process(assertion('f1','음료P','시럽','30',unit='ml')) == 'REVIEW')
        proposals = await router.list_knowledge_proposals(short, claims, sid, 'PENDING_REVIEW')
        proposal = proposals['items'][0]
        check('review UI metadata names affected card and permits approval', proposal['can_approve'] and len(proposal['affected_cards']) == 1 and proposal['relation_type'] == 'SUPPLEMENT')
        approved = await router.approve_knowledge_proposal(proposal['proposal_id'], short, claims, sid, uid)
        again = await router.approve_knowledge_proposal(proposal['proposal_id'], short, claims, sid, uid)
        check('approval updates R state and is idempotent', approved['card_id'] == again['card_id'] and await db.fetchval(
            'select status from r_owner_knowledge_states where store_id=$1 and owner_answer_id=$2', sid, int(changed['owner_answer_id'])) == 'PUBLISHED')
        found = await hybrid_search(pool, store_id=sid, question='음료P 물 얼마나?', query_vector=[1.]+[0.]*1535)
        decision = decide(found, store_id=sid, question='음료P 물 얼마나?')
        chat = await db.fetchval("insert into chat_sessions(store_id,member_id,contract_version) values($1,$2,'v2') returning session_id", sid, staff[0])
        saved = await save_answer(pool, store_id=sid, member_id=staff[0], session_id=chat,
            request_id='p1-reask-after-approval', question='음료P 물 얼마나?', snapshot=found.snapshot,
            plan=decision.plan, resolved=decision.resolved, confirmed_slots=decision.confirmed_slots,
            semantic_context=decision.semantic_context)
        check('unverified recipe variant still fails closed', saved.response.action == 'ESCALATE'
              and decision.plan.escalation_reason == 'UNVERIFIED_VARIANT_SCOPE')
        scoped = await question('음료Q HOT 물 얼마나?')
        await submit(scoped, '음료Q HOT 물은 225ml', 'p1-scoped-original')
        scoped_fact = assertion('f1','음료Q','water_amount','225',unit='ml').model_copy(
            update={'original_assertion':'음료Q HOT 물은 225ml', 'variant':'HOT'})
        check('explicit variant fact publishes', await process(scoped_fact) == 'PUBLISHED')
        found = await hybrid_search(pool, store_id=sid, question='음료Q HOT 물 얼마나?', query_vector=[1.]+[0.]*1535)
        decision = decide(found, store_id=sid, question='음료Q HOT 물 얼마나?')
        saved = await save_answer(pool, store_id=sid, member_id=staff[0], session_id=chat,
            request_id='p1-reask-scoped-approval', question='음료Q HOT 물 얼마나?', snapshot=found.snapshot,
            plan=decision.plan, resolved=decision.resolved, confirmed_slots=decision.confirmed_slots,
            semantic_context=decision.semantic_context)
        check('staff reasks and receives approved fact with citation', saved.response.action == 'ANSWER'
              and bool(saved.response.citations) and '225' in saved.response.message)

        empty = await submit(other, '좋아요', 'p1-legacy-no-facts')
        check('no facts remains review', await process() == 'REVIEW')
        proposals = await router.list_knowledge_proposals(short, claims, sid, 'PENDING_REVIEW')
        check('no-facts cannot offer publication', proposals['items'][0]['approval_block_reason'] == 'NO_FACTS' and not proposals['items'][0]['can_approve'])
        await router.dismiss_knowledge_proposal(proposals['items'][0]['proposal_id'], short, claims, sid)
        closed = await v2_router.pending_detail(str(other), claims, uid)
        check('dismissal readable without inventing publication', closed['answers'][-1]['proposal_status'] == 'DISMISSED' and closed['answers'][-1]['knowledge_status'] == 'REVIEW')
        # 옛 제안은 OWNER_TEXT 연결이 없으며, 빈 초안을 공개할 수 없다.
        category = await db.fetchval('select category_id from task_categories where store_id=$1 limit 1', sid)
        old_answer = int(detail['legacy_answers'][0]['owner_answer_id'])
        await db.execute("""insert into knowledge_change_proposals(store_id,answer_id,relation_type,category_id,proposed_title,proposed_content,reason,status)
            values($1,$2,'NEW',$3,'옛 제안','옛 원문','legacy','PENDING_REVIEW')""", sid, old_answer, category)
        proposals = await router.list_knowledge_proposals(short, claims, sid, 'PENDING_REVIEW')
        check('legacy no-draft proposal blocked', proposals['items'][0]['approval_block_reason'] == 'LEGACY' and not proposals['items'][0]['can_approve'])
        try:
            await submit(qid, '충돌 답변', 'p1-legacy-stale', 1)
        except ApiError as exc:
            check('stale correction rejected', exc.status_code == 409)
        else:
            raise AssertionError('stale accepted')
        try:
            await v2_router.pending_detail(str(qid), dict(claims, store_id=sid + 999999), uid)
        except (ApiError, HTTPException) as exc:
            check('other store cannot read detail', getattr(exc, 'status_code', None) in (403,404))
        else:
            raise AssertionError('cross-store detail accepted')
        sid2 = await db.fetchval("insert into stores(owner_id,store_name,business_type) values($1,'P1 다른 매장','CAFE') returning store_id", uid)
        mid2 = await db.fetchval("insert into store_members(store_id,user_id,member_role) values($1,$2,'OWNER') returning member_id", sid2, uid)
        try:
            await submit_owner_answer(pool, store_id=sid2, member_id=mid2, question_id=qid,
                request_id='p1-cross-store-answer', answer='다른 매장 답변', expected_revision=2)
        except ApiError as exc:
            check('valid other-store owner cannot answer this question', exc.status_code == 404)
        else:
            raise AssertionError('cross-store answer accepted')
        await db.execute('update store_members set removed_at=now() where store_id=$1 and member_id=$2', sid, mid)
        try:
            await submit(other, '탈퇴 후 답변', 'p1-removed-owner', 1)
        except ApiError as exc:
            check('removed owner cannot submit or replay', exc.status_code == 403)
        else:
            raise AssertionError('removed owner accepted')
