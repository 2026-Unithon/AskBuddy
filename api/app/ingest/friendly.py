"""사람이 읽기 좋은 사실 문장(2026-11-08 사용자 결정: '원문 그대로' 규칙 제거).

원문(original_assertion)은 근거로 그대로 남기고, 보이는 문장(assertion)은 모델이 정리한 글을 쓴다.
단 지어내기를 막으려고 기계적으로 검사한다: 정리한 글의 숫자는 모두 원문에 있어야 하고, 사실의 값 숫자는
정리한 글에 남아 있어야 한다. 못 지키면 원문을 쓴다. 모델에게 '지어내지 마'라고만 하지 않는다.
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

MAX_LEN = 300
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _numbers(text: str) -> set[Decimal]:
    found: set[Decimal] = set()
    for token in _NUMBER.findall(text or ""):
        try:
            found.add(Decimal(token.replace(",", "")))
        except InvalidOperation:
            continue
    return found


def friendly_assertion(friendly: str | None, original: str, *, value: str | None, unit: str | None) -> str:
    """보이는 문장. 정리한 글이 검사를 통과하면 그 글, 아니면 원문."""
    text = (friendly or "").strip()
    if not text or len(text) > MAX_LEN:
        return original
    if not _numbers(text) <= _numbers(original):
        return original  # 원문에 없는 숫자를 만들었다
    if not _numbers(value or "") <= _numbers(text):
        return original  # 사실의 값이 빠졌다
    return text
