"""Trusted retrieved quantities and verbatim user evidence constrain model output."""
import json
from app.learn.general_wire import response_schema
from app.learn.general_semantics import GeneralProposal,general_decision,validate_interpretation
from tests.test_r_general_semantics import setup,provider_for
import pytest
from dataclasses import replace
from app.learn.semantic_proposals import proposal_input


def test_raw_wire_has_no_calculation_language_and_requires_evidence_fields():
    wire=response_schema(GeneralProposal,calculation_fact_ids=(),question_quotes=('현재 질문','이전 발화','현재 질문'))
    assert 'calculations' not in wire['properties'] and 'Calculation' not in wire['$defs']
    assert wire['additionalProperties'] is False
    assert {'slots','parts','interpretation','obligations','unresolved'}<=set(wire['required'])
    assert 'slots' in wire['$defs']['AnswerPart']['required']
    assert wire['$defs']['SlotProposal']['properties']['question_quote']['enum']==['현재 질문','이전 발화']
    assert 'calculations' in GeneralProposal.model_json_schema()['properties']
    assert 'schema_version' not in wire['properties']
    assert 'schema_version' not in wire['$defs']['AnswerPlan']['properties']
    assert 'schema_version' in GeneralProposal.model_json_schema()['properties']


def test_typed_wire_preserves_calculations_with_only_retrieved_operand_ids():
    wire=response_schema(GeneralProposal,calculation_fact_ids=('11','12','11'),question_quotes=('질문',))
    assert wire['$defs']['Calculation']['properties']['fact_ids']['items']['enum']==['11','12']
    assert 'calculations' in wire['properties']


@pytest.mark.asyncio
async def test_runtime_supplies_raw_capability_and_user_only_quote_choices(tmp_path):
    search,raw,kw,_=setup(tmp_path)
    search=replace(search,candidates=tuple(c for c in search.candidates
        if next(b for b in search.snapshot.card(c.card_id).blocks if b.block_id==c.block_id).raw_span_id))
    raw['input_hash']=proposal_input(search,store_id=1,question=kw['question'])['input_hash']
    provider=provider_for(search,raw)
    decision,_=await general_decision(search,provider=provider,**kw)
    assert decision.plan.action=='ANSWER'
    proposal=provider.call_args_list[0]
    assert proposal.kwargs['calculation_fact_ids']==()
    assert proposal.kwargs['question_quotes']==(kw['question'],)
    body=json.loads(proposal.args[0].rsplit('\n',1)[-1])
    assert body['capabilities']['calculation_fact_ids']==[]
    assert body['capabilities']['slot_quote_choices']==[kw['question']]
    assert 'question_quotes' not in provider.call_args_list[1].kwargs


@pytest.mark.asyncio
async def test_mixed_candidates_keep_approved_typed_calculation_capability(tmp_path):
    search,raw,kw,_=setup(tmp_path)
    provider=provider_for(search,raw)
    await general_decision(search,provider=provider,**kw)
    assert provider.call_args_list[0].kwargs['calculation_fact_ids']==('900','901','902')


def test_explicit_unsupported_raw_calculation_escalates_without_repeating_entity_choice():
    from tests.test_r_general_live_contract import live_case
    _,search,payload,baseline=live_case('O03')
    assert baseline.plan.action=='CLARIFY'
    raw=dict(snapshot_hash=payload['snapshot_hash'],input_hash=payload['input_hash'],
        plan=dict(snapshot_id=payload['snapshot_id'],knowledge_revision=payload['knowledge_revision'],
            action='ESCALATE',escalation_reason='model technical detail'),
        unsupported_calculation=True,unresolved=['no supported operands'])
    result=validate_interpretation(search,payload=payload,proposal=raw,baseline=baseline,confirmed_slots={})
    assert result.plan.action=='ESCALATE' and result.plan.escalation_reason=='INSUFFICIENT_KNOWLEDGE'
    assert not result.plan.selected_blocks


@pytest.mark.asyncio
async def test_typed_quantities_cannot_claim_raw_only_arithmetic_limitation(tmp_path):
    from unittest.mock import AsyncMock
    from app.errors import ApiError
    search,raw,kw,_=setup(tmp_path)
    raw['plan']=dict(snapshot_id=raw['plan']['snapshot_id'],knowledge_revision=raw['plan']['knowledge_revision'],
        action='ESCALATE',escalation_reason='unsupported')
    raw.update(unsupported_calculation=True,unresolved=['no operands'])
    with pytest.raises(ApiError):await general_decision(search,provider=AsyncMock(return_value=raw),**kw)
