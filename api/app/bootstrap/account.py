"""계정 일(계획 8): 문의·의견 저장, 퇴사, 탈퇴. 순수 DB 함수. 파기는 purge.py(계획 9)."""
from __future__ import annotations

from datetime import datetime, timedelta

import asyncpg

from app.auth.session import revoke_user_sessions
from app.config import get_settings

FEEDBACK_KINDS = ("INQUIRY", "IDEA")
FEEDBACK_MAX = 2000


async def save_feedback(conn: asyncpg.Connection, *, store_id: int, user_id: int, kind: str, body: str) -> int:
    """문의(INQUIRY)·의견(IDEA)을 저장한다. 앞뒤 공백을 지운 글이 비면 ValueError."""
    text = body.strip()
    if kind not in FEEDBACK_KINDS:
        raise ValueError("kind")
    if not text or len(text) > FEEDBACK_MAX:
        raise ValueError("body")
    return int(await conn.fetchval(
        "insert into user_feedback (store_id, user_id, kind, body) values ($1, $2, $3, $4) returning feedback_id",
        store_id, user_id, kind, text))


# ── 퇴사, 탈퇴(계획 8 Task 7) ───────────────────────────────────────────────
# 유예 일수는 config.withdrawal_grace_days 한 곳에만 있다(D22). DB 는 purge_due_at 날짜만 본다

CONFIRM_LEAVE = "퇴사하겠습니다"
CONFIRM_WITHDRAW = "탈퇴하겠습니다"
WITHDRAWN_NAME = "탈퇴한 사용자"


class OwnerCannotLeave(Exception):
    """사장님은 퇴사할 수 없다(회원 탈퇴를 쓴다)."""


class WithdrawalExpired(Exception):
    """취소할 탈퇴 대기가 없다(기한이 지났거나 이미 파기됐다)."""


async def leave_store(conn: asyncpg.Connection, *, store_id: int, user_id: int) -> None:
    """알바생 퇴사: 이 매장 소속만 끝낸다. 계정은 남아 다른 매장에 합류할 수 있다."""
    async with conn.transaction():
        role = await conn.fetchval(
            "select member_role from store_members where store_id = $1 and user_id = $2 and removed_at is null for update",
            store_id, user_id)
        if role is None:
            raise LookupError("membership")
        if role != "STAFF":
            raise OwnerCannotLeave()
        await conn.execute(
            "update store_members set removed_at = now(), removed_by = $2 where store_id = $1 and user_id = $2",
            store_id, user_id)
        await revoke_user_sessions(conn, user_id=user_id)


# store-isolation-ok: 탈퇴는 사용자 단위다. 그 사람의 모든 소속을 끝내고 계정을 비운다
async def withdraw_staff(conn: asyncpg.Connection, *, user_id: int) -> str | None:
    """알바생 탈퇴: 바로 계정을 비운다. 질문 기록은 이름 없이 남는다. 지울 사진 경로를 돌려준다(커밋 뒤 삭제)."""
    async with conn.transaction():
        avatar = await conn.fetchval("select avatar_path from users where user_id = $1 for update", user_id)
        # store-isolation-ok: 탈퇴는 사용자 단위라 그 사람의 모든 매장 소속을 끝낸다
        await conn.execute(
            "update store_members set removed_at = now(), removed_by = $1 where user_id = $1 and removed_at is null",
            user_id)
        # 같은 카카오로 다시 오면 새 계정이 되도록 연결을 끊는다
        await conn.execute("delete from user_identities where user_id = $1", user_id)
        await conn.execute("delete from push_subscriptions where user_id = $1", user_id)
        await revoke_user_sessions(conn, user_id=user_id)
        await conn.execute(
            "update users set name = $2, phone = null, email = null, password_hash = null, avatar_path = null, "
            "deleted_at = now() where user_id = $1",
            user_id, WITHDRAWN_NAME)
    return avatar


async def withdraw_owner(conn: asyncpg.Connection, *, store_id: int, user_id: int, now: datetime) -> datetime:
    """사장님 탈퇴: 매장을 닫고 유예 뒤 파기 날짜를 정한다. 그 매장 모든 사람의 세션을 끊는다. 사용자 행은 그대로."""
    due = now + timedelta(days=get_settings().withdrawal_grace_days)
    async with conn.transaction():
        updated = await conn.fetchval(
            "update stores set closing_at = $3, purge_due_at = $4 "
            "where store_id = $1 and owner_id = $2 and closing_at is null and deleted_at is null returning store_id",
            store_id, user_id, now, due)
        if updated is None:
            raise LookupError("store")
        members = await conn.fetch("select user_id from store_members where store_id = $1", store_id)
        for row in members:
            await revoke_user_sessions(conn, user_id=int(row["user_id"]))
    return due


# store-isolation-ok: 로그인한 사장님 자신의 매장을 owner_id 로 찾는다
async def withdrawal_due(conn: asyncpg.Connection, *, user_id: int) -> datetime | None:
    return await conn.fetchval(
        "select purge_due_at from stores where owner_id = $1 and closing_at is not null and deleted_at is null "
        "order by store_id limit 1",
        user_id)


# store-isolation-ok: 로그인한 사장님 자신의 매장을 owner_id 로 찾는다
async def cancel_withdrawal(conn: asyncpg.Connection, *, user_id: int, now: datetime) -> int:
    """기한 안이면 매장을 다시 연다. 지났으면(또는 이미 파기됐으면) WithdrawalExpired."""
    store_id = await conn.fetchval(
        "update stores set closing_at = null, purge_due_at = null "
        "where owner_id = $1 and closing_at is not null and deleted_at is null and purge_due_at > $2 "
        "returning store_id",
        user_id, now)
    if store_id is None:
        raise WithdrawalExpired()
    return int(store_id)
