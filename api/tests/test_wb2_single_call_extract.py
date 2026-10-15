"""Phase B 추가 S3 — 한 호출 추출기. 기존 추출 요청은 바뀌지 않는다(D16)."""
import asyncio
from types import SimpleNamespace as NS
from unittest.mock import patch

from app.ingest.extract import gemini
from app.ingest.schemas import (FactExtractionResult, IntakeFactExtractionResult,
                                IntakeLocatedFactExtractionResult)


def test_base_prompt_unchanged_and_suffix_appended():
    base = gemini.render_facts_prompt(source_type="SCAN", text="음료Z 샷 2", glossary=[])
    merged = gemini.render_facts_intake_prompt(source_type="SCAN", text="음료Z 샷 2",
                                               glossary=[], hints=("RECIPE",))
    assert merged.startswith(base.rstrip("\n") + "\n\n## 추가 — 자료의 용도 판정")
    assert "점주가 고른 종류: RECIPE" in merged
    no_hint = gemini.render_facts_intake_prompt(source_type="SCAN", text="x", glossary=[], hints=())
    assert "점주가 고른 종류: (고르지 않음)" in no_hint


def test_intake_schema_extends_fact_schema():
    props = IntakeFactExtractionResult.model_json_schema()["properties"]
    assert {"assertions", "unresolved", "intake_ranking", "intake_reason"} <= set(props)
    assert "intake_ranking" not in FactExtractionResult.model_json_schema()["properties"]
    assert issubclass(IntakeLocatedFactExtractionResult, IntakeFactExtractionResult) is False
    assert "intake_ranking" in IntakeLocatedFactExtractionResult.model_json_schema()["properties"]


def test_gemini_single_call_uses_merged_prompt_and_schema():
    seen = {}

    async def fake_measured(prompt, media, sink, context, **kw):
        seen.update(prompt=prompt, schema=kw["schema"])
        return NS(text='{"assertions": [], "unresolved": [], "intake_ranking": '
                       '[{"logic": "NOTICE", "score": 0.8}], "intake_reason": "휴무"}',
                  usage={}, finish_reason="STOP", raw_response_id=None, reused=False)

    s = NS(gemini_api_key="x", extract_locator_hints=False, extract_max_output_tokens=None)
    with patch.object(gemini, "get_settings", lambda: s), \
         patch.object(gemini, "_measured_call", fake_measured):
        out = asyncio.run(gemini.extract_facts_with_intake(
            source_id=1, source_type="SCAN", text="토요일 휴무", glossary=[], media=[],
            hints=(), usage_sink=None, usage_context=None, raw_sink=None))
    assert seen["schema"] is IntakeFactExtractionResult
    assert "## 추가 — 자료의 용도 판정" in seen["prompt"]
    assert out.intake_ranking[0].logic == "NOTICE"


def test_mock_single_call_ranks_hint_or_recipe():
    from app.ingest.extract import mock
    out = asyncio.run(mock.extract_facts_with_intake(
        source_id=1, source_type="SCAN", text="(목 모드)", glossary=[], media=[],
        hints=("POLICY",), usage_context=None, raw_sink=None))
    assert out.intake_ranking[0].logic == "POLICY"
    out = asyncio.run(mock.extract_facts_with_intake(
        source_id=1, source_type="SCAN", text="(목 모드)", glossary=[], media=[], hints=(),
        usage_context=None, raw_sink=None))
    assert out.intake_ranking[0].logic == "RECIPE"
