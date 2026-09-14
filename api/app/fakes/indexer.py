"""가짜 색인·발행 (CP-03, §4.1~4.2).

메모리에서 돌지만 **경합 규칙은 실제와 같게** 둔다. 여기서 쉽게 통과하면
실제 DB 트랜잭션으로 옮길 때 계약이 아니라 이 구현에 맞춰 개발한 것이 된다.

지키는 것 셋:
  1. 준비와 발행을 나눈다. 임베딩·hash 계산은 트랜잭션 밖에서, 판 번호 발급은 안에서
  2. 예상 revision 이 어긋나면 STALE 이다. 마지막 쓰기가 이기지 않는다
  3. 같은 멱등 키의 재시도는 판 번호를 올리지 않고 원래 결과를 되돌려준다
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from app.contracts.errors import ErrorDetail, ERROR_TABLE
from app.contracts.publication import (
    CardVisibilityRequest,
    PrepareIndexRequest,
    PrepareIndexResult,
    PublishKnowledgeRequest,
    PublishKnowledgeResult,
)

PREPARE_TTL = timedelta(minutes=15)
INDEX_CONFIG_VERSION = "fake-index/v1"


def _error(code: str, message: str, request_id: str = "fake") -> ErrorDetail:
    return ErrorDetail(code=code, message=message, request_id=request_id,
                       retryable=ERROR_TABLE[code][1],
                       retry_after_ms=1000 if code == "RATE_LIMITED" else None)


@dataclass
class _Prepared:
    prepared_id: str
    store_id: str
    content_hash: str
    expected_publication_revision: str
    expires_at: datetime


@dataclass
class _Store:
    publication_revision: int = 0
    knowledge_revision: int = 0
    snapshot_id: str | None = None
    snapshot_hash: str | None = None
    excluded_cards: set[str] = field(default_factory=set)


class FakeIndexer:
    def __init__(self, now=None):
        self._now = now or (lambda: datetime.now(UTC))
        self._stores: dict[str, _Store] = {}
        self._prepared: dict[str, _Prepared] = {}
        self._idempotent: dict[tuple, object] = {}
        self._seq = 1000
        self.events: list[dict] = []

    # ── 상태 조회 ────────────────────────────────────────────────
    def store(self, store_id: str) -> _Store:
        return self._stores.setdefault(store_id, _Store())

    def _next_id(self) -> str:
        self._seq += 1
        return str(self._seq)

    def _replay(self, req, kind: str):
        """같은 키·같은 본문이면 원래 결과, 같은 키·다른 본문이면 충돌 (§4.3)."""
        key = (req.scope.store_id, kind, req.idempotency.key)
        seen = self._idempotent.get(key)
        if seen is None:
            return None, None
        body_hash, result = seen
        if body_hash != req.idempotency.body_hash:
            return None, "IDEMPOTENCY_CONFLICT"
        return result, None

    def _remember(self, req, kind: str, result):
        key = (req.scope.store_id, kind, req.idempotency.key)
        self._idempotent[key] = (req.idempotency.body_hash, result)
        return result

    # ── PrepareIndex ────────────────────────────────────────────
    async def prepare_index(self, req: PrepareIndexRequest) -> PrepareIndexResult:
        replay, conflict = self._replay(req, "prepare")
        if conflict:
            return PrepareIndexResult(status="FAILED", error=_error(
                conflict, "같은 키로 다른 요청이 들어왔어요"))
        if replay is not None:
            return replay

        store = self.store(req.scope.store_id)
        if req.expected_publication_revision != str(store.publication_revision):
            # 준비 단계에서 이미 어긋났다. 여기서 막지 않으면 오래된 내용으로 색인한다
            return PrepareIndexResult(status="FAILED", error=_error(
                "STALE_PUBLICATION", "먼저 최신 상태를 불러와 주세요"))

        prepared = _Prepared(
            prepared_id=self._next_id(), store_id=req.scope.store_id,
            content_hash=req.content_hash,
            expected_publication_revision=req.expected_publication_revision,
            expires_at=self._now() + PREPARE_TTL)
        self._prepared[prepared.prepared_id] = prepared
        return self._remember(req, "prepare", PrepareIndexResult(
            status="PREPARED", prepared_id=prepared.prepared_id,
            payload_hash=req.content_hash,
            index_config_version=INDEX_CONFIG_VERSION,
            expires_at=prepared.expires_at))

    # ── PublishKnowledge ────────────────────────────────────────
    async def publish(self, req: PublishKnowledgeRequest) -> PublishKnowledgeResult:
        replay, conflict = self._replay(req, "publish")
        if conflict:
            return PublishKnowledgeResult(status="FAILED", error=_error(
                conflict, "같은 키로 다른 요청이 들어왔어요"))
        if replay is not None:
            # 판 번호를 올리지 않는다. 재시도가 판을 늘리면 캐시가 계속 깨진다
            return replay.model_copy(update={"status": "ALREADY_APPLIED"})

        prepared = self._prepared.get(req.prepared_id)
        if prepared is None or prepared.store_id != req.scope.store_id:
            return PublishKnowledgeResult(status="FAILED", error=_error(
                "INVALID_REFERENCE", "준비 정보를 찾을 수 없어요"))
        if self._now() > prepared.expires_at:
            return PublishKnowledgeResult(status="FAILED", error=_error(
                "INDEX_PREPARE_TIMEOUT", "준비 시간이 지났어요. 다시 시도해 주세요"))

        store = self.store(req.scope.store_id)
        if req.expected_publication_revision != str(store.publication_revision):
            return PublishKnowledgeResult(status="STALE", error=_error(
                "STALE_PUBLICATION", "그 사이 다른 변경이 있었어요"))

        store.publication_revision += 1
        store.knowledge_revision += 1
        store.snapshot_id = self._next_id()
        store.snapshot_hash = prepared.content_hash
        result = PublishKnowledgeResult(
            status="PUBLISHED", snapshot_id=store.snapshot_id,
            snapshot_hash=store.snapshot_hash,
            knowledge_revision=str(store.knowledge_revision))
        self._emit(req.scope.store_id, "KNOWLEDGE_PUBLISHED", store.snapshot_id,
                   str(store.knowledge_revision))
        return self._remember(req, "publish", result)

    # ── 제외·복원 ────────────────────────────────────────────────
    async def set_visibility(
        self, req: CardVisibilityRequest
    ) -> PublishKnowledgeResult:
        replay, conflict = self._replay(req, "visibility")
        if conflict:
            return PublishKnowledgeResult(status="FAILED", error=_error(
                conflict, "같은 키로 다른 요청이 들어왔어요"))
        if replay is not None:
            return replay.model_copy(update={"status": "ALREADY_APPLIED"})

        store = self.store(req.scope.store_id)
        if req.expected_publication_revision != str(store.publication_revision):
            return PublishKnowledgeResult(status="STALE", error=_error(
                "STALE_PUBLICATION", "그 사이 다른 변경이 있었어요"))

        if req.action == "EXCLUDE":
            store.excluded_cards.add(req.card_id)
        else:
            store.excluded_cards.discard(req.card_id)
        store.publication_revision += 1
        # 보이는 지식이 달라졌으므로 판 번호도 오른다 (§4.2)
        store.knowledge_revision += 1
        store.snapshot_id = self._next_id()
        result = PublishKnowledgeResult(
            status="PUBLISHED", snapshot_id=store.snapshot_id,
            snapshot_hash=store.snapshot_hash or ("sha256:" + "0" * 64),
            knowledge_revision=str(store.knowledge_revision))
        self._emit(req.scope.store_id,
                   "CARD_EXCLUDED" if req.action == "EXCLUDE" else "CARD_RESTORED",
                   req.card_id, str(store.knowledge_revision))
        return self._remember(req, "visibility", result)

    def _emit(self, store_id: str, type_: str, aggregate_id: str,
              knowledge_revision: str) -> None:
        self.events.append(dict(
            event_id=self._next_id(), store_id=store_id, type=type_,
            aggregate_id=aggregate_id, knowledge_revision=knowledge_revision,
            occurred_at=self._now()))
