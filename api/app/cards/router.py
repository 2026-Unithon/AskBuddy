from __future__ import annotations

import logging
import json
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query

from app.cards import repository as repo
from app.cards.schemas import (
    CardCategory,
    CardDetail,
    CardEvidence,
    CardList,
    CardListItem,
    CardMutationResult,
    CardReviewEvent,
    CardSource,
    CardVersion,
    CategoryUpdateRequest,
    DraftUpdateRequest,
)
from app.deps import Db
from app.errors import ApiClaims, ApiError
from app.ingest.embed import embed_card
from app.ingest.preprocess.storage import create_signed_read_url

logger = logging.getLogger(__name__)
router = APIRouter()


def _identity(claims: dict[str, Any], *, owner_only: bool = False) -> tuple[int, int, str]:
    role = str(claims.get("role", ""))
    if owner_only and role != "OWNER":
        raise ApiError(403, "OWNER_ONLY", "카드는 사장님만 검수할 수 있습니다.")
    if role not in ("OWNER", "STAFF"):
        raise ApiError(403, "ROLE_NOT_ALLOWED", "카드에 접근할 권한이 없습니다.")
    user_id = claims.get("user_id")
    store_id = claims.get("store_id")
    if user_id is None or store_id is None:
        raise ApiError(403, "STORE_REQUIRED", "먼저 매장에 연결해 주세요.")
    return int(user_id), int(store_id), role


async def require_owner(claims: ApiClaims) -> dict[str, Any]:
    _identity(claims, owner_only=True)
    return claims


OwnerClaims = Annotated[dict[str, Any], Depends(require_owner)]


def _category(row) -> CardCategory | None:
    if row["category_id"] is None:
        return None
    return CardCategory(category_id=int(row["category_id"]), name=row["category_name"] or "")


def _source(row, *, read_url: str | None = None) -> CardSource | None:
    if row["source_id"] is None:
        return None
    return CardSource(
        source_id=int(row["source_id"]),
        title=row["source_title"],
        source_type=row["source_type"],
        read_url=read_url,
    )


def _version(row) -> CardVersion | None:
    return CardVersion(**dict(row)) if row else None


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        return json.loads(value)
    return dict(value or {})


def _mutation(row, *, undo_until: datetime | None = None) -> CardMutationResult:
    return CardMutationResult(
        card_id=int(row["card_id"]),
        review_status=row["review_status"],
        draft_version_id=row["draft_version_id"],
        published_version_id=row["published_version_id"],
        updated_at=row["updated_at"],
        undo_until=undo_until,
    )


async def _evidence_items(db: Db, store_id: int, version_id: int) -> list[CardEvidence]:
    rows = await repo.list_evidence(db, store_id, version_id)
    urls: dict[int, str | None] = {}
    items: list[CardEvidence] = []
    for row in rows:
        source_id = int(row["source_id"])
        if source_id not in urls:
            try:
                urls[source_id] = (
                    await create_signed_read_url(row["file_url"])
                    if row["file_url"]
                    else None
                )
            except RuntimeError:
                logger.warning("근거 원본 URL 발급 실패 source=%s", source_id, exc_info=True)
                urls[source_id] = None
        items.append(
            CardEvidence(
                evidence_id=int(row["evidence_id"]),
                locator_type=row["locator_type"],
                locator=_json_object(row["locator"]),
                excerpt=row["excerpt"],
                source=_source(row, read_url=urls[source_id]),
            )
        )
    return items


@router.get("", response_model=CardList)
async def list_cards(
    db: Db,
    claims: ApiClaims,
    review_status: Literal["pending", "needs_review", "approved", "excluded", "all"] = "pending",
    job_id: int | None = Query(default=None, gt=0),
    category_id: int | None = Query(default=None, gt=0),
    query: str | None = Query(default=None, min_length=1, max_length=200),
    cursor: int | None = Query(default=None, gt=0),
    limit: int = Query(default=20, ge=1, le=100),
) -> CardList:
    _, store_id, role = _identity(claims)
    staff = role == "STAFF"
    normalized_query = query.strip() if query else None
    rows = await repo.list_cards(
        db,
        store_id,
        review_status=review_status,
        job_id=job_id,
        category_id=category_id,
        query=normalized_query,
        cursor=cursor,
        limit=limit + 1,
        staff=staff,
    )
    total = await repo.count_cards(
        db,
        store_id,
        review_status=review_status,
        job_id=job_id,
        category_id=category_id,
        query=normalized_query,
        staff=staff,
    )
    has_more = len(rows) > limit
    rows = rows[:limit]
    return CardList(
        items=[
            CardListItem(
                card_id=int(row["card_id"]),
                review_status=row["review_status"],
                title=row["title"],
                content=row["content"],
                category=_category(row),
                assignment_type=row["assignment_type"],
                source=_source(row),
                job_id=row["origin_job_id"],
                has_evidence=bool(row["has_evidence"]),
                needs_review_reason=row["needs_review_reason"],
                updated_at=row["updated_at"],
            )
            for row in rows
        ],
        next_cursor=int(rows[-1]["card_id"]) if has_more else None,
        total=total,
    )


async def _detail(db: Db, store_id: int, card_id: int, role: str) -> CardDetail:
    row = await repo.get_card(db, store_id, card_id)
    if row is None or (
        role == "STAFF"
        and (row["review_status"] != "APPROVED" or row["published_version_id"] is None)
    ):
        raise ApiError(404, "CARD_NOT_FOUND", "카드를 찾을 수 없습니다.")
    draft = None
    if role == "OWNER":
        draft = await repo.get_version(db, store_id, row["draft_version_id"])
    published = await repo.get_version(db, store_id, row["published_version_id"])
    visible_version_id = (
        row["published_version_id"] if role == "STAFF" else row["draft_version_id"]
    )
    evidence = (
        await _evidence_items(db, store_id, int(visible_version_id))
        if visible_version_id is not None
        else []
    )
    events = []
    if role == "OWNER":
        events = [
            CardReviewEvent(**{**dict(item), "metadata": _json_object(item["metadata"])})
            for item in await repo.list_events(db, store_id, card_id)
        ]
    return CardDetail(
        card_id=card_id,
        review_status=row["review_status"],
        assignment_type=row["assignment_type"],
        category=_category(row),
        source=_source(row),
        job_id=row["origin_job_id"],
        needs_review_reason=row["needs_review_reason"],
        draft=_version(draft),
        published=_version(published),
        evidence=evidence,
        events=events,
        updated_at=row["updated_at"],
    )


@router.get("/{card_id}", response_model=CardDetail)
async def get_card(card_id: int, db: Db, claims: ApiClaims) -> CardDetail:
    _, store_id, role = _identity(claims)
    return await _detail(db, store_id, card_id, role)


@router.patch("/{card_id}/draft", response_model=CardMutationResult)
async def update_draft(
    card_id: int, req: DraftUpdateRequest, db: Db, claims: OwnerClaims
) -> CardMutationResult:
    user_id, store_id, _ = _identity(claims, owner_only=True)
    async with db.transaction():
        card = await repo.get_card_for_update(db, store_id, card_id)
        if card is None:
            raise ApiError(404, "CARD_NOT_FOUND", "카드를 찾을 수 없습니다.")
        if card["review_status"] == "EXCLUDED":
            raise ApiError(409, "CARD_EXCLUDED", "제외된 카드를 먼저 복원해 주세요.")
        if card["draft_version_id"] != req.expected_version_id:
            raise ApiError(
                409,
                "CARD_VERSION_CONFLICT",
                "다른 변경 사항이 먼저 저장되었습니다. 최신 내용을 다시 확인해 주세요.",
                details={"current_version_id": card["draft_version_id"]},
            )
        version_id = await repo.create_draft(
            db,
            store_id,
            card_id,
            title=req.title,
            content=req.content,
            actor_id=user_id,
            source_version_id=req.expected_version_id,
        )
        await repo.add_event(
            db,
            store_id,
            card_id,
            user_id,
            "EDIT_DRAFT",
            from_status=card["review_status"],
            to_status=card["review_status"],
            metadata={"from_version_id": req.expected_version_id, "to_version_id": version_id},
        )
        row = await repo.mutation_row(db, store_id, card_id)
    return _mutation(row)


@router.post("/{card_id}/approve", response_model=CardMutationResult)
async def approve_card(
    card_id: int, db: Db, claims: OwnerClaims
) -> CardMutationResult:
    user_id, store_id, _ = _identity(claims, owner_only=True)
    try:
        async with db.transaction():
            card = await repo.get_card_for_update(db, store_id, card_id)
            if card is None:
                raise ApiError(404, "CARD_NOT_FOUND", "카드를 찾을 수 없습니다.")
            if card["draft_version_id"] is None:
                raise ApiError(409, "CARD_DRAFT_MISSING", "승인할 초안이 없습니다.")
            action = (
                "PUBLISH_EDIT"
                if card["published_version_id"] is not None
                and card["published_version_id"] != card["draft_version_id"]
                else "APPROVE"
            )
            await db.execute(
                """
                update knowledge_cards
                set review_status = 'APPROVED', published_version_id = draft_version_id,
                    excluded_at = null, excluded_by = null, needs_review_reason = null
                where store_id = $1 and card_id = $2
                """,
                store_id,
                card_id,
            )
            await embed_card(db, store_id, card_id)
            await repo.add_event(
                db,
                store_id,
                card_id,
                user_id,
                action,
                from_status=card["review_status"],
                to_status="APPROVED",
                metadata={"published_version_id": card["draft_version_id"]},
            )
            row = await repo.mutation_row(db, store_id, card_id)
    except ApiError:
        raise
    except Exception as exc:
        logger.exception("카드 승인 실패 card=%s store=%s", card_id, store_id)
        raise ApiError(
            502,
            "CARD_PUBLISH_FAILED",
            "카드를 공개하지 못했습니다. 기존 공개 상태는 유지됩니다.",
            retryable=True,
        ) from exc
    return _mutation(row)


@router.post("/{card_id}/exclude", response_model=CardMutationResult)
async def exclude_card(
    card_id: int, db: Db, claims: OwnerClaims
) -> CardMutationResult:
    user_id, store_id, _ = _identity(claims, owner_only=True)
    undo_until = datetime.now(timezone.utc) + timedelta(seconds=10)
    async with db.transaction():
        card = await repo.get_card_for_update(db, store_id, card_id)
        if card is None:
            raise ApiError(404, "CARD_NOT_FOUND", "카드를 찾을 수 없습니다.")
        if card["review_status"] == "EXCLUDED":
            raise ApiError(409, "CARD_ALREADY_EXCLUDED", "이미 제외된 카드입니다.")
        await db.execute(
            """
            update knowledge_cards
            set review_status = 'EXCLUDED', excluded_at = now(), excluded_by = $3
            where store_id = $1 and card_id = $2
            """,
            store_id,
            card_id,
            user_id,
        )
        await repo.add_event(
            db,
            store_id,
            card_id,
            user_id,
            "EXCLUDE",
            from_status=card["review_status"],
            to_status="EXCLUDED",
            metadata={"undo_until": undo_until.isoformat()},
        )
        row = await repo.mutation_row(db, store_id, card_id)
    return _mutation(row, undo_until=undo_until)


@router.post("/{card_id}/restore", response_model=CardMutationResult)
async def restore_card(
    card_id: int, db: Db, claims: OwnerClaims
) -> CardMutationResult:
    user_id, store_id, _ = _identity(claims, owner_only=True)
    async with db.transaction():
        card = await repo.get_card_for_update(db, store_id, card_id)
        if card is None:
            raise ApiError(404, "CARD_NOT_FOUND", "카드를 찾을 수 없습니다.")
        if card["review_status"] != "EXCLUDED":
            raise ApiError(409, "CARD_NOT_EXCLUDED", "제외된 카드만 복원할 수 있습니다.")
        target = "APPROVED" if card["published_version_id"] is not None else "PENDING"
        await db.execute(
            """
            update knowledge_cards
            set review_status = $3, excluded_at = null, excluded_by = null
            where store_id = $1 and card_id = $2
            """,
            store_id,
            card_id,
            target,
        )
        await repo.add_event(
            db,
            store_id,
            card_id,
            user_id,
            "RESTORE",
            from_status="EXCLUDED",
            to_status=target,
        )
        row = await repo.mutation_row(db, store_id, card_id)
    return _mutation(row)


@router.patch("/{card_id}/category", response_model=CardMutationResult)
async def update_category(
    card_id: int, req: CategoryUpdateRequest, db: Db, claims: OwnerClaims
) -> CardMutationResult:
    user_id, store_id, _ = _identity(claims, owner_only=True)
    async with db.transaction():
        card = await repo.get_card_for_update(db, store_id, card_id)
        if card is None:
            raise ApiError(404, "CARD_NOT_FOUND", "카드를 찾을 수 없습니다.")
        if card["updated_at"] != req.expected_updated_at:
            raise ApiError(
                409,
                "CARD_UPDATE_CONFLICT",
                "다른 변경 사항이 먼저 저장되었습니다. 최신 내용을 다시 확인해 주세요.",
                details={"current_updated_at": card["updated_at"].isoformat()},
            )
        if await repo.active_category(db, store_id, req.category_id) is None:
            raise ApiError(404, "CATEGORY_NOT_FOUND", "카테고리를 찾을 수 없습니다.")
        category_version = await db.fetchval(
            "select category_version from stores where store_id = $1", store_id
        )
        await db.execute(
            """
            update knowledge_cards
            set category_id = $3, category_version = $4, assignment_type = 'MANUAL',
                needs_review_reason = case
                  when needs_review_reason = 'CATEGORY_DELETED' then null
                  else needs_review_reason
                end
            where store_id = $1 and card_id = $2
            """,
            store_id,
            card_id,
            req.category_id,
            category_version,
        )
        await db.execute(
            """
            update roadmap_items
            set category_id = $3
            where card_id = $2 and exists (
              select 1 from roadmap_stages s
              where s.stage_id = roadmap_items.stage_id and s.store_id = $1
            )
            """,
            store_id,
            card_id,
            req.category_id,
        )
        await repo.add_event(
            db,
            store_id,
            card_id,
            user_id,
            "MOVE_CATEGORY",
            from_status=card["review_status"],
            to_status=card["review_status"],
            from_category_id=card["category_id"],
            to_category_id=req.category_id,
        )
        row = await repo.mutation_row(db, store_id, card_id)
    return _mutation(row)


@router.get("/{card_id}/evidence", response_model=list[CardEvidence])
async def get_evidence(card_id: int, db: Db, claims: ApiClaims) -> list[CardEvidence]:
    _, store_id, role = _identity(claims)
    card = await repo.get_card(db, store_id, card_id)
    if card is None or (
        role == "STAFF"
        and (card["review_status"] != "APPROVED" or card["published_version_id"] is None)
    ):
        raise ApiError(404, "CARD_NOT_FOUND", "카드를 찾을 수 없습니다.")
    version_id = (
        card["published_version_id"] if role == "STAFF" else card["draft_version_id"]
    )
    return await _evidence_items(db, store_id, int(version_id)) if version_id else []
