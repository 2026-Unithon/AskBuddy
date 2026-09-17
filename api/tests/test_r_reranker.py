import asyncio
import unittest
from pathlib import Path

from app.contracts.snapshot import PublishedKnowledgeSnapshot
from app.contracts.usage import UsageContext
from app.reg.hybrid import Candidate,SearchResult
from app.reg.reranker import Ranking,apply_ranking,candidate_id,rerank
from app.usage.recorder import NullSink


class RerankTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        snapshot=PublishedKnowledgeSnapshot.model_validate_json((Path(__file__).parent/'fixtures/contracts/v1/snapshot.json').read_text(encoding='utf-8'))
        candidates=tuple(Candidate(c.card_id,c.card_version_id,b.block_id,.3,.4,.05) for c in snapshot.cards for b in c.blocks)
        self.search=SearchResult(snapshot,1,candidates,'질문')
        self.kw=dict(store_id=int(snapshot.store_id),question='질문',sink=object(),timeout=.01,
                     context=UsageContext(store_id=snapshot.store_id,stage='RERANK',cost_phase='OPERATING',logical_call_id='rank-test'))

    def test_full_permutation_preserves_original_scores_and_snapshot(self):
        result=apply_ranking(self.search,Ranking(ids=[candidate_id(c) for c in reversed(self.search.candidates)]))
        self.assertEqual(result.candidates,tuple(reversed(self.search.candidates)))
        self.assertIs(result.snapshot,self.search.snapshot)
        self.assertEqual(result.rerank_status,'APPLIED')

    def test_unknown_duplicate_and_missing_ids_rejected(self):
        ids=[candidate_id(c) for c in self.search.candidates]
        for bad in (ids[:-1],['invented',*ids[1:]], [ids[0]]*len(ids)):
            with self.assertRaises(ValueError):apply_ranking(self.search,Ranking(ids=bad))

    async def test_timeout_keeps_original_candidates(self):
        async def slow(*args,**kwargs):await asyncio.sleep(1)
        result=await rerank(self.search,provider=slow,**self.kw)
        self.assertEqual(result.candidates,self.search.candidates)
        self.assertEqual(result.rerank_status,'TIMEOUT')

    async def test_invalid_payload_falls_back_without_second_call(self):
        calls=[]
        async def bad(*args,**kwargs):calls.append(1);return Ranking(ids=['invented'])
        result=await rerank(self.search,provider=bad,**self.kw)
        self.assertEqual(result.rerank_status,'FAILED')
        self.assertEqual(result.candidates,self.search.candidates)
        self.assertEqual(len(calls),1)

    async def test_wrong_store_rejected_before_provider(self):
        self.kw['store_id']=999999
        with self.assertRaises(ValueError):await rerank(self.search,**self.kw)

    async def test_null_sink_rejected_before_provider(self):
        self.kw['sink']=NullSink()
        with self.assertRaises(ValueError):await rerank(self.search,**self.kw)

    async def test_copied_invalid_context_is_revalidated(self):
        self.kw['context']=self.kw['context'].model_copy(update={'attempt_no':0})
        with self.assertRaises(ValueError):await rerank(self.search,**self.kw)
