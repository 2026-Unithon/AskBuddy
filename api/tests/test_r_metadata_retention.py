import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.learn.metadata_retention import purge_expired_metadata, retention_loop


@pytest.mark.asyncio
async def test_idle_stores_are_purged_in_scoped_batches():
    conn = MagicMock()
    conn.fetch = AsyncMock(side_effect=[[{'store_id': 1}, {'store_id': 7}], []])
    conn.fetchval = AsyncMock(side_effect=[3, 2])
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)
    assert await purge_expired_metadata(pool) == 5
    assert [call.args[1] for call in conn.fetchval.call_args_list] == [1, 7]
    assert [call.args[1] for call in conn.fetch.call_args_list] == [0, 7]


@pytest.mark.asyncio
async def test_retention_retries_without_logging_sensitive_driver_error(monkeypatch, caplog):
    purge = AsyncMock(side_effect=RuntimeError('PRIVATE_QUESTION'))
    monkeypatch.setattr('app.learn.metadata_retention.purge_expired_metadata', purge)
    monkeypatch.setattr('app.learn.metadata_retention.asyncio.sleep', AsyncMock(side_effect=asyncio.CancelledError))
    with pytest.raises(asyncio.CancelledError):
        await retention_loop(object())
    assert 'RuntimeError' in caplog.text and 'PRIVATE_QUESTION' not in caplog.text
