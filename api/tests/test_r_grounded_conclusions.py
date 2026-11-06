"""Synthetic provenance/coverage tests, never a claim of model semantic accuracy."""
from copy import deepcopy
from dataclasses import replace
import json
from unittest.mock import AsyncMock

import pytest

from app.contracts.answer import SelectedBlock
from app.contracts.hashing import digest
from app.errors import ApiError
from app.learn.answer_validation import AnswerReferenceError, validate_answer_for_question
from app.learn.approved_renderer import render
from app.learn.general_semantics import GeneralProposal, general_decision, validate_interpretation
from app.learn.general_verification import Verification
from app.learn.general_wire import response_schema
from app.learn.grounded_conclusions import CandidateCoverage, atoms, candidate_references, missing_required_evidence
from app.learn.semantic_proposals import proposal_input
from tests.test_r_general_semantics import setup, provider_for


def enabled(tmp_path):
    search, raw, kw, release = setup(tmp_path)
    release['response_style'] = 'grounded_conclusion'
    kw['settings'].r_general_semantics_path.write_text(json.dumps(release), encoding='utf-8')
    kw['settings'].r_general_semantics_hash = digest(release)
    raw['conclusions'] = [dict(statement='아래 승인된 준비 절차를 따르세요.', question_quote=kw['question'],
        user_evidence=[dict(turn_id=0, quote=kw['question'])], references=deepcopy(raw['plan']['selected_blocks']))]
    raw['case_requirements']=dict(scope='NOT_APPLICABLE',rationale='Synthetic general procedure question',cases=[])
    return search, raw, kw


def modified_verifier(search, raw, change):
    base = provider_for(search, raw)
    async def call(prompt, *, schema, **kwargs):
        result = await base(prompt, schema=schema, **kwargs)
        if schema is Verification:change(result)
        return result
    return AsyncMock(side_effect=call)


@pytest.mark.asyncio
async def test_opted_in_conclusions_render_with_citations_and_unchanged_approved_evidence(tmp_path):
    search, raw, kw = enabled(tmp_path)
    decision, audit = await general_decision(search, provider=provider_for(search, raw), **kw)
    response = render(decision.plan, search.snapshot, resolved=decision.resolved, store_id=1, request_id='conclusion-test')
    assert response.message.startswith('현재 질문에 대한 안내\n아래 승인된 준비 절차를 따르세요. [출처 1]')
    assert response.message.endswith(search.snapshot.raw_spans[0].text)
    assert response.citations[0].raw_span_id == raw['plan']['selected_blocks'][0]['raw_span_id']
    assert decision.resolved.conclusions_verified and decision.confirmed_slots == {}
    assert audit['response_style'] == 'grounded_conclusion' and audit['checked_conclusion_ids'] == [0]
    assert len(audit['candidate_coverage']) == len(candidate_references(search))


@pytest.mark.asyncio
async def test_conclusion_mode_requires_explicit_release_and_actual_conclusion(tmp_path):
    search, raw, kw = enabled(tmp_path)
    release = json.loads(kw['settings'].r_general_semantics_path.read_text('utf-8'))
    release.pop('response_style')
    kw['settings'].r_general_semantics_path.write_text(json.dumps(release), encoding='utf-8')
    kw['settings'].r_general_semantics_hash = digest(release)
    provider = provider_for(search, raw)
    with pytest.raises(ApiError, match='해석 결과'):
        await general_decision(search, provider=provider, **kw)
    assert provider.await_count == 1
    search, raw, kw = enabled(tmp_path)
    raw['conclusions'] = []
    with pytest.raises(ApiError) as error:await general_decision(search, provider=provider_for(search, raw), **kw)
    assert error.value.code == 'GENERAL_INVALID_PROPOSAL'


@pytest.mark.parametrize('change', ['invented_quote', 'wrong_turn', 'other_question', 'version', 'unselected', 'blank'])
def test_conclusion_provenance_is_checked_before_verifier(tmp_path, change):
    search, raw, kw = enabled(tmp_path)
    c = raw['conclusions'][0]
    if change == 'invented_quote':c['user_evidence'][0]['quote'] = '확인하지 않은 외부 처리 결과'
    if change == 'wrong_turn':c['user_evidence'][0]['turn_id'] = 1
    if change == 'other_question':c['question_quote'] = '다른 사건'
    if change == 'version':c['references'][0]['card_version_id'] = '999'
    if change == 'unselected':c['references'] = [candidate_references(search)[0].model_dump(mode='json')]
    if change == 'blank':c['statement'] = '   '
    with pytest.raises(ValueError):validate_interpretation(search, payload=proposal_input(search, store_id=1,
        question=kw['question']), proposal=raw, baseline=kw['baseline'])


def test_unverified_conclusion_cannot_render_or_pass_storage_validation(tmp_path):
    search, raw, kw = enabled(tmp_path)
    decision = validate_interpretation(search, payload=proposal_input(search, store_id=1, question=kw['question']),
        proposal=raw, baseline=kw['baseline'])
    assert not decision.resolved.conclusions_verified
    with pytest.raises(AnswerReferenceError, match='UNVERIFIED_CONCLUSION'):
        validate_answer_for_question(decision.plan, search.snapshot, decision.resolved, store_id=1)
    with pytest.raises(AnswerReferenceError, match='UNVERIFIED_CONCLUSION'):
        render(decision.plan, search.snapshot, resolved=decision.resolved, store_id=1, request_id='unverified')
    with pytest.raises(AnswerReferenceError):
        validate_answer_for_question(kw['baseline'].plan, search.snapshot, decision.resolved, store_id=1)


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['missing', 'duplicate', 'wrong'])
async def test_every_conclusion_must_be_verified(tmp_path, change):
    search, raw, kw = enabled(tmp_path)
    ids = {'missing': [], 'duplicate': [0, 0], 'wrong': [1]}[change]
    with pytest.raises(ApiError) as error:
        await general_decision(search, provider=modified_verifier(search, raw,
            lambda v:v.update(checked_conclusion_ids=ids)), **kw)
    assert error.value.code == 'GENERAL_INVALID_PROPOSAL'


@pytest.mark.asyncio
async def test_required_unselected_evidence_overrides_supported_true(tmp_path):
    search, raw, kw = enabled(tmp_path)
    # Same failure shape as the live omitted prerequisite: independently mark
    # all retrieved evidence required even though the proposal selected only RAW.
    def require_all(v):
        for c in v['candidate_coverage']:c.update(required=True, rationale='synthetic independently required prerequisite')
    with pytest.raises(ApiError) as error:
        await general_decision(search, provider=modified_verifier(search, raw, require_all), **kw)
    assert error.value.code == 'GENERAL_VERIFICATION_REJECTED'
    assert error.value.details['reason_code'] == 'INCOMPLETE_ANSWER'


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['omit', 'duplicate', 'forged', 'none_required'])
async def test_incomplete_or_forged_candidate_inspection_cannot_pass(tmp_path, change):
    search, raw, kw = enabled(tmp_path)
    def corrupt(v):
        coverage = v['candidate_coverage']
        if change == 'omit':coverage.pop(0)
        if change == 'duplicate':coverage.append(deepcopy(coverage[0]))
        if change == 'forged':coverage[0]['reference']['card_version_id'] = '999'
        if change == 'none_required':
            for c in coverage:c['required'] = False
    with pytest.raises(ApiError) as error:
        await general_decision(search, provider=modified_verifier(search, raw, corrupt), **kw)
    assert error.value.code == 'GENERAL_INVALID_PROPOSAL'


def test_candidate_inspection_never_expands_to_unretrieved_snapshot_blocks(tmp_path):
    search, raw, kw = enabled(tmp_path)
    plan = GeneralProposal.model_validate(raw).plan
    retrieved = replace(search, candidates=tuple(c for c in search.candidates if c.block_id == plan.selected_blocks[0].block_id))
    assert atoms(candidate_references(retrieved)) == atoms(plan.selected_blocks)
    coverage = tuple(CandidateCoverage(reference=r, required=True, rationale='synthetic') for r in candidate_references(search))
    with pytest.raises(ValueError):missing_required_evidence(retrieved, plan=plan, coverage=coverage)


@pytest.mark.asyncio
async def test_context_conflict_rejection_discards_conclusions(tmp_path):
    search, raw, kw = enabled(tmp_path)
    def reject(v):v.update(supported=False, reason_code='CONTEXT_CONFLICT', reason_detail='다른 사건 상태를 혼합함')
    with pytest.raises(ApiError) as error:
        await general_decision(search, provider=modified_verifier(search, raw, reject), **kw)
    assert error.value.code == 'GENERAL_VERIFICATION_REJECTED'
    assert error.value.details['reason_code'] == 'CONTEXT_CONFLICT'


@pytest.mark.asyncio
async def test_combined_output_length_fails_before_persistence_without_truncating_evidence(tmp_path):
    search, raw, kw = enabled(tmp_path)
    raw['conclusions'][0]['statement'] = '가' * 500
    raw['conclusions'] = [deepcopy(raw['conclusions'][0]) for _ in range(5)]
    with pytest.raises(ApiError) as error:
        await general_decision(search, provider=provider_for(search, raw), **kw)
    assert error.value.code == 'GENERAL_INVALID_PROPOSAL'


def test_wire_schema_only_offers_conclusions_for_opted_in_release():
    old = response_schema(GeneralProposal, conclusions_enabled=False)
    new = response_schema(GeneralProposal, conclusions_enabled=True)
    assert 'conclusions' not in old['properties'] and 'GroundedConclusion' not in old['$defs']
    assert 'conclusions' in new['required']
    verifier = response_schema(Verification)
    assert {'candidate_coverage', 'checked_conclusion_ids'} <= set(verifier['required'])


@pytest.mark.asyncio
@pytest.mark.parametrize('misbound', [False, True])
async def test_old_state_and_current_correction_keep_exact_turn_provenance(tmp_path, misbound):
    search, raw, kw = enabled(tmp_path)
    previous = kw['question']
    q = '아까 준비 절차는 A건이야. B건은 그대로 두고 A만 다시 알려줘.'
    kw.update(question=q, user_turns=(previous,), context_verified=True)
    raw['input_hash'] = proposal_input(search, store_id=1, question=q, user_turns=(previous,))['input_hash']
    raw['conclusions'][0].update(question_quote=q, user_evidence=[
        dict(turn_id=1 if misbound else 0, quote=previous), dict(turn_id=1, quote=q)])
    if misbound:
        with pytest.raises(ApiError) as error:await general_decision(search, provider=provider_for(search, raw), **kw)
        assert error.value.code == 'GENERAL_INVALID_PROPOSAL'
    else:
        decision, _ = await general_decision(search, provider=provider_for(search, raw), **kw)
        assert decision.resolved.conclusion_user_turns == (previous,)
        assert decision.resolved.question == q
        assert [e.turn_id for e in decision.resolved.conclusions[0].user_evidence] == [0, 1]
