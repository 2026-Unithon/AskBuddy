"""로그인된 기기(계획 8). refresh 토큰 계열(family) 하나가 기기 하나다. 사용자 단위."""
from __future__ import annotations

import uuid

_APPS = (("KAKAOTALK", "카카오톡"), ("SamsungBrowser", "삼성 인터넷"), ("Edg/", "Edge"), ("Chrome/", "Chrome"), ("Safari/", "Safari"))
_DEVICES = (("iPhone", "아이폰"), ("iPad", "아이패드"), ("Android", "안드로이드"), ("Macintosh", "Mac"), ("Windows", "Windows"))


def device_label(ua: str | None) -> str:
    """'아이폰 Safari' 같은 짧은 이름. 판정 순서가 곧 우선순위다(삼성 인터넷·Edge 도 Chrome/ 을 달고 온다)."""
    if not ua:
        return "알 수 없는 기기"
    device = next((name for key, name in _DEVICES if key in ua), "")
    app = next((name for key, name in _APPS if key in ua), "")
    label = " ".join(part for part in (device, app) if part)
    return label or "알 수 없는 기기"


# store-isolation-ok: 세션은 사용자 단위다
async def list_sessions(db, *, user_id: int, current_family: uuid.UUID | None) -> list[dict]:
    """살아 있는 계열만. 계열마다 가장 최근 행(기기 이름, 마지막 사용)."""
    rows = await db.fetch(
        """
        select distinct on (family_id) family_id, user_agent, coalesce(last_used_at, created_at) as last_used_at
        from auth_refresh_tokens
        where user_id = $1 and revoked_at is null and expires_at > now()
        order by family_id, token_id desc
        """,
        user_id)
    items = [
        {"family_id": str(r["family_id"]), "label": device_label(r["user_agent"]),
         "last_used_at": r["last_used_at"], "current": current_family is not None and r["family_id"] == current_family}
        for r in rows
    ]
    # 이 기기를 맨 위, 나머지는 최근 사용 순
    return sorted(items, key=lambda d: (not d["current"], -d["last_used_at"].timestamp()))


# store-isolation-ok: 세션은 사용자 단위다. 내 계열이 아니면 LookupError(라우터에서 404)
async def revoke(db, *, user_id: int, family_id: str) -> None:
    try:
        family = uuid.UUID(family_id)
    except ValueError as exc:
        raise LookupError("family") from exc
    async with db.transaction():
        owner = await db.fetchval(
            "select user_id from auth_refresh_tokens where family_id = $1 and user_id = $2 limit 1", family, user_id)
        if owner is None:
            raise LookupError("family")
        await db.execute(
            "update auth_refresh_tokens set revoked_at = now() where family_id = $1 and user_id = $2 and revoked_at is null",
            family, user_id)


# store-isolation-ok: 세션은 사용자 단위다. 요청의 refresh 쿠키가 어느 계열인지(이 기기 표시)
async def family_of(db, *, raw: str | None) -> uuid.UUID | None:
    if not raw:
        return None
    from app.auth.session import _hash

    return await db.fetchval("select family_id from auth_refresh_tokens where token_hash = $1", _hash(raw))
