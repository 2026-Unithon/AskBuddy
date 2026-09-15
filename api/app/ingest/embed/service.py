"""임베딩 외부 준비 → 짧은 DB 트랜잭션에서 승인·내용 재검사 후 저장."""
from dataclasses import dataclass
from uuid import uuid4
import asyncpg
from app.config import get_settings
from app.contracts.usage import UsageContext
from app.deps import get_pool
from app.ingest import repository as repo
from app.reg.embeddings import content_hash, recorded_embeddings
from app.usage import DbUsageSink


@dataclass(frozen=True)
class PreparedEmbedding:
    store_id: int
    text: str
    vector: list[float]
    model: str
    dimension: int


async def card_usage_context(db, store_id: int, card_id: int) -> UsageContext:
    """카드 승인 여부가 아니라 서버가 기록한 원본 작업의 귀속을 이어받는다."""
    card = await db.fetchrow(
        "select source_id from knowledge_cards where store_id=$1 and card_id=$2", store_id, card_id)
    if card is None:
        raise LookupError("card not found")
    source_id = card["source_id"]
    prior = None
    if source_id is not None:
        prior = await db.fetchrow(
            "select cost_phase, cost_purpose, registration_campaign_id, job_id from ai_usage_attempts "
            "where store_id=$1 and source_id=$2 and stage in ('EXTRACT','ASSEMBLE') "
            "order by started_at desc, usage_attempt_id desc limit 1", store_id, source_id)
        if prior is None:
            raise ValueError("원본 작업의 비용 귀속이 없어 임베딩을 보류합니다")
    operation = str(uuid4())
    return UsageContext(store_id=str(store_id), stage="EMBED",
        cost_phase=prior["cost_phase"] if prior else "OPERATING",
        cost_purpose=prior["cost_purpose"] if prior else "PRODUCT",
        registration_campaign_id=prior["registration_campaign_id"] if prior else None,
        source_id=str(source_id) if source_id is not None else None,
        job_id=str(prior["job_id"]) if prior and prior["job_id"] is not None else None,
        logical_call_id=f"card-embed:{operation}", operation_id=operation)


async def prepare_embedding(store_id: int, title: str, content: str, *,
                            cost_phase: str, cost_purpose: str = "PRODUCT",
                            context: UsageContext | None = None, sink=None) -> PreparedEmbedding:
    """호출자는 DB 트랜잭션 전에 준비한다. 목적·단계는 서버가 결정한다."""
    text = f"{title}\n{content}".strip()
    if context is None:
        operation = str(uuid4())
        context = UsageContext(store_id=str(store_id), stage="EMBED",
                               cost_phase=cost_phase, cost_purpose=cost_purpose,
                               logical_call_id=f"card-embed:{operation}", operation_id=operation)
    if context.store_id != str(store_id) or context.stage != "EMBED":
        raise ValueError("embedding context scope mismatch")
    settings = get_settings()
    vectors = await recorded_embeddings([text], context=context,
                                        sink=sink if sink is not None else DbUsageSink(get_pool()))
    return PreparedEmbedding(store_id, text, vectors[0], settings.embedding_model, settings.embedding_dim)


async def embed_card(conn: asyncpg.Connection, store_id: int, card_id: int, *,
                     prepared: PreparedEmbedding) -> int:
    """외부 호출 없이 저장한다. 승인·내용은 같은 트랜잭션에서 잠금 후 확인한다."""
    card = await conn.fetchrow(
        "select card_id, title, content, is_verified from knowledge_cards "
        "where store_id = $1 and card_id = $2 for update", store_id, card_id)
    if card is None:
        raise LookupError(f"card {card_id} not found in store {store_id}")
    if not card["is_verified"]:
        raise ValueError("승인된 카드만 검색 대상이다")
    text = f"{card['title']}\n{card['content']}".strip()
    if prepared.store_id != store_id or prepared.text != text:
        raise ValueError("임베딩 준비 후 카드 내용이 변경됐다")
    await repo.upsert_embedding(conn, store_id, card_id=card_id, chunk_index=0,
                                chunk_text=text, embedding=prepared.vector,
                                content_hash=content_hash(text), model_name=prepared.model,
                                dimension=prepared.dimension)
    return 1
