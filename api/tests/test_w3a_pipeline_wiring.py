"""W3a 파이프라인 연결 — 준비(짧은 연결)·저장(사유 분기·순서·누락 예외)·작업 카드 수.

모듈 함수는 patch 로 대역을 둔다. 모델·DB 는 부르지 않는다. 설정은 필드 몇 개뿐인 NS 다(F18).
"""
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.config
from app.config import Settings
from app.ingest import (card_plan, entities, fact_assembly, fact_cards, impact, job_worker,
                        pipeline)
from app.ingest.card_plan import EntityGroup, EntityPlanResult, PlanFact
from app.ingest.fact_assembly import AssemblyInput, HeldFact, PlanningOutcome
from app.ingest.fact_cards import DispositionCounts, EntityCardState, WrittenEntity
from app.ingest.pipeline import ExtractionOutcome, PreparedAssembly


def _fact(entity_id: int, revision_id: int) -> PlanFact:
    return PlanFact(fact_revision_id=revision_id, fact_id=revision_id * 10, entity_id=entity_id,
                    subject="음료Z", predicate="물", variant_temperature=None, variant_size=None,
                    quantity_value=None, quantity_unit=None, value_text="합성", polarity="AFFIRM",
                    step_order=None, conditions=(), exceptions=(),
                    original_assertion="음료Z 물 합성", assertion="음료Z 물 합성")


def _group(entity_id: int, *revision_ids: int) -> EntityGroup:
    return EntityGroup(entity_id=entity_id, canonical_name=f"합성대상{entity_id}",
                       facts=tuple(_fact(entity_id, r) for r in revision_ids or (entity_id * 100,)))


def _state(entity_id: int, mode: str) -> EntityCardState:
    return EntityCardState(entity_id, mode, (), "EXISTING_CARD" if mode == "DEFER" else None)


def _counts(missing=0):
    return DispositionCounts(total=3, missing=missing, linked=2, review_pending={"X": 1},
                             excluded={})


def _planning(failed=()):
    return PlanningOutcome(proposals={}, failed_entity_ids=tuple(failed), unresolved=(),
                           batch_count=1, errors=())


class _Patches:
    """_persist_fact_cards 가 부르는 모듈 함수 대역. 호출 순서를 calls 에 남긴다."""

    def __init__(self, *, now, reload=None, plan=None, missing=0):
        self.calls: list = []
        self.now = now
        self.reload = reload or {}
        self.plan = plan or {}
        self.missing = missing
        self.mark = AsyncMock(side_effect=self._mark)
        self.write = AsyncMock(side_effect=self._write)
        self.stack = []

    def _rec(self, name):
        async def f(*a, **k):
            self.calls.append(name)
        return f

    async def _mark(self, conn, store_id, *, source_id, fact_ids, reason):
        self.calls.append(("mark", tuple(fact_ids), reason))
        return 1

    async def _write(self, conn, store_id, **kw):
        self.calls.append(("write", kw["group"].entity_id))
        return WrittenEntity(entity_id=kw["group"].entity_id, card_ids=(1,),
                             new_version_ids=(11, 12), linked_fact_ids=())

    async def _state(self, conn, store_id, entity_id):
        return self.now[entity_id]

    async def _fact_ids(self, conn, store_id, entity_id):
        return [entity_id * 1000]

    async def _load(self, conn, store_id, ids):
        (e,) = ids
        group = self.reload.get(e)
        return AssemblyInput(groups=(group,) if group else (), held=())

    def _plan_entity(self, group, proposals):
        reason = self.plan.get(group.entity_id)
        if reason:
            return EntityPlanResult(group.entity_id, (), None, reason)
        return EntityPlanResult(group.entity_id, ("카드",), None, None)

    async def _counts(self, conn, store_id, source_id):
        self.calls.append("counts")
        return _counts(self.missing)

    def __enter__(self):
        for obj, name, value in [
            (entities, "lock_store_knowledge", self._rec("lock")),
            (fact_cards, "record_unresolvable_occurrences", self._rec("unresolvable")),
            (fact_cards, "entity_card_state", self._state),
            (fact_cards, "entity_fact_ids", self._fact_ids),
            (fact_cards, "mark_pending", self.mark),
            (fact_cards, "write_entity_cards", self.write),
            (fact_cards, "disposition_counts", self._counts),
            (fact_assembly, "load_entity_groups", self._load),
            (card_plan, "plan_entity", self._plan_entity),
            (impact, "record_upload_proposals", self._rec("proposals")),
        ]:
            p = patch.object(obj, name, value)
            p.start()
            self.stack.append(p)
        return self

    def __exit__(self, *exc):
        for p in reversed(self.stack):
            p.stop()
        return False


async def _persist(prepared):
    return await pipeline._persist_fact_cards(object(), 3, 5, {"기타": 1}, prepared,
                                              job_id=9, category_version=1)


@pytest.mark.asyncio
async def test_persist_fact_cards_reason_matrix():
    ids = tuple(range(1, 9))
    before = {1: "DEFER", 2: "NEW", 3: "DEFER", 4: "NEW", 5: "NEW", 6: "NEW", 7: "NEW", 8: "NEW"}
    now = {1: "DEFER", 2: "DEFER", 3: "NEW", 4: "NEW", 5: "NEW", 6: "NEW", 7: "NEW",
           8: "REASSEMBLE"}
    groups = {e: _group(e) for e in ids if before[e] != "DEFER"}
    prepared = PreparedAssembly(
        entity_ids=ids, states={e: _state(e, m) for e, m in before.items()}, groups=groups,
        held=(), data_errors={4: card_plan.DATA_REQUIRES_CYCLE}, planning=_planning([5]))
    reload = dict(groups)
    reload[6] = _group(6, 600, 601)  # 준비 뒤 입력이 달라졌다
    with _Patches(now={e: _state(e, m) for e, m in now.items()}, reload=reload,
                  plan={7: card_plan.DATA_TOO_LARGE}) as p:
        created = await _persist(prepared)

    reasons = {fact_ids[0] // 1000: reason for kind, fact_ids, reason in
               (c for c in p.calls if isinstance(c, tuple) and c[0] == "mark")}
    assert reasons == {
        1: fact_cards.REASON_EXISTING_CARD,
        2: fact_cards.REASON_CONCURRENT,
        3: fact_cards.REASON_CONCURRENT,
        4: card_plan.DATA_REQUIRES_CYCLE,
        5: fact_cards.REASON_ASSEMBLY_FAILED,
        6: fact_cards.REASON_STALE_INPUT,
        7: card_plan.DATA_TOO_LARGE,
    }
    p.write.assert_awaited_once()
    kw = p.write.await_args.kwargs
    assert kw["state"].mode == "REASSEMBLE" and kw["state"].entity_id == 8
    assert kw["group"] is groups[8] and kw["job_id"] == 9 and kw["category_version"] == 1
    assert created == 2


@pytest.mark.asyncio
async def test_persist_fact_cards_deferred_write_is_not_counted():
    prepared = PreparedAssembly(entity_ids=(8,), states={8: _state(8, "NEW")},
                                groups={8: _group(8)}, held=(), data_errors={},
                                planning=_planning())
    with _Patches(now={8: _state(8, "NEW")}, reload={8: _group(8)}) as p:
        p.write.side_effect = None
        p.write.return_value = WrittenEntity(8, (), (), (), deferred_reason="EXISTING_CARD")
        assert await _persist(prepared) == 0


@pytest.mark.asyncio
async def test_persist_fact_cards_lock_and_order():
    held = HeldFact(fact_revision_id=901, fact_id=9010, entity_id=8, reason="VARIANT_UNRESOLVED")
    prepared = PreparedAssembly(entity_ids=(8,), states={8: _state(8, "NEW")},
                                groups={8: _group(8)}, held=(held,), data_errors={},
                                planning=_planning())
    with _Patches(now={8: _state(8, "NEW")}, reload={8: _group(8)}) as p:
        await _persist(prepared)
    assert p.calls == ["lock", "unresolvable", ("write", 8),
                       ("mark", (9010,), "VARIANT_UNRESOLVED"), "proposals", "counts"]


@pytest.mark.asyncio
async def test_persist_fact_cards_missing_raises():
    prepared = PreparedAssembly(entity_ids=(), states={}, groups={}, held=(), data_errors={},
                                planning=_planning())
    with _Patches(now={}, missing=1):
        with pytest.raises(RuntimeError, match="처분 누락"):
            await _persist(prepared)


class _Lease:
    def __init__(self, pool):
        self.pool = pool

    async def __aenter__(self):
        self.pool.held = True
        return self.pool.conn

    async def __aexit__(self, *exc):
        self.pool.held = False
        return False


class _Pool:
    def __init__(self):
        self.held = False
        self.conn = AsyncMock()

    def acquire(self):
        return _Lease(self)


@pytest.mark.asyncio
async def test_prepare_skips_defer_and_data_error_and_holds_no_connection():
    pool = _Pool()
    seen: dict = {}
    g2, g3 = _group(2), _group(3)

    async def load(conn, store_id, ids):
        assert pool.held
        seen["load"] = list(ids)
        return AssemblyInput(groups=(g2, g3), held=())

    async def plan(**kw):
        seen["held_during_plan"] = pool.held
        seen["groups"] = [g.entity_id for g in kw["groups"]]
        seen["ctx"] = kw["context_for"](2)
        seen["strict"] = kw["strict"]
        return _planning()

    states = {1: _state(1, "DEFER"), 2: _state(2, "NEW"), 3: _state(3, "NEW")}
    with patch.object(fact_assembly, "entities_for_source", AsyncMock(return_value=[1, 2, 3])), \
         patch.object(fact_cards, "entity_card_state",
                      AsyncMock(side_effect=lambda c, s, e: states[e])), \
         patch.object(fact_assembly, "load_entity_groups", load), \
         patch.object(card_plan, "check_group",
                      lambda g: card_plan.DATA_NO_NAME if g.entity_id == 3 else None), \
         patch.object(fact_assembly, "plan_entities", plan):
        prepared = await pipeline._prepare_fact_assembly(
            pool, 1, 7, categories=["기타"], glossary=[], usage_sink=None,
            usage_base=(1, 5, "REGISTRATION", "PRODUCT", None, 42), raw_sink=None, strict=True)

    assert seen["load"] == [2, 3]  # DEFER 대상은 입력을 읽지 않는다
    assert seen["groups"] == [2]  # 데이터 오류 묶음은 모델에 보내지 않는다
    assert seen["held_during_plan"] is False
    assert seen["ctx"].segment_id == "plan2" and seen["ctx"].stage == "ASSEMBLE"
    assert seen["strict"] is True
    assert prepared.entity_ids == (1, 2, 3) and set(prepared.groups) == {2, 3}
    assert prepared.data_errors == {3: card_plan.DATA_NO_NAME}
    assert prepared.states == states


async def _run_source(tmp_path):
    src = {"source_id": 7, "store_id": 1, "source_type": "SCAN", "file_url": "x",
           "content_hash": "h", "status": "PROCESSING"}
    conn = AsyncMock()
    conn.transaction = MagicMock(side_effect=lambda: _Tx())
    conn.fetchval = AsyncMock(return_value=3)

    class Pool:
        def acquire(self):
            return _ConnLease(conn)

    outcome = ExtractionOutcome([], [], 1, 0, [], {})
    prepared = PreparedAssembly((), {}, {}, (), {}, _planning())
    mocks = NS(
        prepare=AsyncMock(return_value=prepared),
        persist_facts=AsyncMock(return_value=2),
    )
    settings = Settings(_env_file=None)
    with patch.object(pipeline, "get_pool", return_value=Pool()), \
         patch.object(pipeline, "_preprocess", AsyncMock(return_value=("본문", [], []))), \
         patch.object(pipeline.repo, "get_source", AsyncMock(return_value=src)), \
         patch.object(pipeline.repo, "set_status", AsyncMock()), \
         patch.object(pipeline.repo, "enabled_categories", AsyncMock(return_value={"기타": 1})), \
         patch.object(pipeline.repo, "glossary", AsyncMock(return_value=[])), \
         patch.object(pipeline.storage, "workdir", return_value=tmp_path / "w"), \
         patch.object(pipeline, "_extract_facts_all", AsyncMock(return_value=outcome)), \
         patch.object(pipeline, "_record_segment_failures", AsyncMock()), \
         patch.object(pipeline, "_prepare_fact_assembly", mocks.prepare), \
         patch.object(pipeline, "_persist_fact_cards", mocks.persist_facts), \
         patch("app.config.get_settings", return_value=settings):
        await pipeline.process_source(1, 7)
    return mocks, prepared, conn


class _Tx:
    async def __aenter__(self):
        return None

    async def __aexit__(self, *exc):
        return False


class _ConnLease:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, *exc):
        return False


@pytest.mark.asyncio
async def test_process_source_uses_fact_path(tmp_path):
    mocks, prepared, conn = await _run_source(tmp_path)
    mocks.prepare.assert_awaited_once()
    assert mocks.prepare.await_args.args[1:] == (1, 7)
    assert mocks.prepare.await_args.kwargs["strict"] is True
    mocks.persist_facts.assert_awaited_once()
    args, kw = mocks.persist_facts.await_args.args, mocks.persist_facts.await_args.kwargs
    assert args[0] is conn and args[1:3] == (1, 7) and args[4] is prepared
    assert kw == {"job_id": 3, "category_version": 3}


# ── job_worker 카드 수 ──────────────────────────────────────────────────

def _worker(*, linked_cards, pending):
    conn = AsyncMock()

    async def fetchrow(sql, *args):
        if "update ingest_jobs" in sql:
            return {"category_version": 1}
        if "from sources" in sql:
            return {"status": "DONE", "error_message": None}
        return {"segments_total": 1, "segments_failed": 0}

    async def fetchval(sql, *args):
        if "returning started_at" in sql:
            return None
        if "count(distinct card_id) from fact_occurrences" in sql:
            assert "disposition = 'LINKED'" in sql and args == (1, 3)
            return linked_cards
        if "disposition = 'REVIEW_PENDING'" in sql:
            assert args == (1, 3)
            return pending
        raise AssertionError(sql)

    conn.fetchrow = AsyncMock(side_effect=fetchrow)
    conn.fetchval = AsyncMock(side_effect=fetchval)
    conn.fetch = AsyncMock(return_value=[
        {"source_id": 3, "failed_segment_ids": None, "segments_total": None}])

    class Pool:
        def acquire(self):
            return _ConnLease(conn)

    return Pool(), conn


async def _run_worker(**counts):
    pool, conn = _worker(**counts)
    with patch.object(job_worker, "get_pool", return_value=pool), \
         patch.object(job_worker.pipeline, "process_source", AsyncMock(return_value=None)), \
         patch.object(job_worker, "_refresh_job", AsyncMock(return_value=("NO_RESULT", 0))), \
         patch.object(job_worker, "create_ingest_completed_notification",
                      AsyncMock(return_value=None)), \
         patch("app.config.get_settings", return_value=NS()):
        await job_worker.process_ingest_job(1, 2)
    for c in conn.execute.await_args_list:
        if "set status = $4, card_count = $5" in c.args[0]:
            return c.args[4:], conn
    raise AssertionError("자료 결과 UPDATE 가 없다")


@pytest.mark.asyncio
async def test_job_worker_card_count_uses_linked_occurrences():
    row, _ = await _run_worker(linked_cards=0, pending=2)
    assert row == ("NO_RESULT", 0, "NO_RESULT", "카드에 반영되지 않고 검수할 사실이 남았습니다.")
    row, _ = await _run_worker(linked_cards=0, pending=0)
    assert row == ("NO_RESULT", 0, "NO_RESULT", "추출된 업무 카드가 없습니다.")
    row, _ = await _run_worker(linked_cards=2, pending=1)
    assert row == ("SUCCEEDED", 2, None, None)
