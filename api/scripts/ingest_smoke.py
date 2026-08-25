"""M1 경계 확인 — 업로드 등록 → 처리 → 폴링 → 카드 확인.

    uvicorn app.main:app --reload --port 8000        # 다른 터미널
    export ASKBUDDY_TOKEN=$(python scripts/dev_token.py)
    python scripts/ingest_smoke.py

INGEST_MODE=mock 이면 LLM 을 호출하지 않으므로 키 없이 돈다.
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


async def main() -> int:
    token = TOKEN
    if not token:
        # export 는 셸 단위라 터미널을 옮기면 사라진다. 없으면 직접 발급한다
        from dev_token import mint
        try:
            token = await mint()
        except Exception as e:
            print(f"토큰 발급 실패: {e}", file=sys.stderr)
            return 2
        print("[token] ASKBUDDY_TOKEN 이 없어 직접 발급했다")

    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(base_url=BASE, headers=headers, timeout=30) as c:
        health = await c.get("/health")
        print(f"[health] {health.status_code} {health.text}")

        res = await c.post("/ingest/sources", json={
            "source_type": "VOICE",
            "file_url": "voice/smoke-test.m4a",
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
