"""준혁 — 승인된 카드의 임베딩 적재.

모델명·차원은 config 에서만 읽는다 (D4). 여기에 리터럴로 쓰지 않는다.
관호님 /reg/* 의 임베딩 함수가 리포에 합류하면 _embed() 한 줄을 그 함수 호출로
바꾸면 된다. 양쪽 모두 config 를 보므로 모델·차원이 갈라지지 않는다.
"""
import hashlib
import logging
import time

import asyncpg
from openai import AsyncOpenAI

from app.config import get_settings
from app.ingest import repository as repo

logger = logging.getLogger(__name__)


async def _embed(texts: list[str]) -> list[list[float]]:
    s = get_settings()
    if not s.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY 가 없다. api/.env 를 확인하라")

    client = AsyncOpenAI(api_key=s.openai_api_key)
    started = time.perf_counter()
    res = await client.embeddings.create(model=s.embedding_model, input=texts)
    logger.info("embed model=%s n=%d elapsed=%.1fs tokens=%s",
                s.embedding_model, len(texts), time.perf_counter() - started,
                getattr(res.usage, "total_tokens", "?"))

    vectors = [d.embedding for d in res.data]
    for v in vectors:
        if len(v) != s.embedding_dim:
            raise RuntimeError(
                f"임베딩 차원 불일치: {len(v)} != {s.embedding_dim}. "
                "모델을 바꿨다면 임계값·골든셋을 전면 재측정해야 한다 (D4)"
            )
    return vectors


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
    vector = (await _embed([chunk_text]))[0]
    s = get_settings()

    await repo.upsert_embedding(
        conn, store_id,
        card_id=card_id,
        chunk_index=0,
        chunk_text=chunk_text,
        embedding=vector,
        content_hash=hashlib.sha256(chunk_text.encode("utf-8")).hexdigest(),
        model_name=s.embedding_model,
        dimension=s.embedding_dim,
    )
    return 1
