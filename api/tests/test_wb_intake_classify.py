"""Phase B — 분류 호출 1회. 모델은 대역, 원장 문맥 stage=CLASSIFY, 실패 시 멈춤."""
import asyncio
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch

import pytest
from PIL import Image

from app.ingest.intake import classify
from app.ingest.intake.decide import IntakeClassificationError
from app.ingest.intake.ir import Candidate, Locator, ProbeResult

PROBE = ProbeResult("DOC_TEXT", (Candidate("c1", Locator("PAGE", "1", "1"), "음료Z 샷 2"),
                                 Candidate("c2", Locator("PAGE", "2", "2"), "", sampled=False)))


def _settings(**kw):
    base = dict(intake_classifier_model="gemini:gemini-3.6-flash",
                intake_classifier_max_output_tokens=2048, ingest_mode="real")
    return NS(**{**base, **kw})


def test_prompt_lists_only_sampled_and_hints():
    prompt, images = classify.render_prompt([PROBE], hints=("RECIPE",), context=None)
    assert "c1" in prompt and "음료Z 샷 2" in prompt and "### c2" not in prompt
    # 칩은 로직 이름 그대로 "점주가 고른 종류" 칸에 들어간다
    assert "RECIPE" in prompt.split("## 점주가 고른 종류")[1].split("## 맥락")[0]
    assert images == []


def test_prompt_no_hints_says_none():
    prompt, _ = classify.render_prompt([PROBE], hints=(), context="직원 질문: 시럽 어디?")
    assert "(고르지 않음)" in prompt and "직원 질문: 시럽 어디?" in prompt


def test_images_follow_candidates(tmp_path):
    img = tmp_path / "p1.jpg"; Image.new("RGB", (4, 4)).save(img)
    probe = ProbeResult("DOC_IMAGE", (Candidate("c1", Locator("PAGE", "1", "1"), "", (img,)),))
    prompt, images = classify.render_prompt([probe], hints=(), context=None)
    assert images == [img] and "[그림 1]" in prompt


def test_classify_calls_once_with_classify_stage():
    calls = []

    async def fake_generate(spec, prompt, images, schema, **kw):
        calls.append((spec, kw["usage_context"], kw["what"]))
        return schema.model_validate({"sections": [
            {"candidate_id": "c1", "ranking": [{"logic": "RECIPE", "score": 0.9}], "reason": "표"}]})

    ctx = NS(stage="CLASSIFY")
    with patch.object(classify, "get_settings", lambda: _settings()), \
            patch.object(classify, "measured_generate", fake_generate):
        out = asyncio.run(classify.classify([PROBE], hints=(), context=None, usage_sink=None,
                                            usage_context=ctx))
    assert len(calls) == 1 and calls[0][1] is ctx and calls[0][0].model == "gemini-3.6-flash"
    assert out.model_sections["c1"][0].logic == "RECIPE" and len(out.prompt_digest) == 16


def test_model_error_becomes_classification_error():
    async def boom(*a, **kw):
        raise RuntimeError("503")

    with patch.object(classify, "get_settings", lambda: _settings()), \
            patch.object(classify, "measured_generate", boom):
        with pytest.raises(IntakeClassificationError):
            asyncio.run(classify.classify([PROBE], hints=(), context=None, usage_sink=None,
                                          usage_context=None))


def test_unknown_candidate_in_output_is_error():
    async def fake_generate(spec, prompt, images, schema, **kw):
        return schema.model_validate({"sections": [
            {"candidate_id": "c9", "ranking": [{"logic": "RECIPE", "score": 0.9}]}]})

    with patch.object(classify, "get_settings", lambda: _settings()), \
            patch.object(classify, "measured_generate", fake_generate):
        with pytest.raises(IntakeClassificationError):
            asyncio.run(classify.classify([PROBE], hints=(), context=None, usage_sink=None,
                                          usage_context=None))


def test_mock_build_ranks_hint_first_else_recipe():
    sections = classify.mock_sections([PROBE], hints=("POLICY",))
    assert sections == {"sections": [{"candidate_id": "c1",
                                      "ranking": [{"logic": "POLICY", "score": 0.9}],
                                      "reason": "mock"}]}
    assert classify.mock_sections([PROBE], hints=())["sections"][0]["ranking"][0]["logic"] == "RECIPE"
