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


class RealWorldMissTest(unittest.TestCase):
    """store-b run 9 에서 사람이 검토해 '채점이 틀렸다' 고 판정한 사례들.

    전부 카드에 답이 분명히 있는데 매칭이 놓쳤던 건이다. 다시 틀리면 여기서 걸린다.
    """

    def test_particle_is_stripped(self):
        """b-0035 — 정답지 "한 스푼" vs 카드 "한 스푼을"."""
        fact = {"fact_id": "b-0035", "subject": "배수구", "variant": None,
                "attribute": "약품 투입량", "value": "한 스푼",
                "must_have": True, "source_key": "s"}
        card = _card(1, "커피머신 드립트레이 및 배수구 청소",
                     "배수구 막힘을 예방하기 위해 전용 약품 한 스푼을 넣고 뜨거운 물을 흘려보냅니다.")
        self.assertEqual(match_fact(fact, [card]).verdict, "COVERED")

    def test_verb_ending_is_stripped(self):
        """b-0028 — "처리" vs "처리합니다"."""
        fact = {"fact_id": "b-0028", "subject": "음료 재제조", "variant": None,
                "attribute": "처리주체", "value": "아르바이트 즉시 처리",
                "must_have": False, "source_key": "s"}
        card = _card(1, "고객 음료 재제조 응대 방법",
                     "고객의 음료 재제조 요청은 아르바이트 직원이 즉시 처리합니다.")
        self.assertEqual(match_fact(fact, [card]).verdict, "COVERED")

    def test_single_char_keywords_survive(self):
        """b-0037 — "물"·"샷" 이 한 글자라 버려져 제조순서를 놓쳤다."""
        fact = {"fact_id": "b-0037", "subject": "아메리카노", "variant": "ICE",
                "attribute": "제조순서", "value": "얼음 물 샷 순서",
                "must_have": True, "source_key": "s"}
        card = _card(1, "아이스 아메리카노 제조 순서",
                     "아이스 아메리카노는 얼음, 물, 에스프레소 샷 순서로 컵에 담아 제조한다.")
        self.assertEqual(match_fact(fact, [card]).verdict, "COVERED")

    def test_one_syllable_spelling_drift(self):
        """b-0031 — 정답지 "포터필터" vs 카드 "포타필터"."""
        fact = {"fact_id": "b-0031", "subject": "포터필터", "variant": None,
                "attribute": "침지시간", "value": "30분",
                "must_have": False, "source_key": "s"}
        card = _card(1, "커피머신 추출 부품 세척",
                     "약 30분간 담가둡니다. 포타필터 홈과 가스켓은 미세한 솔로 닦아줍니다.")
        self.assertEqual(match_fact(fact, [card]).verdict, "COVERED")

    def test_card_with_value_beats_card_with_only_subject(self):
        """b-0032 — 대상 이름만 겹치는 카드가 값을 담은 카드를 밀어냈다."""
        fact = {"fact_id": "b-0032", "subject": "포터필터", "variant": None,
                "attribute": "세척제", "value": "중성세제",
                "must_have": False, "source_key": "s"}
        cards = [
            _card(1, "포터필터 마감 분해 청소", "포터필터는 매일 마감 시간에 분해하여 청소합니다."),
            _card(2, "커피머신 추출 부품 세척", "30분 후 중성세제와 흐르는 물로 씻어내며 포타필터 홈을 닦습니다."),
        ]
        m = match_fact(fact, cards)
        self.assertEqual(m.card_id, 2)
        self.assertEqual(m.verdict, "COVERED")

    def test_spelling_drift_does_not_merge_different_menus(self):
        """느슨해진 대신 다른 메뉴끼리 붙으면 안 된다."""
        fact = {"fact_id": "x", "subject": "고구마라떼", "variant": None,
                "attribute": "우유량", "value": "275ml",
                "must_have": False, "source_key": "s"}
        card = _card(1, "곡물라떼", "곡물라떼는 스팀우유 275ml 를 넣습니다.")
        self.assertNotEqual(match_fact(fact, [card]).verdict, "COVERED")

    def test_true_miss_stays_missed(self):
        """b-0016 — 진짜 누락은 고친 뒤에도 누락이어야 한다."""
        fact = {"fact_id": "b-0016", "subject": "냉장고", "variant": None,
                "attribute": "설정온도", "value": "4도 이하",
                "must_have": True, "source_key": "s"}
        card = _card(1, "커피머신 백플러싱 세척",
                     "포타필터를 체결한 후 추출 버튼을 눌러 약 30초간 물을 흘려보냅니다.")
        self.assertNotEqual(match_fact(fact, [card]).verdict, "COVERED")


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
