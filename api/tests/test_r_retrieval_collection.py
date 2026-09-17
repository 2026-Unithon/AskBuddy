from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.contracts.hashing import digest
from app.contracts.snapshot import PublishedKnowledgeSnapshot
from app.reg.hybrid import ChannelSearchResult, hybrid_search
from app.reg.index_audit import audit_index_universe
from app.team.retrieval_collection import collect_retrieval_pool


@pytest.fixture
def sample():
    snapshot = PublishedKnowledgeSnapshot.model_validate_json((Path(__file__).parent /
        'fixtures/contracts/v1/snapshot.json').read_text(encoding='utf-8'))
    refs = tuple((c.card_id,c.card_version_id,b.block_id) for c in snapshot.cards for b in c.blocks)
    def row(ref, score):
        return dict(card_id=int(ref[0]),card_version_id=int(ref[1]),block_id=ref[2],score=score)
    result = ChannelSearchResult(snapshot,7,(row(refs[0],.5),),
        tuple(row(ref,.2) for ref in refs),'질문',(),refs,audit_index_universe(snapshot,refs))
    args = dict(store_id=int(snapshot.store_id),question_id='q1',question='질문',
        query_vector=[1.]+[0.]*1535,embedding_metadata=dict(provider='fixture',
        model='fixed',mode='SYNTHETIC',reference='fixture/v1'),
        expected_snapshot={k:getattr(snapshot,k) for k in ('snapshot_id','knowledge_revision','snapshot_hash')},
        oracle=[],sample_size=2,seed='fixed',channel_limit=20)
    return result,args


@pytest.mark.asyncio
async def test_collection_keeps_full_channels_and_pins_identity(sample):
    result,args = sample
    with patch('app.reg.hybrid.search_channels',new=AsyncMock(return_value=result)) as search:
        collected = await collect_retrieval_pool(object(),**args)
        assert search.call_args.kwargs['include_universe'] is True
        assert collected['review_pool']['pooled_size'] == len(result.vector)
        assert collected['vector'] == list(result.vector)
        assert collected['query_vector_hash'] == digest(args['query_vector'])
        assert collected['collection_hash'] == digest({k:v for k,v in collected.items() if k!='collection_hash'})
        product = await hybrid_search(object(),store_id=args['store_id'],question='질문',
            query_vector=args['query_vector'],candidate_limit=1)
        assert len(product.candidates) == 1
        assert 'include_universe' not in search.call_args.kwargs


@pytest.mark.asyncio
async def test_snapshot_drift_rejected(sample):
    result,args = sample
    args['expected_snapshot']['knowledge_revision'] = '999'
    with patch('app.reg.hybrid.search_channels',new=AsyncMock(return_value=result)):
        with pytest.raises(ValueError,match='snapshot changed'):
            await collect_retrieval_pool(object(),**args)


@pytest.mark.asyncio
async def test_metadata_required_before_query(sample):
    _,args = sample
    args['embedding_metadata']['mode'] = 'UNKNOWN'
    with patch('app.reg.hybrid.search_channels',new=AsyncMock()) as search:
        with pytest.raises(ValueError,match='embedding'):
            await collect_retrieval_pool(object(),**args)
        search.assert_not_called()
