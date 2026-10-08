"""초대 링크. 토큰은 추측할 수 없는 128비트 무작위 값이고 화면에는 링크로만 나간다.

점주가 언제든 다시 복사할 수 있어야 해서 토큰을 해시하지 않고 그대로 둔다.
링크가 새더라도 점주 승인이 막는다. 회수는 재생성(revoked_at)으로만 한다.
"""
from __future__ import annotations

import secrets

import asyncpg

from app.config import get_settings


def new_token() -> str:
    return secrets.token_urlsafe(16)


def invite_url(token: str) -> str:
    return f"{get_settings().web_base_url.rstrip('/')}/join/{token}"


async def _create(db, *, store_id: int) -> str:
    # 매장당 활성 링크 unique 인덱스가 동시 생성을 막는다. 충돌하면 이미 생긴 것을 쓴다
    try:
        async with db.transaction():
            return await db.fetchval(
                """
                insert into invite_codes (store_id, code, expires_at)
                values ($1, $2, 'infinity') returning code
                """,
                store_id, new_token())
    except asyncpg.UniqueViolationError:
        existing = await db.fetchval(
            "select code from invite_codes where store_id = $1 and revoked_at is null", store_id)
        if existing is None:
            raise
        return existing


async def get_or_create(db, *, store_id: int) -> str:
    existing = await db.fetchval(
        "select code from invite_codes where store_id = $1 and revoked_at is null", store_id)
    return existing if existing is not None else await _create(db, store_id=store_id)


async def rotate(db, *, store_id: int) -> str:
    async with db.transaction():
        await db.execute("select store_id from stores where store_id = $1 for update", store_id)
        await db.execute(
            "update invite_codes set revoked_at = now() where store_id = $1 and revoked_at is null",
            store_id)
        return await _create(db, store_id=store_id)


# store-isolation-ok: 공개 초대 링크의 토큰으로 매장을 찾는 경계다. 매장명만 밖으로 나간다
async def resolve(db, *, token: str) -> dict | None:
    row = await db.fetchrow(
        """
        select i.invite_id, i.store_id, s.store_name
        from invite_codes i join stores s on s.store_id = i.store_id
        where i.code = $1 and i.revoked_at is null and i.expires_at > now()
        """,
        token)
    return dict(row) if row else None

# store-isolation-ok: 서명 쿠키에 담아 둔 초대 id 를 다시 확인한다
async def resolve_by_id(db, *, invite_id: int | None) -> dict | None:
    if invite_id is None:
        return None
    row = await db.fetchrow(
        """
        select i.invite_id, i.store_id, s.store_name
        from invite_codes i join stores s on s.store_id = i.store_id
        where i.invite_id = $1 and i.revoked_at is null and i.expires_at > now()
        """,
        invite_id)
    return dict(row) if row else None
