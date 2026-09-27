"""DB 연결 풀 크기 설정 — 기본값·검증·init_pool 전달."""
import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError

from app import deps
from app.config import Settings


def test_pool_size_defaults_keep_previous_behavior(monkeypatch):
    monkeypatch.delenv("DB_POOL_MIN_SIZE", raising=False)
    monkeypatch.delenv("DB_POOL_MAX_SIZE", raising=False)
    s = Settings(_env_file=None)
    assert s.db_pool_min_size == 1
    assert s.db_pool_max_size == 10


def test_pool_size_reads_env(monkeypatch):
    monkeypatch.setenv("DB_POOL_MIN_SIZE", "2")
    monkeypatch.setenv("DB_POOL_MAX_SIZE", "4")
    s = Settings(_env_file=None)
    assert (s.db_pool_min_size, s.db_pool_max_size) == (2, 4)


@pytest.mark.parametrize("min_size,max_size", [(0, 10), (1, 0), (5, 4), (-1, 3)])
def test_pool_size_rejects_invalid(min_size, max_size):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, db_pool_min_size=min_size, db_pool_max_size=max_size)


def test_init_pool_passes_configured_sizes(monkeypatch):
    s = Settings(_env_file=None, db_pool_min_size=3, db_pool_max_size=7)
    monkeypatch.setattr(deps, "_pool", None)
    monkeypatch.setattr(deps, "get_settings", lambda: s)
    fake = AsyncMock(return_value=object())
    with patch.object(deps.asyncpg, "create_pool", fake):
        asyncio.run(deps.init_pool())
    fake.assert_awaited_once()
    assert fake.await_args.kwargs["min_size"] == 3
    assert fake.await_args.kwargs["max_size"] == 7
    monkeypatch.setattr(deps, "_pool", None)
