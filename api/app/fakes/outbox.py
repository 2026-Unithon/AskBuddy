"""가짜 outbox 소비자 (CP-03, §4.3).

전달은 at-least-once 다. **같은 사건이 두 번 오고, 순서가 뒤집히고, 빠지기도 한다.**
소비자가 이걸 견디지 못하면 캐시가 옛 지식으로 되돌아간다 — 점주가 고친 값이
잠깐 뒤에 원래대로 보이는 종류의 버그다.

세 가지를 지킨다:
  1. `(store, consumer, event_id)` 중복은 한 번만 반영한다
  2. 낮은 판 번호로 되돌리지 않는다. 늦게 온 옛 사건은 버린다
  3. 번호가 건너뛰면 재동기화가 필요하다고 표시한다. 조용히 넘어가지 않는다
"""
from __future__ import annotations

from app.contracts.publication import OutboxEvent


class FakeOutbox:
    def __init__(self, consumer: str = "search-index"):
        self.consumer = consumer
        self._seen: set[tuple[str, str, str]] = set()
        # store_id → 마지막으로 반영한 knowledge_revision
        self.applied: dict[str, int] = {}
        self.duplicates = 0
        self.out_of_order = 0
        self.resync_needed: set[str] = set()

    def deliver(self, event: OutboxEvent) -> str:
        """반영 결과를 돌려준다: APPLIED / DUPLICATE / STALE / RESYNC."""
        key = (event.store_id, self.consumer, event.event_id)
        if key in self._seen:
            self.duplicates += 1
            return "DUPLICATE"
        self._seen.add(key)

        if event.knowledge_revision is None:
            # 점주 답변 사건은 판 번호를 옮기지 않는다
            return "APPLIED"

        incoming = int(event.knowledge_revision)
        current = self.applied.get(event.store_id, 0)
        if incoming <= current:
            # 순서가 뒤집혔다. 옛 판으로 되돌리면 고친 값이 되살아난다
            self.out_of_order += 1
            return "STALE"
        if incoming > current + 1:
            # 중간이 비었다. 지금 manifest 로 다시 맞춰야 한다
            self.resync_needed.add(event.store_id)
            self.applied[event.store_id] = incoming
            return "RESYNC"
        self.applied[event.store_id] = incoming
        return "APPLIED"
