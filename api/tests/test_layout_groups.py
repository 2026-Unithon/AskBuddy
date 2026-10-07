"""Task 10 — 세로 병합 칸 처리와 규격 정규화. 실제 공급자를 부르지 않는다."""
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

import pytest
from PIL import Image

from app.ingest import layout
from app.ingest.layout import expand, groups
from app.ingest.layout.schemas import (ExpandResult, GroupSpan, GroupSpans, LayoutFact, PageImage,
                                       PlacedRegion, TableInfo, TableResult, TranscribedRow)
from app.ingest.providers import budget

ST = NS(layout_group_model="anthropic:claude-sonnet-5-5", layout_crop_max_px=2000)
EST = NS(layout_expand_model="gemini:gemini-3.6-flash", layout_expand_batch_rows=10, layout_concurrency=4,
         layout_fact_confidence=0.9)


def _table(labels=("1", "2", "3", "4"), cells=None):
    region = PlacedRegion(1, "p1-r1", "TABLE", (0, 0, 100, 100), 1,
                          TableInfo(header_columns=["구분", "번호", "이름"], expected_rows=len(labels),
                                    row_label_column=1), "MODEL")
    rows = [TranscribedRow(lb, list(cells[k]) if cells else ["조각", lb, f"메뉴{k}"], 0)
            for k, lb in enumerate(labels)]
    return TableResult(region, ["구분", "번호", "이름"], rows, [], [(0, 0, 100, 100)])


def _span(col=0, label="커피 HOT", first="2", last="3"):
    return GroupSpan(column_index=col, label=label, first_row=first, last_row=last)


def test_apply_spans_covers_numeric_range_only():
    t = _table()
    assert groups.apply_spans(t, [_span()]) == 2
    assert [r.cells[0] for r in t.rows] == ["조각", "커피 HOT", "커피 HOT", "조각"]
    assert t.group_columns == {0}


def test_apply_spans_ignores_bad_spans_and_nonnumeric_labels():
    t = _table(labels=("1", "가", "3"))
    bad = [_span(col=9), _span(col=-1), _span(first="가", last="3"), _span(first="1", last="x")]
    assert groups.apply_spans(t, bad) == 0
    assert groups.apply_spans(t, [_span(first="1", last="3")]) == 2     # "가" 행은 건너뜀
    assert t.rows[1].cells[0] == "조각"


def test_apply_spans_pads_short_rows():
    t = _table(labels=("1",), cells=[["x"]])
    t.rows[0].cells = []
    assert groups.apply_spans(t, [_span(col=2, first="1", last="1")]) == 1
    assert t.rows[0].cells == ["", "", "커피 HOT"]


@pytest.mark.parametrize("text,want", [("커피 HOT", "HOT"), ("차 ICE", "ICE"), ("ICE·HOT", ""),
                                       ("Iced", ""), ("", ""), ("hot", "HOT"), ("ICE/ice", "ICE")])
def test_variant_of(text, want):
    assert groups.variant_of(text) == want


def test_row_variant_only_from_covered_cells():
    t = _table(cells=[["x", "1", "ICE 메뉴"], ["y", "2", "메뉴"], ["z", "3", "메뉴"], ["w", "4", "메뉴"]])
    groups.apply_spans(t, [_span(label="커피 HOT", first="2", last="3")])
    assert groups.row_variant(t, 0) == ""          # span 없는 행: 메뉴명의 ICE 는 무시
    assert groups.row_variant(t, 1) == "HOT"
    assert groups.row_variant(t, 3) == ""


def test_row_variant_ambiguous_label():
    t = _table()
    groups.apply_spans(t, [_span(label="ICE HOT")])
    assert groups.row_variant(t, 1) == ""


# ---- 표 사실의 규격 정규화 ----
def _fact(variant, row="R1"):
    return LayoutFact(row_ref=row, original_assertion="o", subject="메뉴", variant=variant,
                      attribute="용량", value="225", unit="ml", polarity="AFFIRM", conditions=[],
                      exceptions=[], order=0)


async def _expand(table, variant):
    async def fake(spec, prompt, images, schema, **k):
        return ExpandResult(facts=[_fact(variant, "R1")])
    t = table
    with patch.object(expand, "get_settings", return_value=EST), \
         patch.object(expand, "measured_generate", fake):
        facts, _ = await expand.expand_table(t, ctx=lambda l: None, usage_sink=None, raw_sink=None)
    return facts


def _one_row(cell0="조각"):
    t = _table(labels=("1",), cells=[[cell0, "1", "메뉴A"]])
    return t


@pytest.mark.asyncio
async def test_expand_model_variant_with_zone_name_normalized():
    facts = await _expand(_one_row(), "차 HOT")
    assert facts[0].variant == "HOT" and facts[0].conditions == []


@pytest.mark.asyncio
async def test_expand_uses_row_variant_when_model_empty():
    t = _one_row()
    groups.apply_spans(t, [_span(label="차 ICE", first="1", last="1")])
    assert (await _expand(t, ""))[0].variant == "ICE"


@pytest.mark.asyncio
async def test_expand_keeps_size_variant():
    assert (await _expand(_one_row(), "L"))[0].variant == "L"


@pytest.mark.asyncio
async def test_expand_conflict_follows_row_and_notes():
    t = _one_row()
    groups.apply_spans(t, [_span(label="차 ICE", first="1", last="1")])
    f = (await _expand(t, "HOT"))[0]
    assert f.variant == "ICE" and "규격 불일치: 모델 HOT / 표 ICE" in f.conditions


# ---- resolve_groups ----
def _page(tmp_path):
    p = tmp_path / "page.png"
    Image.new("RGB", (100, 100), "white").save(p)
    return PageImage(1, p, 100, 100)


@pytest.mark.asyncio
async def test_resolve_groups_applies_spans_and_labels_call(tmp_path):
    t, calls = _table(), []

    async def fake(spec, prompt, images, schema, **k):
        calls.append((k["usage_context"], schema, len(images)))
        return GroupSpans(spans=[_span()])
    with patch.object(groups, "get_settings", return_value=ST), \
         patch.object(groups, "measured_generate", fake):
        notes = await groups.resolve_groups(t, _page(tmp_path), tmp_path, ctx=lambda l: l,
                                            usage_sink=None, raw_sink=None)
    assert notes == [] and t.group_rows == 2 and t.rows[1].cells[0] == "커피 HOT"
    assert calls == [("p1-r1.g", GroupSpans, 1)]


@pytest.mark.asyncio
async def test_resolve_groups_skips_without_numeric_labels(tmp_path):
    t = _table(labels=("가", "나"))
    mock = AsyncMock()
    with patch.object(groups, "get_settings", return_value=ST), \
         patch.object(groups, "measured_generate", mock):
        assert await groups.resolve_groups(t, _page(tmp_path), tmp_path, ctx=lambda l: l,
                                           usage_sink=None, raw_sink=None) == []
    mock.assert_not_called()


@pytest.mark.asyncio
async def test_resolve_groups_error_becomes_note_budget_propagates(tmp_path):
    t = _table()
    with patch.object(groups, "get_settings", return_value=ST), \
         patch.object(groups, "measured_generate", AsyncMock(side_effect=ValueError("x"))):
        notes = await groups.resolve_groups(t, _page(tmp_path), tmp_path, ctx=lambda l: l,
                                            usage_sink=None, raw_sink=None)
    assert notes == ["[병합 칸 실패] 1쪽 p1-r1: ValueError"]
    with patch.object(groups, "get_settings", return_value=ST), \
         patch.object(groups, "measured_generate", AsyncMock(side_effect=budget.BudgetExceeded("상한"))):
        with pytest.raises(budget.BudgetExceeded):
            await groups.resolve_groups(t, _page(tmp_path), tmp_path, ctx=lambda l: l,
                                        usage_sink=None, raw_sink=None)


# ---- 오케스트레이터 ----
@pytest.mark.asyncio
async def test_orchestrator_order_and_stats(tmp_path):
    t = _table()
    order = []
    stats = layout._new_stats()

    async def tt(*a, **k):
        order.append("transcribe")
        return t

    async def rr(table, *a, **k):
        order.append("rows")
        return table

    async def rc(*a, **k):
        order.append("cells")

    async def rg(table, *a, **k):
        order.append("groups")
        table.group_rows = 3
        return ["[병합 칸 실패] x"]

    async def ex(*a, **k):
        order.append("expand")
        return [], []
    with patch.object(layout.transcribe, "transcribe_table", tt), \
         patch.object(layout.recheck, "recheck_rows", rr), \
         patch.object(layout.recheck, "resolve_cells", rc), \
         patch.object(layout.groups, "resolve_groups", rg), \
         patch.object(layout.expand, "expand_table", ex):
        _, unresolved, _ = await layout._process_region(
            t.region, None, tmp_path, lambda l: l, None, [], 1, None, None, stats)
    assert order == ["transcribe", "rows", "cells", "groups", "expand"]
    assert stats["group_rows"] == 3 and "[병합 칸 실패] x" in unresolved
