"""매장 초기 공개 색인 준비 (W).

R 검색·점주 답변 후보 검색은 **활성 공개 색인**(현재 공개판에 연결된 R 색인)만 읽는다.
옛 색인(card_embeddings) 시절에 승인된 카드만 있는 매장은 공개판·색인이 없어서
`INDEX_UNAVAILABLE` 이 난다. 여기서는 그런 매장을 찾아 현재 승인 카드 그대로
한 번 다시 발행(`publish_cards(changes=[])`)해 색인을 만든다.

재발행은 임베딩 비용이 든다. 호출부(스크립트·운영자)가 명시적으로 부를 때만 실행한다.
"""
from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from app.config import get_settings
from app.contracts.usage import UsageContext
from app.publish.approval import PublishCardsResult, publish_cards
from app.reg.index_preparation import INDEX_CONFIG_VERSION

# 색인 상태
READY = "READY"          # 현재 공개판에 지금 설정과 같은 색인이 붙어 있다
MISSING = "MISSING"      # 승인 카드는 있는데 활성 색인이 없다 — 준비가 필요하다
OUTDATED = "OUTDATED"    # 활성 색인은 있으나 임베딩 모델·색인 설정이 지금과 다르다
EMPTY = "EMPTY"          # 승인 카드가 하나도 없다 — 색인할 것이 없다

NEEDS_BOOTSTRAP = (MISSING, OUTDATED)


@dataclass(frozen=True)
class IndexStatus:
    store_id: int
    status: str
    approved_cards: int
    publication_revision: int


async def index_status(conn, *, store_id: int) -> IndexStatus:
    """매장의 활성 공개 색인 상태. R 의 read_current_index 와 같은 연결 조건을 본다."""
    approved = int(await conn.fetchval(
        """
        select count(*) from knowledge_cards
        where store_id = $1 and review_status = 'APPROVED' and is_verified
          and published_version_id is not null
        """,
        store_id))
    publication_revision = int(await conn.fetchval(
        "select coalesce(max(publication_revision), 0) from knowledge_publications "
        "where store_id = $1",
        store_id))
    active = await conn.fetchrow(
        """
        select i.embedding_model, i.index_config_version
        from knowledge_publications p
        join knowledge_snapshots s on s.store_id = p.store_id
          and s.snapshot_id = p.current_snapshot_id
          and s.knowledge_revision = p.knowledge_revision
        join r_index_publications a on a.store_id = p.store_id
          and a.snapshot_id = s.snapshot_id
        join r_index_preparations i on i.store_id = a.store_id
          and i.prepared_id = a.prepared_id and i.state = 'CONSUMED'
        where p.store_id = $1
        """,
        store_id)
    if approved == 0:
        status = EMPTY
    elif active is None:
        status = MISSING
    elif (active["embedding_model"] != get_settings().embedding_model
          or active["index_config_version"] != INDEX_CONFIG_VERSION):
        status = OUTDATED
    else:
        status = READY
    return IndexStatus(store_id, status, approved, publication_revision)


async def stores_needing_index(pool) -> list[IndexStatus]:
    """승인 카드가 있는 모든 매장 중 색인 준비가 필요한 매장."""
    async with pool.acquire() as conn:
        # store-isolation-ok: 운영 점검용 매장 목록. 이후 조회는 매장별 store_id 로 한다
        store_ids = [int(r["store_id"]) for r in await conn.fetch(
            "select distinct store_id from knowledge_cards "
            "where review_status = 'APPROVED' and is_verified "
            "and published_version_id is not null order by store_id")]
        statuses = [await index_status(conn, store_id=sid) for sid in store_ids]
    return [s for s in statuses if s.status in NEEDS_BOOTSTRAP]


async def bootstrap_store_index(
    pool, *, store_id: int, cost_phase: str = "OPERATING",
) -> tuple[IndexStatus, PublishCardsResult | None]:
    """색인이 없거나 낡은 매장이면 현재 승인 카드 그대로 다시 발행해 색인을 만든다.

    READY·EMPTY 면 아무것도 하지 않고 (상태, None) 을 돌려준다. 재발행 결과의
    EMPTY_MANIFEST 는 승인 카드가 모두 출처 없는 레거시라 실을 수 없다는 뜻이다.
    """
    async with pool.acquire() as conn:
        status = await index_status(conn, store_id=store_id)
        if status.status not in NEEDS_BOOTSTRAP:
            return status, None
        owner = await conn.fetchrow(
            """
            select member_id, user_id from store_members
            where store_id = $1 and member_role = 'OWNER'
            order by member_id limit 1
            """,
            store_id)
    if owner is None:
        raise LookupError(f"매장 {store_id} 의 점주 멤버십이 없다")
    operation = str(uuid4())
    context = UsageContext(
        store_id=str(store_id), stage="EMBED", cost_phase=cost_phase,
        cost_purpose="PRODUCT", logical_call_id=f"index-bootstrap:{operation}",
        operation_id=operation)
    result = await publish_cards(
        pool, store_id=store_id, member_id=int(owner["member_id"]),
        actor_user_id=int(owner["user_id"]), changes=[],
        # 같은 판에서의 재시도는 같은 키로 멱등하게 묶인다
        idempotency_key=f"index-bootstrap:{status.publication_revision}",
        usage_context=context)
    return status, result
