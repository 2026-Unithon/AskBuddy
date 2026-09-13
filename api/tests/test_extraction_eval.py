from __future__ import annotations

import unittest

from app.team.extraction import (
    ExtractionReport,
    aggregate,
    match_fact,
    normalize,
    numbers_in,
    variant_present,
)


def _card(card_id: int, title: str, content: str) -> dict:
    return {"card_id": card_id, "title": title, "content": content}


FACT_HOT = {
    "fact_id": "a-0001", "subject": "카페라떼", "variant": "HOT",
    "attribute": "스팀우유량", "value": "275ml", "must_have": True,
    "source_key": "s-recipe",
}
FACT_ICE = {
    "fact_id": "a-0002", "subject": "카페라떼", "variant": "ICE",
    "attribute": "우유량", "value": "225ml", "must_have": True,
    "source_key": "s-recipe",
}


class MatchTest(unittest.TestCase):
    def test_covered_when_subject_value_variant_all_present(self):
        m = match_fact(FACT_HOT, [_card(1, "카페라떼(HOT)", "스팀우유 275ml 를 넣습니다")])
        self.assertEqual(m.verdict, "COVERED")
        self.assertEqual(m.card_id, 1)

    def test_number_distortion_is_not_covered(self):
        """275 를 270 으로 적으면 담긴 것이 아니다."""
        m = match_fact(FACT_HOT, [_card(1, "카페라떼(HOT)", "스팀우유 270ml")])
        self.assertEqual(m.verdict, "PARTIAL")
        self.assertFalse(m.value_hit)

    def test_hot_fact_is_not_covered_by_ice_card(self):
        """규격이 다른 카드가 정답으로 세지면 HOT/ICE 혼동을 못 잡는다."""
        m = match_fact(FACT_HOT, [_card(1, "아이스 카페라떼", "우유 275ml")])
        self.assertNotEqual(m.verdict, "COVERED")

    def test_missing_variant_marker_stays_partial(self):
        """값이 맞아도 규격 표기가 없으면 COVERED 로 올리지 않는다 (과소평가 방향)."""
        m = match_fact(FACT_HOT, [_card(1, "카페라떼", "스팀우유 275ml")])
        self.assertEqual(m.verdict, "PARTIAL")
        self.assertTrue(m.value_hit)
        self.assertFalse(m.variant_hit)

    def test_two_stores_of_same_menu_do_not_cross_match(self):
        m = match_fact(FACT_ICE, [_card(9, "아이스 카페라떼", "우유 225ml 를 넣습니다")])
        self.assertEqual(m.verdict, "COVERED")
        self.assertEqual(m.card_id, 9)

    def test_facts_are_not_stitched_across_cards(self):
        """대상과 값이 서로 다른 카드에 흩어져 있으면 담긴 것이 아니다."""
        cards = [
            _card(1, "카페라떼(HOT)", "우유를 스팀합니다"),   # 대상만
            _card(2, "우유 보관", "275ml 단위로 소분"),        # 값만
        ]
        m = match_fact(FACT_HOT, cards)
        self.assertEqual(m.verdict, "PARTIAL")

    def test_best_card_wins_when_several_partially_match(self):
        cards = [
            _card(1, "카페라떼", "스팀우유를 넣습니다"),
            _card(2, "카페라떼(HOT)", "스팀우유 275ml"),
        ]
        m = match_fact(FACT_HOT, cards)
        self.assertEqual(m.verdict, "COVERED")
        self.assertEqual(m.card_id, 2)

    def test_missing_when_nothing_matches(self):
        m = match_fact(FACT_HOT, [_card(1, "쓰레기 배출", "매일 밤 10시에 버립니다")])
        self.assertEqual(m.verdict, "MISSING")

    def test_no_cards_is_missing_not_crash(self):
        self.assertEqual(match_fact(FACT_HOT, []).verdict, "MISSING")

    def test_prose_value_uses_token_overlap(self):
        fact = {
            "fact_id": "a-0003", "subject": "카페라떼", "variant": None,
            "attribute": "제조순서", "value": "추출 스팀 컵 샷 투입",
            "must_have": False, "source_key": "s-video",
        }
        m = match_fact(fact, [_card(1, "카페라떼 제조", "추출 후 스팀하고 컵에 샷 투입")])
        self.assertEqual(m.verdict, "COVERED")

    def test_all_numbers_must_match_for_multi_number_value(self):
        fact = {
            "fact_id": "a-0005", "subject": "아메리카노", "variant": "HOT",
            "attribute": "온수량", "value": "뜨거운물 8부 (425ml)",
            "must_have": True, "source_key": "s-recipe",
        }
        both = match_fact(fact, [_card(1, "아메리카노(HOT)", "뜨거운물 8부 425ml")])
        self.assertEqual(both.verdict, "COVERED")
        one = match_fact(fact, [_card(1, "아메리카노(HOT)", "뜨거운물 8부까지")])
        self.assertEqual(one.verdict, "PARTIAL")


class HelperTest(unittest.TestCase):
    def test_normalize_drops_punctuation_and_case(self):
        self.assertEqual(normalize("스팀우유 275ml!"), "스팀우유 275ml")

    def test_numbers_ignore_thousands_separator_and_trailing_zero(self):
        self.assertEqual(numbers_in("1,500원 275.0ml"), ["1500", "275"])

    def test_variant_synonyms(self):
        self.assertTrue(variant_present("ICE", "아이스 카페라떼"))
        self.assertTrue(variant_present("HOT", "따뜻한 라떼"))
        self.assertFalse(variant_present("HOT", "아이스 라떼"))

    def test_no_variant_always_passes(self):
        self.assertTrue(variant_present(None, "아무 텍스트"))


class AggregateTest(unittest.TestCase):
    def _report(self) -> list[dict]:
        rep = ExtractionReport()
        cards = [_card(1, "카페라떼(HOT)", "스팀우유 275ml")]
        rep.add(FACT_HOT, match_fact(FACT_HOT, cards), "SCAN")
        rep.add(FACT_ICE, match_fact(FACT_ICE, cards), "SCAN")
        voice = {
            "fact_id": "a-0009", "subject": "마감", "variant": None,
            "attribute": "마감시각", "value": "22시", "must_have": False,
            "source_key": "s-voice",
        }
        rep.add(voice, match_fact(voice, cards), "VOICE")
        return rep.rows

    def test_loss_is_complement_of_recall(self):
        m = aggregate(self._report(), card_count=1)
        self.assertAlmostEqual(m["recall"] + m["loss"], 1.0, places=6)

    def test_source_type_breakdown_is_split(self):
        m = aggregate(self._report(), card_count=1)
        self.assertIn("SCAN", m["by_source_type"])
        self.assertIn("VOICE", m["by_source_type"])
        self.assertEqual(m["by_source_type"]["VOICE"]["fact_count"], 1)

    def test_must_have_misses_are_listed_by_id(self):
        m = aggregate(self._report(), card_count=1)
        self.assertIn("a-0002", m["must_have_missing_ids"])

    def test_empty_report_does_not_divide_by_zero(self):
        self.assertEqual(aggregate([], card_count=0)["fact_count"], 0)


if __name__ == "__main__":
    unittest.main()
