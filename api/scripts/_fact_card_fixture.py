"""실제 DB 검증용 사실 카드 도우미. 유료 호출 없음(mock 조립, 합성 벡터).

seed_fact_card — 점주 직접 입력(OWNER_TEXT) 자료를 만들고 원장 → 사실 조립 → 사실 카드 초안까지.
publish_card   — 카드의 현재 초안을 합성 벡터로 공개한다.
attribute_cost — 승인·제외·복원 라우트가 이어받을 원본 자료의 합성 비용 귀속 행을 넣는다.
edit_fact_value — 사실 편집 저장(PUT /cards/{id}/facts)으로 첫 사실 값만 바꾼 새 초안 판을 만든다.
blockless_card — 판 1 은 있지만 사실 블록이 없는 카드(공개 거절 확인용).
.env 의 INGEST_MODE 가 무엇이든 조립은 mock 으로 돈다(유료 호출 0).
"""
from __future__ import annotations

from unittest.mock import patch

from app.cards import router as card_router
from app.cards.fact_edit_schemas import FactEditRequest
from app.config import get_settings
from app.contracts.usage import UsageContext
from app.db_session import ShortSession
from app.ingest import extract, pipeline
from app.ingest import repository as repo
from app.ingest.schemas import Evidence, ExtractedAssertion
from app.publish.approval import CardChange, PublishCardsResult, publish_cards


def assertion(ref: str, subject: str, attribute: str, value: str, *, unit: str = "",
              source_id: int = 0) -> ExtractedAssertion:
    """합성 사실 하나. 원문은 `대상 속성 값단위`."""
    return ExtractedAssertion(local_ref=ref, original_assertion=f"{subject} {attribute} {value}{unit}",
                              subject=subject, attribute=attribute, value=value, unit=unit,
                              confidence=0.95, evidence=Evidence(source_id=source_id, timestamp_sec=0))


def _mock_settings():
    """조립 호출이 mock 구현으로 가도록 ingest_mode 만 바꾼 설정."""
    return get_settings().model_copy(update={"ingest_mode": "mock"})


async def seed_fact_card(pool, *, store_id: int, owner_user_id: int,
                         assertions: list[ExtractedAssertion],
                         title: str = "합성 자료") -> tuple[int, int]:
    """OWNER_TEXT 자료 하나를 원장·조립까지 처리한다. (card_id, draft_version_id).

    이 자료의 사실이 이어진 카드가 여러 장이면 card_id 가 가장 작은 카드. 공개는 하지 않는다.
    """
    async with pool.acquire() as conn:
        source_id = int(await conn.fetchval(
            "insert into sources (store_id, uploaded_by, source_type, title, file_url, "
            "content_hash, status, processed_at) "
            "values ($1, $2, 'OWNER_TEXT', $3, null, null, 'PROCESSING', now()) "
            "returning source_id", store_id, owner_user_id, title))
        async with conn.transaction():
            await pipeline._persist_ledger(conn, store_id, source_id, "OWNER_TEXT", assertions)
        categories = await repo.enabled_categories(conn, store_id)
    settings = _mock_settings()
    with patch.object(extract, "get_settings", lambda: settings):
        prepared = await pipeline._prepare_fact_assembly(
            pool, store_id, source_id, categories=list(categories), glossary=[],
            usage_sink=None, usage_base=None, raw_sink=None, strict=True)
    async with pool.acquire() as conn, conn.transaction():
        version = int(await conn.fetchval(
            "select category_version from stores where store_id = $1", store_id))
        await pipeline._persist_fact_cards(conn, store_id, source_id, categories, prepared,
                                           job_id=None, category_version=version)
        await repo.set_status(conn, store_id, source_id, "DONE")
        row = await conn.fetchrow(
            "select k.card_id, k.draft_version_id from fact_occurrences o "
            "join knowledge_cards k on k.store_id = o.store_id and k.card_id = o.card_id "
            "where o.store_id = $1 and o.source_id = $2 and o.disposition = 'LINKED' "
            "order by k.card_id limit 1", store_id, source_id)
    if row is None:
        raise RuntimeError("합성 사실 카드가 만들어지지 않았다")
    return int(row["card_id"]), int(row["draft_version_id"])


async def _vectors(texts, **kwargs):
    return [[1.0] + [0.0] * 1535 for _ in texts]


async def publish_card(pool, *, store_id: int, member_id: int, actor_user_id: int,
                       card_id: int) -> PublishCardsResult:
    """카드의 현재 초안을 공개한다. 임베딩은 합성 벡터(유료 호출 0)."""
    async with pool.acquire() as conn:
        draft = int(await conn.fetchval(
            "select draft_version_id from knowledge_cards where store_id = $1 and card_id = $2",
            store_id, card_id))
    context = UsageContext(store_id=str(store_id), stage="EMBED", cost_phase="OPERATING",
                           cost_purpose="PRODUCT",
                           logical_call_id=f"fixture-publish:{card_id}:{draft}")
    with patch("app.reg.index_preparation.recorded_embeddings", _vectors):
        return await publish_cards(pool, store_id=store_id, member_id=member_id,
                                   actor_user_id=actor_user_id,
                                   changes=[CardChange(card_id, draft, draft)],
                                   idempotency_key=f"fixture:{card_id}:{draft}",
                                   usage_context=context)


async def attribute_cost(conn, *, store_id: int, card_id: int) -> None:
    """카드 원본 자료의 합성 추출 비용 귀속 행 — 라우트 재발행(card_usage_context)이 이어받는다."""
    source_id = await conn.fetchval(
        "select source_id from knowledge_cards where store_id = $1 and card_id = $2",
        store_id, card_id)
    if source_id is None:
        return
    await conn.execute(
        "insert into ai_usage_attempts (store_id, cost_phase, stage, logical_call_id, "
        "requested_model, source_id) "
        "select $1, 'REGISTRATION', 'EXTRACT', $2, 'synthetic-extract', $3 "
        "where not exists (select 1 from ai_usage_attempts where store_id = $1 and source_id = $3)",
        store_id, f"synthetic-extract:{source_id}", source_id)


async def edit_fact_value(pool, *, store_id: int, owner_user_id: int, card_id: int,
                          value: str, key: str) -> int:
    """첫 사실의 값만 `value` 로 고친 새 초안 판(OWNER_EDIT). 실제 사실 편집 라우트를 거친다."""
    claims = {"user_id": owner_user_id, "store_id": store_id, "role": "OWNER"}
    view = await card_router.get_card_facts(card_id, ShortSession(pool), claims)
    blocks = []
    first = True
    for block in view.blocks:
        items = []
        for f in block.facts:
            if first:
                fields = {"sentence": f.sentence.replace(f.value or "", value) if f.value
                          else f"{f.sentence} {value}",
                          "polarity": f.polarity, "value": value, "unit": f.unit,
                          "conditions": list(f.conditions), "exceptions": list(f.exceptions),
                          "step_order": f.step_order}
                items.append({"op": "MODIFY", "fact_revision_id": f.fact_revision_id,
                              "fact": fields})
                first = False
            else:
                items.append({"op": "KEEP", "fact_revision_id": f.fact_revision_id})
        if items:
            blocks.append({"kind": block.kind, "items": items})
    req = FactEditRequest.model_validate({"expected_version_id": view.version_id,
                                          "idempotency_key": key, "blocks": blocks})
    await card_router.save_card_facts(card_id, req, ShortSession(pool), claims)
    async with pool.acquire() as conn:
        return int(await conn.fetchval(
            "select draft_version_id from knowledge_cards where store_id = $1 and card_id = $2",
            store_id, card_id))


async def blockless_card(conn, *, store_id: int, category_id: int | None, title: str,
                         content: str) -> tuple[int, int]:
    """판 1 만 있고 사실 블록이 없는 카드. (card_id, version_id). 공개 경로가 거절해야 한다."""
    card_id = int(await conn.fetchval(
        "insert into knowledge_cards (store_id, category_id, title, content, confidence) "
        "values ($1, $2, $3, $4, 90) returning card_id", store_id, category_id, title, content))
    version_id = int(await conn.fetchval(
        "insert into card_versions (store_id, card_id, version_no, title, content, change_source) "
        "values ($1, $2, 1, $3, $4, 'EXTRACTION') returning version_id",
        store_id, card_id, title, content))
    await conn.execute(
        "update knowledge_cards set draft_version_id = $3 where store_id = $1 and card_id = $2",
        store_id, card_id, version_id)
    return card_id, version_id
