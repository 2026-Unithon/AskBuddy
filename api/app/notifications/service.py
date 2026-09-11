"""알림 이벤트 생성과 Web Push 전달을 분리한다.

앱 내부 ``notification_events``가 정본이다. Push 실패는 원래 업무 트랜잭션을
실패시키지 않으며, 전송 요청 상태와 읽음/업무 처리 상태도 서로 섞지 않는다.
"""
from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from urllib.parse import urlparse

import asyncpg

from app.config import get_settings
from app.deps import get_pool

logger = logging.getLogger(__name__)


def push_is_configured() -> bool:
    settings = get_settings()
    subject = settings.vapid_subject
    parsed_subject = urlparse(subject)
    valid_subject = (
        subject.startswith("mailto:") and "@" in subject
    ) or (parsed_subject.scheme == "https" and bool(parsed_subject.netloc))
    return bool(
        settings.vapid_public_key
        and settings.vapid_private_key
        and valid_subject
    )


def aggregate_delivery_status(statuses: Sequence[str]) -> str:
    """한 기기라도 요청 성공이면 이벤트는 REQUESTED, 전부 실패면 FAILED다."""
    if any(status == "REQUESTED" for status in statuses):
        return "REQUESTED"
    if statuses and all(status == "FAILED" for status in statuses):
        return "FAILED"
    return "PENDING"


async def create_notification_event(
    db: asyncpg.Connection,
    *,
    store_id: int,
    recipient_user_id: int,
    event_type: str,
    aggregate_type: str,
    aggregate_id: int,
    dedupe_key: str,
    title: str,
    body: str,
    destination: str,
) -> int | None:
    """새 이벤트일 때만 id를 반환한다. 재시도는 알림과 Push를 중복 생성하지 않는다."""
    value = await db.fetchval(
        """
        insert into notification_events (
          store_id, recipient_user_id, event_type, aggregate_type,
          aggregate_id, dedupe_key, title, body, destination
        ) values ($1,$2,$3,$4,$5,$6,$7,$8,$9)
        on conflict (recipient_user_id, dedupe_key) do nothing
        returning notification_id
        """,
        store_id,
        recipient_user_id,
        event_type,
        aggregate_type,
        aggregate_id,
        dedupe_key,
        title[:200],
        body[:500],
        destination[:500],
    )
    return int(value) if value is not None else None


async def create_pending_question_notification(
    db: asyncpg.Connection,
    store_id: int,
    question_id: int,
    question_text: str,
) -> int | None:
    owner_id = await db.fetchval(
        "select owner_id from stores where store_id = $1", store_id
    )
    if owner_id is None:
        return None
    return await create_notification_event(
        db,
        store_id=store_id,
        recipient_user_id=int(owner_id),
        event_type="PENDING_QUESTION",
        aggregate_type="PENDING_QUESTION",
        aggregate_id=question_id,
        dedupe_key=f"pending-question:{store_id}:{question_id}",
        title="새 질문이 도착했어요",
        body=question_text,
        destination=f"/owner/questions?question_id={question_id}",
    )


async def create_ingest_completed_notification(
    db: asyncpg.Connection,
    store_id: int,
    job_id: int,
    card_count: int,
) -> int | None:
    owner_id = await db.fetchval(
        "select owner_id from stores where store_id = $1", store_id
    )
    if owner_id is None or card_count <= 0:
        return None
    return await create_notification_event(
        db,
        store_id=store_id,
        recipient_user_id=int(owner_id),
        event_type="INGEST_COMPLETED",
        aggregate_type="INGEST_JOB",
        aggregate_id=job_id,
        dedupe_key=f"ingest-completed:{store_id}:{job_id}",
        title="새 카드가 준비됐어요",
        body=f"검토할 업무 카드 {card_count}개가 준비됐습니다.",
        destination=f"/owner/cards/review?job_id={job_id}",
    )


def _failure_status(exc: Exception) -> int | None:
    response = getattr(exc, "response", None)
    if response is None:
        return None
    return getattr(response, "status_code", None) or getattr(response, "status", None)


async def deliver_notification(store_id: int, notification_id: int) -> None:
    """등록된 모든 기기로 보낸다. 오류는 기록하고 호출자에게 전파하지 않는다."""
    if not push_is_configured():
        return
    settings = get_settings()
    pool = get_pool()
    try:
        async with pool.acquire() as db:
            event = await db.fetchrow(
                """
                select notification_id, recipient_user_id, title, body, destination
                from notification_events
                where store_id = $1 and notification_id = $2
                """,
                store_id,
                notification_id,
            )
            if event is None:
                return
            subscriptions = await db.fetch(
                """
                select subscription_id, endpoint, p256dh, auth
                from push_subscriptions
                where user_id = $1 and enabled = true
                order by subscription_id
                """,
                int(event["recipient_user_id"]),
            )
            if not subscriptions:
                return

            from py_vapid import Vapid
            from pywebpush import WebPushException, webpush_async

            vapid_key = Vapid.from_string(settings.vapid_private_key)
            if settings.vapid_subject.startswith("https://"):
                # RFC 8292는 HTTPS 연락 URI를 허용하지만 py-vapid의 기본 검사는
                # mailto만 받으므로 표준 URI를 쓰는 경우 strict 검사를 해제한다.
                vapid_key.conf["no-strict"] = True

            payload = json.dumps(
                {
                    "notification_id": notification_id,
                    "title": event["title"],
                    "body": event["body"],
                    "destination": event["destination"],
                    "icon": "/images/buddy-hero.png",
                },
                ensure_ascii=False,
            )
            statuses: list[str] = []
            for subscription in subscriptions:
                subscription_id = int(subscription["subscription_id"])
                delivery = await db.fetchrow(
                    """
                    insert into notification_deliveries (
                      store_id, notification_id, subscription_id, attempt_count
                    ) values ($1,$2,$3,1)
                    on conflict (notification_id, subscription_id) do update
                    set attempt_count = notification_deliveries.attempt_count + 1,
                        status = case
                          when notification_deliveries.status = 'REQUESTED'
                            then 'REQUESTED'
                          else 'PENDING'
                        end,
                        provider_message = null, failed_at = null
                    returning delivery_id, status
                    """,
                    store_id,
                    notification_id,
                    subscription_id,
                )
                if delivery["status"] == "REQUESTED":
                    statuses.append("REQUESTED")
                    continue
                try:
                    response = await webpush_async(
                        subscription_info={
                            "endpoint": subscription["endpoint"],
                            "keys": {
                                "p256dh": subscription["p256dh"],
                                "auth": subscription["auth"],
                            },
                        },
                        data=payload,
                        vapid_private_key=vapid_key,
                        vapid_claims={"sub": settings.vapid_subject},
                        ttl=86400,
                        timeout=10,
                    )
                    provider_message = f"HTTP {getattr(response, 'status', 201)}"
                    status = "REQUESTED"
                    await db.execute(
                        """
                        update notification_deliveries
                        set status = 'REQUESTED', provider_message = $2,
                            requested_at = now(), failed_at = null
                        where delivery_id = $1
                        """,
                        int(delivery["delivery_id"]),
                        provider_message,
                    )
                    await db.execute(
                        """
                        update push_subscriptions
                        set last_success_at = now(), last_failure_at = null
                        where subscription_id = $1
                        """,
                        subscription_id,
                    )
                except WebPushException as exc:
                    status = "FAILED"
                    http_status = _failure_status(exc)
                    await db.execute(
                        """
                        update notification_deliveries
                        set status = 'FAILED', provider_message = $2,
                            failed_at = now()
                        where delivery_id = $1
                        """,
                        int(delivery["delivery_id"]),
                        str(exc)[:1000],
                    )
                    await db.execute(
                        """
                        update push_subscriptions
                        set enabled = case when $2 = any(array[404,410]) then false else enabled end,
                            last_failure_at = now()
                        where subscription_id = $1
                        """,
                        subscription_id,
                        http_status,
                    )
                    logger.warning(
                        "push failed notification=%s subscription=%s status=%s",
                        notification_id,
                        subscription_id,
                        http_status,
                    )
                except Exception as exc:
                    status = "FAILED"
                    await db.execute(
                        """
                        update notification_deliveries
                        set status = 'FAILED', provider_message = $2,
                            failed_at = now()
                        where delivery_id = $1
                        """,
                        int(delivery["delivery_id"]),
                        str(exc)[:1000],
                    )
                    await db.execute(
                        """
                        update push_subscriptions set last_failure_at = now()
                        where subscription_id = $1
                        """,
                        subscription_id,
                    )
                    logger.exception(
                        "push failed notification=%s subscription=%s",
                        notification_id,
                        subscription_id,
                    )
                statuses.append(status)

            event_status = aggregate_delivery_status(statuses)
            await db.execute(
                """
                update notification_events
                set status = $3::varchar,
                    requested_at = case when $3::varchar = 'REQUESTED' then now() else requested_at end
                where store_id = $1 and notification_id = $2
                """,
                store_id,
                notification_id,
                event_status,
            )
    except Exception:
        logger.exception(
            "notification delivery worker failed store=%s notification=%s",
            store_id,
            notification_id,
        )
