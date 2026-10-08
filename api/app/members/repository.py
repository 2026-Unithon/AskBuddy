"""직원 목록·승인·거절·내보내기. 모든 쿼리는 store_id 로 좁힌다."""
from __future__ import annotations

from app.notifications.service import create_join_approved_notification


class AlreadyDecided(Exception):
    """이미 승인·거절된 요청이다."""


class OtherStore(Exception):
    """다른 매장의 활성 직원이다."""


class CannotRemoveOwner(Exception):
    """점주 본인은 내보낼 수 없다."""


async def list_members(db, *, store_id: int) -> dict:
    pending = await db.fetch(
        """
        select r.request_id, u.name, r.requested_at
        from store_join_requests r join users u on u.user_id = r.user_id
        where r.store_id = $1 and r.status = 'PENDING'
        order by r.requested_at asc
        """,
        store_id)
    active = await db.fetch(
        """
        select m.user_id, u.name, m.member_role as role, m.joined_at
        from store_members m join users u on u.user_id = m.user_id
        where m.store_id = $1 and m.removed_at is null
        order by m.member_role = 'OWNER' desc, m.joined_at asc
        """,
        store_id)
    return {
        "pending": [{**dict(r), "requested_at": r["requested_at"].isoformat()} for r in pending],
        "active": [{**dict(r), "joined_at": r["joined_at"].isoformat()} for r in active],
    }


async def _decide(db, *, store_id: int, request_id: int, owner_id: int, status: str):
    row = await db.fetchrow(
        """
        select request_id, user_id, status from store_join_requests
        where store_id = $1 and request_id = $2 for update
        """,
        store_id, request_id)
    if row is None:
        raise LookupError(request_id)
    if row["status"] != "PENDING":
        raise AlreadyDecided(request_id)
    await db.execute(
        """
        update store_join_requests
        set status = $3, decided_at = now(), decided_by = $4
        where store_id = $1 and request_id = $2
        """,
        store_id, request_id, status, owner_id)
    return int(row["user_id"])


async def approve(db, *, store_id: int, request_id: int, owner_id: int) -> tuple[int, int | None]:
    async with db.transaction():
        user_id = await _decide(db, store_id=store_id, request_id=request_id,
                                owner_id=owner_id, status="APPROVED")
        # 사용자 행을 잠가 서로 다른 매장의 동시 승인을 직렬화한다.
        # store-isolation-ok: 단일 매장 계약을 확인하는 사용자 소속 경계다.
        await db.fetchval("select user_id from users where user_id = $1 for update", user_id)
        # store-isolation-ok: 승인 대상자의 다른 활성 소속 존재 여부만 확인한다.
        other = await db.fetchval("select store_id from store_members where user_id = $1 and store_id <> $2 and removed_at is null limit 1", user_id, store_id)
        if other is not None:
            raise OtherStore()
        # 내보냈던 직원이 다시 들어오면 같은 행을 되살린다. 학습 기록이 그대로 이어진다
        await db.execute(
            """
            insert into store_members (store_id, user_id, member_role, day_count, progress_rate, is_deployable)
            values ($1, $2, 'STAFF', 0, 0, false)
            on conflict (store_id, user_id)
            do update set removed_at = null, removed_by = null
            """,
            store_id, user_id)
        # 멤버 행이 생긴 뒤라 "수신자는 매장 멤버" FK 를 만족한다
        notification_id = await create_join_approved_notification(
            db, store_id=store_id, request_id=request_id, staff_user_id=user_id)
    return user_id, notification_id


async def reject(db, *, store_id: int, request_id: int, owner_id: int) -> None:
    async with db.transaction():
        await _decide(db, store_id=store_id, request_id=request_id,
                      owner_id=owner_id, status="REJECTED")


async def remove(db, *, store_id: int, user_id: int, owner_id: int) -> None:
    if user_id == owner_id:
        raise CannotRemoveOwner()
    updated = await db.fetchval(
        """
        update store_members set removed_at = now(), removed_by = $3
        where store_id = $1 and user_id = $2 and member_role = 'STAFF' and removed_at is null
        returning member_id
        """,
        store_id, user_id, owner_id)
    if updated is None:
        raise LookupError(user_id)
