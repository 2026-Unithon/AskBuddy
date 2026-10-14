"""미디어 훑기 — DOC_IMAGE·AUDIO·VIDEO 의 경계 후보와 표본을 만든다(B-D3b).

ffmpeg·STT·PDF 렌더링은 모두 주입 가능한 인자다. 기본 구현만 실제 도구를 부른다.
"""
from __future__ import annotations

from pathlib import Path
from typing import Awaitable, Callable

from PIL import Image

from app.ingest.intake.grouping import _merge, even_indices
from app.ingest.intake.ir import Candidate, Locator, ProbeResult

_FFMPEG_TIMEOUT = 120

Transcribe = Callable[[Path, object], Awaitable[str]]
Cut = Callable[[Path, Path, int, int], Awaitable[None]]
Grab = Callable[[Path, Path, int, int], Awaitable[None]]


# ---------- 기본 구현(실제 ffmpeg·STT) ----------

async def _default_cut(src: Path, dst: Path, start: int, sec: int) -> None:
    from app.ingest.preprocess.audio import require_ffmpeg
    from app.ingest.preprocess.video import _run
    require_ffmpeg()
    await _run("ffmpeg", "-y", "-ss", str(start), "-t", str(sec), "-i", str(src),
               "-vn", "-ac", "1", "-ar", "16000", str(dst), timeout=_FFMPEG_TIMEOUT)


async def _default_grab(src: Path, dst: Path, at: int, px: int) -> None:
    from app.ingest.preprocess.audio import require_ffmpeg
    from app.ingest.preprocess.video import _run
    require_ffmpeg()
    scale = f"scale='if(gt(iw,ih),{px},-2)':'if(gt(iw,ih),-2,{px})'"
    await _run("ffmpeg", "-y", "-ss", str(at), "-i", str(src), "-frames:v", "1",
               "-vf", scale, str(dst), timeout=_FFMPEG_TIMEOUT)


async def _default_transcribe(path: Path, usage_context) -> str:
    from app.ingest.preprocess.audio import transcribe_detailed
    text, _segments, _model = await transcribe_detailed(path, usage_context=usage_context)
    return text


# ---------- 공통 ----------

def _window_starts(duration: int, k: int, window_sec: int) -> tuple[int, list[tuple[int, int]]]:
    """고른 간격의 창 (시작, 끝) 목록. 창이 하나면 처음 한 창이다."""
    w = max(1, min(window_sec, duration))
    if k <= 1:
        return w, [(0, w)]
    starts = [round((duration - w) * j / (k - 1)) for j in range(k)]
    return w, [(s, s + w) for s in starts]


def _probe_dir(workdir: Path) -> Path:
    d = workdir / "probe"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------- DOC_IMAGE ----------

async def probe_doc_image(path: Path, workdir: Path, *, max_images: int, px: int,
                          max_sections: int, page_count: int, render=None) -> ProbeResult:
    out = _probe_dir(workdir)
    is_pdf = path.suffix.lower() == ".pdf"
    parts = [(str(n), str(n), (str(n),)) for n in range(1, max(1, page_count) + 1)]
    groups = _merge(parts, max_sections, "PAGE")
    chosen = set(even_indices(len(groups), max_images))
    if is_pdf and render is None:
        from app.ingest.layout.pages import _render as render

    candidates: list[Candidate] = []
    for i, g in enumerate(groups):
        if i not in chosen:
            candidates.append(Candidate(g.candidate_id, g.locator, "", (), sampled=False))
            continue
        first = int(g.locator.start)
        if is_pdf:
            img = render(path, first - 1, 72).convert("RGB")
        else:
            with Image.open(path) as src:
                img = src.convert("RGB")
        img.thumbnail((px, px))
        dst = out / f"p{first}.jpg"
        img.save(dst, "JPEG")
        candidates.append(Candidate(g.candidate_id, g.locator, "", (dst,)))
    return ProbeResult("DOC_IMAGE", tuple(candidates))


# ---------- AUDIO ----------

async def probe_audio(path: Path, workdir: Path, *, duration_sec: int, windows: int,
                      window_sec: int, transcribe: Transcribe | None = None,
                      cut: Cut | None = None, usage_context_for=lambda i: None) -> ProbeResult:
    transcribe = transcribe or _default_transcribe
    cut = cut or _default_cut
    out = _probe_dir(workdir)
    k = 1 if duration_sec <= window_sec else windows
    _, spans = _window_starts(duration_sec, k, window_sec)
    candidates = []
    for i, (s, e) in enumerate(spans):
        clip = out / f"a{i + 1}.mp3"
        await cut(path, clip, s, e - s)
        text = await transcribe(clip, usage_context_for(i))
        candidates.append(Candidate(f"c{i + 1}", Locator("TIME", str(s), str(e)), text))
    return ProbeResult("AUDIO", tuple(candidates))


# ---------- VIDEO ----------

async def probe_video(path: Path, workdir: Path, *, duration_sec: int, has_audio: bool,
                      keyframes: int, windows: int, window_sec: int, px: int,
                      transcribe: Transcribe | None = None, cut: Cut | None = None,
                      grab: Grab | None = None, usage_context_for=lambda i: None) -> ProbeResult:
    transcribe = transcribe or _default_transcribe
    cut = cut or _default_cut
    grab = grab or _default_grab
    out = _probe_dir(workdir)
    w, spans = _window_starts(duration_sec, keyframes, window_sec)
    stt = set(even_indices(len(spans), windows)) if has_audio else set()
    candidates, calls = [], 0
    for i, (s, e) in enumerate(spans):
        frame = out / f"v{i + 1}.jpg"
        await grab(path, frame, s + w // 2, px)
        text = ""
        if i in stt:
            clip = out / f"v{i + 1}.mp3"
            await cut(path, clip, s, e - s)
            text = await transcribe(clip, usage_context_for(calls))
            calls += 1
        candidates.append(Candidate(f"c{i + 1}", Locator("TIME", str(s), str(e)), text, (frame,)))
    return ProbeResult("VIDEO", tuple(candidates))
