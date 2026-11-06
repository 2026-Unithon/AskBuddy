"""실제 실패 보존과 합성 새 계약 검사. 모델 의미 정확도 평가는 아니다."""
from copy import deepcopy
import json
from pathlib import Path
import pytest
from app.contracts.hashing import digest
from app.contracts.snapshot import PublishedKnowledgeSnapshot
from app.errors import ApiError
from app.learn.general_semantics import GeneralProposal,general_decision
from app.learn.general_verification import Verification
from app.learn.general_wire import response_schema
from app.learn.grounded_conclusions import (GroundedConclusion,RuleCoverage,SituationReview,
    conclusion_units,missing_conclusion_rules,unsupported_situations)
from app.learn.planner import decide
from app.reg.hybrid import Candidate,SearchResult,normalize_query
from tests.test_r_general_semantics import setup

FROZEN=json.loads((Path(__file__).parent/'fixtures/r_conclusion_units_live_20261008.json').read_text('utf-8'))


def conclusions():
    return GeneralProposal.model_validate(FROZEN['proposal']).conclusions


def review():
    return [dict(conclusion_unit_id=u['unit_id'],status='GROUNDED_CASE_FACTS',
        user_evidence=[e.model_dump() for e in conclusions()[u['conclusion_id']].user_evidence],
        rationale='합성 검사: 모든 사실의 의미를 검증했다는 증거가 아님') for u in conclusion_units(conclusions())]


def check(rows,cs=None):
    return unsupported_situations(tuple(SituationReview.model_validate(x) for x in rows),cs or conclusions(),
        question=FROZEN['request']['input']['question'],user_turns=())


def test_actual_wrong_quote_preserved_and_old_wire_cannot_silently_pass():
    row=next(x for x in FROZEN['verification']['rule_coverage'] if x['rule_id']=='r4')
    assert row['conclusion_quote'] not in conclusions()[row['conclusion_id']].statement
    with pytest.raises(ValueError):Verification.model_validate(FROZEN['verification'])
    wire=response_schema(Verification)
    assert 'conclusion_quote' not in wire['$defs']['RuleCoverage']['properties']
    assert 'situation_review' in wire['required']
    assert set(wire['$defs']['RuleCoverage']['required'])<=set(wire['$defs']['RuleCoverage']['properties'])


def test_units_preserve_exact_positions_without_decimal_or_clause_rewriting():
    text='1.5만원이면 확인합니다.\nA의 승인은 대기입니다! 그 외는 확인하세요'
    c=conclusions()[0].model_copy(update={'statement':text})
    units=conclusion_units((c,))
    assert [u['unit_id'] for u in units]==['c0s0','c0s1','c0s2']
    assert units[0]['text']=='1.5만원이면 확인합니다.'
    assert all(text[u['start']:u['end']]==u['text'] for u in units)


@pytest.mark.parametrize('change',['unknown','foreign','missing','duplicate'])
def test_rule_selection_still_requires_actual_conclusion_and_cited_policy(change):
    rules=FROZEN['verification_request']['selected_rules']
    coverage=[]
    for r in rules:
        n=next(i for i,c in enumerate(conclusions()) if r['reference'] in [x.model_dump(mode='json') for x in c.references])
        coverage.append(dict(rule_id=r['rule_id'],required=True,conclusion_unit_id=f'c{n}s0',rationale='합성'))
    assert missing_conclusion_rules(rules,tuple(RuleCoverage.model_validate(x) for x in coverage),conclusions())==[]
    target=next(x for x in coverage if x['rule_id']=='r4')
    if change=='unknown':target['conclusion_unit_id']='c7s0'
    if change=='foreign':target['conclusion_unit_id']='c1s0'
    if change=='missing':target['conclusion_unit_id']=None
    if change=='duplicate':coverage.append(deepcopy(target))
    if change=='missing':
        assert missing_conclusion_rules(rules,tuple(RuleCoverage.model_validate(x) for x in coverage),conclusions())==['r4']
    else:
        with pytest.raises(ValueError):missing_conclusion_rules(rules,tuple(RuleCoverage.model_validate(x) for x in coverage),conclusions())


@pytest.mark.parametrize('change',['omitted','duplicate','unknown','empty_evidence','invented_evidence','wrong_turn','blank_reason','noncase_evidence','unbound'])
def test_situation_inspection_cannot_omit_or_forge_user_provenance(change):
    rows=review();cs=conclusions()
    if change=='omitted':rows.pop()
    if change=='duplicate':rows.append(deepcopy(rows[0]))
    if change=='unknown':rows[0]['conclusion_unit_id']='c7s0'
    if change=='empty_evidence':rows[0]['user_evidence']=[]
    if change=='invented_evidence':rows[0]['user_evidence'][0]['quote']='3만원'
    if change=='wrong_turn':rows[0]['user_evidence'][0]['turn_id']=9
    if change=='blank_reason':rows[0]['rationale']=' '
    if change=='noncase_evidence':rows[0]['status']='NO_CASE_FACTS'
    if change=='unbound':cs=(cs[0].model_copy(update={'user_evidence':()}),cs[1])
    with pytest.raises(ValueError):check(rows,cs)


def test_unconfirmed_approval_reason_is_rejected_without_requiring_new_user_info():
    rows=review();rows[1]['status']='UNSUPPORTED_CASE_FACTS'
    assert '2만원 초과 또는 이전 영업일' in conclusions()[1].statement
    assert check(rows)==['c1s0']
    # 합성 허용 예: 명시적 조건부 정책 안내는 사건 금액을 단정하지 않는다.
    cs=(conclusions()[0].model_copy(update={'statement':'2만원 초과인 경우에는 점주 승인을 먼저 받으세요.'}),)
    assert check([dict(conclusion_unit_id='c0s0',status='NO_CASE_FACTS',user_evidence=[],rationale='조건부 정책 안내')],cs)==[]


@pytest.mark.asyncio
@pytest.mark.parametrize('unsupported',[False,True])
async def test_current_contract_hash_binding_and_unsupported_case_blocks_supported_verdict(tmp_path,unsupported):
    snap=PublishedKnowledgeSnapshot.model_validate(FROZEN['snapshot']);payload=FROZEN['request']['input']
    candidates=tuple(Candidate(c['card_id'],c['card_version_id'],c['block']['block_id'],None,None,0) for c in payload['candidates'])
    search=SearchResult(snap,1,candidates,normalize_query(payload['question']))
    _,_,kw,release=setup(tmp_path)
    release.update(snapshot_hash=snap.snapshot_hash,response_style='grounded_conclusion')
    kw['settings'].r_general_semantics_path.write_text(json.dumps(release),encoding='utf-8')
    kw['settings'].r_general_semantics_hash=digest(release)
    kw.update(question=payload['question'],user_turns=(),confirmed_slots={},baseline=decide(search,store_id=1,question=payload['question']))
    raw=deepcopy(FROZEN['proposal'])
    raw['case_requirements']=dict(scope='CASE_ACTIONS',rationale='Synthetic current protocol requirements',cases=[
        dict(subject=c['subject'],state=c['state']) for c in FROZEN['verification']['case_action_review']['cases']])
    # 양성 예는 별도 합성 결론이다. 실제 잘못된 사유를 성공 사례로 바꾸지 않는다.
    if not unsupported:
        raw['conclusions'][1]['statement']='사건 B(환불 승인 대기)는 승인 대기 상태와 다음 조치를 기록하고 점주 승인 후 원거래 기록을 확인하세요.'
    async def provider(prompt,*,schema,**unused):
        if schema is GeneralProposal:return raw
        req=json.loads(prompt.rsplit('\n',1)[1])
        assert req['request_hash']==digest({k:v for k,v in req.items() if k!='request_hash'})
        altered=deepcopy(req);altered['conclusion_units'][0]['text']='변경된 결론'
        assert req['request_hash']!=digest({k:v for k,v in altered.items() if k!='request_hash'})
        value=deepcopy(FROZEN['verification']);value['request_hash']=req['request_hash']
        for row in value['rule_coverage']:
            n=row.pop('conclusion_id');row.pop('conclusion_quote')
            row['conclusion_unit_id']=None if n is None else f'c{n}s0'
        value['situation_review']=review()
        if unsupported:value['situation_review'][1]['status']='UNSUPPORTED_CASE_FACTS'
        else:value['case_action_review']['cases'][1]['next_action_quote']='점주 승인 후 원거래 기록을 확인'
        return value
    if unsupported:
        with pytest.raises(ApiError) as error:await general_decision(search,provider=provider,**kw)
        assert error.value.code=='GENERAL_VERIFICATION_REJECTED'
        assert error.value.details['reason_code']=='CONTEXT_CONFLICT'
    else:
        decision,audit=await general_decision(search,provider=provider,**kw)
        assert decision.resolved.conclusions_verified
        assert audit['conclusion_units']==conclusion_units(decision.resolved.conclusions)
        assert audit['situation_review'][1]['status']=='GROUNDED_CASE_FACTS'
