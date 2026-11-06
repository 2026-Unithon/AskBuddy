"""Phase B — 업로드 훑기(probe_source) 규칙. 전사문 재사용·mock 기본 정규화기(Task 9 fix round 1)."""
from unittest.mock import AsyncMock, patch

import pytest

from app.config import Settings
from app.ingest import pipeline
from app.ingest.intake import route as intake_route
from app.ingest.intake.ir import Candidate, Locator, ProbeResult
from app.ingest.preprocess import audio
from tests.test_w3a_pipeline_wiring import _Pool


def _src(source_type, file_url):
    return {"source_id": 7, "store_id": 1, "source_type": source_type, "file_url": file_url,
            "content_hash": "h"}


async def _probe(src, *, mode, **patches):
    settings = Settings(_env_file=None, ingest_mode=mode)
    download = AsyncMock()
    with patch.object(intake_route, "get_settings", return_value=settings), \
         patch.object(pipeline, "_download", download):
        ctx = [patch.object(intake_route.repo, k, v) for k, v in patches.items()]
        for c in ctx:
            c.start()
        try:
            got = await intake_route.probe_source(_Pool(), 1, src, cache=intake_route.IntakeCache(),
                                                  usage_sink=None, usage_base=None)
        finally:
            for c in reversed(ctx):
                c.stop()
    return got, download


@pytest.mark.asyncio
@pytest.mark.parametrize("source_type, file_url, normalizer", [
    ("SCAN", "x", "DOC_TEXT"), ("KAKAO", "", "CHAT"), ("VOICE", "b/1/voice/x.ogg", "AUDIO"),
    ("VIDEO", None, "VIDEO"), ("SCAN", "b/1/scan/x.pdf", "DOC_TEXT"),
])
async def test_mock_unknown_extension_falls_back_to_type_default(source_type, file_url, normalizer):
    got, download = await _probe(_src(source_type, file_url), mode="mock")
    assert got == ProbeResult(normalizer, (
        Candidate("c1", Locator("WHOLE", "", ""), pipeline.MOCK_PLACEHOLDER),))
    download.assert_not_awaited()


@pytest.mark.asyncio
async def test_real_unknown_extension_still_fails():
    with pytest.raises(ValueError, match="정규화기가 없는 입력"):
        await _probe(_src("SCAN", "b/1/scan/x.hwp"), mode="real")


@pytest.mark.asyncio
@pytest.mark.parametrize("source_type, file_url, getter, normalizer", [
    ("VOICE", "b/1/voice/x.m4a", "get_voice", "AUDIO"),
    ("VIDEO", "b/1/video/x.mp4", "get_video", "VIDEO"),
])
async def test_stored_transcript_is_the_probe_without_stt(source_type, file_url, getter, normalizer):
    transcript = "[00:00] 음료Z 샷 2\n" * 400
    stt = AsyncMock()
    with patch.object(audio, "transcribe_detailed", stt):
        got, download = await _probe(
            _src(source_type, file_url), mode="real",
            **{getter: AsyncMock(return_value={"transcript": transcript})})
    limit = Settings(_env_file=None).intake_probe_text_chars
    assert got == ProbeResult(normalizer, (
        Candidate("c1", Locator("WHOLE", "", ""), transcript[:limit]),))
    download.assert_not_awaited()
    stt.assert_not_awaited()
