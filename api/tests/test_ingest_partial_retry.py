"""PARTIAL 자료 재시도가 잃은 구간만 다시 읽고 카드를 중복하지 않는지 검증한다.

F02: 재시도 대상이 FAILED/NO_RESULT 뿐이라 PARTIAL 자료를 다시 돌릴 길이 없었다.
자료 전체를 다시 돌리면 이미 만든 카드가 중복되므로 잃은 구간만 다시 뽑는다.
"""
from datetime import datetime, timezone
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.ingest import extract, job_repository, job_worker, pipeline
from app.ingest.pipeline import ExtractionOutcome, _extract_facts_all
from app.ingest.schemas import Evidence, ExtractedAssertion, ExtractionResult


def _assertion(ref: str) -> ExtractedAssertion:
    return ExtractedAssertion(
        local_ref=ref, original_assertion="원두 18g", subject="음료Z",
        attribute="원두량", value="18", unit="g", confidence=.9,
        evidence=Evidence(timestamp_sec=1))


SEGMENTS = [(f"구간{i} 본문", []) for i in range(1, 4)]


# ── reset_retryable_sources ─────────────────────────────────────────────

def _reset_conn(returned_ids):
    """실행된 UPDATE 마다 SQL 을 보고 돌려줄 source_id 를 고른다."""
    conn = AsyncMock()

    async def fetch(sql, *args):
        key = "PARTIAL" if "'PARTIAL'" in sql else "OTHER"
        return [{"source_id": i} for i in returned_ids.get(key, [])]

    conn.fetch = AsyncMock(side_effect=fetch)
    return conn


def _sql_of(conn, marker):
    return [c for c in conn.fetch.await_args_list if marker(c.args[0])]


@pytest.mark.asyncio
@pytest.mark.parametrize("include_no_result", [False, True])
async def test_reset_targets_partial_regardless_of_no_result_flag(include_no_result):
    conn = _reset_conn({"PARTIAL": [4], "OTHER": [3]})
    count = await job_repository.reset_retryable_sources(
        conn, 1, 2, include_no_result=include_no_result)

    assert count == 2
    partial_calls = _sql_of(conn, lambda s: "'PARTIAL'" in s)
    assert len(partial_calls) == 1
    # 매장·작업이 모두 걸린다
    assert partial_calls[0].args[1:3] == (1, 2)


@pytest.mark.asyncio
async def test_reset_partial_keeps_cards_and_lost_segments():
    conn = _reset_conn({"PARTIAL": [4]})
    await job_repository.reset_retryable_sources(conn, 1, 2, include_no_result=False)

    sql = _sql_of(conn, lambda s: "'PARTIAL'" in s)[0].args[0]
    assert "status = 'QUEUED'" in sql
    assert "error_code = null" in sql and "error_message = null" in sql
    # 이미 만든 카드와 잃은 구간 기록은 지운다면 재시도가 기댈 곳이 없다
    assert "card_count" not in sql
    assert "failed_segment_ids" not in sql
    assert "segments_total" not in sql
    assert "segments_failed" not in sql


@pytest.mark.asyncio
async def test_reset_failed_clears_segment_fields_for_full_rerun():
    conn = _reset_conn({"OTHER": [3]})
    await job_repository.reset_retryable_sources(conn, 1, 2, include_no_result=True)

    calls = _sql_of(conn, lambda s: "'PARTIAL'" not in s)
    assert len(calls) == 1
    sql, args = calls[0].args[0], calls[0].args[1:]
    assert "card_count = 0" in sql
    assert "segments_total = null" in sql
    assert "segments_failed = null" in sql
    assert "failed_segment_ids = null" in sql
    assert ["FAILED", "NO_RESULT"] in args


# ── _extract_facts_all(only_segments) ───────────────────────────────────

@pytest.mark.asyncio
async def test_only_segments_extracts_just_the_lost_segment():
    seen = []

    async def fake_extract_facts(**kw):
        seen.append(kw["text"])
        return NS(assertions=[_assertion("f1")], unresolved=[])

    with patch.object(extract, "extract_facts", side_effect=fake_extract_facts):
        outcome = await _extract_facts_all(
            source_id=1, source_type="VIDEO", text="", media=[],
            glossary=[], segments=SEGMENTS, only_segments={"seg2"})

    assert seen == ["구간2 본문"]
    assert [a.local_ref for a in outcome.assertions] == ["seg2:f1"]
    assert outcome.segments_total == 3
    assert outcome.segments_failed == 0


@pytest.mark.asyncio
async def test_only_segments_failing_again_reports_without_raising():
    async def fake_extract_facts(**kw):
        raise RuntimeError("모델 응답 없음")

    with patch.object(extract, "extract_facts", side_effect=fake_extract_facts):
        outcome = await _extract_facts_all(
            source_id=1, source_type="VIDEO", text="", media=[],
            glossary=[], segments=SEGMENTS, only_segments={"seg2"})

    assert outcome.assertions == []
    assert outcome.segments_total == 3
    assert outcome.segments_failed == 1
    assert outcome.failed_segment_ids == ["seg2"]


@pytest.mark.asyncio
async def test_full_run_with_every_segment_failing_still_raises():
    async def fake_extract_facts(**kw):
        raise RuntimeError("모델 응답 없음")

    with patch.object(extract, "extract_facts", side_effect=fake_extract_facts):
        with pytest.raises(RuntimeError):
            await _extract_facts_all(
                source_id=1, source_type="VIDEO", text="", media=[],
                glossary=[], segments=SEGMENTS)


# ── _record_segment_failures ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_zero_failures_overwrite_previous_lost_segments():
    conn = AsyncMock()
    outcome = ExtractionOutcome([], [], 3, 0, [])
    await pipeline._record_segment_failures(
        conn, store_id=1, job_id=5, source_id=7, outcome=outcome)

    conn.execute.assert_awaited_once()
    sql, *args = conn.execute.await_args.args
    assert "ingest_job_sources" in sql
    assert args[:3] == [1, 5, 7]
    assert args[3:] == [3, 0, None]


# ── process_source 구간 구성 불일치 ─────────────────────────────────────

class _Tx:
    async def __aenter__(self):
        return None

    async def __aexit__(self, *exc):
        return False


class _Lease:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, *exc):
        return False


class _Pool:
    def __init__(self):
        self.conn = AsyncMock()
        self.conn.transaction = MagicMock(side_effect=lambda: _Tx())
        self.conn.fetchval = AsyncMock(return_value=3)

    def acquire(self):
        return _Lease(self.conn)


async def _run_retry(tmp_path, *, segments, retry_segments, expected_total):
    from app.config import get_settings
    from app.ingest.schemas import ExtractedCard
    extract_calls = []

    async def fake_extract_facts(**kw):
        extract_calls.append(kw["text"])
        return NS(assertions=[_assertion("f1")], unresolved=[])

    src = {"source_id": 2, "store_id": 1, "source_type": "VIDEO",
           "file_url": "x", "content_hash": "h", "status": "PROCESSING"}
    persist = AsyncMock(return_value=1)
    set_status = AsyncMock()
    record = AsyncMock()
    pool = _Pool()
    prior = dict(version=1, phase='COMMITTED', ledger_ids={},
        layout_hash=pipeline.recovery.layout_hash(src, '본문', [], SEGMENTS, get_settings()),
        outcome=dict(failed_segment_ids=retry_segments, segments_total=expected_total))
    with patch.object(pipeline, "get_pool", return_value=pool), \
         patch.object(pipeline.recovery, 'load', AsyncMock(return_value=prior)), \
         patch.object(pipeline.recovery, 'replace', AsyncMock()), \
         patch.object(pipeline, "_preprocess",
                      AsyncMock(return_value=("본문", [], segments))), \
         patch.object(pipeline.repo, "get_source", AsyncMock(return_value=src)), \
         patch.object(pipeline.repo, "set_status", set_status), \
         patch.object(pipeline.repo, "enabled_categories",
                      AsyncMock(return_value={"기타": 1})), \
         patch.object(pipeline.repo, "glossary", AsyncMock(return_value=[])), \
         patch.object(pipeline.storage, "workdir", return_value=tmp_path / "w"), \
         patch.object(extract, "extract_facts", fake_extract_facts), \
         patch.object(pipeline, "assemble_assertions",
                      AsyncMock(return_value=ExtractionResult(cards=[ExtractedCard(
                          category_name='기타', title='합성', content='원두 18g', confidence=.9)], unresolved=[]))), \
         patch.object(pipeline, "_persist_ledger", AsyncMock(return_value={})), \
         patch.object(pipeline, "_record_segment_failures", record), \
         patch.object(pipeline, "_persist", persist):
        returned = await pipeline.process_source(
            1, 2, job_id=5, retry_segments=retry_segments,
            expected_segments_total=expected_total)
    return returned, extract_calls, persist, set_status, record


@pytest.mark.asyncio
@pytest.mark.parametrize("segments,retry,expected", [
    (SEGMENTS[:2], ["seg2"], 3),   # 구간 수가 바뀌었다
    (SEGMENTS, ["seg4"], 3),       # 요청 구간이 범위 밖이다
    ([], ["seg1"], 1),             # 구간 없는 자료
])
async def test_layout_mismatch_skips_extraction_and_keeps_cards(
        tmp_path, segments, retry, expected):
    returned, extract_calls, persist, set_status, record = await _run_retry(
        tmp_path, segments=segments, retry_segments=retry,
        expected_total=expected)

    assert returned == pipeline.PARTIAL_RETRY_UNAVAILABLE
    assert extract_calls == []
    persist.assert_not_awaited()
    # 잃은 구간 기록을 덮지 않는다 — 여전히 PARTIAL 이다
    record.assert_not_awaited()
    assert all(c.args[3] != "FAILED" for c in set_status.await_args_list)
    # 기존 카드가 남아 있으므로 자료는 끝난 상태로 돌린다
    assert set_status.await_args_list[-1].args[3] == "DONE"


@pytest.mark.asyncio
async def test_matching_layout_extracts_only_lost_segment_and_appends(tmp_path):
    returned, extract_calls, persist, set_status, record = await _run_retry(
        tmp_path, segments=SEGMENTS, retry_segments=["seg2"], expected_total=3)

    assert returned is None
    assert extract_calls == ["구간2 본문"]
    persist.assert_awaited_once()
    outcome = record.await_args.kwargs["outcome"]
    assert (outcome.segments_total, outcome.segments_failed) == (3, 0)
    assert set_status.await_args_list[-1].args[3] == "DONE"


# ── job_worker ─────────────────────────────────────────────────────────

STARTED_AT = datetime(2026, 9, 26, 3, 0, 0, 123000, tzinfo=timezone.utc)
STARTED_TAG = int(STARTED_AT.timestamp() * 1000)


def _worker_pool(queued_rows, *, source_status="DONE", card_count=3,
                 lost=None):
    conn = AsyncMock()
    fetchrows = {
        "claim": {"category_version": 1},
        "source": {"status": source_status, "error_message": None},
        "lost": lost or {"segments_total": 3, "segments_failed": 0},
    }

    async def fetchrow(sql, *args):
        if "update ingest_jobs" in sql:
            return fetchrows["claim"]
        if "from sources" in sql:
            return fetchrows["source"]
        return fetchrows["lost"]

    conn.fetchrow = AsyncMock(side_effect=fetchrow)
    conn.fetch = AsyncMock(return_value=queued_rows)

    async def fetchval(sql, *args):
        # 자료 시작 시각 — 실행 표지를 여기서 만든다
        if "returning started_at" in sql:
            return STARTED_AT
        return card_count

    conn.fetchval = AsyncMock(side_effect=fetchval)

    class Pool:
        def acquire(self):
            return _Lease(conn)

    return Pool(), conn


def _source_update(conn):
    for c in conn.execute.await_args_list:
        if "set status = $4, card_count = $5" in c.args[0]:
            return c.args
    raise AssertionError("자료 결과 UPDATE 가 없다")


@pytest.mark.asyncio
async def test_worker_retries_only_lost_segments():
    rows = [{"source_id": 3, "failed_segment_ids": ["seg2"], "segments_total": 3}]
    pool, conn = _worker_pool(rows)
    process = AsyncMock(return_value=None)
    with patch.object(job_worker, "get_pool", return_value=pool), \
         patch.object(job_worker.pipeline, "process_source", process), \
         patch.object(job_worker, "_refresh_job",
                      AsyncMock(return_value=("SUCCEEDED", 3))), \
         patch.object(job_worker, "create_ingest_completed_notification",
                      AsyncMock(return_value=None)):
        await job_worker.process_ingest_job(1, 2)

    process.assert_awaited_once()
    assert process.await_args.args == (1, 3)
    assert process.await_args.kwargs["job_id"] == 2
    assert process.await_args.kwargs["retry_segments"] == ["seg2"]
    assert process.await_args.kwargs["expected_segments_total"] == 3
    # 대기 자료를 읽을 때 잃은 구간도 함께 읽는다
    queued_sql = conn.fetch.await_args.args[0]
    assert "failed_segment_ids" in queued_sql and "segments_total" in queued_sql


@pytest.mark.asyncio
async def test_worker_full_run_keeps_existing_call():
    rows = [{"source_id": 3, "failed_segment_ids": None, "segments_total": None}]
    pool, _ = _worker_pool(rows)
    process = AsyncMock(return_value=None)
    with patch.object(job_worker, "get_pool", return_value=pool), \
         patch.object(job_worker.pipeline, "process_source", process), \
         patch.object(job_worker, "_refresh_job",
                      AsyncMock(return_value=("SUCCEEDED", 3))), \
         patch.object(job_worker, "create_ingest_completed_notification",
                      AsyncMock(return_value=None)):
        await job_worker.process_ingest_job(1, 2)

    process.assert_awaited_once_with(1, 3, job_id=2, run_tag=STARTED_TAG)


@pytest.mark.asyncio
async def test_worker_passes_run_tag_from_source_start_time():
    # 같은 작업을 다시 돌릴 때 원가 receipt 의 논리 호출 ID 가 겹치지 않게 한다 (C1)
    rows = [{"source_id": 3, "failed_segment_ids": ["seg2"], "segments_total": 3}]
    pool, conn = _worker_pool(rows)
    process = AsyncMock(return_value=None)
    with patch.object(job_worker, "get_pool", return_value=pool), \
         patch.object(job_worker.pipeline, "process_source", process), \
         patch.object(job_worker, "_refresh_job",
                      AsyncMock(return_value=("SUCCEEDED", 3))), \
         patch.object(job_worker, "create_ingest_completed_notification",
                      AsyncMock(return_value=None)):
        await job_worker.process_ingest_job(1, 2)

    assert process.await_args.kwargs["run_tag"] == STARTED_TAG
    start_sql = next(c for c in conn.fetchval.await_args_list
                     if "returning started_at" in c.args[0])
    assert "started_at = now()" in start_sql.args[0]
    assert start_sql.args[1:] == (1, 2, 3)


@pytest.mark.asyncio
async def test_worker_layout_mismatch_keeps_partial_with_its_cards():
    rows = [{"source_id": 3, "failed_segment_ids": ["seg2"], "segments_total": 3}]
    pool, conn = _worker_pool(
        rows, card_count=4, lost={"segments_total": 3, "segments_failed": 1})
    process = AsyncMock(return_value=pipeline.PARTIAL_RETRY_UNAVAILABLE)
    with patch.object(job_worker, "get_pool", return_value=pool), \
         patch.object(job_worker.pipeline, "process_source", process), \
         patch.object(job_worker, "_refresh_job",
                      AsyncMock(return_value=("PARTIAL", 4))), \
         patch.object(job_worker, "create_ingest_completed_notification",
                      AsyncMock(return_value=None)):
        await job_worker.process_ingest_job(1, 2)

    args = _source_update(conn)
    assert args[4:] == (
        "PARTIAL", 4, "PARTIAL_RETRY_UNAVAILABLE",
        "구간 구성이 바뀌어 잃은 구간만 다시 읽을 수 없습니다. 자료를 새로 올려 주세요.",
    )


# ── 재시도 중 예외 → 다음 재시도 (카드 중복 방지) ─────────────────────────

async def _run_worker(rows, *, source_status, card_count=4, source_error=None):
    pool, conn = _worker_pool(rows, card_count=card_count)
    conn.fetchrow.side_effect = None

    async def fetchrow(sql, *args):
        if "update ingest_jobs" in sql:
            return {"category_version": 1}
        if "from sources" in sql:
            return {"status": source_status, "error_message": source_error}
        return {"segments_total": 3, "segments_failed": 1}

    conn.fetchrow = AsyncMock(side_effect=fetchrow)
    process = AsyncMock(return_value=None)
    with patch.object(job_worker, "get_pool", return_value=pool), \
         patch.object(job_worker.pipeline, "process_source", process), \
         patch.object(job_worker, "_refresh_job",
                      AsyncMock(return_value=("PARTIAL", card_count))), \
         patch.object(job_worker, "create_ingest_completed_notification",
                      AsyncMock(return_value=None)):
        await job_worker.process_ingest_job(1, 2)
    return conn, process


def _segment_fields_untouched(conn):
    for c in conn.execute.await_args_list:
        sql = c.args[0]
        if "ingest_job_sources" in sql:
            for field in ("segments_total", "segments_failed", "failed_segment_ids"):
                assert field not in sql, sql


@pytest.mark.asyncio
async def test_failed_segment_retry_stays_partial_and_keeps_lost_segments():
    rows = [{"source_id": 3, "failed_segment_ids": ["seg2"], "segments_total": 3}]
    conn, _ = await _run_worker(
        rows, source_status="FAILED", source_error="RuntimeError: 다운로드 실패")

    args = _source_update(conn)
    assert args[4:6] == ("PARTIAL", 4)
    assert args[6] == "PARTIAL_RETRY_FAILED"
    assert args[7].startswith("잃은 구간을 다시 읽다가 실패했습니다. 다시 시도해 주세요.")
    assert "다운로드 실패" in args[7]
    _segment_fields_untouched(conn)


@pytest.mark.asyncio
async def test_full_run_failure_still_reports_failed():
    rows = [{"source_id": 3, "failed_segment_ids": None, "segments_total": None}]
    conn, _ = await _run_worker(
        rows, source_status="FAILED", card_count=0, source_error="RuntimeError: x")

    args = _source_update(conn)
    assert args[4:7] == ("FAILED", 0, "EXTRACTION_FAILED")
    assert args[7] == "RuntimeError: x"


@pytest.mark.asyncio
async def test_retry_failure_cycle_retries_only_lost_segments_again():
    # 1) 잃은 구간 재시도가 예외로 끝난다 → 작업 자료 행은 PARTIAL 로 남는다
    rows = [{"source_id": 3, "failed_segment_ids": ["seg2"], "segments_total": 3}]
    conn, _ = await _run_worker(rows, source_status="FAILED")
    written_status = _source_update(conn)[4]
    assert written_status == "PARTIAL"

    # 2) 재시도 초기화는 PARTIAL 경로를 탄다 — 카드 수·구간 기록을 지우지 않는다
    reset = _reset_conn({"PARTIAL": [3]} if written_status == "PARTIAL"
                        else {"OTHER": [3]})
    assert await job_repository.reset_retryable_sources(
        reset, 1, 2, include_no_result=False) == 1
    partial_sql = _sql_of(reset, lambda s: "'PARTIAL'" in s)[0].args[0]
    for field in ("card_count", "segments_total", "segments_failed",
                  "failed_segment_ids"):
        assert field not in partial_sql

    # 3) 다음 실행도 잃은 구간만 다시 읽는다 (전체 재실행 아님)
    _, process = await _run_worker(rows, source_status="DONE")
    assert process.await_args.kwargs["retry_segments"] == ["seg2"]
    assert process.await_args.kwargs["expected_segments_total"] == 3


# ── 같은 작업 재시도의 원가 receipt 충돌 (C1) ──────────────────────────

from app.usage.repository import UsageWriteError  # noqa: E402


class _UniqueLedger:
    """원장 unique (store_id, logical_call_id, attempt_no) 를 흉내 낸다.

    실제 start_attempt 처럼 모델 호출 **전에** 적고, 이미 있으면 UsageWriteError.
    """

    def __init__(self):
        self.keys: set[tuple] = set()

    def start(self, ctx):
        key = (ctx.store_id, ctx.logical_call_id, ctx.attempt_no)
        if key in self.keys:
            raise UsageWriteError(f"이미 기록된 시도다 (call={ctx.logical_call_id})")
        self.keys.add(key)


async def _run_with_ledger(tmp_path, ledger, *, run_tag, retry_segments=None,
                           fail_segments=()):
    """구간 3개 영상 자료를 한 번 처리한다. 추출·조립이 receipt 를 먼저 적는다."""
    extracted, assembled = [], []

    async def fake_extract_facts(**kw):
        ledger.start(kw["usage_context"])
        seg = kw["usage_context"].segment_id
        if seg in fail_segments:
            raise RuntimeError("모델 응답 없음")
        extracted.append(seg)
        return NS(assertions=[_assertion("f1")], unresolved=[])

    async def fake_assemble_cards(**kw):
        ledger.start(kw["usage_context"])
        assembled.append(len(kw["facts"]))
        return ExtractionResult(cards=[], unresolved=[])

    src = {"source_id": 2, "store_id": 1, "source_type": "VIDEO",
           "file_url": "x", "content_hash": "h", "status": "PROCESSING"}
    persist = AsyncMock(return_value=1)
    record = AsyncMock()
    set_status = AsyncMock()
    with patch.object(pipeline, "get_pool", return_value=_Pool()), \
         patch.object(pipeline, "_preprocess",
                      AsyncMock(return_value=("본문", [], SEGMENTS))), \
         patch.object(pipeline.repo, "get_source", AsyncMock(return_value=src)), \
         patch.object(pipeline.repo, "set_status", set_status), \
         patch.object(pipeline.repo, "enabled_categories",
                      AsyncMock(return_value={"기타": 1})), \
         patch.object(pipeline.repo, "glossary", AsyncMock(return_value=[])), \
         patch.object(pipeline.storage, "workdir", return_value=tmp_path / "w"), \
         patch.object(extract, "extract_facts", fake_extract_facts), \
         patch.object(extract, "assemble_cards", fake_assemble_cards), \
         patch.object(pipeline, "_persist_ledger", AsyncMock(return_value={})), \
         patch.object(pipeline, "_record_segment_failures", record), \
         patch.object(pipeline, "_persist", persist):
        await pipeline.process_source(
            1, 2, job_id=5, run_tag=run_tag, retry_segments=retry_segments,
            expected_segments_total=3 if retry_segments else None)
    return NS(extracted=extracted, assembled=assembled, persist=persist,
              outcome=record.await_args.kwargs["outcome"] if record.await_args else None,
              last_status=set_status.await_args_list[-1].args[3])


@pytest.mark.asyncio
async def test_same_job_retry_with_new_run_tag_does_not_collide(tmp_path):
    ledger = _UniqueLedger()
    first = await _run_with_ledger(
        tmp_path, ledger, run_tag=1_790_000_000_000, fail_segments={"seg2"})
    assert first.outcome.failed_segment_ids == ["seg2"]

    # 같은 작업·자료를 다시 돌린다. 실행 표지가 달라 receipt 가 겹치지 않는다
    retry = await _run_with_ledger(
        tmp_path, ledger, run_tag=1_790_000_060_000, retry_segments=["seg2"])

    assert retry.extracted == ["seg2"]
    assert retry.assembled == [1]
    retry.persist.assert_awaited_once()
    assert (retry.outcome.segments_failed, retry.outcome.failed_segment_ids) == (0, [])
    assert retry.last_status == "DONE"


@pytest.mark.asyncio
async def test_same_run_tag_twice_collides(tmp_path):
    # 대역 원장이 정말 unique 를 강제하는지 — 같은 표지면 재시도 구간이 receipt 에서 죽는다
    ledger = _UniqueLedger()
    await _run_with_ledger(
        tmp_path, ledger, run_tag=1_790_000_000_000, fail_segments={"seg2"})
    retry = await _run_with_ledger(
        tmp_path, ledger, run_tag=1_790_000_000_000, retry_segments=["seg2"])

    assert retry.extracted == []
    assert retry.outcome.failed_segment_ids == ["seg2"]


def test_run_tag_scopes_logical_call_id_within_80_chars():
    big = 999_999_999
    ctx = pipeline._usage_context(
        big, big, big, "ASSEMBLE", "REGISTRATION", "PRODUCT", None,
        segment_id="seg99", run_tag=9_999_999_999_999)
    assert ctx.logical_call_id.startswith(f"job{big}r9999999999999:")
    assert len(ctx.logical_call_id) <= 80
    # 표지가 없으면 기존 범위 그대로다 (평가 스크립트 등)
    assert pipeline._usage_context(
        1, 2, 3, "EXTRACT", "REGISTRATION", "PRODUCT", None
    ).logical_call_id == "job3:src2:extract"
    assert pipeline._usage_context(
        1, 2, 3, "EXTRACT", "REGISTRATION", "EVALUATION", 7, run_tag=5
    ).logical_call_id == "run7:src2:extract"
