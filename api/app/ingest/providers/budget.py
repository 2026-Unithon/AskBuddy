"""실행 금액 누적과 상한 (실험용). 상한이 없으면 아무것도 막지 않는다.

요율은 `api/config/rate_card.json`. 요율 없는 모델은 비용을 모른다고 기록할 뿐 0 으로 세지 않는다.
상한에 닿으면 **다음 호출을 부르기 전에** 멈춘다 — 이미 받은 응답은 버리지 않는다.
"""
from decimal import Decimal

from app.usage.rates import load_rate_card


class BudgetExceeded(RuntimeError):
    """금액 상한 도달. 호출부는 그 구역을 실패로 남기고 나머지를 이어간다."""


_LIMIT: Decimal | None = None
_SPENT = Decimal("0")
_UNPRICED: set[str] = set()
_MILLION = Decimal("1000000")


def set_limit(usd: Decimal | None) -> None:
    global _LIMIT, _SPENT
    _LIMIT, _SPENT = usd, Decimal("0")
    _UNPRICED.clear()


def check_before_call() -> None:
    if _LIMIT is not None and _SPENT >= _LIMIT:
        raise BudgetExceeded(f"금액 상한 {_LIMIT} USD 도달 (누적 {_SPENT})")


def add_usage(model: str, usage: dict) -> None:
    global _SPENT
    rate = load_rate_card().model_rate(model)
    if rate["input_per_1m"] is None or rate["output_per_1m"] is None:
        _UNPRICED.add(model)
        return
    out_tokens = int(usage.get("completion_tokens") or 0) + int(usage.get("thought_tokens") or 0)
    _SPENT += (Decimal(int(usage.get("prompt_tokens") or 0)) * rate["input_per_1m"]
               + Decimal(out_tokens) * rate["output_per_1m"]) / _MILLION


def spent() -> Decimal:
    return _SPENT


def unpriced() -> set[str]:
    return set(_UNPRICED)
