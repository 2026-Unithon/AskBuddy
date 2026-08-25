"""시드 knowledge_cards 3건에 OpenAI 임베딩을 채운다.

사용:
  cd api
  .venv\\Scripts\\python scripts/seed_embeddings.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# api/ 를 import 루트로
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import asyncpg
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=True)

from app.config import get_settings  # noqa: E402
from app.reg.embeddings import content_hash, embed_texts, vector_literal  # noqa: E402


async def main() -> None:
    settings = get_settings()
    conn = await asyncpg.connect(settings.supabase_db_url)
    try:
        rows = await conn.fetch(
            """
            select c.card_id, c.store_id, c.title, c.content
            from knowledge_cards c
            join stores s on s.store_id = c.store_id
            where s.store_slug = 'demo-cafe'
              and c.is_verified = true
            order by c.card_id
            """
        )
        if not rows:
            raise SystemExit("demo-cafe 승인 카드가 없다. 002_seed_demo.sql 을 먼저 적용하라.")

        texts = [f"{r['title']}\n{r['content']}" for r in rows]
        vectors = embed_texts(texts)

        async with conn.transaction():
            for r, text, vec in zip(rows, texts, vectors, strict=True):
                await conn.execute(
                    """
                    insert into card_embeddings (
                      card_id, store_id, chunk_index, chunk_text, chunk_tokens,
                      embedding, dimension, model_name, content_hash, lexical_tsv, is_stale
                    ) values (
                      $1, $2, 0, $3, null,
                      $4::vector, $5, $6, $7,
                      to_tsvector('simple', $3), false
                    )
                    on conflict (card_id, chunk_index) do update set
                      chunk_text = excluded.chunk_text,
                      embedding = excluded.embedding,
                      model_name = excluded.model_name,
                      content_hash = excluded.content_hash,
                      lexical_tsv = excluded.lexical_tsv,
                      is_stale = false,
                      updated_at = now()
                    """,
                    int(r["card_id"]),
                    int(r["store_id"]),
                    text,
                    vector_literal(vec),
                    settings.embedding_dim,
                    settings.embedding_model,
                    content_hash(text),
                )
        print(f"ok: embedded {len(rows)} cards for demo-cafe")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
