"""정리 취소와 멈춘 작업(2026-11-08 사용자 실화면). 실제 스키마. PLAN7_TEST_DB_URL 이 없으면 건너뛴다."""
import unittest

from tests._plan7_db import ENABLED, SKIP_REASON, drop_db, fresh_db, seed_store

from app.ingest import job_repository as job_repo
from app.ingest import job_worker


@unittest.skipUnless(ENABLED, SKIP_REASON)
class JobCancelTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.conn, self.name = await fresh_db()
        self.store = await seed_store(self.conn)

    async def asyncTearDown(self):
        await drop_db(self.conn, self.name)

    async def job(self, status="EXTRACTING", minutes_ago=0):
        job_id = await self.conn.fetchval(
            f"insert into ingest_jobs (store_id, created_by, status, category_version, prompt_version, updated_at) "
            f"values ($1, 1, $2, 1, 'test', now() - interval '{minutes_ago} minutes') returning job_id",
            self.store, status)
        source_id = await self.conn.fetchval(
            "insert into sources (store_id, uploaded_by, source_type) values ($1, 1, 'SCAN') returning source_id", self.store)
        await self.conn.execute(
            "insert into ingest_job_sources (store_id, job_id, source_id, status) values ($1, $2, $3, 'QUEUED')",
            self.store, job_id, source_id)
        return job_id

    async def status(self, job_id):
        return tuple(await self.conn.fetchrow("select status, error_code from ingest_jobs where job_id = $1", job_id))

    async def test_cancel_marks_job_and_sources(self):
        job_id = await self.job()
        self.assertTrue(await job_repo.cancel_job(self.conn, self.store, job_id))
        self.assertEqual(await self.status(job_id), ("FAILED", "JOB_CANCELED"))
        self.assertEqual(await self.conn.fetchval("select status from ingest_job_sources where job_id = $1", job_id), "FAILED")

    async def test_worker_refresh_does_not_overwrite_cancel(self):
        job_id = await self.job()
        await job_repo.cancel_job(self.conn, self.store, job_id)
        await job_worker._refresh_job(self.conn, self.store, job_id, final=True)
        self.assertEqual(await self.status(job_id), ("FAILED", "JOB_CANCELED"))

    async def test_cancel_only_active_and_own_store(self):
        done = await self.job(status="SUCCEEDED")
        self.assertFalse(await job_repo.cancel_job(self.conn, self.store, done))
        active = await self.job()
        self.assertFalse(await job_repo.cancel_job(self.conn, self.store + 999, active))

    async def test_stalled_jobs_fail_after_threshold(self):
        old = await self.job(minutes_ago=31)
        fresh = await self.job(minutes_ago=5)
        await job_repo.fail_stalled_jobs(self.conn, self.store, minutes=30)
        self.assertEqual(await self.status(old), ("FAILED", "JOB_STALLED"))
        self.assertEqual((await self.status(fresh))[0], "EXTRACTING")
