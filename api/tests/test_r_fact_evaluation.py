"""Frozen representation and exact immutable-reference accounting."""
from copy import deepcopy
import pytest
from scripts.r_fact_evaluation import (challenge_hash,freeze_challenge,validate_challenge,
    candidate_fact_ids,cited_fact_ids,validate_live_fixture_plan,FORMAT)
from scripts.report_r_operations_live_v2 import validate_comparison


def original():
    value=dict(facts=[dict(fact_id='F1',category='검증정책',assertion='조건이 맞으면 원문을 확인한다.')],
        cases=[dict(turns=[dict(required_fact_ids=['F1'])])])
    value['content_sha256']=challenge_hash(value)
    return value


def test_conversion_is_new_hash_and_preserves_original_rule_and_parent():
    old=original();before=deepcopy(old)
    new=freeze_challenge(old)
    assert old==before and new['content_sha256']!=old['content_sha256']
    assert new['parent_challenge_hash']==old['content_sha256']
    assert new['facts'][0]['w_assertion']['original_assertion']==old['facts'][0]['assertion']
    assert new['facts'][0]['w_assertion']['value']==old['facts'][0]['assertion']
    assert new['cases']==old['cases']
    with pytest.raises(ValueError):validate_challenge(old)


@pytest.mark.parametrize('change',['hash','duplicate','unknown','assertion'])
def test_rejects_tampered_or_ambiguous_fixture(change):
    value=freeze_challenge(original())
    if change=='duplicate':value['facts'].append(deepcopy(value['facts'][0]))
    if change=='unknown':value['cases'][0]['turns'][0]['required_fact_ids']=['F2']
    if change=='assertion':value['facts'][0]['w_assertion']['original_assertion']='다른 문장'
    value['content_sha256']='bad' if change=='hash' else challenge_hash(value)
    with pytest.raises(ValueError):validate_challenge(value)


def test_candidate_and_citation_mapping_require_exact_version_block_and_revision():
    refs=[dict(card_id='1',card_version_id='2',block_id='a',fact_revision_id='10'),
          dict(card_id='1',card_version_id='2',block_id='b',fact_revision_id='11')]
    mapping=[dict(fact_id=f'F{n}',references=[r]) for n,r in enumerate(refs)]
    assert candidate_fact_ids(mapping,[refs[0]])==['F0']
    assert candidate_fact_ids(mapping,[dict(refs[0],card_version_id='1')])==[]
    assert cited_fact_ids(mapping,[refs[0]])==['F0']
    assert cited_fact_ids(mapping,[dict(refs[0],fact_revision_id='11')])==[]


def test_paid_plan_must_pin_new_representation_and_evaluator(monkeypatch):
    from app.contracts.hashing import digest
    monkeypatch.setattr('scripts.r_fact_evaluation.evaluator_sources',lambda:{'file':'new-code'})
    good=dict(knowledge_format=FORMAT,evaluator_source_hash=digest({'file':'new-code'}))
    validate_live_fixture_plan(good)
    for value in ({},dict(good,knowledge_format='RAW'),dict(good,evaluator_source_hash='old')):
        with pytest.raises(ValueError):validate_live_fixture_plan(value)


def test_fact_report_refuses_raw_or_different_frozen_input_comparison():
    run=dict(knowledge_format=FORMAT,input_hash='fact-challenge')
    validate_comparison(run,run)
    validate_comparison({}, {})  # Historical report regeneration remains supported.
    for baseline in ({},dict(run,input_hash='other')):
        with pytest.raises(ValueError):validate_comparison(run,baseline)
    with pytest.raises(ValueError):validate_comparison(dict(knowledge_format=FORMAT),dict(knowledge_format=FORMAT))
