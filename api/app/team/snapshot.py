"""평가 실행의 재현 정보 스냅샷.

'그때 무슨 설정으로 쟀는가' 를 나중에 사람이 기억에 의존해 적으면 비교가 무너진다.
코드 버전·프롬프트 버전은 실행 시점에 파일과 git 에서 직접 읽는다.
"""
from __future__ import annotations

import hashlib
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.config import get_settings

PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"
_REPO_DIR = Path(__file__).resolve().parents[3]


@lru_cache(maxsize=1)
def code_version() -> str:
    """git 커밋. dirty 면 표시한다 — 커밋 안 된 코드의 수치를 커밋 수치로 읽으면 안 된다."""
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "--short=12", "HEAD"],
            cwd=_REPO_DIR,
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=_REPO_DIR,
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        ).stdout.strip()
        return f"{sha}-dirty" if dirty else sha
    except (subprocess.SubprocessError, OSError):
        return "unknown"


def prompt_digest(name: str) -> str:
    """프롬프트 파일 내용 해시. 파일을 고치면 버전이 저절로 바뀐다."""
    path = PROMPTS_DIR / name
    if not path.exists():
        return f"{name}@missing"
    digest = hashlib.sha256(path.read_bytes()).hexdigest()[:12]
    return f"{path.stem}@{digest}"


def prompt_version() -> str:
    """답변 생성 프롬프트가 평가 대상이다."""
    return prompt_digest("grounded_answer.ko.txt")


def settings_snapshot(feature_flags: dict[str, Any] | None = None) -> dict[str, Any]:
    """재현에 필요한 값만 고른다. 비밀값은 담지 않는다."""
    s = get_settings()
    return {
        "env": s.env,
        "answer_mode": s.answer_mode,
        "answer_model": s.gemini_model,
        "embedding_model": s.embedding_model,
        "embedding_dim": s.embedding_dim,
        "retrieval_threshold": s.retrieval_threshold,
        "retrieval_strong_score": s.retrieval_strong_score,
        "confidence_threshold": s.confidence_threshold,
        "ingest_mode": s.ingest_mode,
        "stt_model": s.stt_model,
        "has_gemini_key": bool(s.gemini_api_key),
        "has_openai_key": bool(s.openai_api_key),
        "prompts": {
            name: prompt_digest(name)
            for name in sorted(p.name for p in PROMPTS_DIR.glob("*.txt"))
        },
        "feature_flags": feature_flags or {},
    }
