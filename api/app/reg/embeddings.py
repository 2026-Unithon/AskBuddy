"""관호 — OpenAI 임베딩 (D4 고정). ingest 도 이 모듈을 호출한다."""
from __future__ import annotations

import hashlib
import logging
import time

from openai import OpenAI

from app.config import get_settings

logger = logging.getLogger(__name__)


def embed_texts(texts: list[str]) -> list[list[float]]:
    """text-embedding-3-small / 1536. 빈 입력이면 빈 리스트."""
    if not texts:
        return []
    s = get_settings()
    if not s.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY 가 비어 있다")
    client = OpenAI(api_key=s.openai_api_key)
    t0 = time.perf_counter()
    resp = client.embeddings.create(model=s.embedding_model, input=texts)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    usage = getattr(resp, "usage", None)
    tokens = getattr(usage, "total_tokens", None) if usage else None
    logger.info(
        "embedding model=%s n=%s tokens=%s elapsed_ms=%.1f",
        s.embedding_model,
        len(texts),
        tokens,
        elapsed_ms,
    )
    by_idx = {item.index: item.embedding for item in resp.data}
    vectors = [by_idx[i] for i in range(len(texts))]
    dim = s.embedding_dim
    for v in vectors:
        if len(v) != dim:
            raise RuntimeError(f"embedding dim {len(v)} != {dim}")
    return vectors


def embed_text(text: str) -> list[float]:
    return embed_texts([text])[0]


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def vector_literal(embedding: list[float]) -> str:
    return "[" + ",".join(f"{x:.8f}" for x in embedding) + "]"
