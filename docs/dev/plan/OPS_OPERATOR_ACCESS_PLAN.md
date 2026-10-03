# 운영자 역할과 진단 화면 접근 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `/preflight`를 DB 역할 `OPERATOR` 계정만 쓰게 하고, 진단의 오진 두 건(DB 스키마·검색 게이트 401)을 고친다. 추적: GitHub 이슈 #33.

**Architecture:** `users.role`에 `OPERATOR`를 더하고 `POST /ops/login`이 `aud=askbuddy-ops` 토큰을 발급한다. 운영자 의존성은 audience를 지정해 decode하고 요청마다 `users.role`을 다시 읽는다. 제품 `get_claims`는 audience 없이 decode하므로 PyJWT가 `aud` 있는 토큰을 거부한다. 진단은 연결·스키마를 나눠 점검하고 검색은 `retrieve_question`을 직접 부른다. Web은 sessionStorage 토큰으로 로그인 폼과 진단 화면을 오간다.

**Tech Stack:** FastAPI, PyJWT, bcrypt, asyncpg, unittest + FastAPI TestClient, Next.js 16, TanStack Query v5

**Spec:** [OPS_OPERATOR_ACCESS_DESIGN.md](OPS_OPERATOR_ACCESS_DESIGN.md)

## Global Constraints

- 운영자 역할 값은 `OPERATOR`. `store_members.member_role`은 `OWNER`/`STAFF` 그대로 둔다.
- 운영자 토큰 claim: `user_id`, `role=OPERATOR`, `aud=askbuddy-ops`, `exp`=발급 후 60분, `store_id` 없음.
- 로그인 실패는 사유와 관계없이 `401 {"detail": "invalid credentials"}`. 계정이 없을 때도 bcrypt 비교를 한 번 한다.
- 같은 IP+이메일 실패가 반복되면 차단(429). 프로세스 메모리에서 센다.
- `/preflight`(기본·deep): 토큰 없음·만료·제품 토큰은 401, 역할 회수는 403. `/health`는 공개.
- 진단 검색 비용은 `UsageContext(cost_phase="OPERATING", cost_purpose="DEVELOPMENT", stage="QUERY")`.
- 데모 매장 slug `demo-cafe`가 없으면 검색 점검은 `warn`.
- 임계값·만료 시간은 `api/app/config.py`가 단일 출처(CLAUDE.md 불변식 8).
- 운영자 토큰은 Web `sessionStorage`. 제품 로그인(`localStorage`)과 섞지 않고 제품 세션 만료 이벤트를 일으키지 않는다.
- 주석·문서는 한국어. `web/`에는 단위 테스트 러너가 없다. `pnpm check`와 브라우저 확인을 나눠 보고한다.
- **커밋은 사용자가 지시할 때만 한다.** 각 Task 끝은 `git status --short`로 범위만 확인한다.

## Review Focus

1. **운영자 토큰으로 매장 API 호출**: PyJWT가 audience 미지정 decode에서 `aud` 토큰을 거부해야 한다. → Task 1 `test_operator_token_rejected_by_store_api`
2. **`aud=askbuddy-ops`로 위조됐지만 role이 OWNER인 토큰**: 운영자 의존성이 401로 막아야 한다. → Task 1 `test_ops_audience_with_other_role_rejected`
3. **운영자 화면의 401이 같은 탭의 제품 로그인을 로그아웃시키는 경우**: `fetchJson`의 세션 만료 이벤트를 운영자 호출에서 끈다. → Task 4 Step 2, 수동 확인
4. **테이블이 빠진 DB**: 스키마 줄에 없는 테이블 이름이 나오고 연결 문제 안내(SUPABASE_DB_URL)가 나오지 않아야 한다. 집계 쿼리가 없는 테이블을 읽다 터지지 않아야 한다. → Task 2 `test_missing_tables_named_without_connection_hint`
5. **계정 존재 여부 노출**: 없는 계정·OWNER 계정·틀린 비밀번호가 같은 응답이고 없는 계정도 bcrypt를 수행. → Task 1 `test_failures_share_one_401`, `test_missing_account_still_runs_bcrypt`

---

## 파일 구조

| 파일 | 책임 |
|---|---|
| `supabase/migrations/20261003090000_ops_operator_role.sql` | `users_role_check`에 `OPERATOR` 추가 |
| `api/app/config.py` | 운영자 토큰 만료·로그인 차단 설정 |
| `api/app/ops/__init__.py` | 패키지 |
| `api/app/ops/lockout.py` | `LoginLimiter`: IP+이메일 실패 횟수 |
| `api/app/ops/deps.py` | `create_operator_token`, `get_operator_id`, `OperatorId` |
| `api/app/ops/router.py` | `POST /ops/login` |
| `api/app/main.py` | ops router 등록 |
| `api/app/preflight.py` | 운영자 전용, DB 연결·스키마 분리, 검색 직접 호출 |
| `api/scripts/create_operator.py` | 운영자 계정 생성 |
| `api/tests/test_ops_auth.py` | 로그인·차단·토큰 경계 |
| `api/tests/test_preflight_ops.py` | `/preflight` 접근, DB·검색 점검 |
| `api/tests/test_create_operator.py` | 계정 생성 스크립트 |
| `web/lib/api.ts` | `opsLogin`, `getPreflight(token)`, 세션 만료 이벤트 끄기 옵션 |
| `web/lib/ops-session.ts` | 운영자 토큰 sessionStorage 저장소 |
| `web/lib/query.ts` | `preflightQuery(token)` |
| `web/app/preflight/page.tsx` | 로그인 폼 ↔ 진단 화면 |
| `docs/dev/ASKBUDDY_MVP_CURRENT.md` | §18-1, §19-1 |
| `docs/dev/plan/OPS_OPERATOR_ACCESS_DESIGN.md` | 상태 줄 |

---

### Task 1: 운영자 역할·로그인·토큰

**Files:**
- Create: `supabase/migrations/20261003090000_ops_operator_role.sql`
- Modify: `api/app/config.py` (`jwt_expire_minutes` 줄 바로 아래)
- Create: `api/app/ops/__init__.py`, `api/app/ops/lockout.py`, `api/app/ops/deps.py`, `api/app/ops/router.py`
- Modify: `api/app/main.py` (router import·등록)
- Test: `api/tests/test_ops_auth.py`

**Interfaces:**
- Produces: `app.ops.deps.OPS_AUDIENCE = "askbuddy-ops"`, `OPS_ROLE = "OPERATOR"`, `create_operator_token(user_id: int) -> str`, `async get_operator_id(db: Db, authorization: str | None) -> int`, `OperatorId = Annotated[int, Depends(get_operator_id)]`. Task 2가 `OperatorId`를 쓴다.
- Produces: `POST /ops/login` → `{token, operator: {user_id, name, email}}`. Task 4가 부른다.
- Produces: settings `ops_token_expire_minutes`(60), `ops_login_max_failures`(5), `ops_login_lock_minutes`(15).

- [ ] **Step 1: 실패하는 테스트 작성 `api/tests/test_ops_auth.py`**

```python
"""운영자 로그인·토큰 경계 (이슈 #33)."""
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import bcrypt
import jwt
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.deps import CurrentStoreId, create_token, get_db
from app.ops import router as ops_router_module
from app.ops.deps import OperatorId
from app.ops.lockout import LoginLimiter

SETTINGS = SimpleNamespace(
    jwt_secret="synthetic-test-key-" * 4, jwt_algorithm="HS256",
    ops_token_expire_minutes=60, ops_login_max_failures=3, ops_login_lock_minutes=15)
PASSWORD_HASH = bcrypt.hashpw(b"right-password", bcrypt.gensalt(rounds=4)).decode()


class UsersDb:
    def __init__(self):
        self.users = {
            "ops@example.com": dict(user_id=1, name="운영자", email="ops@example.com",
                                    role="OPERATOR", password_hash=PASSWORD_HASH),
            "owner@example.com": dict(user_id=2, name="점주", email="owner@example.com",
                                      role="OWNER", password_hash=PASSWORD_HASH),
        }

    async def fetchrow(self, sql, *args):
        if "from users where email" in sql:
            return self.users.get(args[0])
        if "from users where user_id" in sql:
            return next((u for u in self.users.values() if u["user_id"] == args[0]), None)
        if "store_members" in sql:
            # 매장 1 에는 점주(user 2)만 소속돼 있다
            return {"member_role": "OWNER"} if args == (1, 2) else None
        raise AssertionError(sql)


class LoginLimiterTest(unittest.TestCase):
    def test_window_expiry_and_reset(self):
        now = [0.0]
        limiter = LoginLimiter(2, 60, clock=lambda: now[0])
        limiter.record_failure("1.1.1.1", "a@example.com")
        limiter.record_failure("1.1.1.1", "a@example.com")
        self.assertTrue(limiter.is_blocked("1.1.1.1", "a@example.com"))
        self.assertFalse(limiter.is_blocked("2.2.2.2", "a@example.com"))
        self.assertFalse(limiter.is_blocked("1.1.1.1", "b@example.com"))
        now[0] = 61
        self.assertFalse(limiter.is_blocked("1.1.1.1", "a@example.com"))
        limiter.record_failure("1.1.1.1", "a@example.com")
        limiter.reset("1.1.1.1", "a@example.com")
        limiter.record_failure("1.1.1.1", "a@example.com")
        self.assertFalse(limiter.is_blocked("1.1.1.1", "a@example.com"))


class OpsAuthTest(unittest.TestCase):
    def setUp(self):
        self.db = UsersDb()
        for target in ("app.deps.get_settings", "app.ops.deps.get_settings",
                       "app.ops.router.get_settings"):
            item = patch(target, return_value=SETTINGS)
            item.start()
            self.addCleanup(item.stop)
        limiter = patch.object(ops_router_module, "_limiter", LoginLimiter(3, 900))
        limiter.start()
        self.addCleanup(limiter.stop)

        app = FastAPI()
        app.include_router(ops_router_module.router, prefix="/ops")

        @app.get("/ops-only")
        async def ops_only(operator_id: OperatorId):
            return {"operator_id": operator_id}

        @app.get("/store-only")
        async def store_only(store_id: CurrentStoreId):
            return {"store_id": store_id}

        async def fake_db():
            yield self.db

        app.dependency_overrides[get_db] = fake_db
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def login(self, email, password):
        return self.client.post("/ops/login", json={"email": email, "password": password})

    @staticmethod
    def bearer(token):
        return {"Authorization": "Bearer " + token}

    @staticmethod
    def later(minutes=5):
        return datetime.now(timezone.utc) + timedelta(minutes=minutes)

    def test_operator_login_returns_ops_token(self):
        res = self.login("OPS@example.com", "right-password")
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["operator"], {"user_id": 1, "name": "운영자", "email": "ops@example.com"})
        claims = jwt.decode(body["token"], SETTINGS.jwt_secret, algorithms=["HS256"],
                            audience="askbuddy-ops")
        self.assertEqual(claims["role"], "OPERATOR")
        self.assertEqual(claims["user_id"], 1)
        self.assertNotIn("store_id", claims)
        self.assertAlmostEqual(claims["exp"] - datetime.now(timezone.utc).timestamp(), 3600, delta=30)
        res = self.client.get("/ops-only", headers=self.bearer(body["token"]))
        self.assertEqual(res.json(), {"operator_id": 1})

    def test_failures_share_one_401(self):
        for email, password in (("ops@example.com", "wrong-password"),
                                ("owner@example.com", "right-password"),
                                ("nobody@example.com", "right-password")):
            res = self.login(email, password)
            self.assertEqual(res.status_code, 401, email)
            self.assertEqual(res.json(), {"detail": "invalid credentials"}, email)

    def test_missing_account_still_runs_bcrypt(self):
        with patch("app.ops.router._verify_password", return_value=False) as verify:
            self.assertEqual(self.login("nobody@example.com", "right-password").status_code, 401)
        verify.assert_called_once()

    def test_repeated_failures_block_even_correct_password(self):
        for _ in range(3):
            self.assertEqual(self.login("ops@example.com", "wrong-password").status_code, 401)
        self.assertEqual(self.login("ops@example.com", "right-password").status_code, 429)
        # 다른 이메일은 막히지 않는다
        self.assertEqual(self.login("owner@example.com", "wrong-password").status_code, 401)

    def test_operator_token_rejected_by_store_api(self):
        token = self.login("ops@example.com", "right-password").json()["token"]
        self.assertEqual(self.client.get("/store-only", headers=self.bearer(token)).status_code, 401)

    def test_product_token_rejected_by_operator_dependency(self):
        product = create_token(dict(store_id=1, user_id=2, role="OWNER", exp=self.later()))
        # 제품 토큰은 매장 API 에서는 통과한다 (대조)
        self.assertEqual(self.client.get("/store-only", headers=self.bearer(product)).status_code, 200)
        self.assertEqual(self.client.get("/ops-only", headers=self.bearer(product)).status_code, 401)
        self.assertEqual(self.client.get("/ops-only").status_code, 401)

    def test_ops_audience_with_other_role_rejected(self):
        forged = create_token(dict(user_id=2, role="OWNER", aud="askbuddy-ops", exp=self.later()))
        self.assertEqual(self.client.get("/ops-only", headers=self.bearer(forged)).status_code, 401)

    def test_expired_ops_token_rejected(self):
        expired = create_token(dict(user_id=1, role="OPERATOR", aud="askbuddy-ops",
                                    exp=datetime.now(timezone.utc) - timedelta(minutes=1)))
        self.assertEqual(self.client.get("/ops-only", headers=self.bearer(expired)).status_code, 401)

    def test_role_revoked_returns_403(self):
        token = self.login("ops@example.com", "right-password").json()["token"]
        self.db.users["ops@example.com"]["role"] = "OWNER"
        self.assertEqual(self.client.get("/ops-only", headers=self.bearer(token)).status_code, 403)


def test_operator_role_migration():
    path = Path(__file__).resolve().parents[2] / "supabase/migrations/20261003090000_ops_operator_role.sql"
    sql = path.read_text(encoding="utf-8")
    code = "\n".join(line for line in sql.splitlines() if not line.strip().startswith("--"))
    assert "users_role_check" in code
    assert "'OWNER'" in code and "'STAFF'" in code and "'OPERATOR'" in code
    assert "store_members" not in code
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd api && source .venv/bin/activate && python -m pytest tests/test_ops_auth.py -q`
Expected: FAIL (`ModuleNotFoundError: No module named 'app.ops'`)

- [ ] **Step 3: migration 작성 `supabase/migrations/20261003090000_ops_operator_role.sql`**

```sql
-- 운영자 역할 추가 (이슈 #33).
-- 운영자는 어느 매장에도 소속되지 않으므로 store_members.member_role 은 OWNER/STAFF 그대로 둔다.
-- 가입 API(/auth/signup)는 계속 OWNER 만 만든다. 운영자는 api/scripts/create_operator.py 로만 만든다.
alter table users drop constraint if exists users_role_check;
alter table users add constraint users_role_check
  check (role in ('OWNER', 'STAFF', 'OPERATOR'));
```

- [ ] **Step 4: 설정 추가 `api/app/config.py`** (`jwt_expire_minutes: int = 1440` 바로 아래)

```python
    # 운영자 토큰(/ops/login). 진단 화면 전용이라 제품 토큰보다 짧게 둔다
    ops_token_expire_minutes: int = 60
    # 같은 IP+이메일 실패가 이 횟수에 닿으면 lock 시간 동안 로그인을 막는다
    ops_login_max_failures: int = 5
    ops_login_lock_minutes: int = 15
```

- [ ] **Step 5: `api/app/ops/__init__.py`** — 빈 파일

- [ ] **Step 6: `api/app/ops/lockout.py`**

```python
"""운영자 로그인 실패 횟수. 서버가 한 대라 프로세스 메모리에서 센다.

서버를 여러 대로 늘리면 저장 위치를 다시 정한다 (OPS_OPERATOR_ACCESS_DESIGN §4-1).
"""
from __future__ import annotations

import time
from collections.abc import Callable

# 키가 이만큼 쌓이면 만료된 기록을 한 번에 치운다. 여러 이메일로 두드려도 메모리가 계속 늘지 않게 한다
_SWEEP_AT = 10_000


class LoginLimiter:
    def __init__(self, max_failures: int, window_seconds: float,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._max = max_failures
        self._window = window_seconds
        self._clock = clock
        self._failures: dict[tuple[str, str], list[float]] = {}

    def _recent(self, key: tuple[str, str]) -> list[float]:
        now = self._clock()
        kept = [t for t in self._failures.get(key, []) if now - t < self._window]
        if kept:
            self._failures[key] = kept
        else:
            self._failures.pop(key, None)
        return kept

    def is_blocked(self, ip: str, email: str) -> bool:
        return len(self._recent((ip, email))) >= self._max

    def record_failure(self, ip: str, email: str) -> None:
        if len(self._failures) >= _SWEEP_AT:
            for key in list(self._failures):
                self._recent(key)
        key = (ip, email)
        self._failures[key] = [*self._recent(key), self._clock()]

    def reset(self, ip: str, email: str) -> None:
        self._failures.pop((ip, email), None)
```

- [ ] **Step 7: `api/app/ops/deps.py`**

```python
"""운영자 인증. 제품 토큰과 audience 로 갈라진다.

제품 API 의 get_claims 는 audience 없이 decode 한다. PyJWT 는 그때 aud 가 있는 토큰을
InvalidAudienceError 로 거부하므로, 운영자 토큰으로 매장 API 를 부를 수 없다.
운영자는 매장에 속하지 않는다. 요청마다 users.role 을 다시 읽어 회수된 역할을 즉시 막는다.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Annotated

import jwt
from fastapi import Depends, Header, HTTPException

from app.config import get_settings
from app.deps import Db, _claim_id, create_token

OPS_AUDIENCE = "askbuddy-ops"
OPS_ROLE = "OPERATOR"


def create_operator_token(user_id: int) -> str:
    s = get_settings()
    return create_token({
        "user_id": user_id,
        "role": OPS_ROLE,
        "aud": OPS_AUDIENCE,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=s.ops_token_expire_minutes),
    })


async def get_operator_id(db: Db, authorization: Annotated[str | None, Header()] = None) -> int:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "missing bearer token")
    s = get_settings()
    try:
        claims = jwt.decode(authorization[7:], s.jwt_secret, algorithms=[s.jwt_algorithm],
                            audience=OPS_AUDIENCE, options={"require": ["exp", "aud"]})
    except jwt.PyJWTError as e:
        raise HTTPException(401, "invalid token") from e
    if claims.get("role") != OPS_ROLE:
        raise HTTPException(401, "invalid token")
    user_id = _claim_id(claims, "user_id")
    # store-isolation-ok: 운영자는 매장에 속하지 않는다. users 역할만 재확인한다
    row = await db.fetchrow("select role from users where user_id = $1", user_id)
    if not row or row["role"] != OPS_ROLE:
        raise HTTPException(403, "operator role required")
    return user_id


OperatorId = Annotated[int, Depends(get_operator_id)]
```

- [ ] **Step 8: `api/app/ops/router.py`**

```python
"""운영자 로그인 (이슈 #33). 운영자는 매장 밖 계정이며 진단 화면에만 쓴다."""
from __future__ import annotations

import asyncio
from functools import cache

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


@cache
def _dummy_hash() -> str:
    """계정이 없을 때 비교할 해시. 같은 비용으로 비교해 응답 시간으로 계정 유무를 알 수 없게 한다."""
    return bcrypt.hashpw(b"askbuddy-ops-dummy", bcrypt.gensalt(rounds=12)).decode("utf-8")


class OpsLoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


@router.post("/login")
async def ops_login(req: OpsLoginRequest, request: Request, db: Db):
    email = str(req.email).lower()
    # 프록시 뒤에서는 프록시 주소가 보인다. 그때는 사실상 이메일 단위로 막힌다
    ip = request.client.host if request.client else "unknown"
    limiter = get_limiter()
    if limiter.is_blocked(ip, email):
        raise HTTPException(429, "too many failed attempts")

    # store-isolation-ok: 운영자 로그인은 매장 밖 users 조회다
    row = await db.fetchrow(
        "select user_id, name, email, role, password_hash from users where email = $1", email)
    password_hash = row["password_hash"] if row and row["password_hash"] else _dummy_hash()
    password_ok = await asyncio.to_thread(_verify_password, req.password, password_hash)
    if not row or not row["password_hash"] or row["role"] != OPS_ROLE or not password_ok:
        limiter.record_failure(ip, email)
        raise HTTPException(401, "invalid credentials")

    limiter.reset(ip, email)
    user_id = int(row["user_id"])
    return {
        "token": create_operator_token(user_id),
        "operator": {"user_id": user_id, "name": row["name"], "email": row["email"]},
    }
```

- [ ] **Step 9: `api/app/main.py` 등록**

다른 router import 옆에 `from app.ops.router import router as ops_router` 를 추가하고,
`app.include_router(auth_router, prefix="/auth", tags=["auth"])` 바로 아래에 다음 줄을 넣는다.

```python
app.include_router(ops_router, prefix="/ops", tags=["ops"])
```

- [ ] **Step 10: 테스트 통과 확인**

Run: `cd api && python -m pytest tests/test_ops_auth.py tests/test_c0_read_auth.py tests/test_migration_versions.py -q`
Expected: 전부 PASS, 경고 없음

- [ ] **Step 11: 변경 확인**

Run: `git status --short api/ supabase/`

---

### Task 2: `/preflight` 운영자 전용 + 진단 오진 수정

**Files:**
- Modify: `api/app/preflight.py`
- Test: `api/tests/test_preflight_ops.py`

**Interfaces:**
- Consumes: Task 1 `app.ops.deps.OperatorId`, `create_operator_token`
- Consumes: `app.reg.retrieve.retrieve_question(db, store_id, question, top_k, *, usage_context, usage_sink)` → `{"kind": "hit"|"miss", "candidates": [{"score": float, ...}], "reason"?: str}`
- Consumes: `app.contracts.usage.UsageContext`, `app.usage.DbUsageSink(pool)`, `app.deps.get_pool()`
- Produces: `GET /preflight` 응답 형식은 그대로(`ok, deep, env, blocking, settings, checks`). Task 4가 소비한다.

- [ ] **Step 1: 실패하는 테스트 작성 `api/tests/test_preflight_ops.py`**

```python
"""/preflight 운영자 전용 전환과 진단 오진 수정 (이슈 #33)."""
import asyncio
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import preflight
from app.deps import create_token, get_db
from app.ops.deps import create_operator_token

SETTINGS = SimpleNamespace(
    jwt_secret="synthetic-test-key-" * 4, jwt_algorithm="HS256", ops_token_expire_minutes=60,
    env="test", ingest_mode="mock", origins=["http://localhost:3000"],
    embedding_model="emb", gemini_model="gem", stt_model="stt",
    retrieval_threshold=0.35, confidence_threshold=0.6, storage_bucket="sources",
    supabase_db_url="postgresql://user:secret@db.example:5432/postgres")


class RoleDb:
    def __init__(self):
        self.role = "OPERATOR"

    async def fetchrow(self, sql, user_id):
        assert "from users where user_id" in sql
        return {"role": self.role} if user_id == 1 else None


class PreflightAccessTest(unittest.TestCase):
    def setUp(self):
        self.db = RoleDb()
        for target in ("app.deps.get_settings", "app.ops.deps.get_settings",
                       "app.preflight.get_settings"):
            item = patch(target, return_value=SETTINGS)
            item.start()
            self.addCleanup(item.stop)
        ok = preflight._check("x", "live")
        for name, value in (("_probe_db", [ok]), ("_probe_storage", ok), ("_probe_openai", ok),
                            ("_probe_gemini", ok), ("_probe_retrieve", ok)):
            item = patch.object(preflight, name, AsyncMock(return_value=value))
            item.start()
            self.addCleanup(item.stop)
        app = FastAPI()
        app.include_router(preflight.router)

        async def fake_db():
            yield self.db

        app.dependency_overrides[get_db] = fake_db
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def get(self, token=None, deep=False):
        headers = {"Authorization": "Bearer " + token} if token else {}
        return self.client.get("/preflight" + ("?deep=1" if deep else ""), headers=headers)

    def test_operator_gets_report(self):
        res = self.get(create_operator_token(1))
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json()["ok"])
        self.assertEqual(self.get(create_operator_token(1), deep=True).status_code, 200)

    def test_no_token_and_product_token_rejected_without_probing(self):
        product = create_token(dict(store_id=1, user_id=1, role="OWNER",
                                    exp=datetime.now(timezone.utc) + timedelta(minutes=5)))
        self.assertEqual(self.get().status_code, 401)
        self.assertEqual(self.get(deep=True).status_code, 401)
        self.assertEqual(self.get(product).status_code, 401)
        self.assertEqual(self.get(product, deep=True).status_code, 401)
        preflight._probe_openai.assert_not_called()

    def test_revoked_role_gets_403(self):
        token = create_operator_token(1)
        self.db.role = "OWNER"
        self.assertEqual(self.get(token).status_code, 403)


class FakeConn:
    def __init__(self, missing):
        self.missing = missing
        self.counted = False

    async def fetch(self, sql, names):
        assert "to_regclass" in sql
        assert set(self.missing) <= set(names)
        return [{"name": name} for name in self.missing]

    async def fetchval(self, sql, *args):
        self.counted = True
        return 1

    async def close(self):
        pass


class ProbeDbTest(unittest.TestCase):
    def run_probe(self, connect):
        with patch.object(preflight.asyncpg, "connect", connect):
            return asyncio.run(preflight._probe_db(SETTINGS))

    def test_missing_tables_named_without_connection_hint(self):
        conn = FakeConn(["knowledge_entities", "fact_revisions"])
        checks = {c["name"]: c for c in self.run_probe(AsyncMock(return_value=conn))}
        self.assertEqual(checks["데이터베이스"]["state"], "live")
        self.assertEqual(checks["스키마"]["state"], "dead")
        self.assertIn("knowledge_entities", checks["스키마"]["detail"])
        self.assertIn("fact_revisions", checks["스키마"]["detail"])
        self.assertIn("migration", checks["스키마"]["fix"])
        self.assertFalse(any("SUPABASE_DB_URL" in c["fix"] for c in checks.values()))
        # 없는 테이블을 읽는 집계는 돌리지 않는다
        self.assertFalse(conn.counted)

    def test_full_schema_runs_counts(self):
        conn = FakeConn([])
        checks = {c["name"]: c for c in self.run_probe(AsyncMock(return_value=conn))}
        self.assertEqual(checks["스키마"]["state"], "live")
        self.assertTrue(conn.counted)
        self.assertIn("시드 데이터", checks)

    def test_connection_failure_is_only_connection_row(self):
        checks = self.run_probe(AsyncMock(side_effect=OSError("connection refused")))
        self.assertEqual([c["name"] for c in checks], ["데이터베이스"])
        self.assertEqual(checks[0]["state"], "dead")
        self.assertIn("SUPABASE_DB_URL", checks[0]["fix"])
        self.assertNotIn("secret", checks[0]["detail"])


class FakePool:
    def __init__(self, store_id):
        self.store_id = store_id

    async def fetchval(self, sql, slug):
        assert "store_slug" in sql and slug == "demo-cafe"
        return self.store_id


class ProbeRetrieveTest(unittest.TestCase):
    def run_probe(self, pool, retrieve):
        with patch.object(preflight, "get_pool", return_value=pool), \
             patch.object(preflight, "retrieve_question", retrieve), \
             patch.object(preflight, "DbUsageSink", lambda p: "sink"):
            return asyncio.run(preflight._probe_retrieve(SETTINGS))

    def test_missing_demo_store_is_warn_and_skips_search(self):
        retrieve = AsyncMock()
        check = self.run_probe(FakePool(None), retrieve)
        self.assertEqual(check["state"], "warn")
        self.assertIn("demo-cafe", check["detail"])
        retrieve.assert_not_called()

    def test_hit_calls_retrieve_directly_with_development_cost(self):
        retrieve = AsyncMock(return_value={"kind": "hit", "candidates": [{"score": 0.71}]})
        check = self.run_probe(FakePool(7), retrieve)
        self.assertEqual(check["state"], "live")
        self.assertIn("0.710", check["detail"])
        args, kwargs = retrieve.call_args
        self.assertEqual(args[1], 7)
        ctx = kwargs["usage_context"]
        self.assertEqual((ctx.store_id, ctx.cost_phase, ctx.cost_purpose, ctx.stage),
                         ("7", "OPERATING", "DEVELOPMENT", "QUERY"))
        self.assertEqual(kwargs["usage_sink"], "sink")

    def test_miss_is_dead_with_reason(self):
        retrieve = AsyncMock(return_value={"kind": "miss", "reason": "below_threshold", "candidates": []})
        check = self.run_probe(FakePool(7), retrieve)
        self.assertEqual(check["state"], "dead")
        self.assertIn("below_threshold", check["detail"])

    def test_search_error_is_dead_not_401(self):
        retrieve = AsyncMock(side_effect=RuntimeError("embedding failed"))
        check = self.run_probe(FakePool(7), retrieve)
        self.assertEqual(check["state"], "dead")
        self.assertIn("embedding failed", check["detail"])
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd api && python -m pytest tests/test_preflight_ops.py -q`
Expected: FAIL (`/preflight`가 토큰 없이 200, `_probe_db`가 스키마를 분리하지 않음, `preflight.retrieve_question` 없음 등)

- [ ] **Step 3: `api/app/preflight.py` 수정**

3-1. 모듈 docstring의 두 줄을 아래로 바꾸고 맨 끝에 한 줄을 더한다.

```
    GET /preflight        DB·Storage·시드·검색까지 실제 호출 (임베딩 1회)
    GET /preflight?deep=1 위 + OpenAI·Gemini 실호출 (돈이 든다. 각 1회)

운영자 전용이다 (이슈 #33). /ops/login 이 발급한 토큰만 받는다. /health 는 공개다.
```

3-2. import를 정리한다. `os`, `httpx`(Storage 점검이 여전히 쓰므로 `httpx`는 유지), 아래를 추가한다.

```python
from uuid import uuid4

from app.contracts.usage import UsageContext
from app.deps import get_pool
from app.ops.deps import OperatorId
from app.reg.retrieve import retrieve_question
from app.usage import DbUsageSink
```

`import os`는 더 쓰지 않으므로 지운다.

3-3. `PROBE_TIMEOUT = 8.0` 아래에 상수를 추가한다.

```python
# 진단이 읽거나, 없으면 제품이 바로 깨지는 테이블. 없으면 migration 이 덜 적용된 것이다
REQUIRED_TABLES = (
    "users", "stores", "store_members", "invite_codes", "knowledge_cards", "card_embeddings",
    "ingest_jobs", "pending_questions", "owner_answers", "notification_events",
    "ai_usage_attempts", "knowledge_publications", "r_index_publications", "r_index_documents",
    "source_facts", "source_fact_occurrences", "fact_revisions", "knowledge_entities",
    "extraction_raw_responses", "upload_change_proposals",
)
DEMO_STORE_SLUG = "demo-cafe"
DEMO_QUESTION = "우유 어디 보관해요?"
```

3-4. `_probe_db`를 통째로 아래로 바꾼다.

```python
async def _missing_tables(conn) -> list[str]:
    rows = await conn.fetch(
        "select t.name from unnest($1::text[]) with ordinality as t(name, i) "
        "where to_regclass('public.' || t.name) is null order by t.i",
        list(REQUIRED_TABLES))
    return [r["name"] for r in rows]


async def _counts(conn) -> dict[str, Any]:
    return {
        "stores": await conn.fetchval("select count(*) from stores"),
        "cards": await conn.fetchval("select count(*) from knowledge_cards"),
        # store-isolation-ok: 운영 점검 화면의 전체 매장 집계
        "approved_stores": await conn.fetchval(
            "select count(distinct store_id) from knowledge_cards "
            "where review_status = 'APPROVED' and is_verified "
            "and published_version_id is not null"),
        # store-isolation-ok: 운영 점검 화면의 전체 매장 집계
        "indexed_stores": await conn.fetchval(
            "select count(*) from knowledge_publications p "
            "join r_index_publications a on a.store_id = p.store_id "
            "and a.snapshot_id = p.current_snapshot_id"),
        "vector_ext": await conn.fetchval(
            "select count(*) from pg_extension where extname = 'vector'"),
        "match_cards": await conn.fetchval(
            "select count(*) from pg_proc where proname = 'match_cards'"),
    }


async def _probe_db(s) -> list[dict]:
    """연결과 스키마를 따로 본다. 테이블이 없는 것을 연결 문제로 안내하지 않는다."""
    host = s.supabase_db_url.split("@")[-1].split("/")[0] if "@" in s.supabase_db_url else "?"
    conn, err, ms = await _timed(asyncpg.connect(s.supabase_db_url, timeout=PROBE_TIMEOUT))
    if err:
        return [_check("데이터베이스", "dead", host,
                       "SUPABASE_DB_URL 확인. 호스팅은 Connection pooling 문자열을 쓴다"
                       f" — {err}", ms)]
    try:
        out = [_check("데이터베이스", "live", host, ms=ms)]

        missing, err, ms = await _timed(_missing_tables(conn))
        if err:
            out.append(_check("스키마", "dead", str(err)[:90], "DB 계정 권한을 확인한다", ms))
            return out
        if missing:
            out.append(_check("스키마", "dead", "없는 테이블: " + ", ".join(missing),
                              "밀린 migration 을 적용한다 (supabase db push)", ms))
            # 아래 집계는 이 테이블들을 읽으므로 돌리지 않는다
            return out
        out.append(_check("스키마", "live", f"필수 테이블 {len(REQUIRED_TABLES)}개 있음", ms=ms))

        data, err, ms = await _timed(_counts(conn))
        if err:
            out.append(_check("집계", "dead", str(err)[:90], "", ms))
            return out
    finally:
        await conn.close()

    out.append(
        _check("pgvector", "live", "확장 + match_cards() 준비됨")
        if data["vector_ext"] and data["match_cards"]
        else _check("pgvector", "dead",
                    f"extension={bool(data['vector_ext'])} match_cards={bool(data['match_cards'])}",
                    "밀린 migration 을 적용한다 (supabase db push)")
    )
    out.append(
        _check("시드 데이터", "live", f"매장 {data['stores']} · 카드 {data['cards']}")
        if data["stores"] and data["cards"]
        else _check("시드 데이터", "dead", f"매장 {data['stores']} · 카드 {data['cards']}",
                    "db/002_seed_demo.sql 실행")
    )
    index_label = f"승인 카드 매장 {data['approved_stores']} · 색인 매장 {data['indexed_stores']}"
    out.append(
        _check("공개 색인", "live", index_label)
        if data["indexed_stores"] >= data["approved_stores"]
        else _check("공개 색인", "dead", f"{index_label} — 색인 없는 매장은 검색이 안 된다",
                    "api 에서 python scripts/bootstrap_store_index.py --apply 실행")
    )
    return out
```

3-5. `_probe_retrieve`를 통째로 아래로 바꾼다.

```python
async def _probe_retrieve(s) -> dict:
    """검색 게이트가 실제로 hit 을 내는지. 데모 매장으로 확인한다.

    HTTP 로 자기 자신을 부르지 않는다 — /reg/retrieve 는 매장 JWT 가 필요하다.
    retrieve_question 을 직접 불러 임베딩·pgvector·게이트를 한 번에 통과시킨다.
    임베딩 비용은 개발 목적으로 기록해 고객 월 운영비(D21)에 섞지 않는다.
    """
    try:
        pool = get_pool()
    except RuntimeError as e:
        return _check("검색 게이트", "dead", str(e), "위 데이터베이스 줄을 먼저 본다")

    async def run():
        # store-isolation-ok: 데모 매장 slug 로 점검 대상 store_id 를 찾는다
        store_id = await pool.fetchval(
            "select store_id from stores where store_slug = $1", DEMO_STORE_SLUG)
        if store_id is None:
            return None
        store_id = int(store_id)
        return await retrieve_question(
            pool, store_id, DEMO_QUESTION, 3,
            usage_context=UsageContext(
                store_id=str(store_id), cost_phase="OPERATING", cost_purpose="DEVELOPMENT",
                stage="QUERY", logical_call_id=f"preflight:{uuid4().hex}"),
            usage_sink=DbUsageSink(pool))

    result, err, ms = await _timed(run())
    if err:
        return _check("검색 게이트", "dead", str(err)[:90],
                      "대개 임베딩 호출 실패다. 위 OpenAI 줄을 먼저 본다", ms)
    if result is None:
        return _check("검색 게이트", "warn", f"데모 매장({DEMO_STORE_SLUG}) 없음 — 점검 생략",
                      "운영 DB 에는 시드가 없을 수 있다", ms)
    if result["kind"] == "hit":
        top = (result.get("candidates") or [{}])[0].get("score", 0)
        return _check("검색 게이트", "live", f"hit · 최고점 {float(top):.3f}", ms=ms)
    return _check("검색 게이트", "dead",
                  f"miss ({result.get('reason')}) — 임계 {s.retrieval_threshold}",
                  "시드 임베딩이 없거나 RETRIEVAL_THRESHOLD 가 너무 높다", ms)
```

3-6. 엔드포인트 서명을 바꾸고 호출 기록을 남긴다.

```python
@router.get("/preflight")
async def preflight(operator_id: OperatorId,
                    deep: bool = Query(False, description="LLM 실호출 포함. 돈이 든다")):
    s = get_settings()
    logger.info("preflight operator=%s deep=%s", operator_id, deep)
```

나머지 본문(`asyncio.gather` 이하)은 그대로 둔다.

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd api && python -m pytest tests/test_preflight_ops.py tests/test_ops_auth.py -q`
Expected: 전부 PASS

- [ ] **Step 5: 전체 API 테스트**

Run: `cd api && mkdir -p tmp && python -m pytest tests -q --basetemp=tmp/ci-pytest`
Expected: 전부 PASS (새 실패 없음)

- [ ] **Step 6: 변경 확인**

Run: `git status --short api/`

---

### Task 3: 운영자 계정 생성 스크립트

**Files:**
- Create: `api/scripts/create_operator.py`
- Test: `api/tests/test_create_operator.py`

**Interfaces:**
- Consumes: `app.auth.router._hash_password(password: str) -> str`, settings `supabase_db_url`
- Produces: `python scripts/create_operator.py --email <이메일> --name <이름>`. 비밀번호는 getpass 두 번.

- [ ] **Step 1: 실패하는 테스트 작성 `api/tests/test_create_operator.py`**

```python
"""운영자 계정 생성 스크립트 (이슈 #33)."""
import asyncio
import importlib.util
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parents[1] / "scripts/create_operator.py"
_spec = importlib.util.spec_from_file_location("create_operator", _PATH)
create_operator = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(create_operator)


def prompts(*answers):
    it = iter(answers)
    return lambda _label: next(it)


def test_password_must_match_twice():
    with pytest.raises(SystemExit):
        create_operator.read_password(prompts("long-enough-pass", "different-pass!"))


def test_password_min_length():
    with pytest.raises(SystemExit):
        create_operator.read_password(prompts("short", "short"))


def test_password_accepted():
    assert create_operator.read_password(prompts("long-enough-pass", "long-enough-pass")) == "long-enough-pass"


def test_password_is_not_an_argument():
    with pytest.raises(SystemExit):
        create_operator.parse_args(["--email", "ops@example.com", "--name", "운영자",
                                    "--password", "long-enough-pass"])


class Conn:
    def __init__(self, row):
        self.row = row
        self.sql = None
        self.args = None

    async def fetchrow(self, sql, *args):
        self.sql, self.args = sql, args
        return self.row


def test_insert_operator_role_without_overwriting():
    conn = Conn({"user_id": 9})
    user_id = asyncio.run(create_operator.insert_operator(conn, "ops@example.com", "운영자", "hash"))
    assert user_id == 9
    assert "'OPERATOR'" in conn.sql
    assert "on conflict (email) do nothing" in conn.sql
    assert "update" not in conn.sql.lower()
    assert conn.args == ("운영자", "ops@example.com", "hash")


def test_existing_email_fails_without_promotion():
    with pytest.raises(SystemExit):
        asyncio.run(create_operator.insert_operator(Conn(None), "owner@example.com", "점주", "hash"))
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd api && python -m pytest tests/test_create_operator.py -q`
Expected: FAIL (`FileNotFoundError` — 스크립트 없음)

- [ ] **Step 3: `api/scripts/create_operator.py` 작성**

```python
"""운영자 계정 생성 (이슈 #33).

  python scripts/create_operator.py --email ops@example.com --name 운영자
  운영 서버: docker compose exec api python scripts/create_operator.py --email ... --name ...

비밀번호는 getpass 로 두 번 받는다. 인자·환경변수로 받지 않는다 (셸 기록에 남지 않게).
같은 이메일이 이미 있으면 역할을 바꾸지 않고 실패한다. 기존 점주 계정을 운영자로 승격하지 않는다.
"""
from __future__ import annotations

import argparse
import asyncio
import getpass
import sys
from collections.abc import Callable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import asyncpg  # noqa: E402

from app.auth.router import _hash_password  # noqa: E402
from app.config import get_settings  # noqa: E402

MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 128  # /ops/login 요청 상한과 같다
MAX_NAME_LENGTH = 50  # users.name varchar(50)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="운영자 계정 생성")
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", required=True)
    return parser.parse_args(argv)


def read_password(prompt: Callable[[str], str] = getpass.getpass) -> str:
    first = prompt("비밀번호: ")
    second = prompt("비밀번호 확인: ")
    if first != second:
        raise SystemExit("두 비밀번호가 다르다")
    if not MIN_PASSWORD_LENGTH <= len(first) <= MAX_PASSWORD_LENGTH:
        raise SystemExit(f"비밀번호는 {MIN_PASSWORD_LENGTH}~{MAX_PASSWORD_LENGTH}자")
    return first


async def insert_operator(conn, email: str, name: str, password_hash: str) -> int:
    # store-isolation-ok: 운영자는 매장에 속하지 않는 users 행이다
    row = await conn.fetchrow(
        "insert into users (name, email, password_hash, role) "
        "values ($1, $2, $3, 'OPERATOR') "
        "on conflict (email) do nothing returning user_id",
        name, email, password_hash)
    if row is None:
        raise SystemExit("같은 이메일이 이미 있다. 기존 계정은 운영자로 바꾸지 않는다")
    return int(row["user_id"])


async def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    email = args.email.strip().lower()
    name = args.name.strip()
    if not name or len(name) > MAX_NAME_LENGTH:
        raise SystemExit(f"이름은 1~{MAX_NAME_LENGTH}자")
    password = read_password()
    conn = await asyncpg.connect(get_settings().supabase_db_url)
    try:
        user_id = await insert_operator(conn, email, name, _hash_password(password))
    finally:
        await conn.close()
    print(f"운영자 생성: user_id={user_id} email={email}")


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd api && python -m pytest tests/test_create_operator.py -q`
Expected: PASS

- [ ] **Step 5: 로컬 DB에서 한 번 실행 (로컬 Supabase가 떠 있을 때만)**

Run: `cd api && supabase migration up --local 2>/dev/null; python scripts/create_operator.py --email ops@example.com --name 운영자` (비밀번호 12자 이상 두 번 입력)
Expected: `운영자 생성: user_id=...`. 같은 명령을 다시 실행하면 "같은 이메일이 이미 있다"로 실패. 로컬 DB가 없으면 이 단계는 생략하고 보고에 적는다.

- [ ] **Step 6: 변경 확인**

Run: `git status --short api/`

---

### Task 4: Web `/preflight` 운영자 로그인 화면

**Files:**
- Modify: `web/lib/api.ts` (`FetchJsonInit`, `fetchJson`의 401 처리, `getPreflight`, `opsLogin` 추가)
- Create: `web/lib/ops-session.ts`
- Modify: `web/lib/query.ts` (`preflightQuery`)
- Modify: `web/app/preflight/page.tsx`

**Interfaces:**
- Consumes: Task 1 `POST /ops/login`, Task 2 `GET /preflight` (Authorization 필요)
- Produces: `opsLogin(email, password): Promise<OperatorLogin>`, `getPreflight(deep, token, signal?)`, `useOpsToken(): string | null`, `setOpsToken(token | null)`, `withOpsSession(run)`, `preflightQuery(token)`

- [ ] **Step 1: 현재 사용처 확인**

Run: `grep -rn "getPreflight\|preflightQuery" web --include=*.ts --include=*.tsx | grep -v node_modules | grep -v .next`
Expected: `web/lib/api.ts`, `web/lib/query.ts`, `web/app/preflight/page.tsx`만 나온다. 다른 곳이 있으면 같은 Task에서 새 서명으로 고친다.

- [ ] **Step 2: `web/lib/api.ts` — 세션 만료 이벤트를 끌 수 있게**

`type FetchJsonInit = RequestInit & { timeoutMs?: number };` 를 아래로 바꾼다.

```ts
// sessionExpiry=false: 운영자 호출의 401 이 같은 탭의 제품 로그인을 끊지 않게 한다
type FetchJsonInit = RequestInit & { timeoutMs?: number; sessionExpiry?: boolean };
```

`fetchJson` 첫 줄의 구조 분해를 `const { timeoutMs = TIMEOUT_MS, sessionExpiry = true, ...fetchInit } = init ?? {};` 로 바꾸고,
401 분기 조건을 `if (sessionExpiry && res.status === 401 && new Headers(fetchInit.headers).has("Authorization")) {` 로 바꾼다.

- [ ] **Step 3: `web/lib/api.ts` — 진단·운영자 로그인 호출**

기존 `getPreflight`를 아래로 바꾸고 바로 뒤에 `opsLogin`을 둔다.

```ts
// /preflight 는 운영자 전용이다. 운영자 토큰은 제품 세션과 따로 다룬다.
export async function getPreflight(deep: boolean, token: string, signal?: AbortSignal) {
  return fetchJson<PreflightReport>(`/preflight${deep ? "?deep=1" : ""}`, {
    cache: "no-store",
    timeoutMs: deep ? 60_000 : TIMEOUT_MS,
    signal,
    headers: authHeader(token),
    sessionExpiry: false,
  });
}

export type OperatorLogin = {
  token: string;
  operator: { user_id: number; name: string; email: string };
};

export async function opsLogin(email: string, password: string) {
  return fetchJson<OperatorLogin>("/ops/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
    sessionExpiry: false,
  });
}
```

- [ ] **Step 4: `web/lib/ops-session.ts` 작성**

```ts
// 운영자 토큰 저장소. sessionStorage 에 둬 탭을 닫으면 사라지고, 제품 로그인(localStorage)과 섞지 않는다.
// 화면 컴포넌트는 토큰 수명을 직접 다루지 않고 이 모듈만 거친다.
import { useSyncExternalStore } from "react";
import { ApiError } from "@/lib/api";

const KEY = "askbuddy:ops-token";
const listeners = new Set<() => void>();

function read(): string | null {
  try {
    return window.sessionStorage.getItem(KEY);
  } catch {
    return null;
  }
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function setOpsToken(token: string | null) {
  try {
    if (token) window.sessionStorage.setItem(KEY, token);
    else window.sessionStorage.removeItem(KEY);
  } catch {
    // 저장소를 못 쓰는 환경이면 이번 화면에서만 로그인 상태가 유지되지 않는다
  }
  listeners.forEach((listener) => listener());
}

export function useOpsToken(): string | null {
  return useSyncExternalStore(subscribe, read, () => null);
}

// 401(토큰 없음·만료)·403(역할 회수)이면 토큰을 지워 로그인 폼으로 돌려보낸다
export async function withOpsSession<T>(run: () => Promise<T>): Promise<T> {
  try {
    return await run();
  } catch (error) {
    if (error instanceof ApiError && (error.status === 401 || error.status === 403)) setOpsToken(null);
    throw error;
  }
}
```

- [ ] **Step 5: `web/lib/query.ts` — `preflightQuery`**

기존 `preflightQuery`를 아래로 바꾸고, 파일 위쪽 import에 `withOpsSession`을 추가한다(`import { withOpsSession } from "@/lib/ops-session";`).

```ts
export function preflightQuery(token: string) {
  return queryOptions({
    queryKey: ["preflight", token, false] as const,
    queryFn: ({ signal }) => withOpsSession(() => getPreflight(false, token, signal)),
    staleTime: 10_000,
    // 인증 실패는 다시 시도해도 같다. 바로 로그인 폼으로 돌린다
    retry: (count, error) =>
      !(error instanceof ApiError && (error.status === 401 || error.status === 403)) && count < 2,
  });
}
```

`ApiError`가 query.ts에 import돼 있지 않으면 `@/lib/api` import 목록에 추가한다.

- [ ] **Step 6: `web/app/preflight/page.tsx` 교체**

```tsx
"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, apiErrorMessage, getPreflight, opsLogin, type PreflightReport } from "@/lib/api";
import { setOpsToken, useOpsToken, withOpsSession } from "@/lib/ops-session";
import { preflightQuery } from "@/lib/query";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
type Check = PreflightReport["checks"][number];
const DOT: Record<Check["state"], string> = { live: "bg-brand-500", warn: "bg-warn-500", dead: "bg-danger-500" };
const LABEL: Record<Check["state"], string> = { live: "연결됨", warn: "미확인", dead: "끊김" };

export default function PreflightPage() {
  const token = useOpsToken();
  return (
    <main className="mx-auto max-w-2xl px-6 py-12">
      <header className="mb-8"><Link href="/" aria-label="뒤로가기" className="mb-4 inline-flex min-h-11 items-center gap-1.5 rounded-lg px-2 text-sm font-semibold text-muted hover:bg-surface-muted hover:text-foreground">← 처음으로</Link><p className="font-mono text-xs uppercase tracking-[0.2em] text-muted">preflight</p><h1 className="mt-2 text-2xl font-bold text-brand-700">배선 점검</h1><p className="mt-2 text-sm text-muted">운영자 전용 화면입니다. 배포한 뒤에 이 줄들이 전부 초록이어야 합니다.</p><p className="mt-1 font-mono text-xs text-muted">{API}</p></header>
      {token ? <Diagnostics token={token} /> : <OperatorLogin />}
    </main>
  );
}

function loginErrorMessage(error: unknown): string {
  if (error instanceof ApiError && error.status === 401) return "이메일 또는 비밀번호가 맞지 않습니다.";
  if (error instanceof ApiError && error.status === 429) return "실패가 반복돼 잠시 막혔습니다. 15분 뒤 다시 시도해주세요.";
  return apiErrorMessage(error, "로그인하지 못했습니다.");
}

function OperatorLogin() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const login = useMutation({
    mutationFn: () => opsLogin(email.trim(), password),
    onSuccess: (result) => setOpsToken(result.token),
  });
  function submit(event: FormEvent) {
    event.preventDefault();
    if (!login.isPending) login.mutate();
  }
  return (
    <form onSubmit={submit} className="rounded-2xl bg-surface px-5 py-5 shadow-sm">
      <h2 className="text-sm font-bold text-brand-700">운영자 로그인</h2>
      <label className="mt-4 block text-xs font-semibold text-muted" htmlFor="ops-email">이메일</label>
      <input id="ops-email" type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} className="mt-1 h-11 w-full rounded-lg border border-border px-3 text-sm" />
      <label className="mt-3 block text-xs font-semibold text-muted" htmlFor="ops-password">비밀번호</label>
      <input id="ops-password" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} className="mt-1 h-11 w-full rounded-lg border border-border px-3 text-sm" />
      {login.error && <p role="alert" className="mt-3 text-sm text-danger-700">{loginErrorMessage(login.error)}</p>}
      <button type="submit" disabled={login.isPending} className="mt-4 h-11 w-full rounded-full bg-brand-600 text-sm font-semibold text-white disabled:opacity-40">{login.isPending ? "확인 중…" : "로그인"}</button>
    </form>
  );
}

function Diagnostics({ token }: { token: string }) {
  const queryClient = useQueryClient();
  const shallow = useQuery(preflightQuery(token));
  const deep = useMutation({ mutationFn: () => withOpsSession(() => getPreflight(true, token)) });
  const report = deep.data ?? shallow.data;
  const error = deep.error ?? shallow.error;
  const busy = deep.isPending || shallow.isFetching;
  function logout() {
    queryClient.removeQueries({ queryKey: ["preflight"] });
    setOpsToken(null);
  }
  return (
    <>
      {error && <div className="mb-5 rounded-2xl bg-danger-50 px-4 py-3 text-danger-700"><p className="text-sm font-bold">백엔드에 닿지 못했습니다 — {error instanceof Error ? error.message : "연결 오류"}</p><ul className="mt-2 list-disc pl-5 text-xs leading-relaxed"><li>API 서버 상태</li><li>웹 배포의 NEXT_PUBLIC_API_URL</li><li>API 서버의 ALLOWED_ORIGINS 설정</li></ul></div>}
      {report && <div className={`mb-5 rounded-2xl px-4 py-3 ${report.ok ? "bg-brand-50 text-brand-700" : "bg-danger-50 text-danger-700"}`}><p className="text-sm font-bold">{report.ok ? `전부 연결됐습니다 (env=${report.env})` : `막는 항목 ${report.blocking.length}개 — ${report.blocking.join(", ")}`}</p></div>}
      <section className="rounded-2xl bg-surface px-5 py-1 shadow-sm"><ul><Row name="프론트엔드" state="live" detail="Next.js 렌더링 정상" fix="" ms={null} />{report?.checks.map((check) => <Row key={check.name} {...check} />)}{!report && !error && <li className="py-4 text-sm text-muted">점검 중…</li>}</ul></section>
      <div className="mt-4 flex flex-wrap gap-2"><button onClick={() => void shallow.refetch()} disabled={busy} className="h-11 rounded-full border border-border px-4 text-sm font-semibold disabled:opacity-40">{shallow.isFetching ? "점검 중…" : "다시 점검"}</button><button onClick={() => deep.mutate()} disabled={busy} className="h-11 rounded-full bg-brand-600 px-4 text-sm font-semibold text-white disabled:opacity-40">{deep.isPending ? "실호출 중…" : "LLM까지 실호출"}</button><button onClick={logout} className="h-11 rounded-full px-4 text-sm font-semibold text-muted hover:bg-surface-muted">로그아웃</button></div><p className="mt-2 text-xs text-muted">LLM 실호출은 OpenAI·Gemini를 한 번씩 호출하므로 요금이 발생합니다.</p>
      {report && <section className="mt-8"><h2 className="text-sm font-bold text-brand-700">현재 설정</h2><dl className="mt-2 rounded-2xl bg-surface px-5 py-3 shadow-sm">{Object.entries(report.settings).map(([key, value]) => <div key={key} className="flex justify-between gap-4 border-b border-border py-1.5 last:border-0"><dt className="font-mono text-xs text-muted">{key}</dt><dd className="font-mono text-xs">{String(value)}</dd></div>)}</dl></section>}
    </>
  );
}

function Row({ name, state, detail, fix, ms }: Check) {
  return <li className="flex gap-3 border-b border-border py-3 last:border-0"><span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${DOT[state]} ${state === "warn" ? "motion-safe:animate-pulse" : ""}`} aria-hidden /><div className="min-w-0 flex-1"><div className="flex items-center justify-between gap-3"><p className="text-sm font-semibold">{name}</p><span className="text-xs font-bold text-muted">{LABEL[state]}{ms !== null ? ` · ${ms}ms` : ""}</span></div><p className="mt-0.5 text-xs text-muted">{detail}</p>{fix && <p className="mt-1 text-xs text-danger-500">{fix}</p>}</div></li>;
}
```

- [ ] **Step 7: 정적 검사**

Run: `cd web && pnpm check`
Expected: lint·typecheck·build 통과. 실패하면 고치고 다시 실행한다.

- [ ] **Step 8: 브라우저 확인 (가능할 때만)**

API(`uvicorn`)와 Web(`pnpm dev`)을 띄울 수 있으면 `/preflight`에서 확인한다: 로그인 폼 → 틀린 비밀번호 문구 → 운영자 로그인 → 진단 표시 → 로그아웃 → 로그인 폼. 띄울 수 없으면 "브라우저 미확인"으로 보고한다. `pnpm check` 통과를 브라우저 확인으로 적지 않는다.

- [ ] **Step 9: 변경 확인**

Run: `git status --short web/`

---

### Task 5: 계약 문서

**Files:**
- Modify: `docs/dev/ASKBUDDY_MVP_CURRENT.md` §18-1 표, §19-1 목록
- Modify: `docs/dev/plan/OPS_OPERATOR_ACCESS_DESIGN.md` 상태 줄

- [ ] **Step 1: §18-1 표**

인증 줄을 아래로 바꾼다.

```
| 인증 | `/auth/signup`, `/auth/login`, `/auth/join`, `/auth/stores`, `/auth/invites`, 운영자 `/ops/login` |
```

진단 줄을 아래로 바꾼다.

```
| 진단 | `/health`(공개), `/preflight`(운영자 전용, `/ops/login` 토큰) |
```

- [ ] **Step 2: §19-1 목록 끝에 추가**

```
- 운영자(`users.role = 'OPERATOR'`)는 어느 매장에도 소속되지 않는다. 운영자 토큰(`aud=askbuddy-ops`, `store_id` 없음, 60분)은 매장 API에 쓸 수 없다. 제품 `get_claims`가 `aud` 있는 토큰을 거부한다.
- 운영자 의존성은 요청마다 `users.role`을 다시 확인한다. 역할을 회수하면 남은 토큰도 403이 된다. 운영자의 매장 데이터 열람 범위는 CS 설계에서 따로 정한다.
```

- [ ] **Step 3: 설계 문서 상태 줄**

`OPS_OPERATOR_ACCESS_DESIGN.md` 2번째 줄의 `상태: **설계만 확정, 구현 보류.**` 를 `상태: **구현됨, 운영 반영 전.** 구현 계획 [OPS_OPERATOR_ACCESS_PLAN.md](OPS_OPERATOR_ACCESS_PLAN.md).` 로 바꾼다. 나머지 문장은 그대로 둔다.

- [ ] **Step 4: 변경 확인**

Run: `git diff --stat docs/dev`
