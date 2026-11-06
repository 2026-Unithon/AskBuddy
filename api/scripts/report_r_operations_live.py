"""Shareable live evaluation report, built only from recorded outputs and usage."""
import argparse
from collections import Counter
from decimal import Decimal
import hashlib
import html
import json
from math import ceil
from pathlib import Path
from statistics import median


def render(directory,baseline_path):
    read=lambda name:json.loads((directory/name).read_text('utf-8'))
    run=read('run.json'); analysis=read('diagnostic-analysis.json'); baseline=json.loads(baseline_path.read_text('utf-8'))
    if run.get('knowledge_format'):
        raise ValueError('historical RAW report only; use report_r_operations_live_v2 for fact campaigns')
    turns=[(c,t) for c in run['rows'] for t in c['turns']]
    diagnostics={(d['case_id'],d['turn_number']):d for d in analysis['diagnostics']}
    times=sorted(t['elapsed_local_ms'] for _,t in turns)
    errors=Counter(t['response'].get('error',{}).get('code') for _,t in turns if t['http_status']!=200)
    stages=Counter(d['stage'] for d in analysis['diagnostics'])
    details=Counter(d.get('detail') for d in analysis['diagnostics'] if isinstance(d.get('detail'),str) and d['stage']=='SERVER_VALIDATION')
    finish=Counter(reason for c in analysis['calls'] for reason in c['finish_reasons'])
    calls=analysis['generation_calls']; known=Decimal(analysis['known_cost_usd'])
    api_success=sum(t['http_status']==200 for _,t in turns)
    answers=sum(t['response'].get('action')=='ANSWER' for _,t in turns)
    within=sum(t['elapsed_local_ms']<=5000 for _,t in turns)
    summary=dict(evaluated_turns=len(turns),scenario_count=run['scenario_count'],model=run['settings']['gemini_model'],
        successful_api_responses=api_success,answers=answers,error_codes=dict(errors),
        schema_and_validation_failures=dict(stages),validation_details=dict(details),finish_reasons=dict(finish),
        provider_generation_calls=calls,provider_count_tokens_calls=analysis['count_tokens_calls'],
        provider_verification_calls=sum(json.loads(s)['schema']=='Verification' for s in (directory/'provider-events.jsonl').read_text('utf-8').splitlines()),
        input_tokens=sum(c['input_tokens'] or 0 for c in analysis['calls']),
        visible_output_tokens=sum(c['visible_output_tokens'] or 0 for c in analysis['calls']),
        thinking_tokens=sum(c['thinking_tokens'] or 0 for c in analysis['calls']),
        known_cost_usd=str(known),unknown_cost_calls=analysis['unknown_cost_calls'],
        assumed_krw_per_usd=1500,known_cost_krw_at_assumed_rate=str(known*1500),
        mean_cost_per_evaluation_turn_usd=str(known/len(turns)),cost_per_resolved_conversation=None,
        latency_p50_ms=median(times),latency_p95_ms=times[ceil(.95*len(times))-1],within_5s=within,
        required_facts_in_model_candidates=analysis['required_facts_in_model_candidates'],
        turns_with_committed_history=analysis['turns_with_history'],
        original_controls_passed=sum(c['passed'] for c in run['positive_controls']),
        run_sha256=hashlib.sha256((directory/'run.json').read_bytes()).hexdigest(),
        quality_interpretation='End-to-end delivery in synthetic RAW fixture. Does not establish standalone Gemini reasoning accuracy; failures and absent committed history limit interpretation.')
    (directory/'live-summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    e=lambda v:html.escape(str(v))
    labels={'PROVIDER_OR_JSON':'응답 수신·JSON 파싱','PROPOSAL_SCHEMA':'응답 구조 검사','SERVER_VALIDATION':'서버 의미·참조 검사',
        'BASELINE_RETAINED':'모델 미해결 → 기존 행동 유지','STRUCTURE_ACCEPTED':'구조 통과'}
    rows=[]
    for case,t in turns:
        d=diagnostics.get((case['case_id'],t['turn_number']),{})
        body=t['response'];error=body.get('error',{})
        rows.append(f"""<tr><td>{e(case['case_id'])} · {t['turn_number']}턴<br>{e(case['title'])}</td>
<td>{e(t['request']['question'])}<details><summary>기대 답변</summary><p>{e(t['expected']['reference_answer'])}</p></details></td>
<td><b>{e(body.get('action') or error.get('code'))}</b><p>{e(body.get('message') or error.get('message'))}</p><small>{t['elapsed_local_ms']/1000:.2f}초</small></td>
<td>{e(labels.get(d.get('stage'),d.get('stage','미호출')))}<p>모델 제안: {e(d.get('proposed_action') or '완전한 JSON 없음')}</p><details><summary>진단 상세</summary><pre>{e(d.get('detail'))}</pre><p>전달된 이전 사용자 발화: {len(d.get('previous_user_turns',[]))}개</p></details></td></tr>""")
    card=lambda label,value:f'<div class="card"><strong>{e(value)}</strong><span>{e(label)}</span></div>'
    status=('실제 모델을 호출했지만 복합 질문의 최종 응답까지 연결되지 않았습니다.' if answers==0 else '실제 모델 호출 결과와 최종 API 응답을 구분해 확인하세요.')
    known_krw=known*1500
    doc=f'''<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>AskBuddy 실제 Gemini 평가 · 2026-10-06</title><style>
*{{box-sizing:border-box}}body{{font-family:Arial,"Malgun Gothic",sans-serif;margin:0;background:#f5f7fb;color:#18263a;line-height:1.7}}main{{max-width:1400px;margin:36px auto;padding:0 24px}}h1{{font-size:32px;line-height:1.3}}h2{{margin-top:32px;font-size:23px}}.lead{{max-width:980px}}.note{{background:#fff1ce;border-left:5px solid #d68a08;padding:18px 22px;border-radius:8px}}.cards{{display:flex;flex-wrap:wrap;gap:12px;margin:24px 0}}.card{{background:#fff;border:1px solid #dae2ee;border-radius:12px;min-width:180px;padding:18px 22px}}strong{{display:block;font-size:28px}}small,.card span{{color:#526177}}table{{width:100%;border-collapse:collapse;background:white;margin:18px 0}}th,td{{text-align:left;vertical-align:top;border-bottom:1px solid #dce3ed;padding:14px}}th{{background:#e8edf5}}.questions td:nth-child(1){{width:13%}}.questions td:nth-child(2){{width:34%}}.questions td:nth-child(3){{width:25%}}pre{{font:inherit;white-space:pre-wrap;overflow-wrap:anywhere}}summary{{cursor:pointer}}footer{{color:#56647b;font-size:12px;overflow-wrap:anywhere}}@media(max-width:800px){{.tablewrap{{overflow-x:auto}}.questions{{min-width:900px}}h1{{font-size:26px}}}}
</style><main><p>AskBuddy · R 실제 API 평가 · 2026년 10월 6일</p><h1>{e(status)}</h1>
<p class="lead">Gemini <b>{e(summary['model'])}</b> · 합성 비레시피 정책 26개 / 승인 RAW 카드 9개 · 12개 시나리오 / 24턴. 실제 FastAPI ASGI 경로와 일회용 PostgreSQL 17, 41개 migration을 사용했습니다. Gemini는 실제 호출했고 검색 임베딩은 고정 테스트 벡터를 유지했습니다.</p>
<div class="note"><b>해석 범위:</b> 이번 결과는 현재 R 구현의 최종 응답 도달 여부입니다. Gemini 단독의 추론 정답률, 실제 검색 정확도, W 실제 산출물의 품질을 측정한 결과가 아닙니다. 오류로 저장되지 않은 앞선 질문은 다음 모델 호출의 이력에도 포함되지 않습니다. 단일 반복의 합성 진단이며 운영 인수가 아닙니다.</div>
<div class="cards">{card('복합 질문 최종 ANSWER',f'{answers}/24')}{card('정상 API 응답',f'{api_success}/24')}{card('실제 생성 호출',calls)}{card('사용량 기반 비용 추정',f'${known:.4f}')}{card('5초 내 응답 (오류 포함)',f'{within}/24')}</div>
<h2>이전 실험과 비교</h2><table><tr><th>항목</th><th>이전: 모델 OFF</th><th>이번: 실제 Gemini ON</th></tr>
<tr><td>최종 행동</td><td>{e(json.dumps(baseline['action_counts'],ensure_ascii=False))}</td><td>{e(json.dumps(run['action_counts'],ensure_ascii=False))}</td></tr>
<tr><td>API 성공·저장</td><td>{baseline['receipt_verified']}/24</td><td>{run['receipt_verified']}/24</td></tr>
<tr><td>모델 생성 호출</td><td>0회</td><td>{calls}회 · 검증 호출 {summary['provider_verification_calls']}회</td></tr>
<tr><td>현재 확인한 사실</td><td>규칙 기반 처리가 복합 질문을 해결하지 못함</td><td>실제 모델 출력과 서버 계약 사이 실패가 드러남</td></tr></table>
<h2>실패 지점</h2><table><tr><th>지점</th><th>건수</th></tr>{''.join(f'<tr><td>{e(labels.get(k,k))}</td><td>{v}</td></tr>' for k,v in stages.items())}</table>
<p>공급자 종료 사유: {e(dict(finish))}. 서버 검증 상세: {e(dict(details))}. 모델에 실제 전달된 후보에 필요한 사실이 들어 있던 질문은 {analysis['required_facts_in_model_candidates']}/{len(analysis['diagnostics'])}입니다. 이는 고정 벡터·소규모 데이터 조건의 관찰입니다.</p>
<h2>비용과 시간</h2><table><tr><th>항목</th><th>실측 또는 계산 결과</th></tr>
<tr><td>입력 / 화면 출력 / 추론 토큰</td><td>{summary['input_tokens']:,} / {summary['visible_output_tokens']:,} / {summary['thinking_tokens']:,}</td></tr>
<tr><td>단가</td><td>100만 토큰당 입력 $0.75 / 출력·추론 $3.75 · standard · 2026-10-06 확인</td></tr>
<tr><td>사용 토큰 × 공식 단가</td><td>${known:.8f} · 미확인 비용 호출 {analysis['unknown_cost_calls']}회</td></tr>
<tr><td>원화 예시</td><td>약 {known_krw:,.0f}원 (1달러=1,500원 가정, 실제 환율·청구액 아님)</td></tr>
<tr><td>승인된 평가 상한</td><td>10,000원 · 별도 보수적 원화 요율로 호출 전 최대 비용 예약</td></tr>
<tr><td>평가 턴당 평균 / 해결된 대화당 비용</td><td>${known/len(turns):.5f} / 해결 결과가 없어 산출 불가</td></tr>
<tr><td>응답 시간 p50 / p95</td><td>{summary['latency_p50_ms']/1000:.2f}초 / {summary['latency_p95_ms']/1000:.2f}초 · 오류 포함</td></tr>
<tr><td>시간 조건</td><td>격리 평가 API 30초 / 의미 해석 27초. 운영 설정은 API 5초 / 모델 3초로 유지</td></tr></table>
<p>비용은 공급자 usage에 공식 단가를 적용한 <b>추정치</b>이며 청구서 확인액이 아닙니다. 실제 임베딩·W 처리·Storage·서버/DB 비용은 포함하지 않았습니다. 현재 공통 원장의 Gemini 요율은 미설정이어서 원장 값을 덮어쓰지 않고 별도 재계산했습니다. <a href="https://ai.google.dev/gemini-api/docs/pricing">Google 공식 요금표</a></p>
<h2>다음 보완 우선순위</h2><ol><li>모델 출력 계약: 대상 ID와 표시명, predicate 근거, 규격 필드의 의미를 명확히 하고 실제 실패 응답을 회귀 입력으로 고정합니다.</li><li>생성 형식·추론량: 구조화 출력 설정과 추론·출력 토큰 배분을 검토합니다. 잘린 JSON을 임의로 수리해 정답 처리하지 않습니다.</li><li>대화 평가: 첫 질문이 정상 저장되는 경로를 확보한 뒤 후속 맥락과 필요한 재질문을 평가합니다. 실패한 질문을 정상 이력으로 몰래 주입하지 않습니다.</li><li>RAW 계산 범위: 발주량 등 계산 질문은 현재 RAW 경로에서 제한됩니다. 승인된 구조화 수량·연산 지원 범위를 별도로 설계합니다.</li><li>수정 후 동일 조건 재평가, 그다음 W 실제 승인 출력과 실제 임베딩을 연결합니다.</li></ol>
<h2>질문별 실제 결과</h2><div class="tablewrap"><table class="questions"><tr><th>시나리오</th><th>질문·기대 답변</th><th>최종 API 응답</th><th>실패 진단</th></tr>{''.join(rows)}</table></div>
<footer>코드 {e(run['commit'])} · 입력 {e(run['input_hash'])}<br>결과 SHA256 {summary['run_sha256']}<br>모델 응답·사용량 원본: sdk-events.jsonl / provider-events.jsonl / usage.json<br>출처 검증과 기본 원문 조회 대조군 {summary['original_controls_passed']}/3 통과. 본문 해석은 보조자 잠정 검토이며 독립 사람 판정은 아닙니다.</footer></main></html>'''
    (directory/'AskBuddy-Gemini-live-evaluation.html').write_text(doc,encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('directory',type=Path);p.add_argument('--baseline',type=Path,required=True)
    a=p.parse_args();render(a.directory,a.baseline)
