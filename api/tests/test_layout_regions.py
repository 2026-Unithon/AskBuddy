from types import SimpleNamespace as NS
from unittest.mock import patch

import pytest
from PIL import Image, ImageDraw

from app.ingest.layout import regions
from app.ingest.layout.schemas import PageImage, Region, RegionMap, TableInfo

COVER = dict(cover_margin_ratio=0.015, max_overlap=0.3)


def _page(tmp_path, draw_boxes=()):
    p = tmp_path / "page.png"
    img = Image.new("RGB", (400, 300), "white")
    d = ImageDraw.Draw(img)
    for b in draw_boxes:
        d.rectangle(b, fill="black")
    img.save(p)
    return PageImage(1, p, 400, 300)


def test_place_regions_scales_clamps_and_orders(tmp_path):
    page = _page(tmp_path)
    rm = RegionMap(regions=[
        Region(kind="PROSE", bbox=[0.5, 0.5, 1.2, 1.0], reading_order=2, table=None),
        Region(kind="TABLE", bbox=[0.0, 0.0, 0.5, 0.5], reading_order=1,
               table=TableInfo(header_columns=["A", "B"], expected_rows=3, row_label_column=0)),
        Region(kind="PROSE", bbox=[0.1, 0.1, 0.101, 0.101], reading_order=3, table=None),
    ])
    out = regions.place_regions(page, rm)
    assert [r.region_id for r in out] == ["p1-r1", "p1-r2"]
    assert out[0].kind == "TABLE" and out[0].box == (0, 0, 200, 150)
    assert out[1].box == (200, 150, 400, 300)        # 1.2 → 쪽 끝으로 자름
    assert all(r.added_by == "MODEL" for r in out)


def test_uncovered_ink_becomes_region(tmp_path):
    page = _page(tmp_path, draw_boxes=[(10, 10, 60, 40), (300, 250, 360, 290)])
    out = regions.uncovered_boxes(page.path, [(0, 0, 100, 100)],
                                  ink_threshold=160, min_area_px=200, **COVER)
    assert len(out) == 1
    x0, y0, x1, y1 = out[0]
    assert x0 <= 300 and y0 <= 250 and x1 >= 360 and y1 >= 290


def test_uncovered_ignores_small_specks(tmp_path):
    page = _page(tmp_path, draw_boxes=[(200, 200, 202, 202)])
    assert regions.uncovered_boxes(page.path, [], ink_threshold=160, min_area_px=200, **COVER) == []


@pytest.mark.asyncio
async def test_map_page_falls_back_on_model_failure(tmp_path):
    page = _page(tmp_path, draw_boxes=[(10, 10, 60, 40)])
    st = NS(layout_region_model="anthropic:claude-sonnet-5-5", layout_region_image_max_px=200,
            layout_ink_threshold=160, layout_uncovered_min_area_px=200,
            layout_cover_margin_ratio=0.015, layout_coverage_max_overlap=0.3)

    async def boom(*a, **k):
        raise RuntimeError("합성 실패")
    with patch.object(regions, "get_settings", return_value=st), \
         patch.object(regions, "measured_generate", boom):
        placed, unresolved = await regions.map_page(page, tmp_path, ctx=lambda l: None,
                                                    usage_sink=None, raw_sink=None)
    assert [(r.kind, r.added_by, r.box) for r in placed] == [("UNCLASSIFIED", "FALLBACK", (0, 0, 400, 300))]
    assert unresolved and "구역 지도 실패" in unresolved[0]


@pytest.mark.asyncio
async def test_map_page_adds_coverage_region(tmp_path):
    page = _page(tmp_path, draw_boxes=[(10, 10, 60, 40), (300, 250, 360, 290)])
    st = NS(layout_region_model="anthropic:claude-sonnet-5-5", layout_region_image_max_px=200,
            layout_ink_threshold=160, layout_uncovered_min_area_px=200,
            layout_cover_margin_ratio=0.015, layout_coverage_max_overlap=0.3)

    async def fake(spec, prompt, images, schema, **k):
        return RegionMap(regions=[Region(kind="PROSE", bbox=[0, 0, 0.25, 0.25],
                                         reading_order=1, table=None)])
    with patch.object(regions, "get_settings", return_value=st), \
         patch.object(regions, "measured_generate", fake):
        placed, _ = await regions.map_page(page, tmp_path, ctx=lambda l: None,
                                           usage_sink=None, raw_sink=None)
    assert [r.added_by for r in placed] == ["MODEL", "COVERAGE"]
    assert placed[1].kind == "UNCLASSIFIED" and placed[1].region_id == "p1-r2"


@pytest.mark.asyncio
async def test_map_page_propagates_budget_exceeded(tmp_path):
    from app.ingest.providers.budget import BudgetExceeded
    page = _page(tmp_path)
    st = NS(layout_region_model="anthropic:claude-sonnet-5-5", layout_region_image_max_px=200,
            layout_ink_threshold=160, layout_uncovered_min_area_px=200,
            layout_cover_margin_ratio=0.015, layout_coverage_max_overlap=0.3)

    async def over(*a, **k):
        raise BudgetExceeded("상한")
    with patch.object(regions, "get_settings", return_value=st), \
         patch.object(regions, "measured_generate", over):
        with pytest.raises(BudgetExceeded):
            await regions.map_page(page, tmp_path, ctx=lambda l: None,
                                   usage_sink=None, raw_sink=None)


def test_uncovered_edge_cells_do_not_leak(tmp_path):
    page = _page(tmp_path, draw_boxes=[(13, 13, 202, 202)])
    assert regions.uncovered_boxes(page.path, [(13, 13, 203, 203)],
                                   ink_threshold=160, min_area_px=200, **COVER) == []


def test_uncovered_large_page_unaligned_cover(tmp_path):
    p = tmp_path / "big.png"
    img = Image.new("RGB", (1600, 1200), "white")
    d = ImageDraw.Draw(img)
    d.rectangle((53, 53, 802, 902), fill="black")
    d.rectangle((1200, 100, 1300, 160), fill="black")
    img.save(p)
    out = regions.uncovered_boxes(p, [(53, 53, 803, 903)], ink_threshold=160, min_area_px=400, **COVER)
    assert len(out) == 1
    x0, y0, x1, y1 = out[0]
    assert x0 <= 1200 and y0 <= 100 and x1 >= 1301 and y1 >= 161


def test_uncovered_thin_line_survives_downscale(tmp_path):
    p = tmp_path / "line.png"
    img = Image.new("RGB", (1600, 1200), "white")
    ImageDraw.Draw(img).line((1000, 500, 1000, 700), fill="black", width=1)
    img.save(p)
    out = regions.uncovered_boxes(p, [], ink_threshold=160, min_area_px=100, **COVER)
    assert len(out) == 1
    assert out[0][0] <= 1000 < out[0][2] and out[0][1] <= 500 and out[0][3] >= 700


def _table_page(tmp_path, footnote=False):
    """실제 스캔 크기(1600×1130)에 두꺼운 테두리 고리와 칸 글자가 있는 표."""
    p = tmp_path / "table.png"
    img = Image.new("RGB", (1600, 1130), "white")
    d = ImageDraw.Draw(img)
    d.rectangle((100, 100, 1500, 900), outline="black", width=6)     # 테두리 고리
    for y in range(160, 880, 60):
        d.line((100, y, 1500, y), fill="black", width=2)             # 행 구분선
        d.rectangle((140, y - 40, 400, y - 20), fill="black")        # 칸 글자 덩어리
    if footnote:
        d.rectangle((120, 980, 900, 1010), fill="black")             # 표 아래 각주 한 줄
    img.save(p)
    return p


@pytest.mark.parametrize("inset", [5, 30])
def test_table_border_ring_outside_model_box_is_not_a_candidate(tmp_path, inset):
    p = _table_page(tmp_path)
    box = (100 + inset, 100 + inset, 1501 - inset, 901 - inset)
    assert regions.uncovered_boxes(p, [box], ink_threshold=160, min_area_px=400, **COVER) == []


def test_footnote_below_table_still_found(tmp_path):
    p = _table_page(tmp_path, footnote=True)
    out = regions.uncovered_boxes(p, [(130, 130, 1471, 871)], ink_threshold=160,
                                  min_area_px=400, **COVER)
    assert len(out) == 1
    x0, y0, x1, y1 = out[0]
    assert y0 >= 900 and x0 <= 120 and x1 >= 900 and y1 >= 1010


def test_uncovered_dust_dropped_by_ink_count(tmp_path):
    """흩어진 점들이 격자 칸으로 이어져 상자는 커도 글자 화소가 적으면 버린다."""
    p = tmp_path / "dust.png"
    img = Image.new("RGB", (400, 300), "white")
    d = ImageDraw.Draw(img)
    for x in range(100, 300, 6):
        d.point((x, 150), fill="black")
    img.save(p)
    assert regions.uncovered_boxes(p, [], ink_threshold=160, min_area_px=200, **COVER) == []


def test_cover_margin_px():
    assert regions.cover_margin_px(1600, 1130, 0.015) == 17
    assert regions.cover_margin_px(200, 100, 0.015) == 4


def test_to_box_pads_short_bbox_with_full_extent():
    assert regions._to_box([0.5], 100, 100) == (50, 0, 100, 100)
