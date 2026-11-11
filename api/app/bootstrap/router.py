"""A01 이후 역할·매장 상태에 따른 첫 화면을 한 번에 결정한다."""
from __future__ import annotations

import logging

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field, field_validator

from app.bootstrap.schemas import (
    BootstrapBadges,
    BootstrapResponse,
    BootstrapStore,
    BootstrapUser,
)
from app.bootstrap import profile
from app.config import get_settings
from app.ingest.preprocess.storage import create_signed_read_url, create_signed_upload_url
from app.deps import Db, raise_if_closed
from app.errors import ApiClaims, ApiError, OpenApiClaims

router = APIRouter()
logger = logging.getLogger(__name__)


def _default_destination(role: str | None, has_store: bool, guide_completed: bool) -> str:
    if role is None:
        return "/auth/role"
    if role == "OWNER":
        if not has_store:
            return "/owner/intent"
        return "/owner" if guide_completed else "/owner/add"
    return "/staff" if has_store else "/staff/pending"


@router.get("/bootstrap", response_model=BootstrapResponse)
async def get_bootstrap(
    db: Db,
    claims: OpenApiClaims,
) -> BootstrapResponse:
    """닫힌 매장도 여기까지는 온다: 탈퇴 대기 사장님은 취소 화면으로 보내고, 알바생은 STORE_CLOSED."""
    user_id = claims.get("user_id")
    if user_id is None:
        raise ApiError(401, "AUTH_INVALID", "로그인 정보가 올바르지 않습니다.")

    user = await db.fetchrow(
        "select user_id, name, role, avatar_path from users where user_id = $1",
        int(user_id),
    )
    if user is None or claims.get("role") != user["role"]:
        raise ApiError(401, "AUTH_INVALID", "로그인 정보가 올바르지 않습니다.")

    claimed_store_id = claims.get("store_id")
    if claimed_store_id is None:
        # 매장 범위는 요청값이나 추측이 아니라 로그인 시 발급한 JWT만 신뢰한다.
        membership = None
    else:
        membership = await db.fetchrow(
            """
            select sm.store_id, sm.member_role, s.store_name,
                   s.guide_completed_at, s.category_version,
                   s.closing_at, s.deleted_at, s.purge_due_at
            from store_members sm
            join stores s on s.store_id = sm.store_id
            where sm.user_id = $1 and sm.store_id = $2 and sm.removed_at is null
            limit 1
            """,
            int(user_id),
            int(claimed_store_id),
        )
        if membership is None:
            # 다른 매장의 존재 여부를 노출하지 않는다.
            raise ApiError(404, "STORE_NOT_FOUND", "접근할 수 있는 매장이 없습니다.")

    if membership is not None and membership["member_role"] != user["role"]:
        raise ApiError(403, "ROLE_MISMATCH", "이 역할로 매장에 접근할 수 없습니다.")

    withdrawal_due_at = None
    # .get: 위 쿼리는 늘 세 칸을 돌려준다. 칸이 없는 옛 가짜 DB(단위 테스트)는 열린 매장으로 본다
    closing_at = membership.get("closing_at") if membership is not None else None
    deleted_at = membership.get("deleted_at") if membership is not None else None
    if closing_at is not None or deleted_at is not None:
        if user["role"] == "OWNER" and deleted_at is None:
            withdrawal_due_at = membership.get("purge_due_at")
        else:
            raise_if_closed(role=user["role"], closing_at=closing_at, deleted_at=deleted_at)

    store: BootstrapStore | None = None
    badges = BootstrapBadges()
    guide_completed = False

    if membership is not None:
        store_id = int(membership["store_id"])
        guide_completed = membership["guide_completed_at"] is not None
        store = BootstrapStore(
            store_id=store_id,
            store_name=membership["store_name"],
            guide_completed=guide_completed,
            category_version=int(membership["category_version"]),
        )
        counts = await db.fetchrow(
            """
            select
              (select count(*) from pending_questions
               where store_id = $1 and status = 'WAITING') as waiting_questions,
              (select count(*) from knowledge_cards
               where store_id = $1
                 and review_status <> 'EXCLUDED'
                 and (review_status in ('PENDING', 'NEEDS_REVIEW')
                      or needs_review_reason is not null))
              + (select count(*) from knowledge_change_proposals
                 where store_id = $1 and status = 'PENDING_REVIEW') as pending_cards
            """,
            store_id,
        )
        badges = BootstrapBadges(
            waiting_questions=int(counts["waiting_questions"]),
            pending_cards=int(counts["pending_cards"]),
        )

    return BootstrapResponse(
        user=BootstrapUser(
            user_id=int(user["user_id"]),
            role=user["role"],
            name=user["name"],
            avatar_url=await _avatar_url(user["avatar_path"]),
        ),
        store=store,
        badges=badges,
        default_destination="/withdrawal" if withdrawal_due_at is not None else _default_destination(
            user["role"], membership is not None, guide_completed
        ),
        withdrawal_due_at=withdrawal_due_at,
    )


class RenameRequest(BaseModel):
    name: str = Field(min_length=1, max_length=50)

    @field_validator("name")
    @classmethod
    def _trim(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("이름을 적어 주세요.")
        return value


@router.patch("/me", status_code=204)
# store-isolation-ok: 매장 데이터가 아니라 로그인한 본인(JWT user_id)의 사용자 행 이름만 바꾼다
async def rename_me(req: RenameRequest, db: Db, claims: ApiClaims) -> None:
    """내 이름 고치기(계획 7 Task 9, o12a)."""
    user_id = claims.get("user_id")
    if user_id is None:
        raise ApiError(401, "UNAUTHORIZED", "다시 로그인해 주세요.")
    await profile.rename_user(db, int(user_id), req.name)


@router.patch("/store", status_code=204)
async def rename_store(req: RenameRequest, db: Db, claims: ApiClaims) -> None:
    """매장 이름 고치기. 사장님만, JWT 의 매장만."""
    if claims.get("role") != "OWNER" or claims.get("store_id") is None:
        raise ApiError(403, "OWNER_ONLY", "매장 이름은 사장님만 바꿀 수 있어요.")
    await profile.rename_store(db, int(claims["store_id"]), req.name)


async def _avatar_url(path: str | None) -> str | None:
    """사진은 비공개 버킷이라 잠깐 읽는 URL 로 준다. 못 만들면 사진 없이(첫 글자) 보인다."""
    if not path:
        return None
    try:
        return await create_signed_read_url(path, get_settings().avatar_read_seconds)
    except Exception:  # noqa: BLE001 — 사진 하나 때문에 시작 화면을 막지 않는다
        logger.warning("avatar sign failed", exc_info=True)
        return None


class AvatarUploadRequest(BaseModel):
    content_type: str
    size: int = Field(gt=0)

    @field_validator("size")
    @classmethod
    def _small(cls, value: int) -> int:
        if value > get_settings().avatar_max_bytes:
            raise ValueError("사진이 너무 커요. 5MB 아래로 골라 주세요.")
        return value


class AvatarUploadResponse(BaseModel):
    upload_url: str
    path: str


class AvatarSetRequest(BaseModel):
    # null 이면 사진을 뺀다
    path: str | None = None


def _me(claims) -> tuple[int, int]:
    user_id, store_id = claims.get("user_id"), claims.get("store_id")
    if user_id is None:
        raise ApiError(401, "UNAUTHORIZED", "다시 로그인해 주세요.")
    if store_id is None:
        raise ApiError(403, "STORE_REQUIRED", "매장에 들어간 뒤 사진을 바꿀 수 있어요.")
    return int(user_id), int(store_id)


@router.post("/me/avatar/upload-url", response_model=AvatarUploadResponse)
async def avatar_upload_url(req: AvatarUploadRequest, claims: ApiClaims) -> AvatarUploadResponse:
    """프로필 사진을 브라우저가 직접 올릴 서명 URL(불변식 7). 경로는 JWT 의 매장·사람으로만 만든다."""
    user_id, store_id = _me(claims)
    try:
        path = profile.avatar_object_path(store_id, user_id, req.content_type)
    except ValueError as exc:
        raise ApiError(422, "AVATAR_TYPE", str(exc)) from exc
    return AvatarUploadResponse(upload_url=await create_signed_upload_url(path), path=path)


@router.put("/me/avatar", status_code=204)
# store-isolation-ok: 본인(JWT user_id) 행만 바꾸고, 경로가 JWT 매장·본인 몫인지 확인한다
async def set_avatar(req: AvatarSetRequest, db: Db, claims: ApiClaims) -> None:
    """올린 사진을 내 프로필로. 다른 사람·다른 매장 경로는 거절한다."""
    user_id, store_id = _me(claims)
    if req.path is not None and not profile.owns_avatar_path(req.path, store_id=store_id, user_id=user_id):
        raise ApiError(403, "AVATAR_PATH", "이 사진은 쓸 수 없어요.")
    await profile.set_avatar(db, user_id, req.path)
