"""Phase A Task 1 — 업로드는 사실 경로 하나만 남는다."""
from __future__ import annotations

import inspect
from pathlib import Path

from app import config
from app.ingest import extract, pipeline, schemas
from app.ingest.extract import gemini, mock

REMOVED_FLAGS = ("w_entity_revision_enabled", "w_upload_proposals_enabled", "w_fact_assembly_enabled")


def test_settings_have_no_upload_flags():
    fields = config.Settings.model_fields
    for name in REMOVED_FLAGS:
        assert name not in fields, name


def test_legacy_assembly_is_gone():
    for module, name in ((pipeline, "assemble_assertions"), (pipeline, "_persist"),
                         (pipeline, "_ledger_keys"), (extract, "assemble_cards"),
                         (gemini, "assemble"), (gemini, "render_assemble_prompt"),
                         (mock, "assemble"), (mock, "_assembled"),
                         (schemas, "ExtractedCard"), (schemas, "ExtractionResult")):
        assert not hasattr(module, name), f"{module.__name__}.{name}"
    prompt = Path(pipeline.__file__).resolve().parents[2] / "prompts" / "assemble_cards.ko.txt"
    assert not prompt.exists()


def test_no_flag_reads_left_in_ingest():
    for module in (pipeline,):
        source = inspect.getsource(module)
        for name in REMOVED_FLAGS:
            assert name not in source, name


ALL_REMOVED = REMOVED_FLAGS + ("w_fact_card_edit_enabled", "w_owner_answer_raw_publish")


def test_no_removed_flag_names_in_code():
    """지운 플래그 이름이 코드·스크립트·테스트에 남지 않는다(test_wa_*.py 는 부재 단언용이라 제외)."""
    root = Path(pipeline.__file__).resolve().parents[2]  # api/
    hits = []
    for folder in ("app", "scripts", "tests"):
        for path in (root / folder).rglob("*.py"):
            if path.name.startswith("test_wa_"):
                continue
            text = path.read_text(encoding="utf-8")
            for name in ALL_REMOVED:
                if name in text or name.upper() in text:
                    hits.append(f"{path.relative_to(root)}:{name}")
    assert hits == []
