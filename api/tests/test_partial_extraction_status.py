"""구간 일부가 실패했을 때 그 사실이 위로 전달되는지 검증한다.

10구간 중 3구간이 실패해도 성공분만 합쳐서 `SUCCEEDED` 로 끝나면
점주는 자료가 전부 처리됐다고 믿는다. 부분 실패는 부분 실패로 보여야 한다.
"""
from types import SimpleNamespace as NS
from unittest.mock import patch

import pytest

from app.ingest import extract
from app.ingest.job_worker import final_job_status
from app.ingest.pipeline import _extract_facts_all
from app.ingest.schemas import Evidence, ExtractedAssertion


def _assertion(ref: str) -> ExtractedAssertion:
    return ExtractedAssertion(
        local_ref=ref, original_assertion="원두 18g", subject="음료Z",
        attribute="원두량", value="18", unit="g", confidence=.9,
        evidence=Evidence(timestamp_sec=1))


def _ok(ref: str):
    return NS(assertions=[_assertion(ref)], unresolved=[])


async def _extract_three_segments(failing: set[int]):
    """3구간짜리 자료를 돌리되 지정한 구간만 실패시킨다."""
    calls = {"n": 0}

    async def fake_extract_facts(**kw):
        calls["n"] += 1
        if calls["n"] in failing:
            raise RuntimeError("모델 응답 없음")
        return _ok(f"f{calls['n']}")

    segments = [(f"구간{i} 본문", []) for i in range(1, 4)]
    with patch.object(extract, "extract_facts", side_effect=fake_extract_facts):
        return await _extract_facts_all(
            source_id=1, source_type="VIDEO", text="", media=[],
            glossary=[], segments=segments)


@pytest.mark.asyncio
async def test_partial_segment_failure_is_reported_not_swallowed():
    # 3구간 중 1구간 실패 — 성공한 2건을 돌려주되 실패 사실도 함께 알린다
    outcome = await _extract_three_segments(failing={2})
    assert len(outcome.assertions) == 2
    assert outcome.segments_total == 3
    assert outcome.segments_failed == 1


@pytest.mark.asyncio
async def test_all_segments_succeeding_reports_no_failure():
    outcome = await _extract_three_segments(failing=set())
    assert outcome.segments_total == 3
    assert outcome.segments_failed == 0


@pytest.mark.asyncio
async def test_failed_segment_ids_are_named_for_retry():
    # 어느 구간이 실패했는지 알아야 그 구간만 다시 돌릴 수 있다
    outcome = await _extract_three_segments(failing={1, 3})
    assert outcome.failed_segment_ids == ["seg1", "seg3"]


@pytest.mark.asyncio
async def test_unsegmented_source_reports_a_single_segment():
    # 구간이 없는 자료도 같은 계약으로 답한다
    async def fake_extract_facts(**kw):
        return _ok("f1")

    with patch.object(extract, "extract_facts", side_effect=fake_extract_facts):
        outcome = await _extract_facts_all(
            source_id=1, source_type="VOICE", text="본문", media=[],
            glossary=[], segments=[])
    assert outcome.segments_total == 1 and outcome.segments_failed == 0


def test_source_with_failed_segments_is_partial_not_succeeded():
    # 카드가 나왔어도 버려진 구간이 있으면 성공으로 보고하지 않는다
    assert final_job_status(total=1, failed=0, cards=3,
                            partial=True) == "PARTIAL"


def test_source_with_no_failed_segments_stays_succeeded():
    assert final_job_status(total=1, failed=0, cards=3,
                            partial=False) == "SUCCEEDED"


class _RecordingConn:
    """부분 실패 기록이 실제로 어떤 질의로 나가는지 붙잡는다."""

    def __init__(self):
        self.calls: list[tuple] = []

    async def execute(self, query: str, *args):
        self.calls.append((query, args))


@pytest.mark.asyncio
async def test_lost_segments_are_recorded_on_the_job_source_row():
    from app.ingest.pipeline import ExtractionOutcome, _record_segment_failures

    conn = _RecordingConn()
    outcome = ExtractionOutcome([], [], 3, 1, ["seg2"])
    await _record_segment_failures(conn, store_id=1, job_id=5, source_id=7,
                                   outcome=outcome)
    assert len(conn.calls) == 1
    query, args = conn.calls[0]
    assert "ingest_job_sources" in query
    assert 1 in args and 5 in args and 7 in args  # 매장·작업·자료가 모두 걸린다
    assert 1 in args and "seg2" in str(args)      # 잃은 구간 수와 이름


@pytest.mark.asyncio
async def test_nothing_is_recorded_when_no_segment_was_lost():
    from app.ingest.pipeline import ExtractionOutcome, _record_segment_failures

    conn = _RecordingConn()
    outcome = ExtractionOutcome([], [], 3, 0, [])
    await _record_segment_failures(conn, store_id=1, job_id=5, source_id=7,
                                   outcome=outcome)
    assert conn.calls == []


@pytest.mark.asyncio
async def test_segment_failures_outside_a_job_are_not_recorded():
    # job 없이 도는 레거시 경로에는 기록할 행이 없다
    from app.ingest.pipeline import ExtractionOutcome, _record_segment_failures

    conn = _RecordingConn()
    outcome = ExtractionOutcome([], [], 3, 2, ["seg1", "seg2"])
    await _record_segment_failures(conn, store_id=1, job_id=None, source_id=7,
                                   outcome=outcome)
    assert conn.calls == []
