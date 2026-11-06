"""Phase B — 결정 규칙(B-D3a 가산·B-D3b 다중·B-D4 가장 가까운 로직). 모델 호출 없음."""
import pytest

from app.ingest.intake import decide
from app.ingest.intake.decide import Ranked, Thresholds
from app.ingest.intake.ir import Candidate, Locator

TH = Thresholds(boost=0.15, multi_label_min=0.35, ambiguous_top_min=0.5, ambiguous_gap_min=0.15)
REG = ("RECIPE",)


def _c(cid, sampled=True):
    return Candidate(cid, Locator("PAGE", cid, cid), "글" if sampled else "", sampled=sampled)


def _r(*pairs):
    return [Ranked(l, s) for l, s in pairs]


def _one(ranking, hints=(), registered=REG):
    return decide.decide_all([_c("c1")], {"c1": _r(*ranking)}, hints=hints, th=TH,
                             registered=registered)[0]


def test_top_logic_wins_even_if_low():
    d = _one([("RECIPE", 0.3), ("POLICY", 0.25)])
    assert d.logic == "RECIPE" and d.ambiguous and d.extractors == ("RECIPE",)


def test_unregistered_falls_back_to_nearest_registered():
    d = _one([("PROCEDURE", 0.8), ("RECIPE", 0.1)])
    assert d.logic == "PROCEDURE" and d.extractors == ("RECIPE",) and d.fallback_unregistered


def test_unregistered_without_registered_in_ranking_uses_first_registered():
    d = _one([("POLICY", 0.9)])
    assert d.extractors == ("RECIPE",) and d.fallback_unregistered


def test_none_has_no_extractor():
    d = _one([("NONE", 0.9), ("RECIPE", 0.05)])
    assert d.logic == "NONE" and d.extractors == ()


def test_notice_keeps_logic_and_one_extractor():
    d = _one([("NOTICE", 0.7), ("POLICY", 0.2)])
    assert d.logic == "NOTICE" and d.extractors == ("RECIPE",)


def test_hint_boost_flips_close_call_and_is_recorded():
    d = _one([("RECIPE", 0.45), ("PROCEDURE", 0.40)], hints=("PROCEDURE",))
    assert d.logic == "PROCEDURE" and d.hint_changed_decision
    assert d.model_ranking[0].logic == "RECIPE"


def test_hint_does_not_beat_clear_content():
    d = _one([("RECIPE", 0.9), ("PROCEDURE", 0.05)], hints=("PROCEDURE",))
    assert d.logic == "RECIPE" and not d.hint_changed_decision


def test_multi_label_two_registered_extractors_dedup():
    reg = ("RECIPE", "POLICY")
    d = _one([("RECIPE", 0.5), ("POLICY", 0.4)], registered=reg)
    assert d.extractors == ("RECIPE", "POLICY")
    d2 = _one([("RECIPE", 0.5), ("PROCEDURE", 0.4)])  # 둘 다 RECIPE 로 풀리면 한 번만
    assert d2.extractors == ("RECIPE",)


def test_notice_never_second_label():
    reg = ("RECIPE",)
    d = _one([("RECIPE", 0.5), ("NOTICE", 0.45)], registered=reg)
    assert d.extractors == ("RECIPE",)


def test_missing_sampled_candidate_raises():
    with pytest.raises(decide.IntakeClassificationError):
        decide.decide_all([_c("c1"), _c("c2")], {"c1": _r(("RECIPE", 0.9))}, hints=(), th=TH,
                          registered=REG)


def test_unsampled_inherits_nearest_sampled_earlier_on_tie():
    cands = [_c("c1"), _c("c2", sampled=False), _c("c3")]
    out = decide.decide_all(cands, {"c1": _r(("RECIPE", 0.9)), "c3": _r(("NONE", 0.9))},
                            hints=(), th=TH, registered=REG)
    assert [d.logic for d in out] == ["RECIPE", "RECIPE", "NONE"]
    assert out[1].inherited_from == "c1"


def test_source_decision_averages_model_scores():
    cands = [_c("c1"), _c("c2")]
    out = decide.decide_all(cands, {"c1": _r(("RECIPE", 0.8), ("NONE", 0.2)),
                                    "c2": _r(("NONE", 0.9), ("RECIPE", 0.1))},
                            hints=(), th=TH, registered=REG)
    src = decide.source_decision(out, hints=(), th=TH, registered=REG)
    assert src.candidate_id == "source" and src.logic == "NONE"  # 평균 NONE 0.55 > RECIPE 0.45


def test_all_none_source_is_none():
    out = decide.decide_all([_c("c1")], {"c1": _r(("NONE", 0.6))}, hints=(), th=TH, registered=REG)
    assert decide.source_decision(out, hints=(), th=TH, registered=REG).logic == "NONE"


def test_round_trip_dict():
    d = _one([("PROCEDURE", 0.8), ("RECIPE", 0.1)])
    assert decide.SectionDecision.from_dict(d.as_dict()) == d
