"""PARTIAL 자료가 있는 작업의 상세 조회·집계가 실패하지 않는지 검증한다.

F01: IngestJobSourceStatus 에 PARTIAL 이 없어 _job_detail 이 ValidationError 로 죽는다.
F02: _refresh_job 이 PARTIAL 자료 수를 세지 않아 작업 전체가 SUCCEEDED 로 잘못 적힌다.
"""
from unittest.mock import AsyncMock, patch

import pytest

from app.ingest import job_repository
from app.ingest.job_worker import _refresh_job
from app.ingest.router import _job_detail


def _job_row(**overrides):
    row = dict(
        job_id=2, title=None, status="SUCCEEDED", category_version=1,
        total_source_count=1, success_source_count=0, failed_source_count=0,
        card_count=3,
    )
    row.update(overrides)
    return row


@pytest.mark.asyncio
async def test_job_detail_with_partial_source_does_not_raise():
    conn = AsyncMock()
    job = _job_row()
    source = dict(source_id=3, filename="synthetic.pdf", status="PARTIAL",
                  card_count=3, error_code="PARTIAL_EXTRACTION",
                  error_message="synthetic failure")
    with patch.object(job_repository, "get_job", AsyncMock(return_value=job)), \
         patch.object(job_repository, "get_job_sources", AsyncMock(return_value=[source])):
        detail = await _job_detail(conn, 1, 2)

    assert detail.sources[0].status == "PARTIAL"
    assert detail.counts.partial == 1


@pytest.mark.asyncio
async def test_job_detail_counts_only_partial_sources():
    conn = AsyncMock()
    job = _job_row(total_source_count=2)
    sources = [
        dict(source_id=3, filename="a.pdf", status="SUCCEEDED", card_count=2,
             error_code=None, error_message=None),
        dict(source_id=4, filename="b.pdf", status="PARTIAL", card_count=1,
             error_code="PARTIAL_EXTRACTION", error_message="synthetic failure"),
    ]
    with patch.object(job_repository, "get_job", AsyncMock(return_value=job)), \
         patch.object(job_repository, "get_job_sources", AsyncMock(return_value=sources)):
        detail = await _job_detail(conn, 1, 2)

    assert detail.counts.partial == 1


@pytest.mark.asyncio
async def test_refresh_job_with_partial_source_reports_partial_status():
    conn = AsyncMock()
    conn.fetchrow.return_value = {
        "total": 1, "succeeded": 0, "failed": 0, "no_result": 0, "partial": 1,
        "cards": 3,
    }
    status, cards = await _refresh_job(conn, 1, 2, final=True)

    assert (status, cards) == ("PARTIAL", 3)
    executed_status = conn.execute.call_args.args[3]
    assert executed_status == "PARTIAL"


@pytest.mark.asyncio
async def test_refresh_job_without_partial_source_reports_succeeded():
    conn = AsyncMock()
    conn.fetchrow.return_value = {
        "total": 1, "succeeded": 1, "failed": 0, "no_result": 0, "partial": 0,
        "cards": 3,
    }
    status, cards = await _refresh_job(conn, 1, 2, final=True)

    assert (status, cards) == ("SUCCEEDED", 3)


@pytest.mark.asyncio
async def test_refresh_job_not_final_reports_extracting():
    conn = AsyncMock()
    conn.fetchrow.return_value = {
        "total": 1, "succeeded": 0, "failed": 0, "no_result": 0, "partial": 1,
        "cards": 0,
    }
    status, _ = await _refresh_job(conn, 1, 2, final=False)

    assert status == "EXTRACTING"


@pytest.mark.asyncio
async def test_refresh_job_aggregation_sql_counts_partial_sources():
    conn = AsyncMock()
    conn.fetchrow.return_value = {
        "total": 1, "succeeded": 0, "failed": 0, "no_result": 0, "partial": 0,
        "cards": 0,
    }
    await _refresh_job(conn, 1, 2, final=False)

    sql = conn.fetchrow.call_args.args[0]
    assert "status = 'PARTIAL'" in sql
