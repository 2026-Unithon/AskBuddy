"""Task 7 — 구역 오케스트레이터와 파이프라인 연결.

실제 공급자를 부르지 않는다. 구역 지도·구역 처리는 대역으로 바꾸거나 mock 모드로 돈다.
"""
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from PIL import Image

from app.ingest import layout
from app.ingest.layout import schemas as ls
from app.ingest.providers import budget


def _settings(**over):
    base = dict(ingest_mode="mock", layout_region_model="anthropic:claude-sonnet-5-5",
                layout_transcribe_model="gemini:gemini-3.6-flash",
                layout_recheck_model="anthropic:claude-sonnet-5-5",
                layout_expand_model="gemini:gemini-3.6-flash", layout_render_dpi=72,
                ingest_scan_max_pages=None, layout_max_bands_per_source=80,
                layout_recheck_max_calls_per_source=30, layout_concurrency=2,
                extract_locator_hints=False, extract_clear_ungrounded_values=False)
    base.update(over)
    return NS(**base)


async def _run(tmp_path, regions_by_page, **kw):
    img = tmp_path / "a.png"
    Image.new("RGB", (400, 300), "white").save(img)
    saved = []

    async def checkpoint(assertions, seg):
        saved.append((seg, len(assertions)))
    with patch.object(layout, "get_settings", return_value=_settings()), \
         patch.object(layout, "map_page", regions_by_page), \
         patch.object(layout, "_process_region", kw.get("process")):
        out = await layout.run_layout_extraction(
            source_id=9, path=kw.get("path", img), workdir=tmp_path / "w", glossary=[],
            usage_sink=None, usage_base=None, raw_sink=None, checkpoint=checkpoint,
            only_segments=kw.get("only"))
    return out, saved


def _regions(n):
    async def fake(page, workdir, **k):
        return [ls.PlacedRegion(page.number, f"p{page.number}-r{i + 1}", "PROSE", (0, 0, 10, 10),
                                i + 1, None, "MODEL") for i in range(n)], []
    return fake


def _fact(ref="f1"):
    from app.ingest.schemas import Evidence, ExtractedAssertion
    return ExtractedAssertion(local_ref=ref, original_assertion="o", subject="s", attribute="a",
                              value="1", evidence=Evidence(), confidence=0.9)


@pytest.mark.asyncio
async def test_each_region_is_a_segment(tmp_path):
    async def process(region, page, workdir, ctx, caps, glossary, source_id, usage_sink, raw_sink, stats):
        return [_fact()], [], "o"
    out, saved = await _run(tmp_path, _regions(2), process=process)
    assert out.segments_total == 2 and out.segments_failed == 0
    assert saved == [("p1-r1", 1), ("p1-r2", 1)]
    assert {a.segment_id for a in out.assertions} == {"p1-r1", "p1-r2"}
    assert layout.STATS[9]["regions"] == 2


@pytest.mark.asyncio
async def test_budget_exceeded_marks_region_failed(tmp_path):
    calls = []

    async def process(region, page, workdir, ctx, caps, glossary, source_id, usage_sink, raw_sink, stats):
        calls.append(region.region_id)
        if region.region_id == "p1-r2":
            raise budget.BudgetExceeded("합성 상한")
        return [], [], ""
    out, _ = await _run(tmp_path, _regions(3), process=process)
    assert out.failed_segment_ids == ["p1-r2", "p1-r3"]       # 상한 뒤 구역은 부르지 않는다
    assert calls == ["p1-r1", "p1-r2"]
    assert out.segments_failed == 2


@pytest.mark.asyncio
async def test_budget_exceeded_in_map_page_stops_and_marks_page(tmp_path):
    """구역 지도에서 상한에 닿으면 그 쪽을 `p{n}-map` 실패 구간으로 남기고 멈춘다."""
    from app.ingest.layout.schemas import PageImage

    pages = [PageImage(n, tmp_path / "a.png", 400, 300) for n in (1, 2, 3)]
    mapped, calls = [], []

    async def fake_map(page, workdir, **k):
        mapped.append(page.number)
        if page.number == 2:
            raise budget.BudgetExceeded("합성 상한")
        return [ls.PlacedRegion(page.number, f"p{page.number}-r1", "PROSE", (0, 0, 10, 10),
                                1, None, "MODEL")], []

    async def process(region, *a, **k):
        calls.append(region.region_id)
        return [_fact()], [], "o"
    with patch.object(layout, "page_images", return_value=pages):
        out, saved = await _run(tmp_path, fake_map, process=process)
    assert mapped == [1, 2]                     # 상한 뒤 쪽은 구역 지도를 부르지 않는다
    assert calls == ["p1-r1"]
    assert out.failed_segment_ids == ["p2-map", "p3-map"]
    assert out.segments_total == 3 and out.segments_failed == 2
    assert saved == [("p1-r1", 1)]


@pytest.mark.asyncio
async def test_unreadable_notes_are_not_region_failures(tmp_path):
    """판독 불가·전개 미반영은 미해결로만 남고 구역 실패로 세지 않는다 (계획 편차 7)."""
    async def process(region, *a, **k):
        return [_fact()], ["[판독 불가] 1쪽 p1-r1 행 1 '가격' 칸: 흐림"], "o"
    out, _ = await _run(tmp_path, _regions(1), process=process)
    assert out.segments_failed == 0 and out.failed_segment_ids == []
    assert any(u.startswith("[판독 불가]") for u in out.unresolved)


@pytest.mark.asyncio
async def test_all_regions_failed_raises(tmp_path):
    async def process(region, *a, **k):
        raise RuntimeError("합성 실패")
    with pytest.raises(RuntimeError):
        await _run(tmp_path, _regions(2), process=process)


@pytest.mark.asyncio
async def test_only_segments(tmp_path):
    seen = []

    async def process(region, *a, **k):
        seen.append(region.region_id)
        return [], [], ""
    out, _ = await _run(tmp_path, _regions(3), process=process, only={"p1-r2"})
    assert seen == ["p1-r2"] and out.segments_total == 3


@pytest.mark.asyncio
async def test_mock_mode_end_to_end(tmp_path, monkeypatch):
    """합성 경로 전체: 구역 지도(쪽 전체 PROSE) → 글 전사 → expand_text(mock 사실 추출).

    api/.env 가 INGEST_MODE=real 이어도 실제 모델을 부르지 않게 환경변수로 mock 을 강제한다
    (pydantic-settings 는 환경변수가 .env 보다 우선). 설정 캐시를 앞뒤로 비운다.
    """
    from app.config import get_settings
    monkeypatch.setenv("INGEST_MODE", "mock")
    monkeypatch.setenv("SCAN_EXTRACT_MODE", "LAYOUT")
    get_settings.cache_clear()
    monkeypatch.setattr(budget, "_LIMIT", None)
    img = tmp_path / "a.png"
    Image.new("RGB", (400, 300), "white").save(img)
    saved = []

    async def checkpoint(assertions, seg):
        saved.append(seg)
    try:
        out = await layout.run_layout_extraction(
            source_id=10, path=img, workdir=tmp_path / "w", glossary=[], usage_sink=None,
            usage_base=None, raw_sink=None, checkpoint=checkpoint, only_segments=None)
    finally:
        get_settings.cache_clear()
    assert out.segments_total >= 1 and out.segments_failed == 0
    assert saved and saved[0] == "p1-r1"


@pytest.mark.asyncio
async def test_mock_mode_without_source_uses_blank_page(tmp_path, monkeypatch):
    """mock 은 원본을 내려받지 않는다(path=None) — 빈 쪽으로 끝까지 돈다."""
    from app.config import get_settings
    monkeypatch.setenv("INGEST_MODE", "mock")
    monkeypatch.setenv("SCAN_EXTRACT_MODE", "LAYOUT")
    get_settings.cache_clear()
    monkeypatch.setattr(budget, "_LIMIT", None)
    try:
        out = await layout.run_layout_extraction(
            source_id=11, path=None, workdir=tmp_path / "w", glossary=[], usage_sink=None,
            usage_base=None, raw_sink=None, checkpoint=None, only_segments=None)
    finally:
        get_settings.cache_clear()
    assert out.segments_total == 1 and out.segments_failed == 0
    assert layout.STATS[11]["pages"] == 1


# ── pipeline 연결 ───────────────────────────────────────────────────────

def test_layout_locator_persisted_as_page():
    a = _fact()
    a._layout_locator = {"page": 2, "region": "p2-r1", "bbox": [0, 0, 1, 1], "row": "3"}
    from app.ingest import pipeline
    assert pipeline._locator_of("SCAN", a, hints=False) == ("PAGE", {"page": 2, "region": "p2-r1",
                                                                      "bbox": [0, 0, 1, 1], "row": "3"})


def test_non_layout_locator_unchanged():
    from app.ingest import occurrences, pipeline
    a = _fact()
    assert pipeline._locator_of("SCAN", a, hints=False) == occurrences.locator_for(
        "SCAN", a.evidence, locator_hints=False)


@pytest.mark.asyncio
async def test_persist_ledger_writes_layout_locator_and_version(monkeypatch):
    """원장·근거 위치에 같은 PAGE 위치를 쓰고, 구역 사실에는 layout 추출 버전을 붙인다."""
    from app.config import get_settings
    from app.ingest import pipeline
    monkeypatch.setenv("INGEST_MODE", "mock")
    get_settings.cache_clear()
    plain, lay = _fact("f1"), _fact("f2")
    lay.value = "2"
    lay._layout_locator = {"page": 1, "region": "p1-r1", "bbox": [0, 0, 5, 5]}
    insert = AsyncMock(return_value=[101, 102])
    occ = AsyncMock()
    try:
        with patch.object(pipeline.repo, "insert_source_facts", insert), \
             patch.object(pipeline.occurrences, "insert_occurrences", occ):
            ids = await pipeline._persist_ledger(MagicMock(), 1, 2, "SCAN", [plain, lay])
        s = get_settings()
    finally:
        get_settings.cache_clear()
    assert ids == {"f1": 101, "f2": 102}
    rows = insert.await_args.args[3]
    assert rows[1]["locator_type"] == "PAGE" and rows[1]["locator"]["region"] == "p1-r1"
    assert rows[0]["extract_version"] is None
    assert rows[1]["extract_version"] == \
        f"layout:{s.layout_transcribe_model}+{s.layout_expand_model}/{s.ingest_mode}"
    # 기존 사실의 버전은 자료 단위 기본값 그대로
    assert insert.await_args.kwargs["extract_version"] == \
        f"{s.gemini_model}@t{s.extract_temperature}/{s.ingest_mode}"
    occ_rows = occ.await_args.args[2]
    assert occ_rows[1]["locator_type"] == "PAGE" and occ_rows[1]["locator"] == rows[1]["locator"]


class _Tx:
    async def __aenter__(self):
        return self

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


async def _process(tmp_path, monkeypatch, *, source_type="SCAN", mode="LAYOUT", reuse=True,
                   retry_segments=None, expected_total=None):
    from app.config import get_settings
    from app.ingest import pipeline
    from app.ingest.schemas import ExtractedCard, ExtractionResult
    monkeypatch.setenv("INGEST_MODE", "mock")
    monkeypatch.setenv("SCAN_EXTRACT_MODE", mode)
    monkeypatch.setenv("EXTRACT_REUSE_ENABLED", "true" if reuse else "false")
    get_settings.cache_clear()
    src = {"source_id": 2, "store_id": 1, "source_type": source_type,
           "file_url": "x", "content_hash": "h", "status": "PROCESSING"}
    run_layout = AsyncMock(return_value=pipeline.ExtractionOutcome([_fact()], [], 2, 0, []))
    single = AsyncMock(return_value=pipeline.ExtractionOutcome([_fact()], [], 1, 0, []))
    try:
        with patch.object(pipeline, "get_pool", return_value=_Pool()), \
             patch.object(pipeline, "_preprocess",
                          AsyncMock(return_value=(pipeline.MOCK_PLACEHOLDER, [], []))), \
             patch.object(pipeline.repo, "get_source", AsyncMock(return_value=src)), \
             patch.object(pipeline.repo, "set_status", AsyncMock()), \
             patch.object(pipeline.repo, "enabled_categories", AsyncMock(return_value={"기타": 1})), \
             patch.object(pipeline.repo, "glossary", AsyncMock(return_value=[])), \
             patch.object(pipeline.storage, "workdir", return_value=tmp_path / "w"), \
             patch.object(layout, "run_layout_extraction", run_layout), \
             patch.object(pipeline, "_extract_facts_all", single), \
             patch.object(pipeline, "assemble_assertions",
                          AsyncMock(return_value=ExtractionResult(cards=[ExtractedCard(
                              category_name="기타", title="합성", content="o", confidence=.9)],
                              unresolved=[]))), \
             patch.object(pipeline, "_record_segment_failures", AsyncMock()), \
             patch.object(pipeline, "_persist", AsyncMock(return_value=1)):
            returned = await pipeline.process_source(
                1, 2, retry_segments=retry_segments, expected_segments_total=expected_total)
    finally:
        get_settings.cache_clear()
    return returned, run_layout, single


@pytest.mark.asyncio
async def test_process_source_routes_scan_layout_even_without_media(tmp_path, monkeypatch):
    returned, run_layout, single = await _process(tmp_path, monkeypatch)
    assert returned is None
    single.assert_not_awaited()
    kw = run_layout.await_args.kwargs
    assert kw["path"] is None and kw["only_segments"] is None
    assert kw["workdir"] == tmp_path / "w" / "layout"


@pytest.mark.asyncio
@pytest.mark.parametrize("source_type,mode", [("SCAN", "SINGLE"), ("VIDEO", "LAYOUT")])
async def test_process_source_other_paths_unchanged(tmp_path, monkeypatch, source_type, mode):
    _, run_layout, single = await _process(tmp_path, monkeypatch, source_type=source_type, mode=mode)
    run_layout.assert_not_awaited()
    single.assert_awaited_once()


@pytest.mark.asyncio
async def test_layout_partial_retry_allowed_with_reuse(tmp_path, monkeypatch):
    returned, run_layout, _ = await _process(tmp_path, monkeypatch, retry_segments=["p1-r2"],
                                             expected_total=2)
    assert returned is None
    assert run_layout.await_args.kwargs["only_segments"] == {"p1-r2"}


@pytest.mark.asyncio
async def test_layout_partial_retry_unavailable_without_reuse(tmp_path, monkeypatch):
    from app.ingest import pipeline
    returned, run_layout, _ = await _process(tmp_path, monkeypatch, reuse=False,
                                             retry_segments=["p1-r2"], expected_total=2)
    assert returned == pipeline.PARTIAL_RETRY_UNAVAILABLE
    run_layout.assert_not_awaited()


@pytest.mark.asyncio
async def test_residual_row_flags_become_unresolved_and_counted(tmp_path):
    """재전사 뒤 남은 행 단위 문제(누락·행 수·열 수)는 미해결로 드러나고 STATS 에 센다."""
    region = ls.PlacedRegion(3, "p3-r2", "TABLE", (0, 0, 100, 100), 2,
                             ls.TableInfo(header_columns=["번호", "이름"], expected_rows=5,
                                          row_label_column=0), "MODEL")
    rows = [ls.TranscribedRow("1", ["1", "메뉴A"], 0), ls.TranscribedRow(None, ["메뉴B"], 1)]
    flags = [ls.CellFlag("p3-r2:1:row", 1, None, "ROW_MISSING", 1),
             ls.CellFlag("p3-r2:1:row", 1, None, "ROW_COUNT", 1),
             ls.CellFlag("p3-r2:1:row", 1, None, "COLUMN_COUNT", 1),
             ls.CellFlag("p3-r2:0:1", 0, 1, "OVERLAP_MISMATCH", 0)]
    table = ls.TableResult(region, ["번호", "이름"], rows, flags, [(0, 0, 100, 60), (0, 40, 100, 100)])
    stats = layout._new_stats()
    with patch.object(layout.transcribe, "transcribe_table", AsyncMock(return_value=table)), \
         patch.object(layout.recheck, "recheck_rows", AsyncMock(return_value=table)), \
         patch.object(layout.recheck, "resolve_cells", AsyncMock(return_value=None)), \
         patch.object(layout.groups, "resolve_groups", AsyncMock(return_value=[])), \
         patch.object(layout.expand, "expand_table", AsyncMock(return_value=([], ["[전개 미반영] x"]))):
        _, unresolved, _ = await layout._process_region(region, None, tmp_path, lambda l: None,
                                                        None, [], 9, None, None, stats)
    assert unresolved == ["[행 누락 의심] 3쪽 p3-r2 ROW_MISSING 띠1",
                          "[행 누락 의심] 3쪽 p3-r2 ROW_COUNT 띠1",
                          "[열 수 불일치] 3쪽 p3-r2 띠1 행 행2",
                          "[전개 미반영] x"]
    assert stats["row_flags_left"] == 3
