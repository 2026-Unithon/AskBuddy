"""짧은 쿼리는 즉시 연결 반환, 트랜잭션 안에서만 연결을 고정한다."""
from contextlib import asynccontextmanager


class ShortSession:
    def __init__(self, pool):
        self.pool = pool
        self.connection = None

    def __getattr__(self, name):
        return getattr(self.connection if self.connection is not None else self.pool, name)

    @asynccontextmanager
    async def transaction(self, **kwargs):
        if self.connection is not None:
            async with self.connection.transaction(**kwargs):
                yield
            return
        async with self.pool.acquire() as conn:
            self.connection = conn
            try:
                async with conn.transaction(**kwargs):
                    yield
            finally:
                self.connection = None
