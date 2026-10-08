"""카카오 로그인 REST 호출 (이슈 #37).

PKCE S256·client_secret_post 지원은 https://kauth.kakao.com/.well-known/openid-configuration 에서
확인했다(2026-10-08). 카카오 access token 은 사용자 조회에만 쓰고 저장하지 않는다.
"""
from __future__ import annotations

import base64
import hashlib
import secrets
import time
import logging
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)
AUTHORIZE_URL = "https://kauth.kakao.com/oauth/authorize"
TOKEN_URL = "https://kauth.kakao.com/oauth/token"
USER_URL = "https://kapi.kakao.com/v2/user/me"
_TIMEOUT = httpx.Timeout(5.0)


class KakaoError(Exception):
    pass


@dataclass(frozen=True)
class KakaoUser:
    id: str
    nickname: str | None


def is_configured() -> bool:
    s = get_settings()
    return bool(s.kakao_rest_api_key and s.kakao_client_secret and s.kakao_redirect_uri)


def pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def authorize_url(*, state: str, code_challenge: str) -> str:
    s = get_settings()
    return AUTHORIZE_URL + "?" + urlencode({
        "client_id": s.kakao_rest_api_key,
        "redirect_uri": s.kakao_redirect_uri,
        "response_type": "code",
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    })


async def fetch_user(*, code: str, code_verifier: str,
                     transport: httpx.AsyncBaseTransport | None = None) -> KakaoUser:
    s = get_settings()
    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, transport=transport) as client:
            token = await client.post(TOKEN_URL, data={
                "grant_type": "authorization_code",
                "client_id": s.kakao_rest_api_key,
                "client_secret": s.kakao_client_secret,
                "redirect_uri": s.kakao_redirect_uri,
                "code": code,
                "code_verifier": code_verifier,
            })
            if token.status_code != 200:
                raise KakaoError(f"token {token.status_code}")
            access = token.json()["access_token"]
            me = await client.get(USER_URL, headers={"Authorization": f"Bearer {access}"})
            if me.status_code != 200:
                raise KakaoError(f"user {me.status_code}")
            data = me.json()
    except (httpx.HTTPError, KeyError, ValueError, TypeError) as exc:
        raise KakaoError(type(exc).__name__) from exc
    finally:
        logger.info("kakao login exchange %.0fms", (time.monotonic() - started) * 1000)
    if not isinstance(data, dict) or type(data.get("id")) is not int or data["id"] <= 0:
        raise KakaoError("invalid user response")
    account = data.get("kakao_account")
    profile = account.get("profile") if isinstance(account, dict) else None
    nickname = profile.get("nickname") if isinstance(profile, dict) else None
    return KakaoUser(str(data["id"]), nickname if isinstance(nickname, str) else None)
