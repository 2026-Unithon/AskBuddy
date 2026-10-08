"""관호 (feat/db) — 가입 · 로그인 · 초대코드 합류.

main.py 는 이 파일의 router 만 import 한다. 엔드포인트는 여기 안에서 자유롭게 추가한다.
"""
from __future__ import annotations

import re
from typing import Literal

import asyncpg
import bcrypt
from fastapi import APIRouter, HTTPException, Request, Response, BackgroundTasks
from pydantic import BaseModel, EmailStr, Field

from app.deps import Claims, CurrentUserId, Db

from app.auth.session import (
    REFRESH_COOKIE, RefreshRejected, active_store_id, clear_refresh_cookie,
    create_access_token, issue_refresh, require_allowed_origin, revoke_family_of,
    rotate_refresh, session_payload, set_refresh_cookie,
)
from app.errors import ApiError

from app.members import invites, join_requests
from app.notifications.service import deliver_notification

router = APIRouter()



def _hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def _verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


class SignupRequest(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    email: EmailStr
    password: str = Field(min_length=6, max_length=128)
    role: Literal["OWNER", "STAFF"] | None = None
    phone: str | None = None


class LoginRequest(BaseModel):
    """역할은 DB에서 결정한다. 요청 role은 구버전 클라이언트 호환용이다."""
    email: EmailStr
    password: str
    role: Literal["OWNER", "STAFF"] | None = None


class CreateStoreRequest(BaseModel):
    """점주 온보딩 — 매장 생성. store_id 는 JWT 재발급으로만 전달한다."""
    store_name: str = Field(min_length=1, max_length=100)
    business_type: str = Field(
        pattern="^(CAFE|RESTAURANT|BAKERY|BAR|CVS|SALON)$"
    )
    store_slug: str | None = Field(default=None, min_length=2, max_length=50)


def _slugify(store_name: str, user_id: int) -> str:
    """store_slug 가 없으면 이름 기반. 비면 store-{user_id}."""
    raw = re.sub(r"[^a-z0-9]+", "-", store_name.lower()).strip("-")
    if not raw:
        raw = f"store-{user_id}"
    return raw[:50]


def _token_for(user_id: int, store_id: int | None, role: str | None) -> str:
    return create_access_token(user_id=user_id, role=role, store_id=store_id)


async def start_session(db, response: Response, *, user_id: int) -> None:
    """로그인·가입이 끝나면 refresh 쿠키를 심는다. 카카오 콜백도 이 함수를 쓴다."""
    raw, _ = await issue_refresh(db, user_id=user_id)
    set_refresh_cookie(response, raw)


# store-isolation-ok: 가입 전에는 매장이 없고 신규 사용자만 생성한다.
@router.post("/signup")
async def signup(req: SignupRequest, response: Response, db: Db):
    """역할 없이도 가입할 수 있다. 직원은 승인 전까지 매장 소속이 없다."""

    existing = await db.fetchrow(
        "select user_id from users where email = $1", str(req.email).lower()
    )
    if existing:
        raise HTTPException(409, "email already registered")

    row = await db.fetchrow(
        """
        insert into users (name, phone, email, password_hash, role)
        values ($1, $2, $3, $4, $5)
        returning user_id, name, email, role
        """,
        req.name,
        req.phone,
        str(req.email).lower(),
        _hash_password(req.password),
        req.role,
    )
    token = _token_for(int(row["user_id"]), None, row["role"])
    await start_session(db, response, user_id=int(row["user_id"]))
    return {
        "token": token,
        "user": {
            "user_id": int(row["user_id"]),
            "name": row["name"],
            "email": row["email"],
            "role": row["role"],
        },
    }


# store-isolation-ok: 로그인 시점에 사용자 자격과 활성 소속을 검증한다.
@router.post("/login")
async def login(req: LoginRequest, response: Response, db: Db):
    """이메일 계정으로 로그인하고 제품 세션 쿠키를 발급한다."""
    row = await db.fetchrow(
        """
        select u.user_id, u.name, u.email, u.role, u.password_hash,
               sm.store_id
        from users u
        left join store_members sm on sm.user_id = u.user_id and sm.removed_at is null
        where u.email = $1
        order by sm.member_id
        limit 1
        """,
        str(req.email).lower(),
    )
    if not row or not row["password_hash"]:
        raise HTTPException(401, "invalid credentials")
    if not _verify_password(req.password, row["password_hash"]):
        raise HTTPException(401, "invalid credentials")
    if row["role"] not in (None, "OWNER", "STAFF"):
        raise HTTPException(401, "invalid credentials")

    store_id = int(row["store_id"]) if row["store_id"] is not None else None
    # JWT 역할은 요청값이 아닌 DB 값으로 정한다.
    token = _token_for(int(row["user_id"]), store_id, row["role"])
    await start_session(db, response, user_id=int(row["user_id"]))
    return {
        "token": token,
        "user": {
            "user_id": int(row["user_id"]),
            "name": row["name"],
            "email": row["email"],
            "role": row["role"],
            "store_id": store_id,
        },
    }


DEFAULT_CATEGORIES: dict[str, list[tuple[str, bool, int]]] = {
    "CAFE": [
        ("오픈업무", True, 1),
        ("재고정리", True, 2),
        ("음료제작", True, 3),
        ("마감업무", True, 4),
        ("베이킹", False, 5),
    ],
}


@router.post("/stores")
async def create_store(req: CreateStoreRequest, db: Db, claims: Claims):
    """OWNER 온보딩: stores + store_members(OWNER). JWT 에 store_id 넣어 재발급.

    signup 직후 토큰에는 store_id 가 없다. CurrentStoreId 를 쓰지 않는다.
    """
    user_id = claims.get("user_id")
    if user_id is None:
        raise HTTPException(403, "token has no user_id")
    if claims.get("role") != "OWNER":
        raise HTTPException(403, "OWNER only")
    user_id = int(user_id)

    already = await db.fetchrow(
        """
        select store_id from store_members
        where user_id = $1 and member_role = 'OWNER'
        limit 1
        """,
        user_id,
    )
    if already:
        raise HTTPException(409, "owner already has a store")

    slug = (req.store_slug or _slugify(req.store_name, user_id)).strip().lower()
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug):
        raise HTTPException(400, "store_slug must be lowercase letters, digits, hyphens")

    try:
        async with db.transaction():
            store = await db.fetchrow(
                """
                insert into stores (owner_id, store_slug, store_name, business_type)
                values ($1, $2, $3, $4)
                returning store_id, store_slug, store_name, business_type
                """,
                user_id,
                slug,
                req.store_name,
                req.business_type,
            )
            store_id = int(store["store_id"])
            await db.execute(
                """
                insert into store_members
                  (store_id, user_id, member_role, day_count, progress_rate, is_deployable)
                values ($1, $2, 'OWNER', 0, 0, false)
                """,
                store_id,
                user_id,
            )
            # 업무 카테고리 기본값. 없으면 추출기가 고를 카테고리가 없어
            # 자료를 올려도 카드가 0건이 된다 (자유 생성 금지 규칙).
            # 이번 릴리스는 카페만 구현한다. 다른 업종은 빈 목록으로 시작한다.
            defaults = DEFAULT_CATEGORIES.get(req.business_type, [])
            if defaults:
                await db.executemany(
                    """
                    insert into task_categories
                      (store_id, category_name, is_enabled, sort_order)
                    values ($1, $2, $3, $4)
                    on conflict (store_id, category_name) do nothing
                    """,
                    [(store_id, name, enabled, order)
                     for name, enabled, order in defaults],
                )
    except asyncpg.UniqueViolationError as e:
        raise HTTPException(409, "store_slug already taken") from e

    token = _token_for(user_id, store_id, "OWNER")
    return {
        "token": token,
        "store": {
            "store_id": store_id,
            "store_slug": store["store_slug"],
            "store_name": store["store_name"],
            "business_type": store["business_type"],
        },
    }



# store-isolation-ok: 쿠키 세션 갱신. 매장은 서버가 활성 멤버십에서 정한다
@router.post("/refresh")
async def refresh(request: Request, response: Response, db: Db):
    require_allowed_origin(request)
    raw = request.cookies.get(REFRESH_COOKIE)
    if not raw:
        raise ApiError(401, "SESSION_EXPIRED", "다시 로그인해 주세요.")
    try:
        user_id, new_raw = await rotate_refresh(db, raw=raw)
        payload = await session_payload(db, user_id=user_id)
    except RefreshRejected as exc:
        raise ApiError(401, "SESSION_EXPIRED", "다시 로그인해 주세요.") from exc
    set_refresh_cookie(response, new_raw)
    return payload


# store-isolation-ok: 로그아웃은 사용자 단위 세션 폐기다
@router.post("/logout", status_code=204)
async def logout(request: Request, db: Db):
    require_allowed_origin(request)
    raw = request.cookies.get(REFRESH_COOKIE)
    if raw:
        await revoke_family_of(db, raw=raw)
    out = Response(status_code=204)
    clear_refresh_cookie(out)
    return out



# store-isolation-ok: 공개 초대 링크 미리보기. 매장명만 돌려준다
@router.get("/invites/{token}")
async def preview_invite(token: str, db: Db):
    found = await invites.resolve(db, token=token)
    if found is None:
        raise ApiError(404, "INVITE_INVALID", "더 이상 쓸 수 없는 초대 링크예요.")
    return {"store_name": found["store_name"]}

class JoinByInviteRequest(BaseModel):
    invite_token: str = Field(min_length=16, max_length=64)


_JOIN_MESSAGES = {
    "ROLE_CONFLICT": "사장님 계정으로는 직원으로 합류할 수 없어요.",
    "ALREADY_IN_OTHER_STORE": "이미 다른 매장에 합류한 계정이에요.",
}


# store-isolation-ok: 매장 소속 전 알바의 합류 요청. 매장은 초대 토큰으로 서버가 찾는다
@router.post("/join-requests")
async def create_join_request(req: JoinByInviteRequest, db: Db, claims: Claims,
                              user_id: CurrentUserId, background: BackgroundTasks):
    invite = await invites.resolve(db, token=req.invite_token)
    if invite is None:
        raise ApiError(404, "INVITE_INVALID", "더 이상 쓸 수 없는 초대 링크예요.")
    store_id = int(invite["store_id"])
    role = claims.get("role")
    if role is None:
        await set_role_if_unset(db, user_id=user_id, role="STAFF")
        role = await db.fetchval("select role from users where user_id = $1", user_id)
    try:
        action = join_requests.decide_join(
            user_role=role,
            active_store_id=await active_store_id(db, user_id=user_id),
            invite_store_id=store_id)
    except join_requests.JoinRefused as exc:
        raise ApiError(exc.status, exc.code, _JOIN_MESSAGES[exc.code]) from exc
    if action == "ALREADY_MEMBER":
        return {"status": "ALREADY_MEMBER", "store_name": invite["store_name"]}
    name = await db.fetchval("select name from users where user_id = $1", user_id)
    _, notification_id = await join_requests.request_join(
        db, store_id=store_id, user_id=user_id,
        invite_id=int(invite["invite_id"]), staff_name=name)
    if notification_id is not None:
        # 커밋 뒤에 보내야 알림 행이 보인다
        background.add_task(deliver_notification, store_id, notification_id)
    return {"status": "PENDING", "store_name": invite["store_name"]}


# store-isolation-ok: 매장 소속 전 알바가 자기 요청 상태만 본다
@router.get("/join-status")
async def join_status(db: Db, user_id: CurrentUserId):
    return await join_requests.latest_status(db, user_id=user_id)

class RoleRequest(BaseModel):
    role: Literal["OWNER", "STAFF"]


# store-isolation-ok: 역할은 사용자 단위다. 아직 매장이 없다
async def set_role_if_unset(db, *, user_id: int, role: str) -> bool:
    changed = await db.fetchval(
        "update users set role = $2 where user_id = $1 and role is null returning user_id",
        user_id, role)
    return changed is not None


# store-isolation-ok: 가입 직후 한 번 역할을 고른다. 매장은 아직 없다
@router.post("/role")
async def choose_role(req: RoleRequest, db: Db, user_id: CurrentUserId):
    if not await set_role_if_unset(db, user_id=user_id, role=req.role):
        raise ApiError(409, "ROLE_ALREADY_SET", "이미 역할을 골랐어요.")
    return await session_payload(db, user_id=user_id)
