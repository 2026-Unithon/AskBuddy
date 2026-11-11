"""계정 라우터(계획 8): 문의·의견, 퇴사, 탈퇴, 탈퇴 취소. store_id·user_id 는 JWT 에서만 꺼낸다."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Response
from pydantic import BaseModel, Field

from app.auth.session import clear_refresh_cookie
from app.bootstrap import account, feedback_mail
from app.config import get_settings
from app.deps import CurrentStoreId, CurrentUserId, Db
from app.errors import ApiError, OpenApiClaims
from app.ingest.preprocess import storage

router = APIRouter()
logger = logging.getLogger(__name__)


class FeedbackRequest(BaseModel):
    kind: Literal["INQUIRY", "IDEA"]
    body: str = Field(max_length=account.FEEDBACK_MAX)


@router.post("/feedback", status_code=201)
async def post_feedback(req: FeedbackRequest, db: Db, store_id: CurrentStoreId, user_id: CurrentUserId,
                        background: BackgroundTasks) -> dict:
    """문의하기, 의견 보내기. 운영자는 DB 에서 본다. 저장한 뒤 운영자에게 메일로 알린다(글은 싣지 않는다)."""
    try:
        feedback_id = await account.save_feedback(db, store_id=store_id, user_id=user_id, kind=req.kind, body=req.body)
    except ValueError as exc:
        raise ApiError(400, "FEEDBACK_EMPTY", "보낼 글을 적어 주세요.") from exc
    # 응답 뒤에 보낸다. 메일 성패는 저장 응답과 무관하다
    background.add_task(feedback_mail.notify_feedback, feedback_id=feedback_id, kind=req.kind)
    return {"feedback_id": feedback_id}


class ConfirmRequest(BaseModel):
    confirm: str = Field(max_length=50)


def check_confirm(req: ConfirmRequest, phrase: str) -> None:
    """화면을 거치지 않은 요청도 같은 문구를 쳐야 한다. 앞뒤 공백만 무시한다."""
    if req.confirm.strip() != phrase:
        raise ApiError(400, "CONFIRM_MISMATCH", f"'{phrase}'를 그대로 입력해 주세요.")


def _signed_out() -> Response:
    # 세션을 서버에서 끊었으니 이 기기의 refresh 쿠키도 지운다
    res = Response(status_code=204)
    clear_refresh_cookie(res)
    return res


async def _delete_avatar(path: str) -> None:
    """커밋 뒤 사진 파일을 지운다. 실패해도 탈퇴는 끝났다(로그에 예외 종류만)."""
    try:
        bucket, object_path = storage.split_object_path(path)
        await storage.delete_objects(bucket, [object_path])
    except Exception as exc:  # noqa: BLE001
        logger.warning("avatar delete failed error=%s", type(exc).__name__)


@router.post("/me/leave-store", status_code=204)
async def leave_store(req: ConfirmRequest, db: Db, claims: OpenApiClaims, store_id: CurrentStoreId,
                      user_id: CurrentUserId) -> Response:
    """퇴사했어요(알바생만). 이 매장 소속만 끝내고 계정은 남는다."""
    if claims.get("role") != "STAFF":
        raise ApiError(403, "OWNER_CANNOT_LEAVE", "사장님은 회원 탈퇴를 이용해 주세요.")
    check_confirm(req, account.CONFIRM_LEAVE)
    try:
        await account.leave_store(db, store_id=store_id, user_id=user_id)
    except account.OwnerCannotLeave as exc:
        raise ApiError(403, "OWNER_CANNOT_LEAVE", "사장님은 회원 탈퇴를 이용해 주세요.") from exc
    except LookupError as exc:
        raise ApiError(404, "MEMBERSHIP_NOT_FOUND", "이미 매장에서 나갔어요.") from exc
    return _signed_out()


@router.post("/me/withdraw", status_code=204)
async def withdraw(req: ConfirmRequest, db: Db, claims: OpenApiClaims, user_id: CurrentUserId,
                   background: BackgroundTasks) -> Response:
    """회원 탈퇴. 사장님(매장 있음)은 매장을 닫고 유예 뒤 파기, 그 밖은 바로 계정을 비운다."""
    check_confirm(req, account.CONFIRM_WITHDRAW)
    store_id = claims.get("store_id")
    if claims.get("role") == "OWNER" and store_id is not None:
        try:
            await account.withdraw_owner(db, store_id=int(store_id), user_id=user_id, now=datetime.now(timezone.utc))
        except LookupError as exc:
            raise ApiError(409, "WITHDRAWAL_NOT_ALLOWED", "이미 탈퇴 대기 중이거나 내 매장이 아니에요.") from exc
        return _signed_out()
    avatar = await account.withdraw_staff(db, user_id=user_id)
    if avatar:
        background.add_task(_delete_avatar, avatar)
    return _signed_out()


# store-isolation-ok: 탈퇴 대기 중에는 매장 범위로 들어올 수 없다. 사장님 자신의 매장을 owner_id 로 찾는다
@router.get("/me/withdrawal")
async def get_withdrawal(db: Db, user_id: CurrentUserId) -> dict:
    """탈퇴 대기 안내 화면용. 대기 중이 아니면 due_at 은 null. 유예 일수는 화면 문구용(config 단일 출처)."""
    due = await account.withdrawal_due(db, user_id=user_id)
    return {"due_at": due.isoformat() if due else None, "grace_days": get_settings().withdrawal_grace_days}


# store-isolation-ok: 탈퇴 대기 중에는 매장 범위로 들어올 수 없다. 사장님 자신의 매장을 owner_id 로 찾는다
@router.post("/me/withdrawal/cancel", status_code=204)
async def cancel_withdrawal(db: Db, user_id: CurrentUserId) -> Response:
    """기한 안에 다시 로그인한 사장님이 탈퇴를 취소한다. 매장이 다시 열린다."""
    try:
        await account.cancel_withdrawal(db, user_id=user_id, now=datetime.now(timezone.utc))
    except account.WithdrawalExpired as exc:
        raise ApiError(409, "WITHDRAWAL_EXPIRED", "취소할 수 있는 기간이 지났어요.") from exc
    return Response(status_code=204)
