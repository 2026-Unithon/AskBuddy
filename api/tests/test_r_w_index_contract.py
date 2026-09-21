from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest

from app.contracts.snapshot import KnowledgeContent, PublishedKnowledgeSnapshot
from app.contracts.publication import PrepareIndexRequest
from app.contracts.hashing import digest, knowledge_content_payload
from app.reg import index_preparation as module


def input_request():
    snap = PublishedKnowledgeSnapshot.model_validate_json((Path(__file__).parent/'fixtures/contracts/v1/snapshot.json').read_text(encoding='utf-8'))
    content = KnowledgeContent(**{k:v for k,v in snap.model_dump().items() if k in KnowledgeContent.model_fields})
    body = dict(scope=dict(store_id=content.store_id, member_id='1'), card_ids=[c.card_id for c in content.cards],
        content_hash=digest(knowledge_content_payload(content)), expected_publication_revision='0',
        expected_card_revisions=[], embedding_model='synthetic',
        glossary_version=content.glossary_version, renderer_version=content.renderer_version)
    request = PrepareIndexRequest(**body, idempotency=dict(key='synthetic-prepare', body_hash=digest(body)))
    return content, request


@pytest.mark.asyncio
@pytest.mark.parametrize('change', [None, 'hash', 'card', 'version', 'model', 'member'])
async def test_typed_producer_preparation_rejects_drift_before_io(monkeypatch, change):
    content, request = input_request()
    if change == 'hash': request=request.model_copy(update={'content_hash':'sha256:'+'0'*64})
    if change == 'card': request=request.model_copy(update={'card_ids':('999999',)})
    if change == 'version': request=request.model_copy(update={'expected_card_revisions':('999',)})
    if change == 'model': request=request.model_copy(update={'embedding_model':'wrong'})
    if change == 'member': request=request.model_copy(update={'scope':request.scope.model_copy(update={'member_id':None})})
    # Re-sign shape-valid mutations: semantic mismatch must also be rejected.
    if change != 'hash':
        request=request.model_copy(update={'idempotency':request.idempotency.model_copy(update={
            'body_hash':digest(request.model_dump(mode='json', exclude={'idempotency'}))})})
    prepare=AsyncMock(return_value='prepared')
    monkeypatch.setattr(module, 'prepare_index', prepare)
    monkeypatch.setattr(module, 'get_settings', lambda:SimpleNamespace(embedding_model='synthetic'))
    result=await module.prepare_index_request(object(),request=request,content=content,usage_context=object())
    if change:
        assert result.status == 'FAILED'; prepare.assert_not_called()
    else:
        assert result == 'prepared'
        assert prepare.call_args.kwargs['request_binding'] == request.idempotency.body_hash
