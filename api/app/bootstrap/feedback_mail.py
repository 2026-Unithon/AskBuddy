"""문의·의견이 저장되면 운영자에게 메일로 알린다(계획 9 Task 10, SES).

메일에는 글을 싣지 않는다(종류와 번호만). 글은 운영자가 DB 에서 본다.
설정이 비어 있으면 보내지 않는다. 보내다 실패해도 저장 응답과 무관하다(예외 종류만 로그).
"""
from __future__ import annotations

import asyncio
import logging

from app.config import get_settings

logger = logging.getLogger(__name__)
KIND_LABEL = {"INQUIRY": "문의", "IDEA": "의견"}


async def notify_feedback(*, feedback_id: int, kind: str, client=None) -> bool:
    settings = get_settings()
    if not (settings.feedback_mail_from and settings.feedback_mail_to and settings.aws_region):
        return False
    label = KIND_LABEL.get(kind, "의견")
    try:
        if client is None:
            import boto3  # 메일을 켤 때만 필요하다

            client = boto3.client("sesv2", region_name=settings.aws_region)
        # boto3 는 동기라 이벤트 루프를 막지 않게 스레드에서 보낸다
        await asyncio.to_thread(
            client.send_email,
            FromEmailAddress=settings.feedback_mail_from,
            Destination={"ToAddresses": [settings.feedback_mail_to]},
            Content={"Simple": {
                "Subject": {"Data": f"[AskBuddy] {label} #{feedback_id}", "Charset": "UTF-8"},
                "Body": {"Text": {"Data": f"새 {label}가 들어왔어요. 번호 {feedback_id}. 내용은 DB 의 user_feedback 에서 확인해요.", "Charset": "UTF-8"}},
            }},
        )
    except Exception as exc:  # noqa: BLE001 — 메일 실패가 저장을 되돌리지 않는다
        logger.warning("feedback mail failed type=%s", type(exc).__name__)
        return False
    return True
