from unittest.mock import patch

import pytest
from PIL import Image

from app.ingest.layout import transcribe as t
from app.ingest.layout.schemas import (BandRow, BandRows, Caps, PageImage, PlacedRegion,
                                       TableInfo, TranscribedRow)


CLAMP = dict(min_row_px=14, max_row_px=80)


def _row(label, cells, top=False, bottom=False):
    return BandRow(row_label=label, cells=cells, cut_top=top, cut_bottom=bottom)


def test_plan_bands_overlap_and_cover():
    bands = t.plan_bands((0, 0, 100, 200), 10, rows_per_band=4, overlap_rows=1, default_row_px=40,
                         **CLAMP)
    assert bands[0] == (0, 0, 100, 80)
    assert bands[1][1] == 60                     # 한 행(20px) 겹침
    assert bands[-1][3] == 200
    assert t.plan_bands((0, 0, 100, 50), None, rows_per_band=4, overlap_rows=1,
                        default_row_px=40, **CLAMP) == [(0, 0, 100, 50)]


def test_crop_zoom(tmp_path):
    src = tmp_path / "p.png"
    Image.new("RGB", (100, 100), "white").save(src)
    out = t.crop_zoom(src, (10, 10, 30, 20), 2.0, tmp_path / "c.png")
    assert Image.open(out).size == (40, 20)


def test_merge_labeled_overlap_keeps_first_and_flags_mismatch():
    header = ["번호", "이름", "값"]
    rows, flags = t.merge_bands([
        [_row("1", ["1", "메뉴A", "10"]), _row("2", ["2", "메뉴B", "20"])],
        [_row("2", ["2", "메뉴B", "28"]), _row("3", ["3", "메뉴C", "30"])],
    ], header)
    assert [r.label for r in rows] == ["1", "2", "3"]
    assert rows[1].cells[2] == "20"
    assert [(f.row_index, f.col, f.reason) for f in flags] == [(1, 2, "OVERLAP_MISMATCH")]


def test_merge_unlabeled_overlap_dedup():
    header = ["이름", "값"]
    rows, flags = t.merge_bands([
        [_row(None, ["메뉴A", "10"]), _row(None, ["메뉴B", "20"])],
        [_row(None, ["메뉴B", "20"]), _row(None, ["메뉴C", "30"])],
    ], header)
    assert [r.cells[0] for r in rows] == ["메뉴A", "메뉴B", "메뉴C"] and flags == []


def test_merge_drops_cut_rows_at_band_edges():
    header = ["이름", "값"]
    rows, _ = t.merge_bands([
        [_row(None, ["메뉴A", "10"]), _row(None, ["메뉴", ""], bottom=True)],
        [_row(None, ["메뉴B", "20"], top=False)],
    ], header)
    assert [r.cells[0] for r in rows] == ["메뉴A", "메뉴B"]


def test_fill_down():
    rows = [TranscribedRow("1", ["1", "섞기", "a"], 0), TranscribedRow("2", ["2", "↑", "b"], 0)]
    t.fill_down(rows)
    assert rows[1].cells[1] == "섞기"


def test_column_count_flag():
    rows = [TranscribedRow("1", ["1", "메뉴A"], 0), TranscribedRow("2", ["2", "메뉴B", "20", "?"], 0),
            TranscribedRow("3", ["3", "메뉴C", "30"], 0)]
    flags = t.check_table(rows, ["번호", "이름", "값"], None, 0)
    assert {(f.row_index, f.reason) for f in flags} == {(0, "COLUMN_COUNT"), (1, "COLUMN_COUNT")}


def test_row_missing_and_count_flags():
    rows = [TranscribedRow("1", ["1", "a"], 0), TranscribedRow("3", ["3", "c"], 1)]
    flags = t.check_table(rows, ["번호", "이름"], 4, 0)
    reasons = sorted(f.reason for f in flags)
    assert reasons == ["ROW_COUNT", "ROW_MISSING"]


def test_row_count_flag_with_no_rows():
    flags = t.check_table([], ["번호", "이름"], 3, 0)
    assert [(f.row_index, f.band_index, f.reason) for f in flags] == [(0, 0, "ROW_COUNT")]


def test_needs_reroute():
    bad = [TranscribedRow(None, ["한 줄 글"], 0), TranscribedRow(None, ["또 한 줄"], 0)]
    assert t.needs_reroute(bad, ["번호", "이름", "값"]) is True
    good = [TranscribedRow("1", ["1", "a", "b"], 0)]
    assert t.needs_reroute(good, ["번호", "이름", "값"]) is False


def _region_and_page(tmp_path):
    src = tmp_path / "p.png"
    Image.new("RGB", (100, 200), "white").save(src)
    page = PageImage(1, src, 100, 200)
    info = TableInfo(header_columns=["번호", "이름", "값"], expected_rows=6, row_label_column=0)
    region = PlacedRegion(1, "p1-r1", "TABLE", (0, 0, 100, 200), 1, info, "MODEL")
    return region, page


@pytest.mark.asyncio
async def test_transcribe_table_merges_bands_and_prefixes_flags(tmp_path):
    region, page = _region_and_page(tmp_path)
    replies = iter([
        BandRows(rows=[_row("1", ["1", "메뉴A", "10"]), _row("2", ["2", "메뉴B", "20"])]),
        BandRows(rows=[_row("2", ["2", "메뉴B", "28"]), _row("3", ["3", "메뉴C", "30"])]),
    ])

    async def fake(*args, **kwargs):
        return next(replies)

    caps = Caps(bands_left=10, recheck_calls_left=0)
    with patch.object(t, "measured_generate", side_effect=fake):
        res = await t.transcribe_table(region, page, tmp_path, caps=caps, ctx=lambda s: None,
                                       usage_sink=None, raw_sink=None,
                                       spec_text="gemini:gemini-3.6-flash")
    assert len(res.band_boxes) == 2
    assert [r.label for r in res.rows] == ["1", "2", "3"]
    assert "p1-r1:1:2" in [f.cell_id for f in res.flags]
    assert all(f.cell_id.startswith("p1-r1:") for f in res.flags)
    assert caps.bands_left == 8


@pytest.mark.asyncio
async def test_transcribe_table_stops_when_no_bands_left(tmp_path):
    region, page = _region_and_page(tmp_path)
    caps = Caps(bands_left=0, recheck_calls_left=0)
    with patch.object(t, "measured_generate") as mg:
        with pytest.raises(RuntimeError):
            await t.transcribe_table(region, page, tmp_path, caps=caps, ctx=lambda s: None,
                                     usage_sink=None, raw_sink=None,
                                     spec_text="gemini:gemini-3.6-flash")
    mg.assert_not_called()


def test_merge_same_label_in_one_band_and_nonadjacent_bands_kept():
    header = ["번호", "이름"]
    rows, flags = t.merge_bands([
        [_row("1", ["1", "가"]), _row("1", ["1", "나"]), _row("3", ["3", "다"])],
        [_row("4", ["4", "라"])],
        [_row("3", ["3", "마"])],
    ], header)
    assert [r.cells[1] for r in rows] == ["가", "나", "다", "라", "마"]
    assert flags == []


def test_merge_unlabeled_identical_real_rows_survive():
    header = ["이름", "값"]
    x, a, b = ["X", "0"], ["A", "1"], ["B", "2"]
    rows, flags = t.merge_bands([
        [_row(None, x), _row(None, a)],
        [_row(None, a), _row(None, a), _row(None, b)],
    ], header)
    assert [r.cells[0] for r in rows] == ["X", "A", "A", "B"] and flags == []


def test_merge_cut_pair_kept_with_row_missing_flag():
    header = ["이름", "값"]
    rows, flags = t.merge_bands([
        [_row(None, ["A", "1"]), _row(None, ["B", ""], bottom=True)],
        [_row(None, ["", "2"], top=True), _row(None, ["C", "3"])],
    ], header)
    assert [r.cells[0] for r in rows] == ["A", "", "C"]
    assert rows[1].cut_top is True
    assert [(f.row_index, f.col, f.reason, f.band_index) for f in flags] == [(1, None, "ROW_MISSING", 1)]


def test_merge_cut_top_dropped_when_prev_not_cut():
    header = ["이름", "값"]
    rows, flags = t.merge_bands([
        [_row(None, ["A", "1"])],
        [_row(None, ["", "1"], top=True), _row(None, ["C", "3"])],
    ], header)
    assert [r.cells[0] for r in rows] == ["A", "C"] and flags == []


def test_row_missing_one_flag_per_gap_at_band_after_gap():
    rows = [TranscribedRow("1", ["1", "a"], 0), TranscribedRow("4", ["4", "d"], 1),
            TranscribedRow("7", ["7", "g"], 2)]
    flags = [f for f in t.check_table(rows, ["번호", "이름"], 7, 0) if f.reason == "ROW_MISSING"]
    assert [(f.row_index, f.band_index) for f in flags] == [(1, 1), (2, 2)]


def test_row_missing_misread_guard_single_flag():
    rows = [TranscribedRow("1", ["1", "a"], 0), TranscribedRow("9", ["9", "i"], 0),
            TranscribedRow("20", ["20", "t"], 1)]
    flags = [f for f in t.check_table(rows, ["번호", "이름"], 3, 0) if f.reason == "ROW_MISSING"]
    assert len(flags) == 1


@pytest.mark.asyncio
async def test_transcribe_table_band_indexes_returns_raw_rows(tmp_path):
    region, page = _region_and_page(tmp_path)

    async def fake(*args, **kwargs):
        return BandRows(rows=[_row("2", ["2", "↑", "20"], top=True), _row("3", ["3", "메뉴C"], bottom=True)])

    caps = Caps(bands_left=10, recheck_calls_left=0)
    with patch.object(t, "measured_generate", side_effect=fake):
        res = await t.transcribe_table(region, page, tmp_path, caps=caps, ctx=lambda s: None,
                                       usage_sink=None, raw_sink=None,
                                       spec_text="gemini:gemini-3.6-flash", band_indexes=[1])
    assert [(r.label, r.band_index, r.cut_top, r.cut_bottom) for r in res.rows] == [
        ("2", 1, True, False), ("3", 1, False, True)]
    assert res.rows[0].cells[1] == "↑"             # fill_down 안 함
    assert res.flags == [] and res.rerouted is False
    assert caps.bands_left == 9


@pytest.mark.asyncio
async def test_transcribe_text_dedup_only_leading_overlap(tmp_path):
    region, page = _region_and_page(tmp_path)
    region.table = None
    replies = iter([
        t.ProseLines(lines=["가", "HOT", "나"]),
        t.ProseLines(lines=["나", "HOT", "HOT", "다"]),
    ])

    async def fake(*args, **kwargs):
        return next(replies)

    caps = Caps(bands_left=10, recheck_calls_left=0)
    with patch.object(t, "measured_generate", side_effect=fake), \
            patch.object(t, "plan_bands", return_value=[(0, 0, 100, 100), (0, 90, 100, 200)]):
        res = await t.transcribe_text(region, page, tmp_path, kind_prompt="prose", caps=caps,
                                      ctx=lambda s: None, usage_sink=None, raw_sink=None)
    assert res.lines == ["가", "HOT", "나", "HOT", "HOT", "다"]


def test_merge_no_alignment_keeps_genuine_row():
    header = ["이름", "값"]
    A, B, C, D, E = (["A", "1"], ["B", "2"], ["C", "3"], ["D", "4"], ["E", "5"])
    rows, _ = t.merge_bands([[_row(None, A), _row(None, B), _row(None, C), _row(None, D)],
                             [_row(None, A), _row(None, E)]], header)
    assert [r.cells[0] for r in rows] == ["A", "B", "C", "D", "A", "E"]


def test_merge_labeled_only_leading_aligned_row_merged():
    header = ["번호", "이름"]
    rows, flags = t.merge_bands([
        [_row("1", ["1", "가"]), _row("2", ["2", "나"])],
        [_row("2", ["2", "나"]), _row("1", ["1", "다"]), _row("1", ["1", "라"])],
    ], header)
    assert [r.label for r in rows] == ["1", "2", "1", "1"] and flags == []


def test_merge_aligned_labeled_mismatch_flag():
    header = ["번호", "이름"]
    rows, flags = t.merge_bands([[_row("1", ["1", "가"]), _row("2", ["2", "나"])],
                                 [_row("2", ["2", "너"]), _row("3", ["3", "다"])]], header)
    assert [(f.row_index, f.col, f.reason) for f in flags] == [(1, 1, "OVERLAP_MISMATCH")]
    assert rows[1].cells[1] == "나"


@pytest.mark.asyncio
async def test_transcribe_text_hot_opening_band_survives(tmp_path):
    region, page = _region_and_page(tmp_path)
    region.table = None
    replies = iter([t.ProseLines(lines=["가", "HOT"]), t.ProseLines(lines=["HOT", "HOT", "다"])])

    async def fake(*args, **kwargs):
        return next(replies)

    caps = Caps(bands_left=10, recheck_calls_left=0)
    with patch.object(t, "measured_generate", side_effect=fake), \
            patch.object(t, "plan_bands", return_value=[(0, 0, 100, 100), (0, 90, 100, 200)]):
        res = await t.transcribe_text(region, page, tmp_path, kind_prompt="prose", caps=caps,
                                      ctx=lambda s: None, usage_sink=None, raw_sink=None)
    assert res.lines == ["가", "HOT", "HOT", "다"]


def test_plan_bands_clamps_too_many_expected_rows():
    """1000px 에 101행(행 9.9px) → 14px 로 묶어 71행 → 띠 수가 101행 기준보다 적다."""
    bands = t.plan_bands((0, 0, 100, 1000), 101, rows_per_band=5, overlap_rows=1,
                         default_row_px=40, **CLAMP)
    unclamped = t.plan_bands((0, 0, 100, 1000), 101, rows_per_band=5, overlap_rows=1,
                             default_row_px=40, min_row_px=1, max_row_px=1000)
    assert len(bands) == 18 and len(unclamped) == 25
    assert all(b[3] - b[1] >= 5 * 14 for b in bands[:-1])
    assert bands[-1][3] == 1000


def test_plan_bands_clamps_too_few_expected_rows():
    """1000px 에 10행(행 100px) → 80px 상한 → 13행(행 약 76.9px)."""
    bands = t.plan_bands((0, 0, 100, 1000), 10, rows_per_band=5, overlap_rows=1,
                         default_row_px=40, **CLAMP)
    assert bands[0] == (0, 0, 100, 385)                       # 5 × 1000/13
    assert len(bands) == 3 and bands[1][1] == 308 and bands[-1][3] == 1000   # 띠 높이 500→385px


def test_merge_window_from_geometry():
    boxes = [(0, 0, 100, 100), (0, 58, 100, 200)]              # 42px 겹침
    assert t.merge_window(boxes, overlap_rows=1, min_row_px=14) == 3
    assert t.merge_window([(0, 0, 100, 100)], overlap_rows=1, min_row_px=14) == 2


@pytest.mark.asyncio
async def test_transcribe_table_precheck_raises_without_calls(tmp_path):
    region, page = _region_and_page(tmp_path)                 # 띠 2개 필요
    caps = Caps(bands_left=1, recheck_calls_left=0)
    with patch.object(t, "measured_generate") as mg:
        with pytest.raises(RuntimeError, match="띠 호출 상한 부족"):
            await t.transcribe_table(region, page, tmp_path, caps=caps, ctx=lambda s: None,
                                     usage_sink=None, raw_sink=None,
                                     spec_text="gemini:gemini-3.6-flash")
    mg.assert_not_called()
    assert caps.bands_left == 1                               # 쓰지 않았다


def test_duplicated_numeric_label_flags_later_row():
    rows = [TranscribedRow("1", ["1", "a"], 0), TranscribedRow("2", ["2", "b"], 0),
            TranscribedRow("2", ["2", "b2"], 1), TranscribedRow("3", ["3", "c"], 1)]
    flags = t.check_table(rows, ["번호", "이름"], None, 0)
    assert [(f.row_index, f.col, f.reason, f.band_index) for f in flags] == [(2, None, "ROW_COUNT", 1)]


def test_merge_keeps_mid_band_rows_marked_cut():
    """잘림 표시가 띠 가운데 행에 붙어도 버리지 않는다 — 가장자리 행만 뜻이 있다."""
    header = ["이름", "값"]
    rows, flags = t.merge_bands([
        [_row(None, ["A", "1"]), _row(None, ["B", "2"], bottom=True), _row(None, ["C", "3"])],
        [_row(None, ["D", "4"]), _row(None, ["E", "5"], top=True), _row(None, ["F", "6"])],
    ], header)
    assert [r.cells[0] for r in rows] == ["A", "B", "C", "D", "E", "F"] and flags == []
