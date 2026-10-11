"""Phase A Task 7 — 카드 판 1 은 코드가 만든다."""
from __future__ import annotations

import pytest

from app.ingest import repository as repo


class _Conn:
    def __init__(self):
        self.calls = []

    async def fetchval(self, query, *args):
        self.calls.append(query)
        if "insert into knowledge_cards" in query:
            return 5
        if "insert into card_versions" in query:
            return 50
        raise AssertionError(query)

    async def execute(self, query, *args):
        self.calls.append(query)


@pytest.mark.asyncio
async def test_insert_card_creates_version_one_and_points_draft():
    conn = _Conn()
    card_id = await repo.insert_card(conn, 7, category_id=1, source_id=11, title="음료Z",
                                     content="음료Z 물 225ml", confidence=90.0, entity_id=4)
    assert card_id == 5
    joined = "\n".join(conn.calls)
    assert "insert into card_versions" in joined
    assert "'EXTRACTION'" in joined
    assert "draft_version_id" in joined
