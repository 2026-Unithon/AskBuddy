"""원가 리포트 (CP-00C) — 등록·운영을 갈라 D21 을 판정한다.

D21 은 **운영 변동비** 월 3,000원이다. 등록비는 1회성이라 별도로 추적하고
예산환산 개월로 본다. 둘을 합치면 어느 매장도 첫 달에 통과하지 못한다.

    I    = 등록 AI 호출비 + 등록 중 과금 전송비
    O_m  = 월 질문 AI + 월 추가자료 AI + 월 저장비 + 월 운영 전송비
    통과  = O_m ≤ 3,000원

**관측이 불완전하면 통과를 선언하지 않는다.** 못 잰 호출을 0으로 합산하면
총액이 사실보다 싸 보이고, 그 수치로 "D21 통과" 를 적게 된다.
"""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

SCENARIOS_PATH = (
    Path(__file__).resolve().parents[3] / "docs" / "dev" / "c0_cost_scenarios.json")

# 판정 결과
PASS = "PASS"
FAIL = "FAIL"
UNDETERMINED = "UNDETERMINED"
"""관측이 불완전해 판정할 수 없다. **통과가 아니다.**"""


def load_scenarios() -> dict[str, Any]:
    return json.loads(SCENARIOS_PATH.read_text(encoding="utf-8"))


def unit_costs(attempts: list[dict[str, Any]]) -> dict[str, Any]:
    """관측된 호출에서 단가를 뽑는다.

    stage 별로 '호출 1회당 얼마' 를 낸다. 시나리오의 질문 수·자료 분량에 곱할 재료다.
    관측률이 1.0 이 아니면 그 단가는 하한이다.
    """
    by_stage: dict[str, dict[str, Any]] = {}
    for a in attempts:
        stage = a["stage"]
        slot = by_stage.setdefault(stage, {
            "count": 0, "observed": 0, "known_cost": Decimal("0"),
            "prompt_tokens": 0, "completion_tokens": 0,
        })
        slot["count"] += 1
        if a.get("usage_status") in ("COMPLETE", "NOT_BILLABLE"):
            slot["observed"] += 1
        if a.get("known_cost_usd") is not None:
            slot["known_cost"] += Decimal(str(a["known_cost_usd"]))
        for key in ("prompt_tokens", "completion_tokens"):
            if a.get(key) is not None:
                slot[key] += int(a[key])

    out = {}
    for stage, slot in by_stage.items():
        n = slot["count"]
        out[stage] = {
            "attempts": n,
            "observation_rate": round(slot["observed"] / n, 4) if n else None,
            "known_cost_usd": slot["known_cost"],
            "cost_per_call_usd": (slot["known_cost"] / n) if n else None,
            "prompt_tokens_per_call": round(slot["prompt_tokens"] / n) if n else None,
            "completion_tokens_per_call": round(slot["completion_tokens"] / n) if n else None,
        }
    return out


def project_operating(
    scenario: dict[str, Any], answer_cost_per_question_usd: Decimal | None,
    storage_cost_usd: Decimal | None, month: int = 1,
    usd_krw: Decimal | None = None,
) -> dict[str, Any]:
    """한 시나리오의 월 운영비를 계산한다.

    첫 달과 안정기의 질문 빈도가 다르다. **평균으로 뭉개면 첫 달을 못 버틴다** —
    신입이 몰리는 달이 가장 비싸고 거기서 D21 이 깨진다.
    """
    employees = int(scenario["employees"])
    days = 30
    rate_key = ("questions_per_employee_day_first_month" if month == 1
                else "questions_per_employee_day_stable")
    per_day = Decimal(str(scenario[rate_key]))
    questions = int(employees * per_day * days)

    answer_cost = (answer_cost_per_question_usd * questions
                   if answer_cost_per_question_usd is not None else None)

    parts = [answer_cost, storage_cost_usd]
    total_usd = None if any(p is None for p in parts) else sum(parts)
    total_krw = (total_usd * usd_krw
                 if total_usd is not None and usd_krw is not None else None)

    return {
        "scenario": scenario["id"],
        "month": month,
        "employees": employees,
        "questions": questions,
        "answer_cost_usd": answer_cost,
        "storage_cost_usd": storage_cost_usd,
        "total_usd": total_usd,
        "total_krw": total_krw,
    }


def judge_d21(total_krw: Decimal | None, budget_krw: Decimal = Decimal("3000")) -> str:
    """D21 판정. **못 재면 통과가 아니라 미정이다.**"""
    if total_krw is None:
        return UNDETERMINED
    return PASS if total_krw <= budget_krw else FAIL


def registration_months(registration_cost_krw: Decimal | None,
                        budget_krw: Decimal = Decimal("3000")) -> Decimal | None:
    """등록비의 예산환산 개월. 손익분기나 실제 회수기간이 아니다."""
    if registration_cost_krw is None:
        return None
    return registration_cost_krw / budget_krw
