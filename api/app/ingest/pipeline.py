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

import asyncpg

from app.deps import get_pool
from app.ingest import repository as repo
from app.ingest.extract import assemble_cards, extract_cards
from app.ingest.preprocess import audio, document, kakao, storage, video
from app.ingest.schemas import ExtractionResult

logger = logging.getLogger(__name__)

MOCK_PLACEHOLDER = "(목 모드 — 전처리를 건너뛰었다)"


async def process_source(
    store_id: int, source_id: int, *, job_id: int | None = None,
    cost_phase: str = "REGISTRATION", cost_purpose: str = "PRODUCT",
    extraction_run_id: int | None = None,
) -> None:
    """자료 하나를 처리한다.

    원가 계측(CP-00B) — 유료 호출마다 원장에 receipt 를 남긴다. 등록인지 운영인지는
    호출부가 정한다. 추출 결과만 보고 자동 분류하지 않는다 (승인 카드 0건이어도
    운영 중 추가 업로드일 수 있다).
    """
    from app.usage import DbUsageSink

    pool = get_pool()
    usage_sink = DbUsageSink(pool)
    started = time.perf_counter()

    async with pool.acquire() as conn:
        try:
            src = await repo.get_source(conn, store_id, source_id)
            if src is None:
                logger.warning("source %s not in store %s — 처리 중단", source_id, store_id)
                return

            await repo.set_status(conn, store_id, source_id, "PROCESSING")

            text, media, segments = await _preprocess(
                conn, store_id, src,
                usage_sink=usage_sink,
                usage_context=_usage_context(
                    store_id, source_id, job_id, "STT",
                    cost_phase, cost_purpose, extraction_run_id),
            )
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

            result = await _extract_all(
                source_id=source_id,
                source_type=src["source_type"],
                text=text,
                media=media,
                categories=list(categories),
                glossary=glossary,
                segments=segments,
                usage_sink=usage_sink,
                usage_base=(store_id, job_id, cost_phase, cost_purpose,
                            extraction_run_id),
            )

            # 분류 중 설정이 바뀌었으면 저장 직전 최신 카테고리를 사용한다.
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
            async with conn.transaction():
                saved = await _persist(
                    conn,
                    store_id,
                    source_id,
                    categories,
                    result,
                    job_id=int(origin_job_id) if origin_job_id is not None else None,
                    category_version=category_version,
                )

            await repo.set_status(conn, store_id, source_id, "DONE")
            logger.info("ingest DONE source=%s cards=%d unresolved=%d %.1fs",
                        source_id, saved, len(result.unresolved),
                        time.perf_counter() - started)

        except Exception as e:
            logger.exception("ingest FAILED source=%s", source_id)
            await _mark_failed(conn, store_id, source_id, e)

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


def _ctx_for(base: tuple | None, source_id: int, stage: str,
             segment_id: str | None = None):
    """usage_base 가 없으면 계측하지 않는다 (기존 호출 경로 호환)."""
    if base is None:
        return None
    store_id, job_id, phase, purpose, run_id = base
    return _usage_context(store_id, source_id, job_id, stage, phase, purpose,
                          run_id, segment_id=segment_id)


async def _extract_all(
    *, source_id: int, source_type: str, text: str, media: list[Path],
    categories: list[str], glossary: list[dict],
    segments: list[tuple[str, list[Path]]],
    usage_sink=None, usage_base: tuple | None = None,
) -> ExtractionResult:
    """구간이 있으면 구간마다 뽑고 합친다. 없으면 통째로 한 번 뽑는다.

    38분을 한 호출에 담으면 모델이 요약하고 세부를 버린다 —
    store-a 실측에서 영상 사실 62건 중 61건을 아예 못 뽑았다.
    구간을 나누면 한 호출이 보는 범위가 줄어든다.

    구간 하나가 실패해도 나머지는 살린다. 전부 실패했을 때만 예외를 올린다.
    """
    from app.config import get_settings

    if not segments:
        # native 영상이 실패하면 프레임으로 폴백한다 (이관경계 4절).
        # 한 모드가 죽었다고 자료 전체를 버리지 않는다.
        return await extract_cards(
            source_id=source_id, source_type=source_type, text=text,
            category_names=categories, glossary=glossary, media=media,
            usage_sink=usage_sink,
            usage_context=_ctx_for(usage_base, source_id, "EXTRACT"),
        )

    merged = ExtractionResult(cards=[], unresolved=[])
    failed = 0
    for index, (seg_text, seg_media) in enumerate(segments, start=1):
        try:
            part = await extract_cards(
                source_id=source_id, source_type=source_type, text=seg_text,
                category_names=categories, glossary=glossary, media=seg_media,
                usage_sink=usage_sink,
                usage_context=_ctx_for(usage_base, source_id, "EXTRACT",
                                       segment_id=f"seg{index}"),
            )
        except Exception as exc:
            failed += 1
            logger.warning("구간 %d/%d 추출 실패 source=%s: %s",
                           index, len(segments), source_id, exc)
            continue
        merged.cards.extend(part.cards)
        merged.unresolved.extend(part.unresolved)
        logger.info("구간 %d/%d 카드 %d장 (프레임 %d장)",
                    index, len(segments), len(part.cards), len(seg_media))

    if failed == len(segments):
        raise RuntimeError(f"모든 구간({failed}개) 추출이 실패했다")
    if failed:
        logger.warning("구간 %d/%d 실패 — 나머지 결과로 진행한다", failed, len(segments))
    logger.info("구간 %d개 합계 카드 %d장 source=%s",
                len(segments), len(merged.cards), source_id)

    if get_settings().extract_passes < 2:
        return merged

    # reduce — 구간별 사실을 모아 대상 단위로 다시 조립한다.
    # 분할만 하면 같은 대상이 여러 카드로 쪼개져 신입이 카드 하나로는 답을 못 얻는다
    # (store-a 실측: 분할만 켰을 때 ASSEMBLY 6 → 22건, 카드 33 → 72장).
    flat = [
        {
            "대상": f.object_name,
            "속성": f.attribute,
            "값": f.value,
            "확실함": round(f.confidence, 2),
            "근거시각": card.evidence.timestamp_sec,
            "구간카드": card.title,
        }
        for card in merged.cards
        for f in card.facts
    ]
    if not flat:
        logger.info("조립할 사실이 없다 — map 결과를 그대로 쓴다 source=%s", source_id)
        return merged

    try:
        reduced = await assemble_cards(
            source_id=source_id, facts=flat,
            category_names=categories, glossary=glossary,
            usage_sink=usage_sink,
            usage_context=_ctx_for(usage_base, source_id, "ASSEMBLE"),
        )
    except Exception as exc:
        # 조립이 죽었다고 뽑아둔 것을 버리지 않는다. map 결과로 폴백한다
        logger.warning("조립 실패 — map 결과로 폴백한다 source=%s: %s", source_id, exc)
        return merged

    if not reduced.cards:
        logger.warning("조립 결과가 비었다 — map 결과로 폴백한다 source=%s", source_id)
        return merged

    reduced.unresolved.extend(merged.unresolved)
    logger.info("조립 완료 source=%s 사실 %d건 · 카드 %d → %d장",
                source_id, len(flat), len(merged.cards), len(reduced.cards))
    return reduced


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

    return await handler(conn, store_id, src,
                         usage_sink=usage_sink, usage_context=usage_context)


async def _download(conn: asyncpg.Connection, store_id: int,
                    src: asyncpg.Record) -> Path:
    """원본을 받고, 프론트가 안 보낸 content_hash 를 채운다."""
    source_id = src["source_id"]
    if not src["file_url"]:
        raise RuntimeError("file_url 이 비어 있다. Storage 업로드가 끝난 뒤 호출하라")

    path = await storage.download(source_id, src["file_url"])
    if src["content_hash"] is None:
        if not await repo.set_content_hash(conn, store_id, source_id,
                                           storage.sha256_of(path)):
            logger.warning("동일 해시의 자료가 이미 있다 source=%s", source_id)
    return path


async def _preprocess_video(
    conn: asyncpg.Connection, store_id: int, src: asyncpg.Record
, *, usage_sink=None, usage_context=None) -> tuple[str, list[Path], list[tuple[str, list[Path]]]]:
    """영상: 오디오 전사 + 프레임 추출. 프레임은 Storage 에 올리고 근거로 남긴다."""
    from app.config import get_settings

    source_id = src["source_id"]
    row = await repo.get_video(conn, source_id)
    if row is None:
        raise RuntimeError("source_video 행이 없다. /ingest/sources 로 등록했는지 확인하라")

    path = await _download(conn, store_id, src)
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
    conn: asyncpg.Connection, store_id: int, src: asyncpg.Record
, *, usage_sink=None, usage_context=None) -> tuple[str, list[Path], list[tuple[str, list[Path]]]]:
    """카톡: txt 를 파싱한다. LLM 을 쓰지 않는다."""
    source_id = src["source_id"]
    if await repo.get_kakao(conn, source_id) is None:
        raise RuntimeError("source_kakao 행이 없다. /ingest/sources 로 등록했는지 확인하라")

    path = await _download(conn, store_id, src)

    # 캡처 이미지는 파싱할 텍스트가 없다. 모델이 그림째 읽는다 (import_type SCREENSHOT)
    if path.suffix.lower() in {".png", ".jpg", ".jpeg"}:
        await repo.update_kakao_result(
            conn, source_id, room_name=None, message_count=0, participant_cnt=0,
            period_start=None, period_end=None, parsed_text="",
        )
        return "(카카오톡 대화 캡처. 첨부한 그림을 읽고 판단할 것)", [path], []

    raw = path.read_text(encoding="utf-8", errors="replace")
    parsed = kakao.parse(raw)

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
    conn: asyncpg.Connection, store_id: int, src: asyncpg.Record
, *, usage_sink=None, usage_context=None) -> tuple[str, list[Path], list[tuple[str, list[Path]]]]:
    """문서·이미지: PDF 는 텍스트 레이어를 먼저 읽고, 없으면 모델에 그림째 넘긴다."""
    source_id = src["source_id"]
    row = await repo.get_scan(conn, source_id)
    if row is None:
        raise RuntimeError("source_scan 행이 없다. /ingest/sources 로 등록했는지 확인하라")

    path = await _download(conn, store_id, src)

    if path.suffix.lower() == ".pdf":
        text, pages = document.read_pdf(path)
        if text:
            await repo.update_scan_result(conn, source_id, page_count=pages,
                                          ocr_text=text, ocr_engine="pypdf")
            return text, [], []
        # 텍스트 레이어가 없는 스캔본 — PDF 를 그대로 모델에 넘긴다
        await repo.update_scan_result(conn, source_id, page_count=pages,
                                      ocr_text=None, ocr_engine=None)
        return "(텍스트 레이어 없는 스캔본. 첨부한 문서를 읽고 판단할 것)", [path], []

    await repo.update_scan_result(conn, source_id, page_count=1,
                                  ocr_text=None, ocr_engine=None)
    return "(이미지 자료. 첨부한 그림을 읽고 판단할 것)", [path], []


async def _preprocess_voice(
    conn: asyncpg.Connection, store_id: int, src: asyncpg.Record
, *, usage_sink=None, usage_context=None) -> tuple[str, list[Path], list[tuple[str, list[Path]]]]:
    from app.config import get_settings
    source_id = src["source_id"]

    # 전사문이 이미 있으면 STT 를 건너뛴다 (가이드 8장 --skip-stt).
    # 추출 프롬프트는 수십 번 돌려야 하는데 STT 는 느리고 비싸다.
    # 다시 전사하려면 source_voice.transcript 를 비우고 재실행한다.
    row = await repo.get_voice(conn, source_id)
    if row and row["transcript"]:
        logger.info("STT 건너뜀 — 기존 전사문 재사용 source=%s chars=%d",
                    source_id, len(row["transcript"]))
        return row["transcript"], [], []

    if get_settings().ingest_mode == "mock":
        return MOCK_PLACEHOLDER, [], []

    path = await _download(conn, store_id, src)
    meta = await audio.probe(path)
    plain, stt_segments, model = await audio.transcribe_detailed(
        path, usage_sink=usage_sink, usage_context=usage_context)
    text = audio.with_timestamps(stt_segments) if stt_segments else plain

    await repo.update_voice_result(
        conn, source_id,
        duration_sec=meta["duration_sec"] or 0,
        transcript=text,
        stt_model=model,
    )
    return text, [], []


async def _persist(
    conn: asyncpg.Connection,
    store_id: int,
    source_id: int,
    categories: dict[str, int],
    result: ExtractionResult,
    *,
    job_id: int | None,
    category_version: int,
) -> int:
    """추출 카드를 is_verified=false 로 적재한다. 임베딩은 점주 승인 후에 한다."""
    from app.config import get_settings

    saved = 0
    # 어느 추출이 이 사실을 만들었나. 프롬프트를 바꾼 뒤 무엇이 달라졌는지 되짚는다
    s = get_settings()
    extract_version = f"{s.gemini_model}@t{s.extract_temperature}/{s.ingest_mode}"
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

        # 사실 원장 — 소유자는 자료다. 카드를 다시 조립해도 사실은 남는다 (13.3-1).
        # 근거 위치는 지금 카드 단위라 같은 카드의 사실이 같은 위치를 갖는다.
        # 13.4 에서 map 이 사실별 위치를 뽑으면 그 값으로 바뀐다.
        fact_ids = await repo.insert_source_facts(
            conn, store_id, source_id,
            [
                {
                    "subject": f.object_name,
                    "variant": None,   # 13.5 에서 RECIPE 스키마가 규격을 채운다
                    "attribute": f.attribute,
                    "value": f.value,
                    "confidence": _to_percent(f.confidence),
                }
                for f in card.facts
            ],
            locator_type=locator_type,
            locator=locator,
            extract_version=extract_version,
        )
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

    for item in result.unresolved:
        logger.info("unresolved source=%s: %s", source_id, item)

    return saved


def _to_percent(confidence: float) -> float:
    """0~1 로 받아 DB 에는 0~100 으로 저장한다 (numeric(5,2) CHECK)."""
    return round(max(0.0, min(1.0, float(confidence))) * 100, 2)
