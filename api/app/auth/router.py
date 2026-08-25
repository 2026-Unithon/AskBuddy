"""관호 (feat/db) — 가입 · 로그인 · 초대코드 합류.

main.py 는 이 파일의 router 만 import 한다. 엔드포인트는 여기 안에서 자유롭게 추가한다.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import bcrypt
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr, Field

from app.config import get_settings
from app.deps import Db, create_token

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
    role: str = Field(pattern="^(OWNER|STAFF)$")
    phone: str | None = None


class LoginRequest(BaseModel):
    """역할 선택 후 재진입. role 은 UI에서 고른 값이며 DB users.role 과 일치해야 한다."""
    email: EmailStr
    password: str
    role: str = Field(pattern="^(OWNER|STAFF)$")


class JoinRequest(BaseModel):
    """알바 최초 합류. role 은 항상 STAFF 로 저장한다 (요청에 role 없음)."""
    email: EmailStr
    password: str
    name: str = Field(min_length=1, max_length=50)
    invite_code: str = Field(min_length=1, max_length=50)
    phone: str | None = None


def _token_for(user_id: int, store_id: int | None, role: str) -> str:
    s = get_settings()
    payload: dict = {
        "user_id": user_id,
        "role": role,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=s.jwt_expire_minutes),
    }
    if store_id is not None:
        payload["store_id"] = store_id
    return create_token(payload)


@router.post("/signup")
async def signup(req: SignupRequest, db: Db):
    """점주 가입. STAFF 는 /auth/join(초대코드)을 쓴다."""
    if req.role != "OWNER":
        raise HTTPException(400, "STAFF 는 /auth/join 으로 가입한다")

    existing = await db.fetchrow(
        "select user_id from users where email = $1", str(req.email).lower()
    )
    if existing:
        raise HTTPException(409, "email already registered")

    row = await db.fetchrow(
        """
        insert into users (name, phone, email, password_hash, role)
        values ($1, $2, $3, $4, 'OWNER')
        returning user_id, name, email, role
        """,
        req.name,
        req.phone,
        str(req.email).lower(),
        _hash_password(req.password),
    )
    token = _token_for(int(row["user_id"]), None, row["role"])
    return {
        "token": token,
        "user": {
            "user_id": int(row["user_id"]),
            "name": row["name"],
            "email": row["email"],
            "role": row["role"],
        },
    }


@router.post("/login")
async def login(req: LoginRequest, db: Db):
    """역할 선택 후 재진입. 요청 role 과 users.role 이 다르면 401 (계정 탐색 방지로 메시지 통일)."""
    row = await db.fetchrow(
        """
        select u.user_id, u.name, u.email, u.role, u.password_hash,
               sm.store_id
        from users u
        left join store_members sm on sm.user_id = u.user_id
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
    # PM UX: 사업자/알바 화면을 갈랐으므로, 고른 role 과 DB role 이 맞을 때만 통과
    if row["role"] != req.role:
        raise HTTPException(401, "invalid credentials")

    store_id = int(row["store_id"]) if row["store_id"] is not None else None
    # JWT role 은 요청값이 아니라 DB 값 (요청 role 은 게이트용)
    token = _token_for(int(row["user_id"]), store_id, row["role"])
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


@router.post("/join")
async def join(req: JoinRequest, db: Db):
    """알바 최초 합류: 초대코드 → users(STAFF) + store_members. 재진입은 /login."""
    invite = await db.fetchrow(
        """
        select invite_id, store_id, expires_at, is_used
        from invite_codes
        where code = $1
        """,
        req.invite_code.strip().upper(),
    )
    if not invite:
        raise HTTPException(404, "invalid invite code")
    if invite["is_used"]:
        raise HTTPException(410, "invite code already used")
    if invite["expires_at"] and invite["expires_at"] < datetime.now(timezone.utc):
        raise HTTPException(410, "invite code expired")

    existing = await db.fetchrow(
        "select user_id from users where email = $1", str(req.email).lower()
    )
    if existing:
        raise HTTPException(409, "email already registered")

    async with db.transaction():
        user = await db.fetchrow(
            """
            insert into users (name, phone, email, password_hash, role)
            values ($1, $2, $3, $4, 'STAFF')
            returning user_id, name, email, role
            """,
            req.name,
            req.phone,
            str(req.email).lower(),
            _hash_password(req.password),
        )
        store_id = int(invite["store_id"])
        await db.execute(
            """
            insert into store_members (store_id, user_id, member_role, day_count, progress_rate, is_deployable)
            values ($1, $2, 'STAFF', 0, 0, false)
            """,
            store_id,
            int(user["user_id"]),
        )
        # 해커톤: 코드 재사용 허용 여부가 미결(N1). 일단 is_used 는 건드리지 않는다.

    token = _token_for(int(user["user_id"]), store_id, user["role"])
    return {
        "token": token,
        "user": {
            "user_id": int(user["user_id"]),
            "name": user["name"],
            "email": user["email"],
            "role": user["role"],
            "store_id": store_id,
        },
    }
