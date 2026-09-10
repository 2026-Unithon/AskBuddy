"""A01 이후 역할·매장 상태에 따른 첫 화면을 한 번에 결정한다."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.bootstrap.schemas import (
    BootstrapBadges,
    BootstrapResponse,
    BootstrapStore,
    BootstrapUser,
)
from app.deps import Db
from app.errors import ApiClaims, ApiError

router = APIRouter()


def _default_destination(role: str, has_store: bool, guide_completed: bool) -> str:
    if role == "OWNER":
        if not has_store:
            return "/owner/setup"
        return "/owner/questions" if guide_completed else "/owner/upload"
    return "/staff/roadmap" if has_store else "/staff/join"


@router.get("/bootstrap", response_model=BootstrapResponse)
async def get_bootstrap(
    db: Db,
    claims: ApiClaims,
) -> BootstrapResponse:
    user_id = claims.get("user_id")
    if user_id is None:
        raise ApiError(401, "AUTH_INVALID", "로그인 정보가 올바르지 않습니다.")

    user = await db.fetchrow(
        "select user_id, name, role from users where user_id = $1",
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
                   s.guide_completed_at, s.category_version
            from store_members sm
            join stores s on s.store_id = sm.store_id
            where sm.user_id = $1 and sm.store_id = $2
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
                      or needs_review_reason is not null)) as pending_cards
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
        ),
        store=store,
        badges=badges,
        default_destination=_default_destination(
            user["role"], membership is not None, guide_completed
        ),
    )
