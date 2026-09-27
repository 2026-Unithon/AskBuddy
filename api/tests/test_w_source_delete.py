"""자료 삭제(D20) 라우트와 근거 표시 — 실제 SQL 은 verify_w_publication_flow 14 가 본다."""
from __future__ import annotations

import unittest
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from app.cards.router import _evidence_items, _source
from app.errors import ApiError
from app.ingest.router import create_ingest_job, delete_ingest_source
from app.ingest.schemas import CreateIngestJobRequest

STORE = 5
OWNER = {"user_id": 1, "store_id": STORE, "role": "OWNER"}
DELETED_AT = datetime(2026, 9, 27, tzinfo=timezone.utc)


class FakeDb:
    def __init__(self, *, source_exists=True):
        self.source_exists = source_exists
        self.queries: list[str] = []

    @asynccontextmanager
    async def transaction(self):
        yield

    async def fetchrow(self, query, *args):
        self.queries.append(query)
        assert args[0] == STORE, "store_id 가 첫 인자여야 한다"
        return {"source_id": args[1]} if self.source_exists else None

    async def fetchval(self, query, *args):
        self.queries.append(query)
        assert args[0] == STORE
        return DELETED_AT


class DeleteSourceRouteTest(unittest.IsolatedAsyncioTestCase):
    async def test_owner_deletes_as_tombstone(self):
        db = FakeDb()
        with patch("app.ingest.router.job_repo.source_in_progress", AsyncMock(return_value=False)), \
                patch("app.ingest.router.delete_source",
                      AsyncMock(return_value="DELETED")) as tombstone:
            result = await delete_ingest_source(9, db, OWNER)
        tombstone.assert_awaited_once_with(db, store_id=STORE, source_id=9)
        self.assertEqual((result.source_id, result.source_availability, result.already_deleted),
                         (9, "DELETED", False))
        # 카드·사실·공개판을 건드리는 쿼리가 없다
        self.assertFalse(any("knowledge_cards" in q or "source_facts" in q for q in db.queries))

    async def test_repeat_delete_reports_already_deleted(self):
        with patch("app.ingest.router.job_repo.source_in_progress", AsyncMock(return_value=False)), \
                patch("app.ingest.router.delete_source", AsyncMock(return_value="ALREADY_DELETED")):
            result = await delete_ingest_source(9, FakeDb(), OWNER)
        self.assertTrue(result.already_deleted)

    async def test_staff_cannot_delete(self):
        with self.assertRaises(ApiError) as raised:
            await delete_ingest_source(9, FakeDb(), {**OWNER, "role": "STAFF"})
        self.assertEqual(raised.exception.status_code, 403)

    async def test_other_store_source_is_not_found(self):
        with patch("app.ingest.router.delete_source", AsyncMock()) as tombstone, \
                self.assertRaises(ApiError) as raised:
            await delete_ingest_source(9, FakeDb(source_exists=False), OWNER)
        self.assertEqual(raised.exception.status_code, 404)
        tombstone.assert_not_awaited()

    async def test_source_in_progress_is_rejected(self):
        with patch("app.ingest.router.job_repo.source_in_progress", AsyncMock(return_value=True)), \
                patch("app.ingest.router.delete_source", AsyncMock()) as tombstone, \
                self.assertRaises(ApiError) as raised:
            await delete_ingest_source(9, FakeDb(), OWNER)
        self.assertEqual((raised.exception.status_code, raised.exception.code),
                         (409, "SOURCE_IN_PROGRESS"))
        tombstone.assert_not_awaited()

    async def test_new_job_rejects_deleted_source(self):
        rows = [{"source_id": 9, "status": "FAILED", "source_availability": "DELETED"}]
        with patch("app.ingest.router.job_repo.source_rows", AsyncMock(return_value=rows)), \
                patch("app.ingest.router.job_repo.create_job", AsyncMock()) as create, \
                self.assertRaises(ApiError) as raised:
            await create_ingest_job(CreateIngestJobRequest(source_ids=[9]), AsyncMock(),
                                    FakeDb(), OWNER, None)
        self.assertEqual(raised.exception.code, "SOURCE_DELETED")
        create.assert_not_awaited()


class EvidenceAvailabilityTest(unittest.IsolatedAsyncioTestCase):
    def _row(self, availability):
        return {"evidence_id": 1, "locator_type": "PAGE", "locator": {"page": 1},
                "excerpt": "원문", "source_id": 9, "source_title": "자료",
                "source_type": "SCAN", "file_url": "store/scan/x.pdf",
                "source_availability": availability}

    async def test_deleted_source_gets_no_read_url(self):
        with patch("app.cards.router.repo.list_evidence",
                   AsyncMock(return_value=[self._row("DELETED")])), \
                patch("app.cards.router.create_signed_read_url", AsyncMock()) as sign:
            [item] = await _evidence_items(object(), STORE, 70)
        sign.assert_not_awaited()
        self.assertIsNone(item.source.read_url)
        self.assertEqual(item.source.source_availability, "DELETED")

    async def test_available_source_is_signed(self):
        with patch("app.cards.router.repo.list_evidence",
                   AsyncMock(return_value=[self._row("AVAILABLE")])), \
                patch("app.cards.router.create_signed_read_url",
                      AsyncMock(return_value="https://signed")):
            [item] = await _evidence_items(object(), STORE, 70)
        self.assertEqual((item.source.read_url, item.source.source_availability),
                         ("https://signed", "AVAILABLE"))

    def test_card_source_defaults_available_for_legacy_rows(self):
        row = {"source_id": 9, "source_title": "자료", "source_type": "SCAN"}
        self.assertEqual(_source(row).source_availability, "AVAILABLE")
