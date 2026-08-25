"""준혁 — 영상 전처리 (M4).

오디오는 전사하고, 화면은 일정 간격 프레임으로 잘라 Storage 에 올린다.
프레임 인덱스는 0-base 다. timestamp_sec = frame_index * FRAME_INTERVAL_SEC 이
성립해야 근거 타임스탬프가 밀리지 않는다.
"""
import asyncio
import json
import logging
from pathlib import Path

from app.config import get_settings
from app.ingest.preprocess import storage
from app.ingest.preprocess.audio import PROBE_TIMEOUT, require_ffmpeg

logger = logging.getLogger(__name__)

FRAME_WIDTH = 640           # 가로 640. Gemini 입력 비용과 판독성의 절충
FFMPEG_TIMEOUT = 600
MAX_FRAMES_TO_MODEL = 20    # 멀티모달 호출에 넣을 최대 장수


async def _run(*args: str, timeout: int) -> bytes:
    proc = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise RuntimeError(f"{args[0]} 시간 초과") from None
    if proc.returncode != 0:
        raise RuntimeError(f"{args[0]} 실패 (code {proc.returncode}): "
                           f"{err.decode('utf-8', 'replace')[-200:]}")
    return out


async def probe(path: Path) -> dict:
    require_ffmpeg()
    out = await _run("ffprobe", "-v", "quiet", "-print_format", "json",
                     "-show_format", "-show_streams", str(path), timeout=PROBE_TIMEOUT)
    meta = json.loads(out or b"{}")
    v = next((s for s in meta.get("streams", []) if s.get("codec_type") == "video"), {})
    duration = meta.get("format", {}).get("duration")

    fps = None
    if v.get("avg_frame_rate") and "/" in v["avg_frame_rate"]:
        num, den = v["avg_frame_rate"].split("/")
        fps = round(int(num) / int(den)) if int(den) else None

    return {
        "duration_sec": int(float(duration)) if duration else 0,
        "resolution": f"{v['width']}x{v['height']}" if v.get("width") else None,
        "fps": fps,
        "has_audio": any(s.get("codec_type") == "audio" for s in meta.get("streams", [])),
    }


async def extract_audio(path: Path, workdir: Path) -> Path:
    """전사용 오디오만 뽑는다. 16kHz 모노면 STT 에 충분하고 파일이 작다."""
    require_ffmpeg()
    dest = workdir / "audio.m4a"
    await _run("ffmpeg", "-y", "-i", str(path), "-vn",
               "-ac", "1", "-ar", "16000", "-c:a", "aac", str(dest),
               timeout=FFMPEG_TIMEOUT)
    return dest


async def extract_frames(path: Path, workdir: Path) -> list[Path]:
    """FRAME_INTERVAL_SEC 간격으로 프레임을 뽑는다. 파일명은 1-base 라 정렬 후 0-base 로 다룬다."""
    require_ffmpeg()
    interval = get_settings().frame_interval_sec
    outdir = workdir / "frames"
    outdir.mkdir(parents=True, exist_ok=True)

    await _run("ffmpeg", "-y", "-i", str(path),
               "-vf", f"fps=1/{interval},scale={FRAME_WIDTH}:-2",
               "-q:v", "3", str(outdir / "frame_%04d.jpg"),
               timeout=FFMPEG_TIMEOUT)

    frames = sorted(outdir.glob("frame_*.jpg"))
    logger.info("프레임 %d장 추출 (%d초 간격)", len(frames), interval)
    return frames


async def upload_frames(store_id: int, source_id: int, frames: list[Path]) -> list[dict]:
    """프레임을 Storage 에 올리고 source_frames 에 넣을 행 정보를 만든다."""
    interval = get_settings().frame_interval_sec
    bucket = get_settings().storage_bucket
    rows = []
    for i, f in enumerate(frames):        # i 가 0-base 프레임 인덱스다
        object_path = f"{bucket}/{store_id}/frames/{source_id}/{i:04d}.jpg"
        await storage.upload(object_path, f.read_bytes(), "image/jpeg")
        rows.append({
            "frame_index": i,
            "timestamp_sec": i * interval,
            "image_url": object_path,
        })
    return rows


def sample_for_model(frames: list[Path]) -> list[Path]:
    """모델에 넣을 프레임을 고르게 솎는다. 전부 넣으면 느리고 비싸다."""
    if len(frames) <= MAX_FRAMES_TO_MODEL:
        return frames
    step = len(frames) / MAX_FRAMES_TO_MODEL
    return [frames[int(i * step)] for i in range(MAX_FRAMES_TO_MODEL)]
