"""Phase B 추가 S5 — 작은 자료·묶음·한 호출 측정 보고(순수)."""
from decimal import Decimal

from app.usage import intake_report


def test_summarize_shares_and_counts():
    stages = [
        {"stage": "CLASSIFY", "calls": 2, "cost_usd": Decimal("0.002"),
         "known_cost_usd": Decimal("0.002"), "prompt_tokens": 2000, "completion_tokens": 100},
        {"stage": "EXTRACT", "calls": 4, "cost_usd": Decimal("0.018"),
         "known_cost_usd": Decimal("0.018"), "prompt_tokens": 9000, "completion_tokens": 900},
    ]
    sources = [
        {"source_id": 1, "normalizer": "DOC_TEXT", "chars": 120, "images": 0, "complete": True,
         "single_call": True, "bundled": False},
        {"source_id": 2, "normalizer": "DOC_TEXT", "chars": 3000, "images": 0, "complete": False,
         "single_call": False, "bundled": True},
        {"source_id": 3, "normalizer": "DOC_IMAGE", "chars": 0, "images": 1, "complete": True,
         "single_call": False, "bundled": True},
        {"source_id": 4, "normalizer": "AUDIO", "chars": 300, "images": 0, "complete": False,
         "single_call": False, "bundled": False},
    ]
    s = intake_report.summarize(stages, sources)
    assert s["classify_cost_share"] == Decimal("0.1")
    assert (s["sources"], s["small"], s["single_call"], s["bundled"], s["standalone"]) == (4, 2, 1, 2, 1)


def test_render_mentions_sections_and_no_data():
    text = intake_report.render(intake_report.summarize([], []))
    assert "단계별" in text and "자료 없음" in text


def test_zero_cost_does_not_divide_by_zero():
    s = intake_report.summarize([{"stage": "EXTRACT", "calls": 1, "cost_usd": Decimal(0),
                                  "known_cost_usd": Decimal(0), "prompt_tokens": 0,
                                  "completion_tokens": 0}], [])
    assert s["classify_cost_share"] is None


def test_unknown_cost_attempts_make_share_none_and_render_says_unobserved():
    # 비용 미관측(cost_usd null) 시도가 있으면 합계는 하한일 뿐 — 비율을 내지 않는다(D21)
    stages = [
        {"stage": "CLASSIFY", "calls": 1, "cost_usd": Decimal("0.002"),
         "known_cost_usd": Decimal("0.002"), "prompt_tokens": 10, "completion_tokens": 1,
         "unknown_cost_calls": 0},
        {"stage": "EXTRACT", "calls": 2, "cost_usd": Decimal("0.018"),
         "known_cost_usd": Decimal("0.018"), "prompt_tokens": 10, "completion_tokens": 1,
         "unknown_cost_calls": 1},
    ]
    s = intake_report.summarize(stages, [])
    assert s["classify_cost_share"] is None
    assert s["unknown_cost_calls"] == 1
    text = intake_report.render(s)
    assert "미관측" in text and "부분(미관측 1건)" in text
