"""Phase B 추가 S1 — 한 작업의 판정 없는 자료를 묶어 분류 1회. 실패해도 작업은 이어간다."""
import asyncio
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

import pytest

from app.config import Settings
from app.ingest import job_worker
from app.ingest.intake import route
from app.ingest.intake.decide import IntakeClassificationError
from app.ingest.intake.ir import Candidate, Locator, ProbeResult
from tests.test_w3a_pipeline_wiring import _worker


def _probe(chars, images=0):
    imgs = tuple(f"/tmp/i{i}.jpg" for i in range(images))
    return ProbeResult("DOC_TEXT", (Candidate("c1", Locator("PAGE", "1", "1"), "가" * chars,
                                              imgs),), complete=True)


def test_bundle_chunks_respects_limits_in_order():
    items = [(1, _probe(5000), ()), (2, _probe(5000), ()), (3, _probe(5000), ()),
             (4, _probe(10), ())]
    chunks = route.bundle_chunks(items, max_sources=8, max_chars=12000, max_images=12, max_candidates=24)
    assert [[i[0] for i in c] for c in chunks] == [[1, 2], [3, 4]]
    chunks = route.bundle_chunks(items, max_sources=2, max_chars=10**9, max_images=12, max_candidates=24)
    assert [[i[0] for i in c] for c in chunks] == [[1, 2], [3, 4]]


def test_bundle_chunks_respects_image_limit():
    items = [(1, _probe(10, images=7), ()), (2, _probe(10, images=7), ()),
             (3, _probe(10, images=5), ())]
    chunks = route.bundle_chunks(items, max_sources=8, max_chars=12000, max_images=12, max_candidates=24)
    assert [[i[0] for i in c] for c in chunks] == [[1], [2, 3]]


def _probe_n(n):
    return ProbeResult("DOC_TEXT", tuple(Candidate(f"c{k}", Locator("PAGE", str(k), str(k)), "가")
                                         for k in range(1, n + 1)), complete=True)


def test_bundle_chunks_respects_candidate_limit():
    # 최종 검토 I-3 — 표본 후보가 많으면 묶음 분류 출력이 잘린다. 후보 수 상한으로도 나눈다
    items = [(1, _probe_n(12), ()), (2, _probe_n(12), ()), (3, _probe_n(5), ())]
    chunks = route.bundle_chunks(items, max_sources=8, max_chars=12000, max_images=12,
                                 max_candidates=24)
    assert [[i[0] for i in c] for c in chunks] == [[1, 2], [3]]
    chunks = route.bundle_chunks(items, max_sources=8, max_chars=12000, max_images=12,
                                 max_candidates=20)
    assert [[i[0] for i in c] for c in chunks] == [[1], [2, 3]]


def test_route_job_bundle_passes_candidate_setting():
    seen = {}
    real = route.bundle_chunks

    def spy(items, **kw):
        seen.update(kw)
        return real(items, **kw)

    with patch.object(route, "bundle_chunks", side_effect=spy):
        _run([11, 12], intake_bundle_max_candidates=5)
    assert seen["max_candidates"] == 5


class _Lease:
    async def __aenter__(self):
        return AsyncMock()

    async def __aexit__(self, *exc):
        return False


class _Pool:
    def acquire(self):
        return _Lease()


BASE = (7, 3, "REGISTRATION", "PRODUCT", None, 42)


def _run(source_ids, *, stored=(), probe_fail=(), bundle_error=None, types=None,
         probed=None, **settings):
    calls = []
    types = types or {}

    async def latest(conn, store_id, sid):
        return object() if sid in stored else None

    async def get_source(conn, store_id, sid):
        return {"source_id": sid, "store_id": store_id,
                "source_type": types.get(sid, "SCAN"),
                "file_url": f"sources/7/scan/{sid}.docx"}

    async def probe(pool, store_id, src, **kw):
        if probed is not None:
            probed.append(src["source_id"])
        if src["source_id"] in probe_fail:
            raise RuntimeError("훑기 실패")
        return _probe(10)

    async def bundle(pool, store_id, items, **kw):
        calls.append(([i[0] for i in items], kw["ctx"]))
        if bundle_error:
            raise bundle_error
        return {i[0]: f"route{i[0]}" for i in items}

    s = Settings(_env_file=None).model_copy(update=settings)
    caches = {}
    with patch.object(route.records, "latest_decision", side_effect=latest), \
         patch.object(route.records, "source_owner_hints", AsyncMock(return_value=())), \
         patch.object(route.repo, "get_source", side_effect=get_source), \
         patch.object(route, "probe_source", side_effect=probe), \
         patch.object(route, "_classify_bundle", side_effect=bundle), \
         patch.object(route, "get_settings", return_value=s):
        out = asyncio.run(route.route_job_bundle(_Pool(), 7, job_id=3, source_ids=source_ids,
                                                 usage_sink=None, usage_base=BASE,
                                                 caches=caches))
    return out, calls, caches


def test_three_new_sources_one_call():
    out, calls, caches = _run([11, 12, 13])
    assert [c[0] for c in calls] == [[11, 12, 13]]
    assert calls[0][1].stage == "CLASSIFY" and calls[0][1].logical_call_id.endswith(":bundle1")
    assert set(out) == {11, 12, 13} and set(caches) == {11, 12, 13}


def test_single_pending_source_is_left_alone():
    out, calls, _ = _run([11, 12], stored={12})
    assert calls == [] and out == {}


def test_probe_failure_drops_only_that_source():
    out, calls, _ = _run([11, 12, 13], probe_fail={12})
    assert [c[0] for c in calls] == [[11, 13]]


def test_probe_failure_leaving_one_source_does_not_bundle():
    out, calls, _ = _run([11, 12], probe_fail={12})
    assert calls == [] and out == {}


def test_bundle_failure_keeps_job_going():
    # Review Focus 1 — 묶음 실패는 예외로 올라오지 않고 판정 없이 둔다
    out, calls, _ = _run([11, 12], bundle_error=IntakeClassificationError("JSON"))
    assert out == {} and len(calls) == 1


def test_media_sources_stay_out_of_bundle():
    # 최종 검토 I-2·S4 — 음성·영상은 묶음 훑기(다운로드·STT)를 하지 않고 지금처럼 따로 간다
    probed = []
    out, calls, caches = _run([11, 12, 13], types={12: "VOICE"}, probed=probed)
    assert [c[0] for c in calls] == [[11, 13]]
    assert probed == [11, 13] and 12 not in caches and set(out) == {11, 13}


def test_media_leaving_one_source_does_not_bundle_or_probe():
    probed = []
    out, calls, _ = _run([11, 12], types={12: "VIDEO"}, probed=probed)
    assert calls == [] and out == {} and probed == []


def test_disabled_does_nothing():
    out, calls, _ = _run([11, 12, 13], intake_bundle_enabled=False)
    assert out == {} and calls == []


# ── job_worker 연결 ──────────────────────────────────────────────────────

async def _run_job(rows, *, bundle):
    pool, conn = _worker(linked_cards=1, pending=0)
    conn.fetch = AsyncMock(return_value=rows)

    async def fetchval(sql, *args):
        # 대역의 fetchval 은 자료 3만 받는다 — 이 테스트는 자료가 여럿이라 여기서만 바꾼다
        if "returning started_at" in sql:
            return None
        if "from fact_occurrences" in sql:
            return 1 if "LINKED" in sql else 0
        raise AssertionError(sql)
    conn.fetchval = AsyncMock(side_effect=fetchval)
    process = AsyncMock(return_value=None)
    with patch.object(job_worker, "get_pool", return_value=pool), \
         patch.object(job_worker.pipeline, "process_source", process), \
         patch.object(route, "route_job_bundle", bundle), \
         patch.object(job_worker, "_refresh_job", AsyncMock(return_value=("SUCCEEDED", 1))), \
         patch.object(job_worker, "create_ingest_completed_notification",
                      AsyncMock(return_value=None)), \
         patch("app.config.get_settings", return_value=NS()):
        await job_worker.process_ingest_job(1, 2)
    return process


ROWS = [{"source_id": 3, "failed_segment_ids": None, "segments_total": None},
        {"source_id": 4, "failed_segment_ids": ["seg2"], "segments_total": 3},
        {"source_id": 5, "failed_segment_ids": None, "segments_total": None}]


@pytest.mark.asyncio
async def test_job_bundles_fresh_sources_and_reuses_caches():
    seen = {}

    async def bundle(pool, store_id, *, job_id, source_ids, usage_sink, usage_base, caches):
        seen.update(store_id=store_id, job_id=job_id, source_ids=list(source_ids),
                    usage_base=usage_base)
        caches[3] = route.IntakeCache()
        caches[5] = route.IntakeCache()
        return {}
    process = await _run_job(ROWS, bundle=AsyncMock(side_effect=bundle))
    # PARTIAL 재시도 자료(4)는 판정이 이미 있어 묶지 않는다
    assert seen["source_ids"] == [3, 5] and seen["store_id"] == 1 and seen["job_id"] == 2
    assert seen["usage_base"][:5] == (1, 2, "REGISTRATION", "PRODUCT", None)
    by_source = {c.args[1]: c.kwargs for c in process.await_args_list}
    assert set(by_source) == {3, 4, 5}
    assert by_source[3]["intake_cache"] is not None
    assert by_source[5]["intake_cache"] is not None
    assert by_source[3]["intake_cache"] is not by_source[5]["intake_cache"]
    assert by_source[4]["retry_segments"] == ["seg2"]
    assert by_source[4].get("intake_cache") is None


@pytest.mark.asyncio
async def test_job_bundle_error_keeps_processing_every_source():
    # Review Focus 1 — 묶음 단계가 예외를 올려도 자료마다 처리한다
    bundle = AsyncMock(side_effect=RuntimeError("묶음 실패"))
    process = await _run_job(ROWS, bundle=bundle)
    bundle.assert_awaited_once()
    assert sorted(c.args[1] for c in process.await_args_list) == [3, 4, 5]


@pytest.mark.asyncio
async def test_job_with_one_fresh_source_skips_bundle():
    bundle = AsyncMock(return_value={})
    process = await _run_job(ROWS[:2], bundle=bundle)
    bundle.assert_not_awaited()
    assert sorted(c.args[1] for c in process.await_args_list) == [3, 4]


# ── process_source 가 받은 캐시를 쓴다 ─────────────────────────────────────

@pytest.mark.asyncio
async def test_process_source_uses_given_intake_cache(tmp_path):
    from tests.test_wb_intake_pipeline import _route
    from tests.test_wb_intake_pipeline import _run as run_pipeline
    given = route.IntakeCache()
    await run_pipeline(tmp_path, route=_route("DOC_TEXT", "RECIPE"),
                       sections={"c1": "본문"}, intake_cache=given)
    # 대역 전처리는 넘겨받은 캐시에 sections 를 채운다 — 같은 객체여야 묶음 훑기를 다시 쓴다
    assert given.sections == {"c1": "본문"}
