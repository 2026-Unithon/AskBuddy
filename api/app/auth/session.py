"""제품 세션 — 90일 슬라이딩 refresh token (이슈 #37).

원문은 httpOnly 쿠키에만 있고 DB 에는 SHA-256 만 둔다. 쓸 때마다 새 토큰으로 바꾼다.
이미 바뀐 토큰이 유예 시간 뒤에 다시 오면 탈취로 보고 그 계열(family) 전체를 폐기한다.
유예 시간 안의 재사용은 여러 탭이 동시에 갱신한 경우라 401 만 돌려준다.
"""
from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import Request, Response

from app.config import get_settings
from app.deps import create_token
from app.errors import ApiError

REFRESH_COOKIE = "ab_refresh"
COOKIE_PATH = "/auth"
REUSE_GRACE_SECONDS = 30


class RefreshRejected(Exception):
    """refresh 토큰을 받아줄 수 없다. 사유는 응답에 드러내지 않는다."""


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


# store-isolation-ok: 세션은 사용자 단위다. 매장 범위는 access token 발급 때 정한다
async def issue_refresh(db, *, user_id: int, family_id: uuid.UUID | None = None) -> tuple[str, int]:
    raw = secrets.token_urlsafe(32)
    expires_at = _now() + timedelta(days=get_settings().refresh_token_expire_days)
    async with db.transaction():
        await db.execute("select user_id from users where user_id = $1 for update", user_id)
        token_id = await db.fetchval(
            """
            insert into auth_refresh_tokens (user_id, token_hash, family_id, expires_at)
            values ($1, $2, $3, $4) returning token_id
            """,
            user_id, _hash(raw), family_id or uuid.uuid4(), expires_at)
    return raw, int(token_id)


# store-isolation-ok: 세션은 사용자 단위다
async def rotate_refresh(db, *, raw: str) -> tuple[int, str]:
    async with db.transaction():
        identity = await db.fetchrow(
            "select user_id from auth_refresh_tokens where token_hash = $1", _hash(raw))
        if identity is None:
            raise RefreshRejected()
        await db.execute("select user_id from users where user_id = $1 for update", identity["user_id"])
        row = await db.fetchrow(
            """
            select token_id, user_id, family_id, expires_at, revoked_at
            from auth_refresh_tokens where token_hash = $1 for update
            """,
            _hash(raw))
        if row is None or row["expires_at"] <= _now():
            raise RefreshRejected()
        if row["revoked_at"] is not None:
            if _now() - row["revoked_at"] > timedelta(seconds=REUSE_GRACE_SECONDS):
                await _revoke_family(db, row["family_id"])
        else:
            new_raw, new_id = await issue_refresh(
                db, user_id=int(row["user_id"]), family_id=row["family_id"])
            await db.execute(
                """
                update auth_refresh_tokens
                set revoked_at = now(), last_used_at = now(), replaced_by = $2
                where token_id = $1
                """,
                row["token_id"], new_id)
            return int(row["user_id"]), new_raw
    # 폐기를 커밋한 뒤 거절해야 변경이 되돌아가지 않는다.
    raise RefreshRejected()


async def _revoke_family(db, family_id) -> None:
    # store-isolation-ok: 세션 계열 폐기는 사용자 단위다
    await db.execute(
        "update auth_refresh_tokens set revoked_at = now() where family_id = $1 and revoked_at is null",
        family_id)


# store-isolation-ok: 로그아웃은 사용자 단위다
async def revoke_family_of(db, *, raw: str) -> None:
    async with db.transaction():
        row = await db.fetchrow(
            "select user_id, family_id from auth_refresh_tokens where token_hash = $1", _hash(raw))
        if row is not None:
            await db.execute("select user_id from users where user_id = $1 for update", row["user_id"])
            await _revoke_family(db, row["family_id"])


# store-isolation-ok: 내보내기 때 그 사용자의 모든 기기를 끊는다
async def revoke_user_sessions(db, *, user_id: int) -> None:
    async with db.transaction():
        await db.execute("select user_id from users where user_id = $1 for update", user_id)
        await db.execute(
            "update auth_refresh_tokens set revoked_at = now() where user_id = $1 and revoked_at is null",
            user_id)


# store-isolation-ok: 로그인 시점에 이 사용자의 현재 매장을 찾는 경계다
async def active_store_id(db, *, user_id: int) -> int | None:
    value = await db.fetchval(
        """
        select store_id from store_members
        where user_id = $1 and removed_at is null
        order by member_id limit 1
        """,
        user_id)
    return int(value) if value is not None else None


def create_access_token(*, user_id: int, role: str | None, store_id: int | None) -> str:
    payload: dict = {
        "user_id": user_id,
        "exp": _now() + timedelta(minutes=get_settings().access_token_expire_minutes),
    }
    if role is not None:
        payload["role"] = role
    if store_id is not None:
        payload["store_id"] = store_id
    return create_token(payload)


# store-isolation-ok: 매장은 서버가 활성 멤버십에서 정한다. 요청값을 받지 않는다
async def session_payload(db, *, user_id: int) -> dict:
    user = await db.fetchrow("select user_id, name, role from users where user_id = $1", user_id)
    if user is None or user["role"] not in (None, "OWNER", "STAFF"):
        raise RefreshRejected()
    store_id = await active_store_id(db, user_id=user_id)
    out_user = {"user_id": int(user["user_id"]), "name": user["name"], "role": user["role"]}
    if store_id is not None:
        out_user["store_id"] = store_id
    return {
        "token": create_access_token(user_id=user_id, role=user["role"], store_id=store_id),
        "user": out_user,
    }


def set_refresh_cookie(response: Response, raw: str) -> None:
    s = get_settings()
    response.set_cookie(
        REFRESH_COOKIE, raw, max_age=s.refresh_token_expire_days * 86400,
        path=COOKIE_PATH, httponly=True, secure=s.auth_cookie_secure, samesite="lax")


def clear_refresh_cookie(response: Response) -> None:
    s = get_settings()
    response.delete_cookie(
        REFRESH_COOKIE, path=COOKIE_PATH, httponly=True,
        secure=s.auth_cookie_secure, samesite="lax")


def require_allowed_origin(request: Request) -> None:
    """쿠키로 인증하는 엔드포인트의 CSRF 방어. SameSite=Lax 에 더해 Origin 을 확인한다."""
    origin = request.headers.get("origin")
    if origin is None or origin not in get_settings().origins:
        raise ApiError(403, "ORIGIN_FORBIDDEN", "허용되지 않은 요청입니다.")
