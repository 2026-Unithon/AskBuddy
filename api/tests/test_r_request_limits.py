"""단위 검증은 상태 분기만 확인한다. DB 원자성은 verify_r_security.py에서 확인한다."""
import unittest
from contextlib import asynccontextmanager
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch
from app.learn.request_limits import request_lease
from app.errors import ApiError


class LimitTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.db = NS(execute=AsyncMock(), fetchrow=AsyncMock(return_value=dict(
            store_count=0,member_count=0,store_active=0,member_active=0)))
        self.active=0
        @asynccontextmanager
        async def acquire():
            self.active+=1
            try:
                yield self.db
            finally:
                self.active-=1
        @asynccontextmanager
        async def transaction():
            yield
        self.db.transaction=transaction
        self.pool=NS(acquire=acquire)
    async def test_connection_released_while_work_runs_and_after_error(self):
        with self.assertRaisesRegex(RuntimeError,"work failed"):
            async with request_lease(self.pool,1,2):
                self.assertEqual(self.active,0)
                raise RuntimeError("work failed")
        self.assertEqual(self.active,0)
        self.assertIn('finished_at',self.db.execute.call_args.args[0])
    async def test_each_limit_rejects_without_work(self):
        for key,value in (("store_count",120),("member_count",20),("store_active",8),("member_active",2)):
            counts=dict(store_count=0,member_count=0,store_active=0,member_active=0)
            counts[key]=value
            self.db.fetchrow.return_value=counts
            with self.subTest(key=key),self.assertRaises(ApiError) as caught:
                async with request_lease(self.pool,1,2):
                    self.fail("blocked request ran")
            self.assertEqual(caught.exception.status_code,429)
    async def test_release_error_does_not_retry_work(self):
        entered=0
        async with request_lease(self.pool,1,2):
            entered+=1
            self.db.execute.side_effect=RuntimeError("cleanup unavailable")
        self.assertEqual(entered,1)
        self.assertEqual(self.active,0)
