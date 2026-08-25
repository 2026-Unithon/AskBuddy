"""준혁 (feat/input) — 자료 처리 파이프라인.

상태 머신 (개발가이드 6-1):
    UPLOADED → PROCESSING → DONE
                         ↘ FAILED (error_message 필수)

이 함수는 백그라운드에서 돈다. 요청 커넥션이 이미 닫힌 뒤이므로 풀에서 직접 얻는다.
실패하면 다음 단계로 넘어가지 않고 FAILED 로 명확히 멈춘다.
"""
import logging
import shutil
import time

import asyncpg

from app.deps import get_pool
from app.ingest import repository as repo
from app.ingest.extract import extract_cards
from app.ingest.preprocess import audio, storage
from app.ingest.schemas import ExtractionResult

logger = logging.getLogger(__name__)

MOCK_PLACEHOLDER = "(목 모드 — 전처리를 건너뛰었다)"


async def process_source(store_id: int, source_id: int) -> None:
    pool = get_pool()
    started = time.perf_counter()

    async with pool.acquire() as conn:
        try:
            src = await repo.get_source(conn, store_id, source_id)
            if src is None:
                logger.warning("source %s not in store %s — 처리 중단", source_id, store_id)
                return

            await repo.set_status(conn, store_id, source_id, "PROCESSING")

            text = await _preprocess(conn, store_id, src)
            categories = await repo.enabled_categories(conn, store_id)
            glossary = await repo.glossary(conn, store_id)

            result = await extract_cards(
                source_id=source_id,
                source_type=src["source_type"],
                text=text,
                category_names=list(categories),
                glossary=glossary,
            )

            async with conn.transaction():
                saved = await _persist(conn, store_id, source_id, categories, result)

            await repo.set_status(conn, store_id, source_id, "DONE")
            logger.info("ingest DONE source=%s cards=%d unresolved=%d %.1fs",
                        source_id, saved, len(result.unresolved),
                        time.perf_counter() - started)

        except Exception as e:
            logger.exception("ingest FAILED source=%s", source_id)
            await _mark_failed(conn, store_id, source_id, e)

        finally:
            shutil.rmtree(storage.workdir(source_id), ignore_errors=True)


async def _mark_failed(
    conn: asyncpg.Connection, store_id: int, source_id: int, exc: Exception
) -> None:
    message = f"{type(exc).__name__}: {exc}"
    try:
        await repo.set_status(conn, store_id, source_id, "FAILED", error_message=message)
    except Exception:
        # 커넥션까지 죽은 경우. 새 커넥션으로 한 번만 더 시도한다.
        # 여기서도 실패하면 프론트 폴링이 PROCESSING 에서 멈추므로 반드시 로그를 남긴다
        logger.exception("FAILED 상태 기록 실패 source=%s (폴링이 멈춘다)", source_id)
        try:
            async with get_pool().acquire() as fresh:
                await repo.set_status(fresh, store_id, source_id, "FAILED",
                                      error_message=message)
        except Exception:
            logger.exception("FAILED 상태 재기록도 실패 source=%s", source_id)


async def _preprocess(
    conn: asyncpg.Connection, store_id: int, src: asyncpg.Record
) -> str:
    """자료 유형별 전처리. 반환값은 추출기에 넣을 텍스트."""
    source_type = src["source_type"]
    source_id = src["source_id"]

    if source_type == "VOICE":
        return await _preprocess_voice(conn, store_id, src)

    # VIDEO · KAKAO · SCAN 은 M4 범위다. 목 모드에서는 경계 확인용으로 통과시킨다.
    from app.config import get_settings
    if get_settings().ingest_mode == "mock":
        logger.info("preprocess skipped (mock) source=%s type=%s", source_id, source_type)
        return MOCK_PLACEHOLDER
    raise NotImplementedError(f"{source_type} 전처리는 아직 구현되지 않았다 (M4 범위)")


async def _preprocess_voice(
    conn: asyncpg.Connection, store_id: int, src: asyncpg.Record
) -> str:
    from app.config import get_settings
    source_id = src["source_id"]

    # 전사문이 이미 있으면 STT 를 건너뛴다 (가이드 8장 --skip-stt).
    # 추출 프롬프트는 수십 번 돌려야 하는데 STT 는 느리고 비싸다.
    # 다시 전사하려면 source_voice.transcript 를 비우고 재실행한다.
    row = await repo.get_voice(conn, source_id)
    if row and row["transcript"]:
        logger.info("STT 건너뜀 — 기존 전사문 재사용 source=%s chars=%d",
                    source_id, len(row["transcript"]))
        return row["transcript"]

    if get_settings().ingest_mode == "mock":
        return MOCK_PLACEHOLDER

    if not src["file_url"]:
        raise RuntimeError("file_url 이 비어 있다. Storage 업로드가 끝난 뒤 호출하라")

    path = await storage.download(source_id, src["file_url"])

    # 프론트가 content_hash 를 안 보냈으면 여기서 채운다.
    # 다음번 같은 파일 업로드는 /ingest/sources 에서 걸린다
    if src["content_hash"] is None:
        if not await repo.set_content_hash(conn, store_id, source_id,
                                           storage.sha256_of(path)):
            logger.warning("동일 해시의 자료가 이미 있다 source=%s", source_id)

    meta = await audio.probe(path)
    text, model = await audio.transcribe(path)

    await repo.update_voice_result(
        conn, source_id,
        duration_sec=meta["duration_sec"] or 0,
        transcript=text,
        stt_model=model,
    )
    return text


async def _persist(
    conn: asyncpg.Connection,
    store_id: int,
    source_id: int,
    categories: dict[str, int],
    result: ExtractionResult,
) -> int:
    """추출 카드를 is_verified=false 로 적재한다. 임베딩은 점주 승인 후에 한다."""
    saved = 0
    for card in result.cards:
        category_id = categories.get(card.category_name)
        if category_id is None:
            # 프롬프트에서 자유 생성을 금지했지만 모델이 어길 수 있다.
            # 카드를 버리지는 않되 미분류로 남기고 로그를 남긴다
            logger.warning("허용 목록에 없는 카테고리 '%s' — 미분류로 저장 source=%s",
                           card.category_name, source_id)

        card_id = await repo.insert_card(
            conn, store_id,
            category_id=category_id,
            source_id=source_id,
            title=card.title,
            content=card.content,
            confidence=_to_percent(card.confidence),
        )
        await repo.insert_facts(conn, card_id, [
            (f.object_name, f.attribute, f.value, _to_percent(f.confidence))
            for f in card.facts
        ])
        saved += 1

    for item in result.unresolved:
        logger.info("unresolved source=%s: %s", source_id, item)

    return saved


def _to_percent(confidence: float) -> float:
    """0~1 로 받아 DB 에는 0~100 으로 저장한다 (numeric(5,2) CHECK)."""
    return round(max(0.0, min(1.0, float(confidence))) * 100, 2)
