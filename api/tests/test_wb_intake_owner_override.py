"""Phase B 후속 1 — 업무 자료 아님(NONE) 판정을 점주가 자료별로 "그래도 추출하기"로 덮는다.

- 덮는 로직: 점주 칩 첫째 → 없으면 저장된 판정 순위에서 NONE 다음 → 그것도 없으면 등록 추출기 첫째.
- 덮은 판정 행에 근거(OWNER_HINT | NEXT_RANKED | REGISTERED_DEFAULT)를 남긴다. 분류는 부르지 않는다.
- API 는 자료 하나만 다시 처리한다(같은 작업의 다른 무결과 자료는 그대로).
- 작업 재시도(retry)는 덮어쓰지 않는다 — 저장된 판정을 그대로 쓴다.
모델·DB 는 부르지 않는다.
"""
import asyncio
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

import pytest

from app.errors import ApiError
from app.ingest.intake import classify, records, route
from app.ingest.intake.decide import (Ranked, SectionDecision, override_logic, owner_override)
from app.ingest.intake.plan import plan_extraction
from app.ingest.intake.records import StoredRoute

NONE_R = (Ranked("NONE", 0.9),)
SEG = [SectionDecision("c1", "NONE", (), False, False, False, None, NONE_R, NONE_R),
       SectionDecision("c2", "NONE", (), False, False, False, "c1", NONE_R, NONE_R)]
SRC_NONE = SectionDecision("source", "NONE", (), False, False, False, None, (Ranked("NONE", 1.0),),
                           (Ranked("NONE", 1.0),))
STORED_NONE = StoredRoute(41, "DOC_TEXT", SEG, SRC_NONE)
REG = ("RECIPE",)


def _src(*ranking):
    r = tuple(Ranked(l, s) for l, s in ranking)
    return SectionDecision("source", "NONE", (), False, False, False, None, r, r)


def _seg(cid, *ranking, inherited=None):
    r = tuple(Ranked(l, s) for l, s in ranking)
    return SectionDecision(cid, "NONE", (), False, False, False, inherited, r, r)


# ── 덮는 로직 고르기 ─────────────────────────────────────────────────────

def test_owner_hint_first():
    assert override_logic(SEG, _src(("NONE", .7), ("PROCEDURE", .2)), hints=("POLICY", "RECIPE"),
                          registered=REG) == ("POLICY", "OWNER_HINT")


def test_next_ranked_after_none_from_source_ranking():
    src = _src(("NONE", .7), ("PROCEDURE", .2), ("RECIPE", .1))
    logic, basis = override_logic(SEG, src, hints=(), registered=REG)
    assert (logic, basis) == ("PROCEDURE", "NEXT_RANKED")
    # 미등록 카드 로직 — 판정은 PROCEDURE, 추출기는 가장 가까운 등록 추출기(RECIPE)
    _, source = owner_override(SEG, src, logic=logic, registered=REG)
    assert source.logic == "PROCEDURE" and source.extractors == ("RECIPE",)
    assert source.fallback_unregistered


def test_next_ranked_tie_follows_logics_order():
    src = _src(("NONE", .6), ("POLICY", .2), ("RECIPE", .2))
    assert override_logic(SEG, src, hints=(), registered=REG) == ("RECIPE", "NEXT_RANKED")


def test_next_ranked_reads_section_scores_when_source_collapsed():
    """구간이 모두 NONE 이면 자료 단위 순위는 NONE 1.0 하나로 접힌다(source_decision).
    그때는 같은 평균 규칙으로 구간(상속 제외)의 가산 전 모델 점수에서 NONE 다음을 고른다."""
    seg = [_seg("c1", ("NONE", .7), ("PROCEDURE", .2), ("RECIPE", .1)),
           _seg("c2", ("NONE", .8), ("RECIPE", .2)),
           _seg("c3", ("NONE", .7), ("POLICY", .9), inherited="c1")]  # 상속은 세지 않는다
    # 평균: PROCEDURE .1, RECIPE .15 → RECIPE
    assert override_logic(seg, SRC_NONE, hints=(), registered=REG) == ("RECIPE", "NEXT_RANKED")


def test_next_ranked_notice_overrides_to_notice_and_is_held():
    src = _src(("NONE", .7), ("NOTICE", .2), ("RECIPE", .1))
    logic, basis = override_logic(SEG, src, hints=(), registered=REG)
    assert (logic, basis) == ("NOTICE", "NEXT_RANKED")
    decisions, source = owner_override(SEG, src, logic=logic, registered=REG)
    assert source.logic == "NOTICE" and {d.logic for d in decisions} == {"NOTICE"}
    # 공지 보류가 그대로 적용된다 — 자료 단위·구간별 모두
    whole = plan_extraction(normalizer="VIDEO", decisions=decisions, source=source, sections=None)
    assert not whole.skip and whole.hold_all_notice
    sectioned = plan_extraction(normalizer="DOC_TEXT", decisions=decisions, source=source,
                                sections={"c1": "가", "c2": "나"})
    assert not sectioned.skip and sectioned.hold_all_notice


def test_none_only_uses_registered_default():
    assert override_logic(SEG, SRC_NONE, hints=(), registered=REG) == (
        "RECIPE", "REGISTERED_DEFAULT")
    assert override_logic(SEG, SRC_NONE, hints=(), registered=("PROCEDURE", "RECIPE")) == (
        "PROCEDURE", "REGISTERED_DEFAULT")


def test_override_keeps_segments_and_marks_owner_choice():
    decisions, source = owner_override(SEG, SRC_NONE, logic="RECIPE", registered=REG)
    assert [d.candidate_id for d in decisions] == ["c1", "c2"]
    assert [d.inherited_from for d in decisions] == [None, "c1"]
    assert {d.logic for d in decisions} == {"RECIPE"} and source.logic == "RECIPE"
    assert all(d.extractors == ("RECIPE",) and d.hint_changed_decision for d in decisions)
    assert decisions[0].model_ranking == NONE_R  # 지난 모델 순위는 기록으로 남는다
    assert source.boosted_ranking == (Ranked("RECIPE", 1.0),)


def test_override_refuses_none():
    with pytest.raises(ValueError):
        owner_override(SEG, SRC_NONE, logic="NONE", registered=REG)


# ── 기록: 표본은 옮기고 model 표지·근거를 남긴다 ───────────────────────

class Conn:
    def __init__(self, rows=()):
        self.calls, self.rows = [], list(rows)

    async def fetchval(self, sql, *args):
        self.calls.append((sql, args))
        return 99

    async def fetch(self, sql, *args):
        self.calls.append((sql, args))
        return self.rows


def test_save_owner_override_copies_sample_and_records_basis():
    conn = Conn()
    decisions, source = owner_override(SEG, SRC_NONE, logic="RECIPE", registered=REG)
    got = asyncio.run(records.save_owner_override(
        conn, 11, source_id=3, base=STORED_NONE, owner_hints=(), decisions=decisions,
        source=source, basis="REGISTERED_DEFAULT"))
    sql, args = conn.calls[0]
    assert got == 99
    assert "from intake_route_decisions" in sql and "store_id = $1" in sql and "'UPLOAD'" in sql
    assert args[:3] == (11, 3, 41) and args[3] is None
    assert args[4] == records.OWNER_OVERRIDE_MODEL == "owner-override"
    marker = json.loads(args[5])
    assert marker == {"override": "OWNER_EXTRACT_ANYWAY", "basis": "REGISTERED_DEFAULT",
                      "base_decision_id": 41, "base_source_logic": "NONE", "logic": "RECIPE"}
    assert args[8] == "RECIPE"


def test_save_owner_override_refuses_unknown_basis():
    decisions, source = owner_override(SEG, SRC_NONE, logic="RECIPE", registered=REG)
    with pytest.raises(ValueError):
        asyncio.run(records.save_owner_override(
            Conn(), 11, source_id=3, base=STORED_NONE, owner_hints=(), decisions=decisions,
            source=source, basis="GUESS"))


# ── 자료 하나 덮기: NONE 만 덮고 분류는 부르지 않는다 ─────────────────

def _run_override(*, latest, hints=()):
    save = AsyncMock(return_value=100)
    with patch.object(records, "latest_decision", AsyncMock(return_value=latest)), \
         patch.object(records, "source_owner_hints", AsyncMock(return_value=tuple(hints))), \
         patch.object(records, "save_owner_override", save), \
         patch.object(classify, "classify",
                      AsyncMock(side_effect=AssertionError("분류를 다시 부르면 안 된다"))):
        got = asyncio.run(route.override_none_for_source(Conn(), 11, 3))
    return got, save


def test_override_source_uses_first_owner_hint():
    got, save = _run_override(latest=STORED_NONE, hints=("PROCEDURE", "RECIPE"))
    assert got == 100
    kw = save.await_args.kwargs
    assert save.await_args.args[1] == 11 and kw["source_id"] == 3 and kw["base"] is STORED_NONE
    assert kw["source"].logic == "PROCEDURE" and kw["owner_hints"] == ("PROCEDURE", "RECIPE")
    assert kw["basis"] == "OWNER_HINT"


def test_override_source_next_ranked_without_hints():
    stored = StoredRoute(41, "VIDEO", SEG, _src(("NONE", .7), ("PROCEDURE", .2), ("RECIPE", .1)))
    _, save = _run_override(latest=stored)
    kw = save.await_args.kwargs
    assert kw["source"].logic == "PROCEDURE" and kw["source"].extractors == ("RECIPE",)
    assert kw["basis"] == "NEXT_RANKED"


def test_override_source_registered_default_when_only_none():
    _, save = _run_override(latest=STORED_NONE)
    kw = save.await_args.kwargs
    assert kw["source"].logic == "RECIPE" and kw["basis"] == "REGISTERED_DEFAULT"


def test_override_source_skips_non_none_decision():
    recipe = StoredRoute(42, "DOC_TEXT", SEG, SRC_NONE.__class__(
        "source", "RECIPE", ("RECIPE",), False, False, False, None, (), ()))
    got, save = _run_override(latest=recipe)
    assert got is None and save.await_count == 0
    got, save = _run_override(latest=None)
    assert got is None and save.await_count == 0


def test_route_source_reuses_override_without_classify():
    """덮은 판정은 최신 판정이라 작업의 route_source 가 분류 없이 그대로 쓴다."""
    decisions, source = owner_override(SEG, SRC_NONE, logic="RECIPE", registered=REG)
    override = StoredRoute(100, "DOC_TEXT", decisions, source)

    class Pool:
        @asynccontextmanager
        async def acquire(self):
            yield object()

    with patch.object(records, "latest_decision", AsyncMock(return_value=override)), \
         patch.object(classify, "classify",
                      AsyncMock(side_effect=AssertionError("분류를 다시 부르면 안 된다"))):
        got = asyncio.run(route.route_source(Pool(), 11, {"source_id": 3},
                                             cache=route.IntakeCache(), usage_sink=None,
                                             usage_base=None))
    assert got is override and got.source.logic == "RECIPE"


# ── 자료 하나만 다시 대기열에 넣는 SQL ─────────────────────────────────

class SqlConn:
    def __init__(self, returned):
        self.returned, self.calls = returned, []

    async def fetchval(self, sql, *args):
        self.calls.append((sql, args))
        return self.returned

    async def execute(self, sql, *args):
        self.calls.append((sql, args))


def test_requeue_targets_only_that_intake_none_source():
    from app.ingest import job_repository as job_repo

    conn = SqlConn(returned=3)
    assert asyncio.run(job_repo.requeue_intake_none_source(conn, 11, 7, 3)) is True
    sql, args = conn.calls[0]
    assert args == (11, 7, 3)
    assert "source_id = $3" in sql and "status = 'NO_RESULT'" in sql
    assert "error_code = 'INTAKE_NONE'" in sql and "'DELETED'" in sql
    assert "status = 'QUEUED'" in sql and "recovery_state = null" in sql
    job_sql, job_args = conn.calls[1]
    assert "update ingest_jobs" in job_sql and "status = 'QUEUED'" in job_sql
    assert job_args == (11, 7)

    conn = SqlConn(returned=None)
    assert asyncio.run(job_repo.requeue_intake_none_source(conn, 11, 7, 3)) is False
    assert len(conn.calls) == 1  # 대상이 아니면 작업을 건드리지 않는다


# ── 라우터: 자료별 그래도 추출하기 ─────────────────────────────────────

class Db:
    @asynccontextmanager
    async def transaction(self):
        yield


OWNER = {"user_id": 1, "store_id": 11, "role": "OWNER"}
JOB = {"job_id": 7, "status": "SUCCEEDED", "category_version": 1}


def _row(**kw):
    base = {"job_status": "SUCCEEDED", "status": "NO_RESULT", "error_code": "INTAKE_NONE",
            "source_availability": "AVAILABLE"}
    return {**base, **kw}


def _extract(*, claims=OWNER, job=JOB, row=None, latest=STORED_NONE, requeued=True):
    from app.ingest import router

    bg = NS(tasks=[], add_task=lambda fn, *a: bg.tasks.append((fn.__name__, a)))
    save = AsyncMock(return_value=100)
    requeue = AsyncMock(return_value=requeued)
    reset = AsyncMock(side_effect=AssertionError("작업 전체 재시도 경로를 타면 안 된다"))
    lock = AsyncMock(return_value=_row() if row is None else row)
    with patch.object(router.job_repo, "get_job", AsyncMock(return_value=job)), \
         patch.object(router.job_repo, "lock_job_source", lock), \
         patch.object(router.job_repo, "requeue_intake_none_source", requeue), \
         patch.object(router.job_repo, "reset_retryable_sources", reset), \
         patch.object(records, "latest_decision", AsyncMock(return_value=latest)), \
         patch.object(records, "source_owner_hints", AsyncMock(return_value=())), \
         patch.object(records, "save_owner_override", save), \
         patch.object(classify, "classify",
                      AsyncMock(side_effect=AssertionError("분류를 다시 부르면 안 된다"))):
        out = asyncio.run(router.extract_source_anyway(7, 3, bg, Db(), claims))
    return out, bg, save, requeue, lock


def test_extract_anyway_requeues_only_that_source():
    out, bg, save, requeue, lock = _extract()
    assert (out.job_id, out.source_count) == (7, 1)
    assert lock.await_args.args[1:] == (11, 7, 3)
    save.assert_awaited_once()
    assert save.await_args.args[1] == 11 and save.await_args.kwargs["source_id"] == 3
    assert requeue.await_args.args[1:] == (11, 7, 3)
    assert bg.tasks == [("process_ingest_job", (11, 7))]


def test_extract_anyway_other_store_job_is_404():
    with pytest.raises(ApiError) as e:
        _extract(job=None)
    assert e.value.status_code == 404


def test_extract_anyway_source_not_in_job_is_404():
    from app.ingest import router

    bg = NS(tasks=[], add_task=lambda *a: None)
    with patch.object(router.job_repo, "get_job", AsyncMock(return_value=JOB)), \
         patch.object(router.job_repo, "lock_job_source", AsyncMock(return_value=None)):
        with pytest.raises(ApiError) as e:
            asyncio.run(router.extract_source_anyway(7, 3, bg, Db(), OWNER))
    assert e.value.status_code == 404


def test_extract_anyway_staff_is_403():
    with pytest.raises(ApiError) as e:
        _extract(claims={"user_id": 2, "store_id": 11, "role": "STAFF"})
    assert e.value.status_code == 403


@pytest.mark.parametrize("row", [
    _row(error_code="NO_RESULT"),          # 분류 판정 때문이 아닌 무결과
    _row(status="FAILED", error_code="EXTRACTION_FAILED"),
    _row(status="SUCCEEDED", error_code=None),
    _row(source_availability="DELETED"),
])
def test_extract_anyway_rejects_non_intake_none_source(row):
    with pytest.raises(ApiError) as e:
        _extract(row=row)
    assert e.value.status_code == 409 and e.value.code == "SOURCE_NOT_JUDGED_NONE"


@pytest.mark.parametrize("row", [_row(job_status="QUEUED"), _row(job_status="EXTRACTING"),
                                 _row(status="QUEUED", error_code=None)])
def test_extract_anyway_in_progress_is_409(row):
    with pytest.raises(ApiError) as e:
        _extract(row=row)
    assert e.value.status_code == 409 and e.value.code == "INGEST_JOB_IN_PROGRESS"


def test_extract_anyway_latest_decision_not_none_is_409():
    recipe = StoredRoute(42, "DOC_TEXT", SEG, SRC_NONE.__class__(
        "source", "RECIPE", ("RECIPE",), False, False, False, None, (), ()))
    with pytest.raises(ApiError) as e:
        _extract(latest=recipe)
    assert e.value.status_code == 409


# ── 작업 재시도는 덮어쓰지 않는다 ─────────────────────────────────────

@pytest.mark.parametrize("include_no_result", [False, True])
def test_retry_never_overrides(include_no_result):
    from app.ingest import router

    bg = NS(tasks=[], add_task=lambda fn, *a: bg.tasks.append(a))
    save = AsyncMock(side_effect=AssertionError("재시도는 판정을 덮지 않는다"))
    with patch.object(router.job_repo, "get_job", AsyncMock(return_value=JOB)), \
         patch.object(router.job_repo, "reset_retryable_sources",
                      AsyncMock(return_value=1)) as reset, \
         patch.object(records, "save_owner_override", save):
        asyncio.run(router.retry_ingest_job(7, bg, Db(), OWNER,
                                            include_no_result=include_no_result))
    assert reset.await_args.kwargs == {"include_no_result": include_no_result}
    assert not hasattr(route, "override_none_for_retry")
