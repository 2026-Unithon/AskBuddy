"""이름 고치기(계획 7 Task 9). 내 이름은 JWT 의 user_id, 매장 이름은 JWT 의 store_id 로만 바꾼다."""
from __future__ import annotations


async def rename_user(conn, user_id: int, name: str) -> None:
    # store-isolation-ok: 사용자 본인 행(JWT user_id)만 바꾼다
    await conn.execute("update users set name = $2 where user_id = $1", user_id, name)


async def rename_store(conn, store_id: int, store_name: str) -> None:
    await conn.execute("update stores set store_name = $2 where store_id = $1", store_id, store_name)
