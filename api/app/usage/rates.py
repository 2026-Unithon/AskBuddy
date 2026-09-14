"""요율표 (CP-00A). 값은 파일에 두고 코드에 박지 않는다.

요율은 공급자가 바꾸고 우리 계약이 아니다. 코드에 박으면 바뀐 걸 모르고
과거 수치를 새 요율로 다시 계산하게 된다. 실행 시점의 `rate_card_version` 을
receipt 에 남겨 그때 무엇으로 곱했는지 되짚는다.

**요율이 없어도 계측은 돈다.** 토큰을 먼저 쌓고 요율은 나중에 곱한다 —
요금표를 확인하는 동안 측정이 멈추면 안 된다.
"""
from __future__ import annotations

import json
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any

RATES_PATH = Path(__file__).resolve().parents[2] / "config" / "rate_card.json"


class RateCard:
    """한 시점의 요율 묶음. 없는 항목은 None 이고 그러면 비용이 null 로 남는다."""

    def __init__(self, raw: dict[str, Any]) -> None:
        self.version: str = raw.get("version", "unset")
        self.currency: str = raw.get("currency", "USD")
        self.note: str = raw.get("note", "")
        self._models: dict[str, dict] = raw.get("models", {})
        self._storage: dict = raw.get("storage", {})

    def _dec(self, value: Any) -> Decimal | None:
        return None if value is None else Decimal(str(value))

    def model_rate(self, model: str) -> dict[str, Decimal | None]:
        """모델 요율. 단위는 요율표가 명시한다 (per_1m_tokens / per_minute)."""
        entry = self._models.get(model, {})
        return {
            "input_per_1m": self._dec(entry.get("input_per_1m_tokens")),
            "output_per_1m": self._dec(entry.get("output_per_1m_tokens")),
            "cached_input_per_1m": self._dec(entry.get("cached_input_per_1m_tokens")),
            "per_minute": self._dec(entry.get("per_minute")),
        }

    def storage_rate(self) -> dict[str, Decimal | None]:
        return {
            "per_gb_month": self._dec(self._storage.get("per_gb_month")),
            "egress_per_gb": self._dec(self._storage.get("egress_per_gb")),
        }

    def has_model(self, model: str) -> bool:
        return model in self._models


@lru_cache(maxsize=1)
def load_rate_card() -> RateCard:
    if not RATES_PATH.exists():
        return RateCard({"version": "missing", "note": "요율표 파일이 없다"})
    return RateCard(json.loads(RATES_PATH.read_text(encoding="utf-8")))
