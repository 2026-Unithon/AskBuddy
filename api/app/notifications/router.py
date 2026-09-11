"""앱 내부 알림 목록과 브라우저 Push 구독 API."""
from __future__ import annotations

import re
from urllib.parse import urlparse

from fastapi import APIRouter, Header, Query, Response
from pydantic import BaseModel, Field

from app.config import get_settings
from app.deps import Claims, CurrentStoreId, CurrentUserId, Db
from app.errors import ApiError
from app.notifications.service import push_is_configured

router = APIRouter()
_KEY_RE = re.compile(r"^[A-Za-z0-9_-]+={0,2}$")


class SubscriptionKeys(BaseModel):
    p256dh: str = Field(min_length=20, max_length=500)
    auth: str = Field(min_length=8, max_length=200)


class SubscriptionRequest(BaseModel):
    endpoint: str = Field(min_length=10, max_length=2000)
    keys: SubscriptionKeys


def _validate_subscription(req: SubscriptionRequest) -> None:
    endpoint = urlparse(req.endpoint)
    if endpoint.scheme != "https" or not endpoint.netloc:
        raise ApiError(422, "INVALID_PUSH_ENDPOINT", "Push 구독 주소를 확인해 주세요.")
    if not _KEY_RE.fullmatch(req.keys.p256dh) or not _KEY_RE.fullmatch(req.keys.auth):
        raise ApiError(422, "INVALID_PUSH_KEYS", "Push 구독 키를 확인해 주세요.")


def _require_owner(claims: dict) -> None:
    if claims.get("role") != "OWNER":
        raise ApiError(403, "OWNER_ONLY", "알림 설정은 사장님만 사용할 수 있습니다.")


@router.get("/support")
async def support(
    db: Db,
    claims: Claims,
    store_id: CurrentStoreId,
    user_id: CurrentUserId,
) -> dict:
    _require_owner(claims)
    settings = get_settings()
    seen_at = await db.fetchval(
        """
        select push_guide_seen_at from owner_ui_state
        where store_id = $1 and user_id = $2
        """,
        store_id,
        user_id,
    )
    return {
        "push_configured": push_is_configured(),
        "vapid_public_key": settings.vapid_public_key or None,
        "guide_version": settings.push_guide_version,
        "guide_seen": seen_at is not None,
    }


@router.post("/subscriptions", status_code=201)
async def save_subscription(
    req: SubscriptionRequest,
    db: Db,
    claims: Claims,
    store_id: CurrentStoreId,
    user_id: CurrentUserId,
    user_agent: str | None = Header(default=None, alias="User-Agent"),
) -> dict:
    _require_owner(claims)
    _validate_subscription(req)
    async with db.transaction():
        belongs = await db.fetchval(
            """
            select exists(
              select 1 from store_members where store_id = $1 and user_id = $2
            )
            """,
            store_id,
            user_id,
        )
        if not belongs:
            raise ApiError(403, "STORE_ACCESS_DENIED", "이 매장에 접근할 수 없습니다.")
        subscription_id = await db.fetchval(
            """
            insert into push_subscriptions (
              user_id, endpoint, p256dh, auth, user_agent, enabled
            ) values ($1,$2,$3,$4,$5,true)
            on conflict (user_id, endpoint) do update
            set p256dh = excluded.p256dh, auth = excluded.auth,
                user_agent = excluded.user_agent, enabled = true, updated_at = now()
            returning subscription_id
            """,
            user_id,
            req.endpoint,
            req.keys.p256dh,
            req.keys.auth,
            (user_agent or "")[:500] or None,
        )
        await db.execute(
            """
            insert into owner_ui_state (user_id, store_id, push_guide_seen_at)
            values ($1,$2,now())
            on conflict (user_id, store_id) do update
            set push_guide_seen_at = coalesce(owner_ui_state.push_guide_seen_at, now()),
                updated_at = now()
            """,
            user_id,
            store_id,
        )
    return {"subscription_id": int(subscription_id), "enabled": True}


@router.delete("/subscriptions/{subscription_id}", status_code=204)
async def delete_subscription(
    subscription_id: int,
    db: Db,
    claims: Claims,
    user_id: CurrentUserId,
) -> Response:
    _require_owner(claims)
    result = await db.execute(
        """
        update push_subscriptions set enabled = false, updated_at = now()
        where subscription_id = $1 and user_id = $2
        """,
        subscription_id,
        user_id,
    )
    if result == "UPDATE 0":
        raise ApiError(404, "PUSH_SUBSCRIPTION_NOT_FOUND", "Push 구독을 찾을 수 없습니다.")
    return Response(status_code=204)


@router.get("")
async def list_notifications(
    db: Db,
    claims: Claims,
    store_id: CurrentStoreId,
    user_id: CurrentUserId,
    unread_only: bool = Query(default=False),
    cursor: int | None = Query(default=None, ge=1),
    limit: int = Query(default=30, ge=1, le=100),
) -> dict:
    _require_owner(claims)
    rows = await db.fetch(
        """
        select n.notification_id, n.event_type, n.aggregate_type, n.aggregate_id,
               n.title, n.body, n.destination, n.status, n.read_at, n.created_at,
               case
                 when n.aggregate_type = 'PENDING_QUESTION' then coalesce((
                   select q.status = 'ANSWERED' from pending_questions q
                   where q.store_id = n.store_id and q.question_id = n.aggregate_id
                 ), true)
                 when n.aggregate_type = 'INGEST_JOB' then not exists (
                   select 1 from knowledge_cards c
                   where c.store_id = n.store_id and c.origin_job_id = n.aggregate_id
                     and c.review_status = 'PENDING'
                 )
                 else false
               end as action_completed
        from notification_events n
        where n.store_id = $1 and n.recipient_user_id = $2
          and ($3::boolean = false or n.read_at is null)
          and ($4::bigint is null or n.notification_id < $4)
        order by n.notification_id desc
        limit $5
        """,
        store_id,
        user_id,
        unread_only,
        cursor,
        limit + 1,
    )
    has_more = len(rows) > limit
    rows = rows[:limit]
    unread_count = int(
        await db.fetchval(
            """
            select count(*) from notification_events
            where store_id = $1 and recipient_user_id = $2 and read_at is null
            """,
            store_id,
            user_id,
        )
    )
    return {
        "items": [
            {
                "notification_id": int(row["notification_id"]),
                "event_type": row["event_type"],
                "aggregate_type": row["aggregate_type"],
                "aggregate_id": int(row["aggregate_id"]),
                "title": row["title"],
                "body": row["body"],
                "destination": row["destination"],
                "delivery_status": row["status"],
                "read_at": row["read_at"].isoformat() if row["read_at"] else None,
                "action_completed": bool(row["action_completed"]),
                "created_at": row["created_at"].isoformat(),
            }
            for row in rows
        ],
        "unread_count": unread_count,
        "next_cursor": int(rows[-1]["notification_id"]) if has_more else None,
    }


@router.post("/{notification_id}/read")
async def mark_notification_read(
    notification_id: int,
    db: Db,
    claims: Claims,
    store_id: CurrentStoreId,
    user_id: CurrentUserId,
) -> dict:
    _require_owner(claims)
    read_at = await db.fetchval(
        """
        update notification_events set read_at = coalesce(read_at, now())
        where store_id = $1 and notification_id = $2 and recipient_user_id = $3
        returning read_at
        """,
        store_id,
        notification_id,
        user_id,
    )
    if read_at is None:
        raise ApiError(404, "NOTIFICATION_NOT_FOUND", "알림을 찾을 수 없습니다.")
    return {"notification_id": notification_id, "read_at": read_at.isoformat()}
