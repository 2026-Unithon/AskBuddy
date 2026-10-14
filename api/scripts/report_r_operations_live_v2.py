"""Report a bounded live run, including stopped/unrun turns and bound human review.

This script performs no provider calls. Review labels are provisional when the
reviewer is an assistant; neither an API 200 nor ANSWER alone is correctness.
"""
import argparse
from collections import Counter
from decimal import Decimal
import hashlib
import html
import json
from math import ceil
from pathlib import Path
from statistics import median


LABELS={
    'COMPLETE_ANSWER':'답변 해결',
    'USEFUL_CLARIFICATION':'필요한 재질문',
    'APPROPRIATE_ESCALATION':'적절한 점주 전달',
    'INCOMPLETE_ANSWER':'불완전한 답변',
    'INCORRECT_ANSWER':'잘못된 답변',
    'UNNECESSARY_CLARIFICATION':'불필요한 재질문',
    'INAPPROPRIATE_ESCALATION':'부적절한 점주 전달',
    'API_ERROR':'API 오류',
    'UNREVIEWED':'미판정',
    'NOT_RUN':'중단 후 미실행',
}
APPROPRIATE={'COMPLETE_ANSWER','USEFUL_CLARIFICATION','APPROPRIATE_ESCALATION'}


def body_hash(body):
    return hashlib.sha256(json.dumps(body,ensure_ascii=False,sort_keys=True).encode()).hexdigest()


def validate_comparison(run,baseline):
    current=run.get('knowledge_format','historical-raw/v1')
    previous=baseline.get('knowledge_format','historical-raw/v1')
    if current!=previous:
        raise ValueError('RAW and W fact campaigns are not comparable; choose a same-format baseline')
    if current!='historical-raw/v1' and (not run.get('input_hash') or run.get('input_hash')!=baseline.get('input_hash')):
        raise ValueError('fact comparison requires the same frozen challenge hash')


def render(directory,baseline_path,review_path=None):
    read=lambda name:json.loads((directory/name).read_text('utf-8'))
    run=read('run.json'); analysis=read('diagnostic-analysis.json'); challenge=read('frozen-challenge.json')
    baseline=json.loads(baseline_path.read_text('utf-8'))
    validate_comparison(run,baseline)
    plan=read('evaluation-plan.json')
    run_hash=hashlib.sha256((directory/'run.json').read_bytes()).hexdigest()
    review=json.loads(review_path.read_text('utf-8')) if review_path else {}
    if review:assert review['run_sha256']==run_hash
    judgments={(x['case_id'],x['turn_number']):x for x in review.get('judgments',[])}
    assert len(judgments)==len(review.get('judgments',[]))
    actual={(c['case_id'],t['turn_number']):t for c in run['rows'] for t in c['turns']}
    assert set(judgments)<=set(actual)
    counts=Counter(); rows=[]; resolved=[]; evidence_reviewed=0; evidence_correct=0
    e=lambda value:html.escape(str(value))
    for case in challenge['cases']:
        case_labels=[]
        for n,expected in enumerate(case['turns'],1):
            key=(case['case_id'],n); turn=actual.get(key); judgment=judgments.get(key)
            label='NOT_RUN' if turn is None else 'API_ERROR' if turn['http_status']!=200 else 'UNREVIEWED'
            case_stop=next((c.get('stop_reason') for c in run['rows'] if c['case_id']==case['case_id']),None)
            reason=('사전 지정 선택 문자열과 실제 사건 선택지가 유일하게 일치하지 않아 후속을 호출하지 않음. 설명형 선택지의 표현 차이도 원인일 수 있음.' if case_stop=='REQUIRED_CHOICE_NOT_OFFERED'
                else '사전 중단 규칙에 따라 호출하지 않음.') if turn is None else '출력 내용 검토 전.'
            if judgment:
                assert judgment['response_sha256']==body_hash(turn['response'])
                label=judgment['label']; reason=judgment['reason']
                assert label in LABELS and label not in ('NOT_RUN','UNREVIEWED')
                assert judgment['reviewer'] and reason
                assert turn['http_status']==200 or label=='API_ERROR'
                if judgment.get('citation_correct') is not None:
                    assert type(judgment['citation_correct']) is bool
                    evidence_reviewed+=1; evidence_correct+=judgment['citation_correct']
            counts[label]+=1;case_labels.append(label)
            body=turn['response'] if turn else {}
            message=body.get('message') or body.get('error',{}).get('message','')
            if body.get('allowed_options'):message+='\n선택지: '+str(body['allowed_options'])
            seconds=f"{turn['elapsed_local_ms']/1000:.2f}초" if turn else '—'
            rows.append(f'<tr><td>{e(case["case_id"])} · {n}<br>{e(case["title"])}</td>'
                f'<td>{e(expected["question"])}<details><summary>기대 답변</summary><pre>{e(expected["reference_answer"])}</pre></details></td>'
                f'<td><b>{e(body.get("action") or body.get("error",{}).get("code", "미실행"))}</b><pre>{e(message)}</pre><small>{seconds}</small></td>'
                f'<td><b>{e(LABELS[label])}</b><p>{e(reason)}</p></td></tr>')
        # A useful clarification alone is not resolution. Every scripted turn
        # must be appropriate and the final turn must deliver a complete answer.
        if all(x in APPROPRIATE for x in case_labels) and case_labels[-1]=='COMPLETE_ANSWER':resolved.append(case['case_id'])
    calls=analysis['generation_calls'];cost=Decimal(analysis['known_cost_usd'])
    times=sorted(t['elapsed_local_ms'] for t in actual.values())
    n=sum(len(c['turns']) for c in challenge['cases'])
    events=[json.loads(line) for line in (directory/'provider-events.jsonl').read_text('utf-8').splitlines()]
    unknown=analysis['unknown_cost_calls']
    quality_available=any(x['http_status']==200 for x in actual.values())
    summary=dict(schema_version='r_live_summary/v2',run_sha256=run_hash,
        knowledge_format=run.get('knowledge_format','historical-raw/v1'),input_hash=run['input_hash'],
        snapshot_hash=run.get('snapshot_hash'),evaluator_source_hash=run.get('evaluator_source_hash'),
        model=run['settings']['gemini_model'],thinking_level=read('evaluation-release.json')['thinking_level'],
        planned_turns=n,executed_turns=len(actual),not_run=counts['NOT_RUN'],stop_reason=run.get('stop_reason'),
        successful_api_responses=run['http_success'],action_counts=run['action_counts'],review_counts=dict(counts),
        appropriate_turns=sum(counts[x] for x in APPROPRIATE),complete_answers=counts['COMPLETE_ANSWER'],
        resolved_scenarios=resolved,planned_scenarios=len(challenge['cases']),
        citation_correct=evidence_correct,citation_reviewed=evidence_reviewed,
        provider_generation_calls=calls,provider_verification_calls=sum(x['schema']=='Verification' for x in events),
        provider_count_tokens_calls=analysis['count_tokens_calls'],
        input_tokens=sum(x['input_tokens'] or 0 for x in analysis['calls']),
        visible_output_tokens=sum(x['visible_output_tokens'] or 0 for x in analysis['calls']),
        thinking_tokens=sum(x['thinking_tokens'] or 0 for x in analysis['calls']),
        known_cost_usd=str(cost),unknown_cost_calls=unknown,assumed_krw_per_usd=1500,
        cost_status='PARTIAL_UNKNOWN' if unknown else 'TOKEN_BASED_ESTIMATE',
        known_cost_krw_at_assumed_rate=str(cost*1500),
        campaign_cost_per_resolved_scenario_usd=str(cost/len(resolved)) if resolved and not unknown else None,
        latency_p50_ms=median(times) if times else None,latency_p95_ms=times[ceil(.95*len(times))-1] if times else None,
        within_5s=sum(x<=5000 for x in times),turns_with_committed_history=analysis['turns_with_history'],
        provisional_assistant_review=True,operational_acceptance=False)
    summary['quality_metrics_status']='PROVISIONAL_REVIEW' if quality_available else 'NOT_MEASURABLE_NO_SUCCESSFUL_RESPONSE'
    (directory/'live-summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    card=lambda label,value:f'<div class="card"><strong>{e(value)}</strong>{e(label)}</div>'
    prior_n=baseline.get('evaluated_turns',baseline.get('planned_turns',24))
    cost_resolved=summary['campaign_cost_per_resolved_scenario_usd']
    p50=f"{summary['latency_p50_ms']/1000:.2f}" if times else '—'
    p95=f"{summary['latency_p95_ms']/1000:.2f}" if times else '—'
    cost_label=f'미확인 {unknown}회' if unknown else f'약 {cost*1500:,.0f}원'
    appropriate_label=f"{summary['appropriate_turns']}/{n}" if quality_available else '측정 불가'
    answer_label=f"{summary['complete_answers']}/{n}" if quality_available else '측정 불가'
    resolution_label=f"{len(resolved)}/{len(challenge['cases'])}" if quality_available else '측정 불가'
    outcome='실제 응답에 대한 잠정 품질 판정' if quality_available else '호출 오류로 중단 — 답변 품질 측정 불가'
    representation='W 원장·조립·공개를 거친 합성 사실 카드' if run.get('knowledge_format') else '합성 승인 RAW 카드'
    doc=f'''<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>AskBuddy Gemini 보완 후 실제 평가</title><style>
body{{font-family:Arial,"Malgun Gothic",sans-serif;background:#f4f6fa;color:#18263a;margin:0;line-height:1.65}}main{{max-width:1400px;margin:36px auto;padding:0 24px}}h1{{font-size:32px}}h2{{margin-top:32px}}.cards{{display:flex;flex-wrap:wrap;gap:12px;margin:24px 0}}.card{{background:white;border:1px solid #dae2ee;border-radius:12px;padding:20px;min-width:150px}}strong{{display:block;font-size:28px}}.note{{padding:20px;background:#fff0cb;border-left:4px solid #c79024}}table{{width:100%;border-collapse:collapse;background:white}}th,td{{text-align:left;vertical-align:top;padding:14px;border-bottom:1px solid #dce3ed}}th{{background:#e8edf5}}pre{{font:inherit;white-space:pre-wrap;overflow-wrap:anywhere}}small,footer{{color:#526177}}footer{{font-size:12px;overflow-wrap:anywhere}}.scroll{{overflow-x:auto}}.questions{{min-width:900px}}.questions td{{width:28%}}.questions td:first-child{{width:16%}}summary{{cursor:pointer}}
</style><main><p>AskBuddy · R 보완 후 유료 진단</p><h1>{e(outcome)}</h1>
<p>{e(summary['model'])} · thinking {e(summary['thinking_level'])} · 고정 질문 {n}턴 / {len(challenge['cases'])}개 시나리오 · 실행 {len(actual)}턴</p>
<p class="note">API 성공은 정답률이 아닙니다. 필요한 재질문은 적절한 대응으로 인정하지만, 마지막 답변까지 해결된 대화와 구분합니다. 내용 판정은 보조자의 잠정 검토이며 독립 사람 평가가 아닙니다. {e(representation)}와 고정 임베딩을 사용했으므로 W 추출 품질·검색 모델 성능·운영 인수를 의미하지 않습니다. 중단 사유: {e(run.get('stop_reason') or '없음')}.</p>
<div class="cards">{card('적절한 대응 / 고정 분모',appropriate_label)}{card('답변 해결 / 고정 분모',answer_label)}{card('정상 API 응답 / 실행 턴',f"{run['http_success']}/{len(actual)}")}{card('완결 시나리오',resolution_label)}{card('비용 확인 상태',cost_label)}</div>
<h2>보완 전후</h2><table><tr><th>항목</th><th>이전 유료 평가</th><th>보완 후 이번 평가</th></tr>
<tr><td>API 성공</td><td>{baseline['successful_api_responses']}/{prior_n}</td><td>{run['http_success']}/{n}</td></tr>
<tr><td>실제 생성 / 검증 호출</td><td>{baseline['provider_generation_calls']} / {baseline['provider_verification_calls']}</td><td>{calls} / {summary['provider_verification_calls']}</td></tr>
<tr><td>사용량 기반 추정 비용</td><td>${baseline['known_cost_usd']}</td><td>${cost} (미확인 {unknown}회)</td></tr>
<tr><td>응답 지연 p50 / p95</td><td>{baseline['latency_p50_ms']/1000:.2f} / {baseline['latency_p95_ms']/1000:.2f}초</td><td>{p50} / {p95}초</td></tr></table>
<p>비교 조건에서 바뀐 것은 코드·프롬프트·구조화 출력·추론 설정입니다. 특정 변경 하나의 독립 효과나 반복 안정성을 측정한 결과는 아닙니다.</p>
<h2>채점과 비용</h2><ul>{''.join(f'<li>{e(LABELS[k])}: {v}</li>' for k,v in counts.items())}</ul>
<p>완결 시나리오: 모든 사전 질문에 적절히 대응하고 마지막 턴이 완전한 답변인 경우. 추가 사용자 답변이 없는 재질문은 해결로 세지 않습니다. 인용 검토 통과 {evidence_correct}/{evidence_reviewed} (검토한 출력 기준).</p>
<p>입력 {summary['input_tokens']:,} / 화면 출력 {summary['visible_output_tokens']:,} / 추론 {summary['thinking_tokens']:,} 토큰. 100만 토큰당 입력 $0.75, 출력·추론 $3.75를 적용한 추정이며 청구액이 아닙니다. 원화는 $1=1,500원 가정입니다. <a href="https://ai.google.dev/gemini-api/docs/pricing">Google 공식 요금표</a>. 전체 캠페인 비용 ÷ 완결 시나리오: {e('$'+cost_resolved if cost_resolved else '산출 불가')}.</p>
<p>위 토큰·달러 합계는 사용량이 확인된 호출만 합산합니다. 미확인 호출이 있으면 전체 비용을 뜻하지 않으며, 0으로 표시된 합계를 무료 또는 청구액 0원으로 해석할 수 없습니다. 답변을 받지 못한 호출과 미실행 질문은 모델 오답으로 판정하지 않습니다.</p>
<p>이번 실행 예산 상한 {e(plan['max_krw'])}원, 자동 재시도 없음. W·실제 임베딩·Storage·서버/DB 비용 제외. 진단용 API 30초 / 모델 27초이며 운영 설정 5초 / 3초는 유지했습니다. 오류를 포함한 실행 {len(actual)}턴 중 5초 이내 {summary['within_5s']}턴. 이력 전달이 확인된 모델 제안 {analysis['turns_with_history']}건.</p>
<h2>질문별 실제 출력과 판정</h2><div class="scroll"><table class="questions"><tr><th>시나리오</th><th>질문·기대 답변</th><th>실제 응답</th><th>잠정 판정</th></tr>{''.join(rows)}</table></div>
<footer>결과 SHA256 {run_hash}<br>입력 {e(run['input_hash'])}<br>원본: run.json, provider-events.jsonl, sdk-events.jsonl, usage.json. 과거 결과는 덮어쓰지 않았습니다.</footer></main></html>'''
    (directory/'AskBuddy-Gemini-live-evaluation.html').write_text(doc,encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False))
    return summary


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('directory',type=Path);p.add_argument('--baseline',type=Path,required=True);p.add_argument('--review',type=Path)
    a=p.parse_args();render(a.directory,a.baseline,a.review)
