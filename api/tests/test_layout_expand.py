from types import SimpleNamespace as NS
from unittest.mock import patch

import pytest

from app.ingest.layout import expand
from app.ingest.layout.schemas import (ExpandResult, LayoutFact, PlacedRegion, ProseResult,
                                       TableInfo, TableResult, TranscribedRow)
from app.ingest.schemas import Evidence, ExtractedAssertion, FactExtractionResult

ST = NS(layout_expand_model="gemini:gemini-3.6-flash", layout_expand_batch_rows=10, layout_concurrency=4,
        layout_fact_confidence=0.9)


def _table(rows=None):
    region = PlacedRegion(2, "p2-r1", "TABLE", (0, 0, 100, 100), 1,
                          TableInfo(header_columns=["번호", "이름", "가격", "얼음"], expected_rows=2,
                                    row_label_column=0), "MODEL")
    rows = rows or [TranscribedRow("1", ["1", "메뉴A", "1,500", "x"], 0),
                    TranscribedRow("2", ["2", "메뉴B", "2000", "가득"], 0)]
    return TableResult(region, ["번호", "이름", "가격", "얼음"], rows, [], [(0, 0, 100, 100)])


def _fact(row, value, attribute="가격", polarity="AFFIRM", original=""):
    return LayoutFact(row_ref=row, original_assertion=original or value, subject="메뉴", variant="",
                      attribute=attribute, value=value, unit="원" if attribute == "가격" else "",
                      polarity=polarity, conditions=[], exceptions=[], order=0)


def test_row_tokens_skip_label_column_and_unreadable():
    t = _table()
    assert expand.row_tokens(t, 0) == [("NUM", "1500"), ("NEG", "얼음")]
    t.unreadable[(1, 2)] = "번짐"
    assert expand.row_tokens(t, 1) == []


def test_row_tokens_decimal_and_range():
    t = _table([TranscribedRow("1", ["1", "메뉴A", "26.5", "3~4"], 0)])
    assert expand.row_tokens(t, 0) == [("NUM", "26.5"), ("NUM", "3"), ("NUM", "4")]


def test_missing_tokens():
    tokens = [("NUM", "1500"), ("NEG", "얼음")]
    facts = [_fact("1", "1500")]
    assert expand.missing_tokens(tokens, facts) == [("NEG", "얼음")]
    facts.append(_fact("1", "", attribute="얼음", polarity="NEGATE"))
    assert expand.missing_tokens(tokens, facts) == []


def test_missing_tokens_digit_boundary():
    assert expand.missing_tokens([("NUM", "25")], [_fact("1", "225")]) == [("NUM", "25")]
    assert expand.missing_tokens([("NUM", "5")], [_fact("1", "26.5")]) == [("NUM", "5")]
    assert expand.missing_tokens([("NUM", "225")], [_fact("1", "225")]) == []


def test_layout_locator_not_in_json_schema():
    assert "_layout_locator" not in ExtractedAssertion.model_json_schema()["properties"]


@pytest.mark.asyncio
async def test_expand_table_retries_missing_then_unresolved():
    t = _table()
    replies = [ExpandResult(facts=[_fact("R1", "1500"), _fact("R2", "2000")]),
               ExpandResult(facts=[])]

    async def fake(spec, prompt, images, schema, **k):
        return replies.pop(0)
    with patch.object(expand, "get_settings", return_value=ST), \
         patch.object(expand, "measured_generate", fake):
        assertions, unresolved = await expand.expand_table(t, ctx=lambda l: None,
                                                           usage_sink=None, raw_sink=None)
    assert len(assertions) == 2
    assert assertions[0]._layout_locator == {"page": 2, "region": "p2-r1", "bbox": [0, 0, 100, 100], "row": "1"}
    assert assertions[0].local_ref == "p2-r1.0.0" and assertions[0].confidence == 0.9
    assert unresolved == ["[전개 미반영] 2쪽 p2-r1 행 1: 얼음(x)"]


@pytest.mark.asyncio
async def test_retry_adds_fact_to_row_with_existing_fact_gets_unique_refs():
    t = _table()
    replies = [ExpandResult(facts=[_fact("R1", "1500"), _fact("R2", "2000")]),
               ExpandResult(facts=[_fact("R1", "", attribute="얼음", polarity="NEGATE")])]

    async def fake(spec, prompt, images, schema, **k):
        return replies.pop(0)
    with patch.object(expand, "get_settings", return_value=ST), \
         patch.object(expand, "measured_generate", fake):
        assertions, unresolved = await expand.expand_table(t, ctx=lambda l: None,
                                                           usage_sink=None, raw_sink=None)
    assert [a.local_ref for a in assertions] == ["p2-r1.0.0", "p2-r1.0.1", "p2-r1.1.0"]
    assert unresolved == []


@pytest.mark.asyncio
async def test_unreadable_cell_not_expanded():
    t = _table()
    t.unreadable[(1, 2)] = "번짐"
    captured = {}

    async def fake(spec, prompt, images, schema, **k):
        captured["prompt"] = prompt
        return ExpandResult(facts=[_fact("R1", "1500"),
                                   _fact("R1", "", attribute="얼음", polarity="NEGATE")])
    with patch.object(expand, "get_settings", return_value=ST), \
         patch.object(expand, "measured_generate", fake):
        assertions, unresolved = await expand.expand_table(t, ctx=lambda l: None,
                                                           usage_sink=None, raw_sink=None)
    assert "2000" not in captured["prompt"] and "[판독 불가]" in captured["prompt"]
    assert "[판독 불가] 2쪽 p2-r1 행 2 '가격' 칸: 번짐" in unresolved


@pytest.mark.asyncio
async def test_expand_text_prefixes_and_locator():
    region = PlacedRegion(1, "p1-r2", "PROSE", (1, 2, 3, 4), 1, None, "MODEL")
    prose = ProseResult(region, ["문장 하나"])
    a = ExtractedAssertion(local_ref="f1", original_assertion="o", subject="s", attribute="a",
                           value="v", evidence=Evidence(), confidence=0.5)
    b = ExtractedAssertion(local_ref="f2", original_assertion="o", subject="s", attribute="a",
                           value="v", requires=["f1"], evidence=Evidence(), confidence=0.5)

    async def fake(**k):
        return FactExtractionResult(assertions=[a, b], unresolved=["x"])
    with patch("app.ingest.extract.extract_facts", fake):
        out, unresolved = await expand.expand_text(prose, source_id=7, glossary=[],
                                                   ctx=lambda l: None, usage_sink=None, raw_sink=None)
    assert [x.local_ref for x in out] == ["p1-r2.t.f1", "p1-r2.t.f2"]
    assert out[1].requires == ["p1-r2.t.f1"]
    assert out[0]._layout_locator == {"page": 1, "region": "p1-r2", "bbox": [1, 2, 3, 4]}
    assert unresolved == ["x"]


async def _run(t, replies):
    seen = []

    async def fake(spec, prompt, images, schema, **k):
        seen.append(prompt)
        return replies.pop(0)
    with patch.object(expand, "get_settings", return_value=ST), \
         patch.object(expand, "measured_generate", fake):
        out = await expand.expand_table(t, ctx=lambda l: None, usage_sink=None, raw_sink=None)
    return out, seen


@pytest.mark.asyncio
async def test_row_ref_normalized_and_unmatched_reported():
    t = _table()
    (assertions, unresolved), _ = await _run(t, [ExpandResult(facts=[
        _fact("[R1]", "1500"), _fact("r1", "", attribute="얼음", polarity="NEGATE"),
        _fact("R2", "2000"), _fact("행9", "777", original="엉뚱")])])
    assert len(assertions) == 3
    assert "[행 연결 실패] 2쪽 p2-r1: row_ref=행9 — 엉뚱" in unresolved


@pytest.mark.asyncio
async def test_duplicate_labels_go_to_right_rows():
    t = _table([TranscribedRow("1", ["1", "메뉴A", "1500", "가득"], 0),
                TranscribedRow("1", ["1", "메뉴B", "2000", "가득"], 0)])
    (assertions, unresolved), _ = await _run(t, [ExpandResult(facts=[
        _fact("R1", "1500"), _fact("R2", "2000")])])
    assert [a.value for a in assertions] == ["1500", "2000"]
    assert assertions[0].local_ref != assertions[1].local_ref
    assert unresolved == []


@pytest.mark.asyncio
async def test_retry_only_gap_rows_no_duplicates():
    t = _table()
    full = [_fact("R1", "1500"), _fact("R1", "", attribute="얼음", polarity="NEGATE"),
            _fact("R2", "2000")]
    first = ExpandResult(facts=[_fact("R1", "1500"), _fact("R2", "2000")])
    (assertions, unresolved), seen = await _run(t, [first, ExpandResult(facts=full)])
    assert len(assertions) == 3 and unresolved == []
    assert "[R2 |" not in seen[1] and "[R1 |" in seen[1]


def test_neg_covered_by_partial_name():
    f = _fact("R1", "", attribute="블렌더", polarity="NEGATE")
    assert expand.missing_tokens([("NEG", "블렌더 회전수")], [f]) == []


@pytest.mark.parametrize("raw,key", [("R1|라벨3", "R1"), ("R12 라벨 1", "R12"), ("[r2]", "R2"),
                                     ("R3", "R3"), ("라벨 1", "라벨1")])
def test_norm_ref_uses_leading_row_key(raw, key):
    assert expand._norm_ref(raw) == key


@pytest.mark.asyncio
async def test_row_ref_with_echoed_label_is_placed():
    t = _table()
    replies = [ExpandResult(facts=[_fact("R1 | 라벨 1", "1500"), _fact("R2|라벨2", "2000"),
                                   _fact("R1|라벨1", "", attribute="얼음", polarity="NEGATE")])]

    async def fake(spec, prompt, images, schema, **k):
        return replies.pop(0)
    with patch.object(expand, "get_settings", return_value=ST), \
         patch.object(expand, "measured_generate", fake):
        assertions, unresolved = await expand.expand_table(t, ctx=lambda l: None,
                                                           usage_sink=None, raw_sink=None)
    assert len(assertions) == 3 and unresolved == []
