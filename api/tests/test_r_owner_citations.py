from dataclasses import replace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from app.contracts.chat import Citation
from app.contracts.hashing import snapshot_digest
from app.contracts.snapshot import PublishedKnowledgeSnapshot
from app.learn.answer_storage import current_source_overlay
from app.learn.approved_renderer import render
from app.learn.planner import decide
from tests.test_r_raw_quantity import search


def owner_response():
    found = search()
    payload = found.snapshot.model_dump(mode='json')
    payload['raw_spans'][0].update(source_id=None, owner_answer_id='17')
    snapshot = PublishedKnowledgeSnapshot.model_validate(payload)
    snapshot = snapshot.model_copy(update=dict(snapshot_hash=snapshot_digest(snapshot)))
    found = replace(found, snapshot=snapshot)
    plan = decide(found, store_id=1, question='HOT 라테 우유 얼마나?').plan
    return render(plan, snapshot, store_id=1, request_id='owner-citation')


def test_owner_raw_render_preserves_text_and_origin():
    response = owner_response()
    assert response.message == '  HOT 라테 우유 225ml 넣는다.\n'
    assert response.citations[0].owner_answer_id == '17'
    assert response.citations[0].source_id is None
    assert not response.citations[0].is_broken


@pytest.mark.parametrize('origin', [{}, {'source_id': '1', 'owner_answer_id': '17'}])
def test_exactly_one_origin(origin):
    with pytest.raises(ValidationError):
        Citation(card_id='1', card_version_id='2', block_id='b', raw_span_id='3', **origin)


def test_owner_origin_can_cite_w3_typed_fact():
    citation = Citation(card_id='1', card_version_id='2', block_id='b', fact_revision_id='3', owner_answer_id='17')
    assert citation.source_id is None and not citation.is_broken


@pytest.mark.asyncio
async def test_owner_history_does_not_look_up_a_file():
    conn = AsyncMock()
    response = await current_source_overlay(conn, store_id=1, response=owner_response())
    conn.fetch.assert_not_called()
    assert response.citations[0].source_availability == 'AVAILABLE'


@pytest.mark.asyncio
async def test_mixed_history_only_overlays_file_availability():
    response = owner_response()
    file_citation = Citation(card_id='2', card_version_id='3', block_id='b', raw_span_id='4', source_id='9')
    response = response.model_copy(update=dict(citations=(*response.citations, file_citation)))
    conn = AsyncMock()
    conn.fetch.return_value = [dict(source_id=9, source_availability='DELETED')]
    current = await current_source_overlay(conn, store_id=1, response=response)
    assert conn.fetch.call_args.args[1:] == (1, [9])
    assert [c.source_availability for c in current.citations] == ['AVAILABLE', 'DELETED']
    assert current.message == response.message
