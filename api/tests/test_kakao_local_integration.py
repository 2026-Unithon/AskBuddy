"""로컬 PostgreSQL에서 인증·초대·격리 경계를 검증한다. 테스트 데이터는 롤백한다.

KAKAO_TEST_DB_URL이 로컬 주소일 때만 실행한다. 운영 연결은 거부한다.
"""
import os
import unittest
from unittest.mock import patch
from urllib.parse import urlparse, parse_qs

import asyncpg
import httpx
from fastapi import FastAPI

from app.auth import kakao_router, router as auth_router, session
from app.auth.kakao import KakaoUser
from app.bootstrap.router import router as bootstrap_router
from app.config import Settings
from app.checklist import repository as checklist_repository
from app.deps import CurrentStoreId, get_db
from app.errors import install_error_handlers
from app.members.router import router as members_router
from app.notifications.router import router as notifications_router


@unittest.skipUnless(os.environ.get("KAKAO_TEST_DB_URL"), "로컬 DB 통합 검증은 명시적으로 실행한다")
class LocalAuthIntegration(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        url = os.environ["KAKAO_TEST_DB_URL"]
        assert urlparse(url).hostname in ("127.0.0.1", "localhost", "::1")
        self.db = await asyncpg.connect(url)
        self.tx = self.db.transaction()
        await self.tx.start()
        settings = Settings(_env_file=None, jwt_secret="synthetic-local-test-secret-" * 3,
                            kakao_rest_api_key="test-key", kakao_client_secret="test-secret",
                            auth_cookie_secure=False, allowed_origins="http://localhost:3000")
        for target in ("app.deps", "app.auth.session", "app.auth.kakao", "app.auth.oauth_state",
                       "app.auth.kakao_router", "app.members.invites"):
            p = patch(target + ".get_settings", return_value=settings)
            p.start()
            self.addCleanup(p.stop)
        self.app = FastAPI()
        install_error_handlers(self.app)
        for router, prefix in ((auth_router.router, "/auth"), (kakao_router.router, "/auth"),
                               (members_router, "/members"), (bootstrap_router, "/app"),
                               (notifications_router, "/notifications")):
            self.app.include_router(router, prefix=prefix)

        @self.app.get("/protected")
        async def protected(store_id: CurrentStoreId):
            return {"store_id": store_id}

        async def db():
            yield self.db
        self.app.dependency_overrides[get_db] = db
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app),
                                       base_url="http://localhost:8000",
                                       headers={"Origin": "http://localhost:3000"})

    async def asyncTearDown(self):
        await self.client.aclose()
        await self.tx.rollback()
        await self.db.close()

    async def signup(self, email, role=None):
        res = await self.client.post("/auth/signup", json={"name": "테스트사용자", "email": email,
                                                           "password": "synthetic-password", "role": role})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertIn("HttpOnly", res.headers["set-cookie"])
        return res.json()

    @staticmethod
    def bearer(s):
        return {"Authorization": "Bearer " + s["token"]}

    async def owner(self, email="owner@example.com"):
        s = await self.signup(email, "OWNER")
        res = await self.client.post("/auth/stores", headers=self.bearer(s),
                                     json={"store_name": "테스트카페", "business_type": "CAFE"})
        self.assertEqual(res.status_code, 200, res.text)
        return {**s, "token": res.json()["token"], "store": res.json()["store"]}

    async def test_signup_role_refresh_logout(self):
        s = await self.signup("new@example.com")
        boot = await self.client.get("/app/bootstrap", headers=self.bearer(s))
        self.assertEqual(boot.json()["default_destination"], "/auth/role")
        denied = await self.client.get("/protected", headers=self.bearer(s))
        self.assertEqual(denied.status_code, 403)
        chosen = await self.client.post("/auth/role", headers=self.bearer(s), json={"role": "STAFF"})
        self.assertEqual(chosen.status_code, 200, chosen.text)
        duplicate = await self.client.post("/auth/role", headers=self.bearer(s), json={"role": "OWNER"})
        self.assertEqual(duplicate.status_code, 409)
        res = await self.client.post("/auth/refresh")
        self.assertEqual(res.json()["user"]["role"], "STAFF")
        boot = await self.client.get("/app/bootstrap", headers=self.bearer(res.json()))
        self.assertEqual(boot.json()["default_destination"], "/staff/pending")
        self.assertEqual((await self.client.post("/auth/logout")).status_code, 204)
        self.assertEqual((await self.client.post("/auth/refresh")).status_code, 401)

    async def test_join_approve_remove_and_store_isolation(self):
        owner = await self.owner()
        other = await self.owner("other@example.com")
        invite = await self.client.get("/members/invite-link", headers=self.bearer(owner))
        token = invite.json()["url"].rsplit("/", 1)[1]
        staff = await self.signup("staff@example.com", "STAFF")
        for _ in range(2):
            join = await self.client.post("/auth/join-requests", headers=self.bearer(staff), json={"invite_token": token})
            self.assertEqual(join.status_code, 200, join.text)
        members = await self.client.get("/members", headers=self.bearer(owner))
        self.assertEqual(len(members.json()["pending"]), 1)
        request_id = members.json()["pending"][0]["request_id"]
        hidden = await self.client.get("/members", headers=self.bearer(other))
        self.assertEqual(hidden.json()["pending"], [])
        denied = await self.client.post(f"/members/requests/{request_id}/approve", headers=self.bearer(other))
        self.assertEqual(denied.status_code, 404)
        # 링크를 재발급해도 이미 생성된 합류 요청은 승인할 수 있다.
        await self.client.post("/members/invite-link/rotate", headers=self.bearer(owner))
        self.assertEqual((await self.client.get("/auth/invites/" + token)).status_code, 404)
        approved = await self.client.post(f"/members/requests/{request_id}/approve", headers=self.bearer(owner))
        self.assertEqual(approved.status_code, 204, approved.text)
        refreshed = await self.client.post("/auth/refresh")
        self.assertEqual(refreshed.json()["user"]["store_id"], owner["store"]["store_id"])
        member_token = self.bearer(refreshed.json())
        self.assertEqual((await self.client.get("/protected", headers=member_token)).status_code, 200)
        store_id = owner["store"]["store_id"]
        user_id = staff["user"]["user_id"]
        member = await checklist_repository.get_member(self.db, store_id, user_id)
        self.assertIsNotNone(member)
        removed = await self.client.post(f'/members/{staff["user"]["user_id"]}/remove', headers=self.bearer(owner))
        self.assertEqual(removed.status_code, 204, removed.text)
        self.assertEqual((await self.client.get("/protected", headers=member_token)).status_code, 403)
        self.assertEqual((await self.client.post("/auth/refresh")).status_code, 401)
        self.assertIsNone(await checklist_repository.get_member(self.db, store_id, user_id))
        active = await checklist_repository.list_members(self.db, store_id)
        self.assertNotIn(user_id, {row["user_id"] for row in active})
        self.assertFalse(await checklist_repository.set_member_shifts(self.db, store_id, member["member_id"], []))
        # 퇴사자의 과거 기록 조회에 필요한 회원 행은 보존한다.
        self.assertIsNotNone(await checklist_repository.member_by_user(self.db, store_id, user_id))
        events = await self.db.fetch("select event_type from notification_events where store_id=$1", owner["store"]["store_id"])
        self.assertEqual({r["event_type"] for r in events}, {"JOIN_REQUESTED", "JOIN_APPROVED"})

    async def test_kakao_callback_creates_once_and_issues_only_cookie(self):
        with patch("app.auth.kakao.fetch_user", return_value=KakaoUser("synthetic-kakao-123", "테스트닉네임")):
            for _ in range(2):
                start = await self.client.get("/auth/kakao/start?intent=LOGIN")
                q = parse_qs(urlparse(start.headers["location"]).query)
                res = await self.client.get("/auth/kakao/callback", params={"state": q["state"][0], "code": "fake-code"})
                self.assertEqual(res.status_code, 302)
                self.assertEqual(res.headers["location"], "http://localhost:3000/auth/complete")
                self.assertIn("ab_refresh=", res.headers["set-cookie"])
                restored = await self.client.post("/auth/refresh")
                self.assertEqual(restored.status_code, 200, restored.text)
                self.assertIsNone(restored.json()["user"]["role"])
        count = await self.db.fetchval("select count(*) from user_identities where provider_user_id='synthetic-kakao-123'")
        self.assertEqual(count, 1)

    async def test_csrf_and_legacy_join_rejected(self):
        await self.signup("csrf@example.com")
        res = await self.client.post("/auth/refresh", headers={"Origin": "https://untrusted.example"})
        self.assertEqual(res.status_code, 403)
        self.assertEqual((await self.client.post("/auth/join", json={})).status_code, 404)
        self.assertEqual((await self.client.post("/auth/invites", json={})).status_code, 404)

    async def test_refresh_replay_revocation_persists(self):
        s = await self.signup("replay@example.com")
        old = self.client.cookies.get("ab_refresh")
        self.assertEqual((await self.client.post("/auth/refresh")).status_code, 200)
        new = self.client.cookies.get("ab_refresh")
        await self.db.execute("update auth_refresh_tokens set revoked_at=now()-interval '31 seconds' where token_hash=$1", session._hash(old))
        with self.assertRaises(session.RefreshRejected):
            await session.rotate_refresh(self.db, raw=old)
        with self.assertRaises(session.RefreshRejected):
            await session.rotate_refresh(self.db, raw=new)
        self.assertEqual(await self.db.fetchval("select count(*) from auth_refresh_tokens where user_id=$1 and revoked_at is null", s["user"]["user_id"]), 0)


    async def test_notification_support_and_storeless_subscription(self):
        owner = await self.owner("notification-owner@example.com")
        support = await self.client.get("/notifications/support", headers=self.bearer(owner))
        self.assertEqual(support.status_code, 200, support.text)
        staff = await self.signup("notification-staff@example.com", "STAFF")
        sub = await self.client.post("/notifications/my-subscriptions", headers=self.bearer(staff),
                                     json={"endpoint": "https://push.example.test/synthetic", "keys": {
                                         "p256dh": "synthetic-test-public-key-123456", "auth": "synthetic-auth-123"}})
        self.assertEqual(sub.status_code, 201, sub.text)
        sub_id = sub.json()["subscription_id"]
        denied = await self.client.delete(f"/notifications/my-subscriptions/{sub_id}", headers=self.bearer(owner))
        self.assertEqual(denied.status_code, 404)
        deleted = await self.client.delete(f"/notifications/my-subscriptions/{sub_id}", headers=self.bearer(staff))
        self.assertEqual(deleted.status_code, 204)
