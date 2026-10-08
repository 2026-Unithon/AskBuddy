"""배치 동시 실행 — 결과는 언제나 입력 순서대로 (W3-1b)."""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from typing import TypeVar

T = TypeVar("T")


async def gather_in_order(calls: Sequence[Callable[[], Awaitable[T]]], *,
                          concurrency: int) -> list[T | Exception]:
    """calls 를 최대 concurrency 개씩 동시에 부르고 결과를 calls 순서대로 돌려준다.

    - concurrency <= 1 이면 앞에서부터 하나씩 await 한다(동시 실행 없음).
    - 각 호출의 `Exception` 은 그 자리에 담아 돌려준다. 다른 호출은 계속 돈다.
      `BaseException`(취소 등)은 담지 않고 그대로 올린다.
    - 빈 목록이면 빈 목록.
    """
    if concurrency <= 1:
        out: list[T | Exception] = []
        for call in calls:
            try:
                out.append(await call())
            except Exception as exc:
                out.append(exc)
        return out

    gate = asyncio.Semaphore(concurrency)

    async def run(call: Callable[[], Awaitable[T]]) -> T | Exception:
        async with gate:
            try:
                return await call()
            except Exception as exc:
                return exc

    return list(await asyncio.gather(*(run(call) for call in calls)))
