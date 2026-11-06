"""Actual mixed-scope failure and synthetic valid regrouping, never model accuracy."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path

import pytest

from app.contracts.hashing import digest
from app.contracts.snapshot import PublishedKnowledgeSnapshot
from app.contracts.answer import SelectedBlock
from app.learn.general_semantics import GeneralProposal,general_decision,validate_interpretation
from app.learn.general_verification import Verification
from app.learn.general_wire import response_schema
from app.learn.grounded_conclusions import atoms,reference_scopes
from app.learn.planner import decide
from app.learn.semantic_proposals import proposal_input
from app.learn.approved_renderer import render
from app.reg.hybrid import Candidate,SearchResult,normalize_query
from tests.test_r_general_semantics import setup

FROZEN=json.loads((Path(__file__).parent/'fixtures/r_part_scopes_live_20261008.json').read_text('utf-8'))


def fixture():
    payload=FROZEN['request']['input']
    snap=PublishedKnowledgeSnapshot.model_validate(FROZEN['snapshot'])
    candidates=tuple(Candidate(c['card_id'],c['card_version_id'],c['block']['block_id'],None,None,0) for c in payload['candidates'])
    search=SearchResult(snap,1,candidates,normalize_query(payload['question']))
    baseline=decide(search,store_id=1,question=payload['question'])
    return search,payload,baseline


def regrouped():
    # Synthetic example only: production never rewrites failed model proposals.
    search,_,_=fixture();raw=deepcopy(FROZEN['proposal']);template=raw['parts'][0]
    raw['parts']=[]
    for ref in raw['plan']['selected_blocks']:
        part=deepcopy(template);entity=search.snapshot.card(ref['card_id']).entity_id
        part['plan']['selected_blocks']=[deepcopy(ref)]
        part['interpretation']['entity_id']=entity
        for slot in part['slots']:
            if slot['slot']=='entity':slot['value']=entity
        raw['parts'].append(part)
    return raw


def test_actual_case_grouped_parts_remain_rejected_without_repair():
    search,payload,baseline=fixture();raw=deepcopy(FROZEN['proposal'])
    with pytest.raises(ValueError,match='entity scope'):
        validate_interpretation(search,payload=payload,proposal=raw,baseline=baseline,confirmed_slots={})
    assert raw==FROZEN['proposal']


def test_three_evidence_parts_can_support_two_case_conclusions():
    search,payload,baseline=fixture();raw=regrouped()
    raw['case_requirements']=dict(scope='CASE_ACTIONS',rationale='Synthetic question requirements',cases=[
        dict(subject=dict(turn_id=0,quote=name),state=dict(turn_id=0,quote=state))
        for name,state in (('A','결제 상태 미확인'),('B','환불 승인 대기'))])
    decision=validate_interpretation(search,payload=payload,proposal=raw,baseline=baseline,confirmed_slots={})
    assert len(decision.resolved.parts)==3 and len(decision.resolved.conclusions)==2
    assert not decision.resolved.conclusions_verified
    assert atoms(decision.resolved.conclusions[0].references)&atoms(decision.resolved.conclusions[1].references)


@pytest.mark.parametrize('change',['mixed_entity','missing_parent_ref','extra_parent_ref','forged_version','foreign_conclusion'])
def test_regrouping_cannot_bypass_scope_union_or_citation_checks(change):
    search,payload,baseline=fixture();raw=regrouped()
    if change=='mixed_entity':raw['parts'][0]['plan']['selected_blocks'].append(raw['plan']['selected_blocks'][1])
    if change=='missing_parent_ref':raw['plan']['selected_blocks'].pop()
    if change=='extra_parent_ref':raw['parts'].pop()
    if change=='forged_version':raw['parts'][0]['plan']['selected_blocks'][0]['card_version_id']='999'
    if change=='foreign_conclusion':raw['conclusions'][0]['references'][0]['card_id']='999'
    with pytest.raises(ValueError):validate_interpretation(search,payload=payload,proposal=raw,baseline=baseline,confirmed_slots={})


def test_scope_table_contains_only_retrieved_references_with_approved_entity():
    search,_,_=fixture()
    scoped=replace(search,candidates=search.candidates[:2]);scopes=reference_scopes(scoped)
    actual={(r['card_id'],r['block_id']) for s in scopes for r in s['references']}
    assert actual=={(c.card_id,c.block_id) for c in scoped.candidates}
    assert len(actual)<len(search.candidates)
    for scope in scopes:
        assert all(scoped.snapshot.card(r['card_id']).entity_id==scope['entity_id'] for r in scope['references'])
    assert reference_scopes(replace(search,candidates=()))==[]


@pytest.mark.asyncio
async def test_scopes_reach_both_calls_and_verified_cross_part_conclusions_render(tmp_path):
    search,payload,baseline=fixture();raw=regrouped()
    raw['case_requirements']=dict(scope='CASE_ACTIONS',rationale='Synthetic question requirements',cases=[
        dict(subject=dict(turn_id=0,quote=name),state=dict(turn_id=0,quote=state))
        for name,state in (('A','결제 상태 미확인'),('B','환불 승인 대기'))])
    _,_,kw,release=setup(tmp_path)
    release.update(snapshot_hash=search.snapshot.snapshot_hash,response_style='grounded_conclusion')
    kw['settings'].r_general_semantics_path.write_text(json.dumps(release),encoding='utf-8')
    kw['settings'].r_general_semantics_hash=digest(release)
    kw.update(question=payload['question'],user_turns=(),baseline=baseline,confirmed_slots={})
    stages=[]
    async def provider(prompt,*,schema,**unused):
        request=json.loads(prompt.rsplit('\n',1)[1]);stages.append(schema.__name__)
        if schema is GeneralProposal:
            assert request['capabilities']['reference_scopes']==reference_scopes(search)
            return raw
        assert schema is Verification and request['reference_scopes']==reference_scopes(search)
        assert request['request_hash']==digest({k:v for k,v in request.items() if k!='request_hash'})
        selected=atoms(GeneralProposal.model_validate(raw).plan.selected_blocks)
        conclusions=GeneralProposal.model_validate(raw).conclusions
        rules=[]
        for r in request['selected_rules']:
            ref=atoms((SelectedBlock.model_validate(r['reference']),))
            n=next(i for i,c in enumerate(conclusions) if ref<=atoms(c.references))
            rules.append(dict(rule_id=r['rule_id'],required=True,conclusion_unit_id=f'c{n}s0',
                rationale='Synthetic structural audit only; not semantic truth'))
        return dict(request_hash=request['request_hash'],supported=True,unresolved=[],
            **request['selected_reference_check'],checked_user_turn_ids=[0],checked_conclusion_ids=[0,1],
            rule_coverage=rules,candidate_coverage=[dict(reference=r,required=bool(atoms((SelectedBlock.model_validate(r),))&selected),
                rationale='Synthetic structural fixture') for r in request['candidate_reference_units']],
            situation_review=[dict(conclusion_unit_id=u['unit_id'],status='GROUNDED_CASE_FACTS',user_evidence=request['proposal']['conclusions'][u['conclusion_id']]['user_evidence'],rationale='Synthetic structural fixture only') for u in request['conclusion_units']],
            case_action_review=dict(scope='CASE_ACTIONS',rationale='Synthetic two-case application fixture',cases=[
                dict(subject=dict(turn_id=0,quote=name),state=dict(turn_id=0,quote=state),conclusion_id=n,
                    next_action_quote=conclusions[n].statement)
                for n,(name,state) in enumerate((('A','결제 상태 미확인'),('B','환불 승인 대기')))]))
    decision,audit=await general_decision(search,provider=provider,**kw)
    assert stages==['GeneralProposal','Verification'] and decision.resolved.conclusions_verified
    assert audit['case_action_review']['scope']=='CASE_ACTIONS'
    response=render(decision.plan,search.snapshot,store_id=1,request_id='scope-combination',resolved=decision.resolved)
    assert len(response.citations)==3
    assert all(c['statement'] in response.message for c in raw['conclusions'])


def test_wire_describes_knowledge_scope_and_cross_part_conclusions():
    schema=response_schema(GeneralProposal)
    assert 'one knowledge entity' in schema['$defs']['AnswerPart']['properties']['plan']['description'].lower()
    assert 'multiple independently validated parts' in schema['properties']['conclusions']['description']
