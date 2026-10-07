"""일시 장애는 해당 작업만 재시도하고, 자료/모델 병렬도는 프로세스 전체에서 묶는다."""
import asyncio
import logging
import random
from functools import wraps
from weakref import WeakKeyDictionary

import asyncpg

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)
_gates = WeakKeyDictionary()


def setting(name: str):
    return getattr(get_settings(), name, Settings.model_fields[name].default)


def gate(name: str, limit: int) -> asyncio.Semaphore:
    # 테스트/CLI의 서로 다른 event loop에 semaphore를 공유하지 않는다.
    gates = _gates.setdefault(asyncio.get_running_loop(), {})
    return gates.setdefault((name, limit), asyncio.Semaphore(limit))


def limited(setting_name: str):
    def decorate(fn):
        @wraps(fn)
        async def wrapped(*args, **kwargs):
            async with gate(setting_name, setting(setting_name)):
                return await fn(*args, **kwargs)
        return wrapped
    return decorate


def transient(exc: Exception) -> bool:
    if isinstance(exc, (TimeoutError, ConnectionError, asyncpg.PostgresConnectionError,
                        asyncpg.TooManyConnectionsError, asyncpg.SerializationError,
                        asyncpg.DeadlockDetectedError)):
        return True
    status = getattr(exc, 'status_code', None) or getattr(exc, 'code', None)
    if isinstance(status, int) and (status in (408, 429) or 500 <= status <= 599):
        return True
    # SDK 연결 예외에는 HTTP 상태가 없기도 한다.
    if type(exc).__name__ in ('APIConnectionError', 'APITimeoutError', 'ConnectTimeout',
                              'ReadTimeout', 'ConnectError', 'RemoteProtocolError'):
        return True
    return isinstance(exc.__cause__, Exception) and transient(exc.__cause__)


async def backoff(retry: int, *, stage: str, exc: Exception) -> None:
    delay = min(setting("ingest_retry_base_seconds") * 2 ** retry, 10.0)
    delay *= random.uniform(0.8, 1.2)
    logger.warning('단계 재시도 stage=%s retry=%d/%d type=%s wait=%.2fs',
                   stage, retry + 1, setting("ingest_stage_retries"), type(exc).__name__, delay)
    await asyncio.sleep(delay)


async def retry_io(operation, *, stage: str):
    """저장/조회만 반복한다. 유료 공급자 호출을 이 함수로 감싸지 않는다."""
    for retry in range(setting("ingest_stage_retries") + 1):
        try:
            return await operation()
        except Exception as exc:
            if not transient(exc) or retry == setting("ingest_stage_retries"):
                raise
            await backoff(retry, stage=stage, exc=exc)
