"""운영자 로그인 실패 횟수. 서버가 한 대라 프로세스 메모리에서 센다.

서버를 여러 대로 늘리면 저장 위치를 다시 정한다 (OPS_OPERATOR_ACCESS_DESIGN §4-1).
"""
from __future__ import annotations

import time
from collections.abc import Callable

# 키 개수 상한. 여러 이메일로 두드려도 메모리가 늘지 않게, 넘으면 가장 오래전에 실패한 키부터 밀어낸다
_SWEEP_AT = 10_000


class LoginLimiter:
    def __init__(self, max_failures: int, window_seconds: float,
                 clock: Callable[[], float] = time.monotonic,
                 max_keys: int = _SWEEP_AT) -> None:
        self._max = max_failures
        self._window = window_seconds
        self._clock = clock
        self._max_keys = max_keys
        # 삽입 순서 = 마지막 실패의 오래된 순서. 갱신할 때 뒤로 옮기므로 맨 앞이 가장 오래된 키다
        self._failures: dict[tuple[str, str], list[float]] = {}

    def _recent(self, key: tuple[str, str]) -> list[float]:
        now = self._clock()
        kept = [t for t in self._failures.get(key, []) if now - t < self._window]
        if kept:
            self._failures[key] = kept
        else:
            self._failures.pop(key, None)
        return kept

    def try_acquire(self, ip: str, email: str) -> bool:
        """막혀 있으면 False. 아니면 시도를 임시 실패로 먼저 세고 True.

        await 없이 한 번에 끝나므로 이벤트 루프에서 원자적이다. 동시 요청이 bcrypt 를
        기다리는 동안 모두 통과하는 일을 막는다. 성공하면 호출자가 reset 으로 지운다.
        """
        if len(self._recent((ip, email))) >= self._max:
            return False
        key = (ip, email)
        kept = self._recent(key)
        self._failures.pop(key, None)
        # 전체를 훑지 않고 맨 앞(가장 오래된 키)만 밀어내므로 요청당 일이 일정하다
        while len(self._failures) >= self._max_keys:
            del self._failures[next(iter(self._failures))]
        self._failures[key] = [*kept, self._clock()]
        return True

    def reset(self, ip: str, email: str) -> None:
        self._failures.pop((ip, email), None)
