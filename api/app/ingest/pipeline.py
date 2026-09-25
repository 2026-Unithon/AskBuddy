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
from pathlib import Path
from typing import NamedTuple

import asyncpg

from app.deps import get_pool
from app.ingest import repository as repo
from app.ingest.preprocess import audio, document, kakao, storage, video
from app.ingest.schemas import ExtractionResult

logger = logging.getLogger(__name__)

MOCK_PLACEHOLDER = "(목 모드 — 전처리를 건너뛰었다)"

# PARTIAL 재시도에서 구간 구성이 달라져 잃은 구간만 다시 읽을 수 없을 때 돌려준다.
# 호출부(job_worker)가 이 값을 보고 자료를 PARTIAL 로 남긴다
PARTIAL_RETRY_UNAVAILABLE = "PARTIAL_RETRY_UNAVAILABLE"


async def process_source(
    store_id: int, source_id: int, *, job_id: int | None = None,
    cost_phase: str = "REGISTRATION", cost_purpose: str = "PRODUCT",
    extraction_run_id: int | None = None,
    retry_segments: list[str] | None = None,
    expected_segments_total: int | None = None,
) -> str | None:
    """자료 하나를 처리한다.

    원가 계측(CP-00B) — 유료 호출마다 원장에 receipt 를 남긴다. 등록인지 운영인지는
    호출부가 정한다. 추출 결과만 보고 자동 분류하지 않는다 (승인 카드 0건이어도
    운영 중 추가 업로드일 수 있다).

    `retry_segments` 를 주면 PARTIAL 재시도다. 그 구간만 다시 뽑아 카드를 **추가**
    한다. 이미 만든 카드·원장은 건드리지 않는다. 구간 구성이 지난 실행과 달라
    같은 구간을 가리킬 수 없으면 추출하지 않고 `PARTIAL_RETRY_UNAVAILABLE` 을
    돌려준다. 보통 경로는 `None` 을 돌려준다.
    """
    from app.usage import DbUsageSink

    pool = get_pool()
    usage_sink = DbUsageSink(pool)
    started = time.perf_counter()

    # 연결은 DB 를 칠 때만 짧게 빌린다. 다운로드·STT·추출·조립처럼 느린 외부
    # 호출 동안 쥐고 있으면, 별도 연결을 잡는 원가 receipt 와 작은 풀에서 겹쳐
    # 작업 전체가 멈춘다.
    try:
        async with pool.acquire() as conn:
            src = await repo.get_source(conn, store_id, source_id)
            if src is None:
                logger.warning("source %s not in store %s — 처리 중단", source_id, store_id)
                return
            await repo.set_status(conn, store_id, source_id, "PROCESSING")

        text, media, segments = await _preprocess(
            pool, store_id, src,
            usage_sink=usage_sink,
            usage_context=_usage_context(
                store_id, source_id, job_id, "STT",
                cost_phase, cost_purpose, extraction_run_id),
        )

        if retry_segments is not None and not _same_layout(
                segments, retry_segments, expected_segments_total):
            # 구간 번호가 지난 실행과 같은 내용을 가리킨다고 믿을 수 없다. 다시 뽑으면
            # 이미 만든 카드와 겹치거나 엉뚱한 구간을 채운다. 잃은 구간은 그대로 두고,
            # 기존 카드가 남아 있으므로 자료는 FAILED 가 아닌 DONE 으로 돌린다
            logger.warning("구간 구성 변경 — 잃은 구간만 재추출 불가 source=%s "
                           "기대 %s구간, 현재 %d구간, 요청 %s",
                           source_id, expected_segments_total, len(segments),
                           retry_segments)
            async with pool.acquire() as conn:
                await repo.set_status(conn, store_id, source_id, "DONE")
            return PARTIAL_RETRY_UNAVAILABLE

        async with pool.acquire() as conn:
            categories = await repo.enabled_categories(conn, store_id)
            glossary = await repo.glossary(conn, store_id)

            if job_id is not None:
                await conn.execute(
                    """
                    update ingest_job_sources
                    set status = 'CLASSIFYING', updated_at = now()
                    where store_id = $1 and job_id = $2 and source_id = $3
                    """,
                    store_id,
                    job_id,
                    source_id,
                )
                await conn.execute(
                    """
                    update ingest_jobs set status = 'CLASSIFYING', updated_at = now()
                    where store_id = $1 and job_id = $2
                    """,
                    store_id,
                    job_id,
                )

        usage_base = (store_id, job_id, cost_phase, cost_purpose,
                      extraction_run_id)

        # ── 입력 → 사실 → (원장) → 카드 ──────────────────────────────
        # 예전에는 입력 → 카드 → (카드에서) 원장 이었다. 그래서 조립이 버린
        # 사실은 원장에도 안 남아, 못 뽑은 것과 뽑고 버린 것을 구분할 수
        # 없었다. 이제 뽑는 즉시 전부 원장에 적고 조립이 그중에서 고른다.
        # 구간을 뽑는 즉시 원장에 적는다 (checkpoint). 전부 끝난 뒤 한 번에
        # 적으면 뒤쪽 구간에서 죽을 때 앞서 뽑은 것까지 같이 사라진다.
        # 연결과 트랜잭션은 구간 하나만큼만 잡아 모델 호출 중 DB 를 점유하지 않는다.
        ledger_ids: dict[str, int] = {}

        async def _checkpoint(seg_assertions, segment_id):
            async with pool.acquire() as c, c.transaction():
                ledger_ids.update(await _persist_ledger(
                    c, store_id, source_id, src["source_type"],
                    seg_assertions))

        outcome = await _extract_facts_all(
            source_id=source_id,
            source_type=src["source_type"],
            text=text,
            media=media,
            glossary=glossary,
            segments=segments,
            usage_sink=usage_sink,
            usage_base=usage_base,
            checkpoint=_checkpoint,
            only_segments=set(retry_segments) if retry_segments is not None else None,
        )
        assertions, unresolved = outcome.assertions, outcome.unresolved
        # 원장 선저장은 위 checkpoint 에서 구간마다 이미 끝났다
        logger.info("원장 선저장 source=%s 사실 %d건", source_id, len(ledger_ids))

        # 분류 중 설정이 바뀌었으면 최신 카테고리로 조립한다 (기존 동작 유지)
        async with pool.acquire() as conn:
            categories = await repo.enabled_categories(conn, store_id)

        # 조립 — 원장에 적힌 사실 중에서 고른다. 새 사실을 만들지 않는다.
        # 모델 호출이므로 연결 밖에서 한다
        result = await assemble_assertions(
            source_id=source_id, assertions=assertions,
            categories=list(categories), glossary=glossary,
            usage_sink=usage_sink, usage_base=usage_base,
        )
        result.unresolved.extend(unresolved)

        async with pool.acquire() as conn:
            async with conn.transaction():
                # 연결을 놓은 사이 자료가 다른 경로로 끝났을 수 있다. 다시 보고 저장한다
                current = await repo.get_source(conn, store_id, source_id)
                if current is None or current["status"] != "PROCESSING":
                    state = "없음" if current is None else current["status"]
                    raise RuntimeError(
                        f"자료 상태가 처리 중 바뀌었다 (현재 {state}) — 저장하지 않는다")

                # 조립 중 설정이 바뀌었을 수 있다. 저장 직전 최신 카테고리를 사용한다.
                categories = await repo.enabled_categories(conn, store_id)
                category_version = int(
                    await conn.fetchval(
                        "select category_version from stores where store_id = $1", store_id
                    )
                )
                origin_job_id = job_id
                if origin_job_id is None:
                    origin_job_id = await conn.fetchval(
                        """
                        select job_id from ingest_jobs
                        where store_id = $1 and idempotency_key = $2
                        """,
                        store_id,
                        f"legacy-source-{source_id}",
                    )

                saved = await _persist(
                    conn,
                    store_id,
                    source_id,
                    categories,
                    result,
                    job_id=int(origin_job_id) if origin_job_id is not None else None,
                    category_version=category_version,
                    ledger_ids=ledger_ids,
                )

            # 잃은 구간을 먼저 적는다. 그래야 뒤에서 상태를 PARTIAL 로 가른다
            await _record_segment_failures(
                conn, store_id, job_id, source_id, outcome=outcome)

            await repo.set_status(conn, store_id, source_id, "DONE")
        logger.info("ingest DONE source=%s cards=%d unresolved=%d "
                    "구간 %d/%d 실패 %.1fs",
                    source_id, saved, len(result.unresolved),
                    outcome.segments_failed, outcome.segments_total,
                    time.perf_counter() - started)
        return None

    except Exception as e:
        logger.exception("ingest FAILED source=%s", source_id)
        await _mark_failed(pool, store_id, source_id, e)

    finally:
        shutil.rmtree(storage.workdir(source_id), ignore_errors=True)


def _usage_context(store_id: int, source_id: int, job_id: int | None,
                   stage: str, cost_phase: str, cost_purpose: str,
                   extraction_run_id: int | None, segment_id: str | None = None,
                   attempt_no: int = 1):
    """호출 하나를 어느 매장·단계에 귀속시킬지. 논리 호출 ID 로 재시도를 묶는다.

    **재추출은 재시도가 아니다.** 논리 호출 ID 에 실행 범위를 넣지 않으면 같은
    자료를 다시 뽑을 때 원장 unique 에 걸려 추출 자체가 죽는다 — 계측이 제품을
    멈추게 한다. 같은 실행 안의 재시도만 `attempt_no` 로 묶는다.
    """
    from app.contracts.usage import UsageContext

    # 실행 범위: 평가는 run, 제품은 job. 둘 다 없으면 자료 단위로만 묶인다
    scope = (f"run{extraction_run_id}:" if extraction_run_id
             else f"job{job_id}:" if job_id else "")
    call = f"{scope}src{source_id}:{stage.lower()}"
    if segment_id:
        call = f"{call}:{segment_id}"
    return UsageContext(
        store_id=str(store_id), cost_phase=cost_phase, cost_purpose=cost_purpose,
        stage=stage, logical_call_id=call, attempt_no=attempt_no,
        job_id=str(job_id) if job_id else None,
        source_id=str(source_id), segment_id=segment_id,
        extraction_run_id=str(extraction_run_id) if extraction_run_id else None,
    )


def _same_layout(segments: list, retry_segments: list[str],
                 expected_total: int | None) -> bool:
    """재계산한 구간이 지난 실행의 구간 번호와 같은 구성인지 본다.

    구간 없는 자료는 잃은 구간이라는 개념이 없으므로 같은 구성으로 보지 않는다.
    """
    if not segments or not retry_segments:
        return False
    if expected_total is not None and len(segments) != expected_total:
        return False
    valid = {f"seg{i}" for i in range(1, len(segments) + 1)}
    return set(retry_segments) <= valid


def _ctx_for(base: tuple | None, source_id: int, stage: str,
             segment_id: str | None = None):
    """usage_base 가 없으면 계측하지 않는다 (기존 호출 경로 호환)."""
    if base is None:
        return None
    store_id, job_id, phase, purpose, run_id = base
    return _usage_context(store_id, source_id, job_id, stage, phase, purpose,
                          run_id, segment_id=segment_id)




async def _mark_failed(
    pool: asyncpg.Pool, store_id: int, source_id: int, exc: Exception
) -> None:
    """FAILED 를 적는다. 작업 연결을 이미 놓았으므로 스스로 빌린다."""
    message = f"{type(exc).__name__}: {exc}"
    try:
        async with pool.acquire() as conn:
            await repo.set_status(conn, store_id, source_id, "FAILED",
                                  error_message=message)
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
    pool: asyncpg.Pool, store_id: int, src: asyncpg.Record
, *, usage_sink=None, usage_context=None) -> tuple[str, list[Path], list[tuple[str, list[Path]]]]:
    """자료 유형별 전처리.

    반환값은 (추출기에 넣을 텍스트, 모델에 함께 보낼 파일들).
    두 번째 값은 영상 프레임이나 스캔 이미지처럼 텍스트로 못 담는 근거다.
    """
    from app.config import get_settings
    source_type = src["source_type"]
    source_id = src["source_id"]

    handler = {
        "VOICE": _preprocess_voice,
        "VIDEO": _preprocess_video,
        "KAKAO": _preprocess_kakao,
        "SCAN": _preprocess_scan,
    }[source_type]

    # 목 모드는 원본을 내려받지 않는다. VOICE 는 전사문 재사용 분기가 있어 그쪽에서 처리한다
    if get_settings().ingest_mode == "mock" and source_type != "VOICE":
        logger.info("preprocess skipped (mock) source=%s type=%s", source_id, source_type)
        return MOCK_PLACEHOLDER, [], []

    # 핸들러는 연결 대신 풀을 받는다. DB 호출마다 짧게 빌리고 다운로드·STT 는 연결 밖에서 한다
    return await handler(pool, store_id, src,
                         usage_sink=usage_sink, usage_context=usage_context)


async def _download(pool: asyncpg.Pool, store_id: int,
                    src: asyncpg.Record) -> Path:
    """원본을 받고, 프론트가 안 보낸 content_hash 를 채운다.

    내려받는 동안은 연결을 쥐지 않는다. 해시 기록만큼만 빌린다.
    """
    source_id = src["source_id"]
    if not src["file_url"]:
        raise RuntimeError("file_url 이 비어 있다. Storage 업로드가 끝난 뒤 호출하라")

    path = await storage.download(source_id, src["file_url"])
    if src["content_hash"] is None:
        digest = storage.sha256_of(path)
        async with pool.acquire() as conn:
            updated = await repo.set_content_hash(conn, store_id, source_id, digest)
        if not updated:
            logger.warning("동일 해시의 자료가 이미 있다 source=%s", source_id)
    return path


async def _preprocess_video(
    pool: asyncpg.Pool, store_id: int, src: asyncpg.Record
, *, usage_sink=None, usage_context=None) -> tuple[str, list[Path], list[tuple[str, list[Path]]]]:
    """영상: 오디오 전사 + 프레임 추출. 프레임은 Storage 에 올리고 근거로 남긴다."""
    from app.config import get_settings

    source_id = src["source_id"]
    async with pool.acquire() as conn:
        row = await repo.get_video(conn, source_id)
    if row is None:
        raise RuntimeError("source_video 행이 없다. /ingest/sources 로 등록했는지 확인하라")

    path = await _download(pool, store_id, src)
    work = storage.workdir(source_id)
    meta = await video.probe(path)

    transcript = row["transcript"]
    stt_segments: list[dict] = []
    if transcript:
        logger.info("STT 건너뜀 — 기존 전사문 재사용 source=%s", source_id)
        # 시각과 함께 저장해둔 전사문이면 구간을 되살린다
        stt_segments = audio.parse_timestamped(transcript)
    elif meta["has_audio"]:
        audio_path = await video.extract_audio(path, work)
        _, stt_segments, _ = await audio.transcribe_detailed(
            audio_path, usage_sink=usage_sink, usage_context=usage_context)
        # 시각을 붙여 저장한다. 추출 프롬프트가 근거 시각을 채우려면 보여야 하고,
        # 재실행 때 STT 없이 다시 쪼개려면 남아 있어야 한다
        transcript = audio.with_timestamps(stt_segments) if stt_segments else ""
    else:
        logger.info("오디오 트랙 없음 source=%s — 화면만으로 추출한다", source_id)
        transcript = ""

    frames = await video.extract_frames(path, work)
    rows = await video.upload_frames(store_id, source_id, frames)
    # 업로드가 끝난 뒤에만 연결을 빌린다
    async with pool.acquire() as conn:
        await repo.insert_frames(conn, row["video_id"], rows)
        await repo.update_video_result(
            conn, source_id,
            duration_sec=meta["duration_sec"], resolution=meta["resolution"],
            fps=meta["fps"], frame_count=len(frames), transcript=transcript or None,
        )

    text = transcript or "(오디오 없음. 화면 이미지만으로 판단할 것)"

    # E4 실험 (이관경계_실험설계.md 4절). 기본값은 frames — 현재 검증된 경로다.
    # native 는 원본을 통째로 모델에 넘긴다. 토큰이 10배 이상 늘 수 있다.
    # 근거용 source_frames 저장은 어느 모드에서도 유지한다.
    if get_settings().video_input_mode == "native":
        logger.info("video_input_mode=native — 원본 영상을 그대로 투입 source=%s", source_id)
        return text, [path], []

    # 긴 영상은 시간 창으로 쪼개 map 한다 (13.4). 창 밖은 그 호출에 보이지 않는다.
    window = get_settings().video_segment_sec
    segments = video.split_by_time(stt_segments, frames, window) if window > 0 else []
    if segments:
        logger.info("영상 %d초 창으로 %d구간 분할 source=%s", window, len(segments), source_id)
    return text, video.sample_for_model(frames), segments


async def _preprocess_kakao(
    pool: asyncpg.Pool, store_id: int, src: asyncpg.Record
, *, usage_sink=None, usage_context=None) -> tuple[str, list[Path], list[tuple[str, list[Path]]]]:
    """카톡: txt 를 파싱한다. LLM 을 쓰지 않는다."""
    source_id = src["source_id"]
    async with pool.acquire() as conn:
        kakao_row = await repo.get_kakao(conn, source_id)
    if kakao_row is None:
        raise RuntimeError("source_kakao 행이 없다. /ingest/sources 로 등록했는지 확인하라")

    path = await _download(pool, store_id, src)

    # 캡처 이미지는 파싱할 텍스트가 없다. 모델이 그림째 읽는다 (import_type SCREENSHOT)
    if path.suffix.lower() in {".png", ".jpg", ".jpeg"}:
        async with pool.acquire() as conn:
            await repo.update_kakao_result(
                conn, source_id, room_name=None, message_count=0, participant_cnt=0,
                period_start=None, period_end=None, parsed_text="",
            )
        return "(카카오톡 대화 캡처. 첨부한 그림을 읽고 판단할 것)", [path], []

    raw = path.read_text(encoding="utf-8", errors="replace")
    parsed = kakao.parse(raw)

    async with pool.acquire() as conn:
        await repo.update_kakao_result(
            conn, source_id,
            room_name=parsed["room_name"],
            message_count=parsed["message_count"],
            participant_cnt=len(parsed["participants"]),
            period_start=parsed["period_start"], period_end=parsed["period_end"],
            parsed_text=parsed["parsed_text"],
        )
    return parsed["parsed_text"], [], []


async def _preprocess_scan(
    pool: asyncpg.Pool, store_id: int, src: asyncpg.Record
, *, usage_sink=None, usage_context=None) -> tuple[str, list[Path], list[tuple[str, list[Path]]]]:
    """문서·이미지: PDF 는 텍스트 레이어를 먼저 읽고, 없으면 모델에 그림째 넘긴다."""
    source_id = src["source_id"]
    async with pool.acquire() as conn:
        row = await repo.get_scan(conn, source_id)
    if row is None:
        raise RuntimeError("source_scan 행이 없다. /ingest/sources 로 등록했는지 확인하라")

    path = await _download(pool, store_id, src)

    if path.suffix.lower() == ".pdf":
        from app.config import get_settings

        read = document.read_pdf(path)
        mode = getattr(get_settings(), "pdf_input_mode", "TEXT")

        # 글이 아예 없는 스캔본은 arm 과 무관하게 문서를 넘긴다. 안 넘기면 빈손이다
        if not read.text:
            async with pool.acquire() as conn:
                await repo.update_scan_result(conn, source_id,
                                              page_count=read.page_count,
                                              ocr_text=None, ocr_engine=None)
            return ("(텍스트 레이어 없는 스캔본. 첨부한 문서를 읽고 판단할 것)",
                    [path], [])

        async with pool.acquire() as conn:
            await repo.update_scan_result(conn, source_id,
                                          page_count=read.page_count,
                                          ocr_text=read.text, ocr_engine="pypdf")

        if mode == "FILE":
            # 텍스트 레이어를 쓰지 않는 arm. 추출한 본문을 붙이지 않는다
            return "(첨부한 문서를 읽고 판단할 것)", [path], []

        if mode == "BOTH":
            return f"{read.text}\n\n(첨부한 문서도 함께 읽고 판단할 것)", [path], []

        # HYBRID — 글로 읽힌 부분을 쓰되, 표·사진 페이지가 남았을 때만 문서를
        # 함께 넘긴다. 첨부하지 않으면 그 페이지는 통째로 사라진다.
        if mode == "HYBRID" and read.visual_pages:
            pages = ", ".join(f"{n}쪽" for n in read.visual_pages)
            return (f"{read.text}\n\n"
                    f"(위 글에 없는 내용이 {pages} 에 그림·표로 있다. "
                    f"첨부한 문서의 해당 쪽을 읽고 판단할 것)"), [path], []

        # TEXT — 대조군. 글로 읽힌 것만 쓴다
        return read.text, [], []

    async with pool.acquire() as conn:
        await repo.update_scan_result(conn, source_id, page_count=1,
                                      ocr_text=None, ocr_engine=None)
    return "(이미지 자료. 첨부한 그림을 읽고 판단할 것)", [path], []


async def _preprocess_voice(
    pool: asyncpg.Pool, store_id: int, src: asyncpg.Record
, *, usage_sink=None, usage_context=None) -> tuple[str, list[Path], list[tuple[str, list[Path]]]]:
    from app.config import get_settings
    source_id = src["source_id"]

    # 전사문이 이미 있으면 STT 를 건너뛴다 (가이드 8장 --skip-stt).
    # 추출 프롬프트는 수십 번 돌려야 하는데 STT 는 느리고 비싸다.
    # 다시 전사하려면 source_voice.transcript 를 비우고 재실행한다.
    async with pool.acquire() as conn:
        row = await repo.get_voice(conn, source_id)
    if row and row["transcript"]:
        logger.info("STT 건너뜀 — 기존 전사문 재사용 source=%s chars=%d",
                    source_id, len(row["transcript"]))
        return row["transcript"], [], []

    if get_settings().ingest_mode == "mock":
        return MOCK_PLACEHOLDER, [], []

    path = await _download(pool, store_id, src)
    meta = await audio.probe(path)
    plain, stt_segments, model = await audio.transcribe_detailed(
        path, usage_sink=usage_sink, usage_context=usage_context)
    text = audio.with_timestamps(stt_segments) if stt_segments else plain

    async with pool.acquire() as conn:
        await repo.update_voice_result(
            conn, source_id,
            duration_sec=meta["duration_sec"] or 0,
            transcript=text,
            stt_model=model,
        )
    return text, [], []


# ── W1: 입력 → 사실 → 원장 → 카드 ────────────────────────────────────────

class ExtractionOutcome(NamedTuple):
    """추출이 무엇을 건졌고 무엇을 버렸는지 함께 전한다.

    실패 구간 수를 돌려주지 않으면 호출부가 부분 성공을 완전 성공과 구분할 수
    없다. 10구간 중 3구간을 잃고도 자료가 `DONE` 으로 끝나면 점주는 전부
    처리됐다고 믿는다.
    """

    assertions: list
    unresolved: list
    segments_total: int
    segments_failed: int
    failed_segment_ids: list[str]


async def _extract_facts_all(
    *, source_id: int, source_type: str, text: str, media: list[Path],
    glossary: list[dict], segments: list[tuple[str, list[Path]]],
    usage_sink=None, usage_base: tuple | None = None,
    checkpoint=None,
    only_segments: set[str] | None = None,
) -> ExtractionOutcome:
    """map — 구간마다 **사실**을 뽑아 모은다. 카드를 만들지 않는다.

    구간 하나가 실패해도 나머지는 살린다. 전부 실패했을 때만 예외를 올린다.
    살린 결과와 함께 **버린 구간**을 돌려준다 — 그래야 호출부가 부분 성공을
    성공으로 위장하지 않는다.
    `local_ref` 는 구간 안에서만 유일하므로 구간 번호를 붙여 전역에서 갈라준다 —
    안 그러면 2구간의 `f1` 이 1구간의 `f1` 을 덮어쓴다.

    `checkpoint(assertions, segment_id)` 를 주면 구간을 뽑는 **즉시** 부른다.
    전부 끝난 뒤 한 번에 적으면 8구간에서 죽을 때 앞 7구간도 같이 사라진다.
    모델 호출은 비싸고 느리다. 이미 뽑은 것은 지킨다.
    적지 못한 구간은 뽑았더라도 잃은 것으로 센다 — 원장에 없으면 없는 것이다.

    `only_segments` 를 주면 PARTIAL 재시도다. 번호(`seg1..segN`)와 전체 구간 수는
    그대로 두고 목록에 든 구간만 뽑는다. 실패 수·목록은 다시 시도한 구간만 센다.
    대상이 전부 다시 실패해도 예외를 올리지 않는다 — 이미 만든 카드가 있다.
    """
    from app.ingest.extract import extract_facts

    def _tag(items, segment: str | None):
        for a in items:
            if segment:
                a.local_ref = f"{segment}:{a.local_ref}"
                a.requires = [f"{segment}:{r}" for r in a.requires]
            a.segment_id = segment
        return items

    if not segments:
        if only_segments is not None:
            # 호출부가 구간 구성을 먼저 확인한다. 여기 오면 자료 전체를 다시 뽑아 카드가 겹친다
            raise RuntimeError("구간 없는 자료는 잃은 구간만 다시 뽑을 수 없다")
        result = await extract_facts(
            source_id=source_id, source_type=source_type, text=text,
            glossary=glossary, media=media, usage_sink=usage_sink,
            usage_context=_ctx_for(usage_base, source_id, "EXTRACT"),
        )
        tagged = _tag(result.assertions, None)
        if checkpoint is not None:
            await checkpoint(tagged, None)
        return ExtractionOutcome(tagged, list(result.unresolved), 1, 0, [])

    merged, unresolved, failed_ids = [], [], []
    for index, (seg_text, seg_media) in enumerate(segments, start=1):
        segment = f"seg{index}"
        if only_segments is not None and segment not in only_segments:
            continue
        try:
            part = await extract_facts(
                source_id=source_id, source_type=source_type, text=seg_text,
                glossary=glossary, media=seg_media, usage_sink=usage_sink,
                usage_context=_ctx_for(usage_base, source_id, "EXTRACT",
                                       segment_id=segment),
            )
        except Exception as exc:
            failed_ids.append(segment)
            logger.warning("구간 %d/%d 사실 추출 실패 source=%s: %s",
                           index, len(segments), source_id, exc)
            continue

        tagged = _tag(part.assertions, segment)
        if checkpoint is not None:
            # 뽑은 즉시 적는다. 적지 못하면 그 구간은 잃은 것으로 센다
            try:
                await checkpoint(tagged, segment)
            except Exception as exc:
                failed_ids.append(segment)
                logger.warning("구간 %d/%d 원장 저장 실패 source=%s: %s",
                               index, len(segments), source_id, exc)
                continue
        merged.extend(tagged)
        unresolved.extend(part.unresolved)
        logger.info("구간 %d/%d 사실 %d건", index, len(segments), len(part.assertions))

    failed = len(failed_ids)
    if only_segments is not None:
        if failed:
            logger.warning("재시도 구간 %d/%d 다시 실패 source=%s",
                           failed, len(only_segments), source_id)
        return ExtractionOutcome(merged, unresolved, len(segments), failed, failed_ids)
    if failed == len(segments):
        raise RuntimeError(f"모든 구간({failed}개) 사실 추출이 실패했다")
    if failed:
        logger.warning("구간 %d/%d 실패 — 나머지로 진행한다", failed, len(segments))
    return ExtractionOutcome(merged, unresolved, len(segments), failed, failed_ids)


async def _record_segment_failures(
    conn: asyncpg.Connection, store_id: int, job_id: int | None, source_id: int,
    *, outcome: "ExtractionOutcome",
) -> None:
    """잃은 구간을 작업 자료 행에 적는다. 뒤에서 상태를 PARTIAL 로 가른다.

    실패가 0 이어도 현재 결과로 덮어쓴다. 안 그러면 재시도로 되찾은 구간이
    지난 실패 기록에 남아 자료가 계속 PARTIAL 로 보인다.

    D1 — store_id 는 필수 인자다. job 없이 도는 레거시 경로에는 적을 행이 없다.
    """
    if job_id is None:
        return
    await conn.execute(
        """
        update ingest_job_sources
        set segments_total = $4, segments_failed = $5,
            failed_segment_ids = $6, updated_at = now()
        where store_id = $1 and job_id = $2 and source_id = $3
        """,
        store_id, job_id, source_id,
        outcome.segments_total, outcome.segments_failed,
        list(outcome.failed_segment_ids) or None,
    )


async def _persist_ledger(
    conn: asyncpg.Connection, store_id: int, source_id: int, source_type: str,
    assertions: list,
) -> dict[str, int]:
    """뽑은 사실을 **조립 전에** 전부 원장에 적는다 (W1).

    {local_ref: fact_id} 를 돌려준다. 조립이 고른 사실을 원장 행에 잇는 열쇠다.

    여기서 적지 않으면 조립이 버린 사실은 어디에도 남지 않는다. 그러면 추출이
    못 뽑은 것과 조립이 버린 것이 같은 숫자로 합쳐져, 무엇을 고쳐야 할지 알 수 없다.
    """
    from app.config import get_settings

    if not assertions:
        return {}

    s = get_settings()
    extract_version = f"{s.gemini_model}@t{s.extract_temperature}/{s.ingest_mode}"
    rows = []
    for a in assertions:
        # 근거 위치는 사실마다 다르다. 영상·음성은 시각, 나머지는 자료 전체
        if source_type in ("VOICE", "VIDEO") and a.evidence.timestamp_sec:
            locator_type = "TIMESTAMP"
            locator = {"timestamp_sec": max(0, a.evidence.timestamp_sec)}
        else:
            locator_type = "WHOLE_SOURCE"
            locator = {}
        rows.append({
            "subject": a.subject,
            "variant": a.as_variant(),
            "attribute": a.attribute,
            "value": a.value,
            "confidence": _to_percent(a.confidence),
            "original_assertion": a.original_assertion,
            "unit": (a.unit or None),
            "polarity": a.polarity,
            "conditions": list(a.conditions),
            "exceptions": list(a.exceptions),
            "step_order": a.as_order(),
            "requires": list(a.requires),
            "local_ref": a.local_ref[:40],
            "segment_id": getattr(a, "segment_id", None),
            "locator_type": locator_type,
            "locator": locator,
            "assembly_state": "PENDING",
        })

    fact_ids = await repo.insert_source_facts(
        conn, store_id, source_id, rows,
        locator_type="WHOLE_SOURCE", locator={},
        extract_version=extract_version,
    )
    return {a.local_ref: fid for a, fid in zip(assertions, fact_ids)}


async def assemble_assertions(
    *, source_id: int, assertions: list,
    categories: list[str], glossary: list[dict],
    usage_sink=None, usage_base: tuple | None = None,
):
    """추출된 사실을 대상 단위로 묶어 카드로 만든다. 등록과 미리보기에서 공유한다.

    새 사실을 만들지 않는다. 고르고 문장으로 다듬는 일만 한다.
    조립 실패는 unresolved에 남긴다. 등록 경로는 호출 전에 사실을 원장에 저장한다.
    """
    from app.ingest.extract import assemble_cards
    from app.ingest.schemas import ExtractionResult

    if not assertions:
        return ExtractionResult(cards=[], unresolved=[])

    flat = [
        {
            "ref": a.local_ref,
            "대상": a.subject,
            "규격": a.as_variant() or "",
            "속성": a.attribute,
            "값": a.value + (f" {a.unit}" if a.unit else ""),
            "부정": a.polarity == "NEGATE",
            "조건": list(a.conditions),
            "예외": list(a.exceptions),
            "순서": a.as_order() or 0,
            "확실함": round(a.confidence, 2),
            "근거시각": a.evidence.timestamp_sec,
        }
        for a in assertions
    ]
    try:
        return await assemble_cards(
            source_id=source_id, facts=flat,
            category_names=categories, glossary=glossary,
            usage_sink=usage_sink,
            usage_context=_ctx_for(usage_base, source_id, "ASSEMBLE"),
        )
    except Exception as exc:
        # 원장은 이미 적혔다. 카드를 못 만들어도 사실은 남는다
        logger.warning("조립 실패 source=%s: %s — 원장의 사실은 남는다", source_id, exc)
        return ExtractionResult(cards=[], unresolved=[f"조립 실패: {exc}"])


async def _persist(
    conn: asyncpg.Connection,
    store_id: int,
    source_id: int,
    categories: dict[str, int],
    result: ExtractionResult,
    *,
    job_id: int | None,
    category_version: int,
    ledger_ids: dict[str, int] | None = None,
) -> int:
    """추출 카드를 is_verified=false 로 적재한다. 임베딩은 점주 승인 후에 한다.

    **원장에는 쓰지 않는다** (W1). 사실은 조립 전에 이미 적혔고, 여기서는 카드가
    그 사실을 가리키게 잇기만 한다. 예전처럼 카드에서 원장을 만들면 조립이 버린
    사실이 사라져 추출 손실과 조립 손실을 구분할 수 없다.
    """
    from app.config import get_settings

    saved = 0
    ledger = ledger_ids or {}
    linked_refs: set[str] = set()
    unmatched: list[str] = []
    source_type = await conn.fetchval(
        "select source_type from sources where store_id = $1 and source_id = $2",
        store_id,
        source_id,
    )
    for card in result.cards:
        category_id = categories.get(card.category_name) or categories.get("기타")
        if category_id is None:
            raise RuntimeError("시스템 카테고리 '기타'가 없습니다.")
        if card.category_name not in categories:
            logger.info(
                "허용 목록에 없는 카테고리 '%s' — 기타로 저장 source=%s",
                card.category_name,
                source_id,
            )

        card_id = await repo.insert_card(
            conn, store_id,
            category_id=category_id,
            source_id=source_id,
            title=card.title,
            content=card.content,
            confidence=_to_percent(card.confidence),
            origin_job_id=job_id,
            category_version=category_version,
        )
        # legacy facts — 코드 이전이 끝나면 끊는다 (13.3-1)
        await repo.insert_facts(conn, card_id, [
            (f.object_name, f.attribute, f.value, _to_percent(f.confidence))
            for f in card.facts
        ])

        if source_type in ("VOICE", "VIDEO"):
            locator_type = "TIMESTAMP"
            locator = {"timestamp_sec": max(0, card.evidence.timestamp_sec)}
        else:
            locator_type = "WHOLE_SOURCE"
            locator = {}

        # 카드 ↔ 원장 잇기 — 조립이 고른 사실의 ref 로 찾는다 (W1)
        refs = [f.ref for f in card.facts if getattr(f, "ref", "")]
        fact_ids = [ledger[r] for r in refs if r in ledger]
        linked_refs.update(r for r in refs if r in ledger)
        unmatched.extend(r for r in refs if r and r not in ledger)
        if refs and not fact_ids:
            # ref 를 하나도 못 이었다. 카드는 남기되 조용히 넘기지 않는다
            logger.warning("카드 '%s' 의 사실 참조를 원장에서 찾지 못했다: %s",
                           card.title[:30], refs[:5])
        if fact_ids:
            await repo.link_card_facts(conn, store_id, card_id, fact_ids)

        await repo.insert_card_evidence(
            conn,
            store_id,
            card_id,
            source_id,
            locator_type=locator_type,
            locator=locator,
        )
        saved += 1

    # 조립이 무엇을 싣고 무엇을 버렸는지 원장에 표시한다 (W1).
    # **버린 것이 남아야 조립 손실을 셀 수 있다.**
    if ledger:
        linked = [ledger[r] for r in linked_refs]
        dropped = [fid for r, fid in ledger.items() if r not in linked_refs]
        await repo.set_assembly_state(conn, store_id, linked, "LINKED")
        await repo.set_assembly_state(conn, store_id, dropped, "DROPPED")
        logger.info("조립 결과 source=%s 사실 %d건 중 실림 %d · 버림 %d%s",
                    source_id, len(ledger), len(linked), len(dropped),
                    f" · 못 이은 참조 {len(unmatched)}" if unmatched else "")

    for item in result.unresolved:
        logger.info("unresolved source=%s: %s", source_id, item)

    return saved


def _to_percent(confidence: float) -> float:
    """0~1 로 받아 DB 에는 0~100 으로 저장한다 (numeric(5,2) CHECK)."""
    return round(max(0.0, min(1.0, float(confidence))) * 100, 2)
