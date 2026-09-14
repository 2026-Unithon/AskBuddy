"""Storage 원가 계측 (CP-00B).

`sources.file_size` 의 클라이언트 값만 합산하지 않는다. 그 값은 프론트가 보낸 것이고,
프레임 같은 파생물은 거기 없다. store-a 는 원본 118MB 인데 프레임 770장이 따로 쌓인다.

저장비는 **누적**이다. 등록 파일은 매월 남아 있으므로 한 달 치가 아니라
`Σ(bytes × 존재시간)` 을 GB-month 로 환산한다.
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

_GB = Decimal(1024) ** 3


async def list_store_objects(store_id: int) -> list[dict[str, Any]]:
    """매장 경로 아래 실제 object 목록. 서버가 확인한 bytes 를 쓴다.

    클라이언트가 보고한 크기를 믿지 않는다 — 틀릴 수도, 파생물이 빠질 수도 있다.
    """
    s = get_settings()
    if not s.supabase_service_key:
        raise RuntimeError("SUPABASE_SERVICE_KEY 가 없다")

    out: list[dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=30) as client:
        for sub in ("voice", "video", "kakao", "scan", "frames"):
            prefix = f"{store_id}/{sub}"
            offset = 0
            while True:
                res = await client.post(
                    f"{s.supabase_url}/storage/v1/object/list/{s.storage_bucket}",
                    headers={"Authorization": f"Bearer {s.supabase_service_key}"},
                    json={"prefix": prefix, "limit": 100, "offset": offset},
                )
                if res.status_code != 200:
                    logger.warning("storage list 실패 %s: %s", prefix, res.status_code)
                    break
                items = res.json() or []
                for item in items:
                    meta = item.get("metadata") or {}
                    out.append({
                        "path": f"{prefix}/{item.get('name')}",
                        # 크기를 못 받으면 null 이다. 0 으로 채우면 저장비가 사라진다
                        "bytes": meta.get("size"),
                        "created_at": item.get("created_at"),
                        "kind": sub,
                    })
                if len(items) < 100:
                    break
                offset += 100
    return out


def storage_cost(objects: list[dict[str, Any]], months: Decimal,
                 per_gb_month: Decimal | None) -> dict[str, Any]:
    """저장 비용과 **관측률**을 함께 낸다.

    크기를 못 받은 object 가 있으면 총액을 주장하지 않는다.
    저장비는 누적이라 작은 누락도 개월 수만큼 커진다.
    """
    known_bytes = sum(int(o["bytes"]) for o in objects if o.get("bytes") is not None)
    unknown = sum(1 for o in objects if o.get("bytes") is None)
    gb = Decimal(known_bytes) / _GB

    complete = unknown == 0 and bool(objects)
    cost = (gb * months * per_gb_month
            if complete and per_gb_month is not None else None)

    return {
        "object_count": len(objects),
        "unknown_size_count": unknown,
        "known_bytes": known_bytes,
        "known_gb": float(round(gb, 6)),
        "months": float(months),
        # 크기 미관측이나 요율 부재면 null. 0 으로 두면 저장비가 공짜로 보인다
        "cost_usd": cost,
        "cost_status": "COMPLETE" if complete else ("UNKNOWN" if not objects else "PARTIAL"),
    }
