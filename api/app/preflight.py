"""배선 점검 — 기능을 짜기 전에, 배포한 뒤에 여기 줄들이 전부 초록이어야 한다.

'로컬은 되는데 배포하면 안 됨' 을 30초 안에 진단하는 것이 목적이다.
그래서 "키가 있다/없다" 가 아니라 실제로 찔러보고 결과를 돌려준다.

    GET /preflight        DB·Storage·시드·검색까지 실제 호출 (임베딩 1회)
    GET /preflight?deep=1 위 + OpenAI·Gemini 실호출 (돈이 든다. 각 1회)

운영자 전용이다 (이슈 #33). /ops/login 이 발급한 토큰만 받는다. /health 는 공개다.
"""
import asyncio
import logging
import time
from typing import Any, Literal
from uuid import uuid4

import asyncpg
import httpx
from fastapi import APIRouter, Query

from app.config import get_settings
from app.contracts.usage import UsageContext
from app.deps import get_pool
from app.ops.deps import OperatorId
from app.reg.retrieve import retrieve_question
from app.usage import DbUsageSink

logger = logging.getLogger(__name__)
router = APIRouter(tags=["preflight"])

State = Literal["live", "dead", "warn"]
PROBE_TIMEOUT = 8.0

# 진단이 읽거나, 없으면 제품이 바로 깨지는 테이블. 없으면 migration 이 덜 적용된 것이다
REQUIRED_TABLES = (
    "users", "stores", "store_members", "invite_codes", "knowledge_cards", "card_embeddings",
    "ingest_jobs", "pending_questions", "owner_answers", "notification_events",
    "ai_usage_attempts", "knowledge_publications", "r_index_publications", "r_index_documents",
    "source_facts", "source_fact_occurrences", "fact_revisions", "knowledge_entities",
    "extraction_raw_responses", "upload_change_proposals",
)
DEMO_STORE_SLUG = "demo-cafe"
DEMO_QUESTION = "우유 어디 보관해요?"


def _check(
    name: str, state: State, detail: str = "", fix: str = "", ms: int | None = None
) -> dict[str, Any]:
    return {"name": name, "state": state, "detail": detail, "fix": fix, "ms": ms}


async def _timed(coro):
    t0 = time.perf_counter()
    try:
        result = await asyncio.wait_for(coro, timeout=PROBE_TIMEOUT)
    except asyncio.TimeoutError:
        return None, TimeoutError(f"{PROBE_TIMEOUT:.0f}초 안에 응답 없음"), 0
    except Exception as e:  # noqa: BLE001 — 어떤 실패든 화면에 보여준다
        return None, e, int((time.perf_counter() - t0) * 1000)
    return result, None, int((time.perf_counter() - t0) * 1000)


# ── 개별 점검 ──────────────────────────────────────────────────────────────

async def _missing_tables(conn) -> list[str]:
    rows = await conn.fetch(
        "select t.name from unnest($1::text[]) with ordinality as t(name, i) "
        "where to_regclass('public.' || t.name) is null order by t.i",
        list(REQUIRED_TABLES))
    return [r["name"] for r in rows]


async def _counts(conn) -> dict[str, Any]:
    return {
        "stores": await conn.fetchval("select count(*) from stores"),
        # store-isolation-ok: 운영 점검 화면의 전체 매장 집계
        "cards": await conn.fetchval("select count(*) from knowledge_cards"),
        # store-isolation-ok: 운영 점검 화면의 전체 매장 집계
        "approved_stores": await conn.fetchval(
            "select count(distinct store_id) from knowledge_cards "
            "where review_status = 'APPROVED' and is_verified "
            "and published_version_id is not null"),
        # store-isolation-ok: 운영 점검 화면의 전체 매장 집계
        "indexed_stores": await conn.fetchval(
            "select count(*) from knowledge_publications p "
            "join r_index_publications a on a.store_id = p.store_id "
            "and a.snapshot_id = p.current_snapshot_id"),
        "vector_ext": await conn.fetchval(
            "select count(*) from pg_extension where extname = 'vector'"),
        "match_cards": await conn.fetchval(
            "select count(*) from pg_proc where proname = 'match_cards'"),
    }


async def _probe_db(s) -> list[dict]:
    """연결과 스키마를 따로 본다. 테이블이 없는 것을 연결 문제로 안내하지 않는다."""
    host = s.supabase_db_url.split("@")[-1].split("/")[0] if "@" in s.supabase_db_url else "?"
    conn, err, ms = await _timed(asyncpg.connect(s.supabase_db_url, timeout=PROBE_TIMEOUT))
    if err:
        return [_check("데이터베이스", "dead", host,
                       "SUPABASE_DB_URL 확인. 호스팅은 Connection pooling 문자열을 쓴다"
                       f" — {err}", ms)]
    try:
        out = [_check("데이터베이스", "live", host, ms=ms)]

        missing, err, ms = await _timed(_missing_tables(conn))
        if err:
            out.append(_check("스키마", "dead", str(err)[:90], "DB 계정 권한을 확인한다", ms))
            return out
        if missing:
            out.append(_check("스키마", "dead", "없는 테이블: " + ", ".join(missing),
                              "밀린 migration 을 적용한다 (supabase db push)", ms))
            # 아래 집계는 이 테이블들을 읽으므로 돌리지 않는다
            return out
        out.append(_check("스키마", "live", f"필수 테이블 {len(REQUIRED_TABLES)}개 있음", ms=ms))

        data, err, ms = await _timed(_counts(conn))
        if err:
            out.append(_check("집계", "dead", str(err)[:90], "", ms))
            return out
    finally:
        await conn.close()

    out.append(
        _check("pgvector", "live", "확장 + match_cards() 준비됨")
        if data["vector_ext"] and data["match_cards"]
        else _check("pgvector", "dead",
                    f"extension={bool(data['vector_ext'])} match_cards={bool(data['match_cards'])}",
                    "밀린 migration 을 적용한다 (supabase db push)")
    )
    out.append(
        _check("시드 데이터", "live", f"매장 {data['stores']} · 카드 {data['cards']}")
        if data["stores"] and data["cards"]
        else _check("시드 데이터", "dead", f"매장 {data['stores']} · 카드 {data['cards']}",
                    "db/002_seed_demo.sql 실행")
    )
    index_label = f"승인 카드 매장 {data['approved_stores']} · 색인 매장 {data['indexed_stores']}"
    out.append(
        _check("공개 색인", "live", index_label)
        if data["indexed_stores"] >= data["approved_stores"]
        else _check("공개 색인", "dead", f"{index_label} — 색인 없는 매장은 검색이 안 된다",
                    "api 에서 python scripts/bootstrap_store_index.py --apply 실행")
    )
    return out


async def _probe_storage(s) -> dict:
    if not s.supabase_service_key:
        return _check("Storage", "dead", "SUPABASE_SERVICE_KEY 없음",
                      "Supabase → Settings → API → service_role 키를 넣는다")

    async def run():
        async with httpx.AsyncClient(timeout=PROBE_TIMEOUT) as c:
            r = await c.get(f"{s.supabase_url}/storage/v1/bucket",
                            headers={"Authorization": f"Bearer {s.supabase_service_key}"})
            return r.status_code, r.json() if r.status_code == 200 else r.text[:120]

    data, err, ms = await _timed(run())
    if err:
        return _check("Storage", "dead", str(err)[:80], "SUPABASE_URL 이 맞는지 확인", ms)

    code, body = data
    if code != 200:
        return _check("Storage", "dead", f"HTTP {code} {body}",
                      "service_role 키인지 확인 (anon·publishable 키로는 안 된다)", ms)

    names = [b["name"] for b in body]
    if s.storage_bucket in names:
        return _check("Storage", "live", f"버킷 '{s.storage_bucket}' 있음", ms=ms)
    return _check("Storage", "dead", f"버킷 목록: {names or '없음'}",
                  f"'{s.storage_bucket}' 버킷을 비공개로 만든다 "
                  "(또는 python scripts/init_storage.py)", ms)


async def _probe_openai(s, deep: bool) -> dict:
    if not s.openai_api_key:
        return _check("OpenAI", "dead", "키 없음",
                      "OPENAI_API_KEY 추가. 임베딩·STT 가 여기에 달려 있다")
    if not deep:
        return _check("OpenAI", "warn", f"키 있음 ({s.embedding_model})",
                      "실제 호출은 ?deep=1 로 확인한다")

    async def run():
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=s.openai_api_key, timeout=PROBE_TIMEOUT)
        res = await client.embeddings.create(model=s.embedding_model, input=["ping"])
        return len(res.data[0].embedding)

    dim, err, ms = await _timed(run())
    if err:
        msg = str(err)
        fix = ("크레딧이 없다. platform.openai.com 에서 충전"
               if "quota" in msg or "credit" in msg else "OPENAI_API_KEY 확인")
        return _check("OpenAI", "dead", msg[:90], fix, ms)
    if dim != s.embedding_dim:
        return _check("OpenAI", "dead", f"차원 {dim} != {s.embedding_dim}",
                      "모델을 바꿨다면 임계값·골든셋을 전면 재측정해야 한다 (D4)", ms)
    return _check("OpenAI", "live", f"{s.embedding_model} · {dim}차원", ms=ms)


async def _probe_gemini(s, deep: bool) -> dict:
    if not s.gemini_api_key:
        return _check("Gemini", "dead", "키 없음",
                      "GEMINI_API_KEY 추가. 없으면 INGEST_MODE=real 이 전부 실패한다")
    if not deep:
        return _check("Gemini", "warn", f"키 있음 ({s.gemini_model})",
                      "실제 호출은 ?deep=1 로 확인한다")

    async def run():
        from google import genai
        client = genai.Client(api_key=s.gemini_api_key)
        res = await client.aio.models.generate_content(
            model=s.gemini_model, contents="OK 라고만 답해")
        return (res.text or "").strip()[:20]

    text, err, ms = await _timed(run())
    if err:
        msg = str(err)
        fix = ("모델 이름이 이 키로 안 열린다. 응답이 알려주는 대체 모델로 바꾼다"
               if "404" in msg or "NOT_FOUND" in msg else "GEMINI_API_KEY 확인")
        return _check("Gemini", "dead", msg[:90], fix, ms)
    return _check("Gemini", "live", f"{s.gemini_model} → {text!r}", ms=ms)


async def _probe_retrieve(s) -> dict:
    """검색 게이트가 실제로 hit 을 내는지. 데모 매장으로 확인한다.

    HTTP 로 자기 자신을 부르지 않는다 — /reg/retrieve 는 매장 JWT 가 필요하다.
    retrieve_question 을 직접 불러 임베딩·pgvector·게이트를 한 번에 통과시킨다.
    임베딩 비용은 개발 목적으로 기록해 고객 월 운영비(D21)에 섞지 않는다.
    """
    try:
        pool = get_pool()
    except RuntimeError as e:
        return _check("검색 게이트", "dead", str(e), "위 데이터베이스 줄을 먼저 본다")

    async def run():
        # store-isolation-ok: 데모 매장 slug 로 점검 대상 store_id 를 찾는다
        store_id = await pool.fetchval(
            "select store_id from stores where store_slug = $1", DEMO_STORE_SLUG)
        if store_id is None:
            return None
        store_id = int(store_id)
        return await retrieve_question(
            pool, store_id, DEMO_QUESTION, 3,
            usage_context=UsageContext(
                store_id=str(store_id), cost_phase="OPERATING", cost_purpose="DEVELOPMENT",
                stage="QUERY", logical_call_id=f"preflight:{uuid4().hex}"),
            usage_sink=DbUsageSink(pool))

    result, err, ms = await _timed(run())
    if err:
        return _check("검색 게이트", "dead", str(err)[:90],
                      "대개 임베딩 호출 실패다. 위 OpenAI 줄을 먼저 본다", ms)
    if result is None:
        return _check("검색 게이트", "warn", f"데모 매장({DEMO_STORE_SLUG}) 없음 — 점검 생략",
                      "운영 DB 에는 시드가 없을 수 있다", ms)
    if result["kind"] == "hit":
        top = (result.get("candidates") or [{}])[0].get("score", 0)
        return _check("검색 게이트", "live", f"hit · 최고점 {float(top):.3f}", ms=ms)
    return _check("검색 게이트", "dead",
                  f"miss ({result.get('reason')}) — 임계 {s.retrieval_threshold}",
                  "시드 임베딩이 없거나 RETRIEVAL_THRESHOLD 가 너무 높다", ms)


# ── 엔드포인트 ─────────────────────────────────────────────────────────────

@router.get("/preflight")
async def preflight(operator_id: OperatorId,
                    deep: bool = Query(False, description="LLM 실호출 포함. 돈이 든다")):
    s = get_settings()
    logger.info("preflight operator=%s deep=%s", operator_id, deep)

    db_checks, storage, openai_c, gemini_c, retrieve = await asyncio.gather(
        _probe_db(s), _probe_storage(s), _probe_openai(s, deep), _probe_gemini(s, deep),
        _probe_retrieve(s),
    )

    checks: list[dict] = [
        _check("백엔드", "live", f"env={s.env} · INGEST_MODE={s.ingest_mode}"),
        _check("CORS", "live" if s.origins else "dead", ", ".join(s.origins) or "없음",
               "ALLOWED_ORIGINS 에 프론트 도메인을 넣는다"),
        *db_checks,
        storage,
        openai_c,
        gemini_c,
        retrieve,
    ]

    dead = [c["name"] for c in checks if c["state"] == "dead"]
    return {
        "ok": not dead,
        "deep": deep,
        "env": s.env,
        "blocking": dead,
        "settings": {
            "ingest_mode": s.ingest_mode,
            "embedding_model": s.embedding_model,
            "gemini_model": s.gemini_model,
            "stt_model": s.stt_model,
            "retrieval_threshold": s.retrieval_threshold,
            "confidence_threshold": s.confidence_threshold,
            "storage_bucket": s.storage_bucket,
        },
        "checks": checks,
    }
