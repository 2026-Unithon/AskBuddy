"""Phase A Task 5 — 점주 답변 글을 사실 수집 입력으로 만든다."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.ingest import owner_text, pipeline
from app.ingest.schemas import Evidence, ExtractedAssertion


def _a(ref, original):
    return ExtractedAssertion(local_ref=ref, original_assertion=original, subject="음료Z",
                              attribute="물", value="225", confidence=0.9,
                              evidence=Evidence(source_id=1, timestamp_sec=0))


def test_compose_text_marks_question_as_context():
    text = owner_text.compose_text(" 음료Z 물 얼마나? ", " 225ml 넣어요 ")
    assert text.startswith(owner_text.QUESTION_HEADER)
    assert "음료Z 물 얼마나?" in text and "225ml 넣어요" in text
    assert text.index(owner_text.QUESTION_HEADER) < text.index(owner_text.ANSWER_HEADER)


def test_drop_question_only_keeps_answer_facts():
    q, ans = "음료Z 물은 몇 ml 넣나요?", "음료Z 물은 225ml 넣어요"
    kept = owner_text.drop_question_only(
        [_a("f1", "음료Z 물은 몇 ml 넣나요"), _a("f2", "음료Z 물은 225ml 넣어요"), _a("f3", "")],
        question=q, answer=ans)
    assert [x.local_ref for x in kept] == ["f2", "f3"]


def test_usage_scope_without_job_uses_run_tag():
    ctx = pipeline._usage_context(7, 11, None, "EXTRACT", "OPERATING", "PRODUCT", None, run_tag=99)
    assert ctx.logical_call_id == "r99:src11:extract"
    ctx = pipeline._usage_context(7, 11, 5, "EXTRACT", "REGISTRATION", "PRODUCT", None, run_tag=99)
    assert ctx.logical_call_id == "job5r99:src11:extract"


class _Pool:
    """acquire() 가 같은 가짜 연결을 돌려준다."""

    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        pool = self

        class _Ctx:
            async def __aenter__(self):
                return pool.conn

            async def __aexit__(self, *exc):
                return False
        return _Ctx()


class _Conn:
    def __init__(self, ledger_exists):
        self.ledger_exists = ledger_exists
        self.executed = []

    async def fetchval(self, query, *args):
        if "from source_facts" in query:
            return self.ledger_exists
        if "category_version" in query:
            return 1
        if "count(*)" in query:
            return 2
        raise AssertionError(query)

    async def execute(self, query, *args):
        self.executed.append(query)

    def transaction(self):
        class _Tx:
            async def __aenter__(self):
                return None

            async def __aexit__(self, *exc):
                return False
        return _Tx()


@pytest.mark.asyncio
async def test_resume_skips_extraction_when_ledger_exists():
    conn = _Conn(ledger_exists=True)
    extract = AsyncMock()
    with patch("app.ingest.extract.extract_facts", extract), \
            patch.object(owner_text.repo, "enabled_categories", AsyncMock(return_value={"기타": 1})), \
            patch.object(owner_text.repo, "glossary", AsyncMock(return_value=[])), \
            patch.object(owner_text.repo, "set_status", AsyncMock()), \
            patch.object(owner_text.pipeline, "_prepare_fact_assembly", AsyncMock()), \
            patch.object(owner_text.pipeline, "_persist_fact_cards", AsyncMock(return_value=0)):
        await owner_text.ingest_owner_text(_Pool(conn), store_id=7, source_id=11,
                                           question="질문", answer="답", run_tag=1)
    extract.assert_not_awaited()


class _EnsureConn:
    """ensure_owner_answer_source 가 치는 조회만 흉내 낸다. link_results 는 연결 조회 결과 순서."""

    def __init__(self, link_results, in_tx=True):
        self.link_results = list(link_results)
        self.in_tx = in_tx
        self.executed = []

    def is_in_transaction(self):
        return self.in_tx

    async def fetchval(self, query, *args):
        if "from owner_answer_sources" in query:
            return self.link_results.pop(0)
        if "insert into sources" in query:
            self.executed.append(("insert_source", args))
            return 500
        if "select status from sources" in query:
            return "PROCESSING"
        raise AssertionError(query)

    async def execute(self, query, *args):
        self.executed.append((query.split("(")[0].strip()[:40], args))


def _kinds(conn):
    return [e[0] for e in conn.executed]


@pytest.mark.asyncio
async def test_ensure_existing_link_returns_without_insert():
    conn = _EnsureConn([42])
    got = await owner_text.ensure_owner_answer_source(
        conn, 7, owner_answer_id=3, actor_id=1, question="q", answer="a")
    assert got == (42, "PROCESSING")
    assert "insert_source" not in _kinds(conn)


@pytest.mark.asyncio
async def test_ensure_new_inserts_source_and_link():
    conn = _EnsureConn([None, 500])
    got = await owner_text.ensure_owner_answer_source(
        conn, 7, owner_answer_id=3, actor_id=1, question="q", answer="a")
    assert got == (500, "PROCESSING")
    assert "insert_source" in _kinds(conn)
    assert any(k.startswith("insert into owner_answer_sources") for k in _kinds(conn))
    assert not any(k.startswith("delete from sources") for k in _kinds(conn))


@pytest.mark.asyncio
async def test_ensure_race_loser_deletes_own_source():
    conn = _EnsureConn([None, 42])  # 연결 삽입 뒤 다시 읽으니 다른 자료가 이겼다
    got = await owner_text.ensure_owner_answer_source(
        conn, 7, owner_answer_id=3, actor_id=1, question="q", answer="a")
    assert got[0] == 42
    deletes = [e for e in conn.executed if e[0].startswith("delete from sources")]
    assert deletes and deletes[0][1] == (7, 500)


@pytest.mark.asyncio
async def test_ensure_requires_transaction():
    with pytest.raises(RuntimeError):
        await owner_text.ensure_owner_answer_source(
            _EnsureConn([], in_tx=False), 7, owner_answer_id=3, actor_id=1, question="q", answer="a")


@pytest.mark.asyncio
async def test_extraction_path_filters_and_persists_ledger():
    from types import SimpleNamespace
    conn = _Conn(ledger_exists=False)
    q, ans = "음료Z 물은 몇 ml 넣나요?", "음료Z 물은 225ml 넣어요"
    result = SimpleNamespace(assertions=[_a("f1", "음료Z 물은 몇 ml 넣나요"),
                                         _a("f2", "음료Z 물은 225ml 넣어요")])
    extract = AsyncMock(return_value=result)
    persist = AsyncMock(return_value={})
    with patch("app.ingest.extract.extract_facts", extract), \
            patch.object(owner_text.repo, "enabled_categories", AsyncMock(return_value={"기타": 1})), \
            patch.object(owner_text.repo, "glossary", AsyncMock(return_value=[])), \
            patch.object(owner_text.repo, "set_status", AsyncMock()), \
            patch.object(owner_text.pipeline, "_persist_ledger", persist), \
            patch.object(owner_text.pipeline, "_prepare_fact_assembly", AsyncMock()), \
            patch.object(owner_text.pipeline, "_persist_fact_cards", AsyncMock(return_value=0)):
        await owner_text.ingest_owner_text(_Pool(conn), store_id=7, source_id=11,
                                           question=q, answer=ans, run_tag=1)
    kw = extract.await_args.kwargs
    assert kw["source_type"] == "OWNER_TEXT" and kw["text"] == owner_text.compose_text(q, ans)
    args = persist.await_args.args
    assert args[3] == "OWNER_TEXT" and [x.local_ref for x in args[4]] == ["f2"]


class _UniqueHashConn:
    """sources 의 (store_id, content_hash) 부분 유일 제약을 흉내 낸다(content_hash 가 null 이면 통과)."""

    def __init__(self):
        self.links: dict[int, int] = {}
        self.sources: dict[int, tuple[int, str | None]] = {}
        self._next = 500

    def is_in_transaction(self):
        return True

    async def fetchval(self, query, *args):
        if "from owner_answer_sources" in query:
            return self.links.get(args[1])
        if "insert into sources" in query:
            assert "null, null" in query, "content_hash 는 null 이어야 한다"
            store_id = args[0]
            # 부분 유일 제약: null 이 아닌 같은 해시가 같은 매장에 있으면 실패
            hashes = [h for (s, h) in self.sources.values() if s == store_id and h is not None]
            assert len(hashes) == len(set(hashes))
            self._next += 1
            self.sources[self._next] = (store_id, None)
            return self._next
        if "select status from sources" in query:
            return "PROCESSING"
        raise AssertionError(query)

    async def execute(self, query, *args):
        if query.startswith("insert into owner_answer_sources"):
            self.links.setdefault(args[1], args[2])


@pytest.mark.asyncio
async def test_two_identical_answers_in_one_store_each_get_a_source():
    # I1: 같은 매장에서 같은 글("네")의 답변 둘이 와도 각자 자료를 만든다
    conn = _UniqueHashConn()
    first = await owner_text.ensure_owner_answer_source(
        conn, 7, owner_answer_id=1, actor_id=1, question="음료Z 얼음 넣나요?", answer="네")
    second = await owner_text.ensure_owner_answer_source(
        conn, 7, owner_answer_id=2, actor_id=1, question="음료Z 컵 뚜껑 닫나요?", answer="네")
    assert first[0] != second[0]
    assert all(h is None for (_s, h) in conn.sources.values())
