"""배선 점검 — 기능을 짜기 전에, 배포한 뒤에 여기 줄들이 전부 초록이어야 한다.

'로컬은 되는데 배포하면 안 됨' 을 30초 안에 진단하는 것이 목적이다.
그래서 "키가 있다/없다" 가 아니라 실제로 찔러보고 결과를 돌려준다.

    GET /preflight        DB·Storage·시드·검색까지 실제 호출 (무료)
    GET /preflight?deep=1 위 + OpenAI·Gemini 실호출 (돈이 든다. 각 1회)
"""
import asyncio
import logging
import os
import time
from typing import Any, Literal

import asyncpg
import httpx
from fastapi import APIRouter, Query

from app.config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter(tags=["preflight"])

State = Literal["live", "dead", "warn"]
PROBE_TIMEOUT = 8.0


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

async def _probe_db(s) -> list[dict]:
    async def run():
        conn = await asyncpg.connect(s.supabase_db_url, timeout=PROBE_TIMEOUT)
        try:
            return {
                "tables": await conn.fetchval(
                    "select count(*) from information_schema.tables "
                    "where table_schema = 'public'"),
                "stores": await conn.fetchval("select count(*) from stores"),
                "cards": await conn.fetchval("select count(*) from knowledge_cards"),
                "verified": await conn.fetchval(
                    "select count(*) from knowledge_cards where is_verified"),
                "embeddings": await conn.fetchval("select count(*) from card_embeddings"),
                "vector_ext": await conn.fetchval(
                    "select count(*) from pg_extension where extname = 'vector'"),
                "match_cards": await conn.fetchval(
                    "select count(*) from pg_proc where proname = 'match_cards'"),
            }
        finally:
            await conn.close()

    data, err, ms = await _timed(run())
    host = s.supabase_db_url.split("@")[-1].split("/")[0] if "@" in s.supabase_db_url else "?"

    if err:
        return [_check("데이터베이스", "dead", host,
                       "SUPABASE_DB_URL 확인. 호스팅은 Connection pooling 문자열을 쓴다"
                       f" — {err}", ms)]

    out = [_check("데이터베이스", "live", f"{host} · 테이블 {data['tables']}개", ms=ms)]

    out.append(
        _check("스키마", "live", f"테이블 {data['tables']}개")
        if data["tables"] >= 24
        else _check("스키마", "dead", f"테이블 {data['tables']}개 (24개여야 함)",
                    "db/001_init_schema.sql 을 SQL Editor 에서 실행")
    )
    out.append(
        _check("pgvector", "live", "확장 + match_cards() 준비됨")
        if data["vector_ext"] and data["match_cards"]
        else _check("pgvector", "dead",
                    f"extension={bool(data['vector_ext'])} match_cards={bool(data['match_cards'])}",
                    "001_init_schema.sql 이 끝까지 실행됐는지 확인")
    )
    out.append(
        _check("시드 데이터", "live", f"매장 {data['stores']} · 카드 {data['cards']}")
        if data["stores"] and data["cards"]
        else _check("시드 데이터", "dead", f"매장 {data['stores']} · 카드 {data['cards']}",
                    "db/002_seed_demo.sql 실행")
    )
    out.append(
        _check("시드 임베딩", "live", f"{data['embeddings']}건")
        if data["embeddings"]
        else _check("시드 임베딩", "dead", "0건 — 검색이 전부 miss 가 된다",
                    "api 에서 python scripts/seed_embeddings.py 한 번 실행")
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
    """검색 게이트가 실제로 hit 을 내는지. 데모의 6번 시나리오다.

    자기 자신을 HTTP 로 부른다 — 라우터·임베딩·pgvector 를 한 번에 통과시켜야
    의미가 있기 때문이다. Railway 는 포트를 PORT 로 준다.
    """
    port = os.environ.get("PORT", "8000")

    async def run():
        async with httpx.AsyncClient(timeout=PROBE_TIMEOUT) as c:
            r = await c.post(f"http://127.0.0.1:{port}/reg/retrieve",
                             json={"store_id": "demo-cafe",
                                   "question": "우유 어디 보관해요?", "top_k": 3})
            try:
                return r.status_code, r.json()
            except ValueError:
                # 500 이면 본문이 JSON 이 아니다. 그 텍스트가 원인을 말해준다
                return r.status_code, {"_raw": r.text[:120]}

    data, err, ms = await _timed(run())
    if err:
        return _check("검색 게이트", "dead", str(err)[:80],
                      f"api 가 127.0.0.1:{port} 에서 응답하는지 확인", ms)

    code, body = data
    if code != 200:
        return _check("검색 게이트", "dead", f"HTTP {code} {body.get('_raw', body)}",
                      "대개 임베딩 호출 실패다. 위 OpenAI 줄을 먼저 본다", ms)

    kind = body.get("kind")
    if kind == "hit":
        top = (body.get("candidates") or [{}])[0].get("score", 0)
        return _check("검색 게이트", "live", f"hit · 최고점 {float(top):.3f}", ms=ms)
    return _check("검색 게이트", "dead",
                  f"miss ({body.get('reason')}) — 임계 {s.retrieval_threshold}",
                  "시드 임베딩이 없거나 RETRIEVAL_THRESHOLD 가 너무 높다", ms)


# ── 엔드포인트 ─────────────────────────────────────────────────────────────

@router.get("/preflight")
async def preflight(deep: bool = Query(False, description="LLM 실호출 포함. 돈이 든다")):
    s = get_settings()

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
