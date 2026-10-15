"""Phase B B-D7 — 평가 지표 계산과 하네스 안전장치. 유료 호출 0."""
import json
import os
import subprocess
import sys
from pathlib import Path

from app.ingest.intake import evaluate
from app.ingest.intake.decide import Ranked, SectionDecision

ROOT = Path(__file__).resolve().parents[1]


def _d(cid, logic, amb=False):
    r = (Ranked(logic, 0.9),)
    return SectionDecision(cid, logic, (), amb, False, False, None, r, r)


def test_score_section_and_source_accuracy_and_confusion():
    cases = [{"case_id": "a", "candidates": [{"candidate_id": "c1", "expected": "RECIPE"},
                                             {"candidate_id": "c2", "expected": "NONE"}]}]
    got = {"a": {"sections": [_d("c1", "RECIPE"), _d("c2", "RECIPE", amb=True)],
                 "source": _d("source", "RECIPE")}}
    rep = evaluate.score(cases, got)
    assert rep.section_accuracy == 0.5 and rep.source_accuracy == 1.0
    assert rep.confusion["NONE"]["RECIPE"] == 1 and rep.ambiguous_ratio == 0.5


def test_label_set_covers_every_normalizer_and_card_logic():
    cases = json.loads((ROOT / "eval/intake/cases.json").read_text(encoding="utf-8"))
    assert {c["normalizer"] for c in cases} == {"DOC_TEXT", "DOC_IMAGE", "AUDIO", "VIDEO", "CHAT", "OWNER_TEXT"}
    labels = {x["expected"] for c in cases for x in c["candidates"]}
    assert labels == {"RECIPE", "PROCEDURE", "POLICY", "REFERENCE", "NOTICE", "NONE"}
    assert sum(1 for c in cases if len({x["expected"] for x in c["candidates"]}) > 1) >= 3


def test_real_requires_confirm():
    res = subprocess.run([sys.executable, "scripts/run_intake_classifier_eval.py", "--real"],
                         cwd=ROOT, capture_output=True, text=True)
    assert res.returncode != 0 and "--confirm-paid" in res.stderr


def test_mock_run_completes_without_cost(tmp_path):
    out = tmp_path / "eval.md"
    res = subprocess.run([sys.executable, "scripts/run_intake_classifier_eval.py", "--out", str(out)],
                         cwd=ROOT, capture_output=True, text=True,
                         env={**os.environ, "INGEST_MODE": "mock"})
    assert res.returncode == 0, res.stderr
    text = out.read_text(encoding="utf-8")
    assert "mock" in text and "0원" in text
    assert "사례 10" in text and "구간 18건" in text


def _load_script():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "run_intake_eval", ROOT / "scripts/run_intake_classifier_eval.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_summary_rows_known_cost_and_failed_case_still_reports():
    import asyncio
    from decimal import Decimal
    from types import SimpleNamespace as NS
    mod = _load_script()
    sink = mod.MemorySink()

    def att(lat, p, c):
        return NS(requested_model="m", latency_ms=lat, usage=NS(prompt_tokens=p, completion_tokens=c))
    sink.attempts = [
        {"attempt": att(120, 10, 5), "cost": Decimal("0.5"), "known_cost": Decimal("0.5"),
         "price_status": "PRICED"},
        {"attempt": att(80, 7, None), "cost": None, "known_cost": Decimal("0.25"),
         "price_status": "NO_RATE"},
    ]
    rows = sink.rows({"a": (0, 1), "b": (1, 2)})
    assert [r["case_id"] for r in rows] == ["a", "b"] and rows[0]["latency_ms"] == 120
    s = mod.summarize(rows)
    assert s["usd"] == Decimal("0.5") and s["known_usd"] == Decimal("0.75")
    assert s["prompt_tokens"] == 17 and s["completion_tokens"] == 5 and s["unpriced_calls"] == 1

    # 실패한 사례가 있어도 run_cases 는 예외를 올리지 않고 오류 행으로 남긴다
    case = {"case_id": "bad", "normalizer": "DOC_TEXT", "hints": [],
            "candidates": [{"candidate_id": "c1", "locator": {"kind": "BAD"},
                            "text": "x", "expected": "NONE"}]}
    got, errors, spans = asyncio.run(mod.run_cases([case]))
    assert "bad" in errors and got == {}
    rep = evaluate.score([], got)
    text = mod.render_report(rep, mode="real", model="m", case_count=1, cost=s, errors=errors)
    assert "실패 사례" in text and "지연(ms)" in text and "known_cost" in text


def test_single_call_mock_run_uses_only_small_cases(tmp_path):
    out = tmp_path / "eval.md"
    res = subprocess.run([sys.executable, "scripts/run_intake_classifier_eval.py", "--single-call",
                          "--out", str(out)], cwd=ROOT, capture_output=True, text=True,
                         env={**os.environ, "INGEST_MODE": "mock"})
    assert res.returncode == 0, res.stderr
    text = out.read_text(encoding="utf-8")
    assert "한 호출" in text and "0원" in text and "작은 사례" in text


def test_single_call_filters_big_cases_and_gives_same_verdict_to_every_section():
    import asyncio
    mod = _load_script()
    small = {"case_id": "s", "normalizer": "DOC_TEXT", "hints": ["POLICY"],
             "candidates": [{"candidate_id": "c1", "locator": {"kind": "PAGE", "page": 1},
                             "text": "짧은 글", "expected": "POLICY"},
                            {"candidate_id": "c2", "locator": {"kind": "PAGE", "page": 2},
                             "text": "또 짧은 글", "expected": "NONE"}]}
    big = {"case_id": "b", "normalizer": "DOC_TEXT", "hints": [],
           "candidates": [{"candidate_id": "c1", "locator": {"kind": "PAGE", "page": 1},
                           "text": "가" * 5000, "expected": "RECIPE"}]}
    used, skipped = mod.split_small_cases([small, big], limit=3000)
    assert [c["case_id"] for c in used] == ["s"] and [c["case_id"] for c in skipped] == ["b"]
    got, errors, spans, facts = asyncio.run(mod.run_single_call_cases(used))
    assert not errors and facts["s"] >= 0
    secs = got["s"]["sections"]
    assert {d.logic for d in secs} == {got["s"]["source"].logic} == {"POLICY"}
    assert [d.candidate_id for d in secs] == ["c1", "c2"]
    rep = evaluate.score(used, got)
    text = mod.render_report(rep, mode="mock", model="m", case_count=1, cost=None,
                             single_call={"used": 1, "skipped": 1, "facts": facts})
    assert "한 호출" in text and "작은 사례 1건" in text and "제외 1건" in text
