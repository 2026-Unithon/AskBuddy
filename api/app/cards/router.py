from __future__ import annotations

import hashlib
import logging
from contextvars import ContextVar
import json
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query

from app.cards import fact_edit
from app.cards import fact_edit_repo as fact_repo
from app.cards import fact_parse
from app.cards import repository as repo
from app.cards.review_items import load_review_items, write_items
from app.cards.fact_edit_revert import plan_revert
from app.ingest import fact_revisions
from app.checklist import repository as checklist_repo
from app.cards.fact_edit_plan import CardFactState, EditError
from app.cards.fact_edit_schemas import (
    CardFactsView,
    EditBlock,
    EditKeep,
    FactBlockView,
    FactEditRequest,
    FactEditResult,
    FactOrigin,
    FactRequirement,
    FactParseRequest,
    FactParseResponse,
    FactRow,
    FactVariant,
    ReviewChooseRequest,
    ReviewWriteRequest,
    EditModify,
    FactFields,
    RevertRequest,
)
from app.cards.schemas import (
    BulkItem,
    BulkRequest,
    BulkResult,
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
)
from app.deps import Db, get_pool
from app.errors import ApiClaims, ApiError
from app.ingest.card_plan import PlanFact
from app.ingest.embed import card_usage_context
from app.ingest.preprocess.storage import create_signed_read_url
from app.publish import CardChange, publish_cards

logger = logging.getLogger(__name__)
router = APIRouter()


# R 준비·공개 경합에서 진 요청의 오류 코드. 재시도로 풀리는 충돌이라 409 로 돌려준다
_PREPARE_RACE_CODES = frozenset({"STALE_PUBLICATION", "STALE_KNOWLEDGE", "IDEMPOTENCY_CONFLICT"})


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
    return CardCategory(category_id=int(row["category_id"]), name=row["category_name"] or "",
                        kind=row["category_kind"] if "category_kind" in row.keys() else None)


def _source(row, *, read_url: str | None = None) -> CardSource | None:
    if row["source_id"] is None:
        return None
    availability = row.get("source_availability")
    return CardSource(
        source_id=int(row["source_id"]),
        title=row["source_title"],
        source_type=row["source_type"],
        read_url=read_url,
        source_availability=availability or "AVAILABLE",
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
        if source_id not in urls and (row.get("source_availability") or "AVAILABLE") != "AVAILABLE":
            # D20: 삭제된 자료는 원본 열람 URL 을 발급하지 않는다(원본 접근 해제)
            urls[source_id] = None
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
    # 직원은 초안을 보지 않으므로 사실 카드 표시·편집 가능 여부도 점주에게만 준다
    fact_card = False
    if role == "OWNER":
        fact_card = await repo.has_block_facts(db, store_id, row["draft_version_id"])
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
        fact_card=fact_card,
    )


@router.get("/{card_id}", response_model=CardDetail)
async def get_card(card_id: int, db: Db, claims: ApiClaims) -> CardDetail:
    _, store_id, role = _identity(claims)
    return await _detail(db, store_id, card_id, role)


@router.post("/{card_id}/approve", response_model=CardMutationResult)
async def approve_card(
    card_id: int, db: Db, claims: OwnerClaims
) -> CardMutationResult:
    """승인 → `publish_cards` 조정자로 판을 올린다 (즉시 색인 직행 경로 제거).

    사전 CAS 검사는 요청 커넥션(`db`)으로 끝내고, `publish_cards` 는 자기
    풀을 스스로 관리한다. `db` 에 열린 트랜잭션·잠금을 쥔 채로 넘기지 않는다.
    """
    user_id, store_id, _ = _identity(claims, owner_only=True)
    try:
        expected = await db.fetchrow(
            "select draft_version_id, published_version_id, review_status from knowledge_cards "
            "where store_id = $1 and card_id = $2", store_id, card_id)
        if expected is None:
            raise ApiError(404, "CARD_NOT_FOUND", "카드를 찾을 수 없습니다.")
        draft_version_id = expected["draft_version_id"]
        if draft_version_id is None:
            raise ApiError(409, "CARD_DRAFT_MISSING", "승인할 초안이 없습니다.")
        if expected["review_status"] == "EXCLUDED":
            raise ApiError(409, "CARD_EXCLUDED", "제외된 카드를 먼저 복원해 주세요.")

        member_id = await db.fetchval(
            "select member_id from store_members where store_id = $1 and user_id = $2 "
            "and member_role = 'OWNER'",
            store_id,
            user_id,
        )
        if member_id is None:
            raise ApiError(403, "OWNER_ONLY", "카드는 사장님만 검수할 수 있습니다.")

        context = await card_usage_context(db, store_id, card_id)
        result = await publish_cards(
            get_pool(),
            store_id=store_id,
            member_id=int(member_id),
            actor_user_id=user_id,
            changes=[CardChange(
                card_id=card_id,
                expected_draft_version_id=draft_version_id,
                target_card_version_id=draft_version_id,
            )],
            idempotency_key=f"approve:{card_id}:{draft_version_id}",
            usage_context=context,
        )

        if result.status in ("PUBLISHED", "ALREADY_APPLIED"):
            if expected["published_version_id"] is None:
                await _default_checklist_link(db, store_id, card_id)
            return _mutation(await repo.mutation_row(db, store_id, card_id))
        if result.status == "NO_PROVENANCE":
            raise ApiError(
                409,
                "CARD_NO_PROVENANCE",
                "출처를 확인할 수 없는 카드는 아직 공개할 수 없습니다.",
            )
        if result.status == "INVALID_CONTENT":
            raise ApiError(
                409,
                "CARD_CONTENT_INVALID",
                "카드 내용이 비어 있거나 너무 길어 공개할 수 없습니다.",
            )
        if result.status == "STALE" or (
            result.status == "PREPARE_FAILED" and result.error_code in _PREPARE_RACE_CODES
        ):
            # 준비 사이 다른 공개가 먼저 판을 올렸다 — 경합에서 진 것이지 장애가 아니다
            raise ApiError(
                409,
                "CARD_VERSION_CONFLICT",
                "다른 변경 사항이 먼저 저장되었습니다. 최신 내용을 다시 확인해 주세요.",
            )
        if result.status == "PREPARE_FAILED":
            raise ApiError(
                502,
                "CARD_PUBLISH_FAILED",
                "카드를 공개하지 못했습니다. 기존 공개 상태는 유지됩니다.",
                retryable=True,
            )
        # 계약에 없는 status 는 조용히 PREPARE_FAILED 취급하지 않고 크게 실패시킨다.
        # 아래 except Exception 이 잡아 502 CARD_PUBLISH_FAILED 로 매핑한다
        raise RuntimeError(f"publish_cards 가 알 수 없는 상태를 반환했다: {result.status}")
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


# 일괄 처리 중에는 카드마다 공개 판을 다시 올리지 않고 모아 두었다가 끝에 한 번 올린다(계획 7 Task 4)
_DEFERRED_REPUBLISH: ContextVar[list[tuple[int, int]] | None] = ContextVar("_DEFERRED_REPUBLISH", default=None)


async def _republish_after_status_change(
    db: Db, *, store_id: int, user_id: int, card_id: int, kind: str, event_id: int
) -> None:
    """제외·복원 커밋 뒤 현재 공개 포인터로 공개판을 다시 올린다 (best-effort).

    제외·복원은 카드 공개 포인터를 옮기지 않고 실릴 카드 집합만 바꾼다. 그래서
    `publish_cards(changes=[])` 로 현재 포인터 그대로 재발행해 R 색인을 맞춘다.
    상태 변경은 이미 커밋됐고, 재발행이 실패해도 요청은 성공으로 돌려준다:
      - 제외는 R 조회가 이미 `review_status` 로 걸러 즉시 반영된다.
      - 복원은 다음 공개(아무 카드 승인·재발행)가 현재 포인터로 manifest 를
        만들므로 스스로 회복된다.
    실패는 크게 로그로 남긴다. 멱등 키는 검수 사건 id 로 행동마다 유일하다.
    재발행 임베딩 비용은 이 카드의 비용 귀속(card_usage_context)으로 잡힌다.
    """
    deferred = _DEFERRED_REPUBLISH.get()
    if deferred is not None:
        deferred.append((card_id, event_id))
        return
    try:
        member_id = await db.fetchval(
            "select member_id from store_members where store_id = $1 and user_id = $2 "
            "and member_role = 'OWNER'",
            store_id,
            user_id,
        )
        if member_id is None:
            raise LookupError("점주 멤버십을 찾을 수 없다")
        context = await card_usage_context(db, store_id, card_id)
        result = await publish_cards(
            get_pool(),
            store_id=store_id,
            member_id=int(member_id),
            actor_user_id=user_id,
            changes=[],
            idempotency_key=f"{kind}:{card_id}:{event_id}",
            usage_context=context,
        )
    except Exception:
        logger.exception(
            "카드 %s 뒤 공개판 재발행 실패 — 다음 공개에서 회복된다 card=%s store=%s",
            kind, card_id, store_id)
        return
    if result.status not in ("PUBLISHED", "ALREADY_APPLIED", "EMPTY_MANIFEST"):
        logger.warning(
            "카드 %s 뒤 공개판 재발행을 하지 못했다 — 다음 공개에서 회복된다 "
            "card=%s store=%s status=%s code=%s",
            kind, card_id, store_id, result.status, result.error_code)


@router.post("/{card_id}/unpublish", response_model=CardMutationResult)
async def unpublish_card(
    card_id: int, db: Db, claims: OwnerClaims
) -> CardMutationResult:
    """미공개(공개 내리기, 계획 7 Task 3). 공개였거나 검수 필요였던 카드를 공개 전으로 돌린다.

    공개 포인터를 비워 직원 레시피·검색·답변(공개 판)에서 빠지게 한다. 초안은 그대로라 다시 공개하면
    같은 판이 올라가 학습 기록이 이어진다. 학습 기록·근무조 연결 표는 건드리지 않는다.
    """
    user_id, store_id, _ = _identity(claims, owner_only=True)
    async with db.transaction():
        card = await repo.get_card_for_update(db, store_id, card_id)
        if card is None:
            raise ApiError(404, "CARD_NOT_FOUND", "카드를 찾을 수 없습니다.")
        if card["review_status"] not in ("APPROVED", "NEEDS_REVIEW"):
            raise ApiError(409, "CARD_NOT_PUBLISHED", "공개했거나 검수가 필요한 카드만 미공개로 바꿀 수 있습니다.")
        await db.execute(
            """
            update knowledge_cards
            set review_status = 'PENDING', published_version_id = null
            where store_id = $1 and card_id = $2
            """,
            store_id,
            card_id,
        )
        event_id = await repo.add_event(
            db, store_id, card_id, user_id, "UNPUBLISH",
            from_status=card["review_status"], to_status="PENDING",
        )
        row = await repo.mutation_row(db, store_id, card_id)
    # 공개 판에 있던 카드만 다시 올려 R 색인에서 뺀다
    if card["published_version_id"] is not None:
        await _republish_after_status_change(
            db, store_id=store_id, user_id=user_id, card_id=card_id,
            kind="unpublish", event_id=event_id)
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
        event_id = await repo.add_event(
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
    # 상태 변경 커밋 뒤 R 색인에서도 빼도록 재발행한다. 실패해도 요청은 성공이다.
    # 한 번도 공개되지 않은 카드는 어느 판에도 없으므로 재발행하지 않는다
    if card["published_version_id"] is not None:
        await _republish_after_status_change(
            db, store_id=store_id, user_id=user_id, card_id=card_id,
            kind="exclude", event_id=event_id)
    return _mutation(row, undo_until=undo_until)


async def _default_checklist_link(db, store_id: int, card_id: int) -> None:
    """처음 공개한 할 일 카드를 모든 근무조에 켠다. 실패해도 공개는 이미 끝났으므로 요청은 성공이다."""
    try:
        await checklist_repo.add_default_link(db, store_id, card_id)
    except Exception:  # noqa: BLE001 — 기본 연결은 부가 동작
        logger.exception("default checklist link failed card=%s store=%s", card_id, store_id)


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
        # 공개 전 카드는 빼기 전 상태로 돌린다. '검수 필요'였으면 이유(needs_review_reason)와 함께 살아난다
        if card["published_version_id"] is not None:
            target = "APPROVED"
        else:
            prior = await repo.last_exclude_from_status(db, store_id, card_id)
            target = "NEEDS_REVIEW" if prior == "NEEDS_REVIEW" else "PENDING"
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
        event_id = await repo.add_event(
            db,
            store_id,
            card_id,
            user_id,
            "RESTORE",
            from_status="EXCLUDED",
            to_status=target,
        )
        row = await repo.mutation_row(db, store_id, card_id)
    # 공개 포인터가 있던 카드는 복원 즉시 R 색인에 돌아오도록 재발행한다.
    # 초안만 있던 카드(PENDING 복귀)는 manifest 가 그대로라 재발행하지 않는다
    if target == "APPROVED":
        await _republish_after_status_change(
            db, store_id=store_id, user_id=user_id, card_id=card_id,
            kind="restore", event_id=event_id)
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


# ── W3b 사실 카드 읽기 ──────────────────────────────────────────────────────

_OTHER_CARD_LABEL = "(다른 카드)"


def requirement_labels(
    requires_fact_ids: tuple[int, ...] | list[int], by_fact: dict[int, PlanFact]
) -> list[FactRequirement]:
    """선행 사실 라벨. 같은 카드 단계면 "{n}번", 단계가 아니면 문장 앞 40자, 카드에 없으면 "(다른 카드)"."""
    out: list[FactRequirement] = []
    for fact_id in requires_fact_ids:
        target = by_fact.get(fact_id)
        if target is None:
            label = _OTHER_CARD_LABEL
        elif target.step_order is not None:
            label = f"{target.step_order}번"
        else:
            label = " ".join(target.original_assertion.split())[:40]
        out.append(FactRequirement(fact_id=fact_id, label=label))
    return out


def fact_row_view(
    fact: PlanFact,
    position: int,
    extra: dict[str, Any],
    by_fact: dict[int, PlanFact],
    edit_block: str | None,
) -> FactRow:
    """판 하나 → 화면 줄. 수치면 value=decimal 문자열(뒤 0 없음)+unit, 아니면 value_text(unit 없음)."""
    if fact.quantity_value is not None:
        value: str | None = format(fact.quantity_value.normalize(), "f")
        unit = fact.quantity_unit
    else:
        value, unit = fact.value_text, None
    return FactRow(
        fact_revision_id=fact.fact_revision_id,
        fact_id=fact.fact_id,
        position=position,
        sentence=fact.original_assertion,
        assertion=fact.assertion,
        subject=fact.subject,
        predicate=fact.predicate,
        variant=FactVariant(temperature=fact.variant_temperature, size=fact.variant_size),
        value=value,
        unit=unit,
        polarity=fact.polarity,
        step_order=fact.step_order,
        conditions=list(fact.conditions),
        exceptions=list(fact.exceptions),
        requires=requirement_labels(fact.requires_fact_ids, by_fact),
        change_kind=extra.get("change_kind"),
        previous_sentence=extra.get("previous_sentence"),
        origins=[FactOrigin(**o) for o in extra.get("origins", [])],
        edit_block=edit_block,  # type: ignore[arg-type]
    )


def build_facts_view(
    state: CardFactState,
    rows: dict[int, dict[str, Any]],
    heads: dict[int, fact_repo.HeadInfo],
) -> CardFactsView:
    """고정 상태 + 판별 칸 + head 분류 → 응답. 순서는 state 그대로(블록 순 → 줄 순)."""
    by_fact = {p.fact.fact_id: p.fact for p in state.pinned}
    blocks: list[FactBlockView] = []
    for block_id, kind, order in state.blocks:
        lines = [p for p in state.pinned if p.block_id == block_id]
        facts = [
            fact_row_view(
                p.fact,
                p.position,
                rows.get(p.fact.fact_revision_id, {}),
                by_fact,
                heads[p.fact.fact_id].edit_block if p.fact.fact_id in heads else None,
            )
            for p in lines
        ]
        variant = facts[0].variant if facts else FactVariant()
        blocks.append(
            FactBlockView(
                block_id=block_id, kind=kind, order=order, variant=variant, facts=facts
            )  # type: ignore[arg-type]
        )
    return CardFactsView(
        card_id=state.card_id,
        version_id=state.version_id,
        title=state.title,
        entity_id=state.entity_id,
        entity_name=state.entity_name or None,
        review_status=state.review_status,  # type: ignore[arg-type]
        published_version_id=state.published_version_id,
        editable=bool(state.review_status != "EXCLUDED" and state.entity_problem is None),
        entity_problem=state.entity_problem,  # type: ignore[arg-type]
        blocks=blocks,
    )


@router.get("/{card_id}/facts", response_model=CardFactsView)
async def get_card_facts(card_id: int, db: Db, claims: OwnerClaims) -> CardFactsView:
    """사실 카드의 초안 판을 사실 줄 단위로 돌려준다. 점주 전용, 트랜잭션 없이 읽는다."""
    _, store_id, _ = _identity(claims, owner_only=True)
    card = await repo.get_card(db, store_id, card_id)
    if card is None:
        raise ApiError(404, "CARD_NOT_FOUND", "카드를 찾을 수 없습니다.")
    not_fact = ApiError(409, "NOT_FACT_CARD", "사실 단위로 고칠 수 있는 카드가 아닙니다.")
    if card["draft_version_id"] is None:
        raise not_fact
    state = await fact_repo.load_card_fact_state(
        db, store_id, card_id, int(card["draft_version_id"])
    )
    if state is None:
        raise not_fact
    rows = await fact_repo.load_fact_rows(db, store_id, state)
    # 대상이 하나로 정해진 카드만 head 대상 비교가 뜻이 있다
    heads: dict[int, fact_repo.HeadInfo] = {}
    if state.entity_problem is None:
        heads = await fact_repo.classify_head(
            db, store_id, {p.fact.fact_id: p.fact.fact_revision_id for p in state.pinned},
            state.entity_id,
        )
    view = build_facts_view(state, rows, heads)
    view.review_items = [*await load_review_items(db, store_id, [p.fact.fact_id for p in state.pinned]),
                         *write_items(view)]
    return view


@router.post("/{card_id}/review-items/write", response_model=FactEditResult)
async def write_review_value(
    card_id: int, req: ReviewWriteRequest, db: Db, claims: OwnerClaims
) -> FactEditResult:
    """검수 그 자리 입력칸(2026-11-08). 근거 없는 사실 한 줄을 사장님 글로 고친다. 나머지 줄은 그대로다."""
    user_id, store_id, _ = _identity(claims, owner_only=True)
    try:
        async with db.transaction():
            view = await get_card_facts(card_id, db, claims)
            target = next((f for b in view.blocks for f in b.facts if f.fact_revision_id == req.fact_revision_id), None)
            if target is None:
                raise ApiError(404, "FACT_NOT_FOUND", "고칠 줄을 찾을 수 없어요. 화면을 새로 고쳐 주세요.")
            blocks = []
            for b in view.blocks:
                if b.kind == "RAW":
                    continue
                items = []
                for f in b.facts:
                    if f.fact_revision_id != req.fact_revision_id:
                        items.append(EditKeep(op="KEEP", fact_revision_id=f.fact_revision_id))
                        continue
                    fields = FactFields(sentence=req.text.strip(), polarity=f.polarity, value=f.value, unit=f.unit,
                                        conditions=f.conditions, exceptions=f.exceptions, step_order=f.step_order,
                                        variant=f.variant, predicate=f.predicate)
                    items.append(EditModify(op="MODIFY", fact_revision_id=f.fact_revision_id, fact=fields))
                if items:
                    blocks.append(EditBlock(kind=b.kind, items=items))
            edit = FactEditRequest(expected_version_id=req.expected_version_id,
                                   idempotency_key=req.idempotency_key, blocks=blocks)
            return await fact_edit.save_fact_edit(db, store_id, card_id=card_id, actor_id=user_id, req=edit)
    except EditError as e:
        raise ApiError(
            e.status, e.code, fact_edit.message_for(e.code), details=e.details or None
        ) from None


# 수정 되돌리기는 이 시간 안에만(화면은 5초 알림의 '되돌리기' 글자만 둔다)
_REVERT_WINDOW = timedelta(minutes=10)


async def _facts_view_at(db, store_id: int, card_id: int, version_id: int) -> CardFactsView:
    """카드의 특정 판(수정 전 판) 사실 보기."""
    state = await fact_repo.load_card_fact_state(db, store_id, card_id, version_id)
    if state is None:
        raise ApiError(409, "REVERT_NOT_POSSIBLE", "이 수정은 되돌릴 수 없어요.")
    rows = await fact_repo.load_fact_rows(db, store_id, state)
    return build_facts_view(state, rows, {})


@router.post("/{card_id}/facts/edits/{edit_id}/revert", response_model=FactEditResult)
async def revert_fact_edit(
    card_id: int, edit_id: int, req: RevertRequest, db: Db, claims: OwnerClaims
) -> FactEditResult:
    """수정 되돌리기(계획 7 Task 7). 가장 최근 수정만, 그사이 카드가 바뀌지 않았을 때만 직전 판 내용으로 새 판을 만든다."""
    user_id, store_id, _ = _identity(claims, owner_only=True)
    edit = await db.fetchrow(
        "select from_version_id, to_version_id, created_at from card_fact_edits "
        "where store_id = $1 and card_id = $2 and edit_id = $3", store_id, card_id, edit_id)
    if edit is None or edit["to_version_id"] is None:
        raise ApiError(404, "EDIT_NOT_FOUND", "되돌릴 수정을 찾을 수 없어요.")
    draft = await db.fetchval(
        "select draft_version_id from knowledge_cards where store_id = $1 and card_id = $2", store_id, card_id)
    if draft != edit["to_version_id"]:
        raise ApiError(409, "REVERT_STALE", "그사이 카드가 바뀌어 되돌릴 수 없어요.")
    if datetime.now(timezone.utc) - edit["created_at"] > _REVERT_WINDOW:
        raise ApiError(409, "REVERT_EXPIRED", "시간이 지나 되돌릴 수 없어요. 직접 고쳐 주세요.")
    try:
        async with db.transaction():
            old = await _facts_view_at(db, store_id, card_id, int(edit["from_version_id"]))
            current = await get_card_facts(card_id, db, claims)
            plan = plan_revert(old, current, idempotency_key=req.idempotency_key)
            return await fact_edit.save_fact_edit(db, store_id, card_id=card_id, actor_id=user_id, req=plan)
    except EditError as e:
        raise ApiError(
            e.status, e.code, fact_edit.message_for(e.code), details=e.details or None
        ) from None


@router.post("/{card_id}/conflicts/{conflict_id}/choose", response_model=FactEditResult)
async def choose_review_value(
    card_id: int, conflict_id: int, req: ReviewChooseRequest, db: Db, claims: OwnerClaims
) -> FactEditResult:
    """검수 고르기(계획 7 Task 6). 맞는 값을 남기고 고르지 않은 값은 '틀린 값'으로 기억해 카드에서 뺀다.

    빼기는 사실 편집 저장과 같은 경로라 새 초안 판이 생기고, 남은 충돌이 없으면 검수 필요가 풀린다.
    """
    user_id, store_id, _ = _identity(claims, owner_only=True)
    try:
        async with db.transaction():
            rejected = await fact_revisions.choose_conflict(
                db, store_id, conflict_id, keep_fact_id=req.keep_fact_id, actor_id=user_id)
            view = await get_card_facts(card_id, db, claims)
            gone = [f.fact_revision_id for b in view.blocks for f in b.facts if f.fact_id == rejected]
            blocks = [
                EditBlock(kind=b.kind, items=[EditKeep(op="KEEP", fact_revision_id=f.fact_revision_id)
                                              for f in b.facts if f.fact_id != rejected])
                for b in view.blocks if b.kind != "RAW"
            ]
            edit = FactEditRequest(
                expected_version_id=req.expected_version_id, idempotency_key=req.idempotency_key,
                blocks=[b for b in blocks if b.items], deleted_fact_revision_ids=gone)
            return await fact_edit.save_fact_edit(db, store_id, card_id=card_id, actor_id=user_id, req=edit)
    except LookupError:
        raise ApiError(404, "CONFLICT_NOT_FOUND", "고를 항목을 찾을 수 없습니다.") from None
    except ValueError:
        raise ApiError(409, "CONFLICT_ALREADY_DECIDED", "이미 정한 항목이에요. 화면을 새로 고쳐 주세요.") from None
    except EditError as e:
        raise ApiError(
            e.status, e.code, fact_edit.message_for(e.code), details=e.details or None
        ) from None


@router.post("/{card_id}/facts/parse", response_model=FactParseResponse)
async def parse_card_facts(
    card_id: int, req: FactParseRequest, db: Db, claims: OwnerClaims
) -> FactParseResponse:
    """점주가 쓴 문장을 사실 후보로 나눠 제안만 돌려준다(저장 없음). 트랜잭션을 열지 않는다."""
    from app.config import get_settings

    _, store_id, _ = _identity(claims, owner_only=True)
    settings = get_settings()
    max_chars = int(getattr(settings, "card_fact_parse_max_chars", 1000))
    if len(req.text) > max_chars:
        raise ApiError(
            422, "PARSE_TEXT_TOO_LONG", f"글은 {max_chars}자까지 분석할 수 있어요.",
            details={"max_chars": max_chars},
        )
    card = await repo.get_card(db, store_id, card_id)
    if card is None:
        raise ApiError(404, "CARD_NOT_FOUND", "카드를 찾을 수 없습니다.")
    if card["review_status"] == "EXCLUDED":
        raise ApiError(409, "CARD_EXCLUDED", "제외된 카드를 먼저 복원해 주세요.")
    not_fact = ApiError(409, "NOT_FACT_CARD", "사실 단위로 고칠 수 있는 카드가 아닙니다.")
    if card["draft_version_id"] is None:
        raise not_fact
    state = await fact_repo.load_card_fact_state(
        db, store_id, card_id, int(card["draft_version_id"])
    )
    if state is None:
        raise not_fact
    if state.entity_problem is not None:
        raise ApiError(
            409, "CARD_ENTITY_MOVED", "메뉴 정리가 바뀌어 이 카드에서 고칠 수 없어요.",
            details={"entity_problem": state.entity_problem},
        )
    if req.mode == "MODIFY" and not any(
        p.fact.fact_revision_id == req.base_fact_revision_id for p in state.pinned
    ):
        raise ApiError(422, "PARSE_BASE_INVALID", "고칠 사실이 이 카드에 없어요.")
    # 읽기는 끝났다. 모델 호출 동안 이 요청은 연결을 쥐지 않는다
    return await fact_parse.parse_card_text(
        get_pool(), store_id=store_id, card_id=card_id, state=state, req=req
    )


@router.put("/{card_id}/facts", response_model=FactEditResult)
async def save_card_facts(
    card_id: int, req: FactEditRequest, db: Db, claims: OwnerClaims
) -> FactEditResult:
    """사실 편집 저장 → 새 초안 판. 공개판은 재승인 전까지 그대로다. 모델을 부르지 않는다."""
    user_id, store_id, _ = _identity(claims, owner_only=True)
    try:
        async with db.transaction():
            return await fact_edit.save_fact_edit(
                db, store_id, card_id=card_id, actor_id=user_id, req=req
            )
    except EditError as e:
        raise ApiError(
            e.status, e.code, fact_edit.message_for(e.code), details=e.details or None
        ) from None


def _bulk_error(error: ApiError) -> dict[str, str]:
    return {"code": error.code, "message": error.message}


@router.post("/bulk", response_model=BulkResult)
async def bulk_cards(req: BulkRequest, db: Db, claims: OwnerClaims) -> BulkResult:
    """카드 여러 장을 한 번에(계획 7 Task 4). 카드마다 성공·실패를 돌려준다.

    공개는 한 번에 한 판으로 올리고, 실패하면 그때만 한 장씩 올려 어느 카드가 문제인지 가린다.
    빼기·미공개·되돌리기·이동은 카드마다 기존 동작을 그대로 쓰고, 공개 판은 마지막에 한 번만 다시 올린다.
    """
    user_id, store_id, _ = _identity(claims, owner_only=True)
    ids = list(dict.fromkeys(req.card_ids))
    if req.action == "approve":
        return await _bulk_approve(db, claims, store_id, user_id, ids)

    single = {"unpublish": unpublish_card, "exclude": exclude_card, "restore": restore_card}
    results: list[BulkItem] = []
    deferred: list[tuple[int, int]] = []
    token = _DEFERRED_REPUBLISH.set(deferred)
    try:
        for card_id in ids:
            try:
                if req.action == "move":
                    row = await db.fetchrow(
                        "select updated_at from knowledge_cards where store_id = $1 and card_id = $2", store_id, card_id)
                    if row is None:
                        raise ApiError(404, "CARD_NOT_FOUND", "카드를 찾을 수 없습니다.")
                    done = await update_category(card_id, CategoryUpdateRequest(
                        category_id=req.category_id, expected_updated_at=row["updated_at"]), db, claims)
                else:
                    done = await single[req.action](card_id, db, claims)
                results.append(BulkItem(card_id=card_id, ok=True, review_status=done.review_status))
            except ApiError as error:
                results.append(BulkItem(card_id=card_id, ok=False, error=_bulk_error(error)))
    finally:
        _DEFERRED_REPUBLISH.reset(token)
    if deferred:
        first_card, first_event = deferred[0]
        await _republish_after_status_change(
            db, store_id=store_id, user_id=user_id, card_id=first_card,
            kind=f"bulk-{req.action}", event_id=first_event)
    return BulkResult(results=results)


async def _bulk_approve(db, claims, store_id: int, user_id: int, ids: list[int]) -> BulkResult:
    rows = {int(r["card_id"]): r for r in await db.fetch(
        "select card_id, draft_version_id, review_status from knowledge_cards "
        "where store_id = $1 and card_id = any($2::bigint[])", store_id, ids)}
    results: dict[int, BulkItem] = {}
    ready: list[int] = []
    for card_id in ids:
        row = rows.get(card_id)
        if row is None:
            results[card_id] = BulkItem(card_id=card_id, ok=False, error={"code": "CARD_NOT_FOUND", "message": "카드를 찾을 수 없습니다."})
        elif row["review_status"] == "EXCLUDED":
            results[card_id] = BulkItem(card_id=card_id, ok=False, error={"code": "CARD_EXCLUDED", "message": "제외된 카드를 먼저 복원해 주세요."})
        elif row["draft_version_id"] is None:
            results[card_id] = BulkItem(card_id=card_id, ok=False, error={"code": "CARD_DRAFT_MISSING", "message": "승인할 초안이 없습니다."})
        else:
            ready.append(card_id)
    if ready:
        member_id = await db.fetchval(
            "select member_id from store_members where store_id = $1 and user_id = $2 and member_role = 'OWNER'",
            store_id, user_id)
        if member_id is None:
            raise ApiError(403, "OWNER_ONLY", "카드는 사장님만 검수할 수 있습니다.")
        changes = [CardChange(card_id=card_id, expected_draft_version_id=rows[card_id]["draft_version_id"],
                              target_card_version_id=rows[card_id]["draft_version_id"]) for card_id in ready]
        digest = hashlib.sha1(",".join(f"{c.card_id}:{c.target_card_version_id}" for c in changes).encode()).hexdigest()[:24]
        result = await publish_cards(
            get_pool(), store_id=store_id, member_id=int(member_id), actor_user_id=user_id,
            changes=changes, idempotency_key=f"bulk-approve:{digest}",
            usage_context=await card_usage_context(db, store_id, ready[0]))
        if result.status in ("PUBLISHED", "ALREADY_APPLIED"):
            for card_id in ready:
                results[card_id] = BulkItem(card_id=card_id, ok=True, review_status="APPROVED")
        else:
            # 한 장이라도 막히면 판 전체가 롤백된다. 한 장씩 올려 어느 카드인지 가린다
            for card_id in ready:
                try:
                    done = await approve_card(card_id, db, claims)
                    results[card_id] = BulkItem(card_id=card_id, ok=True, review_status=done.review_status)
                except ApiError as error:
                    results[card_id] = BulkItem(card_id=card_id, ok=False, error=_bulk_error(error))
    return BulkResult(results=[results[card_id] for card_id in ids])
