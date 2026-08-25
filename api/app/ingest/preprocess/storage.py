"""준혁 — Supabase Storage 에서 원본 내려받기.

프론트가 Storage 에 직접 올린다. 워커는 경로만 받아 여기서 내려받는다.
파일 바이너리를 API 로 POST 받지 않는다 (개발가이드 6-1).
"""
import logging
from pathlib import Path

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

TMP_ROOT = Path(__file__).resolve().parents[3] / "tmp"   # api/tmp/
DOWNLOAD_TIMEOUT = 120.0


def workdir(source_id: int) -> Path:
    d = TMP_ROOT / str(source_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _object_url(file_url: str) -> tuple[str, dict[str, str]]:
    """file_url 이 전체 URL 이면 그대로, 'bucket/path' 형태면 Storage API 주소로 바꾼다."""
    s = get_settings()
    if file_url.startswith(("http://", "https://")):
        headers = {}
        if s.supabase_url and file_url.startswith(s.supabase_url) and s.supabase_service_key:
            headers = {"Authorization": f"Bearer {s.supabase_service_key}"}
        return file_url, headers

    if not s.supabase_url:
        raise RuntimeError("SUPABASE_URL 이 비어 있다. api/.env 를 확인하라")
    path = file_url.lstrip("/")
    return (
        f"{s.supabase_url}/storage/v1/object/{path}",
        {"Authorization": f"Bearer {s.supabase_service_key}"},
    )


async def download(source_id: int, file_url: str) -> Path:
    url, headers = _object_url(file_url)
    dest = workdir(source_id) / Path(file_url.split("?")[0]).name
    logger.info("download source=%s -> %s", source_id, dest.name)

    async with httpx.AsyncClient(timeout=DOWNLOAD_TIMEOUT, follow_redirects=True) as client:
        async with client.stream("GET", url, headers=headers) as res:
            if res.status_code != 200:
                body = (await res.aread())[:200].decode("utf-8", "replace")
                raise RuntimeError(f"원본 다운로드 실패 {res.status_code}: {body}")
            with dest.open("wb") as f:
                async for chunk in res.aiter_bytes(65536):
                    f.write(chunk)

    if dest.stat().st_size == 0:
        raise RuntimeError(f"원본이 비어 있다: {file_url}")
    return dest


# ── 업로드 경로 규약 ───────────────────────────────────────────────────────
#
#   버킷      sources           (비공개. scripts/init_storage.py 로 생성)
#   오브젝트  {store_id}/{voice|video|kakao|scan}/{uuid}.{ext}
#   file_url  버킷을 포함한 전체 경로. 예) sources/1/voice/9f2c….m4a
#
# 브라우저는 Supabase 자격증명을 갖지 않는다(불변식 1·2).
# API 가 서명된 업로드 URL 을 발급하고, 브라우저는 그 URL 로만 PUT 한다.

import hashlib
import uuid as _uuid

_EXT = {
    "VOICE": {"mp3", "m4a", "wav"},
    "VIDEO": {"mp4", "mov"},
    "KAKAO": {"txt", "zip"},
    "SCAN": {"pdf", "jpg", "jpeg", "png"},
}


def build_object_path(store_id: int, source_type: str, filename: str) -> str:
    """업로드할 오브젝트 경로를 만든다. 원본 파일명은 쓰지 않는다.

    한글·공백 파일명이 URL 인코딩에서 깨지는 사고를 원천 차단하고,
    같은 이름 재업로드가 서로 덮어쓰는 것도 막는다.
    """
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    allowed = _EXT.get(source_type, set())
    if ext not in allowed:
        raise ValueError(
            f"{source_type} 는 {'/'.join(sorted(allowed))} 확장자만 받는다 (받은 값: {ext or '없음'})"
        )
    return f"{get_settings().storage_bucket}/{store_id}/{source_type.lower()}/{_uuid.uuid4().hex}.{ext}"


async def create_signed_upload_url(object_path: str) -> str:
    """브라우저가 파일을 직접 PUT 할 1회용 URL. 기본 유효시간은 2시간이다."""
    s = get_settings()
    if not s.supabase_service_key:
        raise RuntimeError("SUPABASE_SERVICE_KEY 가 없다. api/.env 를 확인하라")

    async with httpx.AsyncClient(timeout=30) as client:
        res = await client.post(
            f"{s.supabase_url}/storage/v1/object/upload/sign/{object_path}",
            headers={"Authorization": f"Bearer {s.supabase_service_key}"},
        )
    if res.status_code != 200:
        raise RuntimeError(f"서명 URL 발급 실패 {res.status_code}: {res.text[:200]}")

    # 응답의 url 은 /storage/v1 이 빠진 상대경로다
    return f"{s.supabase_url}/storage/v1{res.json()['url']}"


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


async def upload(object_path: str, data: bytes, content_type: str) -> str:
    """서버가 만든 산출물(영상 프레임 등)을 Storage 에 올린다.

    브라우저 업로드와 달리 여기는 service key 를 쓴다. 이 경로는 API 안에서만 돈다.
    """
    s = get_settings()
    if not s.supabase_service_key:
        raise RuntimeError("SUPABASE_SERVICE_KEY 가 없다. api/.env 를 확인하라")

    async with httpx.AsyncClient(timeout=60) as client:
        res = await client.post(
            f"{s.supabase_url}/storage/v1/object/{object_path}",
            headers={"Authorization": f"Bearer {s.supabase_service_key}",
                     "content-type": content_type,
                     "x-upsert": "true"},
            content=data,
        )
    if res.status_code not in (200, 201):
        raise RuntimeError(f"업로드 실패 {res.status_code}: {res.text[:200]}")
    return object_path
