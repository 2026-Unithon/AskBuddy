"""Synthetic routing regressions; these do not score Gemini's semantic accuracy."""
from dataclasses import replace
import json
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.contracts.answer import AnswerPlan
from app.contracts.hashing import digest, snapshot_digest
from app.errors import ApiError
from app.learn.general_semantics import GeneralProposal, general_decision
from app.learn.general_verification import Verification
from app.learn.general_wire import response_schema
from app.learn.semantic_proposals import proposal_input
from tests.test_r_general_semantics import setup, provider_for


def rejecting_provider(search, raw, **changes):
    accepted = provider_for(search, raw)
    async def call(prompt, *, schema, **kwargs):
        result = await accepted(prompt, schema=schema, **kwargs)
        if schema is not GeneralProposal:
            result.update(supported=False, reason_code='UNVERIFIABLE', reason_detail='synthetic uncertainty')
            result.update(changes)
        return result
    return AsyncMock(side_effect=call)


@pytest.mark.asyncio
@pytest.mark.parametrize('reason', ['CONTEXT_CONFLICT', 'INCOMPLETE_ANSWER', 'UNVERIFIABLE', None])
async def test_rejected_answer_never_reverts_to_broad_entity_choice(tmp_path, reason, caplog):
    search, raw, kw, _ = setup(tmp_path)
    kw['baseline'] = replace(kw['baseline'], plan=AnswerPlan(
        snapshot_id=search.snapshot.snapshot_id, knowledge_revision=search.snapshot.knowledge_revision,
        action='CLARIFY', clarification_slot='entity', allowed_options=('환불', '오픈', '마감'), context_id=uuid4()))
    provider = rejecting_provider(search, raw, reason_code=reason, reason_detail='diagnostic private text')
    with pytest.raises(ApiError) as error:
        await general_decision(search, provider=provider, **kw)
    assert error.value.code == 'GENERAL_VERIFICATION_REJECTED'
    assert error.value.retryable
    assert error.value.details['reason_code'] == (reason or 'UNVERIFIABLE')
    assert 'diagnostic private text' not in str(error.value.details)
    assert provider.await_count == 2  # No retry or third model call.
    assert caplog.records[-1].general_verification['reason_code'] == (reason or 'UNVERIFIABLE')
    assert 'reason_detail' not in caplog.records[-1].general_verification


@pytest.mark.asyncio
@pytest.mark.parametrize('reason,expected', [
    ('MISSING_KNOWLEDGE', 'INSUFFICIENT_KNOWLEDGE'),
    ('UNSUPPORTED_OPERATION', 'INSUFFICIENT_KNOWLEDGE'),
    ('MISSING_USER_INFO', 'UNRESOLVED_CONTEXT')])
async def test_known_missing_information_routes_to_owner_with_audit_not_arbitrary_choices(tmp_path, reason, expected):
    search, raw, kw, _ = setup(tmp_path)
    result, audit = await general_decision(search, provider=rejecting_provider(search, raw,
        reason_code=reason, reason_detail='결제 금액 정보가 없음'), **kw)
    assert result.plan.action == 'ESCALATE' and result.plan.escalation_reason == expected
    assert not result.plan.selected_blocks and not result.resolved.calculations
    assert result.semantic_context is None
    assert result.confirmed_slots == kw['baseline'].confirmed_slots
    assert audit['reason_code'] == reason and audit['reason_detail'] == '결제 금액 정보가 없음'
    assert audit['fallback_action'] == 'ESCALATE'


def variant_setup(tmp_path):
    from tests.test_r_planner import PlannerTest
    from app.learn.planner import decide
    _, _, kw, release = setup(tmp_path)
    search = PlannerTest().search()
    snap = search.snapshot
    fact = snap.fact_revisions[0]
    second = fact.model_copy(update={'fact_revision_id': '2', 'fact_id': '2',
                                   'variant': fact.variant.model_copy(update={'temperature': 'ICE'})})
    card = snap.cards[0]
    card = card.model_copy(update={'blocks': (card.blocks[0].model_copy(update={'fact_revision_ids': ('1', '2')}),)})
    snap = snap.model_copy(update={'cards': (card,), 'fact_revisions': (fact, second)})
    search = replace(search, snapshot=snap.model_copy(update={'snapshot_hash': snapshot_digest(snap)}))
    q = '이 음료의 우유 양이 궁금해요'
    payload = proposal_input(search, store_id=1, question=q)
    raw = dict(snapshot_hash=payload['snapshot_hash'], input_hash=payload['input_hash'],
        plan=dict(snapshot_id='1', knowledge_revision='1', action='ANSWER', selected_blocks=[
            dict(card_id='1', card_version_id='1', block_id='b', fact_revision_ids=['1'])]),
        interpretation=dict(entity_id='1', predicate='milk_amount', variants=[['HOT', None]], target_fact_ids=['1']),
        slots=[dict(slot=k, value=v, question_quote=q) for k, v in
               [('entity', '1'), ('predicate', 'milk_amount'), ('temperature', 'HOT')]])
    release['snapshot_hash'] = payload['snapshot_hash']
    kw['settings'].r_general_semantics_path.write_text(json.dumps(release), encoding='utf-8')
    kw['settings'].r_general_semantics_hash = digest(release)
    kw.update(question=q, baseline=decide(search, store_id=1, question=q), confirmed_slots={})
    return search, raw, kw


@pytest.mark.asyncio
async def test_missing_temperature_asks_only_temperature_keeps_server_context_and_does_not_confirm_guesses(tmp_path):
    search, raw, kw = variant_setup(tmp_path)
    runtime_id = uuid4()
    result, audit = await general_decision(search, context_id=runtime_id, context_verified=True,
        provider=rejecting_provider(search, raw, reason_code='MISSING_USER_INFO',
            reason_detail='HOT 또는 ICE 선택이 없음', clarification=dict(slot='temperature',
                allowed_options=['HOT', 'ICE'], scope_supported=True)), **kw)
    assert result.plan.action == 'CLARIFY' and result.plan.clarification_slot == 'temperature'
    assert result.plan.allowed_options == ('HOT', 'ICE') and result.plan.context_id == runtime_id
    assert result.resolved.entity_id == '1' and result.confirmed_slots == {}
    assert not result.plan.selected_blocks and result.resolved.assessment is None
    assert audit['fallback_action'] == 'CLARIFY'


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['invented', 'duplicate', 'incomplete', 'confirmed', 'unverified_scope', 'broad_entity'])
async def test_verifier_cannot_invent_choices_or_overwrite_confirmed_context(tmp_path, change):
    search, raw, kw = variant_setup(tmp_path)
    clarify = dict(slot='temperature', allowed_options=['HOT', 'ICE'], scope_supported=True)
    if change == 'invented': clarify['allowed_options'] = ['HOT', 'OTHER']
    if change == 'duplicate': clarify['allowed_options'] = ['HOT', 'HOT']
    if change == 'incomplete': clarify['allowed_options'] = ['HOT']
    if change == 'confirmed': kw['confirmed_slots'] = {'temperature': 'HOT'}
    if change == 'unverified_scope': clarify['scope_supported'] = False
    if change == 'broad_entity': clarify.update(slot='entity', allowed_options=['환불', '오픈'])
    with pytest.raises(ApiError) as error:
        await general_decision(search, provider=rejecting_provider(search, raw,
            reason_code='MISSING_USER_INFO', clarification=clarify), **kw)
    assert error.value.code == 'GENERAL_INVALID_PROPOSAL'


@pytest.mark.asyncio
async def test_targeted_clarification_still_has_two_turn_limit(tmp_path):
    search, raw, kw = variant_setup(tmp_path)
    result, _ = await general_decision(search, clarify_turns=2,
        provider=rejecting_provider(search, raw, reason_code='MISSING_USER_INFO',
            clarification=dict(slot='temperature', allowed_options=['HOT', 'ICE'], scope_supported=True)), **kw)
    assert result.plan.action == 'ESCALATE' and result.plan.escalation_reason == 'UNRESOLVED_CONTEXT'


@pytest.mark.parametrize('change', ['supported_reason', 'supported_unresolved', 'no_explanation', 'wrong_clarification'])
def test_verdict_contradictions_are_invalid(change):
    raw = dict(request_hash='sha256:'+'0'*64, supported=False, unresolved=[], checked_fact_ids=[], checked_raw_blocks=[])
    if change == 'supported_reason': raw.update(supported=True, reason_code='CONTEXT_CONFLICT', reason_detail='bad')
    if change == 'supported_unresolved': raw.update(supported=True, unresolved=['missing'])
    if change == 'no_explanation': raw.update(reason_code='MISSING_KNOWLEDGE')
    if change == 'wrong_clarification': raw.update(reason_code='UNVERIFIABLE', reason_detail='unknown',
        clarification=dict(slot='entity', allowed_options=['A', 'B'], scope_supported=True))
    with pytest.raises(ValueError): Verification.model_validate(raw)


def test_model_schema_requires_diagnostics_and_user_turn_coverage():
    schema = response_schema(Verification)
    assert {'reason_code', 'reason_detail', 'clarification', 'checked_user_turn_ids'} <= set(schema['required'])


# Authored dialogue cases exercise provenance/transport/rejection, not whether
# a synthetic responder can understand the words (it is supplied the verdict).
CONTEXT_CASES = [
    (['오늘 직접 결제한 18,000원 건이고 영수증 있어. POS 마감 전이야.'],
     '아, 어제 배달앱 결제였어. 금액은 같아.'),
    (['A 주문은 18,000원 직접 결제, B 주문은 25,000원 배달앱 결제야.'],
     'A 주문만 어제 결제한 걸로 정정할게. B는 그대로야.'),
    (['18,000원 환불을 물어봤어.'], '다른 질문이야. 내일 오픈 담당자가 없으면 어떻게 해?'),
    (['A 주문과 B 주문 둘 다 환불하려고 해.'], '그건 어제 결제했어.'),
]


@pytest.mark.asyncio
@pytest.mark.parametrize('turns,current', CONTEXT_CASES)
async def test_correction_and_topic_change_keep_ordered_user_evidence_for_both_calls(tmp_path, turns, current):
    search, raw, kw, _ = setup(tmp_path)
    # Bind structurally valid proposal to the authored dialogue, without treating
    # it as a semantic gold answer for this fixture's unrelated approved material.
    kw.update(question=current, user_turns=tuple(turns), context_verified=True, confirmed_slots={})
    payload = proposal_input(search, store_id=1, question=current, user_turns=tuple(turns))
    raw['input_hash'] = payload['input_hash']
    for slot in raw['slots']: slot['question_quote'] = turns[0]
    provider = rejecting_provider(search, raw, reason_code='CONTEXT_CONFLICT',
                                  reason_detail='synthetic stale-condition rejection')
    with pytest.raises(ApiError) as error:
        await general_decision(search, provider=provider, **kw)
    assert error.value.code == 'GENERAL_VERIFICATION_REJECTED'
    for call in provider.call_args_list:
        request = json.loads(call.args[0].rsplit('\n', 1)[1])
        assert request['dialogue_turns'] == [
            dict(turn_id=i, role='user', current=i == len(turns), text=text)
            for i, text in enumerate([*turns, current])]
        assert request['confirmed_slots'] == {}
    assert len(provider.call_args_list) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize('ids', [[], [0], [1, 0], [0, 0], [0, 1, 2], [False, 1]])
async def test_verifier_omitting_current_correction_or_forging_turn_coverage_is_invalid(tmp_path, ids):
    search, raw, kw, _ = setup(tmp_path)
    kw.update(user_turns=(kw['question'],), context_verified=True)
    raw['input_hash'] = proposal_input(search, store_id=1, question=kw['question'], user_turns=kw['user_turns'])['input_hash']
    with pytest.raises(ApiError) as error:
        await general_decision(search, provider=rejecting_provider(search, raw, checked_user_turn_ids=ids), **kw)
    assert error.value.code == 'GENERAL_INVALID_PROPOSAL'
