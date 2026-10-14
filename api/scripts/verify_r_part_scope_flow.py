"""Actual API/DB OD06 flow with synthetic model responses; no paid calls.

The fixture checks transport, provenance, storage and rendering only. Its
supported verdicts are not evidence of the model's semantic accuracy.
"""
import argparse
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import sys
from types import SimpleNamespace as NS
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'api'))
import scripts.run_r_operations_http as runner
from app.contracts.hashing import digest
from app.contracts.answer import SelectedBlock
from app.learn.general_semantics import GeneralProposal,source_hash
from app.learn.grounded_conclusions import atoms


async def main(output):
    output.mkdir(parents=True,exist_ok=False)
    frozen=json.loads((ROOT/'api/tests/fixtures/r_part_scopes_live_20261008.json').read_text('utf-8'))
    original=frozen['request']['input']['question']
    challenge=json.loads((ROOT/'output/r-case-actions-20261008/prepared-challenge.json').read_text('utf-8'))
    path=output/'input.json';runner.write_new(path,challenge)
    plan=json.loads((ROOT/'output/r-case-actions-20261008/plan.json').read_text('utf-8'))
    plan.update(source_hash=source_hash(),paid_provider='synthetic-no-network',
        status='SYNTHETIC_API_DB_CHECK_NOT_PAID_OR_QUALITY_EVALUATION')
    plan_path=output/'plan.json';runner.write_new(plan_path,plan)
    calls=[];proposal_count=0

    async def generate(prompt,*,schema,**unused):
        nonlocal proposal_count
        req=json.loads(prompt.rsplit('\n',1)[1]);calls.append(schema.__name__)
        if schema is GeneralProposal:
            proposal_count+=1
            payload=req['input'];raw=deepcopy(frozen['proposal'])
            raw.update(input_hash=payload['input_hash'],snapshot_hash=payload['snapshot_hash'])
            if proposal_count==2:
                raw.update(parts=[],slots=[],interpretation=None,conclusions=[],obligations=[])
                options=['A는 결제 상태 미확인','B는 환불 승인 대기']
                at=payload['user_turns'].index(original)
                raw['plan']=dict(snapshot_id=payload['snapshot_id'],knowledge_revision=payload['knowledge_revision'],
                    action='CLARIFY',clarification_slot='case',allowed_options=options,selected_blocks=[])
                raw['case_options']=[dict(label=label,turn_id=at,question_quote=original) for label in options]
                return raw
            if proposal_count==1:assert payload['question']==original
            else:
                assert proposal_count==3 and req['confirmed_slots']=={'case':'A는 결제 상태 미확인'}
                assert payload['question'].endswith(' A는 결제 상태 미확인') and original in payload['user_turns']
                raw['plan']['selected_blocks']=raw['plan']['selected_blocks'][:2]
                at=payload['user_turns'].index(original)
                raw['conclusions']=[dict(statement='A는 결제 상태 미확인 상태이므로 대기 건으로 남기고 당직 관리자에게 확인을 요청하세요. 메시지 읽음만으로 인계 완료가 아니며 지정 인수자의 업무 인수 확인이 필요합니다.',
                    question_quote=payload['question'],user_evidence=[dict(turn_id=at,quote=original)],references=deepcopy(raw['plan']['selected_blocks']))]
            template=deepcopy(raw['parts'][0]);raw['parts']=[]
            for ref in raw['plan']['selected_blocks']:
                entity=next(c['entity_id'] for c in payload['candidates'] if c['card_id']==ref['card_id'])
                part=deepcopy(template);part['plan']['selected_blocks']=[deepcopy(ref)]
                part['interpretation']['entity_id']=entity
                for slot in part['slots']:
                    slot['question_quote']=payload['question']
                    if slot['slot']=='entity':slot['value']=entity
                raw['parts'].append(part)
            return raw
        proposal=req['proposal']
        verdict=dict(request_hash=req['request_hash'],supported=True,unresolved=[],
            **req['selected_reference_check'],checked_user_turn_ids=list(range(len(req['dialogue_turns']))),
            checked_conclusion_ids=list(range(len(proposal['conclusions']))),rule_coverage=[],candidate_coverage=[])
        if proposal['plan']['action']=='CLARIFY':
            verdict.update(supported=False,reason_code='MISSING_USER_INFO',reason_detail='Synthetic ambiguous case fixture',
                clarification=dict(slot='case',scope_supported=True,allowed_options=proposal['plan']['allowed_options'],case_options=proposal['case_options']))
            return verdict
        selected=atoms(GeneralProposal.model_validate(proposal).plan.selected_blocks)
        cs=GeneralProposal.model_validate(proposal).conclusions
        verdict['candidate_coverage']=[dict(reference=r,required=bool(atoms((SelectedBlock.model_validate(r),))&selected),
            rationale='Synthetic structural fixture only') for r in req['candidate_reference_units']]
        for rule in req['selected_rules']:
            ref=atoms((SelectedBlock.model_validate(rule['reference']),))
            n=next(i for i,c in enumerate(cs) if ref<=atoms(c.references))
            verdict['rule_coverage'].append(dict(rule_id=rule['rule_id'],required=True,conclusion_unit_id=f'c{n}s0',
                rationale='Synthetic structural fixture, not semantic truth'))
        at=next(t['turn_id'] for t in req['dialogue_turns'] if t['text']==original)
        cases=[('A','결제 상태 미확인'),('B','환불 승인 대기')] if proposal_count==1 else [('A','결제 상태 미확인')]
        verdict['situation_review']=[dict(conclusion_unit_id=u['unit_id'],status='GROUNDED_CASE_FACTS',user_evidence=req['proposal']['conclusions'][u['conclusion_id']]['user_evidence'],rationale='Synthetic structural fixture only') for u in req['conclusion_units']]
        verdict['case_action_review']=dict(scope='CASE_ACTIONS',rationale='Synthetic structural fixture',cases=[
            dict(subject=dict(turn_id=at,quote=name),state=dict(turn_id=at,quote=state),conclusion_id=n,next_action_quote=cs[n].statement)
            for n,(name,state) in enumerate(cases)])
        return verdict

    args=NS(input=path,output=output/'run',live_plan=plan_path,plan_hash=digest(plan),approved_by='SYNTHETIC NO NETWORK CHECK')
    with (patch('app.config.get_settings',return_value=NS(gemini_model='synthetic-no-network',gemini_api_key='synthetic')),
            patch('app.learn.general_provider.generate',side_effect=generate),
            patch('google.genai.Client',side_effect=AssertionError('External SDK must not be called'))):
        await runner.main(args)
    result_path=args.output/'run.json';result=json.loads(result_path.read_text('utf-8'))
    result.update(provider_mode='SYNTHETIC_STRUCTURED_RESPONSES',quality_evaluation=False,paid_calls=0)
    result_path.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    turns=result['rows'][0]['turns']
    assert result['http_success']==3 and result['receipt_verified']==3
    assert [t['response']['action'] for t in turns]==['ANSWER','CLARIFY','ANSWER']
    assert [len(t['response']['citations']) for t in (turns[0],turns[2])]==[3,2]
    assert all(t['citation_reads_verified'] for t in (turns[0],turns[2]))
    assert turns[2]['request']['question']==turns[2]['request']['option']=='A는 결제 상태 미확인'
    assert calls==['GeneralProposal','Verification']*3
    print('PASS actual API/DB: three knowledge scopes -> two case conclusions -> descriptive A/B clarification -> actual A selection -> cited answer; zero external SDK calls')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    asyncio.run(main(parser.parse_args().output))
