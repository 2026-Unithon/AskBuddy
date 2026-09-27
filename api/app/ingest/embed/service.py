"""카드 임베딩 비용 귀속.

옛 색인(card_embeddings)에 직접 쓰던 prepare_embedding·embed_card 는 2026-09-27 제거했다.
공개 카드의 색인은 publish_cards 가 R 색인 준비(app.reg.index_preparation)로만 만든다.
"""
from uuid import uuid4
from app.contracts.usage import UsageContext


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
