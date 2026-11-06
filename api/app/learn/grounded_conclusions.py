"""Bounded, model-verified application of approved evidence to user context.

These checks prove provenance/coverage, not the truth of a natural-language
inference. Conclusions never become approved knowledge or confirmed user slots.
"""
from typing import Literal
import re
from pydantic import Field, StrictBool, StrictInt
from app.contracts.common import Contract
from app.contracts.answer import SelectedBlock


class UserEvidence(Contract):
    turn_id: StrictInt = Field(ge=0,le=10)
    quote: str = Field(min_length=1,max_length=1000)


class GroundedConclusion(Contract):
    statement: str = Field(min_length=1,max_length=500)
    question_quote: str = Field(min_length=1,max_length=1000)
    user_evidence: tuple[UserEvidence,...] = Field(min_length=1,max_length=11)
    references: tuple[SelectedBlock,...] = Field(min_length=1,max_length=10)


class CandidateCoverage(Contract):
    reference: SelectedBlock
    required: StrictBool
    rationale: str = Field(min_length=1,max_length=500)


class RuleCoverage(Contract):
    rule_id: str = Field(min_length=1,max_length=30)
    required: StrictBool
    conclusion_unit_id: str | None = Field(default=None,pattern=r'^c[0-7]s[0-9]{1,3}$')
    rationale: str = Field(min_length=1,max_length=500)


class SituationReview(Contract):
    conclusion_unit_id: str = Field(pattern=r'^c[0-7]s[0-9]{1,3}$')
    status: Literal['NO_CASE_FACTS','GROUNDED_CASE_FACTS','UNSUPPORTED_CASE_FACTS']
    user_evidence: tuple[UserEvidence,...] = Field(max_length=11)
    rationale: str = Field(min_length=1,max_length=500)


def conclusion_units(conclusions):
    """서버가 원문 위치를 보존해 문장 ID를 발급한다. 의미 분해/교정은 하지 않는다."""
    units=[]
    for index,c in enumerate(conclusions):
        start=0
        for end in [m.end() for m in re.finditer(r'[.!?](?=\s|$)|\n',c.statement)]+[len(c.statement)]:
            text=c.statement[start:end]
            if text.strip():
                ordinal=sum(u['conclusion_id']==index for u in units)
                units.append(dict(unit_id=f'c{index}s{ordinal}',conclusion_id=index,start=start,end=end,text=text))
            start=end
    if len(units)>200:raise ValueError('too many conclusion units')
    return units


def unsupported_situations(review,conclusions,*,question,user_turns):
    """전체 문장의 사건 사실 검토와 사용자 출처를 강제한다. 함의는 모델 판단이다."""
    units={u['unit_id']:u for u in conclusion_units(conclusions)}
    turns=(*user_turns,question);seen=set();unsupported=[]
    for item in review:
        key=item.conclusion_unit_id
        if key not in units or key in seen or not item.rationale.strip():
            raise ValueError('invalid situation review')
        seen.add(key)
        if item.status=='NO_CASE_FACTS' and item.user_evidence:
            raise ValueError('non-case statement has case evidence')
        if item.status=='GROUNDED_CASE_FACTS' and not item.user_evidence:
            raise ValueError('case facts require user evidence')
        c=conclusions[units[key]['conclusion_id']]
        for e in item.user_evidence:
            if (not e.quote.strip() or e.turn_id>=len(turns) or e.quote not in turns[e.turn_id]
                    or not any(x.turn_id==e.turn_id and e.quote in x.quote for x in c.user_evidence)):
                raise ValueError('situation user evidence mismatch')
        if item.status=='UNSUPPORTED_CASE_FACTS':unsupported.append(key)
    if seen!=set(units):raise ValueError('incomplete situation review')
    return unsupported


class CaseAction(Contract):
    subject: UserEvidence
    state: UserEvidence
    conclusion_id: StrictInt | None = Field(default=None,ge=0,le=7)
    next_action_quote: str = Field(default='',max_length=500)
    state_unit_id: str | None = Field(default=None,pattern=r'^c[0-7]s[0-9]{1,3}$',
        description='Conclusion sentence applying this user state. Required when the answer paraphrases state.quote. Select a server conclusion_units ID; its GROUNDED_CASE_FACTS review must cite the exact state evidence.')


class CaseRequirement(Contract):
    subject: UserEvidence
    state: UserEvidence


class CaseRequirements(Contract):
    scope: Literal['NOT_APPLICABLE','CASE_ACTIONS']
    rationale: str = Field(min_length=1,max_length=500)
    cases: tuple[CaseRequirement,...] = Field(max_length=10)


def case_requirement_keys(requirements, *, question, user_turns, selected_case=None):
    if requirements is None or not requirements.rationale.strip():
        raise ValueError('question case requirements required')
    if bool(requirements.cases)!=(requirements.scope=='CASE_ACTIONS'):
        raise ValueError('case requirement scope mismatch')
    if selected_case and (requirements.scope!='CASE_ACTIONS' or len(requirements.cases)!=1
            or requirements.cases[0].subject.quote not in selected_case):
        raise ValueError('question requirements contradict selected case')
    turns=(*user_turns,question);seen=set();keys=set()
    for item in requirements.cases:
        for e in (item.subject,item.state):
            if not e.quote.strip() or e.turn_id>=len(turns) or e.quote not in turns[e.turn_id]:
                raise ValueError('case requirement user evidence mismatch')
        if item.subject.quote in seen:raise ValueError('duplicate case requirement')
        seen.add(item.subject.quote)
        keys.add((item.subject.turn_id,item.subject.quote,item.state.turn_id,item.state.quote))
    return keys


class CaseActionReview(Contract):
    scope: Literal['NOT_APPLICABLE','CASE_ACTIONS']
    rationale: str = Field(min_length=1,max_length=500)
    cases: tuple[CaseAction,...] = Field(max_length=10)


def missing_case_actions(review,conclusions,*,question,user_turns,requirements=None,situation_review=()):
    """Bind verifier-enumerated case actions to user evidence and the answer.

    Applicability, case enumeration, latest-state selection and action meaning
    still require semantic verification; literal coverage alone cannot prove them.
    """
    if review is None or not review.rationale.strip():
        raise ValueError('explicit case action review required')
    if requirements is not None:
        required=case_requirement_keys(requirements,question=question,user_turns=user_turns)
        observed=case_requirement_keys(review,question=question,user_turns=user_turns)
        if requirements.scope!=review.scope or required!=observed:
            # A verifier cannot silently narrow the question to the generated answer.
            return list(range(max(1,len(required),len(observed))))
    if review.scope=='NOT_APPLICABLE':
        if review.cases:raise ValueError('non-applicable case review has cases')
        return []
    if not review.cases:raise ValueError('case action review has no cases')
    turns=(*user_turns,question);seen=set();missing=[]
    units={u['unit_id']:u for u in conclusion_units(conclusions)}
    reviews={r.conclusion_unit_id:r for r in situation_review}
    for index,item in enumerate(review.cases):
        for evidence in (item.subject,item.state):
            if (not evidence.quote.strip() or evidence.turn_id>=len(turns)
                    or evidence.quote not in turns[evidence.turn_id]):
                raise ValueError('case action user evidence mismatch')
        # The same named subject must not be counted twice to hide another case.
        if item.subject.quote in seen:raise ValueError('duplicate case action subject')
        seen.add(item.subject.quote)
        if item.conclusion_id is None:
            if item.next_action_quote or item.state_unit_id:raise ValueError('case action quote without conclusion')
            missing.append(index)
            continue
        if item.conclusion_id>=len(conclusions):raise ValueError('unknown case action conclusion')
        c=conclusions[item.conclusion_id]
        for evidence in (item.subject,item.state):
            if not any(e.turn_id==evidence.turn_id and evidence.quote in e.quote for e in c.user_evidence):
                raise ValueError('case action not grounded in conclusion user evidence')
        if item.subject.quote not in c.statement:missing.append(index)
        if item.state_unit_id is not None:
            unit=units.get(item.state_unit_id);audit=reviews.get(item.state_unit_id)
            if unit is None or unit['conclusion_id']!=item.conclusion_id:
                raise ValueError('case state sentence outside conclusion')
            if (audit is None or audit.status!='GROUNDED_CASE_FACTS'
                    or not any(e.turn_id==item.state.turn_id and item.state.quote in e.quote for e in audit.user_evidence)):
                missing.append(index)
        elif item.state.quote not in c.statement:
            missing.append(index)
        if not item.next_action_quote.strip() or item.next_action_quote not in c.statement:
            missing.append(index)
    return sorted(set(missing))


def selected_rules(plan,snapshot):
    rules=[]
    for b in plan.selected_blocks:
        if b.raw_span_id:
            texts=next(r.text for r in snapshot.raw_spans if r.raw_span_id==b.raw_span_id).splitlines()
            units=[(b,t) for t in texts if t.strip()]
        else:
            units=[(b.model_copy(update={'fact_revision_ids':(fid,)}),t)
                for fid in b.fact_revision_ids for f in (snapshot.fact(fid),)
                for t in (f.assertion,*f.conditions,*f.exceptions) if t.strip()]
        for ref,text in units:rules.append(dict(rule_id='r'+str(len(rules)),reference=ref.model_dump(mode='json'),text=text))
    return rules


def missing_conclusion_rules(rules,coverage,conclusions):
    by_id={r['rule_id']:r for r in rules};seen=set();missing=[]
    units={u['unit_id']:u for u in conclusion_units(conclusions)}
    for item in coverage:
        if item.rule_id not in by_id or item.rule_id in seen or not item.rationale.strip():
            raise ValueError('invalid rule coverage')
        seen.add(item.rule_id)
        if item.conclusion_unit_id is None:
            if item.required:missing.append(item.rule_id)
        else:
            if item.conclusion_unit_id not in units:raise ValueError('unknown conclusion unit')
            conclusion=conclusions[units[item.conclusion_unit_id]['conclusion_id']]
            ref=SelectedBlock.model_validate(by_id[item.rule_id]['reference'])
            if not atoms((ref,))<=atoms(conclusion.references):raise ValueError('rule not cited by conclusion')
    if seen!=set(by_id) or not any(c.required for c in coverage):raise ValueError('incomplete selected rule inspection')
    return missing


def atoms(blocks):
    return {(b.card_id,b.card_version_id,b.block_id,kind,value)
        for b in blocks for kind,value in
        ((('raw',b.raw_span_id),) if b.raw_span_id else tuple(('fact',f) for f in b.fact_revision_ids))}


def validate_conclusions(conclusions,*,plan,question,user_turns):
    if not conclusions:return
    if plan.action!='ANSWER' or len(conclusions)>8:raise ValueError('conclusions require bounded ANSWER')
    if (not isinstance(question,str) or not question.strip() or len(question)>1000
            or len(user_turns)>10 or any(not isinstance(t,str) or not t.strip() or len(t)>1000 for t in user_turns)):
        raise ValueError('bounded user context required')
    selected=atoms(plan.selected_blocks)
    turns=(*user_turns,question)
    for c in conclusions:
        # Reparse even server dataclass inputs before persistence/rendering.
        c=GroundedConclusion.model_validate(c.model_dump())
        refs=atoms(c.references)
        if (not c.statement.strip() or not c.question_quote.strip() or c.question_quote not in question or not refs or not refs<=selected
                or any(bool(b.raw_span_id)==bool(b.fact_revision_ids) for b in c.references)):
            raise ValueError('conclusion outside question or selected evidence')
        for e in c.user_evidence:
            if not e.quote.strip() or e.turn_id>=len(turns) or e.quote not in turns[e.turn_id]:
                raise ValueError('conclusion user evidence mismatch')


def candidate_references(search):
    refs=[]
    for candidate in search.candidates:
        card=search.snapshot.card(candidate.card_id)
        block=next(b for b in card.blocks if b.block_id==candidate.block_id)
        base=dict(card_id=card.card_id,card_version_id=card.card_version_id,block_id=block.block_id)
        if block.raw_span_id:refs.append(SelectedBlock(**base,raw_span_id=block.raw_span_id))
        else:refs.extend(SelectedBlock(**base,fact_revision_ids=(fid,)) for fid in block.fact_revision_ids)
    return tuple(refs)


def reference_scopes(search):
    """Describe retrieved evidence scopes without selecting relevant policy.

    User cases are not knowledge entities. Several cases may use one scope;
    one conclusion may cite evidence validated in several independent scopes.
    """
    groups={}
    for ref in candidate_references(search):
        entity=search.snapshot.card(ref.card_id).entity_id
        groups.setdefault(entity,[]).append(ref.model_dump(mode='json'))
    return [dict(entity_id=entity,references=refs) for entity,refs in groups.items()]


def missing_required_evidence(search,*,plan,coverage):
    expected=atoms(candidate_references(search));seen=set();required=set()
    for item in coverage:
        if bool(item.reference.raw_span_id)==bool(item.reference.fact_revision_ids):
            raise ValueError('coverage must identify one fact or RAW span')
        unit=atoms((item.reference,))
        if len(unit)!=1 or not unit<=expected or unit&seen or not item.rationale.strip():
            raise ValueError('invalid or duplicate candidate coverage')
        seen|=unit
        if item.required:required|=unit
    if seen!=expected or not required:raise ValueError('incomplete candidate inspection or no required evidence')
    return required-atoms(plan.selected_blocks)


def conclusion_lines(conclusions,*,citations):
    lines=[]
    for c in conclusions:
        refs=atoms(c.references)
        indices=[str(n) for n,ci in enumerate(citations,1)
            if (ci.card_id,ci.card_version_id,ci.block_id,'raw' if ci.raw_span_id else 'fact',
                ci.raw_span_id or ci.fact_revision_id) in refs]
        if not indices:raise ValueError('conclusion has no rendered citation')
        lines.append(c.statement+' [출처 '+', '.join(indices)+']')
    return lines
