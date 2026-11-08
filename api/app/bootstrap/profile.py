"""이름 고치기(계획 7 Task 9)와 프로필 사진(2026-11-08). 내 것은 JWT 의 user_id, 매장 이름은 JWT 의 store_id 로만 바꾼다."""
from __future__ import annotations

import re
import uuid

from app.config import get_settings

AVATAR_TYPES = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}


async def rename_user(conn, user_id: int, name: str) -> None:
    # store-isolation-ok: 사용자 본인 행(JWT user_id)만 바꾼다
    await conn.execute("update users set name = $2 where user_id = $1", user_id, name)


async def rename_store(conn, store_id: int, store_name: str) -> None:
    await conn.execute("update stores set store_name = $2 where store_id = $1", store_id, store_name)


def avatar_object_path(store_id: int, user_id: int, content_type: str) -> str:
    """올릴 사진 경로. 원본 파일명은 쓰지 않는다(sources 와 같은 이유)."""
    ext = AVATAR_TYPES.get(content_type)
    if ext is None:
        raise ValueError("사진은 JPG·PNG·WEBP 만 올릴 수 있어요.")
    return f"{get_settings().avatar_bucket}/{store_id}/{user_id}/{uuid.uuid4().hex}.{ext}"


def owns_avatar_path(path: str, *, store_id: int, user_id: int) -> bool:
    """이 경로가 이 매장·이 사람 몫으로 발급된 모양인가(다른 사람·다른 매장·경로 꼼수 거절)."""
    bucket = re.escape(get_settings().avatar_bucket)
    return re.fullmatch(rf"{bucket}/{store_id}/{user_id}/[0-9a-f]{{32}}\.(jpg|png|webp)", path) is not None


async def set_avatar(conn, user_id: int, path: str | None) -> None:
    # store-isolation-ok: 사용자 본인 행(JWT user_id)만 바꾼다. 경로는 부르는 쪽이 매장·사람 몫인지 확인한다
    await conn.execute("update users set avatar_path = $2 where user_id = $1", user_id, path)
