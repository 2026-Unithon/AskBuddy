"""준혁 (feat/input) — 자료 처리 파이프라인.

상태 머신 (개발가이드 6-1):
    UPLOADED → PROCESSING → DONE
                         ↘ FAILED (error_message 필수)

이 함수는 백그라운드에서 돈다. 요청 커넥션이 이미 닫힌 뒤이므로 풀에서 직접 얻는다.
실패하면 다음 단계로 넘어가지 않고 FAILED 로 명확히 멈춘다.
"""
import asyncio
import logging
import shutil
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Mapping, NamedTuple, Sequence

import asyncpg

from app.deps import get_pool
from app.ingest import occurrences
from app.ingest import repository as repo
from app.ingest import recovery
from app.ingest.intake import route as intake_route
from app.ingest.raw_responses import TruncatedOutputError
from app.ingest.preprocess import audio, document, kakao, storage, video
from app.ingest.variant_split import split_hot_ice
from app.ingest.schemas import ExtractedAssertion

logger = logging.getLogger(__name__)

MOCK_PLACEHOLDER = "(목 모드 — 전처리를 건너뛰었다)"

# PARTIAL 재시도에서 구간 구성이 달라져 잃은 구간만 다시 읽을 수 없을 때 돌려준다.
# 호출부(job_worker)가 이 값을 보고 자료를 PARTIAL 로 남긴다
PARTIAL_RETRY_UNAVAILABLE = "PARTIAL_RETRY_UNAVAILABLE"

# 입구 분류가 업무 자료가 아니라고(NONE) 판정해 추출하지 않았을 때 돌려준다(Phase B).
# 호출부(job_worker)가 이 값을 보고 작업 자료를 NO_RESULT 와 안내 메시지로 적는다
INTAKE_NONE = "INTAKE_NONE"


from app.config import get_settings
from app.ingest.resilience import limited, retry_io


@limited("ingest_source_concurrency")
async def process_source(
    store_id: int, source_id: int, *, job_id: int | None = None,
    cost_phase: str = "REGISTRATION", cost_purpose: str = "PRODUCT",
    extraction_run_id: int | None = None,
    retry_segments: list[str] | None = None,
    expected_segments_total: int | None = None,
    run_tag: int | None = None,
    intake_cache: "intake_route.IntakeCache | None" = None,
) -> str | None:
    """자료 하나를 처리한다.

    원가 계측(CP-00B) — 유료 호출마다 원장에 receipt 를 남긴다. 등록인지 운영인지는
    호출부가 정한다. 추출 결과만 보고 자동 분류하지 않는다 (승인 카드 0건이어도
    운영 중 추가 업로드일 수 있다).

    `retry_segments` 를 주면 PARTIAL 재시도다. 그 구간만 다시 뽑아 카드를 **추가**
    한다. 이미 만든 카드·원장은 건드리지 않는다. 구간 구성이 지난 실행과 달라
    같은 구간을 가리킬 수 없으면 추출하지 않고 `PARTIAL_RETRY_UNAVAILABLE` 을
    돌려준다. 보통 경로는 `None` 을 돌려준다.

    `run_tag` 는 같은 작업을 다시 돌릴 때 실행 하나를 가르는 표지다 (job_worker 가
    자료 시작 시각에서 만든다). 없으면 논리 호출 ID 가 작업 단위로만 묶인다.

    `intake_cache` 를 주면 그 캐시를 쓴다 — 작업 묶음 분류가 훑으며 받은 다운로드·파싱을
    다시 하지 않는다(S1). 없으면 새 캐시를 만든다.
    """
    from app.ingest.raw_responses import DbRawResponseSink
    from app.usage import DbUsageSink

    pool = get_pool()
    # 추출은 백그라운드 작업이라 영수증 저장의 일시 장애를 재시도로 버틴다
    usage_sink = DbUsageSink(pool, resilient=True)
    # 모델 원래 응답 기록 (W1-1). mock 도 같은 기록을 남긴다. 저장 실패는 추출을 멈춘다
    raw_sink = DbRawResponseSink(pool, run_tag=run_tag)
    started = time.perf_counter()
    recovery_enabled = job_id is not None and extraction_run_id is None and cost_purpose == 'PRODUCT'
    previous = None

    # 연결은 DB 를 칠 때만 짧게 빌린다. 다운로드·STT·추출·조립처럼 느린 외부
    # 호출 동안 쥐고 있으면, 별도 연결을 잡는 원가 receipt 와 작은 풀에서 겹쳐
    # 작업 전체가 멈춘다.
    try:
        async with pool.acquire() as conn:
            src = await repo.get_source(conn, store_id, source_id)
            if src is None:
                logger.warning("source %s not in store %s — 처리 중단", source_id, store_id)
                return
            if recovery_enabled:
                previous = await recovery.load(conn, store_id, job_id, source_id)
                if previous and previous['phase'] == 'COMMITTED' and not previous['outcome']['failed_segment_ids']:
                    # 카드 커밋 후 worker 결과 기록만 실패한 재호출은 카드를 다시 만들지 않는다.
                    await repo.set_status(conn, store_id, source_id, 'DONE')
                    return
            await repo.set_status(conn, store_id, source_id, "PROCESSING")

        # 분류 단계를 화면에 먼저 알린다(B-D10). 작업 없는 경로는 적을 행이 없다
        if job_id is not None:
            async with pool.acquire() as conn:
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
                      extraction_run_id, run_tag)

        # ── 입구 분류(Phase B) ─────────────────────────────────────────
        # 최신 판정이 있으면 재사용한다 — 재시도·복구에서 구간 구성이 지난 실행과 같다.
        # 분류 실패(IntakeClassificationError)는 아래 except 가 FAILED 로 적는다
        from app.ingest.intake.plan import plan_extraction
        from app.ingest.intake.registry import SECTIONED_NORMALIZERS

        stt_context = _usage_context(
            store_id, source_id, job_id, "STT",
            cost_phase, cost_purpose, extraction_run_id, run_tag=run_tag)
        # 평가 실행(운영 제품 경로가 아닌 실행)은 입구 분류를 하지 않는다 — 지금까지와 같은
        # 입력으로 재야 비교가 된다(D16). 분류 호출도 없다
        intake_enabled = cost_purpose == "PRODUCT" and extraction_run_id is None
        # 함수 안에서 들여와 테스트가 바꾼 설정을 본다. 입구 블록(구역 추출 판단)보다 먼저 둔다
        from app.config import get_settings
        plan = None
        # 한 호출(S3)이 이미 뽑은 사실. 구간 없는 첫 추출 대신 쓴다
        prefetched = None
        if intake_enabled:
            cache = intake_cache or intake_route.IntakeCache()
            route = await intake_route.route_source(
                pool, store_id, src, cache=cache, usage_sink=usage_sink, usage_base=usage_base)
            single_pending = (route if isinstance(route, intake_route.SingleCallPending)
                              else None)
            if (single_pending is None and route.source.logic == "NONE"
                    and route.normalizer not in SECTIONED_NORMALIZERS):
                # 업무 자료가 아니다 — 전처리(전체 STT·프레임 업로드)부터 하지 않는다
                return await _finish_intake_none(pool, store_id, source_id, job_id, started)

            text, media, segments = await _preprocess(
                pool, store_id, src, usage_sink=usage_sink, usage_context=stt_context,
                cache=cache)
            if single_pending is not None and _layout_mode(src, get_settings()):
                # 구역(LAYOUT) 추출로 갈 자료다 — 한 호출 결과를 쓸 수 없어 두 번 내게 된다.
                # 한 호출 없이 분류해 저장하고 보통(구역) 추출로 간다
                logger.warning("구역 추출 자료 — 한 호출 대신 분류한다 source=%s", source_id)
                route = await intake_route.classify_and_save(
                    pool, store_id, src, single_pending.probe, hints=single_pending.hints,
                    usage_sink=usage_sink, usage_base=usage_base)
                if route.source.logic == "NONE":
                    return await _finish_intake_none(pool, store_id, source_id, job_id, started)
            elif single_pending is not None:
                # 작은 자료 — 분류와 추출을 한 호출로(S3). 잘리면 분류 후 보통 경로로 간다.
                # 순위 없는 결과(IntakeClassificationError)는 아래 except 가 FAILED 로 적는다
                async with pool.acquire() as conn:
                    glossary_now = await repo.glossary(conn, store_id)
                try:
                    single = await intake_route.extract_with_intake(
                        pool, store_id, src, single_pending, text=text, media=media,
                        glossary=glossary_now, usage_sink=usage_sink, usage_base=usage_base,
                        raw_sink=raw_sink)
                    route, prefetched = single.route, single.result
                except TruncatedOutputError:
                    logger.warning("한 호출 출력 잘림 — 분류 후 보통 추출로 간다 source=%s",
                                   source_id)
                    route = await intake_route.classify_and_save(
                        pool, store_id, src, single_pending.probe, hints=single_pending.hints,
                        usage_sink=usage_sink, usage_base=usage_base)
                if route.source.logic == "NONE":
                    # 업무 자료가 아니다 — 뽑은 사실은 원장에 적지 않는다(Review Focus 2)
                    return await _finish_intake_none(pool, store_id, source_id, job_id, started)
                if (prefetched is not None and route.source.hint_changed_decision
                        and route.source.model_ranking
                        and route.source.model_ranking[0].logic == "NONE"):
                    # 모델 1위는 NONE 이라 꼬리 지시대로 사실을 비웠는데 점주 칩이 결정을 바꿨다.
                    # 빈 결과를 쓰지 않고 저장 판정으로 보통 추출 1회를 한다(최종 검토 I-1)
                    logger.warning("한 호출 NONE 을 점주 칩이 뒤집음 — 보통 추출로 다시 뽑는다 "
                                   "source=%s logic=%s", source_id, route.source.logic)
                    prefetched = None
            plan = plan_extraction(normalizer=route.normalizer, decisions=route.decisions,
                                   source=route.source,
                                   sections=intake_route.full_sections(cache, route.normalizer))
            if plan.skip:
                return await _finish_intake_none(pool, store_id, source_id, job_id, started)
            # 거른 것이 없으면 계획 글은 전처리 글과 같다(D16). 구간별 묶음이면 구간을 바꾼다
            if plan.text is not None:
                text = plan.text
            if plan.segments is not None:
                segments = plan.segments
        else:
            text, media, segments = await _preprocess(
                pool, store_id, src, usage_sink=usage_sink, usage_context=stt_context)

        fingerprint = await asyncio.to_thread(recovery.layout_hash, src, text, media, segments, get_settings()) if recovery_enabled else None
        if previous and previous['phase'] == 'COMMITTED':
            retry_segments = previous['outcome']['failed_segment_ids']
            expected_segments_total = previous['outcome']['segments_total']
        # LAYOUT 모드의 구역 ID 는 구역 지도 응답이 재사용될 때만 같은 영역을 가리킨다(계획 편차 4)
        layout_retry_ok = (_layout_mode(src, get_settings())
                           and bool(getattr(get_settings(), "extract_reuse_enabled", False)))
        if ((previous and previous['layout_hash'] != fingerprint)
                or (retry_segments is not None and not layout_retry_ok and (
                    not previous or not _same_layout(segments, retry_segments, expected_segments_total)))):
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

        # ── 입력 → 사실 → (원장) → 카드 ──────────────────────────────
        # 예전에는 입력 → 카드 → (카드에서) 원장 이었다. 그래서 조립이 버린
        # 사실은 원장에도 안 남아, 못 뽑은 것과 뽑고 버린 것을 구분할 수
        # 없었다. 이제 뽑는 즉시 전부 원장에 적고 조립이 그중에서 고른다.
        # 구간을 뽑는 즉시 원장에 적는다 (checkpoint). 전부 끝난 뒤 한 번에
        # 적으면 뒤쪽 구간에서 죽을 때 앞서 뽑은 것까지 같이 사라진다.
        # 연결과 트랜잭션은 구간 하나만큼만 잡아 모델 호출 중 DB 를 점유하지 않는다.
        ledger_ids: dict[str, int] = {}

        async def _checkpoint(seg_assertions, segment_id):
            async def write():
                async with pool.acquire() as c, c.transaction():
                    saved = await _persist_ledger(
                        c, store_id, source_id, src["source_type"], seg_assertions)
                return saved
            ledger_ids.update(await retry_io(write, stage="ledger.checkpoint"))

        if previous and previous['phase'] == 'EXTRACTED':
            cached = previous['outcome']
            outcome = ExtractionOutcome(
                [ExtractedAssertion.model_validate(a) for a in cached['assertions']],
                cached['unresolved'], cached['segments_total'], cached['segments_failed'],
                cached['failed_segment_ids'],
                # 복구본에는 원래 응답 ID 가 없다. 인스턴스마다 새 dict 를 준다
                {})
            ledger_ids = previous['ledger_ids']
        else:
            # SCAN·LAYOUT 은 구역 기반 다단계 추출로 간다. mock 은 원본이 없어(media 빈 목록)
            # 오케스트레이터가 빈 쪽으로 돈다. 그 밖의 경로는 이전과 같다
            layout_mode = _layout_mode(src, get_settings())
            if layout_mode:
                from app.ingest.layout import run_layout_extraction
                outcome = await run_layout_extraction(
                    source_id=source_id, path=media[0] if media else None,
                    workdir=storage.workdir(source_id) / "layout", glossary=glossary,
                    usage_sink=usage_sink, usage_base=usage_base, raw_sink=raw_sink,
                    checkpoint=_checkpoint,
                    only_segments=set(retry_segments) if retry_segments is not None else None)
            else:
                if prefetched is not None and segments:
                    # 작은 자료라 생기지 않는다. 구간 글과 맞지 않으니 한 호출 결과를 버린다
                    logger.warning("한 호출 뒤 구간 %d개 — 한 호출 결과를 버리고 다시 뽑는다 "
                                   "source=%s", len(segments), source_id)
                outcome = await _extract_facts_all(
                    source_id=source_id, source_type=src["source_type"], text=text, media=media,
                    glossary=glossary, segments=segments, usage_sink=usage_sink, usage_base=usage_base,
                    raw_sink=raw_sink, checkpoint=_checkpoint,
                    only_segments=set(retry_segments) if retry_segments is not None else None,
                    prefetched=prefetched if not segments else None,
                )
            if recovery_enabled:
                pending = dict(version=1, phase='EXTRACTED', layout_hash=fingerprint,
                    outcome=dict(assertions=[a.model_dump(mode='json') for a in outcome.assertions],
                        unresolved=outcome.unresolved, segments_total=outcome.segments_total,
                        segments_failed=outcome.segments_failed, failed_segment_ids=outcome.failed_segment_ids),
                    ledger_ids=ledger_ids)
                async with pool.acquire() as c, c.transaction():
                    await recovery.replace(c, store_id, job_id, source_id, previous, pending)
                previous = pending
        assertions, unresolved = outcome.assertions, outcome.unresolved
        # 원장 선저장은 위 checkpoint 에서 구간마다 이미 끝났다
        logger.info("원장 선저장 source=%s 사실 %d건", source_id, len(ledger_ids))

        # 분류 중 설정이 바뀌었으면 최신 카테고리로 조립한다 (기존 동작 유지)
        async with pool.acquire() as conn:
            categories = await repo.enabled_categories(conn, store_id)

        # NOTICE 보류는 occurrence 단위다. 이 자료에서 공지 구간(또는 자료 전체)에만 나온
        # 사실은 이 자료 occurrence 를 잇지 않고 INTAKE_NOTICE 검수 대기로 둔다. 그중 다른 받침이
        # 없는 사실만 조립 묶음에서도 뺀다
        hold_kw = {}
        if plan is not None and (plan.hold_all_notice or plan.notice_segment_ids):
            async with pool.acquire() as conn:
                notice_only, unsupported = await _notice_holds(
                    conn, store_id, source_id,
                    None if plan.hold_all_notice else sorted(plan.notice_segment_ids))
            from app.ingest import fact_cards
            hold_kw = {"held_fact_ids": {f: fact_cards.REASON_INTAKE_NOTICE for f in unsupported},
                       "notice_fact_ids": notice_only}
            logger.info("공지 보류 source=%s 사실 %d건 (조립 제외 %d건)",
                        source_id, len(notice_only), len(unsupported))

        # 대상 단위 사실 조립 — 입력은 짧은 연결로 읽고 놓은 뒤 모델을 부른다.
        # 배치 실패는 strict 라 예외(FAILED)
        prepared = await _prepare_fact_assembly(
            pool, store_id, source_id, categories=list(categories), glossary=glossary,
            usage_sink=usage_sink, usage_base=usage_base, raw_sink=raw_sink, strict=True,
            **hold_kw)
        unresolved_total = len(prepared.planning.unresolved) + len(unresolved)

        async with pool.acquire() as conn:
            async with conn.transaction():
                if recovery_enabled:
                    committed = dict(previous, phase='COMMITTED', ledger_ids={},
                                     outcome=dict(previous['outcome'], assertions=[], unresolved=[]))
                    await recovery.replace(conn, store_id, job_id, source_id, previous, committed)
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

                saved = await _persist_fact_cards(
                    conn, store_id, source_id, categories, prepared,
                    job_id=int(origin_job_id) if origin_job_id is not None else None,
                    category_version=category_version)

                # 카드·구간 결과·완료를 함께 확정한다. 중간 오류는 모두 rollback한다.
                await _record_segment_failures(
                    conn, store_id, job_id, source_id, outcome=outcome)

                await repo.set_status(conn, store_id, source_id, "DONE")
        logger.info("ingest DONE source=%s cards=%d unresolved=%d "
                    "구간 %d/%d 실패 %.1fs",
                    source_id, saved,
                    unresolved_total,
                    outcome.segments_failed, outcome.segments_total,
                    time.perf_counter() - started)
        return None

    except recovery.RecoveryConflict:
        # 다른 호출이 확정한 상태를 FAILED로 덮지 않는다.
        raise
    except Exception as e:
        logger.exception("ingest FAILED source=%s", source_id)
        await _mark_failed(pool, store_id, source_id, e)

    finally:
        shutil.rmtree(storage.workdir(source_id), ignore_errors=True)


def _layout_mode(src, settings) -> bool:
    """이 자료가 구역(LAYOUT) 다단계 추출로 가는가. 추출 분기와 한 호출 판단이 같은 조건을 쓴다."""
    return (src["source_type"] == "SCAN"
            and getattr(settings, "scan_extract_mode", "SINGLE") == "LAYOUT")


def _usage_context(store_id: int, source_id: int, job_id: int | None,
                   stage: str, cost_phase: str, cost_purpose: str,
                   extraction_run_id: int | None, segment_id: str | None = None,
                   attempt_no: int = 1, run_tag: int | None = None):
    """호출 하나를 어느 매장·단계에 귀속시킬지. 논리 호출 ID 로 재시도를 묶는다.

    **재추출은 재시도가 아니다.** 논리 호출 ID 에 실행 범위를 넣지 않으면 같은
    자료를 다시 뽑을 때 원장 unique 에 걸려 추출 자체가 죽는다 — 계측이 제품을
    멈추게 한다. 같은 실행 안의 재시도만 `attempt_no` 로 묶는다.

    같은 작업을 다시 돌리는 재시도(실패 자료·잃은 구간)도 재추출이다. 작업 ID 만으로는
    지난 실행과 ID 가 같아지므로 `run_tag` 로 실행을 가른다.
    """
    from app.contracts.usage import UsageContext

    # 실행 범위: 평가는 run, 제품은 job. 둘 다 없으면 자료 단위로만 묶인다
    # 제품 작업은 실행 표지를 붙인다 — `job{J}r{tag}:`. 길이 상한 80 안이다
    # (ID 9자리·표지 13자리·seg99 에서 약 55자)
    job_scope = f"job{job_id}r{run_tag}:" if run_tag else f"job{job_id}:"
    # 작업 없는 운영 수집(점주 답변)은 실행 표지로 재시도를 가른다
    scope = (f"run{extraction_run_id}:" if extraction_run_id
             else job_scope if job_id else f"r{run_tag}:" if run_tag else "")
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


async def _finish_intake_none(pool, store_id: int, source_id: int, job_id: int | None,
                              started: float) -> str:
    """업무 자료가 아니라는 판정으로 끝낸다. 구간 기록은 0/1, 자료는 DONE."""
    async with pool.acquire() as conn, conn.transaction():
        await _record_segment_failures(
            conn, store_id, job_id, source_id,
            outcome=ExtractionOutcome([], [], 1, 0, [], {}))
        await repo.set_status(conn, store_id, source_id, "DONE")
    logger.info("ingest DONE(INTAKE_NONE) source=%s — 업무 자료 아님, 추출하지 않음 %.1fs",
                source_id, time.perf_counter() - started)
    return INTAKE_NONE


async def _notice_holds(conn: asyncpg.Connection, store_id: int, source_id: int,
                        segment_ids: list[str] | None
                        ) -> tuple[frozenset[int], frozenset[int]]:
    """공지 보류 대상 지식 사실 (이 자료에서 공지에만 나온 것, 그중 다른 받침이 없는 것).

    - 공지에만 나온 사실: 이 자료의 **모든** occurrence(source_fact_occurrences)가 공지 범위다
      (`segment_ids` 가 None 이면 자료 전체가 공지). 원장 행의 첫 구간만 보지 않는다 —
      같은 사실이 RECIPE 구간에도 나오면 보통 사실이다.
    - 다른 받침: 다른 자료의 원장 행이 같은 지식 사실로 이어져 있다.
    조립·카드·검수 사유는 원장 행 ID 가 아니라 지식 사실 ID 로 일하므로 연결표로 옮긴다.
    """
    rows = await conn.fetch(
        "select l.fact_id, o.segment_id, "
        "       exists (select 1 from source_fact_revision_links l2 "
        "               join source_facts sf2 on sf2.store_id = l2.store_id "
        "                 and sf2.fact_id = l2.source_fact_id "
        "               where l2.store_id = $1 and l2.fact_id = l.fact_id "
        "                 and sf2.source_id <> $2) as other_support "
        "from source_fact_occurrences o "
        "join source_fact_revision_links l on l.store_id = o.store_id "
        "  and l.source_fact_id = o.fact_id "
        "where o.store_id = $1 and o.source_id = $2 "
        "order by l.fact_id, o.occurrence_id",
        store_id, source_id)
    return notice_holds_of(rows, segment_ids)


def notice_holds_of(rows, segment_ids: list[str] | None
                    ) -> tuple[frozenset[int], frozenset[int]]:
    """occurrence 행(fact_id·segment_id·other_support)에서 공지 보류 대상을 가른다. 순수 함수."""
    scope = None if segment_ids is None else set(segment_ids)
    all_notice: dict[int, bool] = {}
    supported: dict[int, bool] = {}
    for r in rows:
        fid = int(r["fact_id"])
        in_notice = scope is None or r["segment_id"] in scope
        all_notice[fid] = all_notice.get(fid, True) and in_notice
        supported[fid] = supported.get(fid, False) or bool(r["other_support"])
    notice_only = frozenset(f for f, v in all_notice.items() if v)
    return notice_only, frozenset(f for f in notice_only if not supported[f])


async def _store_notice_holds(conn: asyncpg.Connection, store_id: int, source_id: int,
                              fact_ids: Sequence[int], notice_fact_ids: frozenset[int]
                              ) -> frozenset[int]:
    """매장 전체 기준 공지 보류 사실 (최종 리뷰 I1).

    공지 보류는 그 공지 자료의 실행에서만 걸면, 뒤에 같은 대상을 건드리는 다른 자료(레시피 업로드·
    점주 답변)의 조립이 그 사실을 head 로 읽어 카드에 넣는다. 그래서 조립마다 매장 전체를 다시 본다.
    다른 자료의 occurrence 와 점주 출처만 보고, 이 자료 몫은 이번 실행의 공지 범위로 가른다.
    """
    ids = sorted({int(f) for f in fact_ids})
    if not ids:
        return frozenset()
    rows = await conn.fetch(
        "select k.fact_id, "
        "  exists (select 1 from fact_occurrences o "
        "          join fact_revisions r on r.store_id = o.store_id "
        "            and r.fact_revision_id = o.fact_revision_id "
        "          where o.store_id = $1 and r.fact_id = k.fact_id and o.source_id <> $2 "
        "            and o.disposition = 'REVIEW_PENDING' and o.reason = 'INTAKE_NOTICE'"
        "  ) as notice_pending, "
        "  exists (select 1 from fact_occurrences o "
        "          join fact_revisions r on r.store_id = o.store_id "
        "            and r.fact_revision_id = o.fact_revision_id "
        "          where o.store_id = $1 and r.fact_id = k.fact_id and o.source_id <> $2 "
        "            and (o.disposition = 'LINKED' or (o.disposition = 'REVIEW_PENDING' "
        "                 and o.reason is distinct from 'INTAKE_NOTICE'))"
        "  ) as other_occurrence, "
        "  (exists (select 1 from fact_owner_answer_links a "
        "           where a.store_id = $1 and a.fact_id = k.fact_id) "
        "   or exists (select 1 from fact_revision_meta m "
        "              where m.store_id = $1 and m.fact_id = k.fact_id "
        "                and m.change_kind in ('OWNER_CORRECTION', 'OWNER_ANSWER'))"
        "  ) as owner_support, "
        "  exists (select 1 from source_fact_revision_links l "
        "          join source_facts sf on sf.store_id = l.store_id "
        "            and sf.fact_id = l.source_fact_id "
        "          where l.store_id = $1 and l.fact_id = k.fact_id and sf.source_id = $2"
        "  ) as in_current "
        "from knowledge_facts k where k.store_id = $1 and k.fact_id = any($3::bigint[])",
        store_id, source_id, ids)
    return store_notice_holds_of(rows, notice_fact_ids)


def store_notice_holds_of(rows, notice_fact_ids: frozenset[int]) -> frozenset[int]:
    """매장 전체 보류 판정. 순수 함수.

    보류 = 다른 자료에 INTAKE_NOTICE 검수 대기 occurrence 가 있고, 공지 아닌 받침이 하나도 없다.
    공지 아닌 받침은 다른 자료의 LINKED·다른 사유 검수 대기 occurrence, 점주 출처(답변·정정),
    이 자료의 공지 범위 밖 occurrence 다. 점주가 제외(EXCLUDED)한 occurrence 는 받침이 아니다.
    """
    held: set[int] = set()
    for r in rows:
        fid = int(r["fact_id"])
        if not r["notice_pending"] or r["other_occurrence"] or r["owner_support"]:
            continue
        if r["in_current"] and fid not in notice_fact_ids:
            continue  # 이 자료가 공지 밖에서 같은 사실을 말한다
        held.add(fid)
    return frozenset(held)


def _ctx_for(base: tuple | None, source_id: int, stage: str,
             segment_id: str | None = None):
    """usage_base 가 없으면 계측하지 않는다 (기존 호출 경로 호환)."""
    if base is None:
        return None
    store_id, job_id, phase, purpose, run_id, run_tag = base
    return _usage_context(store_id, source_id, job_id, stage, phase, purpose,
                          run_id, segment_id=segment_id, run_tag=run_tag)




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
, *, usage_sink=None, usage_context=None, cache=None
) -> tuple[str, list[Path], list[tuple[str, list[Path]]]]:
    """자료 유형별 전처리.

    반환값은 (추출기에 넣을 텍스트, 모델에 함께 보낼 파일들).
    두 번째 값은 영상 프레임이나 스캔 이미지처럼 텍스트로 못 담는 근거다.

    `cache`(입구 분류의 IntakeCache)를 주면 훑기에서 받은 파일·읽은 결과를 다시 쓰고,
    글만 낸 경우 구간 글(`cache.sections`)을 채운다.
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
                         usage_sink=usage_sink, usage_context=usage_context, cache=cache)


async def _download(pool: asyncpg.Pool, store_id: int,
                    src: asyncpg.Record, cache=None) -> Path:
    """원본을 받고, 프론트가 안 보낸 content_hash 를 채운다.

    내려받는 동안은 연결을 쥐지 않는다. 해시 기록만큼만 빌린다.
    `cache.path` 가 있으면 다시 받지 않고, 받으면 거기에 둔다(입구 분류 훑기와 공유).
    """
    if cache is not None and cache.path is not None:
        return cache.path
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
    if cache is not None:
        cache.path = path
    return path


async def _fetch(pool: asyncpg.Pool, store_id: int, src: asyncpg.Record, cache) -> Path:
    """캐시가 있을 때만 캐시를 넘긴다(캐시 없는 기존 호출 경로·대역과 같은 호출)."""
    if cache is None:
        return await _download(pool, store_id, src)
    return await _download(pool, store_id, src, cache=cache)


async def _preprocess_video(
    pool: asyncpg.Pool, store_id: int, src: asyncpg.Record
, *, usage_sink=None, usage_context=None, cache=None
) -> tuple[str, list[Path], list[tuple[str, list[Path]]]]:
    """영상: 오디오 전사 + 프레임 추출. 프레임은 Storage 에 올리고 근거로 남긴다."""
    from app.config import get_settings

    source_id = src["source_id"]
    async with pool.acquire() as conn:
        row = await repo.get_video(conn, source_id)
    if row is None:
        raise RuntimeError("source_video 행이 없다. /ingest/sources 로 등록했는지 확인하라")

    path = await _fetch(pool, store_id, src, cache)
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
    segments = (video.split_by_time(stt_segments, frames, window,
                                    overlap_sec=get_settings().video_segment_overlap_sec)
                if window > 0 else [])
    if segments:
        logger.info("영상 %d초 창으로 %d구간 분할 source=%s", window, len(segments), source_id)
    return text, video.sample_for_model(frames), segments


async def _preprocess_kakao(
    pool: asyncpg.Pool, store_id: int, src: asyncpg.Record
, *, usage_sink=None, usage_context=None, cache=None
) -> tuple[str, list[Path], list[tuple[str, list[Path]]]]:
    """카톡: txt 를 파싱한다. LLM 을 쓰지 않는다."""
    source_id = src["source_id"]
    async with pool.acquire() as conn:
        kakao_row = await repo.get_kakao(conn, source_id)
    if kakao_row is None:
        raise RuntimeError("source_kakao 행이 없다. /ingest/sources 로 등록했는지 확인하라")

    path = await _fetch(pool, store_id, src, cache)

    # 캡처 이미지는 파싱할 텍스트가 없다. 모델이 그림째 읽는다 (import_type SCREENSHOT)
    if path.suffix.lower() in {".png", ".jpg", ".jpeg"}:
        async with pool.acquire() as conn:
            await repo.update_kakao_result(
                conn, source_id, room_name=None, message_count=0, participant_cnt=0,
                period_start=None, period_end=None, parsed_text="",
            )
        return "(카카오톡 대화 캡처. 첨부한 그림을 읽고 판단할 것)", [path], []

    from app.config import get_settings

    raw = path.read_text(encoding="utf-8", errors="replace")
    # 번호 표지는 W1-4 플래그를 켰을 때만. 끄면 이전과 같은 글이다
    parsed = kakao.parse(
        raw, message_numbers=bool(getattr(get_settings(), "extract_locator_hints", False)))

    async with pool.acquire() as conn:
        await repo.update_kakao_result(
            conn, source_id,
            room_name=parsed["room_name"],
            message_count=parsed["message_count"],
            participant_cnt=len(parsed["participants"]),
            period_start=parsed["period_start"], period_end=parsed["period_end"],
            parsed_text=parsed["parsed_text"],
        )
    if cache is not None:
        # 파싱은 모델 없는 순수 함수라 훑기와 같은 글이 나온다. 방 이름 등 메타데이터가
        # 필요해 여기서 다시 파싱한다
        from app.ingest.intake import grouping, registry
        cache.chat_text = parsed["parsed_text"]
        groups = grouping.group_chat(parsed["parsed_text"],
                                     max_sections=get_settings().intake_max_sections)
        cache.sections = grouping.sections_text(groups, registry.JOINER["CHAT"])
    return parsed["parsed_text"], [], []


async def _preprocess_scan(
    pool: asyncpg.Pool, store_id: int, src: asyncpg.Record
, *, usage_sink=None, usage_context=None, cache=None
) -> tuple[str, list[Path], list[tuple[str, list[Path]]]]:
    """문서·이미지: PDF 는 텍스트 레이어를 먼저 읽고, 없으면 모델에 그림째 넘긴다."""
    source_id = src["source_id"]
    async with pool.acquire() as conn:
        row = await repo.get_scan(conn, source_id)
    if row is None:
        raise RuntimeError("source_scan 행이 없다. /ingest/sources 로 등록했는지 확인하라")

    path = await _fetch(pool, store_id, src, cache)

    if path.suffix.lower() == ".docx":
        from app.ingest.preprocess import docx
        # UnsupportedDocument → process_source 가 FAILED 로 적는다
        read = cache.docx if cache is not None and cache.docx is not None else docx.read_docx(path)
        text = docx.to_text(read)
        if read.skipped_images:
            logger.info("docx 그림 %d개는 읽지 않았다 source=%s", read.skipped_images, source_id)
        async with pool.acquire() as conn:
            await repo.update_scan_result(conn, source_id, page_count=1,
                                          ocr_text=text or None, ocr_engine="docx")
        if not text:
            raise docx.UnsupportedDocument("docx 에 읽을 글이 없다")
        if cache is not None:
            from app.config import get_settings as _settings
            from app.ingest.intake import grouping, registry
            cache.docx = read
            groups = grouping.group_docx(read, max_sections=_settings().intake_max_sections,
                                         min_chars=_settings().intake_min_section_chars)
            cache.sections = grouping.sections_text(groups, registry.JOINER["DOC_TEXT"])
        return text, [], []

    from app.config import get_settings as _gs
    if getattr(_gs(), "scan_extract_mode", "SINGLE") == "LAYOUT":
        # 구역 경로는 원본 파일만 받는다. 텍스트 레이어·HYBRID 판단은 하지 않는다
        pages = document.pdf_page_count(path) if path.suffix.lower() == ".pdf" else 1
        async with pool.acquire() as conn:
            await repo.update_scan_result(conn, source_id, page_count=pages,
                                          ocr_text=None, ocr_engine="layout")
        return "", [path], []

    if path.suffix.lower() == ".pdf":
        from app.config import get_settings

        if cache is not None:
            # 입구 분류 훑기가 읽은 쪽별 결과를 다시 쓴다
            if cache.pdf is None:
                cache.pdf = document.pdf_pages(path)
            read = document.pdf_read_of(cache.pdf)
        else:
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

        # TEXT — 대조군. 글로 읽힌 것만 쓴다. 글만 냈으므로 구간 글을 남긴다
        if cache is not None:
            from app.ingest.intake import grouping, registry
            groups = grouping.group_pdf_pages(
                cache.pdf.blocks, max_sections=get_settings().intake_max_sections)
            cache.sections = grouping.sections_text(groups, registry.JOINER["DOC_TEXT"])
        return read.text, [], []

    async with pool.acquire() as conn:
        await repo.update_scan_result(conn, source_id, page_count=1,
                                      ocr_text=None, ocr_engine=None)
    return "(이미지 자료. 첨부한 그림을 읽고 판단할 것)", [path], []


async def _preprocess_voice(
    pool: asyncpg.Pool, store_id: int, src: asyncpg.Record
, *, usage_sink=None, usage_context=None, cache=None
) -> tuple[str, list[Path], list[tuple[str, list[Path]]]]:
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

    path = await _fetch(pool, store_id, src, cache)
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
    # 구간 → 원래 응답 행 (W1-1). 구간 없는 자료는 키가 None 이다.
    # 기본값은 None 이다 — NamedTuple 기본값은 모든 인스턴스가 한 객체를 공유하므로
    # 가변 dict 를 두지 않는다. None 은 "모른다"(복구본·대역)이고 호출부는 빈 것으로 읽는다
    raw_response_ids: dict[str | None, int] | None = None


async def _extract_facts_all(
    *, source_id: int, source_type: str, text: str, media: list[Path],
    glossary: list[dict], segments: list[tuple[str, list[Path]]],
    usage_sink=None, usage_base: tuple | None = None,
    raw_sink=None,
    checkpoint=None,
    only_segments: set[str] | None = None,
    prefetched=None,
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

    `prefetched`(FactExtractionResult) 를 주면 구간 없는 자료의 첫 호출 대신 그 결과를 쓴다 —
    한 호출(S3)이 이미 뽑았다. 서버 검사·원장 적기는 보통 첫 호출 결과와 같은 길로 간다.
    """
    from app.config import get_settings
    from app.ingest.extract import extract_facts

    settings = get_settings()
    max_depth = settings.extract_truncation_split_max_depth
    # W1-4 — 끄면 모델이 준 쪽·메시지 번호를 보지 않는다(스키마에도 없다)
    hints = bool(getattr(settings, "extract_locator_hints", False))
    # W1-4 최종 수정 — 끄면(기본) 근거 없는 단위·규격을 비우지 않고 판정만 남긴다
    clear_ungrounded = bool(getattr(settings, "extract_clear_ungrounded_values", False))

    def _tag(items, prefix: str | None, segment: str | None):
        # prefix 는 하위 경로까지 붙은 이름(seg3.2), segment 는 부모 구간(seg3)이다
        for a in items:
            if prefix:
                a.local_ref = f"{prefix}:{a.local_ref}"
                a.requires = [f"{prefix}:{r}" for r in a.requires]
            a.segment_id = segment
        return items

    async def _extract_part(part_text, part_media, segment):
        """구간 하나를 뽑는다. 잘리면 반으로 나눠 다시 뽑는다 (W1-2).

        [(하위 경로 이름, 결과)] 를 돌려준다. 하나라도 끝내 잘리면 `TruncatedOutputError`
        를 올린다 — 반쪽만 건진 결과는 쓰지 않는다. PARTIAL 재시도가 구간 전체를 다시
        뽑으므로, 반쪽을 원장에 적으면 재시도 때 겹친다.
        """
        return await _extract_with_split(
            part_text, part_media, segment=segment, path="", depth=0,
            max_depth=max_depth,
            call=lambda text, media, label: extract_facts(
                source_id=source_id, source_type=source_type, text=text,
                glossary=glossary, media=media, usage_sink=usage_sink,
                usage_context=_ctx_for(usage_base, source_id, "EXTRACT", segment_id=label),
                raw_sink=raw_sink,
            ))

    def _collect(parts, segment, part_text, part_media):
        """하위 결과를 합치고 서버 검사(W1-4)를 한다. 원장에 적기 **전에** 부른다.

        검사는 그 구간 입력 글을 근거로 한다. 사실마다 나온 원래 응답 행을 붙인다 —
        근거 위치(occurrence)가 그 행을 가리킨다.
        """
        assertions, unresolved, raw_ids = [], [], {}
        for label, result in parts:
            raw_id = _raw_id_of(result)
            for a in _tag(result.assertions, label, segment):
                a._raw_response_id = raw_id
                assertions.append(a)
            unresolved.extend(result.unresolved)
            raw_ids[label] = raw_id
        unresolved.extend(occurrences.validate_assertions(
            assertions, source_type=source_type, text=part_text, media=list(part_media or []),
            locator_hints=hints, clear_ungrounded=clear_ungrounded))
        return assertions, unresolved, raw_ids

    if not segments:
        if only_segments is not None:
            # 호출부가 구간 구성을 먼저 확인한다. 여기 오면 자료 전체를 다시 뽑아 카드가 겹친다
            raise RuntimeError("구간 없는 자료는 잃은 구간만 다시 뽑을 수 없다")
        # 구간 없는 자료가 끝내 잘리면 잃은 구간으로 남길 곳이 없다 — 예외로 멈춘다(FAILED)
        if prefetched is not None:
            # 한 호출이 이미 뽑았다 — 같은 입력을 다시 부르지 않는다
            parts = [(None, prefetched)]
        else:
            parts = await _extract_part(text, media, None)
        tagged, unresolved, raw_ids = _collect(parts, None, text, media)
        if checkpoint is not None:
            await checkpoint(tagged, None)
        return ExtractionOutcome(tagged, unresolved, 1, 0, [], _raw_ids(raw_ids))

    async def _one_segment(index, seg_text, seg_media):
        """구간 하나를 뽑고 바로 원장에 적는다. (사실, 미해결, 원래 응답 ID) 또는 None(잃음)."""
        segment = f"seg{index}"
        try:
            parts = await _extract_part(seg_text, seg_media, segment)
        except Exception as exc:
            logger.warning("구간 %d/%d 사실 추출 실패 source=%s: %s",
                           index, len(segments), source_id, exc)
            return None
        tagged, part_unresolved, part_raw = _collect(parts, segment, seg_text, seg_media)
        if checkpoint is not None:
            # 뽑은 즉시 적는다. 적지 못하면 그 구간은 잃은 것으로 센다
            try:
                await checkpoint(tagged, segment)
            except Exception as exc:
                logger.warning("구간 %d/%d 원장 저장 실패 source=%s: %s",
                               index, len(segments), source_id, exc)
                return None
        logger.info("구간 %d/%d 사실 %d건", index, len(segments), len(tagged))
        return tagged, part_unresolved, part_raw

    todo = [(index, seg_text, seg_media)
            for index, (seg_text, seg_media) in enumerate(segments, start=1)
            if only_segments is None or f"seg{index}" in only_segments]
    concurrency = settings.extract_segment_concurrency
    if concurrency <= 1:
        # 기존 동작 — 앞 구간부터 차례대로
        results = [await _one_segment(*item) for item in todo]
    else:
        gate = asyncio.Semaphore(concurrency)

        async def _gated(item):
            async with gate:
                return await _one_segment(*item)
        results = await asyncio.gather(*(_gated(item) for item in todo))

    # 동시에 돌려도 합치는 순서는 구간 번호 순이다
    merged, unresolved, failed_ids = [], [], []
    raw_ids: dict[str | None, int | None] = {}
    for (index, _, _), got in zip(todo, results):
        if got is None:
            failed_ids.append(f"seg{index}")
            continue
        tagged, part_unresolved, part_raw = got
        merged.extend(tagged)
        unresolved.extend(part_unresolved)
        raw_ids.update(part_raw)

    failed = len(failed_ids)
    if only_segments is not None:
        if failed:
            logger.warning("재시도 구간 %d/%d 다시 실패 source=%s",
                           failed, len(only_segments), source_id)
        return ExtractionOutcome(merged, unresolved, len(segments), failed, failed_ids,
                                 _raw_ids(raw_ids))
    if failed == len(segments):
        raise RuntimeError(f"모든 구간({failed}개) 사실 추출이 실패했다")
    if failed:
        logger.warning("구간 %d/%d 실패 — 나머지로 진행한다", failed, len(segments))
    return ExtractionOutcome(merged, unresolved, len(segments), failed, failed_ids,
                             _raw_ids(raw_ids))


# 구간 없는 자료를 나눌 때 하위 경로 앞에 붙이는 이름. `whole.1:f1` 처럼 쓴다
_WHOLE_SOURCE_LABEL = "whole"


def _sub_label(segment: str | None, path: str) -> str | None:
    """하위 경로 이름. seg3 + '2.1' → seg3.2.1, 구간 없음 + '1' → whole.1, 나누지 않았으면 그대로."""
    if not path:
        return segment
    return f"{segment or _WHOLE_SOURCE_LABEL}.{path}"


async def _extract_with_split(text, media, *, segment, path, depth,
                              max_depth, call):
    """잘리면 반으로 나눠 다시 뽑는다. 깊이 상한·더 못 나눔이면 `TruncatedOutputError`.

    잘림은 호출 예외가 아니다 — `_call` 의 재시도가 같은 입력을 되풀이하지 않는다.
    나누기는 여기(호출 위)에서만 한다. 한 반쪽이 끝내 잘리면 나머지는 부르지 않는다.
    """
    from app.ingest.raw_responses import TruncatedOutputError

    label = _sub_label(segment, path)
    try:
        return [(label, await call(text, media, label))]
    except TruncatedOutputError as exc:
        where = label or "자료 전체"
        if depth >= max_depth:
            raise TruncatedOutputError(
                f"{where} 출력이 잘렸고 분할 깊이 상한({max_depth})에 닿았다: {exc}") from exc
        halves = _split_input(text, media)
        if halves is None:
            raise TruncatedOutputError(
                f"{where} 출력이 잘렸고 더 나눌 수 없다: {exc}") from exc
        logger.warning("%s 출력 잘림 — 반으로 나눠 다시 뽑는다 (깊이 %d/%d)",
                       where, depth + 1, max_depth)
        parts = []
        for i, (half_text, half_media) in enumerate(halves, start=1):
            parts.extend(await _extract_with_split(
                half_text, half_media, segment=segment,
                path=f"{path}.{i}" if path else str(i), depth=depth + 1,
                max_depth=max_depth, call=call))
        return parts


def _split_input(text: str, media: list[Path]):
    """입력을 앞/뒤 반으로 나눈다. 더 나눌 수 없으면 None.

    - 글은 줄 경계에서 반으로 나눈다(앞쪽이 짧거나 같다).
    - 첨부 목록(영상 프레임 등)은 앞/뒤 반씩 나눈다.
    - 첨부가 하나(문서·캡처 한 장)면 나누지 않는다 — 글만 나눠도 그 첨부가 매번
      통째로 들어가 출력이 줄지 않는다.
    - 글이 한 줄이고 첨부가 둘 이상이면 글은 양쪽에 그대로 두고 첨부만 나눈다.
    """
    media = list(media or [])
    if len(media) == 1:
        return None
    lines = (text or "").splitlines()
    text_halves = None
    if len(lines) >= 2:
        mid = len(lines) // 2
        text_halves = ("\n".join(lines[:mid]), "\n".join(lines[mid:]))
    media_halves = None
    if len(media) >= 2:
        mid = len(media) // 2
        media_halves = (media[:mid], media[mid:])
    if text_halves is None and media_halves is None:
        return None
    text_halves = text_halves or (text, text)
    media_halves = media_halves or ([], [])
    return [(text_halves[0], media_halves[0]), (text_halves[1], media_halves[1])]


def _raw_id_of(result) -> int | None:
    """추출 결과에 붙은 원래 응답 행. 대역(fake)이 돌려준 결과에는 없을 수 있다."""
    return getattr(result, "raw_response_id", None)


def _raw_ids(ids: dict) -> dict:
    """기록하지 않은 구간(None 값)은 뺀다."""
    return {k: v for k, v in ids.items() if v is not None}


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


def _is_layout_fact(a) -> bool:
    return bool(getattr(a, "_layout_locator", None))


def _layout_extract_version(s) -> str:
    # source_facts.extract_version 은 varchar(120)
    return f"layout:{s.layout_transcribe_model}+{s.layout_expand_model}/{s.ingest_mode}"[:120]


def _locator_of(source_type: str, a, *, hints: bool) -> tuple[str, dict]:
    """사실 하나의 근거 위치. 원장(source_facts)과 근거 위치(occurrence)가 같은 값을 쓴다.

    구역 추출 사실은 쪽·구역·좌표(·행)를 PAGE 위치로 남긴다. 그 밖에는 기존 규칙 —
    영상·음성은 시각, 문서는 쪽, 카톡은 메시지 번호. 쓸 번호가 없으면(서버 검사가 지운
    것 포함) 자료 전체다.
    """
    layout_loc = getattr(a, "_layout_locator", None)
    if layout_loc:
        return "PAGE", dict(layout_loc)
    return occurrences.locator_for(source_type, a.evidence, locator_hints=hints)


async def _persist_ledger(
    conn: asyncpg.Connection, store_id: int, source_id: int, source_type: str,
    assertions: list,
) -> dict[str, int]:
    """뽑은 사실을 **조립 전에** 전부 원장에 적는다 (W1).

    {local_ref: fact_id} 를 돌려준다. 조립이 고른 사실을 원장 행에 잇는 열쇠다.

    근거 위치(W1-4)도 같은 트랜잭션에서 사실마다 하나씩 남긴다. 같은 사실이 두 자리에
    나오면 원장은 한 행(처음 위치), 위치는 두 행이다. 다시 돌려도 같은 자리는 늘지 않는다.

    여기서 적지 않으면 조립이 버린 사실은 어디에도 남지 않는다. 그러면 추출이
    못 뽑은 것과 조립이 버린 것이 같은 숫자로 합쳐져, 무엇을 고쳐야 할지 알 수 없다.
    """
    from app.config import get_settings

    if not assertions:
        return {}

    s = get_settings()
    # W3-0 §3-1 — HOT/ICE 가 함께 적힌 사실을 규격별 두 사실로 나눈다(D19).
    # 반환 열쇠도 갈라진 이름표다
    assertions = split_hot_ice(assertions)
    extract_version = f"{s.gemini_model}@t{s.extract_temperature}/{s.ingest_mode}"
    hints = bool(getattr(s, "extract_locator_hints", False))
    rows = []
    for a in assertions:
        locator_type, locator = _locator_of(source_type, a, hints=hints)
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
            "ext": getattr(a, "ext", None),
            # 구역 사실만 사실 단위 버전을 갖는다. None 이면 자료 단위 기본값(extract_version)
            "extract_version": _layout_extract_version(s) if _is_layout_fact(a) else None,
        })

    fact_ids = await repo.insert_source_facts(
        conn, store_id, source_id, rows,
        locator_type="WHOLE_SOURCE", locator={},
        extract_version=extract_version,
    )
    await occurrences.insert_occurrences(conn, store_id, [
        {"fact_id": fid, "segment_id": row["segment_id"], "local_ref": row["local_ref"],
         "locator_type": row["locator_type"], "locator": row["locator"],
         "raw_response_id": getattr(a, "raw_response_id", None),
         "check_flags": list(getattr(a, "check_flags", None) or [])}
        for a, row, fid in zip(assertions, rows, fact_ids)
    ])
    # W2-2 — 같은 트랜잭션에서 원장 사실을 대상·판·occurrence 로 잇는다
    from app.ingest import fact_ledger
    await fact_ledger.link_source_facts(conn, store_id, source_id, sorted(set(fact_ids)))
    return {a.local_ref: fid for a, fid in zip(assertions, fact_ids)}


# ── 대상 단위 사실 조립 ──────────────────────────────────────────────────

@dataclass(frozen=True)
class PreparedAssembly:
    entity_ids: tuple[int, ...]  # 이 자료가 건드린 살아 있는 대상(오름차순)
    states: dict[int, "EntityCardState"]  # 준비 때 상태
    groups: dict[int, "EntityGroup"]  # DEFER·REDRAFT 가 아닌 대상의 입력(사실 1개 이상)
    held: tuple["HeldFact", ...]
    data_errors: dict[int, str]  # check_group 코드
    planning: "PlanningOutcome"
    # 입구 분류가 보류한 지식 사실 — 이 자료에서 공지에만 나오고 다른 받침이 없다.
    # 조립·재초안에 넣지 않는다
    held_fact_ids: frozenset[int] = frozenset()
    # 이 자료에서 공지에만 나온 지식 사실 전부(held_fact_ids 포함). 이 자료의 그 occurrence 는
    # 어느 경로로도 LINKED 가 되지 않고 INTAKE_NOTICE 검수 대기로 남는다
    notice_fact_ids: frozenset[int] = frozenset()


async def _prepare_fact_assembly(pool, store_id: int, source_id: int, *, categories: list[str],
                                 glossary: list[dict], usage_sink, usage_base, raw_sink,
                                 strict: bool,
                                 held_fact_ids: Mapping[int, str] | None = None,
                                 notice_fact_ids: frozenset[int] | None = None
                                 ) -> PreparedAssembly:
    """조립 입력을 짧은 연결로 읽고 놓은 뒤, 연결 없이 사실 조립 모델을 부른다.

    DEFER 대상(수동·점주 초안·레거시 카드)과 REDRAFT 대상(공개 자동 사실 카드)은 입력을 읽지 않는다. 데이터 오류 묶음은
    모델에 보내지 않는다. 사용량 문맥은 배치마다 `plan{n}` 이다(배치가 하나여도 plan0).

    `held_fact_ids`({지식 사실 ID: 사유}) 는 이 자료에서 공지에만 나오고 다른 받침이 없는
    사실이다. 묶음에서 빼고(사실이 0개가 된 묶음은 버린다) HeldFact 로 held 에 더한다.
    `notice_fact_ids` 는 공지에만 나온 사실 전부다(다른 받침이 있으면 묶음에 남는다). 그 사유는
    저장 단계(_persist_fact_cards)가 대상 판정과 상관없이 단다.
    여기에 매장 전체 기준 공지 보류(`_store_notice_holds`)를 더해 같은 방식으로 뺀다.
    결과의 held_fact_ids 는 둘을 합친 것이라 저장 단계의 다시 읽기 비교도 같은 집합으로 거른다.
    """
    from app.ingest import card_plan, fact_assembly, fact_cards

    hold = dict(held_fact_ids or {})
    async with pool.acquire() as conn:
        entity_ids = tuple(await fact_assembly.entities_for_source(conn, store_id, source_id))
        states = {e: await fact_cards.entity_card_state(conn, store_id, e) for e in entity_ids}
        # REDRAFT 는 모델 없이 공개판에 새 사실만 붙이므로(A-D4) 입력을 읽지 않는다
        loaded = await fact_assembly.load_entity_groups(
            conn, store_id, [e for e in entity_ids if states[e].mode not in ("DEFER", "REDRAFT")])
        # 매장 전체 기준 공지 보류(최종 리뷰 I1) — 다른 자료의 공지에서만 나와 보류된 사실이
        # 이 자료의 조립(NEW·REASSEMBLE)에 head 로 섞이지 않게 한다. REDRAFT 는 이 자료의
        # 새 사실만 붙이므로 해당 없다
        candidates = {f.fact_id for g in loaded.groups for f in g.facts} | {
            h.fact_id for h in loaded.held}
        store_held = await _store_notice_holds(
            conn, store_id, source_id, sorted(candidates - set(hold)),
            frozenset(notice_fact_ids or ()))
    if store_held:
        hold.update({f: fact_cards.REASON_INTAKE_NOTICE for f in store_held})
        logger.info("매장 전체 공지 보류 source=%s 사실 %d건", source_id, len(store_held))
    # 여기부터 연결 없음 — 모델 호출 중 DB 연결을 쥐지 않는다
    groups = {g.entity_id: g for g in loaded.groups}
    held = list(loaded.held)
    if hold:
        from app.ingest.fact_assembly import HeldFact

        def as_held(rev: int, fid: int, eid: int) -> HeldFact:
            return HeldFact(rev, fid, eid, hold[fid])

        # 이미 빠진 판(규격 미해결 등)이 보류 사실이면 입구 보류 사유가 앞선다
        held = [h if h.fact_id not in hold else as_held(h.fact_revision_id, h.fact_id, h.entity_id)
                for h in held]
        for e, g in list(groups.items()):
            kept = tuple(f for f in g.facts if f.fact_id not in hold)
            if len(kept) == len(g.facts):
                continue
            held.extend(as_held(f.fact_revision_id, f.fact_id, e)
                        for f in g.facts if f.fact_id in hold)
            if kept:
                groups[e] = replace(g, facts=kept)
            else:
                del groups[e]  # 보류 사실뿐인 대상은 묶음을 버린다
    data_errors = {e: code for e, g in groups.items() if (code := card_plan.check_group(g))}
    planning = await fact_assembly.plan_entities(
        source_id=source_id,
        groups=[groups[e] for e in sorted(groups) if e not in data_errors],
        categories=categories, glossary=glossary, usage_sink=usage_sink,
        context_for=lambda i: _ctx_for(usage_base, source_id, "ASSEMBLE", segment_id=f"plan{i}"),
        raw_sink=raw_sink, strict=strict)
    return PreparedAssembly(entity_ids=entity_ids, states=states, groups=groups,
                            held=tuple(held), data_errors=data_errors, planning=planning,
                            held_fact_ids=frozenset(hold),
                            notice_fact_ids=frozenset(notice_fact_ids or ()) | frozenset(hold))


async def _persist_fact_cards(conn: asyncpg.Connection, store_id: int, source_id: int,
                              categories: dict[str, int], prepared: PreparedAssembly, *,
                              job_id: int | None, category_version: int) -> int:
    """사실 카드를 쓰고 이 자료의 occurrence 를 모두 처분한다. 호출자 트랜잭션 안에서 돈다.

    매장 지식 잠금을 잡은 뒤 대상마다 상태·입력을 다시 보고, 준비 뒤 달라졌으면 쓰지 않고
    구체적 사유로 검수 대기로 둔다. 처분 누락이 있으면 예외로 트랜잭션을 되돌린다.
    이번에 만든 카드 판 수를 돌려준다.
    """
    from app.ingest import card_plan, entities, fact_assembly, fact_cards

    await entities.lock_store_knowledge(conn, store_id)
    await fact_cards.record_unresolvable_occurrences(conn, store_id, source_id)

    planning = prepared.planning
    failed = set(planning.failed_entity_ids)
    created = 0
    # 이 자료에서 공지에만 나온 사실 — 어느 쓰기 경로도 이 자료의 그 occurrence 를 잇지 않는다
    notice = prepared.notice_fact_ids | prepared.held_fact_ids
    for e in prepared.entity_ids:
        now = await fact_cards.entity_card_state(conn, store_id, e)
        before = prepared.states[e]
        fact_ids = await fact_cards.entity_fact_ids(conn, store_id, e)
        if prepared.held_fact_ids and fact_ids and set(fact_ids) <= prepared.held_fact_ids:
            # 입구 분류가 보류한 사실만 가진 대상 — 판정과 상관없이 카드를 쓰지 않는다.
            # 아래 보류 처리가 사유(INTAKE_NOTICE)를 단다
            continue

        async def pending(reason: str) -> None:
            await fact_cards.mark_pending(conn, store_id, source_id=source_id,
                                          fact_ids=fact_ids, reason=reason)

        if now.mode == "DEFER":
            await pending(fact_cards.REASON_EXISTING_CARD if before.mode == "DEFER"
                          else fact_cards.REASON_CONCURRENT)
            continue
        if before.mode == "DEFER":
            # 지금은 풀렸지만 준비 때 입력을 읽지 않았다
            await pending(fact_cards.REASON_CONCURRENT)
            continue
        if now.mode == "REDRAFT" or before.mode == "REDRAFT":
            # 공개 카드에 새 사실만 붙인다(A-D4). 준비 뒤 판정이 바뀌었으면 쓰지 않는다
            if now.mode != before.mode:
                await pending(fact_cards.REASON_CONCURRENT)
                continue
            # 보류 사실은 새 초안에 붙이지 않고, 공지 occurrence 는 공개판 고정 사실이어도
            # 잇지 않는다. 보류가 없으면 기존 호출과 같다
            exclude = ({"exclude_fact_ids": prepared.held_fact_ids, "notice_fact_ids": notice}
                       if notice else {})
            written = await fact_cards.redraft_published_card(
                conn, store_id, source_id=source_id, state=now, **exclude)
            if written.deferred_reason is None:
                created += len(written.new_version_ids)
            continue
        if e in prepared.data_errors:
            await pending(prepared.data_errors[e])
            continue
        if e in failed:
            await pending(fact_cards.REASON_ASSEMBLY_FAILED)
            continue
        group = prepared.groups.get(e)
        if group is None:
            continue  # 모든 사실이 보류 — 아래 보류 처리가 사유를 단다
        reloaded = await fact_assembly.load_entity_groups(conn, store_id, [e])
        # 준비 때 보류 사실을 뺐으므로 다시 읽은 묶음에서도 빼고 비교한다
        current = {f.fact_revision_id for g in reloaded.groups if g.entity_id == e
                   for f in g.facts if f.fact_id not in prepared.held_fact_ids}
        if current != {f.fact_revision_id for f in group.facts}:
            await pending(fact_cards.REASON_STALE_INPUT)
            continue
        result = card_plan.plan_entity(group, planning.proposals.get(e, ()))
        if result.pending_reason:
            await pending(result.pending_reason)
            continue
        if result.model_error:
            logger.warning("W3a 모델 계획 버림 source=%s 대상 %s %s — 대체 계획",
                           source_id, e, result.model_error)
        # 지금 상태를 넘긴다 — 준비 때 NEW 였어도 지금 REASSEMBLE 이면 재조립한다
        written = await fact_cards.write_entity_cards(
            conn, store_id, source_id=source_id, job_id=job_id,
            category_version=category_version, categories=categories, state=now,
            group=group, result=result, **({"notice_fact_ids": notice} if notice else {}))
        if written.deferred_reason:
            # 잠금 아래 다시 본 상태가 달라 쓰지 않았다(occurrence 사유는 쓰기 쪽이 달았다)
            logger.info("W3a 카드 쓰기 보류 source=%s 대상 %s %s",
                        source_id, e, written.deferred_reason)
            continue
        created += len(written.new_version_ids)

    # 대상 단위 사유 뒤에 단다 — 더 구체적인 보류 사유가 덮이지 않게
    for h in prepared.held:
        await fact_cards.mark_pending(conn, store_id, source_id=source_id,
                                      fact_ids=[h.fact_id], reason=h.reason)
    # 공지 보류는 대상 판정(DEFER·REDRAFT 포함)과 상관없이 단다. 위 held 로 이미 단 것은 빼고
    rest = sorted(notice - {h.fact_id for h in prepared.held})
    if rest:
        await fact_cards.mark_pending(conn, store_id, source_id=source_id, fact_ids=rest,
                                      reason=fact_cards.REASON_INTAKE_NOTICE)

    from app.ingest import impact
    await impact.record_upload_proposals(conn, store_id, source_id, job_id=job_id)

    counts = await fact_cards.disposition_counts(conn, store_id, source_id)
    if counts.missing > 0:
        raise RuntimeError(f"occurrence 처분 누락 {counts.missing}건 — 저장하지 않는다")
    logger.info("W3a 처분 source=%s 합계 %d · LINKED %d · 검수 대기 %s · 제외 %s",
                source_id, counts.total, counts.linked, counts.review_pending, counts.excluded)
    for item in planning.unresolved:
        logger.info("unresolved source=%s: %s", source_id, item)
    return created


def _to_percent(confidence: float) -> float:
    """0~1 로 받아 DB 에는 0~100 으로 저장한다 (numeric(5,2) CHECK)."""
    return round(max(0.0, min(1.0, float(confidence))) * 100, 2)
