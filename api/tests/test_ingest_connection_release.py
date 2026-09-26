"""자료 처리가 외부 호출(다운로드·추출·조립) 동안 DB 연결을 쥐지 않는지 검증한다.

원가 receipt 는 **별도 연결**을 잡는다. 작업이 연결 하나를 모델 호출 내내 쥐고
있으면 작은 풀에서 receipt 가 연결을 못 얻어 작업 전체가 멈춘다.
"""
import asyncio
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.ingest import extract, pipeline
from app.ingest.schemas import ExtractionResult


class _Tx:
    async def __aenter__(self):
        return None

    async def __aexit__(self, *exc):
        return False


def _conn():
    conn = AsyncMock()
    conn.transaction = MagicMock(side_effect=lambda: _Tx())
    conn.fetchval = AsyncMock(return_value=3)
    return conn


class _Lease:
    def __init__(self, pool):
        self.pool = pool

    async def __aenter__(self):
        if self.pool.sem is not None:
            await self.pool.sem.acquire()
        self.pool.held += 1
        return self.pool.conn

    async def __aexit__(self, *exc):
        self.pool.held -= 1
        if self.pool.sem is not None:
            self.pool.sem.release()
        return False


class _Pool:
    """지금 잡힌 연결 수를 센다. size 를 주면 그만큼만 빌려준다."""

    def __init__(self, size: int | None = None):
        self.held = 0
        self.conn = _conn()
        self.sem = asyncio.Semaphore(size) if size else None

    def acquire(self):
        return _Lease(self)


def _row(status: str = "PROCESSING"):
    return {"source_id": 2, "store_id": 1, "source_type": "KAKAO",
            "file_url": "x", "content_hash": "h", "status": status}


async def _run(pool, tmp_path, *, get_source=None, extract_hook=None,
               job_id=None):
    """KAKAO 자료 하나를 대역으로 처리하고, 각 외부 호출 시점의 held 를 모은다."""
    seen: dict[str, list[int]] = {}
    txt = tmp_path / "대화.txt"
    txt.write_text("대화", encoding="utf-8")

    def note(stage):
        seen.setdefault(stage, []).append(pool.held)

    async def fake_download(source_id, url):
        note("download")
        return txt

    async def fake_extract_facts(**kw):
        note("extract")
        if extract_hook is not None:
            await extract_hook()
        return NS(assertions=[], unresolved=[])

    async def fake_assemble(**kw):
        note("assemble")
        return ExtractionResult(cards=[], unresolved=[])

    async def fake_ledger(*a, **kw):
        note("checkpoint")
        return {}

    persist = AsyncMock(return_value=0)
    set_status = AsyncMock()
    settings = NS(ingest_mode="real", video_segment_sec=60, frame_interval_sec=3,
                  video_max_frames_to_model=20, video_input_mode='frames', pdf_input_mode='HYBRID')
    get_source = get_source or AsyncMock(return_value=_row())

    with patch.object(pipeline, "get_pool", return_value=pool), \
         patch.object(pipeline.recovery, 'load', AsyncMock(return_value=None)), \
         patch.object(pipeline.recovery, 'replace', AsyncMock()), \
         patch("app.config.get_settings", return_value=settings), \
         patch.object(pipeline.repo, "get_source", get_source), \
         patch.object(pipeline.repo, "set_status", set_status), \
         patch.object(pipeline.repo, "get_kakao", AsyncMock(return_value={"kakao_id": 1})), \
         patch.object(pipeline.repo, "update_kakao_result", AsyncMock()), \
         patch.object(pipeline.repo, "enabled_categories",
                      AsyncMock(return_value={"기타": 1})), \
         patch.object(pipeline.repo, "glossary", AsyncMock(return_value=[])), \
         patch.object(pipeline.storage, "download", fake_download), \
         patch.object(pipeline.storage, "workdir", return_value=tmp_path / "w"), \
         patch.object(pipeline.kakao, "parse", return_value={
             "room_name": None, "message_count": 1, "participants": [],
             "period_start": None, "period_end": None, "parsed_text": "대화"}), \
         patch.object(extract, "extract_facts", fake_extract_facts), \
         patch.object(pipeline, "assemble_assertions", fake_assemble), \
         patch.object(pipeline, "_persist_ledger", fake_ledger), \
         patch.object(pipeline, "_persist", persist):
        await pipeline.process_source(1, 2, job_id=job_id)
    return seen, persist, set_status


@pytest.mark.asyncio
async def test_external_stages_run_without_a_held_connection(tmp_path):
    pool = _Pool()
    seen, persist, set_status = await _run(pool, tmp_path, job_id=5)

    assert seen["download"] == [0]
    assert seen["extract"] == [0]
    assert seen["assemble"] == [0]
    # checkpoint 는 원장 저장만큼 짧게 잡는다
    assert seen["checkpoint"] == [1]
    persist.assert_awaited_once()
    assert set_status.await_args_list[-1].args[3] == "DONE"
    assert pool.held == 0


@pytest.mark.asyncio
async def test_single_connection_pool_does_not_starve_receipt_writer(tmp_path):
    # 추출 중 receipt 기록이 연결을 하나 더 잡는다. 작업이 쥐고 있으면 교착이다
    pool = _Pool(size=1)

    async def receipt():
        async with pool.acquire():
            pass

    seen, persist, set_status = await asyncio.wait_for(
        _run(pool, tmp_path, extract_hook=receipt, job_id=5), timeout=2)
    persist.assert_awaited_once()
    assert set_status.await_args_list[-1].args[3] == "DONE"


@pytest.mark.asyncio
@pytest.mark.parametrize("late_row", [_row("FAILED"), None])
async def test_changed_source_status_blocks_persist(tmp_path, late_row):
    # 처리 중 자료가 다른 경로로 끝났으면 저장하지 않고 FAILED 로 멈춘다
    get_source = AsyncMock(side_effect=[_row(), late_row])
    pool = _Pool()
    _, persist, set_status = await _run(
        pool, tmp_path, get_source=get_source, job_id=5)

    persist.assert_not_awaited()
    last = set_status.await_args_list[-1]
    assert last.args[3] == "FAILED"
    assert "처리 중 바뀌었다" in last.kwargs["error_message"]
    assert pool.held == 0


# ── 저장·구간 기록·DONE 은 한 트랜잭션이다 (I1) ─────────────────────────

class _TrackedTx:
    """열림 여부와 빠져나갈 때의 예외를 기록한다."""

    def __init__(self, log):
        self.log = log

    async def __aenter__(self):
        self.log["open"] = True
        return None

    async def __aexit__(self, exc_type, exc, tb):
        self.log["open"] = False
        self.log["exits"].append(exc_type)
        return False


def _tracked_pool():
    pool = _Pool()
    log = {"open": False, "exits": []}
    pool.conn.transaction = MagicMock(side_effect=lambda: _TrackedTx(log))
    return pool, log


async def _run_tracked(tmp_path, *, record_error=None):
    pool, log = _tracked_pool()
    during: dict[str, list[bool]] = {}

    def note(name):
        during.setdefault(name, []).append(log["open"])

    async def persist(*a, **kw):
        note("persist")
        return 1

    async def record(*a, **kw):
        note("record")
        if record_error is not None:
            raise record_error

    async def set_status(conn, store_id, source_id, status, **kw):
        note(status)

    with patch.object(pipeline, "_persist", persist), \
         patch.object(pipeline, "_record_segment_failures", record), \
         patch.object(pipeline.repo, "set_status", set_status):
        await _run_inner(pool, tmp_path, job_id=5)
    return during, log


async def _run_inner(pool, tmp_path, *, job_id):
    txt = tmp_path / "대화.txt"
    txt.write_text("대화", encoding="utf-8")

    async def fake_download(source_id, url):
        return txt

    async def fake_extract_facts(**kw):
        return NS(assertions=[], unresolved=[])

    async def fake_assemble(**kw):
        return ExtractionResult(cards=[], unresolved=[])

    settings = NS(ingest_mode="real", video_segment_sec=60, frame_interval_sec=3,
                  video_max_frames_to_model=20, video_input_mode='frames', pdf_input_mode='HYBRID')

    with patch("app.config.get_settings", return_value=settings), \
         patch.object(pipeline, "get_pool", return_value=pool), \
         patch.object(pipeline.recovery, 'load', AsyncMock(return_value=None)), \
         patch.object(pipeline.recovery, 'replace', AsyncMock()), \
         patch.object(pipeline.repo, "get_source", AsyncMock(return_value=_row())), \
         patch.object(pipeline.repo, "get_kakao", AsyncMock(return_value={"kakao_id": 1})), \
         patch.object(pipeline.repo, "update_kakao_result", AsyncMock()), \
         patch.object(pipeline.repo, "enabled_categories",
                      AsyncMock(return_value={"기타": 1})), \
         patch.object(pipeline.repo, "glossary", AsyncMock(return_value=[])), \
         patch.object(pipeline.storage, "download", fake_download), \
         patch.object(pipeline.storage, "workdir", return_value=tmp_path / "w"), \
         patch.object(pipeline.kakao, "parse", return_value={
             "room_name": None, "message_count": 1, "participants": [],
             "period_start": None, "period_end": None, "parsed_text": "대화"}), \
         patch.object(extract, "extract_facts", fake_extract_facts), \
         patch.object(pipeline, "assemble_assertions", fake_assemble), \
         patch.object(pipeline, "_persist_ledger", AsyncMock(return_value={})):
        await pipeline.process_source(1, 2, job_id=job_id)


@pytest.mark.asyncio
async def test_persist_segment_record_and_done_share_one_transaction(tmp_path):
    during, log = await _run_tracked(tmp_path)

    assert during["persist"] == [True]
    assert during["record"] == [True]
    assert during["DONE"] == [True]
    assert log["open"] is False


@pytest.mark.asyncio
async def test_segment_record_failure_rolls_back_persisted_cards(tmp_path):
    # 구간 기록이 죽으면 카드 저장도 함께 되돌린다. 커밋된 카드가 남으면
    # 다음 재시도가 같은 구간을 또 뽑아 카드가 겹친다
    during, log = await _run_tracked(
        tmp_path, record_error=RuntimeError("연결 끊김"))

    assert during["persist"] == [True]
    assert during["record"] == [True]
    assert "DONE" not in during
    # 저장이 든 트랜잭션이 예외를 안고 빠져나갔다 (= 롤백)
    assert RuntimeError in log["exits"]
    assert during["FAILED"] == [False]
