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
# 상한은 config.py 가 단일 출처다 (불변식 8). sample_for_model() 에서 읽는다


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


def frame_time_sec(frame: Path) -> int:
    """파일명 frame_0007.jpg → 시각(초). 1-base 라 1을 뺀다."""
    try:
        index = int(frame.stem.rsplit("_", 1)[-1])
    except ValueError:
        return 0
    return max(0, index - 1) * get_settings().frame_interval_sec


def split_by_time(
    segments: list[dict], frames: list[Path], window_sec: int
) -> list[tuple[str, list[Path]]]:
    """전사 구간과 프레임을 같은 시간 창으로 묶는다.

    한 호출이 보는 범위를 줄이는 것이 목적이다. 38분을 통째로 주면 모델이
    요약해버리고 세부를 버린다 (store-a 실측: 영상 사실 62건 중 61건 미추출).

    창마다 그 시간대의 전사문과 프레임만 들어간다. 창 밖은 보이지 않는다.
    """
    if window_sec <= 0:
        return []

    last = 0.0
    if segments:
        last = max(float(s.get("end", 0) or 0) for s in segments)
    if frames:
        # 목록 순서를 믿지 않는다. 실제 시각의 최댓값을 쓴다
        last = max(last, float(max(frame_time_sec(f) for f in frames)))
        # 마지막 프레임 자체도 창 안에 들어와야 하므로 한 칸 뒤까지 본다
        last += get_settings().frame_interval_sec
    if last <= 0:
        return []

    windows: list[tuple[str, list[Path]]] = []
    start = 0
    while start < last:
        end = start + window_sec
        lines = [
            f"[{int(sg['start']) // 60:02d}:{int(sg['start']) % 60:02d}] {sg['text']}"
            for sg in segments
            if start <= float(sg.get("start", 0) or 0) < end
        ]
        window_frames = [f for f in frames if start <= frame_time_sec(f) < end]
        if lines or window_frames:
            head = (f"(영상 {start // 60}분 {start % 60}초 ~ "
                    f"{min(int(end), int(last)) // 60}분 {min(int(end), int(last)) % 60}초 구간)")
            body = "\n".join(lines) if lines else "(이 구간에 말이 없다. 화면만으로 판단할 것)"
            windows.append((f"{head}\n{body}", sample_for_model(window_frames)))
        start = end
    return windows


def sample_for_model(frames: list[Path]) -> list[Path]:
    """모델에 넣을 프레임을 고르게 솎는다. 전부 넣으면 느리고 비싸다.

    상한은 `VIDEO_MAX_FRAMES_TO_MODEL` 이며 0 이면 솎지 않고 전부 넣는다.
    몇 장이 최적인지는 가정하지 않고 평가 하네스로 정한다.
    """
    cap = get_settings().video_max_frames_to_model
    if cap <= 0 or len(frames) <= cap:
        return frames
    step = len(frames) / cap
    return [frames[int(i * step)] for i in range(cap)]
