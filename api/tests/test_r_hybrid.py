import unittest
from app.reg.hybrid import fuse,normalize_query,lexical_query


class HybridTest(unittest.TestCase):
    def test_korean_question_tokens_are_recall_only_or_terms(self):
        self.assertIn('"물은" OR "물"',lexical_query('HOT 라테 물은 225ml인가요?'))
        self.assertIn('"225"',lexical_query('225ml'))
        self.assertEqual(lexical_query('OR -ICE'), '"or" OR "ice"')
    def row(self,cid,score):
        return dict(card_id=cid,card_version_id=cid+100,block_id="b",score=score)

    def test_lexical_only_candidate_has_no_vector_floor(self):
        rows = fuse([self.row(1,1)],[self.row(2,.9)],limit=10)
        self.assertEqual({r.card_id for r in rows},{"1","2"})
        self.assertIsNone(rows[0].vector_score)
        self.assertLess(rows[0].rrf_score,.1)

    def test_scores_remain_separate_and_common_candidate_gains_rank(self):
        rows = fuse([self.row(1,.3),self.row(2,.1)],[self.row(2,.9)],limit=2)
        self.assertEqual(rows[0].card_id,"2")
        self.assertEqual((rows[0].lexical_score,rows[0].vector_score),(.1,.9))

    def test_duplicate_and_nan_are_invalid(self):
        with self.assertRaises(ValueError):
            fuse([self.row(1,1),self.row(1,1)],[],limit=2)
        with self.assertRaises(ValueError):
            fuse([],[self.row(1,float("nan"))],limit=2)

    def test_normalization_is_search_only_and_keeps_units(self):
        self.assertEqual(normalize_query("  ＨＯＴ   ２２５ml \n"),"hot 225ml")
