"""실제 API/DB 평가 출력과 출력에 결속된 검토를 HTML로 표시한다."""
import argparse
import hashlib
import html
import json
from pathlib import Path
from statistics import median


def render(run_path, review_path, output):
    run=json.loads(run_path.read_text('utf-8'))
    if run.get('knowledge_format'):
        raise ValueError('historical RAW report only; fact campaigns require frozen-denominator reporting')
    review=json.loads(review_path.read_text('utf-8')) if review_path else None
    labels={}
    if review:
        assert review['run_sha256']==hashlib.sha256(run_path.read_bytes()).hexdigest()
        labels={(r['case_id'],r['turn_number']):r for r in review['judgments']}
        assert len(labels)==len(review['judgments'])
    rows=[]
    totals=dict(correct=0,incorrect=0,unreviewed=0,error=0)
    sessions=[]
    used=set()
    e=lambda value:html.escape(str(value))
    for case in run['rows']:
        judgments=[]
        for t in case['turns']:
            key=(case['case_id'],t['turn_number'])
            body=t['response']
            correct=None
            reason='행동 일치만 확인됨. 답변 내용 검토 필요.'
            if not t['action_matches']:
                correct=False
                reason='기대 행동과 실제 행동 불일치.'
            if key in labels:
                label=labels[key]
                assert label['response_sha256']==hashlib.sha256(json.dumps(body,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
                assert type(label['semantic_correct']) is bool and label['reviewer'].strip() and label['reason'].strip()
                correct=label['semantic_correct'];reason=label['reason'];used.add(key)
            judgments.append(correct)
            totals['correct' if correct is True else 'incorrect' if correct is False else 'unreviewed']+=1
            if t['http_status']!=200:totals['error']+=1
            observed=body.get('message') or body.get('error',{}).get('message','')
            if body.get('allowed_options'):observed+='\n선택지: '+', '.join(body['allowed_options'])
            status='통과' if correct is True else '실패' if correct is False else '미판정'
            action=body.get('action') or body.get('error',{}).get('code','ERROR')
            rows.append(f'''<tr><td>{e(case['case_id'])} · {t['turn_number']}턴<br><small>{e(case['title'])}</small></td>
<td><p>{e(t['request']['question'])}</p><small>기대: {e(t['expected']['expected_action'])}</small></td>
<td><b>{e(action)}</b><pre>{e(observed)}</pre></td>
<td><b>{e(status)}</b><p>{e(reason)}</p><details><summary>기대 답변·근거</summary><pre>{e(t['expected']['reference_answer'])}</pre><p>{e(', '.join(t['expected']['required_fact_ids']))}</p></details></td></tr>''')
        sessions.append(all(j is True for j in judgments))
    assert used==set(labels)
    turns=[t for c in run['rows'] for t in c['turns']]
    times=sorted(t['elapsed_local_ms'] for t in turns)
    n=len(turns)
    summary=dict(**totals,turn_count=n,complete_scenarios=sum(sessions),scenario_count=len(sessions),
        http_success=run['http_success'],receipt_verified=run['receipt_verified'],
        required_facts_in_candidates=run['required_facts_in_candidates'],action_counts=run['action_counts'],
        source_run_sha256=hashlib.sha256(run_path.read_bytes()).hexdigest(),provider_mode=run.get('provider_mode','NO_PAID_PROVIDER'),
        assistant_review_is_provisional=True)
    output.with_suffix('.summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    card=lambda label,value:f'<div class="card"><strong>{e(value)}</strong><span>{e(label)}</span></div>'
    document=f'''<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>AskBuddy 운영 질문 재평가</title><style>
body{{font-family:Arial,"Malgun Gothic",sans-serif;margin:0;background:#f6f7fb;color:#19273b;line-height:1.65}}main{{max-width:1400px;margin:40px auto;padding:0 28px}}h1{{font-size:32px;margin-bottom:8px}}.lead{{max-width:920px}}.cards{{display:flex;gap:14px;flex-wrap:wrap;margin:28px 0}}.card{{background:white;border:1px solid #dee4ee;border-radius:14px;padding:18px 24px;min-width:155px}}strong{{display:block;font-size:28px}}.card span,small{{color:#57667c}}.note{{background:#fff4d9;padding:18px;border-radius:12px}}table{{width:100%;border-collapse:collapse;background:white;margin:24px 0}}td,th{{border-bottom:1px solid #dce3ed;text-align:left;padding:16px;vertical-align:top}}th{{background:#e9eef6}}td{{width:25%}}td:first-child{{width:15%}}pre{{font:inherit;white-space:pre-wrap;word-break:break-word}}summary{{cursor:pointer}}footer{{font-size:13px;color:#57667c;overflow-wrap:anywhere}}
</style><main><h1>AskBuddy 운영 질문 재평가</h1><p class="lead">합성 운영 정책 26개 · 질문 시나리오 12개 · 총 24턴. 실제 FastAPI 경로와 일회용 PostgreSQL 17에서 실행하고, 답변 receipt 저장 및 세션 이력을 확인했습니다.</p>
<p class="note">이 실행의 공급자 모드: <b>{e(run.get('provider_mode','NO_PAID_PROVIDER'))}</b>. 검색 임베딩은 고정 합성 벡터입니다. 따라서 실제 검색 모델 정확도·운영 응답 속도로 해석할 수 없습니다. 내용 검토는 보조자 잠정 판정이며 독립 사람 검토나 운영 품질 승인에 해당하지 않습니다.</p>
<div class="cards">{card('잠정 내용 통과',str(totals['correct'])+'/'+str(n))}{card('API 성공·답변 저장',str(run['receipt_verified'])+'/'+str(n))}{card('필수 근거 검색 후보 포함',str(run['required_facts_in_candidates'])+'/'+str(n))}{card('완결 시나리오',str(sum(sessions))+'/'+str(len(sessions)))}</div>
<p>실제 행동: {e(json.dumps(run['action_counts'],ensure_ascii=False))}. 실행 오류 {totals['error']}건, 미판정 {totals['unreviewed']}건. 합성 임베딩을 포함한 로컬 API 중앙 지연 {median(times):.1f}ms이며 실제 모델 호출 여부는 위 모드를 확인해야 합니다.</p>
<h2>실제 질문·출력·기대 답변</h2><table><thead><tr><th>시나리오</th><th>입력 질문</th><th>실제 출력</th><th>검토</th></tr></thead><tbody>{''.join(rows)}</tbody></table>
<footer>코드: {e(run['commit'])}<br>입력 hash: {e(run['input_hash'])}<br>결과 hash: {summary['source_run_sha256']}<br>출처: {e(str(run_path.resolve()))}</footer></main></html>'''
    output.write_text(document,encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--run',type=Path,required=True)
    parser.add_argument('--review',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    render(args.run,args.review,args.output)
