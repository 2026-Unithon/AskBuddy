"""General interpretation under an explicitly accepted deployment policy, default OFF.

Model agreement and server structure checks are NOT human semantic truth. This
path requires a version-bound acceptance artifact before any runtime provider call.
"""
import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Literal
from uuid import uuid4
from pydantic import Field, StrictBool, model_validator
from app.contracts.common import Contract, EntityId
from app.contracts.hashing import digest

logger=logging.getLogger(__name__)
from app.contracts.usage import UsageContext
from app.contracts.validate import validate_answer_references
from app.errors import ApiError
from app.learn.answer_validation import FactSuitability, SuitabilityAssessment, ResolvedSelection, ResolvedPart, question_hash, validate_answer_for_question
from app.contracts.answer import AnswerPlan
from app.contracts.chat import ChatResponse
from app.learn.grounded_calculations import Calculation, calculate
from app.learn.planner import Decision, policy_action, PREDICATES
from app.learn.semantic_proposals import SemanticProposal, SlotProposal, proposal_input, validate_proposal
from app.learn.general_wire import parse_proposal
from app.learn.general_verification import Verification, rejection_decision
from app.learn.case_clarification import CaseOption, validate_case_options
from app.learn.grounded_conclusions import GroundedConclusion, validate_conclusions, candidate_references, missing_required_evidence,selected_rules,missing_conclusion_rules,missing_case_actions,reference_scopes,conclusion_units,unsupported_situations
from dataclasses import replace
from app.team.evaluation_budget import BudgetDenied
from app.usage.repository import UsageWriteError
from app.learn.grounded_conclusions import CaseRequirements, case_requirement_keys
from app.learn.entity_names import entity_names

VERSION='r-general-semantics/v12'
SOURCES=('learn/general_semantics.py','learn/general_provider.py','learn/answer_validation.py',
    'learn/semantic_proposals.py','learn/planner.py','contracts/validate.py','learn/v2_router.py',
    'learn/answer_storage.py','learn/approved_renderer.py','learn/question_contexts.py','team/evaluation_budget.py',
    'learn/clarification_scope.py','learn/entity_names.py','learn/reviewed_grouping.py','learn/reviewed_semantics.py',
    'learn/dialogue_history.py','learn/grounded_calculations.py','learn/general_wire.py',
    'learn/general_verification.py','learn/case_clarification.py','learn/grounded_conclusions.py','learn/failed_user_turns.py',
    '../prompts/r_general_proposal.txt','../prompts/r_general_verification.txt')


def source_hash():
    root=Path(__file__).resolve().parents[1]
    return digest({p:(root/p).read_text(encoding='utf-8') for p in SOURCES})


class Release(Contract):
    schema_version: Literal['r-general-release/v1']='r-general-release/v1'
    store_id: EntityId
    snapshot_hash: str = Field(pattern=r'^sha256:[0-9a-f]{64}$')
    source_hash: str = Field(pattern=r'^sha256:[0-9a-f]{64}$')
    model: str = Field(min_length=1,max_length=100)
    acceptance_reference: str = Field(min_length=1,max_length=500)
    approved_by: str = Field(min_length=1,max_length=100)
    valid_until: datetime
    max_input_tokens: int = Field(strict=True,gt=0,le=100000)
    max_output_tokens: int = Field(strict=True,gt=0,le=10000)
    max_prompt_bytes: int = Field(strict=True,gt=0,le=200000)
    thinking_level: Literal['minimal','low','medium','high']='low'
    response_style: Literal['approved_original','grounded_conclusion']='approved_original'


class Interpretation(Contract):
    entity_id: str = Field(min_length=1,max_length=100,description='Exact candidates.entity_id, never the displayed title. slots.entity.value must equal this ID.')
    predicate: str = Field(min_length=1,max_length=100,description='Selected typed fact predicate; RAW-only uses approved_procedure. slots.predicate.value must match.')
    variants: tuple[tuple[str|None,str|None],...] = Field(max_length=10,description='Pairs of [temperature, size], never [entity, predicate]. RAW-only uses []; do not invent variants.')
    target_fact_ids: tuple[EntityId,...] = Field(max_length=100)
    # 규격이 비어 있는 사실을 서버가 NOT_APPLICABLE 로 판정하는 것은 snapshot 만 보면
    # 되는 계산이라 서버가 직접 한다(아래 assessment 구성). 모델에게 같은 값을 복사시키던
    # not_applicable_fact_ids 는 2026-10-15 유료 진단에서 "질문에 해당 없는 사실" 로
    # 오해돼 정답 선택을 두 번 다 버렸다. 모델에게는 **모델만 답할 수 있는 것**만 묻는다 —
    # 규격이 비어 있어 이 질문에 적용해도 되는지 판단할 수 없는 사실이 있는가.
    variant_unverifiable_fact_ids: tuple[EntityId,...] = Field(default=(),max_length=100,
        description='Selected facts whose empty [temperature,size] you CANNOT justify applying to this question. Leave empty when the approved wording makes the fact variant-independent. Any id here blocks the answer; prefer unresolved/CLARIFY when the whole question is unclear.')

    # 2026-10-15 은퇴한 칸. 보존한 과거 모델 출력(tests/fixtures/*_live_*.json)이 이 키를
    # 달고 있다. 기록을 고쳐 쓰지 않으려고 **읽을 때 떨군다.** 값은 쓰지 않는다 —
    # 규격 무관 판정은 서버가 snapshot 으로 계산한다.
    @model_validator(mode='before')
    @classmethod
    def drop_retired_not_applicable(cls,data):
        if isinstance(data,dict) and 'not_applicable_fact_ids' in data:
            data={k:v for k,v in data.items() if k!='not_applicable_fact_ids'}
        return data


class Obligation(Contract):
    fact_revision_id: EntityId
    kind: Literal['condition','exception']
    statement: str = Field(min_length=1,max_length=1000)
    question_quote: str = Field(min_length=1,max_length=1000)


class AnswerPart(Contract):
    plan: AnswerPlan = Field(description='One knowledge entity scope only: RAW selected blocks must belong to interpretation.entity_id. Use input capabilities.reference_scopes. Never group different knowledge entities into a part just because they concern the same user case. Parent plan unions scopes; conclusions may combine their references.')
    interpretation: Interpretation = Field(description='Knowledge entity/predicate/variant scope, not user case A/B. Separate distinct entities into distinct parts even when one case needs all of them.')
    slots: tuple[SlotProposal,...] = Field(default=(),max_length=20)
    obligations: tuple[Obligation,...] = Field(default=(),max_length=100)


class GeneralProposal(SemanticProposal):
    case_requirements: CaseRequirements | None = Field(default=None,
        description='For grounded ANSWER, first enumerate the cases and latest user states required by the QUESTION, independently of what the draft answers. Named-state handoff questions require CASE_ACTIONS even if they also ask common fields. General forms or unrelated topics use reasoned NOT_APPLICABLE. Other actions/original mode: null.')
    interpretation: Interpretation | None = None
    obligations: tuple[Obligation,...] = Field(default=(),max_length=100)
    parts: tuple[AnswerPart,...] = Field(default=(),max_length=8,description='Empty for top-level interpretation, or 1..8 independently grounded parts with top-level interpretation=null and slots/obligations=[]. One part is validated identically to a single answer; the parent selected references must equal the union of its parts.')
    calculations: tuple[Calculation,...] = Field(default=(),max_length=8)
    unsupported_calculation: StrictBool = False
    case_options: tuple[CaseOption,...] = Field(default=(),max_length=10)
    conclusions: tuple[GroundedConclusion,...] = Field(default=(),max_length=8,
        description='User-facing case/question applications. Each conclusion may cite references from multiple independently validated parts. Parts and conclusions need not have matching counts or indices.')


def load_release(settings,search,store_id):
    with Path(settings.r_general_semantics_path).open('rb') as stream:
        data=stream.read(16001)
    if len(data)>16000:raise ValueError('release too large')
    raw=json.loads(data)
    if digest(raw)!=settings.r_general_semantics_hash:raise ValueError('release pin mismatch')
    release=Release.model_validate(raw)
    if (release.store_id!=str(store_id) or release.snapshot_hash!=search.snapshot.snapshot_hash
            or release.source_hash!=source_hash() or release.model!=settings.gemini_model
            or release.valid_until.tzinfo is None or datetime.now(timezone.utc)>=release.valid_until
            or not release.acceptance_reference.strip() or not release.approved_by.strip()):
        raise ValueError('release scope/version/model/expiry mismatch')
    return release


def validate_interpretation(search,*,payload,proposal,baseline,context_id=None,clarify_turns=0,confirmed_slots=None):
    proposal=parse_proposal(proposal)
    decision=_validate_interpretation(search,payload=payload,proposal=proposal,baseline=baseline,
        context_id=context_id,clarify_turns=clarify_turns,confirmed_slots=confirmed_slots)
    if proposal.conclusions:
        if decision is baseline or proposal.unresolved:raise ValueError('unresolved proposal cannot carry conclusions')
        validate_conclusions(proposal.conclusions,plan=decision.plan,question=payload['question'],user_turns=tuple(payload['user_turns']))
        decision=replace(decision,resolved=replace(decision.resolved,conclusions=proposal.conclusions,
            conclusion_user_turns=tuple(payload['user_turns'])))
    return decision


def _validate_interpretation(search,*,payload,proposal,baseline,context_id=None,clarify_turns=0,confirmed_slots=None):
    proposal=parse_proposal(proposal)
    # Explicitly supplied slots come from accepted server context, not from the
    # planner's guesses while processing the current question.
    trusted_slots=dict(baseline.confirmed_slots if confirmed_slots is None else confirmed_slots)
    base=SemanticProposal.model_validate(proposal.model_dump(exclude={'interpretation','obligations','parts','calculations','unsupported_calculation','case_options','conclusions','case_requirements'}))
    validate_proposal(base,search,payload)
    if proposal.equivalent_question_ids:raise ValueError('model cannot merge questions')
    if proposal.plan.action=='CLARIFY' and proposal.plan.clarification_slot=='case':
        if proposal.parts or proposal.interpretation or proposal.calculations or proposal.unsupported_calculation or proposal.unresolved:
            raise ValueError('case clarification cannot carry answer interpretation')
        validate_case_options(proposal.case_options,allowed_options=proposal.plan.allowed_options,
            question=payload['question'],user_turns=tuple(payload['user_turns']),confirmed_slots=trusted_slots)
        plan=proposal.plan.model_copy(update={'context_id':context_id or uuid4()})
        if clarify_turns>=2:
            plan=AnswerPlan(snapshot_id=plan.snapshot_id,knowledge_revision=plan.knowledge_revision,
                action='ESCALATE',escalation_reason='UNRESOLVED_CONTEXT')
        return Decision(plan,ResolvedSelection('','',(),payload['question'],
            case_options=proposal.case_options,case_user_turns=tuple(payload['user_turns'])),trusted_slots,None)
    if proposal.case_options:raise ValueError('case options require case clarification')
    if proposal.unsupported_calculation:
        from app.learn.grounded_calculations import UNITS
        if (proposal.plan.action!='ESCALATE' or not proposal.unresolved or proposal.calculations or proposal.parts
                or any(f.quantity and f.polarity=='AFFIRM' and f.quantity.unit.lower() in UNITS
                    for c in search.candidates for b in search.snapshot.card(c.card_id).blocks if b.block_id==c.block_id
                    for fid in b.fact_revision_ids for f in (search.snapshot.fact(fid),))):
            raise ValueError('unsupported calculation requires escalation without eligible retrieved quantities')
        # Keep the public reason and pending workflow server-owned; never expose
        # model-authored implementation details to the employee.
        return Decision(proposal.plan.model_copy(update={'escalation_reason':'INSUFFICIENT_KNOWLEDGE'}),
            baseline.resolved,trusted_slots,None)
    if proposal.unresolved or proposal.plan.action=='ESCALATE':
        return baseline
    if proposal.plan.action not in ('ANSWER','CLARIFY'):raise ValueError('server owns policy actions')
    plan=proposal.plan
    if proposal.calculations and plan.action != 'ANSWER':raise ValueError('only answers may calculate')
    if proposal.parts:
        if (plan.action != 'ANSWER' or proposal.interpretation is not None
                or proposal.slots or proposal.obligations):
            raise ValueError('multipart answers require disjoint interpretation fields')
        parts=[]
        for part in proposal.parts:
            if part.plan.action != 'ANSWER':raise ValueError('all parts must be answerable')
            child=GeneralProposal(snapshot_hash=proposal.snapshot_hash,input_hash=proposal.input_hash,
                plan=part.plan,interpretation=part.interpretation,slots=part.slots,obligations=part.obligations)
            result=validate_interpretation(search,payload=payload,proposal=child,baseline=baseline,confirmed_slots=trusted_slots)
            parts.append(ResolvedPart(result.plan,result.resolved))
        if len(parts)==1:
            from app.learn.answer_validation import reference_atoms
            if reference_atoms(plan)!=reference_atoms(parts[0].plan):raise ValueError('single part reference union mismatch')
            resolved=replace(parts[0].resolved,calculations=proposal.calculations,
                calculation_user_turns=tuple(payload['user_turns']))
            validate_answer_for_question(plan,search.snapshot,resolved,store_id=int(payload['store_id']))
            return Decision(plan,resolved,trusted_slots,None)
        resolved=ResolvedSelection('','',(),payload['question'],parts=tuple(parts),
            calculations=proposal.calculations,calculation_user_turns=tuple(payload['user_turns']))
        validate_answer_for_question(plan,search.snapshot,resolved,store_id=int(payload['store_id']))
        return Decision(plan,resolved,trusted_slots,None)
    if plan.action == 'CLARIFY' and plan.clarification_slot == 'entity':
        if clarify_turns >= 2:return baseline
        if proposal.interpretation is not None:raise ValueError('entity is not resolved yet')
        from app.learn.clarification_scope import validate_options
        validate_options(search, plan=plan, slots=trusted_slots)
        return Decision(plan.model_copy(update={'context_id':context_id or uuid4()}),
            baseline.resolved,trusted_slots,None)
    query=proposal.interpretation
    if query is None:raise ValueError('interpretation required')
    snap=search.snapshot
    if any(b.raw_span_id and snap.card(b.card_id).entity_id!=query.entity_id for b in plan.selected_blocks):
        raise ValueError('RAW reference crosses interpretation entity scope; separate knowledge scopes into parts')
    cards=[snap.card(c.card_id) for c in search.candidates if snap.card(c.card_id).entity_id==query.entity_id]
    if not cards:raise ValueError('entity outside candidates')
    # Check prior server/user-confirmed context; model slots never become confirmed slots.
    slots=trusted_slots
    if slots.get('entity') and slots['entity'] not in entity_names(snap,query.entity_id):raise ValueError('entity contradicts context')
    if slots.get('predicate') and slots['predicate'] not in (query.predicate,PREDICATES.get(query.predicate,(query.predicate,()))[0]):
        raise ValueError('predicate contradicts context')
    for key,position in (('temperature',0),('size',1)):
        if slots.get(key) and any(v[position]!=slots[key] for v in query.variants):raise ValueError('variant contradicts context')
    # A quote is traceability, not proof of semantic equivalence. Acceptance is evaluated separately.
    evidence={(s.slot,s.value) for s in proposal.slots}
    if not {('entity',query.entity_id),('predicate',query.predicate)}.issubset(evidence):
        raise ValueError('missing interpretation evidence')
    if plan.action=='CLARIFY':
        if clarify_turns>=2:return baseline
        attr=plan.clarification_slot
        if attr not in ('temperature','size') or slots.get(attr):raise ValueError('unsupported or already confirmed clarification')
        from app.learn.clarification_scope import validate_options
        validate_options(search,plan=plan,slots=slots,entity_id=query.entity_id,predicate=query.predicate)
        plan=plan.model_copy(update={'context_id':context_id or uuid4()})
        return Decision(plan,baseline.resolved,dict(slots),None)
    refs=validate_answer_references(plan,snap,store_id=payload['store_id'])
    facts=[snap.fact(fid) for fid in refs.fact_ids]
    null_variants={f.fact_revision_id for f in facts if (f.variant.temperature,f.variant.size)==(None,None)}
    unverifiable=query.variant_unverifiable_fact_ids
    if len(unverifiable)!=len(set(unverifiable)) or not set(unverifiable)<=null_variants:
        # 고르지 않은 사실이나 규격이 있는 사실을 "판단 불가" 로 적을 수 없다
        raise ValueError('variant applicability claim outside the selected null-variant facts')
    if unverifiable:
        # 모델이 적용성을 못 세운 사실로는 답하지 않는다. 추정으로 메우지 않는다
        raise ValueError('variant applicability unverified for a selected fact')
    expected={(f.fact_revision_id,kind,statement) for f in facts
        for kind,statements in (('condition',f.conditions),('exception',f.exceptions)) for statement in statements}
    supplied=[(o.fact_revision_id,o.kind,o.statement) for o in proposal.obligations]
    if set(supplied)!=expected or len(supplied)!=len(set(supplied)):
        raise ValueError('condition/exception omitted or invented')
    if any(not any(o.question_quote in turn for turn in (payload['question'],*payload['user_turns'])) for o in proposal.obligations):
        raise ValueError('condition/exception lacks user evidence')
    for temperature,size in query.variants:
        for key,value in (('temperature',temperature),('size',size)):
            if value is not None and slots.get(key)!=value and (key,value) not in evidence:
                raise ValueError('variant lacks user evidence')
    # Copy conditions/RAW identities from the approved snapshot, never the model's assessment.
    assessment=SuitabilityAssessment(store_id=payload['store_id'],snapshot_id=snap.snapshot_id,
        knowledge_revision=snap.knowledge_revision,snapshot_hash=snap.snapshot_hash,question_hash=question_hash(payload['question']),
        entity_id=query.entity_id,predicate=query.predicate,variants=query.variants,target_fact_ids=query.target_fact_ids,
        facts=tuple(FactSuitability(f.fact_revision_id,'NOT_APPLICABLE' if (f.variant.temperature,f.variant.size)==(None,None) else 'SPECIFIC',f.conditions,f.exceptions) for f in facts),
        raw_blocks=refs.raw_blocks)
    resolved=ResolvedSelection(query.entity_id,query.predicate,query.variants,payload['question'],assessment,
        calculations=proposal.calculations,calculation_user_turns=tuple(payload['user_turns']))
    validate_answer_for_question(plan,snap,resolved,store_id=int(payload['store_id']))
    return Decision(plan,resolved,dict(slots),None)


async def general_decision(search,*,settings,store_id,question,user_turns,baseline,context,sink,
                           timeout,context_verified=False,context_id=None,clarify_turns=0,provider=None,confirmed_slots=None):
    if (not getattr(settings,'r_general_semantics_enabled',False)
            or baseline.plan.action not in ('ESCALATE','CLARIFY') or policy_action(question)):
        return baseline,None
    if (user_turns or context_id is not None) and not context_verified:return baseline,None
    try:
        release=load_release(settings,search,store_id)
    except (ValueError,OSError,AttributeError) as exc:
        raise ApiError(503,'GENERAL_RELEASE_UNAVAILABLE','의미 해석의 검증 설정을 확인하지 못했습니다.',retryable=False) from exc
    if not search.candidates:return baseline,None
    if timeout<=0:raise ApiError(504,'GENERAL_DEADLINE','의미 해석 시간이 부족합니다.',retryable=True)
    from app.learn.general_provider import generate
    provider=provider or generate
    context=UsageContext.model_validate(context.model_dump())
    if context.store_id!=str(store_id) or context.stage!='ANSWER':raise ValueError('trusted ANSWER context required')
    trusted_slots=dict(baseline.confirmed_slots if confirmed_slots is None else confirmed_slots)
    try:
        async with asyncio.timeout(min(timeout,3.0)):
            payload=proposal_input(search,store_id=store_id,question=question,user_turns=user_turns)
            from app.learn.grounded_calculations import UNITS
            quantity_ids=tuple(dict.fromkeys(f['fact_revision_id'] for c in payload['candidates'] for f in c['facts']
                if f.get('quantity') and f.get('polarity')=='AFFIRM' and f['quantity']['unit'].lower() in UNITS))
            quotes=tuple(dict.fromkeys((question,*user_turns)))
            dialogue_turns=[dict(turn_id=i,role='user',current=i==len(user_turns),text=text)
                for i,text in enumerate((*user_turns,question))]
            prompt=((Path(__file__).resolve().parents[2]/'prompts/r_general_proposal.txt').read_text(encoding='utf-8').strip()+'\n'
                +json.dumps(dict(input=payload,confirmed_slots=trusted_slots,dialogue_turns=dialogue_turns,
                    capabilities=dict(calculation_fact_ids=quantity_ids,slot_quote_choices=quotes,response_style=release.response_style,
                        reference_scopes=reference_scopes(search),
                        max_answer_chars=ChatResponse.model_json_schema()['properties']['message']['maxLength'])),ensure_ascii=False))
            proposal_started=perf_counter()
            proposal=parse_proposal(await provider(prompt,schema=GeneralProposal,release=release,
                calculation_fact_ids=quantity_ids,question_quotes=quotes,
                context=context.model_copy(update={'logical_call_id':'general:'+digest(dict(call=context.logical_call_id,phase='proposal'))[7:]}),sink=sink))
            decision=validate_interpretation(search,payload=payload,proposal=proposal,baseline=baseline,
                context_id=context_id,clarify_turns=clarify_turns,confirmed_slots=trusted_slots)
            if release.response_style=='approved_original' and proposal.conclusions:
                raise ValueError('conclusions not enabled by accepted release')
            if release.response_style=='grounded_conclusion' and decision.plan.action=='ANSWER' and not proposal.conclusions:
                raise ValueError('situation-specific conclusions required by release')
            if release.response_style=='grounded_conclusion' and decision.plan.action=='ANSWER':
                case_requirement_keys(proposal.case_requirements,question=question,user_turns=user_turns,
                    selected_case=trusted_slots.get('case'))
            audit=dict(version=VERSION,response_style=release.response_style,release_hash=settings.r_general_semantics_hash,input_hash=payload['input_hash'],
                proposal_hash=digest(proposal.model_dump(mode='json')),proposal_ms=round((perf_counter()-proposal_started)*1000,3))
            if proposal.unsupported_calculation:
                return decision,dict(audit,status='UNSUPPORTED_CALCULATION_ESCALATED')
            if decision is baseline:return baseline,dict(audit,status='UNRESOLVED')
            refs=validate_answer_references(decision.plan,search.snapshot,store_id=str(store_id))
            rules=selected_rules(decision.plan,search.snapshot) if proposal.conclusions else []
            review=dict(input=payload,confirmed_slots=trusted_slots,dialogue_turns=dialogue_turns,proposal=proposal.model_dump(mode='json'),
                selected_reference_check=dict(checked_fact_ids=list(refs.fact_ids),checked_raw_blocks=[list(r) for r in refs.raw_blocks]),
                selected_rules=rules,
                conclusion_units=conclusion_units(proposal.conclusions),
                reference_scopes=reference_scopes(search),
                candidate_reference_units=[b.model_dump(mode='json') for b in candidate_references(search)],
                response_style=release.response_style,
                calculated_lines=calculate(decision.resolved.calculations,plan=decision.plan,snapshot=search.snapshot,
                    store_id=store_id,question=question,user_turns=user_turns))
            review['request_hash']=digest(review)
            verification_started=perf_counter()
            verdict=Verification.model_validate(await provider(
                (Path(__file__).resolve().parents[2]/'prompts/r_general_verification.txt').read_text(encoding='utf-8').strip()
                +'\n'+json.dumps(review,ensure_ascii=False),
                schema=Verification,release=release,context=context.model_copy(update={
                    'logical_call_id':'general:'+digest(dict(call=context.logical_call_id,phase='verify'))[7:]}),sink=sink))
            if (verdict.request_hash!=review['request_hash'] or set(verdict.checked_fact_ids)!=set(refs.fact_ids)
                    or len(verdict.checked_fact_ids)!=len(set(verdict.checked_fact_ids))
                    or set(verdict.checked_raw_blocks)!=set(refs.raw_blocks)
                    or len(verdict.checked_raw_blocks)!=len(set(verdict.checked_raw_blocks))):
                raise ValueError('verifier binding/coverage mismatch')
            if verdict.checked_user_turn_ids!=tuple(range(len(dialogue_turns))):
                raise ValueError('verifier user-turn coverage mismatch')
            audit=dict(audit,verification_hash=digest(verdict.model_dump(mode='json')),
                verification_ms=round((perf_counter()-verification_started)*1000,3))
            if not verdict.supported:
                return rejection_decision(search,verdict=verdict,proposal=proposal,question=question,
                    trusted_slots=trusted_slots,user_turns=user_turns,context_id=context_id,clarify_turns=clarify_turns,audit=audit)
            if verdict.checked_conclusion_ids!=tuple(range(len(proposal.conclusions))):
                raise ValueError('conclusion verification coverage mismatch')
            if decision.plan.action=='ANSWER':
                missing=missing_required_evidence(search,plan=decision.plan,coverage=verdict.candidate_coverage)
                if missing:
                    rejected=verdict.model_copy(update=dict(supported=False,reason_code='INCOMPLETE_ANSWER',
                        reason_detail='Verifier-required evidence omitted from selected answer.'))
                    return rejection_decision(search,verdict=rejected,proposal=proposal,question=question,
                        trusted_slots=trusted_slots,user_turns=user_turns,context_id=context_id,clarify_turns=clarify_turns,
                        audit=dict(audit,missing_reference_units=sorted(missing)))
            if proposal.conclusions:
                unsupported=unsupported_situations(verdict.situation_review,proposal.conclusions,
                    question=question,user_turns=user_turns)
                if unsupported:
                    rejected=verdict.model_copy(update=dict(supported=False,reason_code='CONTEXT_CONFLICT',
                        reason_detail='Conclusion asserts case conditions unsupported by user evidence.'))
                    return rejection_decision(search,verdict=rejected,proposal=proposal,question=question,
                        trusted_slots=trusted_slots,user_turns=user_turns,context_id=context_id,clarify_turns=clarify_turns,
                        audit=dict(audit,unsupported_situation_units=unsupported))
                missing_cases=missing_case_actions(verdict.case_action_review,proposal.conclusions,
                    question=question,user_turns=user_turns,requirements=proposal.case_requirements,
                    situation_review=verdict.situation_review)
                if missing_cases:
                    rejected=verdict.model_copy(update=dict(supported=False,reason_code='INCOMPLETE_ANSWER',
                        reason_detail='Required case state or next action was not applied in its conclusion.'))
                    return rejection_decision(search,verdict=rejected,proposal=proposal,question=question,
                        trusted_slots=trusted_slots,user_turns=user_turns,context_id=context_id,clarify_turns=clarify_turns,
                        audit=dict(audit,missing_case_indices=missing_cases))
                missing_rules=missing_conclusion_rules(rules,verdict.rule_coverage,proposal.conclusions)
                if missing_rules:
                    rejected=verdict.model_copy(update=dict(supported=False,reason_code='INCOMPLETE_ANSWER',
                        reason_detail='Required selected rules were not applied in any conclusion.'))
                    return rejection_decision(search,verdict=rejected,proposal=proposal,question=question,
                        trusted_slots=trusted_slots,user_turns=user_turns,context_id=context_id,clarify_turns=clarify_turns,
                        audit=dict(audit,missing_rule_ids=missing_rules))
                decision=replace(decision,resolved=replace(decision.resolved,conclusions_verified=True))
                # Validate the complete public output before any persistence.
                # Never silently truncate approved originals to fit conclusions.
                from app.learn.approved_renderer import render
                render(decision.plan,search.snapshot,store_id=store_id,request_id='general-output-check',resolved=decision.resolved)
            return decision,dict(audit,status='STRUCTURE_AND_MODEL_CHECKED',response_style=release.response_style,
                case_requirements=proposal.case_requirements.model_dump(mode='json') if proposal.case_requirements else None,
                case_action_review=verdict.case_action_review.model_dump(mode='json') if verdict.case_action_review else None,
                rule_coverage=[c.model_dump(mode='json') for c in verdict.rule_coverage],
                conclusion_units=review['conclusion_units'],
                situation_review=[c.model_dump(mode='json') for c in verdict.situation_review],
                candidate_coverage=[c.model_dump(mode='json') for c in verdict.candidate_coverage],
                checked_conclusion_ids=list(verdict.checked_conclusion_ids),checked_user_turn_ids=list(verdict.checked_user_turn_ids))
    except BudgetDenied:raise
    except ApiError:raise
    except UsageWriteError as exc:raise ApiError(503,'USAGE_UNAVAILABLE','의미 해석 계측을 시작하지 못했습니다.',retryable=True) from exc
    except TimeoutError as exc:raise ApiError(504,'GENERAL_DEADLINE','의미 해석 시간이 초과되었습니다.',retryable=True) from exc
    except (ValueError,KeyError,StopIteration) as exc:
        # 사유를 남기지 않으면 유료 실행에서 무엇이 막았는지 알 수 없다(2026-10-15 진단).
        # 코드가 쓴 상수 문구만 싣는다 — 계약 위반 상세는 **위치·종류만** 남기고
        # 사용자 글·모델 설명이 섞일 수 있는 입력값은 싣지 않는다.
        errors=getattr(exc,'errors',None)
        detail=('; '.join(sorted({'.'.join(str(p) for p in e.get('loc',()))+':'+e.get('type','')
                                  for e in errors()}))[:300] if callable(errors)
                else f'{type(exc).__name__}: {exc}'[:300])
        logger.warning('general_proposal_rejected detail=%s',detail)
        raise ApiError(503,'GENERAL_INVALID_PROPOSAL','해석 결과를 검증하지 못했습니다.',retryable=False) from exc
    except Exception as exc:raise ApiError(503,'GENERAL_MODEL_UNAVAILABLE','의미 해석을 완료하지 못했습니다.',retryable=True) from exc
