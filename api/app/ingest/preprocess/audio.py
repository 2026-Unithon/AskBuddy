"""준혁 — 음성 전처리 (M2). ffprobe 로 메타 확인 → STT 로 전사.

ffmpeg 는 시스템 설치다. 없으면 조용히 넘어가지 않고 명확히 죽인다.
"""
import asyncio
import json
import logging
import shutil
from pathlib import Path

from openai import AsyncOpenAI

from app.config import get_settings

logger = logging.getLogger(__name__)

PROBE_TIMEOUT = 30
STT_TIMEOUT = 300


def require_ffmpeg() -> None:
    missing = [b for b in ("ffmpeg", "ffprobe") if shutil.which(b) is None]
    if missing:
        raise RuntimeError(
            f"{', '.join(missing)} 를 PATH 에서 찾을 수 없다. "
            "brew install ffmpeg (mac) / winget install Gyan.FFmpeg (win). "
            "Windows 는 WSL2 를 권장한다"
        )


async def probe(path: Path) -> dict[str, int | None]:
    """duration_sec, sample_rate 를 뽑는다. 실패해도 파이프라인을 세우지 않는다."""
    require_ffmpeg()
    proc = await asyncio.create_subprocess_exec(
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_format", "-show_streams", str(path),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=PROBE_TIMEOUT)
    except asyncio.TimeoutError:
        proc.kill()
        raise RuntimeError("ffprobe 시간 초과") from None

    if proc.returncode != 0:
        raise RuntimeError(f"ffprobe 실패 (code {proc.returncode})")

    meta = json.loads(out or b"{}")
    duration = meta.get("format", {}).get("duration")
    audio = next((s for s in meta.get("streams", []) if s.get("codec_type") == "audio"), {})
    return {
        "duration_sec": int(float(duration)) if duration else 0,
        "sample_rate": int(audio["sample_rate"]) if audio.get("sample_rate") else None,
    }


async def transcribe(path: Path) -> tuple[str, str]:
    """(전사문, 사용 모델). OPENAI_API_KEY 는 api 에만 존재한다 (불변식 2)."""
    s = get_settings()
    if not s.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY 가 없다. api/.env 를 확인하라")

    client = AsyncOpenAI(api_key=s.openai_api_key, timeout=STT_TIMEOUT)
    with path.open("rb") as f:
        res = await client.audio.transcriptions.create(
            model=s.stt_model, file=f, language="ko", response_format="text",
        )
    text = res if isinstance(res, str) else getattr(res, "text", "")
    text = (text or "").strip()
    if not text:
        raise RuntimeError("전사 결과가 비어 있다. 음성이 무음이거나 너무 짧다")

    logger.info("stt model=%s chars=%d", s.stt_model, len(text))
    return text, s.stt_model
