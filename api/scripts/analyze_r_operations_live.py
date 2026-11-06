"""Replay recorded Gemini proposals locally and price observed tokens; no API calls."""
import argparse
from collections import Counter
from dataclasses import replace
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.contracts.snapshot import PublishedKnowledgeSnapshot
from app.learn.general_semantics import GeneralProposal,validate_interpretation
from app.learn.general_wire import parse_proposal
from app.learn.general_provider import usage_tokens
from app.learn.planner import decide
from app.reg.hybrid import Candidate,SearchResult,normalize_query


def analyze(directory):
    read=lambda name:json.loads((directory/name).read_text('utf-8'))
    snapshot=PublishedKnowledgeSnapshot.model_validate(read('published-snapshot.json'))
    challenge=read('frozen-challenge.json')
    lookup={t['question']:(c['case_id'],n) for c in challenge['cases'] for n,t in enumerate(c['turns'],1)}
    expected={t['question']:t for c in challenge['cases'] for t in c['turns']}
    for case in challenge['cases']:
        for n,t in enumerate(case['turns']):
            if t.get('select_option') and n:
                for option in dict.fromkeys((t['question'],t['select_option'],*t.get('select_option_aliases',[]))):
                    expanded=case['turns'][n-1]['question']+' '+option
                    lookup[expanded]=(case['case_id'],n+1)
                    expected[expanded]=t
    fact_map={m['card_id']:m['fact_ids'] for m in read('fact-card-map.json')}
    events=[json.loads(s) for s in (directory/'provider-events.jsonl').read_text('utf-8').splitlines()]
    diagnostics=[]
    for event in events:
        if event['schema']!='GeneralProposal':continue
        data=json.loads(event['prompt'].rsplit('\n',1)[-1])
        payload=data['input']
        case,turn=lookup[payload['question']]
        item=dict(case_id=case,turn_number=turn,question=payload['question'],
            previous_user_turns=payload['user_turns'],elapsed_ms=event['elapsed_ms'],
            proposed_action=event.get('output',{}).get('plan',{}).get('action'))
        candidate_facts={fid for c in payload['candidates'] for fid in fact_map[c['card_id']]}
        item['required_facts_in_model_candidates']=set(expected[payload['question']]['required_fact_ids'])<=candidate_facts
        if 'exception_type' in event:
            item.update(stage='BUDGET_BLOCKED' if event['exception_type']=='BudgetDenied' else 'PROVIDER_OR_JSON',
                error=event['exception_type'],detail=event.get('exception_message'))
        else:
            candidates=tuple(Candidate(c['card_id'],c['card_version_id'],c['block']['block_id'],None,None,0)
                for c in payload['candidates'])
            search=SearchResult(snapshot,1,candidates,normalize_query(payload['question']))
            baseline=decide(search,store_id=int(payload['store_id']),question=payload['question'])
            baseline=replace(baseline,confirmed_slots=data['confirmed_slots'])
            try:
                proposal=parse_proposal(event['output'])
            except ValueError as exc:
                item.update(stage='PROPOSAL_SCHEMA',error=type(exc).__name__,detail=str(exc))
            else:
                try:
                    decision=validate_interpretation(search,payload=payload,proposal=proposal,baseline=baseline,
                        confirmed_slots=data['confirmed_slots'])
                    item.update(stage='BASELINE_RETAINED' if decision is baseline else 'STRUCTURE_ACCEPTED',
                        error=None,detail=list(proposal.unresolved))
                except (ValueError,KeyError,StopIteration) as exc:
                    item.update(stage='SERVER_VALIDATION',error=type(exc).__name__,detail=str(exc))
        diagnostics.append(item)
    sdk=[json.loads(s) for s in (directory/'sdk-events.jsonl').read_text('utf-8').splitlines()]
    generated=[e for e in sdk if e['method']=='generate_content']
    costs=[]
    plan=read('evaluation-plan.json')
    for i,event in enumerate(generated,1):
        response=event.get('response',{})
        usage=response.get('usage_metadata') or {}
        inp,out,thought=usage_tokens(usage)
        cached=usage.get('cached_content_token_count')
        known=all(type(n)is int and n>=0 for n in (inp,out,thought))
        # No caching was requested. Any observed cache/other charge makes this
        # simple standard-price calculation partial rather than silently wrong.
        known=known and cached in (None,0) and usage.get('tool_use_prompt_token_count') in (None,0)
        usd=(Decimal(inp)*Decimal(plan['input_usd_per_million'])+
            Decimal(out+thought)*Decimal(plan['output_usd_per_million']))/Decimal(1000000) if known else None
        costs.append(dict(call=i,requested_model=event['model'],reported_model=response.get('model_version'),
            response_id=response.get('response_id'),elapsed_ms=event['elapsed_ms'],
            finish_reasons=[c.get('finish_reason') for c in response.get('candidates') or []],
            input_tokens=inp,visible_output_tokens=out,thinking_tokens=thought,
            billable_output_tokens=out+thought if known else None,cost_usd=str(usd) if usd is not None else None,
            exception=event.get('exception_type'),cost_status='TOKEN_BASED_ESTIMATE' if known else 'UNKNOWN'))
    known_cost=sum((Decimal(c['cost_usd']) for c in costs if c['cost_usd'] is not None),Decimal(0))
    report=dict(schema_version='r-live-diagnostic/v1',provisional_review=True,
        source_provider_events_sha256=hashlib.sha256((directory/'provider-events.jsonl').read_bytes()).hexdigest(),
        diagnostic_counts=dict(Counter(d['stage'] for d in diagnostics)),diagnostics=diagnostics,
        required_facts_in_model_candidates=sum(d['required_facts_in_model_candidates'] for d in diagnostics),
        turns_with_history=sum(bool(d['previous_user_turns']) for d in diagnostics),
        generation_calls=len(generated),count_tokens_calls=sum(e['method']=='count_tokens' for e in sdk),
        known_cost_usd=str(known_cost),unknown_cost_calls=sum(c['cost_usd'] is None for c in costs),
        assumed_krw_per_usd=1500,known_cost_krw_at_assumed_rate=str(known_cost*1500),
        pricing_reference=plan['pricing_reference'],calls=costs,
        note='Usage-based standard-price estimate, not provider invoice; excludes embedding, W extraction, storage and server/DB costs. Diagnostic replay performs no model calls. Failed API turns are not durable user history.')
    (directory/'diagnostic-analysis.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in ('calls','diagnostics','pricing_reference','note')},ensure_ascii=False))
    for d in diagnostics:print(d['case_id'],d['turn_number'],d['stage'],str(d['detail'])[:230])

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('directory',type=Path)
    analyze(parser.parse_args().directory)
