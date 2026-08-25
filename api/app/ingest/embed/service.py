"""준혁 — 승인된 카드의 임베딩 적재.

임베딩 생성 자체는 관호님 `app.reg.embeddings.embed_texts` 를 호출한다.
여기에 새 임베딩 함수를 만들지 않는다 — 모델명·차원이 갈라진다 (D4).
그쪽은 동기 함수라 이벤트 루프를 막지 않도록 to_thread 로 감싼다.
"""
import asyncio
import logging

import asyncpg

from app.ingest import repository as repo
from app.reg.embeddings import content_hash, embed_texts

logger = logging.getLogger(__name__)


async def embed_card(conn: asyncpg.Connection, store_id: int, card_id: int) -> int:
    """승인된 카드 1건을 임베딩해 card_embeddings 에 적재한다. 반환값은 청크 수."""
    card = await repo.get_card(conn, store_id, card_id)
    if card is None:
        raise LookupError(f"card {card_id} not found in store {store_id}")
    if not card["is_verified"]:
        raise ValueError(
            f"card {card_id} 는 아직 승인되지 않았다. 승인된 카드만 검색 대상이다"
        )

    # 카드는 짧다. 청크를 나누지 않고 제목+본문 한 덩어리로 넣는다
    chunk_text = f"{card['title']}\n{card['content']}".strip()
    vectors = await asyncio.to_thread(embed_texts, [chunk_text])

    from app.config import get_settings
    s = get_settings()
    await repo.upsert_embedding(
        conn, store_id,
        card_id=card_id,
        chunk_index=0,
        chunk_text=chunk_text,
        embedding=vectors[0],
        content_hash=content_hash(chunk_text),
        model_name=s.embedding_model,
        dimension=s.embedding_dim,
    )
    logger.info("embed card=%s store=%s chunks=1", card_id, store_id)
    return 1
