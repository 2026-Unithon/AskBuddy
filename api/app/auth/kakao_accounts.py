"""카카오 계정을 AskBuddy 계정에 잇는다. 판정은 순수 함수, DB 처리는 그 결과만 따른다."""
from __future__ import annotations

import asyncpg

from app.auth.kakao import KakaoUser
from app.members import join_requests
from app.members.join_requests import JoinRefused, decide_join

_FALLBACK_NAME = "카카오 사용자"


class AuthFlowError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def decide(*, intent: str, user_exists: bool, user_role: str | None, active_store_id: int | None,
           invite_store_id: int | None) -> str:
    if intent not in ("LOGIN", "STAFF_JOIN") or (user_exists and user_role not in (None, "OWNER", "STAFF")):
        raise AuthFlowError("ROLE_CONFLICT")
    if intent == "LOGIN":
        # 단일 로그인 화면. 새 계정은 역할을 비워 두고 가입 직후 고르게 한다
        return "LOGIN" if user_exists else "CREATE_UNSET"
    # STAFF_JOIN — 초대 링크로 왔으니 알바다
    if invite_store_id is None:
        raise AuthFlowError("INVITE_INVALID")
    if not user_exists:
        return "CREATE_STAFF_AND_REQUEST"
    if user_role is None:
        return "SET_STAFF_AND_REQUEST"
    try:
        action = decide_join(user_role=user_role, active_store_id=active_store_id,
                             invite_store_id=invite_store_id)
    except JoinRefused as exc:
        raise AuthFlowError(exc.code) from exc
    return "LOGIN" if action == "ALREADY_MEMBER" else "REQUEST"


async def _find(db, kakao_id: str):
    return await db.fetchrow(
        """
        select u.user_id, u.role, u.name from user_identities i join users u on u.user_id = i.user_id
        where i.provider = 'KAKAO' and i.provider_user_id = $1 for update of u
        """,
        kakao_id)


async def _create_user(db, *, kakao_user: KakaoUser, role: str | None) -> dict:
    name = (kakao_user.nickname or _FALLBACK_NAME).strip()[:50] or _FALLBACK_NAME
    user = await db.fetchrow(
        "insert into users (name, role) values ($1, $2) returning user_id, role, name", name, role)
    await db.execute(
        "insert into user_identities (user_id, provider, provider_user_id) values ($1, 'KAKAO', $2)",
        user["user_id"], kakao_user.id)
    return dict(user)


# store-isolation-ok: 로그인 시점이라 아직 매장 범위가 없다. 초대 매장은 서버가 토큰으로 찾은 값이다
async def complete_kakao_login(db, *, kakao_user: KakaoUser, intent: str,
                               invite: dict | None) -> tuple[int, int | None]:
    for attempt in range(2):
        try:
            async with db.transaction():
                user = await _find(db, kakao_user.id)
                active = None
                if user is not None:
                    active = await db.fetchval(
                        """
                        select store_id from store_members
                        where user_id = $1 and removed_at is null order by member_id limit 1
                        """,
                        user["user_id"])
                action = decide(
                    intent=intent,
                    user_exists=user is not None,
                    user_role=user["role"] if user else None,
                    active_store_id=int(active) if active is not None else None,
                    invite_store_id=int(invite["store_id"]) if invite else None)
                notification_id = None
                if action == "CREATE_UNSET":
                    user = await _create_user(db, kakao_user=kakao_user, role=None)
                elif action in ("CREATE_STAFF_AND_REQUEST", "SET_STAFF_AND_REQUEST", "REQUEST"):
                    if action == "CREATE_STAFF_AND_REQUEST":
                        user = await _create_user(db, kakao_user=kakao_user, role="STAFF")
                    elif action == "SET_STAFF_AND_REQUEST":
                        await db.execute(
                            "update users set role = 'STAFF' where user_id = $1 and role is null",
                            user["user_id"])
                    _, notification_id = await join_requests.request_join(
                        db, store_id=int(invite["store_id"]), user_id=int(user["user_id"]),
                        invite_id=int(invite["invite_id"]), staff_name=user["name"])
                await db.execute(
                    """
                    update user_identities set last_login_at = now()
                    where provider = 'KAKAO' and provider_user_id = $1
                    """,
                    kakao_user.id)
                return int(user["user_id"]), notification_id
        except asyncpg.UniqueViolationError:
            # 같은 카카오 계정의 콜백이 동시에 두 번 왔다. 한 번 더 돌면 기존 계정으로 로그인된다
            if attempt == 1:
                raise
    raise AssertionError("unreachable")
