"""/checklist — 근무조 체크리스트 (docs/dev/plan/UI_REBRAND_P5_CHECKLIST.md)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Annotated, Any

import asyncpg
from fastapi import APIRouter, Path, Query, Response, status

from app.checklist import repository as repo
from app.checklist.calendar import ShiftWindow, business_date, local_time, pick_current_shift
from app.checklist.schemas import BIGINT_MAX, CardLinks, CheckRequest, IdList, MySettings, Settings, ShiftCreate, ShiftOrder, ShiftUpdate, SubmissionRequest
from app.checklist.scope import Shift, build_today, cards_in_scope, line_keys, resolve_scope
from app.deps import Db
from app.errors import ApiClaims, ApiError

router = APIRouter()

PathId = Annotated[int, Path(ge=1, le=BIGINT_MAX)]


@dataclass(frozen=True)
class Member:
    store_id: int
    user_id: int
    member_id: int
    role: str
    personal: bool
    timezone: str
    day_starts_at: time
    staff_records_visible: bool


# store-isolation-ok: store_id·user_id 를 JWT 에서 꺼내고 현재 멤버십을 다시 확인하는 경계
async def require_member(db, claims: dict[str, Any]) -> Member:
    store_id, user_id = claims.get("store_id"), claims.get("user_id")
    if store_id is None or user_id is None:
        raise ApiError(403, "STORE_REQUIRED", "먼저 매장에 연결해 주세요.")
    row = await repo.get_member(db, int(store_id), int(user_id))
    if row is None or row["member_role"] != claims.get("role"):
        raise ApiError(403, "MEMBERSHIP_REQUIRED", "이 매장에 접근할 수 없어요.")
    return Member(int(store_id), int(user_id), int(row["member_id"]), row["member_role"],
                  bool(row["personal_records_enabled"]), row["timezone"], row["business_day_starts_at"],
                  bool(row["staff_records_visible"]))


def require_owner_member(member: Member) -> None:
    if member.role != "OWNER":
        raise ApiError(403, "OWNER_ONLY", "사장님만 바꿀 수 있어요.")


def _shift_out(shift: Shift) -> dict[str, Any]:
    return {
        "shift_id": shift.shift_id, "name": shift.name, "sort_order": shift.sort_order,
        "starts_at": shift.starts_at.isoformat(timespec="minutes") if shift.starts_at else None,
        "ends_at": shift.ends_at.isoformat(timespec="minutes") if shift.ends_at else None,
    }


@router.get("/shifts")
async def list_shifts(db: Db, claims: ApiClaims) -> dict[str, Any]:
    member = await require_member(db, claims)
    cards = await repo.shift_card_ids(db, member.store_id)
    return {"items": [{**_shift_out(s), "card_ids": cards.get(s.shift_id, [])}
                      for s in await repo.list_shifts(db, member.store_id)]}


@router.post("/shifts", status_code=status.HTTP_201_CREATED)
async def create_shift(body: ShiftCreate, db: Db, claims: ApiClaims) -> dict[str, Any]:
    member = await require_member(db, claims)
    require_owner_member(member)
    try:
        shift = await repo.create_shift(db, member.store_id, body.name, body.starts_at, body.ends_at)
    except asyncpg.UniqueViolationError as exc:
        raise ApiError(409, "SHIFT_NAME_TAKEN", "같은 이름의 근무조가 있어요.") from exc
    return _shift_out(shift)


@router.patch("/shifts/{shift_id}")
async def update_shift(shift_id: PathId, body: ShiftUpdate, db: Db, claims: ApiClaims) -> dict[str, Any]:
    member = await require_member(db, claims)
    require_owner_member(member)
    set_time = body.clear_time or body.starts_at is not None
    try:
        shift = await repo.update_shift(db, member.store_id, shift_id, body.name,
                                        None if body.clear_time else body.starts_at,
                                        None if body.clear_time else body.ends_at, set_time)
    except asyncpg.UniqueViolationError as exc:
        raise ApiError(409, "SHIFT_NAME_TAKEN", "같은 이름의 근무조가 있어요.") from exc
    if shift is None:
        raise ApiError(404, "SHIFT_NOT_FOUND", "근무조를 찾을 수 없어요.")
    return _shift_out(shift)


@router.delete("/shifts/{shift_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_shift(shift_id: PathId, db: Db, claims: ApiClaims) -> Response:
    member = await require_member(db, claims)
    require_owner_member(member)
    if not await repo.archive_shift(db, member.store_id, shift_id):
        raise ApiError(404, "SHIFT_NOT_FOUND", "근무조를 찾을 수 없어요.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/shifts/order")
async def reorder_shifts(body: ShiftOrder, db: Db, claims: ApiClaims) -> dict[str, Any]:
    member = await require_member(db, claims)
    require_owner_member(member)
    if not await repo.reorder_shifts(db, member.store_id, body.shift_ids):
        raise ApiError(409, "SHIFT_ORDER_STALE", "근무조가 바뀌었어요. 새로 불러온 뒤 다시 정렬해 주세요.")
    return {"items": [_shift_out(s) for s in await repo.list_shifts(db, member.store_id)]}


@router.post("/shifts/preset", status_code=status.HTTP_201_CREATED)
async def create_preset(db: Db, claims: ApiClaims) -> dict[str, Any]:
    member = await require_member(db, claims)
    require_owner_member(member)
    shifts = await repo.create_preset(db, member.store_id)
    if shifts is None:
        raise ApiError(409, "SHIFTS_EXIST", "이미 근무조가 있어요.")
    return {"items": [_shift_out(s) for s in shifts]}


@router.put("/shifts/{shift_id}/cards")
async def set_shift_cards(shift_id: PathId, body: IdList, db: Db, claims: ApiClaims) -> dict[str, Any]:
    member = await require_member(db, claims)
    require_owner_member(member)
    if not await repo.shifts_exist(db, member.store_id, [shift_id]):
        raise ApiError(404, "SHIFT_NOT_FOUND", "근무조를 찾을 수 없어요.")
    if not await repo.card_exists(db, member.store_id, body.ids):
        raise ApiError(404, "CARD_NOT_FOUND", "카드를 찾을 수 없어요.")
    await repo.set_shift_cards(db, member.store_id, shift_id, list(dict.fromkeys(body.ids)))
    return {"shift_id": shift_id, "card_ids": list(dict.fromkeys(body.ids))}


@router.get("/cards/{card_id}")
async def get_card_links(card_id: PathId, db: Db, claims: ApiClaims) -> dict[str, Any]:
    member = await require_member(db, claims)
    require_owner_member(member)
    links = await repo.get_card_links(db, member.store_id, card_id)
    if links is None:
        raise ApiError(404, "CARD_NOT_FOUND", "카드를 찾을 수 없어요.")
    return links


@router.put("/cards/{card_id}")
async def set_card_links(card_id: PathId, body: CardLinks, db: Db, claims: ApiClaims) -> dict[str, Any]:
    member = await require_member(db, claims)
    require_owner_member(member)
    if not await repo.card_exists(db, member.store_id, [card_id]):
        raise ApiError(404, "CARD_NOT_FOUND", "카드를 찾을 수 없어요.")
    if not await repo.shifts_exist(db, member.store_id, body.shift_ids):
        raise ApiError(404, "SHIFT_NOT_FOUND", "근무조를 찾을 수 없어요.")
    await repo.set_card_links(db, member.store_id, card_id, body.checklist, list(dict.fromkeys(body.shift_ids)))
    return await repo.get_card_links(db, member.store_id, card_id)  # type: ignore[return-value]


@router.get("/members")
async def list_members(db: Db, claims: ApiClaims) -> dict[str, Any]:
    member = await require_member(db, claims)
    require_owner_member(member)
    return {"items": await repo.list_members(db, member.store_id)}


@router.put("/members/{member_id}/shifts")
async def set_member_shifts(member_id: PathId, body: IdList, db: Db, claims: ApiClaims) -> dict[str, Any]:
    member = await require_member(db, claims)
    require_owner_member(member)
    if not await repo.shifts_exist(db, member.store_id, body.ids):
        raise ApiError(404, "SHIFT_NOT_FOUND", "근무조를 찾을 수 없어요.")
    if not await repo.set_member_shifts(db, member.store_id, member_id, body.ids):
        raise ApiError(404, "MEMBER_NOT_FOUND", "직원을 찾을 수 없어요.")
    return {"member_id": member_id, "shift_ids": sorted(set(body.ids))}


@router.get("/settings")
# store-isolation-ok: require_member가 JWT 매장으로 읽은 현재 구성원·매장 설정만 반환한다
async def get_settings(db: Db, claims: ApiClaims) -> dict[str, Any]:
    member = await require_member(db, claims)
    require_owner_member(member)
    return {"business_day_starts_at": member.day_starts_at.isoformat(timespec="minutes"),
            "staff_records_visible": member.staff_records_visible, "timezone": member.timezone}


@router.get("/me")
# store-isolation-ok: require_member가 JWT 매장·사용자로 읽은 본인 설정만 반환한다
async def get_me(db: Db, claims: ApiClaims) -> dict[str, Any]:
    member = await require_member(db, claims)
    return {"personal_records_enabled": member.personal}


@router.patch("/settings")
async def update_settings(body: Settings, db: Db, claims: ApiClaims) -> dict[str, Any]:
    member = await require_member(db, claims)
    require_owner_member(member)
    await repo.update_settings(db, member.store_id, body.business_day_starts_at, body.staff_records_visible)
    fresh = await require_member(db, claims)
    return {"business_day_starts_at": fresh.day_starts_at.isoformat(timespec="minutes"),
            "staff_records_visible": fresh.staff_records_visible, "timezone": fresh.timezone}


@router.patch("/me")
async def update_me(body: MySettings, db: Db, claims: ApiClaims) -> dict[str, Any]:
    member = await require_member(db, claims)
    await repo.set_personal_records(db, member.store_id, member.member_id, body.personal_records_enabled)
    return {"personal_records_enabled": body.personal_records_enabled}


def date_policy(today: date, requested: date, previous_submitted: bool, *, allow_late: bool) -> bool:
    """오늘이면 False. 바로 전 영업일이고 아직 제출 안 했고 어제 창 경로면 True(late). 그 밖은 409 (C6)."""
    if requested == today:
        return False
    if allow_late and requested == today - timedelta(days=1) and not previous_submitted:
        return True
    raise ApiError(409, "BUSINESS_DATE_CHANGED", "하루가 바뀌었어요.", details={
        "current_business_date": today.isoformat(),
        "previous_unsubmitted": not previous_submitted,
    })


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _context(db, member: Member, now_utc: datetime):
    today = business_date(now_utc, member.timezone, member.day_starts_at)
    previous = today - timedelta(days=1)
    shifts = await repo.list_shifts(db, member.store_id)
    scope = resolve_scope(member.role, [s.shift_id for s in shifts],
                          await repo.member_shift_ids(db, member.store_id, member.member_id))
    cards = await repo.load_cards(db, member.store_id)
    previous_submitted = await repo.get_submission(db, member.store_id, previous, member.user_id) is not None
    return today, previous, shifts, scope, cards, previous_submitted


async def today_view(db, member: Member, *, now_utc: datetime, selected_shift_id: int | None,
                     requested_date: date | None, include_all: bool) -> dict[str, Any]:
    today, previous, shifts, scope, cards, previous_submitted = await _context(db, member, now_utc)
    target = today
    if requested_date is not None and requested_date != today:
        date_policy(today, requested_date, previous_submitted, allow_late=True)
        target, include_all = requested_date, True
    windows = [ShiftWindow(s.shift_id, s.sort_order, s.starts_at, s.ends_at) for s in shifts if s.shift_id in scope.shift_ids]
    current, upcoming = pick_current_shift(windows, local_time(now_utc, member.timezone), member.day_starts_at)
    if selected_shift_id is not None:
        if selected_shift_id not in scope.shift_ids:
            raise ApiError(404, "SHIFT_NOT_FOUND", "근무조를 찾을 수 없어요.")
        current, upcoming = selected_shift_id, False
    scoped = cards_in_scope(cards, scope)
    checked = await repo.checked_keys(db, member.store_id, target, [c.card_version_id for c in scoped])
    return build_today(
        business_date=target, previous_business_date=previous, previous_submitted=previous_submitted,
        shifts=shifts, cards=cards, scope=scope, checked=checked, selected_shift_id=current, upcoming=upcoming,
        include_all=include_all, submissions=await repo.submissions_on(db, member.store_id, target),
        my_submission=await repo.get_submission(db, member.store_id, target, member.user_id),
    )


# store-isolation-ok: today_view 가 require_member 로 JWT·멤버십 검증한 member.store_id 로만 조회한다
@router.get("/today")
async def get_today(db: Db, claims: ApiClaims,
                    shift_id: int | None = Query(default=None),
                    date_: date | None = Query(default=None, alias="date")) -> dict[str, Any]:
    member = await require_member(db, claims)
    return await today_view(db, member, now_utc=_now(), selected_shift_id=shift_id,
                            requested_date=date_, include_all=False)


def _validate_items(items, allowed: set[tuple[int, int]]) -> list[tuple[int, int, bool]]:
    out = []
    for item in items:
        if (item.card_version_id, item.line_no) not in allowed:
            raise ApiError(409, "CHECK_OUT_OF_SCOPE", "지금 목록에 없는 항목이에요. 새로 불러와 주세요.")
        out.append((item.card_version_id, item.line_no, item.checked))
    return out


@router.put("/checks")
async def put_check(body: CheckRequest, db: Db, claims: ApiClaims) -> dict[str, Any]:
    member = await require_member(db, claims)
    today, previous, _, scope, cards, previous_submitted = await _context(db, member, _now())
    date_policy(today, body.business_date, previous_submitted, allow_late=False)
    items = _validate_items([body], line_keys(cards_in_scope(cards, scope)))
    scoped = cards_in_scope(cards, scope)
    keys = line_keys(scoped)
    async with db.transaction():
        await repo.apply_checks(db, member.store_id, today, member.user_id, items, late=False, personal=member.personal)
        # 범위를 다 체크하면 서버가 제출을 자동 기록한다 (C4). 이미 제출했으면 그대로 둔다
        checked = await repo.checked_keys(db, member.store_id, today, [c.card_version_id for c in scoped])
        submission = await repo.get_submission(db, member.store_id, today, member.user_id)
        if submission is None and keys and keys <= checked:
            submission = await repo.insert_submission(
                db, member.store_id, today, member.user_id, None if scope.all else list(scope.shift_ids),
                len(keys), len(keys & checked), late=False, personal=member.personal,
            )
    return {"business_date": today.isoformat(), "card_version_id": body.card_version_id,
            "line_no": body.line_no, "checked": body.checked, "submitted": submission is not None}


@router.post("/submissions")
async def submit(body: SubmissionRequest, db: Db, claims: ApiClaims) -> dict[str, Any]:
    member = await require_member(db, claims)
    today, previous, _, scope, cards, previous_submitted = await _context(db, member, _now())
    late = date_policy(today, body.business_date, previous_submitted, allow_late=True)
    target = body.business_date
    scoped = cards_in_scope(cards, scope)
    keys = line_keys(scoped)
    items = _validate_items(body.checks, keys)
    async with db.transaction():
        await repo.apply_checks(db, member.store_id, target, member.user_id, items, late=late, personal=member.personal)
        checked = await repo.checked_keys(db, member.store_id, target, [c.card_version_id for c in scoped])
        submission = await repo.insert_submission(
            db, member.store_id, target, member.user_id, None if scope.all else list(scope.shift_ids),
            len(keys), len(keys & checked), late=late, personal=member.personal,
        )
    return {"business_date": target.isoformat(), "submission": submission}


def records_access(viewer: Member, target_user_id: int, target_role: str | None) -> bool:
    """본인은 항상. 직원은 남의 기록 403(존재 여부와 무관). 점주는 매장 설정(알바생 기록)에 따라 (C7-2)."""
    if target_user_id != viewer.user_id and viewer.role != "OWNER":
        raise ApiError(403, "RECORDS_FORBIDDEN", "다른 사람의 기록은 볼 수 없어요.")
    if target_role is None:
        raise ApiError(404, "MEMBER_NOT_FOUND", "직원을 찾을 수 없어요.")
    if target_user_id == viewer.user_id:
        return True
    return viewer.staff_records_visible


def month_range(month: str) -> tuple[date, date]:
    """'YYYY-MM' → (월 첫날, 월 마지막날). 없는 달은 422."""
    try:
        start = date.fromisoformat(month + "-01")
    except ValueError:
        raise ApiError(422, "VALIDATION_ERROR", "월을 다시 확인해 주세요.") from None
    end = (start.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    return start, end


@router.get("/status")
async def get_status(db: Db, claims: ApiClaims) -> dict[str, Any]:
    member = await require_member(db, claims)
    require_owner_member(member)
    now = _now()
    view = await today_view(db, member, now_utc=now, selected_shift_id=None, requested_date=None, include_all=True)
    today = date.fromisoformat(view["business_date"])
    shifts = {s.shift_id: s.name for s in await repo.list_shifts(db, member.store_id)}
    last = await repo.last_submission(db, member.store_id, [today, today - timedelta(days=1)])
    if last is not None:
        ids = last["scope_shift_ids"]
        last.pop("user_id", None)   # 점주 화면은 누가 냈는지 식별하지 않는다 (C7-1)
        last["shift_names"] = [] if ids is None else [shifts[i] for i in ids if i in shifts]
    return {"business_date": view["business_date"], "current_shift_id": view["current_shift_id"],
            "shifts": view["shifts"], "scope_counts": view["scope_counts"], "last_submission": last}


async def _target(db, member: Member, user_id: int | None) -> tuple[int, bool, bool]:
    target_id = user_id if user_id is not None else member.user_id
    row = await repo.member_by_user(db, member.store_id, target_id)
    visible = records_access(member, target_id, row["member_role"] if row else None)
    return target_id, visible, bool(row["personal_records_enabled"]) if row else False


@router.get("/records")
async def get_records(db: Db, claims: ApiClaims, month: str = Query(pattern=r"^\d{4}-\d{2}$"),
                      user_id: int | None = Query(default=None)) -> dict[str, Any]:
    member = await require_member(db, claims)
    target_id, visible, recording = await _target(db, member, user_id)
    start, end = month_range(month)
    days = await repo.record_days(db, member.store_id, target_id, start, end) if visible else []
    return {"user_id": target_id, "month": month, "visible": visible,
            "recording": recording if visible else False, "days": days}


@router.get("/records/{day}")
async def get_record_day(day: date, db: Db, claims: ApiClaims,
                         user_id: int | None = Query(default=None)) -> dict[str, Any]:
    member = await require_member(db, claims)
    target_id, visible, _ = await _target(db, member, user_id)
    if not visible:
        return {"user_id": target_id, "date": day.isoformat(), "visible": False, "lines": [], "submission": None}
    return {"user_id": target_id, "visible": True, **await repo.record_day(db, member.store_id, target_id, day)}
