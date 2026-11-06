"""Phase B B-D3a — 업로드 요청의 점주 선택 칩. 선택·여러 개·강제 아님·허용값만."""
import asyncio

import pytest
from pydantic import ValidationError

from app.ingest import repository as repo
from app.ingest.schemas import CreateSourceRequest

BASE = dict(source_type="SCAN", file_url="b/1/scan/x.pdf", meta={"doc_type": "PDF"})


def test_hints_optional_default_empty():
    assert CreateSourceRequest(**BASE).owner_hints == []


def test_multiple_hints_allowed():
    assert CreateSourceRequest(**BASE, owner_hints=["RECIPE", "NOTICE"]).owner_hints == ["RECIPE", "NOTICE"]


@pytest.mark.parametrize("bad", [["NONE"], ["레시피"], ["RECIPE"] * 6])
def test_rejects_unknown_or_too_many(bad):
    with pytest.raises(ValidationError):
        CreateSourceRequest(**BASE, owner_hints=bad)


class _Conn:
    def __init__(self):
        self.args = None

    async def fetchval(self, sql, *args):
        self.args = args
        return 1


def _create(**kw):
    conn = _Conn()
    asyncio.run(repo.create_source(
        conn, 7, uploaded_by=1, source_type="SCAN", file_url="f", title=None,
        file_size=None, content_hash=None, mime_type=None, original_filename=None, **kw))
    return conn.args


def test_repo_stores_deduplicated_hints():
    assert _create(owner_hints=["RECIPE", "NOTICE", "RECIPE"])[-1] == ["RECIPE", "NOTICE"]


def test_repo_empty_hints_is_null():
    assert _create()[-1] is None
    assert _create(owner_hints=[])[-1] is None
