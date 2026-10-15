"""입구 분류기 평가 하네스(B-D7).

  python scripts/run_intake_classifier_eval.py                      # mock, 비용 0
  python scripts/run_intake_classifier_eval.py --real --confirm-paid  # 유료, 사용자 승인 뒤에만
  python scripts/run_intake_classifier_eval.py --single-call         # 한 호출(분류+추출) 비교용

기본 실행은 DB·네트워크를 만지지 않는다. mock 의 정확도는 모델 성능이 아니다(D10).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DEFAULT_CASES = ROOT / "eval" / "intake" / "cases.json"


class MemorySink:
    """원장 대신 메모리에 영수증을 모은다 — 평가 실행은 DB 를 쓰지 않는다."""

    def __init__(self) -> None:
        self.attempts: list[dict] = []

    async def start(self, attempt) -> int:
        self.attempts.append({"attempt": attempt, "known_cost": None, "cost": None})
        return len(self.attempts) - 1

    async def finalize(self, attempt_id, attempt, known_cost, cost, price_status) -> None:
        self.attempts[attempt_id] = {"attempt": attempt, "known_cost": known_cost,
                                     "cost": cost, "price_status": price_status}

    def rows(self, spans: dict[str, tuple[int, int]] | None = None) -> list[dict]:
        """호출 한 건당 한 행. spans 는 사례별 attempts 구간(시작, 끝)이다."""
        owner = {}
        for cid, (lo, hi) in (spans or {}).items():
            for k in range(lo, hi):
                owner[k] = cid
        out = []
        for k, a in enumerate(self.attempts):
            at = a["attempt"]
            u = at.usage
            out.append({"case_id": owner.get(k, "?"), "model": at.requested_model,
                        "latency_ms": at.latency_ms, "prompt_tokens": u.prompt_tokens,
                        "completion_tokens": u.completion_tokens, "cost": a["cost"],
                        "known_cost": a["known_cost"], "price_status": a.get("price_status")})
        return out


def summarize(rows: list[dict]) -> dict:
    """합계. 총액(cost)과 일부만 매긴 known_cost 를 따로 낸다 — 합치지 않는다."""
    usd = sum((r["cost"] for r in rows if r["cost"] is not None), Decimal(0))
    known = sum((r["known_cost"] for r in rows if r["known_cost"] is not None), Decimal(0))
    return {"calls": len(rows),
            "prompt_tokens": sum(r["prompt_tokens"] or 0 for r in rows),
            "completion_tokens": sum(r["completion_tokens"] or 0 for r in rows),
            "usd": usd, "known_usd": known,
            "unpriced_calls": sum(1 for r in rows if r["cost"] is None),
            "rows": rows}


def build_probe(case: dict):
    from app.ingest.intake.ir import Candidate, Locator, ProbeResult
    return ProbeResult(case["normalizer"], tuple(
        Candidate(c["candidate_id"], Locator(**c["locator"]), c["text"])
        for c in case["candidates"]))


async def run_cases(cases: list[dict], *, sink=None, real: bool = False):
    """(결과, 실패 사례 {case_id: 오류}, 사례별 영수증 구간). 한 사례가 실패해도 이어서 돈다."""
    from app.config import get_settings
    from app.ingest.intake import registry
    from app.ingest.intake.classify import classify
    from app.ingest.intake.decide import Thresholds, decide_all, source_decision

    th = Thresholds.from_settings(get_settings())
    registered = registry.registered_logics()
    out, errors, spans = {}, {}, {}
    for i, case in enumerate(cases, start=1):
        lo = len(sink.attempts) if sink is not None else 0
        try:
            probe = build_probe(case)
            hints = case.get("hints", [])
            ctx = None
            if real:
                from app.ingest import pipeline
                ctx = pipeline._usage_context(1, i, None, "CLASSIFY", "REGISTRATION",
                                              "EVALUATION", None)
            outcome = await classify([probe], hints=hints, context=None,
                                     usage_sink=sink if real else None, usage_context=ctx)
            decisions = decide_all(probe.candidates, outcome.model_sections, hints=hints,
                                   th=th, registered=registered)
            out[case["case_id"]] = {
                "sections": decisions,
                "source": source_decision(decisions, hints=hints, th=th, registered=registered)}
        except Exception as exc:  # 앞선 호출의 비용 기록을 잃지 않으려고 사례 단위로 삼킨다
            errors[case["case_id"]] = f"{type(exc).__name__}: {exc}"
        if sink is not None:
            spans[case["case_id"]] = (lo, len(sink.attempts))
    return out, errors, spans


def split_small_cases(cases: list[dict], *, limit: int) -> tuple[list[dict], list[dict]]:
    """작은 자료 조건 — 후보 글 전체가 limit 자 이하인 사례만 쓴다. (쓴 것, 뺀 것)"""
    used, skipped = [], []
    for c in cases:
        total = sum(len(x["text"]) for x in c["candidates"])
        (used if total <= limit else skipped).append(c)
    return used, skipped


async def run_single_call_cases(cases: list[dict], *, sink=None, real: bool = False):
    """사례마다 후보 글을 이어 붙여 한 호출로 부른다. 순위로 자료 판정을 만들고 모든 구간에 같은 판정을 준다.

    (결과, 실패 사례, 영수증 구간, 사례별 사실 수).
    """
    import dataclasses
    from app.config import get_settings
    from app.ingest import extract
    from app.ingest.extract import mock as _mock  # noqa: F401
    from app.ingest.intake import registry
    from app.ingest.intake.decide import Ranked, Thresholds, _decide

    th = Thresholds.from_settings(get_settings())
    registered = registry.registered_logics()
    out, errors, spans, facts = {}, {}, {}, {}
    for i, case in enumerate(cases, start=1):
        lo = len(sink.attempts) if sink is not None else 0
        try:
            hints = tuple(case.get("hints", []))
            text = "\n\n".join(c["text"] for c in case["candidates"])
            ctx = None
            if real:
                from app.ingest import pipeline
                ctx = pipeline._usage_context(1, i, None, "EXTRACT", "REGISTRATION",
                                              "EVALUATION", None)
            # mock 실행은 설정과 무관하게 mock 구현을 직접 부른다 — 유료 호출이 새지 않게
            fn = (extract.extract_facts_with_intake if real
                  else extract.mock.extract_facts_with_intake)
            res = await fn(
                source_id=i, source_type="doc", text=text, glossary=[], media=None, hints=hints,
                usage_context=ctx, **({"usage_sink": sink} if real else {}))
            ranking = [Ranked(r.logic, r.score) for r in res.intake_ranking]
            src = _decide("source", ranking, hints=hints, th=th, registered=registered)
            out[case["case_id"]] = {
                "sections": [dataclasses.replace(src, candidate_id=c["candidate_id"])
                             for c in case["candidates"]],
                "source": src}
            facts[case["case_id"]] = len(res.assertions)
        except Exception as exc:
            errors[case["case_id"]] = f"{type(exc).__name__}: {exc}"
        if sink is not None:
            spans[case["case_id"]] = (lo, len(sink.attempts))
    return out, errors, spans, facts


def render_report(rep, *, mode: str, model: str, case_count: int, cost: dict | None,
                  errors: dict | None = None, single_call: dict | None = None) -> str:
    lines = [f"# 입구 분류기 평가 ({date.today().isoformat()})", "",
             f"- 실행 모드: {mode}" + ("  (mock 정확도는 모델 성능이 아니다)" if mode == "mock" else ""),
             f"- 분류 모델: {model}", f"- 자료 {rep.source_count}건 · 구간 {rep.section_count}건 (사례 {case_count})",
             f"- 자료 정확도: {rep.source_accuracy:.3f}", f"- 구간 정확도: {rep.section_accuracy:.3f}",
             f"- 모호 비율: {rep.ambiguous_ratio:.3f}"]
    if single_call:
        lines += ["- 방식: 한 호출 (분류와 추출을 합친 호출, 구간 정확도는 모든 구간에 같은 판정)",
                  f"- 작은 사례 {single_call['used']}건 사용 · 제외 {single_call['skipped']}건 "
                  "(전체 글자가 훑기 표본 상한 초과)",
                  f"- 뽑은 사실 수: {sum(single_call['facts'].values())}"]
    lines += ["", "## 로직별 재현율", ""]
    lines += [f"- {k}: {v:.3f}" for k, v in rep.per_logic_recall.items()]
    lines += ["", "## 혼동표 (정답 → 예측)", ""]
    for exp, row in sorted(rep.confusion.items()):
        lines.append(f"- {exp}: " + ", ".join(f"{p} {n}" for p, n in sorted(row.items())))
    lines += ["", "## 비용", ""]
    if cost is None:
        lines.append("- 0원 (mock, 유료 호출 없음)")
    else:
        lines.append(f"- 호출 {cost['calls']}회 · 입력 토큰 {cost['prompt_tokens']} · "
                     f"출력 토큰 {cost['completion_tokens']}")
        lines.append(f"- 총액 USD {cost['usd']} (요율 미적용·일부 관측 호출 {cost['unpriced_calls']}건)")
        lines.append(f"- 알려진 비용(known_cost) USD {cost['known_usd']}")
        lines += ["", "## 호출별", "",
                  "| 사례 | 모델 | 지연(ms) | 입력 | 출력 | 비용 | known | 가격 |",
                  "|---|---|---|---|---|---|---|---|"]
        for r in cost["rows"]:
            lines.append(f"| {r['case_id']} | {r['model']} | {r['latency_ms']} | {r['prompt_tokens']} | "
                         f"{r['completion_tokens']} | {r['cost']} | {r['known_cost']} | {r['price_status']} |")
    if errors:
        lines += ["", "## 실패 사례", ""] + [f"- {k}: {v}" for k, v in errors.items()]
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    ap.add_argument("--real", action="store_true")
    ap.add_argument("--confirm-paid", action="store_true")
    ap.add_argument("--single-call", action="store_true",
                    help="사례 글을 이어 붙여 분류+추출 한 호출로 채점(작은 사례만)")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args(argv)
    if args.real and not args.confirm_paid:
        print("--real 은 유료 호출이다. 사용자 승인 뒤 --confirm-paid 와 함께만 실행한다.",
              file=sys.stderr)
        return 2
    os.environ["INGEST_MODE"] = "real" if args.real else "mock"

    from app.config import get_settings
    from app.ingest.intake import evaluate

    cases = json.loads(args.cases.read_text(encoding="utf-8"))
    sink = MemorySink() if args.real else None
    got, errors, spans = {}, {}, {}
    single = None
    text = ""
    if args.single_call:
        cases, skipped = split_small_cases(cases, limit=get_settings().intake_probe_text_chars)
        single = {"used": len(cases), "skipped": len(skipped), "facts": {}}
    try:
        if args.single_call:
            got, errors, spans, single["facts"] = asyncio.run(
                run_single_call_cases(cases, sink=sink, real=args.real))
        else:
            got, errors, spans = asyncio.run(run_cases(cases, sink=sink, real=args.real))
    finally:
        # 예외가 새도 앞선 호출의 비용 요약과 --out 을 남긴다
        done = [c for c in cases if c["case_id"] in got]
        rep = evaluate.score(done, got)
        cost = summarize(sink.rows(spans)) if sink is not None else None
        text = render_report(rep, mode="real" if args.real else "mock",
                             model=get_settings().intake_classifier_model,
                             case_count=len(cases), cost=cost, errors=errors,
                             single_call=single)
        if args.real and cost["calls"] == 0:
            text += "\n영수증이 기록되지 않았다.\n"
        print(text)
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(text, encoding="utf-8")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
