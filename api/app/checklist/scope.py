"""범위·묶음·개수 계산과 오늘 응답 조립 (설계 §5·§6). DB 를 모른다."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time
from typing import Any

COMMON_NAME = "공통"


@dataclass(frozen=True)
class Shift:
    shift_id: int
    name: str
    sort_order: int
    starts_at: time | None
    ends_at: time | None


@dataclass(frozen=True)
class ChecklistCard:
    card_id: int
    card_version_id: int
    title: str
    lines: tuple[str, ...]
    common: bool                 # 근무조 연결이 하나도 없으면 공통 단위 (C9)
    shift_ids: frozenset[int]    # 활성 근무조만. 보관 근무조 연결은 빠져 있다


@dataclass(frozen=True)
class Scope:
    all: bool
    shift_ids: tuple[int, ...]   # 범위 안 근무조(활성, 정렬 순서)


def resolve_scope(role: str, active_shift_ids: list[int], member_shift_ids: set[int]) -> Scope:
    """점주·근무조 없는 매장·담당 없는 직원은 전체. 아니면 담당 근무조만 (C3)."""
    assigned = tuple(s for s in active_shift_ids if s in member_shift_ids)
    if role == "OWNER" or not active_shift_ids or not assigned:
        return Scope(True, tuple(active_shift_ids))
    return Scope(False, assigned)


def cards_in_scope(cards: list[ChecklistCard], scope: Scope) -> list[ChecklistCard]:
    allowed = set(scope.shift_ids)
    return [c for c in cards if c.common or (c.shift_ids & allowed)]


def line_keys(cards: list[ChecklistCard]) -> set[tuple[int, int]]:
    """한 카드가 여러 근무조에 있어도 줄은 한 번만 센다."""
    return {(c.card_version_id, n) for c in cards for n in range(1, len(c.lines) + 1)}


def _card_view(card: ChecklistCard, checked: set[tuple[int, int]]) -> dict[str, Any]:
    return {
        "card_id": card.card_id,
        "card_version_id": card.card_version_id,
        "title": card.title,
        "lines": [
            {"line_no": n, "text": text, "checked": (card.card_version_id, n) in checked}
            for n, text in enumerate(card.lines, start=1)
        ],
    }


def _counts(cards: list[ChecklistCard], checked: set[tuple[int, int]]) -> dict[str, int]:
    keys = line_keys(cards)
    return {"total": len(keys), "done": len(keys & checked)}


def _covers(submission: dict[str, Any], shift_id: int) -> bool:
    ids = submission.get("scope_shift_ids")
    # 전체 범위 제출(scope_shift_ids=None)은 근무조를 체크하지 않는다 — 명시된 근무조만
    return ids is not None and shift_id in ids


def build_today(
    *,
    business_date: date,
    previous_business_date: date,
    previous_submitted: bool,
    shifts: list[Shift],
    cards: list[ChecklistCard],
    scope: Scope,
    checked: set[tuple[int, int]],
    selected_shift_id: int | None,
    upcoming: bool,
    include_all: bool,
    submissions: list[dict[str, Any]],
    my_submission: dict[str, Any] | None,
) -> dict[str, Any]:
    """오늘 할 일 응답. 공통 묶음을 항상 맨 앞에, 그 뒤에 고른 근무조(또는 어제 창이면 범위 전체)."""
    by_id = {s.shift_id: s for s in shifts}
    scoped = cards_in_scope(cards, scope)
    common = [c for c in scoped if c.common]

    shift_rows = []
    for shift_id in scope.shift_ids:
        shift = by_id[shift_id]
        own = [c for c in scoped if shift_id in c.shift_ids]
        shift_rows.append({
            "shift_id": shift_id,
            "name": shift.name,
            "starts_at": shift.starts_at.isoformat(timespec="minutes") if shift.starts_at else None,
            "ends_at": shift.ends_at.isoformat(timespec="minutes") if shift.ends_at else None,
            **_counts(own, checked),
            "submitted": any(_covers(s, shift_id) for s in submissions),
        })

    groups: list[dict[str, Any]] = []
    if common:
        groups.append({"shift_id": None, "name": COMMON_NAME, "cards": [_card_view(c, checked) for c in common]})
    visible_shift_ids = list(scope.shift_ids) if include_all else ([selected_shift_id] if selected_shift_id in scope.shift_ids else [])
    view_cards = list(common)
    for shift_id in visible_shift_ids:
        own = [c for c in scoped if shift_id in c.shift_ids]
        if own:
            groups.append({"shift_id": shift_id, "name": by_id[shift_id].name, "cards": [_card_view(c, checked) for c in own]})
        view_cards.extend(own)

    return {
        "business_date": business_date.isoformat(),
        "previous_business_date": previous_business_date.isoformat(),
        "previous_submitted": previous_submitted,
        "scope": {"all": scope.all, "shift_ids": list(scope.shift_ids)},
        "current_shift_id": selected_shift_id if selected_shift_id in scope.shift_ids else None,
        "upcoming": upcoming,
        "shifts": shift_rows,
        "groups": groups,
        "view": _counts(view_cards, checked),
        "scope_counts": _counts(scoped, checked),
        "my_submission": my_submission,
    }
