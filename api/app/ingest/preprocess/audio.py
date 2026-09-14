"""준혁 — 음성 전처리 (M2). ffprobe 로 메타 확인 → STT 로 전사.

ffmpeg 는 시스템 설치다. 없으면 조용히 넘어가지 않고 명확히 죽인다.
"""
import asyncio
import json
import logging
from decimal import Decimal
import re
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


async def transcribe_detailed(
    path: Path, *, usage_sink=None, usage_context=None
) -> tuple[str, list[dict], str]:
    """(전사문, 구간 목록, 사용 모델).

    `verbose_json` 으로 받아 구간별 시작·끝 시각을 보존한다.
    시각이 없으면 긴 영상을 시간으로 쪼갤 수 없고, 사실이 영상의 어느 지점에서
    나왔는지도 알 수 없다 (13.4).

    OPENAI_API_KEY 는 api 에만 존재한다 (불변식 2).
    """
    s = get_settings()
    if not s.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY 가 없다. api/.env 를 확인하라")

    client = AsyncOpenAI(api_key=s.openai_api_key, timeout=STT_TIMEOUT)

    if usage_context is None:
        res = await _transcribe_call(client, path, s.stt_model)
    else:
        from app.usage import recorder

        async with recorder.attempt(usage_sink, usage_context,
                                    model=s.stt_model, mode="real") as rec:
            rec.measure_input(input_bytes=path.stat().st_size)
            res = await _transcribe_call(client, path, s.stt_model)
            rec.reported_model = s.stt_model
            # Whisper 는 토큰이 아니라 **오디오 길이**로 과금한다.
            # verbose_json 의 duration 이 그 단위다. 없으면 못 잰 것이지 0 이 아니다
            duration = getattr(res, "duration", None)
            if duration is not None:
                rec.measure_input(input_bytes=path.stat().st_size,
                                  media_duration_sec=float(duration))
                rec.observe(billable_units=Decimal(str(duration)) / Decimal("60"),
                            billable_unit_name="minute",
                            raw={"duration_sec": float(duration)})
            else:
                rec.partial("공급자가 duration 을 보고하지 않았다")

    text = (getattr(res, "text", "") or "").strip()
    segments: list[dict] = []
    for seg in (getattr(res, "segments", None) or []):
        chunk = (getattr(seg, "text", "") or "").strip()
        if not chunk:
            continue
        segments.append({
            "start": float(getattr(seg, "start", 0) or 0),
            "end": float(getattr(seg, "end", 0) or 0),
            "text": chunk,
        })

    if not text and segments:
        text = " ".join(seg["text"] for seg in segments)
    if not text:
        raise RuntimeError("전사 결과가 비어 있다. 음성이 무음이거나 너무 짧다")

    logger.info("stt model=%s chars=%d segments=%d", s.stt_model, len(text), len(segments))
    return text, segments, s.stt_model


async def transcribe(path: Path) -> tuple[str, str]:
    """(전사문, 사용 모델). 구간이 필요 없는 호출부용."""
    text, _, model = await transcribe_detailed(path)
    return text, model


async def _transcribe_call(client, path: Path, model: str):
    with path.open("rb") as f:
        return await client.audio.transcriptions.create(
            model=model, file=f, language="ko", response_format="verbose_json",
        )


def parse_timestamped(text: str) -> list[dict]:
    """`[MM:SS] 내용` 으로 저장된 전사문을 구간으로 되돌린다.

    전사문을 시각과 함께 저장해두면 재실행 때 STT 를 다시 돌리지 않고도
    시간 창으로 쪼갤 수 있다. 실험을 반복하려면 이게 필요하다.
    """
    out: list[dict] = []
    for line in (text or "").splitlines():
        m = re.match(r"^\[(\d{1,2}):(\d{2})\]\s*(.*)$", line.strip())
        if not m:
            continue
        start = int(m.group(1)) * 60 + int(m.group(2))
        body = m.group(3).strip()
        if body:
            out.append({"start": float(start), "end": float(start), "text": body})
    for i, seg in enumerate(out[:-1]):
        seg["end"] = out[i + 1]["start"]
    return out


def with_timestamps(segments: list[dict]) -> str:
    """구간을 `[MM:SS] 내용` 형식으로 펼친다.

    추출 프롬프트가 근거 시각을 채우려면 전사문에 시각이 보여야 한다.
    """
    lines = []
    for seg in segments:
        total = int(seg["start"])
        lines.append(f"[{total // 60:02d}:{total % 60:02d}] {seg['text']}")
    return "\n".join(lines)
