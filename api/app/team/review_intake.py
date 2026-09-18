"""Incremental human decisions before snapshot mapping; never implicit approval."""
from copy import deepcopy
from datetime import datetime, timezone
from typing import Literal

from pydantic import Field, StrictBool, model_validator
from app.contracts.common import Contract
from app.contracts.hashing import digest
from app.team.reviewed_manifest import ReviewedCase


class HumanCaseDecision(Contract):
    meaning_id: str = Field(min_length=1)
    question: str = Field(min_length=1, max_length=1000)
    expected_action: Literal['ANSWER', 'CLARIFY', 'ESCALATE', 'REFUSE', 'SAFE_ROUTE']
    must_have: StrictBool
    applicability: Literal['SPECIFIC', 'COMMON', 'NOT_APPLICABLE', 'UNDETERMINED']
    conditions: tuple[str, ...]
    exceptions: tuple[str, ...]
    scope_reason: str = Field(min_length=1)
    forbidden_claims: tuple[str, ...]
    reviewer: str = Field(min_length=1)
    reason: str = Field(min_length=1)

    @model_validator(mode='after')
    def substantive(self):
        if any(not value.strip() for value in (self.meaning_id, self.question, self.scope_reason, self.reviewer, self.reason)):
            raise ValueError('explicit human question, scope and attribution required')
        if self.expected_action == 'ANSWER' and self.applicability == 'UNDETERMINED':
            raise ValueError('unresolved applicability cannot approve ANSWER')
        return self


def checked_queue(queue):
    if (queue.get('schema_version') != 'r_review_queue/v1'
            or digest({k: v for k, v in queue.items() if k != 'queue_hash'}) != queue.get('queue_hash')):
        raise ValueError('stale or altered review queue')
    ids = queue['selected_meaning_ids']
    if not ids or len(set(ids)) != len(ids) or set(ids) != {r['meaning_id'] for r in queue['source_rows']}:
        raise ValueError('invalid review denominator')
    return queue


def _sealed(payload):
    return dict(payload, intake_hash=digest(payload))


def start_intake(queue):
    checked_queue(queue)
    return _sealed(dict(schema_version='r_review_intake/v1', queue_hash=queue['queue_hash'],
        review_hash=queue['review_hash'], revision=0, events=[], decisions={},
        production_promotion=False, evaluation_ready=False))


def checked_intake(queue, intake):
    checked_queue(queue)
    if (intake.get('schema_version') != 'r_review_intake/v1'
            or intake.get('queue_hash') != queue['queue_hash']
            or intake.get('review_hash') != queue['review_hash']
            or intake.get('production_promotion') is not False
            or intake.get('evaluation_ready') is not False
            or digest({k: v for k, v in intake.items() if k != 'intake_hash'}) != intake.get('intake_hash')):
        raise ValueError('stale or altered intake')
    if not set(intake['decisions']).issubset(queue['selected_meaning_ids']):
        raise ValueError('foreign reviewed question')
    if type(intake['revision']) is not int or not 0 <= intake['revision'] <= 10000 or len(intake['events']) != intake['revision']:
        raise ValueError('invalid intake revision')
    replay = start_intake(queue)
    keys = set()
    for event in intake['events']:
        decision = HumanCaseDecision.model_validate(event['decision']).model_dump(mode='json')
        if (event['previous_hash'] != replay['intake_hash'] or event['revision'] != replay['revision'] + 1
                or event['body_hash'] != digest(decision) or event['request_id'] in keys
                or decision['meaning_id'] not in queue['selected_meaning_ids']):
            raise ValueError('inconsistent review history')
        keys.add(event['request_id'])
        payload = deepcopy({k: v for k, v in replay.items() if k != 'intake_hash'})
        payload['revision'] += 1
        payload['events'].append(event)
        payload['decisions'][decision['meaning_id']] = decision
        replay = _sealed(payload)
    if replay != intake:
        raise ValueError('review projection differs from recorded decisions')
    return intake


def record_decision(queue, intake, *, expected_hash, request_id, decision):
    """CAS plus idempotent receipt; corrections append evidence instead of erasing it."""
    checked_intake(queue, intake)
    parsed = HumanCaseDecision.model_validate(decision)
    if parsed.meaning_id not in queue['selected_meaning_ids'] or not 8 <= len(request_id) <= 80:
        raise ValueError('known question and bounded request key required')
    body = parsed.model_dump(mode='json')
    body_hash = digest(body)
    previous = next((e for e in intake['events'] if e['request_id'] == request_id), None)
    if previous:
        if previous['body_hash'] != body_hash:
            raise ValueError('review request key conflict')
        return intake
    if intake['intake_hash'] != expected_hash:
        raise ValueError('review changed; inspect latest before correcting')
    result = deepcopy({k: v for k, v in intake.items() if k != 'intake_hash'})
    result['revision'] += 1
    result['events'].append(dict(request_id=request_id, body_hash=body_hash,
        previous_hash=expected_hash, revision=result['revision'],
        recorded_at=datetime.now(timezone.utc).isoformat(), decision=body))
    result['decisions'][parsed.meaning_id] = body
    return _sealed(result)


def pending_questions(queue, intake, *, limit=5):
    checked_intake(queue, intake)
    if type(limit) is not int or not 1 <= limit <= 10:
        raise ValueError('review one to ten questions at a time')
    return [row for row in queue['source_rows'] if row['meaning_id'] not in intake['decisions']][:limit]


def mapped_judgments(queue, intake, *, mappings):
    """Prepare existing finalize_review input; that function still verifies the approved snapshot."""
    checked_intake(queue, intake)
    selected = set(queue['selected_meaning_ids'])
    if set(intake['decisions']) != selected or set(mappings) != selected:
        raise ValueError('all selected human decisions and explicit mappings required')
    judgments = []
    for meaning_id in queue['selected_meaning_ids']:
        evidence = mappings[meaning_id]
        if set(evidence) != {'required_fact_revisions', 'required_raw_blocks'}:
            raise ValueError('mapping cannot override human judgments')
        row = ReviewedCase.model_validate(dict(intake['decisions'][meaning_id], **evidence))
        judgments.append(row.model_dump(mode='json'))
    return dict(review_hash=queue['review_hash'], selected_meaning_ids=queue['selected_meaning_ids'],
        selection_reason=queue['selection_reason'], judgments=judgments)
