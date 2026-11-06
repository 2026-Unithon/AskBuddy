"""/report — 사장 리포트. 건수만 보인다(완성도·신뢰도 퍼센트는 쓰지 않는다)."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Query

from app.checklist.calendar import business_date
from app.checklist.router import require_member, require_owner_member
from app.deps import Db
from app.errors import ApiClaims, ApiError
from app.report import repository as repo

router = APIRouter()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def business_day_start(day: date, tz: str, day_starts_at: time) -> datetime:
    """영업일 day 가 시작하는 순간(UTC)."""
    return datetime.combine(day, day_starts_at, tzinfo=ZoneInfo(tz)).astimezone(timezone.utc)


def report_window(now_utc: datetime, tz: str, day_starts_at: time, days: int) -> tuple[date, date, datetime, datetime]:
    """오늘 영업일을 포함한 최근 days 영업일. 끝은 지금이다."""
    last = business_date(now_utc, tz, day_starts_at)
    first = last - timedelta(days=days - 1)
    return first, last, business_day_start(first, tz, day_starts_at), now_utc


# store-isolation-ok: require_member 로 JWT·멤버십을 확인한 member.store_id 로만 조회한다
@router.get("/summary")
async def summary(db: Db, claims: ApiClaims, days: int = Query(default=7)) -> dict[str, Any]:
    # 쿼리 문자열 "7" 은 Literal[7, 30] 로 바뀌지 않아 422 가 난다. 정수로 받고 여기서 고른다
    if days not in (7, 30):
        raise ApiError(422, "VALIDATION_ERROR", "기간은 7일 또는 30일만 볼 수 있어요.")
    member = await require_member(db, claims)
    require_owner_member(member)
    first, last, start, end = report_window(_now(), member.timezone, member.day_starts_at, days)
    sid = member.store_id
    return {
        "first_date": first.isoformat(),
        "last_date": last.isoformat(),
        "days": days,
        "questions": await repo.question_counts(db, sid, start, end),
        "top_escalations": await repo.top_escalations(db, sid, start, end),
        # 알바생 기록 공개를 끈 매장은 사람별 표를 주지 않는다(C7-2)
        "per_staff": await repo.per_staff(db, sid, start, end) if member.staff_records_visible else None,
        "checklist": await repo.checklist_counts(db, sid, first, last),
        "today_tasks": await repo.today_task_counts(db, sid, first, last),
    }
