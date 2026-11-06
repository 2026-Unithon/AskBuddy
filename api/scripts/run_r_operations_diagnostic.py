"""Run the frozen operations pack against the R core without DB or provider calls.

Fallback when the disposable Docker engine cannot start. Free-text turns are sent
unchanged, independently: no gold slots or evaluator-built conversation memory.
This is NOT a multi-turn HTTP/session accuracy measurement.
"""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import html
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'api'))
from app.contracts.snapshot import PublishedKnowledgeSnapshot
from app.contracts.hashing import snapshot_digest, verify_snapshot_hash
from app.reg.hybrid import Candidate, SearchResult
from app.learn.planner import decide
from app.learn.approved_renderer import render


def dump(path,value):
    with path.open('x',encoding='utf-8') as stream:json.dump(value,stream,ensure_ascii=False,indent=2)


def build_snapshot(challenge):
    grouped=defaultdict(list)
    for fact in challenge['facts']:grouped[fact['category']].append(fact)
    cards=[];spans=[];mapping=[]
    for n,(title,facts) in enumerate(grouped.items(),1):
        ident=str(n)
        text='\n'.join(f['assertion'] for f in facts)
        cards.append(dict(card_id=ident,card_version_id=ident,entity_id=ident,title=title,
            blocks=[dict(block_id='b'+ident,kind='RAW',order=1,raw_span_id=ident)]))
        spans.append(dict(raw_span_id=ident,source_id=ident,text=text))
        mapping.append(dict(card_id=ident,source_id=ident,title=title,text=text,fact_ids=[f['fact_id'] for f in facts]))
    snapshot=PublishedKnowledgeSnapshot.model_validate(dict(store_id='1',snapshot_id='1',knowledge_revision='1',
        snapshot_hash='sha256:'+'0'*64,created_at='2026-10-06T00:00:00Z',glossary_version='operations-diagnostic/v1',
        renderer_version='r-approved/v1',cards=cards,raw_spans=spans))
    snapshot=snapshot.model_copy(update=dict(snapshot_hash=snapshot_digest(snapshot)))
    verify_snapshot_hash(snapshot)
    return snapshot,mapping


def execute(search,key,question):
    try:
        decision=decide(search,store_id=1,question=question)
        response=render(decision.plan,search.snapshot,store_id=1,request_id=key,
            pending_id='1' if decision.plan.action=='ESCALATE' else None,
            availability={s.source_id:'AVAILABLE' for s in search.snapshot.raw_spans})
        return dict(status='RECORDED',response=response.model_dump(mode='json'),
            reason=decision.plan.escalation_reason,pending_is_render_placeholder=True)
    except Exception as exc:
        return dict(status='ERROR',error_type=type(exc).__name__,response=None)


def write_report(out,report):
    e=html.escape
    action_labels={'ANSWER':'답변','CLARIFY':'재질문','ESCALATE':'점주 확인','REFUSE':'거절','SAFE_ROUTE':'안전 안내'}
    articles=[]
    for case in report['rows']:
        turns=[]
        for n,t in enumerate(case['turns'],1):
            body=t['observed'].get('response') or {}
            turns.append(f'<section><h3>{n}턴 입력 · {e(t["question"])}</h3>'
                f'<div class="comparison"><div><small>기대 · {action_labels[t["expected_action"]]}</small><p>{e(t["reference_answer"])}</p></div>'
                f'<div><small>실제 · {action_labels.get(body.get("action"),"실행 오류")}</small><p>{e(body.get("message",t["observed"].get("error_type","")))}</p>'
                +(f'<p>선택지: {e(" / ".join(body.get("allowed_options",[])))}</p>' if body.get('allowed_options') else '')
                +f'<p class="reason">{e(t["observed"].get("reason") or "대상 확인")}</p></div></div>'
                f'<p><b>판정:</b> {e(t["verdict_reason"])}</p><p class="muted">필수 근거: {e(", ".join(t["required_fact_ids"]))}</p></section>')
        articles.append(f'<article><small>{case["case_id"]} · {e(case["kind"])} · 직접 입력 진단</small><h2>{e(case["title"])}</h2>'
            +''.join(turns)+'</article>')
    counts=report['summary']['actual_actions']
    doc='''<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>AskBuddy 운영 질문 실행 결과</title>
<style>*{box-sizing:border-box}body{margin:0;background:#f3f5f9;color:#20354c;font-family:'Malgun Gothic',sans-serif}main{max-width:1060px;margin:auto;padding:40px 24px}header{background:#193849;color:white;border-radius:18px;padding:30px}h1{font-size:31px;line-height:1.5}h2{font-size:21px}h3{font-size:16px;line-height:1.8}p{line-height:1.85}small,.muted,.reason{font-size:12px;color:#5b7088}.note{background:#fff0d4;border-radius:12px;padding:20px;margin:20px 0}.stats{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}.stat,article{background:white;border:1px solid #dde4ee;border-radius:12px;padding:22px;margin:16px 0}.stat b{display:block;font-size:30px;margin:10px 0}.comparison{display:grid;grid-template-columns:1fr 1fr;gap:14px}.comparison>div{background:#f2f6fa;border-radius:8px;padding:15px}section{border-top:1px solid #e0e6ee;padding-bottom:12px}footer{font-size:12px;color:#586f87;margin-top:25px;line-height:1.9}@media(max-width:650px){.stats,.comparison{grid-template-columns:1fr}main{padding:20px 12px}}@media print{article{break-inside:avoid}body{background:white}header{background:#eee;color:#193849}}</style>
<main><header><div>ASKBUDDY / OPERATIONS DIAGNOSTIC / 2026.10.06</div><h1>운영 고난도 질문 실행 결과</h1><p>고정한 12개 시나리오의 24개 발화를 현재 R 판단·렌더링 코드에 직접 입력했습니다.</p></header>
<div class="note"><b>실행 범위: 판단·렌더링 직접 호출. 실제 대화 API 평가는 미실행입니다.</b><br>Docker가 임시 소켓 접근 오류로 시작되지 않아 DB·HTTP 경로를 실행하지 못했습니다. 이전 대화를 주입하지 않은 독립 입력 진단이므로 아래 수치를 세션 맥락 이해율이나 종합 채팅 정확도로 해석할 수 없습니다.</div>
<div class="stats"><div class="stat"><small>단일 질문 6개</small><b>__SINGLE__ / 6</b><small>고정 후보를 받은 기본 R 경로의 완전 통과</small></div><div class="stat"><small>24개 발화 직접 입력</small><b>__TURN__ / 24</b><small>단일·후속 발화 합계 / 실제 세션 평가 아님</small></div><div class="stat"><small>실제 3턴 대화 6개</small><b>미측정</b><small>Docker 복구 후 실제 API 재실행 필요</small></div></div>
<p>실제 행동: __ACTIONS__<br>정책 원문 조회 양성 대조: __CONTROL__ / 3 통과. 입력 자료가 없어 발생한 빈 지식 응답이 아님을 확인했습니다.</p>
<h2>왜 이 결과가 나왔나</h2><p>정책 사실 26개를 분야별 RAW 카드 9개로 묶고 모든 카드를 후보로 제공했습니다. 검색 누락을 제거한 진단에서도 기본 경로는 규칙·조건을 조합한 업무 답변을 만들지 못했습니다. 개별 카드 원문 조회와 복합 상황에 대한 답변은 다른 기능입니다.</p>
<p>추가 진단에서는 정답에 필요한 정책 카드만 후보로 제공해 단일 질문 6개를 다시 실행했지만 기대 행동 일치는 여전히 0/6이었습니다. 이는 정답 근거로 후보를 고른 별도 진단이며 실제 검색 성능이 아닙니다. 결과는 candidate-sensitivity.json에 보존했습니다.</p>
<p>기본 결정 경로만 실행했고 선택적 검토 의미 해석·일반 의미 해석·재정렬은 실행하지 않았습니다. 현재 운영 배포의 설정이나 모델 품질을 측정한 결과가 아닙니다.</p>
__CASES__
<h2>판정 방식</h2><p>기대 행동과 다르면 실패입니다. 행동이 같더라도 질문이 요구한 확인 질문·규칙 설명이 있는지 실제 출력별로 별도 검토했습니다. 채점은 이번 작업의 검토이며 독립 평가자 검토 전입니다. 원래 질문·정답·필수 사실은 실행 전에 만든 JSON 그대로 사용했습니다. 결과를 보고 질문이나 정답을 수정하지 않았습니다.</p>
<footer>기준 커밋: __COMMIT__<br>원본 결과: run.json · 고정 입력: frozen-challenge.json · 합성 승인 DTO: snapshot.json<br>유료 호출 0회, 운영 DB 접근 없음, 실제 점주 알림 전송 없음. 응답의 “확인을 요청했어요”는 렌더러 문구이며 이번 직접 호출에서는 pending ID를 표시용으로만 사용했습니다.<br>독립 평가 및 실제 HTTP 대화 검증은 남아 있습니다. 실행 준비 코드: api/scripts/run_r_operations_http.py</footer></main></html>'''
    action_text=' / '.join(f'{action_labels[k]} {v}개' for k,v in counts.items())
    doc=doc.replace('__CASES__',''.join(articles)).replace('__SINGLE__',str(report['summary']['single_passes'])).replace('__TURN__',str(report['summary']['turn_passes']))
    doc=doc.replace('__ACTIONS__',action_text).replace('__CONTROL__',str(sum(c['passed'] for c in report['controls']))).replace('__COMMIT__',report['commit'][:12])
    (out/'AskBuddy-operations-results.html').write_text(doc,encoding='utf-8')


def main(args):
    data=json.loads(args.input.read_text('utf-8'))
    unhashed={k:v for k,v in data.items() if k!='content_sha256'}
    assert data['content_sha256']==hashlib.sha256(json.dumps(unhashed,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    args.output.mkdir(parents=True,exist_ok=True)
    dump(args.output/'frozen-challenge.json',data)
    snap,mapping=build_snapshot(data)
    dump(args.output/'snapshot.json',snap.model_dump(mode='json'))
    dump(args.output/'fact-card-map.json',mapping)
    candidates=tuple(Candidate(c.card_id,c.card_version_id,b.block_id,1.,1.,.02) for c in snap.cards for b in c.blocks)
    search=SearchResult(snap,1,candidates,'')
    controls=[]
    for i,item in enumerate(mapping[:3]):
        result=execute(search,'control-'+str(i),item['title']+' 승인 원문 보여줘')
        body=result.get('response') or {}
        controls.append(dict(question=item['title']+' 승인 원문 보여줘',observed=result,
            passed=body.get('action')=='ANSWER' and body.get('message')==item['text']
                and [c['source_id'] for c in body.get('citations',[])]==[item['source_id']]))
    rows=[]
    for spec in data['cases']:
        turns=[]
        for n,t in enumerate(spec['turns'],1):
            result=execute(search,spec['case_id']+'-'+str(n),t['question'])
            action=(result.get('response') or {}).get('action')
            matches=action==t['expected_action']
            turns.append(dict(**t,observed=result,action_matches=matches,
                semantic_correct=None if matches else False,
                verdict_reason='행동만 일치; 출력별 의미 검토 필요' if matches else '기대 행동과 실제 행동 불일치'))
        rows.append(dict(case_id=spec['case_id'],title=spec['title'],kind=spec['kind'],turns=turns,
            actual_session_evaluated=False))
    source_files=('api/app/learn/planner.py','api/app/learn/approved_renderer.py','api/app/learn/raw_quantity.py',
        'api/app/learn/v2_router.py','api/scripts/run_r_operations_diagnostic.py')
    turns=[t for r in rows for t in r['turns']]
    report=dict(schema_version='r_operations_core_run/v1',created_at=datetime.now(timezone.utc).isoformat(),
        input_hash=data['content_sha256'],commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        source_hashes={f:hashlib.sha256((ROOT/f).read_bytes()).hexdigest() for f in source_files},
        scope='PURE_DEFAULT_V2_DECISION_RENDERER_ALL_RAW_CANDIDATES_NO_HISTORY_INJECTION',
        database_http_status='BLOCKED_DOCKER_STARTUP_SOCKET_ACCESS_ERROR',session_accuracy=None,
        paid_calls=0,controls=controls,rows=rows,
        summary=dict(turns=len(turns),action_matches=sum(t['action_matches'] for t in turns),
            actual_actions=dict(Counter((t['observed'].get('response') or {}).get('action','ERROR') for t in turns)),
            unreviewed=sum(t['semantic_correct'] is None for t in turns),errors=sum(t['observed']['status']=='ERROR' for t in turns)))
    dump(args.output/'run-unreviewed.json',report)
    print(json.dumps(report['summary'],ensure_ascii=False))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--input',type=Path,default=ROOT/'output/r-operations-challenge-20261006/operations-challenge.json')
    parser.add_argument('--output',type=Path,required=True)
    main(parser.parse_args())
