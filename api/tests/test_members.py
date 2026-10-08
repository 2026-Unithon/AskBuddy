import jwt
"""직원 관리·합류 승인·내보내기 (이슈 #37)."""
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.deps import CurrentStoreId, create_token, get_db

SETTINGS = SimpleNamespace(jwt_secret="synthetic-test-key-" * 4, jwt_algorithm="HS256")


def bearer(**claims):
    claims.setdefault("exp", datetime.now(timezone.utc) + timedelta(minutes=5))
    return {"Authorization": "Bearer " + create_token(claims)}


class MembershipDb:
    def __init__(self, removed: bool):
        self.removed = removed

    async def fetchrow(self, sql, *args):
        assert "removed_at is null" in sql, sql
        return None if self.removed else {"member_role": "STAFF"}


class StoreGateTest(unittest.TestCase):
    def _client(self, removed):
        p = patch("app.deps.get_settings", return_value=SETTINGS)
        p.start()
        self.addCleanup(p.stop)
        app = FastAPI()

        @app.get("/store-only")
        async def store_only(store_id: CurrentStoreId):
            return {"store_id": store_id}

        db = MembershipDb(removed)

        async def fake_db():
            yield db

        app.dependency_overrides[get_db] = fake_db
        return TestClient(app)

    def test_active_member_passes(self):
        res = self._client(False).get("/store-only", headers=bearer(user_id=5, store_id=1, role="STAFF"))
        self.assertEqual(res.status_code, 200)

    def test_removed_member_blocked_with_live_token(self):
        res = self._client(True).get("/store-only", headers=bearer(user_id=5, store_id=1, role="STAFF"))
        self.assertEqual(res.status_code, 403)

from app.members import invites
from app.members import router as members_router_module
from app.auth import router as auth_router_module
from app.errors import install_error_handlers


class FakeInviteDb:
    def __init__(self):
        self.rows = []  # dict(invite_id, store_id, code, revoked_at)

    def transaction(self):
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def tx():
            yield
        return tx()

    async def fetchval(self, sql, *args):
        if "select code from invite_codes" in sql:
            row = next((r for r in self.rows if r["store_id"] == args[0] and r["revoked_at"] is None), None)
            return row["code"] if row else None
        if sql.lstrip().startswith("insert into invite_codes"):
            self.rows.append(dict(invite_id=len(self.rows) + 1, store_id=args[0], code=args[1], revoked_at=None))
            return args[1]
        raise AssertionError(sql)

    async def execute(self, sql, *args):
        if sql.startswith("select store_id from stores"):
            return
        if sql.lstrip().startswith("update invite_codes set revoked_at"):
            for r in self.rows:
                if r["store_id"] == args[0] and r["revoked_at"] is None:
                    r["revoked_at"] = "now"
            return
        raise AssertionError(sql)

    async def fetchrow(self, sql, *args):
        if "from invite_codes i" in sql:
            row = next((r for r in self.rows if r["code"] == args[0] and r["revoked_at"] is None), None)
            return dict(invite_id=row["invite_id"], store_id=row["store_id"], store_name="테스트카페") if row else None
        if "from store_members" in sql:
            # get_store_id 경계: user 1 은 점주, 그 밖은 직원
            return {"member_role": "OWNER" if args[1] == 1 else "STAFF"}
        raise AssertionError(sql)


class InviteLinkTest(unittest.TestCase):
    def setUp(self):
        settings = SimpleNamespace(**vars(SETTINGS), web_base_url="https://askbuddy.kr")
        for target in ("app.deps.get_settings", "app.members.invites.get_settings"):
            p = patch(target, return_value=settings)
            p.start()
            self.addCleanup(p.stop)
        self.db = FakeInviteDb()
        app = FastAPI()
        install_error_handlers(app)
        app.include_router(members_router_module.router, prefix="/members")
        app.include_router(auth_router_module.router, prefix="/auth")

        async def fake_db():
            yield self.db

        app.dependency_overrides[get_db] = fake_db
        self.client = TestClient(app)
        self.owner = bearer(user_id=1, store_id=1, role="OWNER")

    def test_token_is_long_and_url_safe(self):
        token = invites.new_token()
        self.assertGreaterEqual(len(token), 22)
        self.assertRegex(token, r"^[A-Za-z0-9_-]+$")

    def test_get_creates_once_then_reuses(self):
        a = self.client.get("/members/invite-link", headers=self.owner).json()["url"]
        b = self.client.get("/members/invite-link", headers=self.owner).json()["url"]
        self.assertEqual(a, b)
        self.assertTrue(a.startswith("https://askbuddy.kr/join/"))
        self.assertEqual(len(self.db.rows), 1)

    def test_rotate_invalidates_previous_link(self):
        old = self.client.get("/members/invite-link", headers=self.owner).json()["url"].rsplit("/", 1)[1]
        new = self.client.post("/members/invite-link/rotate", headers=self.owner).json()["url"].rsplit("/", 1)[1]
        self.assertNotEqual(old, new)
        self.assertEqual(self.client.get(f"/auth/invites/{old}").status_code, 404)
        self.assertEqual(self.client.get(f"/auth/invites/{new}").json(), {"store_name": "테스트카페"})

    def test_preview_unknown_token_404_same_shape(self):
        res = self.client.get("/auth/invites/doesnotexist000000000")
        self.assertEqual(res.status_code, 404)
        self.assertEqual(res.json()["error"]["code"], "INVITE_INVALID")

    def test_staff_cannot_manage_links(self):
        staff = bearer(user_id=5, store_id=1, role="STAFF")
        self.assertEqual(self.client.get("/members/invite-link", headers=staff).status_code, 403)

from app.members.join_requests import JoinRefused, decide_join, status_from_rows


class DecideJoinTest(unittest.TestCase):
    def test_request_when_no_store(self):
        self.assertEqual(decide_join(user_role="STAFF", active_store_id=None, invite_store_id=1), "REQUEST")

    def test_already_member_of_same_store(self):
        self.assertEqual(decide_join(user_role="STAFF", active_store_id=1, invite_store_id=1), "ALREADY_MEMBER")

    def test_owner_refused(self):
        with self.assertRaises(JoinRefused) as ctx:
            decide_join(user_role="OWNER", active_store_id=1, invite_store_id=1)
        self.assertEqual((ctx.exception.code, ctx.exception.status), ("ROLE_CONFLICT", 403))

    def test_other_store_refused(self):
        with self.assertRaises(JoinRefused) as ctx:
            decide_join(user_role="STAFF", active_store_id=2, invite_store_id=1)
        self.assertEqual((ctx.exception.code, ctx.exception.status), ("ALREADY_IN_OTHER_STORE", 409))


class JoinStatusTest(unittest.TestCase):
    def test_no_request(self):
        self.assertEqual(status_from_rows(None, active_member=False), {"status": "NONE", "store_name": None})

    def test_pending_and_rejected_pass_through(self):
        for status in ("PENDING", "REJECTED"):
            row = {"status": status, "store_name": "테스트카페"}
            self.assertEqual(status_from_rows(row, active_member=False)["status"], status)

    def test_approved_but_removed_is_removed(self):
        row = {"status": "APPROVED", "store_name": "테스트카페"}
        self.assertEqual(status_from_rows(row, active_member=False)["status"], "REMOVED")
        self.assertEqual(status_from_rows(row, active_member=True)["status"], "APPROVED")


class JoinRequestEndpointTest(unittest.TestCase):
    """로그인한 알바가 초대 링크로 합류 요청을 보낸다."""

    def setUp(self):
        settings = SimpleNamespace(**vars(SETTINGS), web_base_url="https://askbuddy.kr",
                                   access_token_expire_minutes=60, refresh_token_expire_days=90,
                                   auth_cookie_secure=True, origins=["https://askbuddy.kr"])
        for target in ("app.deps.get_settings", "app.auth.session.get_settings",
                       "app.members.invites.get_settings"):
            p = patch(target, return_value=settings)
            p.start()
            self.addCleanup(p.stop)
        self.calls = []
        self.delivered = []
        self.active = {5: None, 6: 1, 8: 2}  # user_id → 활성 매장

        async def resolve(db, *, token):
            ok = token == "good-token-0000000"
            return {"invite_id": 9, "store_id": 1, "store_name": "테스트카페"} if ok else None

        async def active_store_id(db, *, user_id):
            return self.active.get(user_id)

        async def request_join(db, **kw):
            self.calls.append(kw)
            return 77, 11

        async def deliver(store_id, notification_id):
            self.delivered.append((store_id, notification_id))

        for target, fn in (("app.auth.router.invites.resolve", resolve),
                           ("app.auth.router.active_store_id", active_store_id),
                           ("app.auth.router.join_requests.request_join", request_join),
                           ("app.auth.router.deliver_notification", deliver)):
            q = patch(target, side_effect=fn)
            q.start()
            self.addCleanup(q.stop)

        class Db:
            async def fetchval(self, sql, *args):
                if "select name from users" in sql:
                    return "새알바"
                raise AssertionError(sql)

        app = FastAPI()
        install_error_handlers(app)
        app.include_router(auth_router_module.router, prefix="/auth")
        db = Db()

        async def fake_db():
            yield db

        app.dependency_overrides[get_db] = fake_db
        self.client = TestClient(app)

    def post(self, token, headers):
        return self.client.post("/auth/join-requests", json={"invite_token": token}, headers=headers)

    def test_storeless_staff_creates_request_and_notifies_owner(self):
        res = self.post("good-token-0000000", bearer(user_id=5, role="STAFF"))
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), {"status": "PENDING", "store_name": "테스트카페"})
        self.assertEqual(self.calls[0] | {}, {"store_id": 1, "user_id": 5, "invite_id": 9, "staff_name": "새알바"})
        self.assertEqual(self.delivered, [(1, 11)])

    def test_already_member_does_not_request(self):
        res = self.post("good-token-0000000", bearer(user_id=6, store_id=1, role="STAFF"))
        self.assertEqual(res.json(), {"status": "ALREADY_MEMBER", "store_name": "테스트카페"})
        self.assertEqual(self.calls, [])

    def test_owner_token_refused(self):
        res = self.post("good-token-0000000", bearer(user_id=6, store_id=1, role="OWNER"))
        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.json()["error"]["code"], "ROLE_CONFLICT")

    def test_member_of_other_store_refused(self):
        res = self.post("good-token-0000000", bearer(user_id=8, store_id=2, role="STAFF"))
        self.assertEqual(res.status_code, 409)
        self.assertEqual(res.json()["error"]["code"], "ALREADY_IN_OTHER_STORE")

    def test_invalid_link_and_no_login(self):
        res = self.post("revoked-token-0000", bearer(user_id=5, role="STAFF"))
        self.assertEqual(res.status_code, 404)
        self.assertEqual(res.json()["error"]["code"], "INVITE_INVALID")
        self.assertEqual(self.post("good-token-0000000", {}).status_code, 401)
        self.assertEqual(self.calls, [])


class StaffSignupTest(unittest.TestCase):
    """알바는 초대 없이 가입할 수 있다. 매장 없는 계정이 된다."""

    def setUp(self):
        settings = SimpleNamespace(**vars(SETTINGS), access_token_expire_minutes=60,
                                   refresh_token_expire_days=90, auth_cookie_secure=True,
                                   origins=["https://askbuddy.kr"])
        for target in ("app.deps.get_settings", "app.auth.session.get_settings"):
            p = patch(target, return_value=settings)
            p.start()
            self.addCleanup(p.stop)

        async def start_session(db, response, *, user_id):
            response.set_cookie("ab_refresh", "x")

        q = patch("app.auth.router.start_session", side_effect=start_session)
        q.start()
        self.addCleanup(q.stop)

        class Db:
            async def fetchrow(self, sql, *args):
                if "from users where email" in sql:
                    return None
                if sql.lstrip().startswith("insert into users"):
                    return {"user_id": 5, "name": args[0], "email": args[2], "role": args[4]}
                raise AssertionError(sql)

            async def execute(self, sql, *args):
                raise AssertionError("store_members 에 쓰면 안 된다: " + sql)

        app = FastAPI()
        install_error_handlers(app)
        app.include_router(auth_router_module.router, prefix="/auth")
        db = Db()

        async def fake_db():
            yield db

        app.dependency_overrides[get_db] = fake_db
        self.client = TestClient(app)

    def test_staff_signup_has_no_store(self):
        res = self.client.post("/auth/signup", json={
            "name": "새알바", "email": "new@example.com", "password": "secret1", "role": "STAFF"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["user"]["role"], "STAFF")
        claims = jwt.decode(res.json()["token"], SETTINGS.jwt_secret, algorithms=["HS256"])
        self.assertNotIn("store_id", claims)

    def test_join_endpoint_removed(self):
        self.assertEqual(self.client.post("/auth/join", json={}).status_code, 404)

from app.members import repository


class MembersApiTest(unittest.TestCase):
    def setUp(self):
        p = patch("app.deps.get_settings", return_value=SETTINGS)
        p.start()
        self.addCleanup(p.stop)
        self.revoked = []
        self.delivered = []

        class Db:
            async def fetchrow(self, sql, *args):
                return {"member_role": "OWNER" if args[1] == 1 else "STAFF"}

        async def approve(db, *, store_id, request_id, owner_id):
            if request_id == 404:
                raise LookupError
            if request_id == 409:
                raise repository.AlreadyDecided
            return 5, 21

        async def deliver(store_id, notification_id):
            self.delivered.append((store_id, notification_id))

        async def remove(db, *, store_id, user_id, owner_id):
            if user_id == owner_id:
                raise repository.CannotRemoveOwner
            if user_id == 404:
                raise LookupError

        async def revoke(db, *, user_id):
            self.revoked.append(user_id)

        for target, fn in (("app.members.router.repository.approve", approve),
                           ("app.members.router.repository.remove", remove),
                           ("app.members.router.revoke_user_sessions", revoke),
                           ("app.members.router.deliver_notification", deliver)):
            q = patch(target, side_effect=fn)
            q.start()
            self.addCleanup(q.stop)
        app = FastAPI()
        install_error_handlers(app)
        app.include_router(members_router_module.router, prefix="/members")
        db = Db()

        async def fake_db():
            yield db

        app.dependency_overrides[get_db] = fake_db
        self.client = TestClient(app)
        self.owner = bearer(user_id=1, store_id=1, role="OWNER")

    def test_approve_status_codes(self):
        self.assertEqual(self.client.post("/members/requests/1/approve", headers=self.owner).status_code, 204)
        # 승인 알림은 응답 뒤 알바 기기로 보낸다
        self.assertEqual(self.delivered, [(1, 21)])
        self.assertEqual(self.client.post("/members/requests/404/approve", headers=self.owner).status_code, 404)
        self.assertEqual(self.client.post("/members/requests/409/approve", headers=self.owner).status_code, 409)

    def test_remove_revokes_sessions(self):
        self.assertEqual(self.client.post("/members/5/remove", headers=self.owner).status_code, 204)
        self.assertEqual(self.revoked, [5])

    def test_owner_cannot_remove_self(self):
        res = self.client.post("/members/1/remove", headers=self.owner)
        self.assertEqual(res.status_code, 400)
        self.assertEqual(self.revoked, [])

    def test_unknown_member_404(self):
        self.assertEqual(self.client.post("/members/404/remove", headers=self.owner).status_code, 404)

    def test_staff_forbidden(self):
        staff = bearer(user_id=5, store_id=1, role="STAFF")
        self.assertEqual(self.client.post("/members/requests/1/approve", headers=staff).status_code, 403)
