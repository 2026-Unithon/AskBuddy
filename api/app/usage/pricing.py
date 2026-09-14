"""관측된 사용량에 요율을 곱한다 (CP-00A).

두 가지를 엄격히 가른다.
  known_cost_usd  요율이 있는 항목만 더한 값. 항상 계산된다
  cost_usd        전부 관측·가격 책정됐을 때만 내는 총액. 하나라도 비면 null

이 구분이 없으면 "토큰을 못 받은 호출" 이 0원으로 합산되어 **총액이 사실보다 싸 보인다.**
그 수치로 D21 통과를 선언하면 거짓이 된다.
"""
from __future__ import annotations

from decimal import Decimal

from app.contracts.usage import PriceStatus, UsageAttempt, UsageStatus
from app.usage.rates import RateCard, load_rate_card

_MILLION = Decimal("1000000")


def price_attempt(
    attempt: UsageAttempt, card: RateCard | None = None
) -> tuple[Decimal | None, Decimal | None, PriceStatus]:
    """(known_cost, cost, price_status).

    `cost` 는 **모든 과금 단위가 관측되고 전부 가격이 있을 때만** 값이 된다.
    """
    card = card or load_rate_card()
    model = attempt.reported_model or attempt.requested_model
    usage = attempt.usage

    if attempt.usage_status == "NOT_BILLABLE":
        return Decimal("0"), Decimal("0"), "PRICED"

    rate = card.model_rate(model)
    known = Decimal("0")
    priced_any = False
    unpriced_any = False

    def add(units: int | Decimal | None, per_1m: Decimal | None) -> None:
        nonlocal known, priced_any, unpriced_any
        if units is None:
            return
        if per_1m is None:
            unpriced_any = True
            return
        known += Decimal(units) / _MILLION * per_1m
        priced_any = True

    add(usage.prompt_tokens, rate["input_per_1m"])
    add(usage.completion_tokens, rate["output_per_1m"])
    add(usage.cached_tokens, rate["cached_input_per_1m"])
    # 사고 토큰은 공급자가 출력으로 과금하는 경우가 많다. 별도 요율이 없으면 출력 요율을 쓴다
    add(usage.thought_tokens, rate["output_per_1m"])

    if usage.billable_units is not None:
        if rate["per_minute"] is not None and usage.billable_unit_name == "minute":
            known += usage.billable_units * rate["per_minute"]
            priced_any = True
        else:
            unpriced_any = True

    if not card.has_model(model):
        return (known if priced_any else None), None, "NO_RATE"
    if unpriced_any or not priced_any:
        return (known if priced_any else None), None, "UNKNOWN_UNITS"

    # 요율이 다 있어도 관측이 불완전하면 총액을 내지 않는다
    if attempt.usage_status != "COMPLETE":
        return known, None, "PRICED"
    return known, known, "PRICED"


def summarize(attempts: list[UsageAttempt]) -> dict:
    """여러 호출의 합계. **관측률을 함께 낸다.**

    총액만 보면 "쌌다" 인지 "못 쟀다" 인지 구분되지 않는다.
    """
    total = len(attempts)
    known_sum = Decimal("0")
    complete = 0
    unknown = 0
    all_priced = True

    for a in attempts:
        known, cost, _ = price_attempt(a)
        if known is not None:
            known_sum += known
        if a.usage_status == "COMPLETE":
            complete += 1
        elif a.usage_status == "UNKNOWN":
            unknown += 1
        if cost is None and a.usage_status != "NOT_BILLABLE":
            all_priced = False

    return {
        "attempt_count": total,
        "complete_count": complete,
        "unknown_count": unknown,
        # 관측률이 1.0 이 아니면 아래 total 은 하한이다
        "observation_rate": round(complete / total, 4) if total else None,
        "known_cost_usd": known_sum,
        # 하나라도 미관측·미가격이면 총액을 주장하지 않는다
        "total_cost_usd": known_sum if (all_priced and total) else None,
    }
