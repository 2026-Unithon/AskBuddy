"""카카오 로그인 (이슈 #37). 카카오 서버는 httpx.MockTransport 로 흉내 낸다."""
import asyncio
import base64
import hashlib
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import httpx

from app.auth import kakao, oauth_state

SETTINGS = SimpleNamespace(
    jwt_secret="synthetic-test-key-" * 4, jwt_algorithm="HS256",
    kakao_rest_api_key="rest-key", kakao_client_secret="secret",
    kakao_redirect_uri="https://api.askbuddy.kr/auth/kakao/callback",
    web_base_url="https://askbuddy.kr", auth_cookie_secure=True,
    access_token_expire_minutes=60, refresh_token_expire_days=90,
    origins=["https://askbuddy.kr"])


class StateTest(unittest.TestCase):
    def setUp(self):
        for target in ("app.deps.get_settings", "app.auth.oauth_state.get_settings",
                       "app.auth.kakao.get_settings"):
            p = patch(target, return_value=SETTINGS)
            p.start()
            self.addCleanup(p.stop)

    def test_state_round_trip(self):
        s = oauth_state.OAuthState("st", "ver", "STAFF_JOIN", 9, "/staff/roadmap")
        self.assertEqual(oauth_state.decode_state(oauth_state.encode_state(s)), s)

    def test_state_rejects_tamper_and_product_token(self):
        from app.deps import create_token
        token = oauth_state.encode_state(oauth_state.OAuthState("st", "ver", "OWNER", None, None))
        with self.assertRaises(oauth_state.InvalidState):
            oauth_state.decode_state(token[:-2] + "xx")
        product = create_token({"user_id": 1, "role": "OWNER", "exp": 9999999999})
        with self.assertRaises(oauth_state.InvalidState):
            oauth_state.decode_state(product)

    def test_state_token_rejected_by_product_api(self):
        from fastapi import HTTPException
        from app.deps import get_claims
        token = oauth_state.encode_state(oauth_state.OAuthState("st", "ver", "OWNER", None, None))
        with self.assertRaises(HTTPException):
            asyncio.run(get_claims("Bearer " + token))

    def test_safe_next_whitelist(self):
        self.assertEqual(oauth_state.safe_next("/owner/cards?x=1"), "/owner/cards?x=1")
        self.assertEqual(oauth_state.safe_next("/staff/roadmap"), "/staff/roadmap")
        for bad in ("//evil.com", "https://evil.com", "/ownerx", "/role", "/owner/\\evil", None, ""):
            self.assertIsNone(oauth_state.safe_next(bad), bad)

    def test_authorize_url_has_pkce_and_state(self):
        verifier, challenge = kakao.pkce_pair()
        expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        self.assertEqual(challenge, expected)
        q = parse_qs(urlparse(kakao.authorize_url(state="st", code_challenge=challenge)).query)
        self.assertEqual(q["client_id"], ["rest-key"])
        self.assertEqual(q["response_type"], ["code"])
        self.assertEqual(q["code_challenge_method"], ["S256"])
        self.assertEqual(q["state"], ["st"])
        self.assertEqual(q["redirect_uri"], [SETTINGS.kakao_redirect_uri])


class FetchUserTest(unittest.TestCase):
    def setUp(self):
        p = patch("app.auth.kakao.get_settings", return_value=SETTINGS)
        p.start()
        self.addCleanup(p.stop)

    def test_exchange_sends_secret_and_verifier(self):
        seen = {}

        def handler(request: httpx.Request):
            if request.url.path == "/oauth/token":
                seen["form"] = parse_qs(request.content.decode())
                return httpx.Response(200, json={"access_token": "kat"})
            seen["auth"] = request.headers["authorization"]
            return httpx.Response(200, json={"id": 123, "kakao_account": {"profile": {"nickname": "닉"}}})

        user = asyncio.run(kakao.fetch_user(code="c", code_verifier="v",
                                            transport=httpx.MockTransport(handler)))
        self.assertEqual(user, kakao.KakaoUser("123", "닉"))
        self.assertEqual(seen["form"]["client_secret"], ["secret"])
        self.assertEqual(seen["form"]["code_verifier"], ["v"])
        self.assertEqual(seen["form"]["grant_type"], ["authorization_code"])
        self.assertEqual(seen["auth"], "Bearer kat")

    def test_token_error_raises(self):
        transport = httpx.MockTransport(lambda r: httpx.Response(400, json={"error": "invalid_grant"}))
        with self.assertRaises(kakao.KakaoError):
            asyncio.run(kakao.fetch_user(code="c", code_verifier="v", transport=transport))

from app.auth.kakao_accounts import AuthFlowError, decide


ACTIONS = {"LOGIN", "CREATE_UNSET", "CREATE_STAFF_AND_REQUEST", "SET_STAFF_AND_REQUEST", "REQUEST"}


class DecideTest(unittest.TestCase):
    def check(self, expected, **kw):
        base = dict(user_exists=False, user_role=None, active_store_id=None, invite_store_id=None)
        if kw.get("user_role") is not None:
            base["user_exists"] = True
        base.update(kw)
        if expected in ACTIONS:
            self.assertEqual(decide(**base), expected)
        else:
            with self.assertRaises(AuthFlowError) as ctx:
                decide(**base)
            self.assertEqual(ctx.exception.code, expected)

    def test_login_intent(self):
        # 단일 로그인 화면: 기존 계정은 역할과 상관없이 로그인, 새 계정은 역할 미정으로 만든다
        self.check("CREATE_UNSET", intent="LOGIN")
        for role in ("OWNER", "STAFF", None):
            self.check("LOGIN", intent="LOGIN", user_exists=True, user_role=role)

    def test_staff_join_intent(self):
        self.check("INVITE_INVALID", intent="STAFF_JOIN", invite_store_id=None)
        self.check("CREATE_STAFF_AND_REQUEST", intent="STAFF_JOIN", invite_store_id=1)
        # 역할을 아직 안 고른 계정이 링크로 왔다 → 알바로 정하고 요청
        self.check("SET_STAFF_AND_REQUEST", intent="STAFF_JOIN", user_exists=True, invite_store_id=1)
        self.check("ROLE_CONFLICT", intent="STAFF_JOIN", user_role="OWNER", invite_store_id=1)
        self.check("LOGIN", intent="STAFF_JOIN", user_role="STAFF", active_store_id=1, invite_store_id=1)
        self.check("ALREADY_IN_OTHER_STORE", intent="STAFF_JOIN", user_role="STAFF",
                   active_store_id=2, invite_store_id=1)
        self.check("REQUEST", intent="STAFF_JOIN", user_role="STAFF", invite_store_id=1)


from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import kakao_router as kakao_router_module
from app.deps import get_db
from app.errors import install_error_handlers


class KakaoRouteTest(unittest.TestCase):
    def setUp(self):
        for target in ("app.deps.get_settings", "app.auth.oauth_state.get_settings",
                       "app.auth.kakao.get_settings", "app.auth.kakao_router.get_settings",
                       "app.auth.session.get_settings", "app.members.invites.get_settings"):
            p = patch(target, return_value=SETTINGS)
            p.start()
            self.addCleanup(p.stop)
        self.completed = []

        async def resolve(db, *, token):
            return {"invite_id": 9, "store_id": 1, "store_name": "테스트카페"} if token == "good" else None

        async def resolve_by_id(db, *, invite_id):
            return {"invite_id": 9, "store_id": 1, "store_name": "테스트카페"} if invite_id == 9 else None

        async def fetch_user(*, code, code_verifier):
            if code == "boom":
                raise kakao.KakaoError("x")
            # 점주 계정으로 초대 링크를 연 경우를 흉내 낸다
            return kakao.KakaoUser("999" if code == "owner" else "123", "닉")

        async def complete(db, *, kakao_user, intent, invite):
            if kakao_user.id == "999":
                raise AuthFlowError("ROLE_CONFLICT")
            self.completed.append((kakao_user.id, intent, invite))
            return 5, None

        async def start_session(db, response, *, user_id):
            response.set_cookie("ab_refresh", "r", path="/auth")

        for target, fn in (("app.auth.kakao_router.invites.resolve", resolve),
                           ("app.auth.kakao_router.invites.resolve_by_id", resolve_by_id),
                           ("app.auth.kakao_router.kakao.fetch_user", fetch_user),
                           ("app.auth.kakao_router.complete_kakao_login", complete),
                           ("app.auth.kakao_router.start_session", start_session)):
            q = patch(target, side_effect=fn)
            q.start()
            self.addCleanup(q.stop)
        app = FastAPI()
        install_error_handlers(app)
        app.include_router(kakao_router_module.router, prefix="/auth")

        async def fake_db():
            yield object()

        app.dependency_overrides[get_db] = fake_db
        self.client = TestClient(app, base_url="https://api.askbuddy.kr", follow_redirects=False)

    def start(self, **params):
        return self.client.get("/auth/kakao/start", params=params)

    def callback(self, start_res, code="ok", state=None, **extra):
        q = parse_qs(urlparse(start_res.headers["location"]).query)
        params = {"code": code, "state": state or q["state"][0], **extra}
        return self.client.get("/auth/kakao/callback", params=params)

    def test_providers(self):
        self.assertEqual(self.client.get("/auth/providers").json(), {"kakao": True})

    def test_start_redirects_to_kakao_and_sets_state_cookie(self):
        res = self.start(intent="LOGIN")
        self.assertEqual(res.status_code, 302)
        self.assertTrue(res.headers["location"].startswith("https://kauth.kakao.com/oauth/authorize?"))
        self.assertIn("ab_oauth=", res.headers["set-cookie"])
        self.assertIn("Path=/auth/kakao", res.headers["set-cookie"])

    def test_start_rejects_unknown_intent_and_bad_invite(self):
        self.assertEqual(self.start(intent="OWNER").status_code, 422)
        res = self.start(intent="STAFF_JOIN", invite="bad")
        self.assertEqual(res.status_code, 302)
        self.assertEqual(res.headers["location"], "https://askbuddy.kr/auth/complete?error=INVITE_INVALID")

    def test_full_owner_flow(self):
        res = self.callback(self.start(intent="LOGIN", next="/owner/cards"))
        self.assertEqual(res.status_code, 302)
        self.assertEqual(res.headers["location"], "https://askbuddy.kr/auth/complete?next=%2Fowner%2Fcards")
        cookies = res.headers.get_list("set-cookie")
        self.assertTrue(any(c.startswith("ab_refresh=") for c in cookies))
        self.assertTrue(any(c.startswith('ab_oauth=""') for c in cookies))
        self.assertEqual(self.completed, [("123", "LOGIN", None)])

    def test_join_passes_invite_from_cookie_not_query(self):
        self.callback(self.start(intent="STAFF_JOIN", invite="good"))
        self.assertEqual(self.completed[0][2]["invite_id"], 9)

    def test_state_mismatch_creates_nothing(self):
        res = self.callback(self.start(intent="LOGIN"), state="forged")
        self.assertEqual(res.headers["location"], "https://askbuddy.kr/auth/complete?error=OAUTH_STATE_INVALID")
        self.assertEqual(self.completed, [])

    def test_missing_state_cookie(self):
        start_res = self.start(intent="LOGIN")
        self.client.cookies.clear()
        res = self.callback(start_res)
        self.assertEqual(res.headers["location"], "https://askbuddy.kr/auth/complete?error=OAUTH_STATE_INVALID")

    def test_user_cancel(self):
        start_res = self.start(intent="LOGIN")
        q = parse_qs(urlparse(start_res.headers["location"]).query)
        res = self.client.get("/auth/kakao/callback", params={"error": "access_denied", "state": q["state"][0]})
        self.assertEqual(res.headers["location"], "https://askbuddy.kr/auth/complete?error=KAKAO_CANCELLED")

    def test_kakao_failure_and_flow_error(self):
        res = self.callback(self.start(intent="LOGIN"), code="boom")
        self.assertEqual(res.headers["location"], "https://askbuddy.kr/auth/complete?error=KAKAO_FAILED")
        res = self.callback(self.start(intent="STAFF_JOIN", invite="good"), code="owner")
        self.assertEqual(res.headers["location"], "https://askbuddy.kr/auth/complete?error=ROLE_CONFLICT")

    def test_open_redirect_next_dropped(self):
        res = self.callback(self.start(intent="LOGIN", next="//evil.com"))
        self.assertEqual(res.headers["location"], "https://askbuddy.kr/auth/complete")

    def test_not_configured(self):
        with patch("app.auth.kakao_router.kakao.is_configured", return_value=False):
            self.assertEqual(self.client.get("/auth/providers").json(), {"kakao": False})
            res = self.start(intent="LOGIN")
            self.assertEqual(res.status_code, 302)
            self.assertEqual(res.headers["location"],
                             "https://askbuddy.kr/auth/complete?error=KAKAO_NOT_CONFIGURED")
