from pathlib import Path
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import pytest

from app.contracts.snapshot import PublishedKnowledgeSnapshot
from app.reg.index_audit import audit_index_universe, IndexUniverseMismatch
from app.reg.hybrid import search_channels


@pytest.fixture
def universe():
    snapshot = PublishedKnowledgeSnapshot.model_validate_json((Path(__file__).parent /
        'fixtures/contracts/v1/snapshot.json').read_text(encoding='utf-8'))
    refs = [(c.card_id,c.card_version_id,b.block_id) for c in snapshot.cards for b in c.blocks]
    return snapshot,refs


def test_exact_universe_and_order_independent_report(universe):
    snapshot,refs = universe
    report = audit_index_universe(snapshot,refs)
    assert report['complete']
    assert report == audit_index_universe(snapshot,list(reversed(refs)))


@pytest.mark.parametrize('fault',['missing','wrong_version','foreign_block','duplicate','empty'])
def test_missing_extra_and_duplicate_never_shrink_truth(universe,fault):
    snapshot,refs = universe
    original = refs[0]
    if fault == 'missing': refs.pop(0)
    elif fault == 'wrong_version': refs[0] = (original[0],'999999',original[2])
    elif fault == 'foreign_block': refs.append((original[0],original[1],'foreign'))
    elif fault == 'duplicate': refs.append(original)
    else: refs = []
    report = audit_index_universe(snapshot,refs)
    assert not report['complete']
    assert report['expected_count'] == sum(len(c.blocks) for c in snapshot.cards)
    if fault in ('missing','wrong_version','empty'): assert list(original) in report['missing']
    if fault == 'wrong_version': assert list(refs[0]) in report['unexpected']
    if fault == 'duplicate': assert report['duplicates']==[dict(reference=list(original),count=2)]


@pytest.mark.asyncio
async def test_channel_collection_stops_on_incomplete_index(universe):
    snapshot,refs = universe
    indexed = [dict(card_id=int(r[0]),card_version_id=int(r[1]),block_id=r[2]) for r in refs[1:]]
    released = []
    class Connection:
        fetch = AsyncMock(side_effect=[[],[],indexed])
        @asynccontextmanager
        async def transaction(self,**kwargs):
            assert kwargs == dict(isolation='repeatable_read',readonly=True)
            yield
    class Pool:
        @asynccontextmanager
        async def acquire(self):
            try: yield Connection()
            finally: released.append(True)
    with patch('app.reg.hybrid.read_current_index',new=AsyncMock(return_value=(snapshot,1,1))), \
         patch('app.reg.hybrid.load_lexicon',new=AsyncMock(return_value=())), \
         patch('app.reg.hybrid.matched_terms',return_value=()):
        with pytest.raises(IndexUniverseMismatch) as exc:
            await search_channels(Pool(),store_id=int(snapshot.store_id),question='검토 질문',
                query_vector=[1.]+[0.]*1535,include_universe=True)
    assert exc.value.audit['missing']==[list(refs[0])]
    assert released==[True]
