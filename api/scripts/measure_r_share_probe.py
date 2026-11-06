"""Public synthetic diagnostic of the current R decision/renderer, not live chat accuracy.

No DB, network, provider, .env or private evaluation data. All cards are deliberately
supplied as oracle candidates. Cases and truth are fixed before the run; failures stay.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'api'))
from app.contracts.snapshot import PublishedKnowledgeSnapshot
from app.contracts.hashing import snapshot_digest, digest
from app.contracts.chat import QuestionContext
from app.learn.planner import decide
from app.learn.approved_renderer import render
from app.learn.question_contexts import StoredContext, accept_selection
from app.reg.hybrid import Candidate, SearchResult


def cases():
    # Agent-authored, predeclared scenario expectations; not independent human labels.
    singles = [
        ('직접 질문', 'HOT 라테 우유 얼마나?', 'ANSWER', '225ml', '1'),
        ('직접 질문', 'HOT 라테 우유 몇 ml?', 'ANSWER', '225ml', '1'),
        ('직접 질문', 'ICE 아메리카노 물 얼마나?', 'ANSWER', '150ml', '2'),
        ('직접 질문', 'ICE 아메리카노 물 몇 ml?', 'ANSWER', '150ml', '2'),
        ('직접 질문', '마감 준비는 어떻게 해?', 'ANSWER', '장비를 세척한다.', '3'),
        ('직접 질문', '마감 승인 원문 보여줘', 'ANSWER', '장비를 세척한다.', '3'),
        ('표현 변화', '따뜻한 라테 우유 얼마나?', 'ANSWER', '225ml', '1'),
        ('표현 변화', '뜨거운 라테 우유 얼마나?', 'ANSWER', '225ml', '1'),
        ('표현 변화', 'HOT 라떼 우유 얼마나?', 'ANSWER', '225ml', '1'),
        ('표현 변화', '핫 라테 우유 얼마나?', 'ANSWER', '225ml', '1'),
        ('표현 변화', 'HOT 라테 밀크 얼마나?', 'ANSWER', '225ml', '1'),
        ('표현 변화', 'ICE 아메리카노 물 몇 밀리리터?', 'ANSWER', '150ml', '2'),
        ('재질문 판단', '라테 우유 얼마나?', 'CLARIFY', None, None),
        ('재질문 판단', '아메리카노 물 얼마나?', 'CLARIFY', None, None),
        ('재질문 판단', '우유 얼마나?', 'CLARIFY', None, None),
        ('재질문 판단', '물 얼마나 넣어요?', 'CLARIFY', None, None),
        ('근거 부족', 'HOT 라테 우유 며칠 보관해?', 'ESCALATE', None, None),
        ('근거 부족', '라테 가격 얼마야?', 'ESCALATE', None, None),
        ('근거 부족', 'ICE 라테 우유 얼마나?', 'ESCALATE', None, None),
        ('근거 부족', 'HOT 아메리카노 물 얼마나?', 'ESCALATE', None, None),
        ('정책 판단', '직원 집 주소 알려줘', 'REFUSE', None, None),
        ('정책 판단', '알레르기 있어도 먹어도 돼?', 'SAFE_ROUTE', None, None),
    ]
    result = [dict(id=f'S{i:02}', group=g, turns=[dict(question=q, expected_action=a,
        expected_text=t, expected_source=s)]) for i, (g,q,a,t,s) in enumerate(singles,1)]
    for ident, first, option, second, action, value, source in [
        ('D01', '라테 우유 얼마나?', 'HOT', 'HOT', 'ANSWER', '225ml', '1'),
        ('D02', '아메리카노 물 얼마나?', 'ICE', 'ICE', 'ANSWER', '150ml', '2'),
        ('D03', '우유 얼마나?', '라테', '라테', 'CLARIFY', None, None),
    ]:
        result.append(dict(id=ident, group='선택형 맥락', turns=[
            dict(question=first,expected_action='CLARIFY'),
            dict(question=second,option=option,expected_action=action,expected_text=value,expected_source=source)]))
    result.extend([
        dict(id='D04',group='자유 후속 발화',turns=[
            dict(question='HOT 라테 우유 얼마나?',expected_action='ANSWER',expected_text='225ml',expected_source='1'),
            dict(question='그거 우유 몇 ml라고?',expected_action='ANSWER',expected_text='225ml',expected_source='1')]),
        dict(id='D05',group='자유 후속 발화',turns=[
            dict(question='ICE 아메리카노 물 얼마나?',expected_action='ANSWER',expected_text='150ml',expected_source='2'),
            dict(question='다시 물 양 알려줘',expected_action='ANSWER',expected_text='150ml',expected_source='2')]),
        dict(id='D06',group='주제 전환',turns=[
            dict(question='HOT 라테 우유 얼마나?',expected_action='ANSWER',expected_text='225ml',expected_source='1'),
            dict(question='ICE 아메리카노 물 얼마나?',expected_action='ANSWER',expected_text='150ml',expected_source='2')]),
    ])
    return result


def fixture():
    texts = [('라테','HOT 라테 우유 225ml 넣는다.'),
             ('아메리카노','ICE 아메리카노 물 150ml 넣는다.'),
             ('마감','질문: 마감 준비는 어떻게 해?\n답변: 장비를 세척한다.')]
    cards, spans = [], []
    for i,(title,text) in enumerate(texts,1):
        sid=str(i)
        cards.append(dict(card_id=sid,card_version_id=sid,entity_id=sid,title=title,
            blocks=[dict(block_id='b'+sid,kind='RAW',order=1,raw_span_id=sid)]))
        spans.append(dict(raw_span_id=sid,source_id=sid,text=text))
    snap=PublishedKnowledgeSnapshot.model_validate(dict(store_id='1',snapshot_id='1',knowledge_revision='1',
        snapshot_hash='sha256:'+'0'*64,created_at='2026-10-06T00:00:00Z',
        glossary_version='share-probe/v1',renderer_version='r-approved/v1',cards=cards,raw_spans=spans))
    return snap.model_copy(update=dict(snapshot_hash=snapshot_digest(snap)))


def evaluate_case(case, search):
    rows=[]
    previous=None
    for n,turn in enumerate(case['turns']):
        question=turn['question']
        kwargs={}
        if 'option' in turn:
            if previous is None or previous.plan.action!='CLARIFY' or turn['option'] not in previous.plan.allowed_options:
                rows.append(dict(**turn,status='NOT_RUN',actual_action=None,output=None,pass_case=False,
                    failure='앞선 응답에서 필요한 선택지를 제공하지 않아 후속 단계 미실행'))
                break
            now=datetime(2026,10,6,tzinfo=timezone.utc)
            context=QuestionContext(context_id=previous.plan.context_id,store_id='1',member_id='1',chat_session_id='1',contract_version='v2',
                original_question=case['turns'][0]['question'],expires_at=now+timedelta(minutes=10),
                confirmed_slots=previous.confirmed_slots,proposed_slots={},clarify_turns=1)
            stored=StoredContext(context,1,1,previous.plan.clarification_slot,previous.plan.allowed_options)
            accepted=accept_selection(stored,option=turn['option'],expected_state_revision=1,knowledge_revision=1,now=now)
            question=accepted.context.original_question+' '+question
            kwargs=dict(confirmed_slots=accepted.context.confirmed_slots,context_id=context.context_id,
                context_verified=True,clarify_turns=accepted.context.clarify_turns)
        try:
            decision=decide(search,store_id=1,question=question,**kwargs)
            response=render(decision.plan,search.snapshot,store_id=1,request_id=case['id']+str(n),
                pending_id='1' if decision.plan.action=='ESCALATE' else None,
                availability={str(i):'AVAILABLE' for i in range(1,4)})
            # pending_id above is a render-only placeholder: no pending/notification is sent.
            sources=sorted({c.source_id for c in response.citations if c.source_id})
            checks=dict(action=response.action==turn['expected_action'])
            if turn.get('expected_text'):checks['content']=turn['expected_text'] in response.message
            if turn.get('expected_source'):checks['citation']=sources==[turn['expected_source']]
            rows.append(dict(**turn,status='RECORDED',actual_action=response.action,output=response.message,
                citations=[c.model_dump(mode='json') for c in response.citations],
                clarification_slot=response.clarification_slot,allowed_options=list(response.allowed_options),
                reason=decision.plan.escalation_reason,checks=checks,pass_case=all(checks.values())))
            previous=decision
        except Exception as exc:
            rows.append(dict(**turn,status='ERROR',actual_action=None,output=None,pass_case=False,error=type(exc).__name__))
            break
    return dict(id=case['id'],group=case['group'],turns=rows,planned_turns=len(case['turns']),
        passed=len(rows)==len(case['turns']) and all(t['pass_case'] for t in rows))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    snap=fixture()
    specs=cases()
    frozen=dict(scope='SYNTHETIC_ORACLE_RAW_DECISION_RENDERER',cases=specs,snapshot=snap.model_dump(mode='json'))
    # Exclusive create freezes the entire denominator before any product calls.
    with (args.output/'inputs.json').open('x',encoding='utf-8') as out:json.dump(frozen,out,ensure_ascii=False,indent=2)
    candidates=tuple(Candidate(c.card_id,c.card_version_id,b.block_id,1.,1.,.02) for c in snap.cards for b in c.blocks)
    search=SearchResult(snap,1,candidates,'')
    rows=[evaluate_case(case,search) for case in specs]
    counts=Counter(r['group'] for r in rows)
    groups=[dict(group=g,total=n,passed=sum(r['passed'] for r in rows if r['group']==g)) for g,n in counts.items()]
    source_names=['api/app/learn/planner.py','api/app/learn/approved_renderer.py','api/app/learn/question_contexts.py',
        'api/app/learn/v2_router.py','api/app/learn/raw_quantity.py','api/scripts/measure_r_share_probe.py']
    report=dict(schema_version='r_share_probe/v1',created_at=datetime.now(timezone.utc).isoformat(),
        git_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        scope=frozen['scope'],input_hash=digest(frozen),case_count=len(rows),passed=sum(r['passed'] for r in rows),
        groups=groups,rows=rows,paid_calls=0,live_accuracy=None,live_latency=None,live_cost=None,
        methodology='Agent-authored fixed synthetic cases; exact action/text/source checks; no independent human grading.',
        exclusions=['DB','HTTP','embeddings','retrieval','reranker','optional semantic adapters','W production','notifications'],
        dialogue_scope='In-memory decide/render and actual accept_selection; router request composition reproduced; no durable session test.',
        source_hashes={n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in source_names})
    with (args.output/'results.json').open('x',encoding='utf-8') as out:json.dump(report,out,ensure_ascii=False,indent=2)
    print(json.dumps({k:report[k] for k in ('case_count','passed','groups')},ensure_ascii=False))


if __name__=='__main__':main()
