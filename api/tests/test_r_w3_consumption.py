"""R consumer tests. These are synthetic contracts, not W3 production evidence."""
from dataclasses import replace
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from app.contracts.hashing import snapshot_digest, verify_snapshot_hash
from app.contracts.snapshot import FactProvenance, PublishedKnowledgeSnapshot
from app.errors import ApiError
from app.learn.approved_renderer import render
from app.learn.planner import decide
from app.reg.index_preparation import documents
from app.reg.owner_candidates import published_owner_candidates
from tests import test_r_planner as planner_fixture


def owner_facts():
    found = planner_fixture.PlannerTest().search()
    payload = found.snapshot.model_dump(mode='json')
    for fact in payload['fact_revisions']:
        fact['provenance'] = [dict(owner_answer_id='17')]
    snapshot = PublishedKnowledgeSnapshot.model_validate(payload)
    snapshot = snapshot.model_copy(update=dict(snapshot_hash=snapshot_digest(snapshot)))
    return replace(found, snapshot=snapshot)


def test_typed_owner_facts_survive_search_plan_render_and_hash():
    found = owner_facts()
    verify_snapshot_hash(found.snapshot)
    assert documents(found.snapshot)
    decision = decide(found, store_id=1, question='HOT 라테 우유 얼마나?')
    assert decision.plan.action == 'ANSWER'
    response = render(decision.plan, found.snapshot, store_id=1, request_id='w3-consumer')
    assert response.citations
    assert all(c.fact_revision_id and c.owner_answer_id == '17' and c.source_id is None
               for c in response.citations)
    changed = found.snapshot.model_dump(mode='json')
    changed['fact_revisions'][0]['provenance'][0]['owner_answer_id'] = '18'
    with pytest.raises(ValueError, match='hash'):
        verify_snapshot_hash(PublishedKnowledgeSnapshot.model_validate(changed))


def test_mixed_fact_provenance_keeps_all_origins():
    found = owner_facts()
    facts = tuple(f.model_copy(update=dict(provenance=(
        *f.provenance, FactProvenance(source_id='7', occurrence_id='8'))))
        for f in found.snapshot.fact_revisions)
    snapshot = found.snapshot.model_copy(update=dict(fact_revisions=facts))
    snapshot = snapshot.model_copy(update=dict(snapshot_hash=snapshot_digest(snapshot)))
    decision = decide(replace(found, snapshot=snapshot), store_id=1, question='HOT 라테 우유 얼마나?')
    response = render(decision.plan, snapshot, store_id=1, request_id='mixed-origin',
                      availability={'7': 'DELETED'})
    assert {c.source_id for c in response.citations} == {None, '7'}
    assert any(c.is_broken for c in response.citations)
    assert any(c.owner_answer_id == '17' and not c.is_broken for c in response.citations)


@pytest.mark.parametrize('origin', [{}, {'source_id': '1'}, {'owner_answer_id': '2', 'occurrence_id': '3'},
    {'source_id': '1', 'occurrence_id': '3', 'owner_answer_id': '2'}])
def test_invalid_provenance_cannot_enter_snapshot(origin):
    with pytest.raises(ValidationError):
        FactProvenance(**origin)


def connection():
    db = MagicMock()
    db.transaction.return_value.__aenter__ = AsyncMock()
    db.transaction.return_value.__aexit__ = AsyncMock(return_value=False)
    db.fetchval = AsyncMock()
    return db


@pytest.mark.asyncio
async def test_new_or_excluded_store_has_no_candidates_without_reading_index(monkeypatch):
    db = connection()
    db.fetchval.return_value = False
    read = AsyncMock(side_effect=AssertionError('empty store must not require index'))
    monkeypatch.setattr('app.reg.owner_candidates.read_current_index', read)
    assert await published_owner_candidates(db, store_id=1, query_vector=[1.] + [0.]*1535,
        embedding_model='synthetic', top_k=5) == []
    assert db.fetchval.call_args.args[1] == 1
    read.assert_not_called()


@pytest.mark.asyncio
async def test_approved_knowledge_missing_index_stays_retryable_error(monkeypatch):
    db = connection()
    db.fetchval.return_value = True
    monkeypatch.setattr('app.reg.owner_candidates.read_current_index',
        AsyncMock(side_effect=ApiError(503, 'INDEX_UNAVAILABLE', 'missing', retryable=True)))
    with pytest.raises(ApiError) as caught:
        await published_owner_candidates(db, store_id=1, query_vector=[1.] + [0.]*1535,
            embedding_model='synthetic', top_k=5)
    assert caught.value.code == 'INDEX_UNAVAILABLE'


@pytest.mark.asyncio
@pytest.mark.parametrize('damage', [None, 'json', 'shape', 'schema', 'hash', 'duplicate_metadata'])
async def test_corrupt_publication_is_retryable_not_empty(damage):
    from app.contracts.hashing import knowledge_content_payload
    from app.reg.hybrid import read_current_index
    snapshot = owner_facts().snapshot
    content = knowledge_content_payload(snapshot)
    row = dict(content=content, snapshot_id=snapshot.snapshot_id,
        knowledge_revision=snapshot.knowledge_revision, snapshot_hash=snapshot.snapshot_hash,
        created_at=snapshot.created_at, glossary_version=snapshot.glossary_version,
        renderer_version=snapshot.renderer_version, prepared_id='synthetic', index_revision=1)
    if damage == 'json':
        row['content'] = '{'
    elif damage == 'shape':
        row['content'] = []
    elif damage == 'schema':
        content['cards'] = [{'card_id': 'invalid'}]
    elif damage == 'hash':
        row['snapshot_hash'] = '0' * 64
    elif damage == 'duplicate_metadata':
        content['snapshot_id'] = snapshot.snapshot_id
    db = connection()
    db.fetchrow = AsyncMock(return_value=row)
    if damage is None:
        loaded, _, _ = await read_current_index(db, store_id=int(snapshot.store_id))
        assert loaded == snapshot
        return
    with pytest.raises(ApiError) as caught:
        await read_current_index(db, store_id=int(snapshot.store_id))
    assert caught.value.code == 'INDEX_UNAVAILABLE'
    assert caught.value.status_code == 503 and caught.value.retryable


@pytest.mark.asyncio
async def test_legacy_retrieve_uses_current_index_and_preserves_category(monkeypatch):
    from app.reg import retrieve
    candidates = AsyncMock(return_value=[dict(id=3, version_id=4, title='우유 보관',
        content='우유는 냉장 보관합니다.', category_name='보관', score=.9)])
    monkeypatch.setattr(retrieve, 'published_owner_candidates', candidates)
    monkeypatch.setattr(retrieve, 'embed_text', lambda _: [1.] + [0.]*1535)
    monkeypatch.setattr(retrieve, 'get_settings', lambda: NS(embedding_model='synthetic', retrieval_threshold=.35))
    result = await retrieve.retrieve_question(object(), 7, '우유 보관')
    assert result['kind'] == 'hit' and result['candidates'][0]['version_id'] == 4
    assert result['candidates'][0]['category'] == '보관'
    assert candidates.call_args.kwargs['store_id'] == 7
    candidates.side_effect = ApiError(503, 'INDEX_UNAVAILABLE', 'missing')
    with pytest.raises(ApiError):
        await retrieve.retrieve_question(object(), 7, '우유 보관')


@pytest.mark.asyncio
async def test_retention_is_disabled_without_touching_database(monkeypatch):
    from app.reg import index_retention
    monkeypatch.setattr(index_retention, 'get_settings', lambda: NS(r_index_gc_enabled=False))
    assert await index_retention.purge_expired_index_documents(object()) == 0
    monkeypatch.setattr(index_retention, 'get_settings', lambda: NS(r_index_gc_enabled=True,
        r_index_gc_keep_previous=None, r_index_gc_min_age_days=None))
    with pytest.raises(ValueError, match='requires agreed'):
        await index_retention.purge_expired_index_documents(object())


@pytest.mark.asyncio
async def test_empty_worker_store_can_process_first_owner_answer(monkeypatch):
    from app.cards import owner_answer_worker as worker
    from app.publish.bootstrap import IndexStatus
    from tests.test_r_usage_routes import Pool
    monkeypatch.setattr(worker, 'index_status', AsyncMock(return_value=IndexStatus(1, 'EMPTY', 0, 0)))
    assert await worker._index_ready(Pool(), store_id=1, warned={})


@pytest.mark.asyncio
@pytest.mark.parametrize('exists', [True, False])
async def test_initial_empty_publication_only_when_needed(monkeypatch, exists):
    from app.publish import empty
    from app.publish.approval import PublishCardsResult
    from tests.test_r_usage_routes import Pool
    pool = Pool()
    pool.fetchval = AsyncMock(return_value=exists)
    publish = AsyncMock(return_value=PublishCardsResult(status='PUBLISHED'))
    monkeypatch.setattr(empty, 'publish_cards', publish)
    await empty.ensure_initial_publication(pool, store_id=7, member_id=3, user_id=10)
    assert publish.await_count == (0 if exists else 1)
    if not exists:
        assert publish.call_args.kwargs['initialize_empty']
        assert publish.call_args.kwargs['changes'] == []
