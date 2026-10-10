"""W3b — 점주 입력 자료(OWNER_TEXT, 파일 없음)를 읽는 기존 W 경로가 깨지거나 파일을 열려 하지 않는다."""
from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from app.cards.router import _evidence_items
from app.errors import ApiError
from app.ingest.router import create_ingest_job, process
from app.ingest.schemas import CreateIngestJobRequest, ProcessRequest

from tests.test_w_source_delete import OWNER, STORE, FakeDb

_OWNER_TEXT = {"source_id": 9, "store_id": STORE, "source_type": "OWNER_TEXT",
               "title": "카드 직접 입력 · 음료Z", "file_url": None, "content_hash": None,
               "status": "DONE", "error_message": None, "processed_at": None,
               "source_availability": "AVAILABLE"}


class OwnerTextSourceTest(unittest.IsolatedAsyncioTestCase):
    async def test_process_refuses_owner_text_even_with_force(self):
        background = MagicMock()
        with patch("app.ingest.router.repo.get_source", AsyncMock(return_value=_OWNER_TEXT)), \
                patch("app.ingest.router.repo.set_status", AsyncMock()) as set_status, \
                self.assertRaises(HTTPException) as raised:
            await process(ProcessRequest(source_id=9, force=True), background, FakeDb(), STORE)
        self.assertEqual(raised.exception.status_code, 409)
        set_status.assert_not_awaited()
        background.add_task.assert_not_called()

    async def test_new_job_refuses_owner_text_source(self):
        # /ingest/jobs 에는 OWNER_TEXT 전용 분기가 없다(source_rows 는 source_type 을 읽지 않는다).
        # 점주 입력 자료는 만들 때부터 DONE 이라 기존 SOURCE_NOT_READY(409) 로 거절된다
        rows = [{"source_id": 9, "status": "DONE", "source_availability": "AVAILABLE"}]
        with patch("app.ingest.router.job_repo.source_rows", AsyncMock(return_value=rows)), \
                patch("app.ingest.router.job_repo.create_job", AsyncMock()) as create, \
                self.assertRaises(ApiError) as raised:
            await create_ingest_job(CreateIngestJobRequest(source_ids=[9]), AsyncMock(),
                                    FakeDb(), OWNER, None)
        self.assertEqual(raised.exception.code, "SOURCE_NOT_READY")
        create.assert_not_awaited()

    async def test_card_evidence_of_owner_text_has_no_read_url(self):
        row = {"evidence_id": 1, "locator_type": "MESSAGE", "locator": {"line": 1},
               "excerpt": "ICE 물은 230ml", "source_id": 9, "source_title": _OWNER_TEXT["title"],
               "source_type": "OWNER_TEXT", "file_url": None, "source_availability": "AVAILABLE"}
        with patch("app.cards.router.repo.list_evidence", AsyncMock(return_value=[row])), \
                patch("app.cards.router.create_signed_read_url", AsyncMock()) as sign:
            [item] = await _evidence_items(object(), STORE, 70)
        sign.assert_not_awaited()
        self.assertIsNone(item.source.read_url)
        self.assertEqual((item.source.source_type, item.excerpt), ("OWNER_TEXT", "ICE 물은 230ml"))
