"""점주 답변 → 파일 없는 자료(OWNER_TEXT) → 사실 수집 (Phase A, A-D3).

업로드와 같은 길을 탄다: 추출 → 원장(_persist_ledger) → 대상 연결 → 사실 조립 → 사실 카드.
질문 문장은 답변을 이해하기 위한 맥락일 뿐 사실로 저장하지 않는다. 추출 프롬프트 파일은
바꾸지 않고(재사용 키 보존) 입력 글 머리말로 알린다. 질문에만 나온 원문은 서버가 버린다.

모든 DB 함수는 store_id 를 필수로 받고 모든 조회가 store_id 로 좁힌다(D1).
모델 호출 중에는 DB 연결을 쥐지 않는다.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from app.ingest import pipeline
from app.ingest import repository as repo
from app.ingest.schemas import ExtractedAssertion

logger = logging.getLogger(__name__)

QUESTION_HEADER = "[직원 질문 — 답변을 이해하기 위한 맥락이다. 여기서는 사실을 뽑지 않는다]"
ANSWER_HEADER = "[점주 답변 — 사실은 여기서만 뽑는다]"
SOURCE_TITLE = "점주 답변 · {question}"
_TITLE_QUESTION_MAX = 80


def compose_text(question: str, answer: str) -> str:
    return f"{QUESTION_HEADER}\n{question.strip()}\n\n{ANSWER_HEADER}\n{answer.strip()}"


def _norm(text: str | None) -> str:
    return re.sub(r"\s+", "", text or "")


def drop_question_only(assertions: list[ExtractedAssertion], *, question: str,
                       answer: str) -> list[ExtractedAssertion]:
    """원문이 답변에는 없고 질문에만 있는 사실을 버린다. 원문이 비면 판단하지 않고 남긴다."""
    q, a = _norm(question), _norm(answer)
    kept = []
    for x in assertions:
        original = _norm(x.original_assertion)
        if original and original not in a and original in q:
            logger.info("점주 답변 — 질문에만 있는 원문을 버린다 ref=%s", x.local_ref)
            continue
        kept.append(x)
    return kept


@dataclass(frozen=True)
class AnswerCard:
    card_id: int
    draft_version_id: int
    published_version_id: int | None
    review_status: str
    needs_review_reason: str | None


async def owner_answer_source(conn, store_id: int, *, owner_answer_id: int) -> int | None:
    value = await conn.fetchval(
        "select source_id from owner_answer_sources where store_id = $1 and owner_answer_id = $2",
        store_id, owner_answer_id)
    return int(value) if value is not None else None


async def _source_status(conn, store_id: int, source_id: int) -> str:
    return await conn.fetchval(
        "select status from sources where store_id = $1 and source_id = $2", store_id, source_id)


async def ensure_owner_answer_source(conn, store_id: int, *, owner_answer_id: int, actor_id: int,
                                     question: str, answer: str) -> tuple[int, str]:
    """답변 하나에 자료 하나를 보장한다(멱등). **반드시 트랜잭션 안에서 부른다.**

    답변별 트랜잭션 잠금으로 한 번에 하나만 만든다. 그래도 연결 삽입에서 졌다면
    (잠금 밖 경로) 내가 만든 자료 행을 지워 고아를 남기지 않는다.
    """
    if not conn.is_in_transaction():
        raise RuntimeError("ensure_owner_answer_source 는 트랜잭션 안에서 불러야 한다")
    await conn.execute(
        # 인자는 정수다. $n::text 로 쓰면 asyncpg 가 문자열을 요구해 실제 DB 에서 DataError 가 난다
        "select pg_advisory_xact_lock(hashtextextended("
        "'owner_answer_source:' || $1::bigint || ':' || $2::bigint, 0))",
        store_id, owner_answer_id)
    existing = await owner_answer_source(conn, store_id, owner_answer_id=owner_answer_id)
    if existing is not None:
        return existing, await _source_status(conn, store_id, existing)
    title = SOURCE_TITLE.format(question=question.strip()[:_TITLE_QUESTION_MAX])[:200]
    # content_hash 는 null 로 둔다(fact_edit 과 같다). sources 의 (store_id, content_hash) 유일
    # 제약 때문에 같은 매장에서 같은 글의 답변("네" 등)이 두 번 오면 삽입이 실패한다.
    # 답변 하나당 자료 하나라는 멱등은 owner_answer_sources PK 와 위 잠금이 보장한다.
    source_id = int(await conn.fetchval(
        "insert into sources (store_id, uploaded_by, source_type, title, file_url, content_hash, status) "
        "values ($1, $2, 'OWNER_TEXT', $3, null, null, 'PROCESSING') returning source_id",
        store_id, actor_id, title))
    await conn.execute(
        "insert into owner_answer_sources (store_id, owner_answer_id, source_id) "
        "values ($1, $2, $3) on conflict (store_id, owner_answer_id) do nothing",
        store_id, owner_answer_id, source_id)
    won = await owner_answer_source(conn, store_id, owner_answer_id=owner_answer_id)
    if won != source_id:
        # 진 쪽: 내 자료 행은 연결이 없으니 지운다
        await conn.execute(
            "delete from sources where store_id = $1 and source_id = $2", store_id, source_id)
    return int(won), await _source_status(conn, store_id, int(won))


async def answer_fact_count(conn, store_id: int, *, source_id: int) -> int:
    return int(await conn.fetchval(
        "select count(*) from source_fact_occurrences where store_id = $1 and source_id = $2",
        store_id, source_id))


async def answer_cards(conn, store_id: int, *, source_id: int) -> list[AnswerCard]:
    rows = await conn.fetch(
        "select distinct k.card_id, k.draft_version_id, k.published_version_id, "
        "       k.review_status, k.needs_review_reason "
        "from fact_occurrences o "
        "join knowledge_cards k on k.store_id = o.store_id and k.card_id = o.card_id "
        "where o.store_id = $1 and o.source_id = $2 and o.disposition = 'LINKED' "
        "  and k.review_status <> 'EXCLUDED' and k.draft_version_id is not null "
        "order by k.card_id", store_id, source_id)
    return [AnswerCard(card_id=int(r["card_id"]), draft_version_id=int(r["draft_version_id"]),
                       published_version_id=(int(r["published_version_id"])
                                             if r["published_version_id"] is not None else None),
                       review_status=r["review_status"],
                       needs_review_reason=r["needs_review_reason"]) for r in rows]


async def ingest_owner_text(pool, *, store_id: int, source_id: int, question: str, answer: str,
                            run_tag: int) -> int:
    """답변 글에서 사실을 뽑아 원장·카드까지 만든다. 이 자료의 원장 사실 수를 돌려준다.

    원장이 이미 있으면(재시도) 추출을 건너뛴다. 모델 호출 중에는 연결을 쥐지 않는다.
    """
    from app.ingest.raw_responses import DbRawResponseSink
    from app.usage import DbUsageSink

    async with pool.acquire() as conn:
        has_ledger = await conn.fetchval(
            "select exists (select 1 from source_facts where store_id = $1 and source_id = $2)",
            store_id, source_id)
        glossary = await repo.glossary(conn, store_id)

    usage_base = (store_id, None, "OPERATING", "PRODUCT", None, run_tag)
    usage_sink = DbUsageSink(pool, resilient=True)
    raw_sink = DbRawResponseSink(pool, run_tag=run_tag)

    if not has_ledger:
        from app.ingest.extract import extract_facts
        result = await extract_facts(
            source_id=source_id, source_type="OWNER_TEXT", text=compose_text(question, answer),
            glossary=glossary, media=[], usage_sink=usage_sink,
            usage_context=pipeline._ctx_for(usage_base, source_id, "EXTRACT"),
            raw_sink=raw_sink)
        assertions = drop_question_only(list(result.assertions), question=question, answer=answer)
        async with pool.acquire() as conn, conn.transaction():
            await pipeline._persist_ledger(conn, store_id, source_id, "OWNER_TEXT", assertions)

    async with pool.acquire() as conn:
        categories = await repo.enabled_categories(conn, store_id)
    prepared = await pipeline._prepare_fact_assembly(
        pool, store_id, source_id, categories=list(categories), glossary=glossary,
        usage_sink=usage_sink, usage_base=usage_base, raw_sink=raw_sink, strict=True)

    async with pool.acquire() as conn, conn.transaction():
        # 조립 중 설정이 바뀌었을 수 있다. 저장 직전 최신 카테고리를 쓴다
        categories = await repo.enabled_categories(conn, store_id)
        category_version = int(await conn.fetchval(
            "select category_version from stores where store_id = $1", store_id))
        await pipeline._persist_fact_cards(
            conn, store_id, source_id, categories, prepared,
            job_id=None, category_version=category_version)
        await repo.set_status(conn, store_id, source_id, "DONE")
        return await answer_fact_count(conn, store_id, source_id=source_id)
