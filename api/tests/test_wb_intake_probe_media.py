# api/tests/test_wb_intake_probe_media.py
"""Phase B — 미디어 훑기: 고른 간격·상한·위치. ffmpeg·STT 는 대역(유료 호출 0)."""
import asyncio
from pathlib import Path

from PIL import Image

from app.ingest.intake import probe_media


def _run(coro):
    return asyncio.run(coro)


def test_audio_windows_first_middle_last(tmp_path):
    cuts, said = [], []

    async def cut(src, dst, start, sec):
        cuts.append((start, sec)); dst.write_bytes(b"x")

    async def transcribe(path, usage_context):
        said.append(path.name); return f"말{len(said)}"

    probe = _run(probe_media.probe_audio(tmp_path / "a.m4a", tmp_path, duration_sec=600,
                                         windows=3, window_sec=20, transcribe=transcribe, cut=cut,
                                         usage_context_for=lambda i: None))
    assert [c[0] for c in cuts] == [0, 290, 580]
    assert [(c.locator.start, c.locator.end) for c in probe.candidates] == [
        ("0", "20"), ("290", "310"), ("580", "600")]
    assert [c.text for c in probe.candidates] == ["말1", "말2", "말3"]


def test_short_audio_single_window(tmp_path):
    async def cut(src, dst, start, sec): dst.write_bytes(b"x")
    async def transcribe(path, usage_context): return "짧은 말"
    probe = _run(probe_media.probe_audio(tmp_path / "a.m4a", tmp_path, duration_sec=15, windows=3,
                                         window_sec=20, transcribe=transcribe, cut=cut,
                                         usage_context_for=lambda i: None))
    assert len(probe.candidates) == 1 and probe.candidates[0].locator.end == "15"


def test_video_keyframes_and_stt_subset(tmp_path):
    grabs, cuts = [], []

    async def grab(src, dst, at, px):
        grabs.append(at); Image.new("RGB", (8, 8)).save(dst)

    async def cut(src, dst, start, sec):
        cuts.append(start); dst.write_bytes(b"x")

    async def transcribe(path, usage_context): return "말"

    probe = _run(probe_media.probe_video(tmp_path / "v.mp4", tmp_path, duration_sec=500,
                                         has_audio=True, keyframes=5, windows=3, window_sec=20,
                                         px=512, transcribe=transcribe, cut=cut, grab=grab,
                                         usage_context_for=lambda i: None))
    assert len(probe.candidates) == 5 and len(grabs) == 5
    assert len(cuts) == 3  # 처음·중간·끝 창만 STT
    assert [bool(c.text) for c in probe.candidates] == [True, False, True, False, True]
    assert all(len(c.images) == 1 for c in probe.candidates)


def test_video_without_audio_has_no_stt(tmp_path):
    async def grab(src, dst, at, px): Image.new("RGB", (8, 8)).save(dst)
    async def cut(src, dst, start, sec): raise AssertionError("오디오 없는 영상은 자르지 않는다")
    async def transcribe(path, usage_context): raise AssertionError
    probe = _run(probe_media.probe_video(tmp_path / "v.mp4", tmp_path, duration_sec=60,
                                         has_audio=False, keyframes=4, windows=3, window_sec=20,
                                         px=512, transcribe=transcribe, cut=cut, grab=grab,
                                         usage_context_for=lambda i: None))
    assert all(c.text == "" for c in probe.candidates)


def test_doc_image_samples_six_of_twenty_pages_shrunk(tmp_path):
    def render(path, index, dpi):
        return Image.new("RGB", (2000, 1000))

    probe = _run(probe_media.probe_doc_image(tmp_path / "s.pdf", tmp_path, max_images=6, px=512,
                                             max_sections=12, page_count=20, render=render))
    sampled = probe.sampled()
    assert len(probe.candidates) == 12 and len(sampled) == 6
    assert sampled[0].candidate_id == "c1" and sampled[-1].candidate_id == "c12"
    with Image.open(sampled[0].images[0]) as im:
        assert max(im.size) == 512


def test_single_image_is_one_sampled_candidate(tmp_path):
    img = tmp_path / "p.jpg"
    Image.new("RGB", (1000, 3000)).save(img)
    probe = _run(probe_media.probe_doc_image(img, tmp_path, max_images=6, px=512,
                                             max_sections=12, page_count=1))
    (c,) = probe.candidates
    assert c.sampled and c.locator.kind == "PAGE"
