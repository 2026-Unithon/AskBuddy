"""카드 표시 줄 검사 (D23). 모델이 쓴 줄이 사실에 없는 것을 지어내거나 사실 값을 빠뜨렸는지.

문자열 검사이고 모델 호출이 아니다. 특정 낱말·메뉴·단위 표를 두지 않는다 — 숫자는 정규식으로,
단위는 '숫자 바로 뒤 낱말이 근거 사실 글 어딘가에 있는가' 로만 본다.
"""
from __future__ import annotations

import re
from collections.abc import Sequence
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.ingest.card_plan import PlanFact

LINE_EMPTY = "LINE_EMPTY"
LINE_INVENTED_NUMBER = "LINE_INVENTED_NUMBER"
LINE_INVENTED_UNIT = "LINE_INVENTED_UNIT"
LINE_BARE_VALUE = "LINE_BARE_VALUE"
_WORD = re.compile(r"[가-힣A-Za-z]")

# 분수 → 천 단위 쉼표 → 소수/정수 순으로 본다. 원문자(②)는 \d 에 걸리지 않게 ASCII 숫자만
_NUMBER = re.compile(r"[0-9]+/[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+(?:\.[0-9]+)?|[0-9]+(?:\.[0-9]+)?")
# 숫자 바로 뒤(공백 무시) 낱말 하나: 영문·기호 덩어리 또는 한글 덩어리
_UNIT_AFTER = re.compile(r"\s*([A-Za-z%°℃]+|[가-힣]+)")


def _canon(token: str) -> str:
    token = token.replace(",", "")
    if "." in token and "/" not in token:
        token = token.rstrip("0").rstrip(".")
    return token or "0"


def numbers_in(text: str) -> set[str]:
    """글 안의 숫자 덩어리를 정규화해 모은다(쉼표 제거, 소수 끝 0 제거, 분수 그대로, 범위는 각 끝)."""
    return {_canon(m.group(0)) for m in _NUMBER.finditer(text or "")}


def _number_units(text: str) -> list[tuple[str, str | None]]:
    """(숫자, 바로 뒤 낱말 또는 None)."""
    out: list[tuple[str, str | None]] = []
    for m in _NUMBER.finditer(text or ""):
        after = _UNIT_AFTER.match(text, m.end())
        out.append((_canon(m.group(0)), after.group(1) if after else None))
    return out


def _fact_texts(fact: "PlanFact") -> list[str]:
    texts = [fact.assertion, fact.original_assertion, fact.value_text or "", fact.quantity_unit or ""]
    if fact.quantity_value is not None:
        texts.append(str(fact.quantity_value))
    texts.extend(fact.conditions)
    texts.extend(fact.exceptions)
    return [t for t in texts if t]


def fact_numbers(fact: "PlanFact") -> set[str]:
    nums: set[str] = set()
    for t in _fact_texts(fact):
        nums |= numbers_in(t)
    return nums


def value_numbers(fact: "PlanFact") -> set[str]:
    """빠뜨림 검사가 줄에 꼭 있어야 한다고 보는 숫자: 값 칸(수량·값 글)의 숫자, 없으면 정리 문장의 숫자.

    원문 전체를 보지 않는다 — 표 행 번호처럼 값이 아닌 숫자가 원문에 남는다(2026-11-17 실측).
    """
    nums = numbers_in(fact.value_text or "")
    if fact.quantity_value is not None:
        nums |= numbers_in(str(fact.quantity_value))
    return nums or numbers_in(fact.assertion or fact.original_assertion)


def _unit_grounded(unit: str, pool: str) -> bool:
    if unit.isascii():
        return unit.lower() in pool.lower()
    # 한글 단위 뒤에 조사 한 글자가 붙을 수 있다(래들을·ml를). 낱말 표 없이 끝 한 글자만 떼어 본다
    return unit in pool or (len(unit) > 1 and unit[:-1] in pool)


def _bare_value(text: str) -> bool:
    """숫자와 그 바로 뒤 단위를 지우면 낱말이 남지 않는 줄(무엇의 값인지 없음)."""
    pieces, cursor, found = [], 0, False
    for m in _NUMBER.finditer(text):
        found = True
        pieces.append(text[cursor:m.start()])
        unit = _UNIT_AFTER.match(text, m.end())
        cursor = unit.end() if unit else m.end()
    if not found:
        return False
    rest = "".join(pieces) + text[cursor:]
    return not _WORD.search(rest)


def check_line(text: str, facts: Sequence["PlanFact"]) -> str | None:
    """줄이 근거 사실에 없는 숫자·단위를 쓰면 이유 코드, 문제없으면 None."""
    if not (text or "").strip():
        return LINE_EMPTY
    if _bare_value(text):
        return LINE_BARE_VALUE
    grounded: set[str] = set()
    for f in facts:
        grounded |= fact_numbers(f)
    pool = "\n".join(t for f in facts for t in _fact_texts(f))
    for number, unit in _number_units(text):
        if number not in grounded:
            return LINE_INVENTED_NUMBER
        if unit is not None and not _unit_grounded(unit, pool):
            return LINE_INVENTED_UNIT
    return None


def uncovered_facts(lines: Sequence[tuple[str, Sequence[int]]], facts: Sequence["PlanFact"]) -> list[int]:
    """어느 줄에도 인용되지 않았거나, 인용한 줄들에 그 사실의 숫자가 하나도 없는 사실 판 id(입력 순서).

    D23 은 값(숫자)만 문자열로 본다. 조건·예외는 말투를 바꿔 쓸 수 있어 글자 그대로를 요구하지 않는다
    (요구하면 같은 뜻의 원문 줄이 덧붙어 같은 말이 두 번 나온다 — 2026-11-17 실측)."""
    cited_text: dict[int, list[str]] = {}
    for text, refs in lines:
        for rid in refs:
            cited_text.setdefault(rid, []).append(text)
    out: list[int] = []
    for f in facts:
        texts = cited_text.get(f.fact_revision_id)
        if texts is None:
            out.append(f.fact_revision_id)
            continue
        nums = value_numbers(f)
        if nums and not (nums & set().union(*(numbers_in(t) for t in texts))):
            out.append(f.fact_revision_id)
    return out
