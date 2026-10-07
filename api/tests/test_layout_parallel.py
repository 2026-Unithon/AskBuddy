"""레이아웃 추출 병렬화 — 쪽·구역·표 전개 묶음 동시 처리, 결과 순서 고정, 금액 상한, 띠 예약.

실제 공급자를 부르지 않는다. 구역 지도·구역 처리·모델 호출은 대역이다.
"""
import asyncio
import re
from types import SimpleNamespace as NS
from unittest.mock import patch

import pytest
from PIL import Image

from app.ingest import layout
from app.ingest.layout import expand
from app.ingest.layout import schemas as ls
from app.ingest.layout import transcribe as t
from app.ingest.providers import budget


def _settings(**over):
    base = dict(ingest_mode="mock", layout_region_model="anthropic:claude-sonnet-5-5",
                layout_transcribe_model="gemini:gemini-3.6-flash",
                layout_recheck_model="anthropic:claude-sonnet-5-5",
                layout_expand_model="gemini:gemini-3.6-flash", layout_render_dpi=72,
                ingest_scan_max_pages=None, layout_max_bands_per_source=80,
                layout_recheck_max_calls_per_source=30, layout_concurrency=2,
                layout_region_concurrency=3,
                extract_locator_hints=False, extract_clear_ungrounded_values=False)
    base.update(over)
    return NS(**base)


def _fact(ref):
    from app.ingest.schemas import Evidence, ExtractedAssertion
    return ExtractedAssertion(local_ref=ref, original_assertion="o", subject="s", attribute="a",
                              value="1", evidence=Evidence(), confidence=0.9)


def _pages(tmp_path, n):
    img = tmp_path / "a.png"
    Image.new("RGB", (400, 300), "white").save(img)
    return img, [ls.PageImage(k, img, 400, 300) for k in range(1, n + 1)]


def _mapper(n_regions, delay_of=lambda page: 0.0, notes=True):
    async def fake(page, workdir, **k):
        await asyncio.sleep(delay_of(page.number))
        regions = [ls.PlacedRegion(page.number, f"p{page.number}-r{i + 1}", "PROSE", (0, 0, 10, 10),
                                   i + 1, None, "MODEL") for i in range(n_regions)]
        return regions, ([f"[지도] {page.number}쪽"] if notes else [])
    return fake


async def _run(tmp_path, *, n_pages, mapper, process, only=None, **settings_over):
    img, pages = _pages(tmp_path, n_pages)
    saved = []

    async def checkpoint(assertions, seg):
        saved.append(seg)
    with patch.object(layout, "get_settings", return_value=_settings(**settings_over)), \
         patch.object(layout, "page_images", return_value=pages), \
         patch.object(layout, "map_page", mapper), \
         patch.object(layout, "_process_region", process):
        out = await layout.run_layout_extraction(
            source_id=21, path=img, workdir=tmp_path / "w", glossary=[], usage_sink=None,
            usage_base=None, raw_sink=None, checkpoint=checkpoint, only_segments=only)
    return out, saved


class _Gauge:
    """동시에 몇 개가 진행 중인지 잰다."""

    def __init__(self):
        self.now = 0
        self.peak = 0

    def enter(self):
        self.now += 1
        self.peak = max(self.peak, self.now)

    def leave(self):
        self.now -= 1


@pytest.mark.asyncio
async def test_regions_run_concurrently_within_limit(tmp_path):
    gauge = _Gauge()

    async def process(region, *a, **k):
        gauge.enter()
        await asyncio.sleep(0.02)
        gauge.leave()
        return [_fact(region.region_id)], [], "o"
    out, _ = await _run(tmp_path, n_pages=1, mapper=_mapper(6), process=process,
                        layout_region_concurrency=3)
    assert 1 < gauge.peak <= 3
    assert out.segments_total == 6 and out.segments_failed == 0


@pytest.mark.asyncio
async def test_region_limit_spans_pages(tmp_path):
    """구역 동시 처리 상한은 쪽마다가 아니라 자료 하나 전체에 건다."""
    gauge = _Gauge()

    async def process(region, *a, **k):
        gauge.enter()
        await asyncio.sleep(0.02)
        gauge.leave()
        return [], [], ""
    await _run(tmp_path, n_pages=3, mapper=_mapper(3), process=process, layout_region_concurrency=2)
    assert gauge.peak == 2


@pytest.mark.asyncio
async def test_pages_map_concurrently(tmp_path):
    gauge = _Gauge()

    async def mapper(page, workdir, **k):
        gauge.enter()
        await asyncio.sleep(0.02)
        gauge.leave()
        return [ls.PlacedRegion(page.number, f"p{page.number}-r1", "PROSE", (0, 0, 10, 10), 1,
                                None, "MODEL")], []

    async def process(region, *a, **k):
        return [], [], ""
    await _run(tmp_path, n_pages=3, mapper=mapper, process=process)
    assert gauge.peak == 3


def _reverse_process(fail=()):
    """뒤 구역일수록 먼저 끝난다. fail 에 든 구역은 실패한다."""
    async def process(region, *a, **k):
        page, idx = region.page, region.order
        await asyncio.sleep(0.05 - 0.01 * page - 0.003 * idx)
        if region.region_id in fail:
            raise RuntimeError("합성 실패")
        return ([_fact(f"{region.region_id}.a"), _fact(f"{region.region_id}.b")],
                [f"[메모] {region.region_id}"], "o")
    return process


@pytest.mark.asyncio
async def test_outcome_order_is_page_then_region(tmp_path):
    mapper = _mapper(3, delay_of=lambda n: 0.03 - 0.01 * n)    # 뒤 쪽 지도가 먼저 나온다
    out, saved = await _run(tmp_path, n_pages=3, mapper=mapper,
                            process=_reverse_process(fail={"p1-r2", "p3-r1"}))
    expect_ok = [f"p{p}-r{r}" for p in (1, 2, 3) for r in (1, 2, 3)
                 if f"p{p}-r{r}" not in {"p1-r2", "p3-r1"}]
    assert [a.local_ref for a in out.assertions] == [f"{rid}.{x}" for rid in expect_ok for x in "ab"]
    assert [a.segment_id for a in out.assertions] == [rid for rid in expect_ok for _ in "ab"]
    expected_notes = []
    for p in (1, 2, 3):
        expected_notes.append(f"[지도] {p}쪽")
        expected_notes += [f"[메모] p{p}-r{r}" for r in (1, 2, 3)
                           if f"p{p}-r{r}" not in {"p1-r2", "p3-r1"}]
    assert out.unresolved == expected_notes
    assert out.failed_segment_ids == ["p1-r2", "p3-r1"]
    assert out.segments_total == 9 and out.segments_failed == 2
    assert sorted(saved) == sorted(expect_ok)


@pytest.mark.asyncio
async def test_map_failure_keeps_page_position(tmp_path):
    async def mapper(page, workdir, **k):
        await asyncio.sleep(0.03 - 0.01 * page.number)
        if page.number == 2:
            raise ValueError("이미지 처리 오류")
        return [ls.PlacedRegion(page.number, f"p{page.number}-r1", "PROSE", (0, 0, 10, 10), 1,
                                None, "MODEL")], []
    out, _ = await _run(tmp_path, n_pages=3, mapper=mapper,
                        process=_reverse_process(fail={"p1-r1"}))
    assert out.failed_segment_ids == ["p1-r1", "p2-map"]
    assert out.segments_total == 3


@pytest.mark.asyncio
async def test_budget_stop_waits_for_running_and_fails_unstarted(tmp_path):
    started, finished = [], []

    async def process(region, *a, **k):
        rid = region.region_id
        started.append(rid)
        if rid == "p1-r2":
            await asyncio.sleep(0.01)
            raise budget.BudgetExceeded("합성 상한")
        await asyncio.sleep(0.05)                # 상한이 켜지는 동안 진행 중이다
        finished.append(rid)
        return [_fact(rid)], [], "o"
    out, saved = await _run(tmp_path, n_pages=1, mapper=_mapper(5, notes=False), process=process,
                            layout_region_concurrency=2)
    assert started == ["p1-r1", "p1-r2"]         # 상한 뒤에는 새 구역을 시작하지 않는다
    assert finished == ["p1-r1"]                 # 진행 중이던 구역은 끝까지 기다린다
    assert saved == ["p1-r1"]
    assert [a.segment_id for a in out.assertions] == ["p1-r1"]
    assert out.failed_segment_ids == ["p1-r2", "p1-r3", "p1-r4", "p1-r5"]
    assert out.segments_total == 5 and out.segments_failed == 4
    left = [x for x in asyncio.all_tasks() if x is not asyncio.current_task()]
    assert left == []                            # 반환 뒤 남은 작업이 없다


@pytest.mark.asyncio
async def test_serial_and_parallel_outcomes_match(tmp_path):
    async def run(conc, sub):
        sub.mkdir()
        layout.STATS.pop(21, None)

        async def process(region, page, workdir, ctx, caps, glossary, source_id, usage_sink,
                          raw_sink, stats):
            stats["rows"] += region.order
            return await _reverse_process(fail={"p2-r2"})(region)
        out, _ = await _run(sub, n_pages=3, mapper=_mapper(3, delay_of=lambda n: 0.03 - 0.01 * n),
                            process=process, layout_region_concurrency=conc)
        return ([(a.segment_id, a.local_ref) for a in out.assertions], out.unresolved,
                out.failed_segment_ids, out.segments_total, out.segments_failed,
                dict(layout.STATS[21]))
    assert await run(1, tmp_path / "s") == await run(3, tmp_path / "p")


@pytest.mark.asyncio
async def test_only_segments_respected_in_parallel(tmp_path):
    seen = []

    async def process(region, *a, **k):
        seen.append(region.region_id)
        await asyncio.sleep(0.01)
        return [], [], ""
    out, _ = await _run(tmp_path, n_pages=2, mapper=_mapper(3), process=process,
                        only={"p1-r2", "p2-map"})
    assert sorted(seen) == ["p1-r2", "p2-r1", "p2-r2", "p2-r3"]
    assert out.segments_total == 6


# ── 띠 상한 예약 ───────────────────────────────────────────────────────

TS = NS(layout_band_rows=5, layout_band_overlap_rows=1, layout_default_row_px=40, layout_min_row_px=14,
        layout_max_row_px=80, layout_concurrency=4, layout_transcribe_model="gemini:gemini-3.6-flash",
        layout_zoom=1.0)


def _six_band_region(tmp_path, rid):
    """24행 × 20px = 띠 6개."""
    img = tmp_path / "tall.png"
    Image.new("RGB", (100, 480), "white").save(img)
    info = ls.TableInfo(header_columns=["번호", "이름"], expected_rows=24, row_label_column=0)
    return (ls.PlacedRegion(1, rid, "TABLE", (0, 0, 100, 480), 1, info, "MODEL"),
            ls.PageImage(1, img, 100, 480))


@pytest.mark.asyncio
async def test_band_cap_reserved_before_calls(tmp_path):
    calls = []

    async def fake(*args, **kwargs):
        calls.append(kwargs["usage_context"])
        await asyncio.sleep(0.01)
        return ls.BandRows(rows=[])
    caps = ls.Caps(bands_left=8, recheck_calls_left=0)
    a, page = _six_band_region(tmp_path, "p1-r1")
    b, _ = _six_band_region(tmp_path, "p1-r2")
    with patch.object(t, "get_settings", return_value=TS), \
         patch.object(t, "measured_generate", side_effect=fake):
        assert len(t.plan_bands(a.box, 24, rows_per_band=5, overlap_rows=1, default_row_px=40,
                                min_row_px=14, max_row_px=80)) == 6
        got = await asyncio.gather(
            *(t.transcribe_table(r, page, tmp_path, caps=caps, ctx=lambda l: l, usage_sink=None,
                                 raw_sink=None) for r in (a, b)), return_exceptions=True)
    assert not isinstance(got[0], BaseException)
    assert isinstance(got[1], RuntimeError) and "띠 호출 상한 부족" in str(got[1])
    assert len(calls) == 6 and all(c.startswith("p1-r1.") for c in calls)   # 진 구역은 0회
    assert caps.bands_left == 2


@pytest.mark.asyncio
async def test_text_bands_reserved_up_front(tmp_path):
    img = tmp_path / "tall.png"
    Image.new("RGB", (100, 2000), "white").save(img)
    region = ls.PlacedRegion(1, "p1-r1", "PROSE", (0, 0, 100, 2000), 1, None, "MODEL")
    page = ls.PageImage(1, img, 100, 2000)
    caps = ls.Caps(bands_left=1, recheck_calls_left=0)
    with patch.object(t, "get_settings", return_value=TS), \
         patch.object(t, "measured_generate") as mg:
        with pytest.raises(RuntimeError, match="띠 호출 상한 부족"):
            await t.transcribe_text(region, page, tmp_path, kind_prompt="prose", caps=caps,
                                    ctx=lambda l: l, usage_sink=None, raw_sink=None)
    mg.assert_not_called()
    assert caps.bands_left == 1


@pytest.mark.asyncio
async def test_text_bands_deducted_once(tmp_path):
    img = tmp_path / "tall.png"
    Image.new("RGB", (100, 2000), "white").save(img)
    region = ls.PlacedRegion(1, "p1-r1", "PROSE", (0, 0, 100, 2000), 1, None, "MODEL")
    page = ls.PageImage(1, img, 100, 2000)
    n = len(t.plan_bands(region.box, None, rows_per_band=15, overlap_rows=1, default_row_px=40,
                         min_row_px=14, max_row_px=80))
    caps = ls.Caps(bands_left=n + 3, recheck_calls_left=0)

    async def fake(*args, **kwargs):
        return ls.ProseLines(lines=[kwargs["usage_context"]])
    with patch.object(t, "get_settings", return_value=TS), \
         patch.object(t, "measured_generate", side_effect=fake):
        res = await t.transcribe_text(region, page, tmp_path, kind_prompt="prose", caps=caps,
                                      ctx=lambda l: l, usage_sink=None, raw_sink=None)
    assert n > 1 and len(res.lines) == n
    assert caps.bands_left == 3


# ── 표 전개 묶음 병렬 ──────────────────────────────────────────────────

EST = NS(layout_expand_model="gemini:gemini-3.6-flash", layout_expand_batch_rows=10,
         layout_fact_confidence=0.9, layout_concurrency=4)


def _wide_table(n):
    region = ls.PlacedRegion(2, "p2-r1", "TABLE", (0, 0, 100, 100), 1,
                             ls.TableInfo(header_columns=["번호", "이름", "가격"], expected_rows=n,
                                          row_label_column=0), "MODEL")
    rows = [ls.TranscribedRow(str(i + 1), [str(i + 1), f"메뉴{chr(65 + i)}", str(1000 + i)], 0)
            for i in range(n)]
    return ls.TableResult(region, ["번호", "이름", "가격"], rows, [], [(0, 0, 100, 100)])


@pytest.mark.asyncio
async def test_expand_batches_run_concurrently_in_order():
    gauge = _Gauge()
    table = _wide_table(25)

    async def fake(spec, prompt, images, schema, **k):
        gauge.enter()
        tag = k["usage_context"]                     # p2-r1.x{배치}
        batch = int(tag.rsplit("x", 1)[1])
        await asyncio.sleep(0.03 - 0.01 * batch)     # 뒤 배치가 먼저 끝난다
        gauge.leave()
        facts = []
        for key, label in re.findall(r"\[(R\d+) \| 라벨 (\d+)\]", prompt):
            i = int(label) - 1
            facts.append(ls.LayoutFact(row_ref=key, original_assertion="가격", subject=f"메뉴{i + 1}",
                                       variant="", attribute="가격", value=str(1000 + i), unit="원",
                                       polarity="AFFIRM", conditions=[], exceptions=[], order=0))
        if batch == 1:
            facts.append(ls.LayoutFact(row_ref="R99", original_assertion="떠돌이", subject="s",
                                       variant="", attribute="a", value="", unit="",
                                       polarity="AFFIRM", conditions=[], exceptions=[], order=0))
        return ls.ExpandResult(facts=facts)
    with patch.object(expand, "get_settings", return_value=EST), \
         patch.object(expand, "measured_generate", fake):
        assertions, unresolved = await expand.expand_table(table, ctx=lambda l: l,
                                                           usage_sink=None, raw_sink=None)
    assert gauge.peak == 3
    assert [a._layout_locator["row"] for a in assertions] == [str(i + 1) for i in range(25)]
    assert [a.local_ref for a in assertions][:2] == ["p2-r1.0.0", "p2-r1.1.0"]
    assert unresolved == ["[행 연결 실패] 2쪽 p2-r1: row_ref=R99 — 떠돌이"]


# ── 보강: 형제 예외 우선순위·작업 방치 방지·묶음 상한 ─────────────────────

@pytest.mark.asyncio
async def test_expand_prefers_budget_exceeded_over_other_errors():
    """여러 묶음이 실패하면 금액 상한 예외를 우선 올린다 — 구역이 멈춤 표시를 켜게."""
    table = _wide_table(20)

    async def fake(spec, prompt, images, schema, **k):
        if k["usage_context"].endswith("x0"):
            raise ValueError("합성 오류")
        await asyncio.sleep(0.01)
        raise budget.BudgetExceeded("합성 상한")
    with patch.object(expand, "get_settings", return_value=EST), \
         patch.object(expand, "measured_generate", fake):
        with pytest.raises(budget.BudgetExceeded):
            await expand.expand_table(table, ctx=lambda l: l, usage_sink=None, raw_sink=None)


@pytest.mark.asyncio
async def test_transcribe_prefers_budget_exceeded_over_other_errors(tmp_path):
    region, page = _six_band_region(tmp_path, "p1-r1")

    async def fake(*args, **kwargs):
        if kwargs["usage_context"].endswith(".b0"):
            raise ValueError("합성 오류")
        await asyncio.sleep(0.01)
        raise budget.BudgetExceeded("합성 상한")
    with patch.object(t, "get_settings", return_value=TS), \
         patch.object(t, "measured_generate", side_effect=fake):
        with pytest.raises(budget.BudgetExceeded):
            await t.transcribe_table(region, page, tmp_path, caps=ls.Caps(10, 0), ctx=lambda l: l,
                                     usage_sink=None, raw_sink=None)


class _BadRegion:
    """try 밖(통계 집계)에서 예상 못 한 예외를 낸다."""
    page, region_id, order = 1, "p1-r1", 1

    @property
    def added_by(self):
        raise KeyError("합성 코드 오류")


@pytest.mark.asyncio
async def test_unexpected_error_waits_for_siblings(tmp_path):
    finished = []

    async def mapper(page, workdir, **k):
        if page.number == 1:
            return [_BadRegion()], []
        return [ls.PlacedRegion(page.number, f"p{page.number}-r1", "PROSE", (0, 0, 10, 10), 1,
                                None, "MODEL")], []

    async def process(region, *a, **k):
        await asyncio.sleep(0.03)
        finished.append(region.region_id)
        return [], [], ""
    with pytest.raises(KeyError):
        await _run(tmp_path, n_pages=3, mapper=mapper, process=process)
    assert sorted(finished) == ["p2-r1", "p3-r1"]      # 형제가 끝난 뒤에 오류가 올라온다
    left = [x for x in asyncio.all_tasks() if x is not asyncio.current_task()]
    assert left == []


@pytest.mark.asyncio
async def test_expand_batches_bounded_by_layout_concurrency():
    gauge = _Gauge()
    table = _wide_table(50)                              # 묶음 5개

    async def fake(spec, prompt, images, schema, **k):
        gauge.enter()
        await asyncio.sleep(0.01)
        gauge.leave()
        return ls.ExpandResult(facts=[])
    settings = NS(**{**vars(EST), "layout_concurrency": 2})
    with patch.object(expand, "get_settings", return_value=settings), \
         patch.object(expand, "measured_generate", fake):
        await expand.expand_table(table, ctx=lambda l: l, usage_sink=None, raw_sink=None)
    assert gauge.peak == 2
