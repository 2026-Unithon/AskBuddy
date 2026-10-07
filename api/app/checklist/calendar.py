"""영업일·지금 근무조·본문 줄 — DB 없이 계산한다 (설계 §5)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

_DAY = 24 * 60


def business_date(now_utc: datetime, tz: str, day_starts_at: time) -> date:
    """영업일 시작 시각 이전 새벽은 전날 영업일이다 (C5)."""
    local = now_utc.astimezone(ZoneInfo(tz))
    return (local - timedelta(hours=day_starts_at.hour, minutes=day_starts_at.minute)).date()


def local_time(now_utc: datetime, tz: str) -> time:
    return now_utc.astimezone(ZoneInfo(tz)).time().replace(second=0, microsecond=0)


def split_lines(content: str) -> list[str]:
    """체크 항목 = 공개 본문의 한 줄. 빈 줄은 뺀다 (C8, 웹 NumberedContent 와 같은 규칙)."""
    return [line.strip() for line in content.split("\n") if line.strip()]


@dataclass(frozen=True)
class ShiftWindow:
    shift_id: int
    sort_order: int
    starts_at: time | None
    ends_at: time | None


def _minutes(value: time) -> int:
    return value.hour * 60 + value.minute


def _covers(shift: ShiftWindow, now: time) -> bool:
    if shift.starts_at is None or shift.ends_at is None:
        return False
    start, end, t = _minutes(shift.starts_at), _minutes(shift.ends_at), _minutes(now)
    if start < end:
        return start <= t < end
    # 자정을 넘는 근무조 (ends_at <= starts_at)
    return t >= start or t < end


def pick_current_shift(shifts: list[ShiftWindow], now: time, day_starts_at: time) -> tuple[int | None, bool]:
    """지금 근무조. 맞는 게 없으면 오늘(영업일) 남은 가장 빠른 근무조를 upcoming 으로, 그것도 없으면 첫 근무조."""
    if not shifts:
        return None, False
    ordered = sorted(shifts, key=lambda s: (s.sort_order, s.shift_id))
    for shift in ordered:
        if _covers(shift, now):
            return shift.shift_id, False

    day_start = _minutes(day_starts_at)

    def position(value: time) -> int:
        # 영업일 시작부터 몇 분 지났는지
        return (_minutes(value) - day_start) % _DAY

    later = [s for s in ordered if s.starts_at is not None and position(s.starts_at) > position(now)]
    if later:
        nearest = min(later, key=lambda s: (position(s.starts_at), s.sort_order))  # type: ignore[arg-type]
        return nearest.shift_id, True
    return ordered[0].shift_id, False
