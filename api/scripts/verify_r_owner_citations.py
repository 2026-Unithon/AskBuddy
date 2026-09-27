"""실제 W 공개 결과로 R 저장·재조회·근거 접근·출처 FK를 검사한다."""
from unittest.mock import patch
from fastapi import HTTPException

from app.config import get_settings
from app.contracts.answer import AnswerPlan, SelectedBlock
from app.errors import ApiError
from app.learn.answer_storage import save_answer, current_source_overlay
from app.learn.answer_validation import ResolvedSelection, SuitabilityAssessment, question_hash
from app.learn import v2_router
from app.reg.hybrid import read_current_index, hybrid_search


async def verify(pool, admin, *, store, card_id, owner_answer_id, other_answer_id):
    sid, mid, uid = store['sid'], store['mid'], store['uid']
    passed = []
    def check(name, ok):
        assert ok, name
        passed.append(name)
        print('PASS owner citation', name)
    snapshot, _, _ = await read_current_index(admin, store_id=sid)
    card = snapshot.card(str(card_id))
    block = card.blocks[0]
    span = next(s for s in snapshot.raw_spans if s.raw_span_id == block.raw_span_id)
    session = await admin.fetchval('''insert into chat_sessions(store_id,member_id,contract_version)
        values($1,$2,'v2') returning session_id''', sid, mid)
    question = '검수 대기 새 답변은 무엇인가요?'
    found = await hybrid_search(pool, store_id=sid, question=question, query_vector=[1.0]+[0.0]*1535)
    check('W approved card retrieved', str(card_id) in {c.card_id for c in found.candidates})
    plan = AnswerPlan(snapshot_id=snapshot.snapshot_id, knowledge_revision=snapshot.knowledge_revision,
        action='ANSWER', selected_blocks=(SelectedBlock(card_id=card.card_id, card_version_id=card.card_version_id,
            block_id=block.block_id, raw_span_id=span.raw_span_id),))
    # 합성 의미 판정만 고정한다. W 콘텐츠/색인, R 참조 검증·저장·조회는 실제 코드다.
    assessment = SuitabilityAssessment(store_id=str(sid), snapshot_id=snapshot.snapshot_id,
        knowledge_revision=snapshot.knowledge_revision, snapshot_hash=snapshot.snapshot_hash,
        question_hash=question_hash(question), entity_id=card.entity_id, predicate='synthetic_owner',
        variants=(), raw_blocks=((card.card_id, card.card_version_id, block.block_id, span.raw_span_id),))
    resolved = ResolvedSelection(card.entity_id, 'synthetic_owner', (), question=question, assessment=assessment)
    async def save():
        return await save_answer(pool, store_id=sid, member_id=mid, session_id=session,
            request_id='owner-citation-roundtrip', question=question, snapshot=snapshot,
            plan=plan, resolved=resolved, confirmed_slots={})
    first, replay = await save(), await save()
    check('owner citation saves and replays once', not first.replayed and replay.replayed
          and first.receipt_id == replay.receipt_id and first.response.message == span.text)
    row = await admin.fetchrow('''select * from r_answer_citations
        where store_id=$1 and receipt_id=$2''', sid, int(first.receipt_id))
    check('owner origin persisted without fabricated source', row['source_id'] is None
          and row['owner_answer_id'] == owner_answer_id and row['raw_span_id'] == int(span.raw_span_id))
    overlay = await current_source_overlay(admin, store_id=sid, response=first.response)
    check('history preserves available owner origin', overlay.citations[0].owner_answer_id == str(owner_answer_id)
          and overlay.citations[0].source_availability == 'AVAILABLE')
    with patch.object(v2_router, 'get_pool', return_value=pool), patch.object(get_settings(), 'r_v2_enabled', True):
        claims = dict(store_id=sid, user_id=uid, role='OWNER')
        detail = await v2_router.citation_detail(first.receipt_id, 1, claims, uid)
        check('citation detail returns owner source and exact text', detail['owner_answer_id'] == str(owner_answer_id)
              and detail['text'] == span.text and detail['source_availability'] == 'AVAILABLE')
        try:
            await v2_router.citation_detail(first.receipt_id, 1, dict(claims, store_id=sid+99999), uid)
        except (ApiError, HTTPException) as exc:
            check('other store cannot open citation', exc.status_code in (403, 404))
        else:
            raise AssertionError('cross-store citation exposed')
    for bad_owner in (other_answer_id, owner_answer_id+999999):
        try:
            async with admin.transaction():
                await admin.execute('''insert into r_answer_citations(store_id,receipt_id,citation_order,
                    card_id,card_version_id,block_id,raw_span_id,owner_answer_id)
                    values($1,$2,2,$3,$4,$5,$6,$7)''', sid, int(first.receipt_id), card_id,
                    int(card.card_version_id), block.block_id, int(span.raw_span_id), bad_owner)
        except Exception as exc:
            check('wrong owner origin rejected by DB', 'r_citation_owner_origin_fk' in str(exc))
        else:
            raise AssertionError('forged owner origin saved')
    print(f'Verified {len(passed)} owner citation checks')
