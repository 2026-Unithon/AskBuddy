from __future__ import annotations

from typing import Any

from app.config import get_settings

SUPPORTED_EXTENSIONS: dict[str, tuple[str, ...]] = {
    "VOICE": ("mp3", "m4a", "wav"),
    "VIDEO": ("mp4", "mov"),
    "KAKAO": ("txt", "jpg", "jpeg", "png"),
    "SCAN": ("pdf", "jpg", "jpeg", "png"),
}


def get_capabilities() -> dict[str, dict[str, Any]]:
    settings = get_settings()
    return {
        "VOICE": {
            "extensions": list(SUPPORTED_EXTENSIONS["VOICE"]),
            "max_bytes": settings.ingest_voice_max_bytes,
            "max_duration_sec": settings.ingest_voice_max_duration_sec,
        },
        "VIDEO": {
            "extensions": list(SUPPORTED_EXTENSIONS["VIDEO"]),
            "max_bytes": settings.ingest_video_max_bytes,
            "max_duration_sec": settings.ingest_video_max_duration_sec,
        },
        "KAKAO": {
            "extensions": list(SUPPORTED_EXTENSIONS["KAKAO"]),
            "max_bytes": settings.ingest_kakao_max_bytes,
        },
        "SCAN": {
            "extensions": list(SUPPORTED_EXTENSIONS["SCAN"]),
            "max_bytes": settings.ingest_scan_max_bytes,
            "max_pages": settings.ingest_scan_max_pages,
        },
    }


def extension_of(filename: str) -> str:
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
