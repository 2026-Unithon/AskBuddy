"""/today-tasks — 사장이 보내는 오늘만 할 일. 영업일이 지나면 화면에서 빠진다."""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Annotated, Any
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Path, Response, status

from app.checklist.calendar import business_date
from app.checklist.router import Member, require_member, require_owner_member
from app.checklist.schemas import BIGINT_MAX
from app.deps import Db, get_pool
from app.errors import ApiClaims, ApiError
from app.notifications.service import create_today_task_notification, deliver_notification
from app.today_tasks import repository as repo
from app.today_tasks.polish import polish_text
from app.today_tasks.schemas import DoneRequest, PolishRequest, SeenRequest, TodayTaskCreate
from app.usage import DbUsageSink

router = APIRouter()

TaskId = Annotated[int, Path(ge=1, le=BIGINT_MAX)]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def today_of(member: Member, now_utc: datetime) -> date:
    return business_date(now_utc, member.timezone, member.day_starts_at)


async def _owner(db, claims) -> Member:
    member = await require_member(db, claims)
    require_owner_member(member)
    return member


# store-isolation-ok: require_member 로 JWT·멤버십을 확인한 member.store_id 로만 쓴다
@router.post("", status_code=status.HTTP_201_CREATED)
async def create(body: TodayTaskCreate, db: Db, claims: ApiClaims, background: BackgroundTasks) -> dict[str, Any]:
    member = await _owner(db, claims)
    today = today_of(member, _now())
    send = body.body or body.text
    notification_ids: list[int] = []
    async with db.transaction():
        targets = await repo.active_staff(db, member.store_id, body.member_ids)
        if set(targets) != set(body.member_ids):
            raise ApiError(422, "TARGET_NOT_FOUND", "보낼 수 없는 직원이 있어요. 직원 목록을 새로 불러와 주세요.")
        task_id = await repo.create_task(db, member.store_id, today, send, body.text, member.user_id, body.member_ids)
        for member_id in body.member_ids:
            nid = await create_today_task_notification(db, member.store_id, task_id, targets[member_id], send)
            if nid is not None:
                notification_ids.append(nid)
    # 앱 알림 저장이 끝난 뒤에만 Push 를 요청한다. Push 실패는 지시 저장을 되돌리지 않는다
    for nid in notification_ids:
        background.add_task(deliver_notification, member.store_id, nid)
    tasks = await repo.list_for_owner(db, member.store_id, today)
    created = next(t for t in tasks if t["task_id"] == task_id)
    return {"business_date": today.isoformat(), "task": created}


# store-isolation-ok: require_member 로 확인한 member.store_id 로만 조회한다
@router.get("")
async def list_today(db: Db, claims: ApiClaims) -> dict[str, Any]:
    member = await _owner(db, claims)
    today = today_of(member, _now())
    return {"business_date": today.isoformat(), "items": await repo.list_for_owner(db, member.store_id, today)}


# store-isolation-ok: require_member 로 확인한 member.store_id 로만 조회한다
@router.get("/mine")
async def list_mine(db: Db, claims: ApiClaims) -> dict[str, Any]:
    member = await require_member(db, claims)
    today = today_of(member, _now())
    return {"business_date": today.isoformat(),
            "items": await repo.list_for_member(db, member.store_id, today, member.member_id)}


# store-isolation-ok: require_member 로 확인한 member.store_id 로만 쓴다
@router.post("/polish")
async def polish(body: PolishRequest, db: Db, claims: ApiClaims) -> dict[str, Any]:
    member = await _owner(db, claims)
    text = await polish_text(body.text, store_id=member.store_id, call_id=uuid4().hex,
                             usage_sink=DbUsageSink(get_pool()))
    return {"body": text}


# store-isolation-ok: require_member 로 확인한 member.store_id 로만 쓴다
@router.post("/seen")
async def seen(body: SeenRequest, db: Db, claims: ApiClaims) -> dict[str, Any]:
    member = await require_member(db, claims)
    today = today_of(member, _now())
    count = await repo.mark_seen(db, member.store_id, member.member_id, list(dict.fromkeys(body.task_ids)), today)
    return {"updated": count}


# store-isolation-ok: require_member 로 확인한 member.store_id 로만 쓴다
@router.put("/{task_id}/done")
async def done(task_id: TaskId, body: DoneRequest, db: Db, claims: ApiClaims) -> dict[str, Any]:
    member = await require_member(db, claims)
    today = today_of(member, _now())
    if not await repo.set_done(db, member.store_id, task_id, member.member_id, today, body.done):
        raise ApiError(404, "TASK_NOT_FOUND", "오늘 받은 할 일이 아니에요. 새로 불러와 주세요.")
    return {"task_id": task_id, "done": body.done}


# store-isolation-ok: require_member 로 확인한 member.store_id 로만 쓴다
@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def cancel(task_id: TaskId, db: Db, claims: ApiClaims) -> Response:
    member = await _owner(db, claims)
    if not await repo.cancel_task(db, member.store_id, task_id, today_of(member, _now())):
        raise ApiError(404, "TASK_NOT_FOUND", "오늘 보낸 할 일이 아니에요.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
