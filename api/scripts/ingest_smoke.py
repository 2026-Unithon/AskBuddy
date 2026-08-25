"""경계 확인 — 업로드 등록 → 처리 → 폴링 → 카드 확인.

    uvicorn app.main:app --reload --port 8000        # 다른 터미널

권장 (실 JWT):
    curl -X POST localhost:8000/auth/login -H "Content-Type: application/json" \\
      -d '{"email":"owner@demo.cafe","password":"demo1234","role":"OWNER"}'
    export ASKBUDDY_TOKEN=<응답 token>
    python scripts/ingest_smoke.py

하위 호환 (dev_token 비활성 — 명시적 force만):
    export ASKBUDDY_TOKEN=$(ALLOW_DEV_TOKEN=1 python scripts/dev_token.py --force)
    python scripts/ingest_smoke.py

INGEST_MODE=mock  LLM 을 호출하지 않는다. 키 없이 돈다.
                 원본을 내려받지 않으므로 파일을 실제로 올리지도 않는다.
INGEST_MODE=real  서명 URL 로 파일을 올린 뒤 전사·추출을 실제로 돌린다.
                 OPENAI_API_KEY·GEMINI_API_KEY·SUPABASE_SERVICE_KEY 가 필요하고,
                 무음 파일이라 전사 결과가 비어 실패할 수 있다. 그건 정상이다.

file_url 은 두 모드 모두 D8 규약을 따른다 — sources/{store_id}/voice/{uuid}.m4a
"""
import asyncio
import os
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx

BASE = os.environ.get("ASKBUDDY_API", "http://localhost:8000")
TOKEN = os.environ.get("ASKBUDDY_TOKEN", "")
POLL_INTERVAL = 2.0      # D6 — 프론트와 같은 간격
POLL_TIMEOUT = 120.0


def _sample_audio() -> bytes:
    """실제 모드용 표본 오디오. ffmpeg 로 5초짜리를 만든다.

    더미 바이트를 올리면 ffprobe 가 먼저 죽어서 그 뒤 단계를 전혀 확인하지 못한다.
    """
    import shutil
    import subprocess
    import tempfile

    if shutil.which("ffmpeg") is None:
        raise RuntimeError("실제 모드 스모크에는 ffmpeg 가 필요하다. brew install ffmpeg")

    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "smoke.m4a"
        subprocess.run(
            ["ffmpeg", "-v", "quiet", "-f", "lavfi", "-i",
             "sine=frequency=440:duration=5", "-ar", "16000", "-c:a", "aac",
             "-y", str(out)],
            check=True,
        )
        return out.read_bytes()


def _store_id_of(token: str) -> int:
    """토큰에서 store_id 를 꺼낸다. 서명 검증은 서버가 한다."""
    import jwt
    return int(jwt.decode(token, options={"verify_signature": False})["store_id"])


async def _prepare_object(client: httpx.AsyncClient, token: str) -> tuple[str, bool]:
    """(file_url, 실제로 올렸는지).

    목 모드는 원본을 내려받지 않으므로 규약에 맞는 경로만 만들어 준다.
    실제 모드는 서명 URL 을 받아 파일을 올린다 — 안 올리면 다운로드 단계에서
    'Bucket not found' 같은 엉뚱한 에러로 멈춘다.
    """
    from app.config import get_settings

    if get_settings().ingest_mode != "real":
        return f"sources/{_store_id_of(token)}/voice/{uuid.uuid4().hex}.m4a", False

    res = await client.post("/ingest/upload-url",
                            json={"source_type": "VOICE", "filename": "smoke.m4a"})
    if res.status_code != 200:
        raise RuntimeError(f"서명 URL 발급 실패 {res.status_code}: {res.text[:150]}")
    body = res.json()

    async with httpx.AsyncClient(timeout=60) as anon:      # 인증 헤더 없이 올린다
        up = await anon.put(body["upload_url"], content=_sample_audio(),
                            headers={"content-type": "audio/mp4"})
    if up.status_code not in (200, 201):
        raise RuntimeError(f"업로드 실패 {up.status_code}: {up.text[:150]}")
    return body["file_url"], True


async def main() -> int:
    token = TOKEN
    if not token:
        # 권장: ASKBUDDY_TOKEN 을 /auth/login 으로 넣어라.
        # 없으면 로컬 하위 호환으로만 force mint (dev_token 기본 경로는 비활성).
        from dev_token import mint
        try:
            token = await mint(force=True)
        except Exception as e:
            print(f"토큰 발급 실패: {e}", file=sys.stderr)
            print(
                "힌트: POST /auth/login 후 ASKBUDDY_TOKEN 을 export 하라.",
                file=sys.stderr,
            )
            return 2
        print("[token] ASKBUDDY_TOKEN 없음 — deprecated force mint 사용 (login 권장)")

    from app.config import get_settings
    mode = get_settings().ingest_mode
    print(f"[mode] INGEST_MODE={mode}"
          + ("  — LLM 을 호출한다. 키와 비용이 든다" if mode == "real" else "  — LLM 미호출"))

    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(base_url=BASE, headers=headers, timeout=60) as c:
        health = await c.get("/health")
        print(f"[health] {health.status_code} {health.text}")

        file_url, uploaded = await _prepare_object(c, token)
        print(f"[object] {file_url}" + ("  (업로드 완료)" if uploaded else "  (mock — 업로드 생략)"))

        res = await c.post("/ingest/sources", json={
            "source_type": "VOICE",
            "file_url": file_url,
            "title": "스모크 테스트 음성",
            "content_hash": uuid.uuid4().hex,     # 매번 새 자료로 취급
            "meta": {"audio_format": "m4a", "record_method": "UPLOAD"},
        })
        if res.status_code != 201:
            print(f"[sources] 실패 {res.status_code}: {res.text}", file=sys.stderr)
            return 1
        source_id = res.json()["source_id"]
        print(f"[sources] source_id={source_id}")

        res = await c.post("/ingest/process", json={"source_id": source_id})
        print(f"[process] {res.status_code} {res.json()}")

        deadline = time.monotonic() + POLL_TIMEOUT
        while time.monotonic() < deadline:
            await asyncio.sleep(POLL_INTERVAL)
            body = (await c.get("/ingest/status", params={"source_id": source_id})).json()
            print(f"[poll] {body['status']} cards={body['card_count']}")

            if body["status"] == "DONE":
                if mode == "real":
                    # 합성 오디오에는 매장 지식이 없다. 카드 0건이 정상이고,
                    # DONE 에 도달했다는 것이 곧 다운로드·ffprobe·STT·추출 전 구간 통과다
                    print(f"\n통과 — 전 구간 통과 (카드 {body['card_count']}건, "
                          "합성 오디오라 0건이어도 정상)")
                    return 0
                ok = body["card_count"] > 0
                print("\n통과 — 카드가 적재됐다" if ok else "\n실패 — 카드가 0건이다")
                return 0 if ok else 1
            if body["status"] == "FAILED":
                print(f"\n실패 — {body['error_message']}", file=sys.stderr)
                return 1

        print("\n실패 — 폴링 시간 초과. PROCESSING 에서 멈췄다", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
