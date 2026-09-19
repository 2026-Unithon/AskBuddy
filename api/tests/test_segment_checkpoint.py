"""구간을 뽑는 즉시 원장에 적는지 검증한다 (W1 checkpoint).

전부 끝난 뒤에 한 번에 적으면, 8번째 구간에서 프로세스가 죽을 때 앞 7구간도
같이 사라진다. 모델 호출은 비싸고 느리다. 이미 뽑은 것은 지켜야 한다.
"""
from types import SimpleNamespace as NS
from unittest.mock import patch

import pytest

from app.ingest import extract
from app.ingest.pipeline import _extract_facts_all
from app.ingest.schemas import Evidence, ExtractedAssertion


def _assertion(ref: str) -> ExtractedAssertion:
    return ExtractedAssertion(
        local_ref=ref, original_assertion="원두 18g", subject="음료Z",
        attribute="원두량", value="18", unit="g", confidence=.9,
        evidence=Evidence(timestamp_sec=1))


async def _run(*, segments: int, failing: set[int] = frozenset(),
               checkpoint=None, crash_after: int | None = None):
    """구간별 추출을 돌리되 지정한 구간을 실패시키거나 도중에 터뜨린다."""
    calls = {"n": 0}

    async def fake_extract_facts(**kw):
        calls["n"] += 1
        if crash_after is not None and calls["n"] > crash_after:
            raise KeyboardInterrupt("프로세스가 죽었다")
        if calls["n"] in failing:
            raise RuntimeError("모델 응답 없음")
        return NS(assertions=[_assertion(f"f{calls['n']}")], unresolved=[])

    segs = [(f"구간{i} 본문", []) for i in range(1, segments + 1)]
    with patch.object(extract, "extract_facts", side_effect=fake_extract_facts):
        return await _extract_facts_all(
            source_id=1, source_type="VIDEO", text="", media=[],
            glossary=[], segments=segs, checkpoint=checkpoint)


@pytest.mark.asyncio
async def test_each_segment_is_checkpointed_as_soon_as_it_is_extracted():
    saved = []

    async def checkpoint(assertions, segment_id):
        saved.append(segment_id)

    await _run(segments=3, checkpoint=checkpoint)
    # 끝나고 한 번이 아니라 구간마다 한 번씩
    assert saved == ["seg1", "seg2", "seg3"]


@pytest.mark.asyncio
async def test_checkpoint_receives_only_that_segments_facts():
    batches = []

    async def checkpoint(assertions, segment_id):
        batches.append([a.local_ref for a in assertions])

    await _run(segments=3, checkpoint=checkpoint)
    assert batches == [["seg1:f1"], ["seg2:f2"], ["seg3:f3"]]


@pytest.mark.asyncio
async def test_a_crash_midway_keeps_the_segments_already_checkpointed():
    saved = []

    async def checkpoint(assertions, segment_id):
        saved.extend(a.local_ref for a in assertions)

    # 3구간을 돌리다 2구간까지 저장한 뒤 프로세스가 죽는다
    with pytest.raises(KeyboardInterrupt):
        await _run(segments=3, crash_after=2, checkpoint=checkpoint)
    assert saved == ["seg1:f1", "seg2:f2"]


@pytest.mark.asyncio
async def test_failed_segments_are_not_checkpointed():
    saved = []

    async def checkpoint(assertions, segment_id):
        saved.append(segment_id)

    await _run(segments=3, failing={2}, checkpoint=checkpoint)
    assert saved == ["seg1", "seg3"]


@pytest.mark.asyncio
async def test_a_segment_whose_ledger_write_fails_counts_as_lost():
    # 뽑았어도 적지 못했으면 그 구간은 잃은 것이다. 성공으로 세지 않는다
    async def checkpoint(assertions, segment_id):
        if segment_id == "seg2":
            raise RuntimeError("원장 저장 실패")

    outcome = await _run(segments=3, checkpoint=checkpoint)
    assert outcome.segments_failed == 1
    assert outcome.failed_segment_ids == ["seg2"]
    assert [a.local_ref for a in outcome.assertions] == ["seg1:f1", "seg3:f3"]


@pytest.mark.asyncio
async def test_unsegmented_source_is_checkpointed_too():
    saved = []

    async def checkpoint(assertions, segment_id):
        saved.append((segment_id, [a.local_ref for a in assertions]))

    async def fake_extract_facts(**kw):
        return NS(assertions=[_assertion("f1")], unresolved=[])

    with patch.object(extract, "extract_facts", side_effect=fake_extract_facts):
        await _extract_facts_all(source_id=1, source_type="VOICE", text="본문",
                                 media=[], glossary=[], segments=[],
                                 checkpoint=checkpoint)
    assert saved == [(None, ["f1"])]


@pytest.mark.asyncio
async def test_extraction_still_works_without_a_checkpoint():
    outcome = await _run(segments=2)
    assert len(outcome.assertions) == 2 and outcome.segments_failed == 0
