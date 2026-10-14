"""User-authored case labels are dialogue references, never approved entities."""
import json
import re
from pydantic import Field, StrictInt
from app.contracts.common import Contract

CONTEXT_KEY = '_case_dialogue'


class CaseOption(Contract):
    label: str = Field(min_length=1, max_length=80)
    turn_id: StrictInt = Field(ge=0, le=10)
    question_quote: str = Field(min_length=1, max_length=1000)


def validate_case_options(options, *, allowed_options, question, user_turns, confirmed_slots):
    if confirmed_slots.get('case'):
        raise ValueError('case is already confirmed')
    labels = tuple(o.label for o in options)
    if not 2 <= len(labels) <= 10 or labels != tuple(allowed_options) or len(set(labels)) != len(labels):
        raise ValueError('distinct case options must match offered labels')
    turns = (*user_turns, question)
    for option in options:
        # Single ASCII labels must not be harvested from words such as APP.
        if (option.label != option.label.strip() or any(ord(c)<32 for c in option.label)
                or option.turn_id >= len(turns)
                or option.question_quote not in turns[option.turn_id]
                or not re.search(r'(?<![A-Za-z0-9])'+re.escape(option.label)+r'(?![A-Za-z0-9])', option.question_quote)):
            raise ValueError('case label lacks exact user-turn evidence')


def case_context_data(plan, resolved):
    if plan.clarification_slot != 'case':
        return {}
    turns = resolved.case_user_turns
    if len(turns)>10 or any(not isinstance(t,str) or not t.strip() or len(t)>1000 for t in turns):
        raise ValueError('bounded case dialogue required')
    validate_case_options(resolved.case_options, allowed_options=plan.allowed_options,
        question=resolved.question, user_turns=turns, confirmed_slots={})
    return {CONTEXT_KEY: json.dumps(dict(user_turns=turns,question=resolved.question,
        options=[o.model_dump() for o in resolved.case_options]), ensure_ascii=False)}


def case_context_turns(context):
    """Only call with an ownership/TTL-checked server context, never HTTP data."""
    data=json.loads(context.proposed_slots[CONTEXT_KEY])
    turns=tuple(data['user_turns'])
    options=tuple(CaseOption.model_validate(o) for o in data['options'])
    if len(turns)>10 or any(not isinstance(t,str) or not t.strip() or len(t)>1000 for t in turns):
        raise ValueError('invalid stored case dialogue')
    question=data['question']
    if not isinstance(question,str) or not question.strip() or len(question)>1000:
        raise ValueError('invalid stored case question')
    validate_case_options(options,allowed_options=tuple(o.label for o in options),
        question=question,user_turns=turns,confirmed_slots={})
    if context.confirmed_slots.get('case') not in {o.label for o in options}:
        raise ValueError('selected case outside stored evidence')
    return turns
