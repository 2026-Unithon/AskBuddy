"""관호 (feat/db) — 가입 · 로그인 · 초대코드 합류.

main.py 는 이 파일의 router 만 import 한다. 엔드포인트는 여기 안에서 자유롭게 추가한다.
"""
from __future__ import annotations

import re
import secrets
from datetime import datetime, timedelta, timezone

import asyncpg
import bcrypt
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr, Field

from app.config import get_settings
from app.deps import Claims, CurrentStoreId, CurrentUserId, Db, create_token

router = APIRouter()

_INVITE_TTL_DAYS = 365


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


def _make_invite_code(business_type: str) -> str:
    """예: CAFE-A3F2. invite_codes.code unique (varchar 30)."""
    return f"{business_type}-{secrets.token_hex(2).upper()}"


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


# 업종별 기본 업무 카테고리. db/002_seed_demo.sql 의 demo-cafe 와 같은 값이다.
# 이번 릴리스는 카페만 구현한다 — 나머지 업종은 매장 생성 후 점주가 직접 켠다.
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


@router.post("/invites")
async def create_invite(
    db: Db,
    user_id: CurrentUserId,
    store_id: CurrentStoreId,
    claims: Claims,
):
    """점주가 알바용 초대코드 발급. store_id 는 JWT 만 신뢰 (body 없음)."""
    if claims.get("role") != "OWNER":
        raise HTTPException(403, "OWNER only")

    # JWT store_id 가 이 OWNER 의 매장인지 확인
    member = await db.fetchrow(
        """
        select member_id from store_members
        where store_id = $1 and user_id = $2 and member_role = 'OWNER'
        """,
        store_id,
        user_id,
    )
    if not member:
        raise HTTPException(403, "not owner of this store")

    biz = await db.fetchrow(
        "select business_type from stores where store_id = $1",
        store_id,
    )
    if not biz:
        raise HTTPException(404, "store not found")

    # 이미 쓸 수 있는 코드가 있으면 그걸 돌려준다.
    # 화면에 들어올 때마다 새로 발급하면 사장님이 알바에게 알려준 코드가 계속 바뀐다.
    existing = await db.fetchrow(
        """
        select invite_id, code, expires_at, store_id
        from invite_codes
        where store_id = $1 and is_used = false and expires_at > now()
        order by invite_id
        limit 1
        """,
        store_id,
    )
    if existing:
        return {
            "invite_id": int(existing["invite_id"]),
            "code": existing["code"],
            "store_id": int(existing["store_id"]),
            "expires_at": existing["expires_at"].isoformat(),
            "reused": True,
        }

    expires_at = datetime.now(timezone.utc) + timedelta(days=_INVITE_TTL_DAYS)

    # unique 충돌 시 몇 번 재시도
    for _ in range(5):
        code = _make_invite_code(biz["business_type"])
        try:
            row = await db.fetchrow(
                """
                insert into invite_codes (store_id, code, expires_at)
                values ($1, $2, $3)
                returning invite_id, code, expires_at, store_id
                """,
                store_id,
                code,
                expires_at,
            )
            return {
                "invite_id": int(row["invite_id"]),
                "code": row["code"],
                "store_id": int(row["store_id"]),
                "expires_at": row["expires_at"].isoformat(),
                "reused": False,
            }
        except asyncpg.UniqueViolationError:
            continue

    raise HTTPException(500, "failed to allocate invite code")
