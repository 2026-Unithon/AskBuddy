"""카카오 로그인 엔드포인트 (이슈 #37). 콜백이 끝나면 웹 /auth/complete 로 돌려보낸다."""
from __future__ import annotations

import logging
import secrets
from typing import Literal
from urllib.parse import urlencode

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import RedirectResponse

from app.auth import kakao
from app.auth.kakao_accounts import AuthFlowError, complete_kakao_login
from app.auth.oauth_state import (
    OAUTH_COOKIE, OAUTH_COOKIE_PATH, InvalidState, OAuthState, decode_state, encode_state, safe_next,
)
from app.auth.router import start_session
from app.config import get_settings
from app.deps import Db
from app.members import invites
from app.notifications.service import deliver_notification

router = APIRouter()
logger = logging.getLogger(__name__)


def _to_web(*, error: str | None = None, next_path: str | None = None) -> RedirectResponse:
    query = {}
    if error:
        query["error"] = error
    elif next_path:
        query["next"] = next_path
    url = get_settings().web_base_url.rstrip("/") + "/auth/complete"
    res = RedirectResponse(url + ("?" + urlencode(query) if query else ""), status_code=302)
    res.headers["Cache-Control"] = "no-store"
    res.headers["Referrer-Policy"] = "no-referrer"
    res.delete_cookie(OAUTH_COOKIE, path=OAUTH_COOKIE_PATH)
    return res


# store-isolation-ok: 공개 설정 조회
@router.get("/providers")
async def providers():
    return {"kakao": kakao.is_configured()}


# store-isolation-ok: 로그인 시작. 초대 토큰으로 매장을 찾되 id 만 서명 쿠키에 담는다
@router.get("/kakao/start")
async def kakao_start(db: Db, intent: Literal["LOGIN", "STAFF_JOIN"],
                      invite: str | None = None, next: str | None = None):
    if not kakao.is_configured():
        return _to_web(error="KAKAO_NOT_CONFIGURED")
    invite_id = None
    if intent == "STAFF_JOIN":
        found = await invites.resolve(db, token=invite) if invite else None
        if found is None:
            return _to_web(error="INVITE_INVALID")
        invite_id = int(found["invite_id"])
    verifier, challenge = kakao.pkce_pair()
    state = secrets.token_urlsafe(24)
    res = RedirectResponse(kakao.authorize_url(state=state, code_challenge=challenge), status_code=302)
    res.headers["Cache-Control"] = "no-store"
    s = get_settings()
    res.set_cookie(
        OAUTH_COOKIE, encode_state(OAuthState(state, verifier, intent, invite_id, safe_next(next))),
        max_age=600, path=OAUTH_COOKIE_PATH, httponly=True, secure=s.auth_cookie_secure, samesite="lax")
    return res


# store-isolation-ok: 로그인 콜백. 매장은 서명 쿠키의 초대 id 를 다시 검증해 정한다
@router.get("/kakao/callback")
async def kakao_callback(request: Request, db: Db, background: BackgroundTasks,
                         state: str | None = None, code: str | None = None, error: str | None = None):
    try:
        saved = decode_state(request.cookies.get(OAUTH_COOKIE) or "")
    except InvalidState:
        return _to_web(error="OAUTH_STATE_INVALID")
    if not state or not secrets.compare_digest(state, saved.state):
        return _to_web(error="OAUTH_STATE_INVALID")
    if error or not code:
        return _to_web(error="KAKAO_CANCELLED" if error == "access_denied" else "KAKAO_FAILED")
    try:
        kakao_user = await kakao.fetch_user(code=code, code_verifier=saved.verifier)
    except kakao.KakaoError as exc:
        logger.warning("kakao exchange failed: %s", exc)
        return _to_web(error="KAKAO_FAILED")

    invite = None
    if saved.intent == "STAFF_JOIN":
        # start 와 callback 사이에 링크가 재생성됐을 수 있다. 다시 확인한다
        invite = await invites.resolve_by_id(db, invite_id=saved.invite_id)
        if invite is None:
            return _to_web(error="INVITE_INVALID")
    try:
        user_id, notification_id = await complete_kakao_login(
            db, kakao_user=kakao_user, intent=saved.intent, invite=invite)
    except AuthFlowError as exc:
        return _to_web(error=exc.code)
    if notification_id is not None:
        background.add_task(deliver_notification, int(invite["store_id"]), notification_id)
    res = _to_web(next_path=saved.next)
    await start_session(db, res, user_id=user_id)
    return res
