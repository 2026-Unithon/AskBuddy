import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.errors import ApiError
from app.learn import owner_handoff as handoff
from app.learn import router as routes
from app.publish.approval import PublishCardsResult


@pytest.fixture
def review(monkeypatch):
    conn = MagicMock()
    conn.is_in_transaction.return_value = True
    proposal = dict(answer_id=4, status='PUBLISHED', result_card_id=5,
                    result_version_id=6, question_id=3, revision_no=2)
    state = dict(status='REVIEW', result={})
    conn.fetchrow = AsyncMock(side_effect=lambda *args: state if 'r_owner_knowledge_states' in args[0] else proposal)
    conn.fetchval = AsyncMock(side_effect=[3, 2])
    conn.execute = AsyncMock()
    evidence = AsyncMock(return_value=dict(published_card_version_id='6', snapshot_id='7',
                                          confirmed_knowledge_revision='8'))
    notify = AsyncMock()
    monkeypatch.setattr(handoff, 'publication_evidence', evidence)
    monkeypatch.setattr(handoff, 'notify_publication', notify)
    args = dict(store_id=1, proposal_id=9, owner_answer_id=4, card_id=5,
                card_version_id=6, knowledge_revision=8)
    return conn, proposal, state, evidence, notify, args


@pytest.mark.asyncio
async def test_review_finishes_once_without_reconsuming_event(review):
    conn, _, state, _, notify, args = review
    await handoff.finish_owner_review(conn, **args)
    payload = json.loads(conn.execute.call_args.args[3])
    assert payload['review_proposal_id'] == '9'
    assert payload['published_card_version_id'] == '6'
    state.update(status='PUBLISHED', result=payload)
    conn.fetchval.side_effect = [3, 2]
    await handoff.finish_owner_review(conn, **args)
    assert conn.execute.await_count == notify.await_count == 1
    assert 'outbox' not in conn.execute.call_args.args[0]


@pytest.mark.asyncio
@pytest.mark.parametrize('status', ['PENDING', 'LINKED', 'FAILED', 'PUBLISHED'])
async def test_only_review_can_transition(review, status):
    conn, _, state, _, notify, args = review
    state['status'] = status
    with pytest.raises(ApiError):
        await handoff.finish_owner_review(conn, **args)
    conn.execute.assert_not_called()
    notify.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['latest', 'version', 'answer', 'proposal', 'transaction'])
async def test_stale_or_mismatched_completion_rejected(review, change):
    conn, proposal, _, evidence, notify, args = review
    if change == 'latest':
        conn.fetchval.side_effect = [3, 3]
    elif change == 'version':
        evidence.return_value['published_card_version_id'] = '99'
    elif change == 'answer':
        proposal['answer_id'] = 99
    elif change == 'proposal':
        conn.fetchrow.side_effect = None
        conn.fetchrow.return_value = None
    else:
        conn.is_in_transaction.return_value = False
    with pytest.raises((ApiError, ValueError)):
        await handoff.finish_owner_review(conn, **args)
    conn.execute.assert_not_called()
    notify.assert_not_called()


@pytest.mark.asyncio
async def test_notification_failure_propagates_to_publication(review):
    conn, _, _, _, notify, args = review
    notify.side_effect = RuntimeError('notification unavailable')
    with pytest.raises(RuntimeError):
        await handoff.finish_owner_review(conn, **args)


@pytest.fixture
def route(monkeypatch):
    db = MagicMock()
    db.fetchval = AsyncMock(return_value=2)
    db.fetchrow = AsyncMock(return_value=dict(result_card_id=5, result_version_id=6))
    publish = AsyncMock(return_value=PublishCardsResult(status='PUBLISHED'))
    finish = AsyncMock()
    monkeypatch.setattr(routes, 'get_pool', lambda: 'pool')
    monkeypatch.setattr(routes, 'approve_owner_proposal', publish)
    monkeypatch.setattr(routes, 'finish_owner_review', finish)
    return db, publish, finish


@pytest.mark.asyncio
@pytest.mark.parametrize('status', ['PUBLISHED', 'ALREADY_APPLIED'])
async def test_route_uses_new_coordinator_and_stored_result(route, status):
    db, publish, finish = route
    publish.return_value = PublishCardsResult(status=status)
    result = await routes.approve_knowledge_proposal(9, db, {'role': 'OWNER'}, 1, 10)
    assert result == dict(proposal_id=9, status='PUBLISHED', card_id=5, version_id=6)
    kwargs = publish.call_args.kwargs
    assert kwargs['member_id'] == 2 and kwargs['actor_user_id'] == 10
    await kwargs['notify_r']('conn', 4, 5, 6, 8)
    finish.assert_awaited_once_with('conn', store_id=1, proposal_id=9, owner_answer_id=4,
                                  card_id=5, card_version_id=6, knowledge_revision=8)
    db.transaction.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize('status,code,http', [
    ('NO_PROVENANCE', None, 409), ('INVALID_CONTENT', None, 409),
    ('EMPTY_MANIFEST', None, 409), ('STALE', None, 409),
    ('PREPARE_FAILED', 'STALE_PUBLICATION', 409),
    ('PREPARE_FAILED', 'STALE_KNOWLEDGE', 409),
    ('PREPARE_FAILED', 'IDEMPOTENCY_CONFLICT', 409),
    ('PREPARE_FAILED', 'MODEL_UNAVAILABLE', 502),
])
async def test_route_failure_mapping(route, status, code, http):
    db, publish, _ = route
    publish.return_value = PublishCardsResult(status=status, error_code=code)
    with pytest.raises((ApiError, HTTPException)) as caught:
        await routes.approve_knowledge_proposal(9, db, {'role': 'OWNER'}, 1, 10)
    assert caught.value.status_code == http
    db.fetchrow.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize('role,member', [('STAFF', 2), ('OWNER', None)])
async def test_route_rejects_non_owner_before_publish(route, role, member):
    db, publish, _ = route
    db.fetchval.return_value = member
    with pytest.raises(HTTPException) as caught:
        await routes.approve_knowledge_proposal(9, db, {'role': role}, 1, 10)
    assert caught.value.status_code == 403
    publish.assert_not_called()
