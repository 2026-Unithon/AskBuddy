"""카카오 왕복 동안 state·PKCE verifier 를 서명 쿠키에 담는다. 서버 테이블이 필요 없다.

aud 가 있어 제품 API(get_claims, audience 미지정)는 이 토큰을 받아주지 않는다.
"""
from __future__ import annotations

import re
from urllib.parse import unquote
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone

import jwt

from app.config import get_settings

OAUTH_COOKIE = "ab_oauth"
OAUTH_COOKIE_PATH = "/auth/kakao"
_AUD = "askbuddy-oauth"
_TTL = timedelta(minutes=10)
INTENTS = ("LOGIN", "STAFF_JOIN")
# /owner/... 또는 /staff/... 상대 경로만. 역슬래시·스킴·이중 슬래시를 막는다
_NEXT = re.compile(r"^/(owner|staff)(/[A-Za-z0-9_\-/.?=&%]*)?$")


class InvalidState(Exception):
    pass


@dataclass(frozen=True)
class OAuthState:
    state: str
    verifier: str
    intent: str
    invite_id: int | None
    next: str | None


def safe_next(value: str | None) -> str | None:
    if not value or not _NEXT.match(value):
        return None
    decoded = unquote(value)
    if "\\" in decoded or "//" in decoded or any(part in (".", "..") for part in decoded.split("?", 1)[0].split("/")):
        return None
    if any(ord(c) < 32 for c in decoded):
        return None
    return value


def encode_state(s: OAuthState) -> str:
    st = get_settings()
    payload = {**asdict(s), "aud": _AUD, "exp": datetime.now(timezone.utc) + _TTL}
    return jwt.encode(payload, st.jwt_secret, algorithm=st.jwt_algorithm)


def decode_state(token: str) -> OAuthState:
    st = get_settings()
    try:
        data = jwt.decode(token, st.jwt_secret, algorithms=[st.jwt_algorithm],
                          audience=_AUD, options={"require": ["exp", "aud"]})
        if data.get("intent") not in INTENTS or not isinstance(data.get("state"), str) or not isinstance(data.get("verifier"), str):
            raise InvalidState()
        return OAuthState(data["state"], data["verifier"], data["intent"],
                          data.get("invite_id"), data.get("next"))
    except (jwt.PyJWTError, KeyError) as exc:
        raise InvalidState() from exc
