"""작은 자료 호출 줄이기 측정 보고 (Phase B 추가 S5) — 순수 집계·서식.

원가 원장(`ai_usage_attempts`)의 단계별 호출·비용과 입구 판정(`intake_route_decisions`)의
자료별 최신 판정을 받아, 분류 비용 비율·작은 자료 비중·묶음/한 호출/단독 분류 수를 낸다.
DB 조회는 `scripts/intake_cost_report.py` 가 한다. 여기서는 DB 를 치지 않는다.

비용이 0(요율표 미설정·mock)이면 비율은 None 이다. 0 으로 나누거나 0% 로 적지 않는다 —
못 잰 것을 "분류 비용 없음" 으로 읽게 된다. 비용 미관측(`cost_usd` null) 시도가 하나라도
있으면 합계는 하한일 뿐이라 비율도 None 이고, 합계는 "부분(미관측 N건)" 으로 적는다
(원장 규칙 1 — 결측은 0 이 아니다, D21 미관측은 UNKNOWN).
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

def _dec(value: Any) -> Decimal:
    return Decimal(str(value)) if value is not None else Decimal(0)


def _ratio(part: int, whole: int) -> Decimal | None:
    return (Decimal(part) / Decimal(whole)) if whole else None


def summarize(stage_rows: list[dict], source_rows: list[dict]) -> dict:
    """단계별 표·CLASSIFY 비용 비율·작은 자료 수/비율·한 호출·묶음·단독 분류 수."""
    stages = []
    for row in sorted(stage_rows, key=lambda r: r["stage"]):
        stages.append({
            "stage": row["stage"],
            "calls": int(row.get("calls") or 0),
            "cost_usd": _dec(row.get("cost_usd")),
            "known_cost_usd": _dec(row.get("known_cost_usd")),
            "prompt_tokens": int(row.get("prompt_tokens") or 0),
            "completion_tokens": int(row.get("completion_tokens") or 0),
            # 키가 없으면 미관측 0 (예전 행 모양 호환)
            "unknown_cost_calls": int(row.get("unknown_cost_calls") or 0),
        })
    total_cost = sum((s["cost_usd"] for s in stages), Decimal(0))
    classify_cost = sum((s["cost_usd"] for s in stages if s["stage"] == "CLASSIFY"), Decimal(0))
    unknown = sum(s["unknown_cost_calls"] for s in stages)
    # 미관측이 있으면 합계는 하한 — 비율을 내면 거짓 정밀도가 된다
    classify_share = (classify_cost / total_cost) if total_cost and not unknown else None

    n = len(source_rows)
    small = sum(1 for r in source_rows if r.get("complete"))
    single = sum(1 for r in source_rows if r.get("single_call"))
    bundled = sum(1 for r in source_rows if r.get("bundled"))
    # 한 호출도 묶음도 아닌 자료 — 자료 하나만 분류한 경우
    standalone = sum(1 for r in source_rows if not r.get("single_call") and not r.get("bundled"))

    by_normalizer: dict[str, dict[str, int]] = {}
    for r in source_rows:
        slot = by_normalizer.setdefault(r.get("normalizer") or "?", {"sources": 0, "small": 0})
        slot["sources"] += 1
        slot["small"] += 1 if r.get("complete") else 0

    return {
        "stages": stages,
        "total_calls": sum(s["calls"] for s in stages),
        "total_cost_usd": total_cost,
        "classify_cost_usd": classify_cost,
        "classify_cost_share": classify_share,
        "unknown_cost_calls": unknown,
        "sources": n,
        "small": small,
        "small_share": _ratio(small, n),
        "single_call": single,
        "bundled": bundled,
        "standalone": standalone,
        "by_normalizer": dict(sorted(by_normalizer.items())),
    }


def _pct(value: Decimal | None) -> str:
    return "—" if value is None else f"{(value * 100).quantize(Decimal('0.1'))}%"


def render(summary: dict) -> str:
    """마크다운 보고. 비어 있으면 '자료 없음'·'호출 없음' 을 적는다."""
    lines = ["# 입구 호출 보고 (작은 자료 호출 줄이기)", "", "## 단계별 호출·비용 (운영 제품 호출)", ""]
    if summary["stages"]:
        lines += ["| 단계 | 호출 | 비용(USD) | 관측 비용(USD) | 비용 미관측 시도 | prompt 토큰 "
                  "| completion 토큰 |",
                  "|---|---:|---:|---:|---:|---:|---:|"]
        for s in summary["stages"]:
            cost = (f"{s['cost_usd']} (부분)" if s["unknown_cost_calls"] else f"{s['cost_usd']}")
            lines.append(f"| {s['stage']} | {s['calls']} | {cost} | {s['known_cost_usd']} "
                         f"| {s['unknown_cost_calls']} | {s['prompt_tokens']} "
                         f"| {s['completion_tokens']} |")
        unknown = summary.get("unknown_cost_calls", 0)
        total = (f"부분(미관측 {unknown}건) — 관측분 ${summary['total_cost_usd']} 은 하한"
                 if unknown else f"${summary['total_cost_usd']}")
        reason = ("미관측 시도가 있어 내지 않음" if unknown
                  else "비용 미산출 — 요율표·관측 확인")
        lines += ["", f"- 합계 호출 {summary['total_calls']} · 비용 {total}",
                  f"- 분류(CLASSIFY) 비용 비율 {_pct(summary['classify_cost_share'])}"
                  + (f" ({reason})" if summary["classify_cost_share"] is None else "")]
    else:
        lines.append("호출 없음")
    lines += ["", "## 자료별 입구 판정", ""]
    if summary["sources"]:
        lines += [f"- 자료 {summary['sources']} · 작은 자료(훑기가 전체를 담음) {summary['small']} "
                  f"({_pct(summary['small_share'])})",
                  f"- 한 호출 {summary['single_call']} · 묶음 분류 {summary['bundled']} · "
                  f"단독 분류 {summary['standalone']}",
                  "  - 단독 분류 = 한 호출·묶음이 아닌 최신 판정(점주 덮어쓰기·점주 답변 판정 포함)",
                  "",
                  "| 정규화기 | 자료 | 작은 자료 |", "|---|---:|---:|"]
        for name, slot in summary["by_normalizer"].items():
            lines.append(f"| {name} | {slot['sources']} | {slot['small']} |")
    else:
        lines.append("자료 없음")
    return "\n".join(lines) + "\n"
