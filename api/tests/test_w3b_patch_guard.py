"""W3b — 사실 카드의 자유 본문 PATCH 는 막고, 레거시 카드는 그대로 둔다."""
from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import pytest

from app.cards import router
from app.cards.schemas import DraftUpdateRequest
from app.errors import ApiError


class _Db:
    def __init__(self, has_facts: bool):
        self.has_facts = has_facts
        self.fetchval_calls = []

    @asynccontextmanager
    async def transaction(self):
        yield

    async def fetchval(self, sql, *args):
        self.fetchval_calls.append((sql, args))
        return self.has_facts


CLAIMS = {"sub": "1", "store_id": 7, "role": "OWNER"}
CARD = {"review_status": "NEEDS_REVIEW", "draft_version_id": 11}
REQ = DraftUpdateRequest(title="t", content="c", expected_version_id=11)


def _patches(create):
    return (
        patch.object(router, "_identity", return_value=(1, 7, "OWNER")),
        patch.object(router.repo, "get_card_for_update", AsyncMock(return_value=CARD)),
        patch.object(router.repo, "create_draft", create),
        patch.object(router.repo, "add_event", AsyncMock()),
        patch.object(router.repo, "mutation_row", AsyncMock(return_value={})),
        patch.object(router, "_mutation", return_value="ok"),
    )


async def _run(db, create):
    ps = _patches(create)
    for p in ps:
        p.start()
    try:
        return await router.update_draft(5, REQ, db, CLAIMS)
    finally:
        for p in ps:
            p.stop()


@pytest.mark.asyncio
async def test_fact_card_is_blocked_before_create_draft():
    create = AsyncMock(return_value=99)
    db = _Db(True)
    with pytest.raises(ApiError) as e:
        await _run(db, create)
    assert e.value.status_code == 409 and e.value.code == "FACT_CARD_TEXT_EDIT_BLOCKED"
    create.assert_not_awaited()
    assert db.fetchval_calls[0][1] == (7, 11)


@pytest.mark.asyncio
async def test_legacy_card_still_creates_draft():
    create = AsyncMock(return_value=99)
    assert await _run(_Db(False), create) == "ok"
    create.assert_awaited_once()
