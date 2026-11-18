"""추출 직후 서버 보정 (계획 10). 모델 호출이 아니고, 특정 낱말·메뉴로 분기하지 않는다.

1. 표 칸 모양(`이름=값`, 화살표 없음) 사실에 붙은 절차 번호를 지운다 — 표의 칸은 절차가 아니다.
2. 화살표 통문장(`제조순서=블랜더 → 믹싱 → 토핑`)이 여러 사실에 그대로 반복되고, 각 사실의 값이
   화살표 조각 하나와 같으면 사실마다 그 조각을 보이는 문장으로 쓰고 번호를 조각 순서로 다시 매긴다.
   근거 원문(`original_assertion`)은 그대로 남는다. 값이 조각과 맞지 않으면 손대지 않는다(추측하지 않는다).
"""
from __future__ import annotations

import re

from app.ingest.schemas import ExtractedAssertion

_ARROW = re.compile(r"→|->|⇒|➔")
# '순서 없음' 은 ExtractedAssertion 에서 0 이다(응답 스키마)
NO_ORDER = 0


def _text(f: ExtractedAssertion) -> str:
    return (f.assertion or f.original_assertion or "").strip()


def _is_cell(text: str) -> bool:
    """`이름=값` 모양이고 화살표가 없다(첫 `=` 앞이 비지 않음)."""
    if _ARROW.search(text) or "=" not in text:
        return False
    return bool(text.split("=", 1)[0].strip())


def _pieces(text: str) -> list[str]:
    """화살표 통문장의 조각. 첫 `=` 앞이 이름이면 떼고 나눈다."""
    head, sep, rest = text.partition("=")
    body = rest if sep and head.strip() and not _ARROW.search(head) else text
    return [p.strip() for p in _ARROW.split(body) if p.strip()]


def normalize_extracted(facts: list[ExtractedAssertion]) -> list[ExtractedAssertion]:
    out = list(facts)
    # 1) 표 칸의 절차 번호
    for i, f in enumerate(out):
        if f.order and _is_cell(_text(f)):
            out[i] = f.model_copy(update={"order": NO_ORDER})

    # 2) 반복된 화살표 통문장
    by_text: dict[str, list[int]] = {}
    for i, f in enumerate(out):
        text = _text(f)
        if _ARROW.search(text):
            by_text.setdefault(text, []).append(i)
    for text, idxs in by_text.items():
        if len(idxs) < 2:
            continue
        pieces = _pieces(text)
        slots = []
        for i in idxs:
            value = (out[i].value or "").strip()
            if value not in pieces:
                break
            slots.append((i, pieces.index(value)))
        else:
            for i, slot in slots:
                out[i] = out[i].model_copy(update={"assertion": pieces[slot], "order": slot + 1})
    return out
