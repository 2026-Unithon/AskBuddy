import json
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.reg.index_preparation import IndexDocument, _document_key, _reusable_vectors, _valid_vector


DOC = IndexDocument('1', '2', 'raw1', '승인 원문', '제목\n승인 원문')
VECTOR = [0.123456789, 1.0] + [0.0]*1534


@pytest.mark.parametrize('field,value', [
    ('card_id', '3'), ('card_version_id', '4'), ('block_id', 'raw2'),
    ('approved_text', '승인 원문 '), ('retrieval_text', '다른 제목\n승인 원문'),
])
def test_each_document_identity_component_invalidates_reuse(field, value):
    assert _document_key(DOC) != _document_key(replace(DOC, **{field: value}))


@pytest.mark.parametrize('vector', [[0.0]*1536, [1.0], [True]*1536,
                                   [float('nan')]*1536, [float('inf')]*1536])
def test_invalid_reused_or_provider_vector(vector):
    assert not _valid_vector(vector)


@pytest.mark.asyncio
async def test_exact_input_reuses_literal_without_rounding():
    literal = json.dumps(VECTOR)
    conn = AsyncMock()
    conn.fetch.return_value = [dict(card_id=1, card_version_id=2, block_id='raw1',
        approved_text=DOC.approved_text, retrieval_text=DOC.retrieval_text, vector=literal)]
    content = SimpleNamespace(glossary_version='dictionary/v1', renderer_version='renderer/v1')
    reused = await _reusable_vectors(conn, store_id=7, content=content, model='model', docs=(DOC,))
    assert reused == {_document_key(DOC): literal}
    assert conn.fetch.call_args.args[1:] == (7, 'model', 'r-block-index/v1', 'dictionary/v1', 'renderer/v1')
    conn.fetch.return_value[0]['retrieval_text'] += ' '
    assert not await _reusable_vectors(conn, store_id=7, content=content, model='model', docs=(DOC,))


@pytest.mark.asyncio
@pytest.mark.parametrize('vector', ['invalid', '[0]', json.dumps([0.0]*1536)])
async def test_invalid_cached_vector_becomes_miss(vector):
    conn = AsyncMock()
    conn.fetch.return_value = [dict(card_id=1, card_version_id=2, block_id='raw1',
        approved_text=DOC.approved_text, retrieval_text=DOC.retrieval_text, vector=vector)]
    assert not await _reusable_vectors(conn, store_id=7,
        content=SimpleNamespace(glossary_version='g', renderer_version='r'), model='m', docs=(DOC,))
