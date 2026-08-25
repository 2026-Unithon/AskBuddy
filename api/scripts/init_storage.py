"""원본 파일 버킷 생성. 각자 로컬에서 최초 1회 실행한다.

    python scripts/init_storage.py

Studio 에서 손으로 만들면 셋의 설정이 갈라진다. 스크립트로 통일한다.
버킷은 비공개다. 브라우저는 서명 URL 로만 접근한다.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

from app.config import get_settings  # noqa: E402

MAX_FILE_SIZE = 500 * 1024 * 1024      # 500MB — 영상 여유분


def _already_exists(res: httpx.Response) -> bool:
    if res.status_code == 409:
        return True
    try:
        body = res.json()
    except Exception:
        return False
    return (body.get("code") == "BucketAlreadyExists"
            or str(body.get("statusCode")) == "409")


async def main() -> int:
    s = get_settings()
    if not s.supabase_service_key:
        print("SUPABASE_SERVICE_KEY 가 비어 있다. api/.env 를 채워라\n"
              "  supabase status  출력의 SECRET_KEY(=service_role) 를 넣는다", file=sys.stderr)
        return 2

    headers = {"Authorization": f"Bearer {s.supabase_service_key}"}
    async with httpx.AsyncClient(timeout=30) as c:
        res = await c.post(
            f"{s.supabase_url}/storage/v1/bucket",
            headers=headers,
            json={"name": s.storage_bucket, "id": s.storage_bucket,
                  "public": False, "file_size_limit": MAX_FILE_SIZE},
        )
        if res.status_code in (200, 201):
            print(f"버킷 '{s.storage_bucket}' 생성 완료 (비공개, 최대 500MB)")
        elif _already_exists(res):
            # Storage 는 중복일 때 HTTP 400 에 본문으로 409 를 담아 보낸다.
            # HTTP 코드만 보면 실패로 오인한다
            print(f"버킷 '{s.storage_bucket}' 이미 존재 — 넘어간다")
        else:
            print(f"생성 실패 {res.status_code}: {res.text[:300]}", file=sys.stderr)
            return 1

        listed = await c.get(f"{s.supabase_url}/storage/v1/bucket", headers=headers)
        names = [b["name"] for b in listed.json()] if listed.status_code == 200 else []
        print(f"현재 버킷: {', '.join(names) or '(없음)'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
