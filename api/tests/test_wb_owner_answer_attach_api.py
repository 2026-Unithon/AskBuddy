# api/tests/test_wb_owner_answer_attach_api.py
"""Phase B B-D1 — 점주 답변 첨부 API. 같은 첨부 두 번 → 작업 하나(Review Focus 5)."""
from __future__ import annotations

import unittest
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

from app.errors import ApiError
from app.ingest.router import attach_owner_answer_file
from app.ingest.schemas import AttachOwnerAnswerRequest

STORE = 5
OWNER = {"user_id": 1, "store_id": STORE, "role": "OWNER"}
R = "app.ingest.router"


class FakeDb:
    def __init__(self, *, question=True, source_type="SCAN", answer_status=None):
        self.question, self.source_type, self.answer_status = question, source_type, answer_status

    @asynccontextmanager
    async def transaction(self):
        yield

    async def fetchval(self, sql, *args):
        assert args[0] == STORE, "store_id 가 첫 인자여야 한다"
        if "owner_answer_sources" in sql:
            return self.answer_status
        if "from pending_questions" in sql:
            return args[1] if self.question else None
        if "from sources" in sql:
            return self.source_type
        if "category_version" in sql:
            return 4
        raise AssertionError(sql)

    async def execute(self, sql, *args):
        # 보충 작업 키 잠금만 쓴다(/jobs 라우트와 같은 방식)
        assert "pg_advisory_xact_lock" in sql, sql


class Background:
    def __init__(self):
        self.tasks = []

    def add_task(self, fn, *args):
        self.tasks.append((fn.__name__, args))


class AttachApiTests(unittest.IsolatedAsyncioTestCase):
    async def _call(self, db, *, created=True, claims=OWNER, existing_job=None,
                    source_status="UPLOADED", availability="AVAILABLE", in_progress=False):
        bg = Background()
        row = {"source_id": 9, "status": source_status, "source_availability": availability}
        with patch(f"{R}.intake_records.attach", AsyncMock(return_value=created)) as attach, \
             patch(f"{R}.job_repo.find_by_idempotency",
                   AsyncMock(return_value=existing_job)) as find, \
             patch(f"{R}.job_repo.source_rows", AsyncMock(return_value=[row])), \
             patch(f"{R}.job_repo.source_in_progress", AsyncMock(return_value=in_progress)), \
             patch(f"{R}.job_repo.create_job",
                   AsyncMock(return_value={"job_id": 55, "status": "QUEUED"})) as create:
            out = await attach_owner_answer_file(42, AttachOwnerAnswerRequest(source_id=9), bg,
                                                 db, claims)
        return out, bg, attach, find, create

    async def test_before_answer_only_attaches(self):
        out, bg, attach, _, create = await self._call(FakeDb())
        self.assertEqual((out.question_id, out.source_id, out.created, out.job_id), (42, 9, True, None))
        attach.assert_awaited_once()
        self.assertEqual(attach.await_args.args[1], STORE)
        self.assertEqual(attach.await_args.kwargs, {"pending_question_id": 42, "source_id": 9})
        create.assert_not_awaited()
        self.assertEqual(bg.tasks, [])

    async def test_same_attachment_twice_makes_no_second_job(self):
        out, bg, _, _, create = await self._call(FakeDb(answer_status="DONE"), created=False)
        self.assertEqual((out.created, out.job_id), (False, None))
        create.assert_not_awaited()
        self.assertEqual(bg.tasks, [])

    async def test_after_answer_processed_starts_supplement_job(self):
        out, bg, _, find, create = await self._call(FakeDb(answer_status="DONE"))
        self.assertEqual(out.job_id, 55)
        self.assertEqual(find.await_args.args[1:], (STORE, "owner-answer-attach:9"))
        kw = create.await_args.kwargs
        self.assertEqual((kw["source_ids"], kw["idempotency_key"], kw["category_version"]),
                         ([9], "owner-answer-attach:9", 4))
        self.assertEqual(bg.tasks, [("process_ingest_job", (STORE, 55))])

    # ── 보충 작업 가드 (최종 리뷰 I2) — /ingest/jobs 와 같은 조건 ──────────────

    async def _assert_no_supplement(self, **kw):
        out, bg, _, _, create = await self._call(FakeDb(answer_status="DONE"), **kw)
        self.assertEqual((out.created, out.job_id), (True, None))
        create.assert_not_awaited()
        self.assertEqual(bg.tasks, [])

    async def test_done_source_gets_no_supplement_job(self):
        # 중복 업로드로 돌아온 이미 처리된 자료 — 다시 추출하지 않는다
        await self._assert_no_supplement(source_status="DONE")

    async def test_processing_source_gets_no_supplement_job(self):
        await self._assert_no_supplement(source_status="PROCESSING")

    async def test_deleted_source_gets_no_supplement_job(self):
        await self._assert_no_supplement(source_status="FAILED", availability="DELETED")

    async def test_source_in_active_job_gets_no_supplement_job(self):
        # 답변 작업이 이미 이 첨부를 대기열에 넣었다 — 두 작업이 같은 자료를 돌리지 않는다
        await self._assert_no_supplement(in_progress=True)

    async def test_failed_source_gets_supplement_job(self):
        out, bg, _, _, create = await self._call(FakeDb(answer_status="DONE"),
                                                 source_status="FAILED")
        self.assertEqual(out.job_id, 55)
        create.assert_awaited_once()

    async def test_answer_still_processing_only_attaches(self):
        out, bg, _, _, create = await self._call(FakeDb(answer_status="PROCESSING"))
        self.assertIsNone(out.job_id)
        create.assert_not_awaited()

    async def test_existing_supplement_job_is_reused(self):
        out, bg, _, _, create = await self._call(
            FakeDb(answer_status="DONE"), existing_job={"job_id": 31, "status": "SUCCEEDED"})
        self.assertEqual(out.job_id, 31)
        create.assert_not_awaited()
        self.assertEqual(bg.tasks, [])  # QUEUED 가 아니면 다시 시작하지 않는다

    async def test_other_store_question_is_404(self):
        with self.assertRaises(ApiError) as e:
            await self._call(FakeDb(question=False))
        self.assertEqual((e.exception.status_code, e.exception.code), (404, "QUESTION_NOT_FOUND"))

    async def test_missing_source_is_404(self):
        with self.assertRaises(ApiError) as e:
            await self._call(FakeDb(source_type=None))
        self.assertEqual((e.exception.status_code, e.exception.code), (404, "SOURCE_NOT_FOUND"))

    async def test_owner_text_source_is_422(self):
        with self.assertRaises(ApiError) as e:
            await self._call(FakeDb(source_type="OWNER_TEXT"))
        self.assertEqual((e.exception.status_code, e.exception.code), (422, "INVALID_ATTACHMENT"))

    async def test_staff_is_403(self):
        with self.assertRaises(ApiError) as e:
            await self._call(FakeDb(), claims={**OWNER, "role": "STAFF"})
        self.assertEqual(e.exception.status_code, 403)
