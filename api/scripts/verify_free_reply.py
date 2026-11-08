"""Exercise session binding and atomic receipt/pending writes with scripted planner offers."""
from unittest.mock import patch
from uuid import uuid4
from app.contracts.answer import AnswerPlan
from app.learn.answer_validation import ResolvedSelection
from app.learn.planner import Decision


async def verify(client, headers, db, check):
    for prefix,turns,slots in (
        ('refund',('환불하려는데 어떻게 처리해?', '영수증은 없어요'),('entity','entity')),
        ('opening',('오픈 준비를 어디부터 시작해?', '혼자 근무해요', '현금 시재는 아직 안 셌어요'),
         ('entity','predicate','size')),
    ):
        sid=(await client.post('/learn/v2/sessions',headers=headers,
            json={'request_id':'free-test-session-'+prefix})).json()['session_id']
        ctx=None
        prior=None
        for i,(raw,slot) in enumerate(zip(turns,slots)):
            def decide(search,**kw):
                assert kw['clarify_turns']==i and kw['confirmed_slots']=={}
                assert kw['question']==' '.join(turns[:i+1])
                plan=AnswerPlan(snapshot_id=search.snapshot.snapshot_id,knowledge_revision=search.snapshot.knowledge_revision,
                    action='CLARIFY',clarification_slot=slot,allowed_options=(slot+' A', slot+' B'),
                    context_id=kw['context_id'] or uuid4())
                return Decision(plan,ResolvedSelection('','',(),question=kw['question']),{},None)
            body=dict(session_id=sid,request_id=f'free-test-{prefix}-{i}',question=raw)
            with patch('app.learn.v2_router.decide',decide):
                r=await client.post('/learn/v2/chat',headers=headers,json=body)
            check('free reply commits',r.status_code==200)
            out=r.json()
            rid=int(r.headers['x-answer-receipt-id'])
            if i:
                row=await db.fetchrow("""select resolved_query->>'question' as q,
                    execution_metadata->>'clarification_parent' as parent from r_answer_receipts where receipt_id=$1""",rid)
                check('free reply preserves scope and staff text',row['q']==' '.join(turns[:i+1]) and row['parent']==str(prior))
            if i<len(turns)-1:
                check('different clarification keeps the same context',out['action']=='CLARIFY' and
                    (not ctx or out['context_id']==ctx))
                ctx=out['context_id']
            else:
                check('no repeated or third clarification',out['action']=='ESCALATE' and raw in out['message'])
                saved=await db.fetchval('select question_text from pending_questions where question_id=$1',int(out['pending_id']))
                check('owner receives original and every detail',saved==' '.join(turns))
                replay=await client.post('/learn/v2/chat',headers=headers,json=body)
                check('free reply retry returns the original receipt',int(replay.headers['x-answer-receipt-id'])==rid)
            prior=rid
