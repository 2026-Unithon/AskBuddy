from types import SimpleNamespace as NS
from unittest.mock import patch

import pytest
from PIL import Image

from app.ingest.layout import recheck
from app.ingest.layout.schemas import (Caps, CellAnswer, CellFlag, CropRequest, PageImage,
                                       PlacedRegion, RecheckTurn, TableInfo, TableResult,
                                       TranscribedRow)

ST = NS(layout_recheck_model="anthropic:claude-sonnet-5-5", layout_recheck_max_turns=2,
        layout_zoom=2.0, layout_band_overlap_rows=1, layout_min_row_px=14,
        layout_recheck_max_crops_per_turn=3, layout_crop_max_px=2000)


def _table(tmp_path):
    p = tmp_path / "page.png"
    Image.new("RGB", (200, 200), "white").save(p)
    page = PageImage(1, p, 200, 200)
    region = PlacedRegion(1, "p1-r1", "TABLE", (0, 0, 200, 200), 1,
                          TableInfo(header_columns=["이름", "값"], expected_rows=2,
                                    row_label_column=None), "MODEL")
    rows = [TranscribedRow(None, ["메뉴A", "10"], 0), TranscribedRow(None, ["메뉴B", "2?"], 0)]
    flags = [CellFlag("p1-r1:1:1", 1, 1, "OVERLAP_MISMATCH", 0)]
    return page, TableResult(region, ["이름", "값"], rows, flags, [(0, 0, 200, 200)])


def test_crop_box_inside_region():
    assert recheck.crop_box((100, 100, 300, 200), CropRequest(bbox=[0.5, 0, 1, 1], scale=3)) == (200, 100, 300, 200)


def test_crop_box_clamps_outside():
    assert recheck.crop_box((0, 0, 100, 100), CropRequest(bbox=[-1, -1, 2, 2], scale=1)) == (0, 0, 100, 100)


@pytest.mark.asyncio
async def test_resolve_cells_requests_crop_then_answers(tmp_path):
    page, table = _table(tmp_path)
    turns = [RecheckTurn(crops=[CropRequest(bbox=[0.5, 0.5, 1, 1], scale=3)], answers=[]),
             RecheckTurn(crops=[], answers=[CellAnswer(cell_id="p1-r1:1:1", value="25",
                                                        unreadable_reason=None)])]
    calls = []

    async def fake(spec, prompt, images, schema, **k):
        calls.append(len(images))
        return turns[len(calls) - 1]
    caps = Caps(bands_left=10, recheck_calls_left=5)
    with patch.object(recheck, "get_settings", return_value=ST), \
         patch.object(recheck, "measured_generate", fake):
        await recheck.resolve_cells(table, page, tmp_path, caps=caps, ctx=lambda l: None,
                                    usage_sink=None, raw_sink=None)
    assert table.rows[1].cells[1] == "25"
    assert calls == [1, 2]
    assert caps.recheck_calls_left == 3


@pytest.mark.asyncio
async def test_resolve_cells_cap_marks_unreadable(tmp_path):
    page, table = _table(tmp_path)

    async def never(spec, prompt, images, schema, **k):
        return RecheckTurn(crops=[CropRequest(bbox=[0, 0, 1, 1], scale=2)], answers=[])
    with patch.object(recheck, "get_settings", return_value=ST), \
         patch.object(recheck, "measured_generate", never):
        await recheck.resolve_cells(table, page, tmp_path, caps=Caps(10, 5), ctx=lambda l: None,
                                    usage_sink=None, raw_sink=None)
    assert table.unreadable == {(1, 1): "cap"}


@pytest.mark.asyncio
async def test_resolve_cells_model_says_unreadable(tmp_path):
    page, table = _table(tmp_path)

    async def says(spec, prompt, images, schema, **k):
        return RecheckTurn(crops=[], answers=[CellAnswer(cell_id="p1-r1:1:1", value=None,
                                                          unreadable_reason="번짐")])
    with patch.object(recheck, "get_settings", return_value=ST), \
         patch.object(recheck, "measured_generate", says):
        await recheck.resolve_cells(table, page, tmp_path, caps=Caps(10, 5), ctx=lambda l: None,
                                    usage_sink=None, raw_sink=None)
    assert table.unreadable == {(1, 1): "번짐"}


@pytest.mark.asyncio
async def test_no_recheck_budget_marks_all_unreadable(tmp_path):
    page, table = _table(tmp_path)
    with patch.object(recheck, "get_settings", return_value=ST):
        await recheck.resolve_cells(table, page, tmp_path, caps=Caps(10, 0), ctx=lambda l: None,
                                    usage_sink=None, raw_sink=None)
    assert table.unreadable == {(1, 1): "cap"}


@pytest.mark.asyncio
async def test_resolve_cells_guards_out_of_range_cell(tmp_path):
    page, table = _table(tmp_path)
    table.rows[1].cells = ["메뉴B"]                       # 열 1 이 행에 없다
    seen = {}

    async def fake(spec, prompt, images, schema, **k):
        seen["prompt"] = prompt
        return RecheckTurn(crops=[], answers=[])
    with patch.object(recheck, "get_settings", return_value=ST), \
         patch.object(recheck, "measured_generate", fake):
        await recheck.resolve_cells(table, page, tmp_path, caps=Caps(10, 5), ctx=lambda l: None,
                                    usage_sink=None, raw_sink=None)
    assert "p1-r1:1:1" in seen["prompt"]


@pytest.mark.asyncio
async def test_budget_exceeded_propagates(tmp_path):
    from app.ingest.providers.budget import BudgetExceeded
    page, table = _table(tmp_path)

    async def boom(spec, prompt, images, schema, **k):
        raise BudgetExceeded("상한")
    with patch.object(recheck, "get_settings", return_value=ST), \
         patch.object(recheck, "measured_generate", boom):
        with pytest.raises(BudgetExceeded):
            await recheck.resolve_cells(table, page, tmp_path, caps=Caps(10, 5),
                                        ctx=lambda l: None, usage_sink=None, raw_sink=None)


@pytest.mark.asyncio
async def test_recheck_rows_retranscribes_flagged_band(tmp_path):
    page, table = _table(tmp_path)
    table.flags = [CellFlag("p1-r1:1:row", 1, None, "COLUMN_COUNT", 0)]
    table.rows[1].cells = ["메뉴B"]
    seen = {}

    async def fake_tt(region, page, workdir, *, caps, ctx, usage_sink, raw_sink, spec_text=None, band_indexes=None):
        seen["spec"], seen["bands"] = spec_text, band_indexes
        return TableResult(region, ["이름", "값"], [TranscribedRow(None, ["메뉴A", "10"], 0),
                                                   TranscribedRow(None, ["메뉴B", "20"], 0)], [], [(0, 0, 200, 200)])
    caps = Caps(10, 5)
    with patch.object(recheck, "get_settings", return_value=ST), \
         patch.object(recheck, "transcribe_table", fake_tt):
        out = await recheck.recheck_rows(table, page, tmp_path, caps=caps, ctx=lambda l: None,
                                         usage_sink=None, raw_sink=None)
    assert seen == {"spec": ST.layout_recheck_model, "bands": [0]}
    assert [r.cells for r in out.rows] == [["메뉴A", "10"], ["메뉴B", "20"]]
    assert out.flags == []
    assert caps.recheck_calls_left == 4


@pytest.mark.asyncio
async def test_recheck_rows_keeps_other_bands_and_prefixes_flags(tmp_path):
    page, table = _table(tmp_path)
    table.region.table.expected_rows = 3
    table.rows = [TranscribedRow(None, ["메뉴A", "10"], 0), TranscribedRow(None, ["메뉴B"], 1)]
    table.band_boxes = [(0, 0, 200, 100), (0, 100, 200, 200)]
    table.flags = [CellFlag("p1-r1:1:row", 1, None, "COLUMN_COUNT", 1)]
    got = {}

    async def fake_tt(region, page, workdir, *, caps, ctx, usage_sink, raw_sink, spec_text=None, band_indexes=None):
        got["bands"] = band_indexes
        return TableResult(region, ["이름", "값"], [TranscribedRow(None, ["메뉴B"], 1)], [], table.band_boxes)
    with patch.object(recheck, "get_settings", return_value=ST), \
         patch.object(recheck, "transcribe_table", fake_tt):
        out = await recheck.recheck_rows(table, page, tmp_path, caps=Caps(10, 5), ctx=lambda l: None,
                                         usage_sink=None, raw_sink=None)
    assert got["bands"] == [1]
    assert [r.cells for r in out.rows] == [["메뉴A", "10"], ["메뉴B"]]
    ids = {f.cell_id for f in out.flags}
    assert "p1-r1:1:row" in ids and "p1-r1:1:row" in ids
    assert all(i.startswith("p1-r1:") for i in ids)


def test_crop_box_sorts_inverted_coords():
    req = CropRequest(bbox=[0.8, 0.2, 0.3, 0.6], scale=2)
    assert recheck.crop_box((0, 0, 100, 100), req) == (30, 20, 80, 60)


def test_crop_box_pads_short_bbox_with_full_extent():
    assert recheck.crop_box((0, 0, 100, 100), CropRequest(bbox=[0.1, 0.1], scale=2)) == (10, 10, 100, 100)


def test_crop_box_zero_size_is_none():
    assert recheck.crop_box((0, 0, 100, 100), CropRequest(bbox=[0.5, 0.1, 0.5, 0.9], scale=2)) is None


def test_crop_scale_caps_long_edge():
    assert recheck.crop_scale((0, 0, 1000, 200), 4.0, 2000) == 2.0
    assert recheck.crop_scale((0, 0, 4000, 100), 1.0, 2000) == 0.5        # 1 아래로도 낮춘다
    assert recheck.crop_scale((0, 0, 100, 100), 9.0, 2000) == 4.0


@pytest.mark.asyncio
async def test_resolve_cells_bad_crops_skipped_and_capped(tmp_path):
    """뒤집힘·짧음은 정리해 쓰고, 넓이 0 은 무시하고, 한 턴 확대 수는 상한까지만."""
    page, table = _table(tmp_path)
    crops = [CropRequest(bbox=[0.5, 0.5, 0.5, 0.9], scale=2),          # 넓이 0 — 무시
             CropRequest(bbox=[0.8, 0.2, 0.3, 0.6], scale=2),          # 뒤집힘 — 정렬
             CropRequest(bbox=[0.1, 0.1], scale=2),                    # 짧음 — 채움
             CropRequest(bbox=[0, 0, 1, 1], scale=2)]                  # 상한(3) 밖 — 버림
    calls = []

    async def fake(spec, prompt, images, schema, **k):
        calls.append(len(images))
        if len(calls) == 1:
            return RecheckTurn(crops=crops, answers=[])
        return RecheckTurn(crops=[], answers=[CellAnswer(cell_id="p1-r1:1:1", value="25",
                                                          unreadable_reason=None)])
    with patch.object(recheck, "get_settings", return_value=ST), \
         patch.object(recheck, "measured_generate", fake):
        await recheck.resolve_cells(table, page, tmp_path, caps=Caps(10, 5), ctx=lambda l: None,
                                    usage_sink=None, raw_sink=None)
    assert calls == [1, 3]                    # 영역 1장 + 유효 확대 2장
    assert table.rows[1].cells[1] == "25"


@pytest.mark.asyncio
async def test_resolve_cells_crop_long_edge_capped(tmp_path):
    page, table = _table(tmp_path)
    st = NS(**{**vars(ST), "layout_crop_max_px": 100})
    sizes = []

    async def fake(spec, prompt, images, schema, **k):
        sizes.append([Image.open(i).size for i in images])
        if len(sizes) == 1:
            return RecheckTurn(crops=[CropRequest(bbox=[0, 0, 1, 1], scale=4)], answers=[])
        return RecheckTurn(crops=[], answers=[])
    with patch.object(recheck, "get_settings", return_value=st), \
         patch.object(recheck, "measured_generate", fake):
        await recheck.resolve_cells(table, page, tmp_path, caps=Caps(10, 5), ctx=lambda l: None,
                                    usage_sink=None, raw_sink=None)
    assert sizes[1][1] == (100, 100)          # 200px × 4 → 긴 변 100px 로 낮춤


@pytest.mark.asyncio
async def test_recheck_rows_window_from_band_geometry(tmp_path):
    """띠 겹침이 3행(42px ÷ 14px)이면 창도 3 — 설정 겹침 1행(창 2)보다 넓게 겹침을 지운다."""
    page, table = _table(tmp_path)
    table.region.table.expected_rows = None
    table.band_boxes = [(0, 0, 200, 100), (0, 58, 200, 200)]
    a, b, c, d = ["A", "1"], ["B", "2"], ["C", "3"], ["D", "4"]
    table.rows = [TranscribedRow(None, a, 0), TranscribedRow(None, b, 0), TranscribedRow(None, c, 0),
                  TranscribedRow(None, ["D"], 1)]
    table.flags = [CellFlag("p1-r1:3:row", 3, None, "COLUMN_COUNT", 1)]

    async def fake_tt(region, page, workdir, *, caps, ctx, usage_sink, raw_sink, spec_text=None, band_indexes=None):
        return TableResult(region, ["이름", "값"], [TranscribedRow(None, a, 1), TranscribedRow(None, b, 1),
                                                   TranscribedRow(None, c, 1), TranscribedRow(None, d, 1)],
                           [], table.band_boxes)
    with patch.object(recheck, "get_settings", return_value=ST), \
         patch.object(recheck, "transcribe_table", fake_tt):
        out = await recheck.recheck_rows(table, page, tmp_path, caps=Caps(10, 5), ctx=lambda l: None,
                                         usage_sink=None, raw_sink=None)
    assert [r.cells[0] for r in out.rows] == ["A", "B", "C", "D"]
