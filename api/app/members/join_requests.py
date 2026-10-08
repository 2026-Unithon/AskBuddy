"""알바 합류 요청. 승인 전에는 store_members 행을 만들지 않는다."""
from __future__ import annotations

import asyncpg

from app.notifications.service import create_join_request_notification


class JoinRefused(Exception):
    def __init__(self, code: str, status: int):
        super().__init__(code)
        self.code = code
        self.status = status


def decide_join(*, user_role: str, active_store_id: int | None, invite_store_id: int) -> str:
    """이미 있는 계정이 초대 링크를 열었을 때. 카카오 STAFF_JOIN 도 같은 규칙을 쓴다."""
    if user_role != "STAFF":
        raise JoinRefused("ROLE_CONFLICT", 403)
    if active_store_id == invite_store_id:
        return "ALREADY_MEMBER"
    if active_store_id is not None:
        raise JoinRefused("ALREADY_IN_OTHER_STORE", 409)
    return "REQUEST"


def status_from_rows(latest: dict | None, *, active_member: bool) -> dict:
    """가장 최근 요청과 현재 멤버십으로 알바 화면 상태를 정한다."""
    if latest is None:
        return {"status": "NONE", "store_name": None}
    status = latest["status"]
    if status == "APPROVED" and not active_member:
        status = "REMOVED"
    return {"status": status, "store_name": latest["store_name"]}


async def request_join(db, *, store_id: int, user_id: int, invite_id: int | None,
                       staff_name: str) -> tuple[int, int | None]:
    """(request_id, 새로 만든 점주 알림 id). 이미 기다리는 요청이 있으면 알림 없이 그 id."""
    existing = await db.fetchval(
        """
        select request_id from store_join_requests
        where store_id = $1 and user_id = $2 and status = 'PENDING'
        """,
        store_id, user_id)
    if existing is not None:
        return int(existing), None
    try:
        async with db.transaction():
            request_id = int(await db.fetchval(
                """
                insert into store_join_requests (store_id, user_id, invite_id)
                values ($1, $2, $3) returning request_id
                """,
                store_id, user_id, invite_id))
            notification_id = await create_join_request_notification(
                db, store_id=store_id, request_id=request_id, staff_name=staff_name)
    except asyncpg.UniqueViolationError:
        # 같은 사람이 동시에 두 번 눌렀다. 먼저 생긴 요청을 쓴다
        return int(await db.fetchval(
            """
            select request_id from store_join_requests
            where store_id = $1 and user_id = $2 and status = 'PENDING'
            """,
            store_id, user_id)), None
    return request_id, notification_id


# store-isolation-ok: 매장 소속 전 알바가 자기 요청만 본다(user_id 는 JWT)
async def latest_status(db, *, user_id: int) -> dict:
    latest = await db.fetchrow(
        """
        select r.store_id, r.status, s.store_name
        from store_join_requests r join stores s on s.store_id = r.store_id
        where r.user_id = $1
        order by r.requested_at desc, r.request_id desc limit 1
        """,
        user_id)
    active = False
    if latest is not None:
        active = await db.fetchval(
            """
            select exists(select 1 from store_members
                          where store_id = $1 and user_id = $2 and removed_at is null)
            """,
            latest["store_id"], user_id)
    return status_from_rows(dict(latest) if latest else None, active_member=bool(active))
