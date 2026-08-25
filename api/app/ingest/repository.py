"""준혁 (feat/input) — /ingest/* 의 모든 DB 접근.

규칙: 모든 함수는 store_id 를 필수 인자로 받는다. 기본값도 Optional 도 없다.
RLS 가 없으므로(D1) 여기서 빠뜨리면 그대로 전 매장이 열린다.
sources 하위 테이블은 source_id 로만 접근하지만, 진입 전에 반드시
get_source(store_id, source_id) 로 소유 매장을 확인한 뒤 호출한다.
"""
import asyncpg

MAX_ERROR_LEN = 500          # sources.error_message varchar(500)
MAX_TITLE_LEN = 200
MAX_CATEGORY_LEN = 50


# ── sources ────────────────────────────────────────────────────────────────

async def find_by_hash(
    conn: asyncpg.Connection, store_id: int, content_hash: str
) -> asyncpg.Record | None:
    return await conn.fetchrow(
        "select source_id, status from sources "
        "where store_id = $1 and content_hash = $2",
        store_id, content_hash,
    )


async def create_source(
    conn: asyncpg.Connection,
    store_id: int,
    *,
    uploaded_by: int,
    source_type: str,
    file_url: str,
    title: str | None,
    file_size: int | None,
    content_hash: str | None,
) -> int:
    return await conn.fetchval(
        "insert into sources "
        "  (store_id, uploaded_by, source_type, title, file_url, file_size, content_hash, status) "
        "values ($1, $2, $3, $4, $5, $6, $7, 'UPLOADED') "
        "returning source_id",
        store_id, uploaded_by, source_type,
        (title or "")[:MAX_TITLE_LEN] or None,
        file_url, file_size, content_hash,
    )


async def get_source(
    conn: asyncpg.Connection, store_id: int, source_id: int
) -> asyncpg.Record | None:
    return await conn.fetchrow(
        "select source_id, store_id, source_type, title, file_url, content_hash, status, "
        "       error_message, processed_at "
        "from sources where store_id = $1 and source_id = $2",
        store_id, source_id,
    )


async def set_status(
    conn: asyncpg.Connection,
    store_id: int,
    source_id: int,
    status: str,
    error_message: str | None = None,
) -> None:
    """FAILED 는 error_message 가 필수다 (개발가이드 6-1)."""
    await conn.execute(
        "update sources set status = $3::varchar, "
        "       error_message = $4, "
        "       processed_at = case when $3::varchar in ('DONE','FAILED') "
        "                           then now() else processed_at end "
        "where store_id = $1 and source_id = $2",
        store_id, source_id, status,
        (error_message or "")[:MAX_ERROR_LEN] or None,
    )


async def set_content_hash(
    conn: asyncpg.Connection, store_id: int, source_id: int, content_hash: str
) -> bool:
    """프론트가 해시를 안 보냈을 때 서버가 뒤늦게 채운다.

    이미 같은 해시의 자료가 있으면 unique 인덱스가 막는다. 그 경우 False 를
    돌려주고 조용히 넘어간다 — 중복 차단의 1차 방어선은 /ingest/sources 다.
    """
    try:
        await conn.execute(
            "update sources set content_hash = $3 "
            "where store_id = $1 and source_id = $2 and content_hash is null",
            store_id, source_id, content_hash,
        )
        return True
    except asyncpg.UniqueViolationError:
        return False


async def count_cards(conn: asyncpg.Connection, store_id: int, source_id: int) -> int:
    return await conn.fetchval(
        "select count(*) from knowledge_cards where store_id = $1 and source_id = $2",
        store_id, source_id,
    ) or 0


# ── sources 하위 테이블 ────────────────────────────────────────────────────

async def create_voice(
    conn: asyncpg.Connection, source_id: int, *,
    audio_format: str, duration_sec: int, record_method: str, sample_rate: int | None,
) -> None:
    await conn.execute(
        "insert into source_voice (source_id, audio_format, duration_sec, record_method, sample_rate) "
        "values ($1, $2, $3, $4, $5)",
        source_id, audio_format, duration_sec, record_method, sample_rate,
    )


async def update_voice_result(
    conn: asyncpg.Connection, source_id: int, *,
    duration_sec: int, transcript: str, stt_model: str,
) -> None:
    await conn.execute(
        "update source_voice set duration_sec = $2, transcript = $3, stt_model = $4 "
        "where source_id = $1",
        source_id, duration_sec, transcript, stt_model,
    )


async def get_voice(conn: asyncpg.Connection, source_id: int) -> asyncpg.Record | None:
    return await conn.fetchrow(
        "select voice_id, audio_format, duration_sec, transcript from source_voice "
        "where source_id = $1", source_id,
    )


async def create_video(
    conn: asyncpg.Connection, source_id: int, *,
    video_format: str, duration_sec: int, resolution: str | None, fps: int | None,
) -> None:
    await conn.execute(
        "insert into source_video (source_id, video_format, duration_sec, resolution, fps) "
        "values ($1, $2, $3, $4, $5)",
        source_id, video_format, duration_sec, resolution, fps,
    )


async def create_kakao(
    conn: asyncpg.Connection, source_id: int, *,
    import_type: str, room_name: str | None,
) -> None:
    await conn.execute(
        "insert into source_kakao (source_id, import_type, room_name) values ($1, $2, $3)",
        source_id, import_type, room_name,
    )


async def create_scan(
    conn: asyncpg.Connection, source_id: int, *,
    doc_type: str, doc_category: str | None, page_count: int,
) -> None:
    await conn.execute(
        "insert into source_scan (source_id, doc_type, doc_category, page_count) "
        "values ($1, $2, $3, $4)",
        source_id, doc_type, doc_category, page_count,
    )


# ── 추출 컨텍스트 ──────────────────────────────────────────────────────────

async def enabled_categories(conn: asyncpg.Connection, store_id: int) -> dict[str, int]:
    """점주가 켜둔 카테고리만. 추출 프롬프트에 이 목록만 선투입한다 (자유 생성 금지)."""
    rows = await conn.fetch(
        "select category_id, category_name from task_categories "
        "where store_id = $1 and is_enabled = true order by sort_order",
        store_id,
    )
    return {r["category_name"]: r["category_id"] for r in rows}


async def glossary(conn: asyncpg.Connection, store_id: int) -> list[dict[str, str]]:
    rows = await conn.fetch(
        "select term, variants, description from store_glossary where store_id = $1",
        store_id,
    )
    return [dict(r) for r in rows]


# ── 지식카드 쓰기 ──────────────────────────────────────────────────────────

async def insert_card(
    conn: asyncpg.Connection,
    store_id: int,
    *,
    category_id: int | None,
    source_id: int,
    title: str,
    content: str,
    confidence: float,
) -> int:
    """추출 카드는 항상 is_verified=false. 점주 승인 전에는 검색에 노출되지 않는다."""
    return await conn.fetchval(
        "insert into knowledge_cards "
        "  (store_id, category_id, source_id, title, content, confidence, is_verified) "
        "values ($1, $2, $3, $4, $5, $6, false) returning card_id",
        store_id, category_id, source_id,
        title[:MAX_TITLE_LEN], content, confidence,
    )


async def insert_facts(
    conn: asyncpg.Connection, card_id: int, facts: list[tuple[str, str, str, float]]
) -> None:
    if not facts:
        return
    await conn.executemany(
        "insert into facts (card_id, object_name, attribute, value, confidence, is_verified) "
        "values ($1, $2, $3, $4, $5, false)",
        [(card_id, o[:100], a[:100], v[:500], c) for o, a, v, c in facts],
    )


async def get_card(
    conn: asyncpg.Connection, store_id: int, card_id: int
) -> asyncpg.Record | None:
    return await conn.fetchrow(
        "select card_id, title, content, is_verified from knowledge_cards "
        "where store_id = $1 and card_id = $2",
        store_id, card_id,
    )


# ── 임베딩 ─────────────────────────────────────────────────────────────────

async def upsert_embedding(
    conn: asyncpg.Connection,
    store_id: int,
    *,
    card_id: int,
    chunk_index: int,
    chunk_text: str,
    embedding: list[float],
    content_hash: str,
    model_name: str,
    dimension: int,
) -> None:
    """asyncpg 는 vector 타입을 모른다. 문자열로 넘기고 SQL 에서 캐스팅한다.

    변환은 관호님 vector_literal 을 쓴다. 자릿수가 갈라지면 같은 카드가
    재적재될 때마다 content_hash 는 같은데 벡터만 미세하게 달라진다.
    """
    from app.reg.embeddings import vector_literal
    literal = vector_literal(embedding)
    await conn.execute(
        "insert into card_embeddings "
        "  (card_id, store_id, chunk_index, chunk_text, embedding, dimension, "
        "   model_name, content_hash, lexical_tsv, is_stale, indexed_at) "
        "values ($1, $2, $3, $4, $5::vector, $6, $7, $8, to_tsvector('simple', $4), false, now()) "
        "on conflict (card_id, chunk_index) do update set "
        "  chunk_text = excluded.chunk_text, "
        "  embedding = excluded.embedding, "
        "  dimension = excluded.dimension, "
        "  model_name = excluded.model_name, "
        "  content_hash = excluded.content_hash, "
        "  lexical_tsv = excluded.lexical_tsv, "
        "  is_stale = false, "
        "  updated_at = now()",
        card_id, store_id, chunk_index, chunk_text, literal, dimension,
        model_name, content_hash,
    )
