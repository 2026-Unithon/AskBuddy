from __future__ import annotations

import logging
import json
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query

from app.cards import fact_edit
from app.cards import fact_edit_repo as fact_repo
from app.cards import fact_parse
from app.cards import repository as repo
from app.cards.fact_edit_plan import CardFactState, EditError
from app.cards.fact_edit_schemas import (
    CardFactsView,
    FactBlockView,
    FactEditRequest,
    FactEditResult,
    FactOrigin,
    FactRequirement,
    FactParseRequest,
    FactParseResponse,
    FactRow,
    FactVariant,
)
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
    return CardCategory(category_id=int(row["category_id"]), name=row["category_name"] or "")


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
    fact_edit_enabled = False
    if role == "OWNER":
        from app.config import get_settings

        fact_card = await repo.has_block_facts(db, store_id, row["draft_version_id"])
        fact_edit_enabled = bool(
            getattr(get_settings(), "w_fact_card_edit_enabled", False)
        )
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
        fact_edit_enabled=fact_edit_enabled,
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
        # W3b — 사실 카드의 본문을 통째로 바꾸면 고정된 사실과 어긋난다. 사실 단위로만 고친다
        if await repo.has_block_facts(db, store_id, card["draft_version_id"]):
            raise ApiError(
                409, "FACT_CARD_TEXT_EDIT_BLOCKED", "사실 카드는 사실 단위로 고쳐 주세요."
            )
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
    *,
    flag_on: bool,
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
        editable=bool(
            flag_on and state.review_status != "EXCLUDED" and state.entity_problem is None
        ),
        entity_problem=state.entity_problem,  # type: ignore[arg-type]
        blocks=blocks,
    )


@router.get("/{card_id}/facts", response_model=CardFactsView)
async def get_card_facts(card_id: int, db: Db, claims: OwnerClaims) -> CardFactsView:
    """사실 카드의 초안 판을 사실 줄 단위로 돌려준다. 점주 전용, 트랜잭션 없이 읽는다."""
    from app.config import get_settings

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
    flag_on = bool(getattr(get_settings(), "w_fact_card_edit_enabled", False))
    return build_facts_view(state, rows, heads, flag_on=flag_on)


@router.post("/{card_id}/facts/parse", response_model=FactParseResponse)
async def parse_card_facts(
    card_id: int, req: FactParseRequest, db: Db, claims: OwnerClaims
) -> FactParseResponse:
    """점주가 쓴 문장을 사실 후보로 나눠 제안만 돌려준다(저장 없음). 트랜잭션을 열지 않는다."""
    from app.config import get_settings

    _, store_id, _ = _identity(claims, owner_only=True)
    settings = get_settings()
    if not getattr(settings, "w_fact_card_edit_enabled", False):
        raise ApiError(403, "FACT_EDIT_DISABLED", "사실 단위 고치기는 아직 열리지 않았어요.")
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
    from app.config import get_settings

    user_id, store_id, _ = _identity(claims, owner_only=True)
    if not getattr(get_settings(), "w_fact_card_edit_enabled", False):
        raise ApiError(403, "FACT_EDIT_DISABLED", "사실 단위 고치기는 아직 열리지 않았어요.")
    try:
        async with db.transaction():
            return await fact_edit.save_fact_edit(
                db, store_id, card_id=card_id, actor_id=user_id, req=req
            )
    except EditError as e:
        raise ApiError(
            e.status, e.code, fact_edit.message_for(e.code), details=e.details or None
        ) from None
