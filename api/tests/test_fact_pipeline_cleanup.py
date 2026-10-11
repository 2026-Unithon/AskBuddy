"""사실 추출 흐름을 오프라인으로 검증한다."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch
import pytest
from app.ingest import extract
from app.ingest.pipeline import _extract_facts_all


@pytest.mark.asyncio
async def test_mock_uses_fact_extraction_with_refs():
    with patch.object(extract, "get_settings", return_value=NS(ingest_mode="mock")):
        outcome = await _extract_facts_all(source_id=9, source_type="VOICE", text="mock",
                                           media=[], glossary=[], segments=[])
    assertions, unresolved = outcome.assertions, outcome.unresolved
    assert len(assertions) == 4 and unresolved
    assert all(a.local_ref for a in assertions)


@pytest.mark.asyncio
async def test_preview_reads_categories_then_extracts_facts(tmp_path, capsys):
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
    assert "사실 4건" in capsys.readouterr().out
