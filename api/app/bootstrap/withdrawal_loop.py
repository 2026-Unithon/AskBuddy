"""사장님 탈퇴 유예가 지난 매장을 한 시간마다 파기한다(D22). 파기는 purge.py(계획 9)."""
from __future__ import annotations

import asyncio
import logging

from app.bootstrap import purge

logger = logging.getLogger(__name__)
SWEEP_SECONDS = 3600


async def withdrawal_loop(pool) -> None:
    while True:
        try:
            purged = await purge.purge_due_stores(pool)
            if purged:
                logger.info("store purge sweep purged=%d", len(purged))
        except Exception as exc:  # noqa: BLE001 — 다음 시간에 다시 한다
            # 예외 본문에는 쿼리·경로가 섞일 수 있어 종류만 남긴다
            logger.error("store purge sweep failed type=%s", type(exc).__name__)
        await asyncio.sleep(SWEEP_SECONDS)
