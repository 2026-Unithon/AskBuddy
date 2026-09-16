"""레거시 제거 후 실제 호출 경계와 현재 fact/ref 흐름을 오프라인으로 검증한다."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch
import pytest
from app.ingest import extract
from app.ingest.pipeline import _extract_facts_all, assemble_assertions
from app.ingest.schemas import Evidence, ExtractedAssertion, ExtractionResult


@pytest.mark.asyncio
async def test_mock_uses_fact_extraction_and_assembly_with_refs():
    with patch.object(extract, "get_settings", return_value=NS(ingest_mode="mock")):
        assertions, unresolved = await _extract_facts_all(source_id=9, source_type="VOICE", text="mock",
                                                        media=[], glossary=[], segments=[])
        result = await assemble_assertions(source_id=9, assertions=assertions, categories=["준비"], glossary=[])
    assert len(assertions) == 4 and len(result.cards) == 3 and unresolved
    assert {f.ref for c in result.cards for f in c.facts} == {a.local_ref for a in assertions}
    assert all(c.evidence.source_id == 9 for c in result.cards)


@pytest.mark.asyncio
async def test_one_entity_two_variants_preserves_values_conditions_and_refs():
    assertions = [ExtractedAssertion(local_ref="hot", original_assertion="HOT 우유 180ml",
        subject="음료Z", variant="HOT", attribute="우유량", value="180", unit="ml", confidence=.9,
        conditions=["포장 주문"], evidence=Evidence(timestamp_sec=5)),
        ExtractedAssertion(local_ref="ice", original_assertion="ICE 우유 120ml",
        subject="음료Z", variant="ICE", attribute="우유량", value="120", unit="ml", confidence=.8,
        exceptions=["재고 부족"], order=2, evidence=Evidence(timestamp_sec=10))]
    with patch.object(extract, "get_settings", return_value=NS(ingest_mode="mock")):
        result = await assemble_assertions(source_id=1, assertions=assertions, categories=["레시피"], glossary=[])
    assert len(result.cards) == 1
    card = result.cards[0]
    assert all(t in card.content for t in ["HOT", "ICE", "180 ml", "120 ml", "포장 주문", "재고 부족", "순서: 2"])
    assert [(f.ref, f.value) for f in card.facts] == [("hot", "180 ml"), ("ice", "120 ml")]


@pytest.mark.asyncio
async def test_mock_missing_categories_keeps_extracted_assertions():
    with patch.object(extract, "get_settings", return_value=NS(ingest_mode="mock")):
        extracted = await extract.extract_facts(source_id=1, source_type="VOICE", text="mock", glossary=[])
        result = await assemble_assertions(source_id=1, assertions=extracted.assertions, categories=[], glossary=[])
    assert extracted.assertions and not result.cards and result.unresolved


@pytest.mark.asyncio
async def test_real_fact_and_assembly_prompts_have_separate_inputs():
    from app.ingest.extract import gemini
    raw = json.dumps({"assertions": [dict(local_ref="f1", original_assertion="음료Z ICE 우유 120ml",
                                         subject="음료Z", variant="ICE", attribute="우유량", value="120ml", confidence=.9)]})
    measured = AsyncMock(side_effect=[(raw, {}), (ExtractionResult().model_dump_json(), {})])
    with patch.object(extract, "get_settings", return_value=NS(ingest_mode="real")), \
         patch.object(gemini, "get_settings", return_value=NS(gemini_api_key="synthetic")), \
         patch.object(gemini, "_measured_call", measured):
        extracted = await extract.extract_facts(source_id=1, source_type="VOICE", text="원본 테스트 문장", glossary=[])
        await assemble_assertions(source_id=1, assertions=extracted.assertions, categories=["레시피"], glossary=[])
    first, second = measured.call_args_list
    assert "원본 테스트 문장" in first.args[0] and "사실만" in first.args[0]
    assert '"ref": "f1"' in second.args[0] and '"규격": "ICE"' in second.args[0]
    assert "한 카드 안에서 규격별로 표시" in second.args[0]
    assert first.kwargs["prompt_hash"] != second.kwargs["prompt_hash"]


@pytest.mark.asyncio
async def test_preview_reads_categories_then_uses_current_pipeline(tmp_path, capsys):
    script = Path(__file__).resolve().parents[1] / "scripts/extract_preview.py"
    spec = importlib.util.spec_from_file_location("fact_preview_test", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    source = tmp_path / "transcript.txt"
    source.write_text("합성 미리보기", encoding="utf-8")
    conn = NS(fetchval=AsyncMock(return_value=1), fetch=AsyncMock(side_effect=[[{"category_name": "준비"}], []]),
              close=AsyncMock())
    with patch.object(module.asyncpg, "connect", AsyncMock(return_value=conn)), \
         patch.object(module, "get_settings", return_value=NS(supabase_db_url="synthetic", ingest_mode="mock", confidence_threshold=.6)), \
         patch.object(extract, "get_settings", return_value=NS(ingest_mode="mock")), \
         patch.object(module.sys, "argv", ["preview", "--file", str(source)]):
        assert await module.main() == 0
    conn.close.assert_awaited_once()
    assert "사실 4건 → 카드 3건" in capsys.readouterr().out
