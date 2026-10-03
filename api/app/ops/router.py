"""운영자 로그인 (이슈 #33). 운영자는 매장 밖 계정이며 진단 화면에만 쓴다."""
from __future__ import annotations

import asyncio

import bcrypt
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field

from app.auth.router import _verify_password
from app.config import get_settings
from app.deps import Db
from app.ops.deps import OPS_ROLE, create_operator_token
from app.ops.lockout import LoginLimiter

router = APIRouter()

_limiter: LoginLimiter | None = None


def get_limiter() -> LoginLimiter:
    global _limiter
    if _limiter is None:
        s = get_settings()
        _limiter = LoginLimiter(s.ops_login_max_failures, s.ops_login_lock_minutes * 60)
    return _limiter


# 계정이 없을 때 비교할 해시. 같은 비용으로 비교해 응답 시간으로 계정 유무를 알 수 없게 한다.
# 첫 요청이 추가 비용을 내지 않도록 import 때 계산한다
_DUMMY_HASH = bcrypt.hashpw(b"askbuddy-ops-dummy", bcrypt.gensalt(rounds=12)).decode("utf-8")


class OpsLoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


# store-isolation-ok: 운영자는 매장 밖 계정이라 store_id 가 없다
@router.post("/login")
async def ops_login(req: OpsLoginRequest, request: Request, db: Db):
    email = str(req.email).lower()
    # 프록시 뒤에서는 프록시 주소가 보인다. 그때는 사실상 이메일 단위로 막힌다
    ip = request.client.host if request.client else "unknown"
    limiter = get_limiter()
    # 시도를 await 전에 먼저 센다. 동시 요청이 한꺼번에 검사를 통과하지 못하게 한다
    if not limiter.try_acquire(ip, email):
        raise HTTPException(429, "too many failed attempts")

    # store-isolation-ok: 운영자 로그인은 매장 밖 users 조회다
    row = await db.fetchrow(
        "select user_id, name, email, role, password_hash from users where email = $1", email)
    password_hash = row["password_hash"] if row and row["password_hash"] else _DUMMY_HASH
    password_ok = await asyncio.to_thread(_verify_password, req.password, password_hash)
    if not row or not row["password_hash"] or row["role"] != OPS_ROLE or not password_ok:
        raise HTTPException(401, "invalid credentials")

    limiter.reset(ip, email)
    user_id = int(row["user_id"])
    return {
        "token": create_operator_token(user_id),
        "operator": {"user_id": user_id, "name": row["name"], "email": row["email"]},
    }
