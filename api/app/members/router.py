"""점주 직원 관리 API (이슈 #37). 모든 쿼리는 JWT 의 store_id 로 좁힌다."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.deps import Claims, CurrentStoreId, Db
from app.errors import ApiError
from app.members import invites

router = APIRouter()


async def get_owner_store_id(store_id: CurrentStoreId, claims: Claims) -> int:
    if claims.get("role") != "OWNER":
        raise ApiError(403, "FORBIDDEN", "사장님만 쓸 수 있어요.")
    return store_id


OwnerStoreId = Annotated[int, Depends(get_owner_store_id)]


@router.get("/invite-link")
async def get_invite_link(db: Db, store_id: OwnerStoreId):
    return {"url": invites.invite_url(await invites.get_or_create(db, store_id=store_id))}


@router.post("/invite-link/rotate")
async def rotate_invite_link(db: Db, store_id: OwnerStoreId):
    return {"url": invites.invite_url(await invites.rotate(db, store_id=store_id))}

from fastapi import BackgroundTasks

from app.auth.session import revoke_user_sessions
from app.deps import CurrentUserId
from app.members import repository
from app.notifications.service import deliver_notification


@router.get("")
async def list_members(db: Db, store_id: OwnerStoreId):
    return await repository.list_members(db, store_id=store_id)


@router.post("/requests/{request_id}/approve", status_code=204)
async def approve_request(request_id: int, db: Db, store_id: OwnerStoreId, owner_id: CurrentUserId,
                          background: BackgroundTasks):
    try:
        _, notification_id = await repository.approve(
            db, store_id=store_id, request_id=request_id, owner_id=owner_id)
    except LookupError as exc:
        raise ApiError(404, "NOT_FOUND", "요청을 찾을 수 없어요.") from exc
    except repository.OtherStore as exc:
        raise ApiError(409, "ALREADY_IN_OTHER_STORE", "이미 다른 매장에 합류한 계정이에요.") from exc
    except repository.AlreadyDecided as exc:
        raise ApiError(409, "ALREADY_DECIDED", "이미 처리된 요청이에요.") from exc
    if notification_id is not None:
        background.add_task(deliver_notification, store_id, notification_id)


@router.post("/requests/{request_id}/reject", status_code=204)
async def reject_request(request_id: int, db: Db, store_id: OwnerStoreId, owner_id: CurrentUserId):
    try:
        await repository.reject(db, store_id=store_id, request_id=request_id, owner_id=owner_id)
    except LookupError as exc:
        raise ApiError(404, "NOT_FOUND", "요청을 찾을 수 없어요.") from exc
    except repository.OtherStore as exc:
        raise ApiError(409, "ALREADY_IN_OTHER_STORE", "이미 다른 매장에 합류한 계정이에요.") from exc
    except repository.AlreadyDecided as exc:
        raise ApiError(409, "ALREADY_DECIDED", "이미 처리된 요청이에요.") from exc


@router.post("/{user_id}/remove", status_code=204)
async def remove_member(user_id: int, db: Db, store_id: OwnerStoreId, owner_id: CurrentUserId):
    try:
        await repository.remove(db, store_id=store_id, user_id=user_id, owner_id=owner_id)
    except repository.CannotRemoveOwner as exc:
        raise ApiError(400, "CANNOT_REMOVE_OWNER", "사장님 본인은 내보낼 수 없어요.") from exc
    except LookupError as exc:
        raise ApiError(404, "NOT_FOUND", "직원을 찾을 수 없어요.") from exc
    await revoke_user_sessions(db, user_id=user_id)
