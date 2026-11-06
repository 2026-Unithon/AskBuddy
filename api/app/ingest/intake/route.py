"""업로드 자료의 입구 분류 단계(Phase B Task 9) — 정규화기 판단·훑기·분류·판정 기록.

`process_source` 가 전처리 **앞에서** 부른다. 같은 자료의 최신 판정이 있으면 그대로 쓴다 —
재시도·PARTIAL 재시도·복구에서 분류를 다시 부르지 않아 구간 구성이 지난 실행과 같다.

모듈은 속성으로 들여온다(테스트가 `records.*`·`classify.classify`·`get_settings` 를 patch 한다).
pipeline 은 이 모듈을 들여오므로, 여기서는 함수 안에서 pipeline 을 들여온다(순환 import).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Sequence

from app.config import get_settings
from app.ingest import capabilities
from app.ingest import repository as repo
from app.ingest.intake import classify, records, registry
from app.ingest.intake.classify import ClassifyOutcome
from app.ingest.intake.decide import (IntakeClassificationError, Ranked, Thresholds,
                                      decide_all, override_logic, owner_override,
                                      source_decision)
from app.ingest.intake.ir import Candidate, Locator, ProbeResult
from app.ingest.intake.records import StoredRoute
from app.ingest.schemas import FactExtractionResult
from app.ingest.preprocess.docx import DocxRead
from app.ingest.preprocess.document import PdfPages

logger = logging.getLogger(__name__)

# mock 모드에서 확장자를 모를 때 쓰는 입력 종류별 기본 정규화기. real 모드는 그대로 실패한다
_MOCK_DEFAULT_NORMALIZER = {"SCAN": "DOC_TEXT", "KAKAO": "CHAT", "VOICE": "AUDIO",
                            "VIDEO": "VIDEO"}


@dataclass
class IntakeCache:
    """훑기와 전처리가 함께 쓰는 읽기 결과. 다운로드·PDF 글자 층·docx·카톡 파싱을 한 번만 한다.

    `sections` 는 전처리가 글만 냈을 때만 전처리 핸들러가 채운다(구간별 추출 입력).
    """
    path: Path | None = None
    pdf: PdfPages | None = None
    docx: DocxRead | None = None
    chat_text: str | None = None
    sections: dict[str, str] | None = None


def full_sections(cache: IntakeCache, normalizer: str) -> dict[str, str] | None:
    return cache.sections if normalizer in registry.SECTIONED_NORMALIZERS else None


@dataclass(frozen=True)
class SingleCallPending:
    """작은 자료 — 분류를 부르지 않았다. 본 추출 한 호출이 판정을 함께 낸다(S3)."""
    probe: ProbeResult
    hints: tuple[str, ...]


@dataclass(frozen=True)
class SingleCallResult:
    """한 호출의 결과 — 저장한 판정과 이미 뽑은 사실."""
    route: StoredRoute
    result: FactExtractionResult  # 또는 Located 변형


# 한 호출의 원장 하위 이름. 잘려서 보통 추출로 돌아갈 때 그 호출(`…:extract`)과
# 논리 호출 ID 가 겹치면 원장 unique(store_id, logical_call_id, attempt_no)에 걸린다
SINGLE_CALL_SEGMENT = "single"


async def route_source(pool, store_id: int, src, *, cache: IntakeCache, usage_sink,
                       usage_base: tuple | None) -> StoredRoute | SingleCallPending:
    """자료의 판정. 최신 판정이 있으면 분류 0회로 돌려준다. 없으면 훑고 분류해 저장한다.

    스위치(`intake_single_call_small`)가 켜져 있고 작은 자료(훑기가 내용 전체를 담음)면
    분류하지 않고 `SingleCallPending` 을 돌려준다 — process_source 가 추출 한 호출로
    판정까지 받는다. 저장된 판정이 있으면(재시도·복구) 늘 그 판정을 쓴다.

    분류 실패(모델 오류·JSON·후보 누락)는 IntakeClassificationError 로 올라가
    process_source 가 FAILED 로 멈춘다 — 조용히 다른 로직으로 보내지 않는다.
    """
    source_id = src["source_id"]
    async with pool.acquire() as conn:
        stored = await records.latest_decision(conn, store_id, source_id)
        if stored is not None:
            logger.info("입구 판정 재사용 source=%s decision=%s", source_id, stored.decision_id)
            return stored
        hints = await records.source_owner_hints(conn, store_id, source_id)

    # 여기부터 연결 없음 — 다운로드·STT·분류 모델 호출 중 DB 연결을 쥐지 않는다
    probe = await probe_source(pool, store_id, src, cache=cache, usage_sink=usage_sink,
                               usage_base=usage_base)
    if single_call_eligible(probe, get_settings()):
        # 작은 자료 — 여기서는 분류하지 않고 본 추출 한 호출로 판정을 함께 받는다(S3)
        logger.info("입구 한 호출 대상 source=%s 정규화기 %s", source_id, probe.normalizer)
        return SingleCallPending(probe, tuple(hints or ()))
    return await classify_and_save(pool, store_id, src, probe, hints=hints,
                                   usage_sink=usage_sink, usage_base=usage_base)


async def classify_and_save(pool, store_id: int, src, probe: ProbeResult, *, hints,
                            usage_sink, usage_base: tuple | None) -> StoredRoute:
    """훑은 자료를 분류 1회로 판정하고 저장한다. 모델 호출 중에는 DB 연결을 쥐지 않는다."""
    from app.ingest import pipeline

    source_id = src["source_id"]
    ctx = pipeline._ctx_for(usage_base, source_id, "CLASSIFY")
    outcome = await classify.classify([probe], hints=hints, context=None,
                                      usage_sink=usage_sink, usage_context=ctx)
    th = Thresholds.from_settings(get_settings())
    registered = registry.registered_logics()
    decisions = decide_all(probe.candidates, outcome.model_sections, hints=hints, th=th,
                           registered=registered)
    source = source_decision(decisions, hints=hints, th=th, registered=registered)

    async with pool.acquire() as conn:
        decision_id = await records.save_decision(
            conn, store_id, source_id=source_id, entry="UPLOAD", owner_answer_id=None,
            probe=probe, owner_hints=hints, outcome=outcome, decisions=decisions,
            source=source, logical_call_id=ctx.logical_call_id if ctx else None)
    logger.info("입구 판정 source=%s 정규화기 %s 자료 로직 %s 구간 %d",
                source_id, probe.normalizer, source.logic, len(decisions))
    return StoredRoute(decision_id, probe.normalizer, list(decisions), source)


def single_call_route(probe: ProbeResult, result, *, hints, model: str):
    """한 호출 결과의 자료 순위를 판정으로 바꾼다(순수).

    모든 후보에 같은 순위를 준다 — 재시도 때 저장 판정으로 구간 글이 그대로 이어지게.
    순위가 비면 IntakeClassificationError(로직을 추정해 보내지 않는다).
    """
    ranking = [Ranked(r.logic, r.score) for r in (getattr(result, "intake_ranking", None) or [])]
    if not ranking:
        raise IntakeClassificationError("한 호출 결과에 용도 판정이 없다")
    model_sections = {c.candidate_id: ranking for c in probe.candidates}
    th = Thresholds.from_settings(get_settings())
    registered = registry.registered_logics()
    # 한 호출은 자료 전체를 봤다 — 표본 밖 후보도 직접 판정한 것으로 둔다
    candidates = tuple(replace(c, sampled=True) for c in probe.candidates)
    decisions = decide_all(candidates, model_sections, hints=hints, th=th,
                           registered=registered)
    source = source_decision(decisions, hints=hints, th=th, registered=registered)
    raw = {"single_call": True,
           "intake_ranking": [[r.logic, r.score] for r in ranking],
           "intake_reason": getattr(result, "intake_reason", "") or ""}
    return decisions, source, ClassifyOutcome(model_sections, raw, model, "")


async def extract_with_intake(pool, store_id: int, src, pending: SingleCallPending, *, text,
                              media, glossary, usage_sink, usage_base: tuple | None,
                              raw_sink) -> SingleCallResult:
    """분류와 추출을 한 호출로(S3). 원장 문맥은 EXTRACT, 판정은 entry=UPLOAD 로 저장한다.

    출력이 잘리면 `TruncatedOutputError` 가 그대로 올라간다 — 호출부가 분류 후 보통 추출로 간다.
    순위가 비면 IntakeClassificationError 로 올라가고 판정은 저장하지 않는다.
    모델 호출 중에는 DB 연결을 쥐지 않는다. 연결은 저장할 때만 짧게 빌린다.
    """
    from app.ingest import extract, pipeline

    source_id = src["source_id"]
    ctx = pipeline._ctx_for(usage_base, source_id, "EXTRACT", segment_id=SINGLE_CALL_SEGMENT)
    result = await extract.extract_facts_with_intake(
        source_id=source_id, source_type=src["source_type"], text=text, glossary=glossary,
        media=media, hints=tuple(pending.hints), usage_sink=usage_sink, usage_context=ctx,
        raw_sink=raw_sink)
    decisions, source, outcome = single_call_route(
        pending.probe, result, hints=pending.hints, model=get_settings().gemini_model)
    async with pool.acquire() as conn:
        decision_id = await records.save_decision(
            conn, store_id, source_id=source_id, entry="UPLOAD", owner_answer_id=None,
            probe=pending.probe, owner_hints=pending.hints, outcome=outcome,
            decisions=decisions, source=source,
            logical_call_id=ctx.logical_call_id if ctx else None)
    logger.info("입구 한 호출 판정 source=%s 정규화기 %s 자료 로직 %s 사실 %d",
                source_id, pending.probe.normalizer, source.logic,
                len(getattr(result, "assertions", []) or []))
    return SingleCallResult(
        StoredRoute(decision_id, pending.probe.normalizer, list(decisions), source), result)


async def override_none_for_source(conn, store_id: int, source_id: int) -> int | None:
    """점주 "그래도 추출하기"(자료 하나)에서 자료 단위 NONE 판정을 덮은 판정을 남긴다(후속 1).

    분류를 다시 부르지 않는다. 덮는 로직은 `override_logic`(칩 첫째 → 저장된 순위의 NONE 다음
    → 등록 추출기 첫째)이 고르고, 그 근거를 판정 행에 남긴다. 작업은 늘 하던 대로 최신 판정을
    재사용하므로 그 판정으로 추출한다. 작업 재시도·자동 재시도·복구는 이 함수를 지나지 않아
    저장된 판정을 그대로 쓴다(Review Focus 2). 최신 판정이 NONE 이 아니면 None 을 돌려준다.
    호출자 트랜잭션 안에서 돈다(DB 만 친다).
    """
    stored = await records.latest_decision(conn, store_id, source_id)
    if stored is None or stored.source.logic != "NONE":
        return None
    hints = await records.source_owner_hints(conn, store_id, source_id)
    registered = registry.registered_logics()
    logic, basis = override_logic(stored.decisions, stored.source, hints=hints,
                                  registered=registered)
    decisions, source = owner_override(stored.decisions, stored.source, logic=logic,
                                       registered=registered)
    decision_id = await records.save_owner_override(
        conn, store_id, source_id=source_id, base=stored, owner_hints=hints,
        decisions=decisions, source=source, basis=basis)
    logger.info("입구 판정 점주 덮어쓰기 source=%s %s → %s(%s) decision=%s",
                source_id, stored.decision_id, logic, basis, decision_id)
    return decision_id


# 한 호출(분류+추출) 대상 정규화기 — 음성·영상은 이번 범위가 아니다(S4)
SINGLE_CALL_NORMALIZERS = frozenset({"DOC_TEXT", "CHAT", "DOC_IMAGE"})


def single_call_eligible(probe: ProbeResult, settings) -> bool:
    """작은 자료(훑기가 내용 전체를 담음)를 한 호출로 처리하는가. 스위치가 꺼져 있으면 늘 False."""
    if not getattr(settings, "intake_single_call_small", False):
        return False
    if not probe.complete or probe.normalizer not in SINGLE_CALL_NORMALIZERS:
        return False
    # 구역(LAYOUT) 스캔은 다단계 추출이라 한 호출로 합칠 수 없다
    if probe.normalizer == "DOC_IMAGE" and getattr(settings, "scan_extract_mode", "SINGLE") == "LAYOUT":
        return False
    return True


def _prefixed(source_id: int, probe: ProbeResult) -> ProbeResult:
    """묶음 분류용으로 후보 id 앞에 자료 접두어(`s{source_id}:`)를 붙인다."""
    return ProbeResult(probe.normalizer, tuple(
        replace(c, candidate_id=f"s{source_id}:{c.candidate_id}") for c in probe.candidates),
        complete=probe.complete)


def _split_outcome(outcome: ClassifyOutcome, source_id: int) -> ClassifyOutcome:
    """묶음 분류 결과에서 한 자료 몫만 골라 접두어를 뗀다. 저장된 판정의 후보 id 는 접두어가 없다."""
    prefix = f"s{source_id}:"
    sections = {k[len(prefix):]: v for k, v in outcome.model_sections.items()
                if k.startswith(prefix)}
    raw = dict(outcome.raw or {})
    if isinstance(raw.get("sections"), list):
        raw["sections"] = [
            {**sec, "candidate_id": sec["candidate_id"][len(prefix):]}
            for sec in raw["sections"]
            if isinstance(sec, dict) and str(sec.get("candidate_id", "")).startswith(prefix)]
    return ClassifyOutcome(sections, raw, outcome.model, outcome.prompt_digest)


async def _classify_bundle(pool, store_id: int,
                           items: Sequence[tuple[int, ProbeResult, tuple[str, ...]]], *,
                           context: str | None, global_hints: Sequence[str], usage_sink, ctx,
                           entry: str, owner_answer_id: int | None) -> dict[int, StoredRoute]:
    """여러 자료를 분류 1회로 판정한다. 후보 id 는 `s{source_id}:` 로 묶고, 결정은 자료마다
    그 자료의 칩만 가산한다. 모든 자료가 판정된 뒤 한 트랜잭션으로 저장한다(함께 남거나 함께 없다).
    분류 실패는 IntakeClassificationError 로 올라간다. 모델 호출 중에는 DB 연결을 쥐지 않는다."""
    candidate_hints = {f"s{sid}:{c.candidate_id}": hints
                       for sid, probe, hints in items if hints for c in probe.sampled()}
    outcome = await classify.classify(
        [_prefixed(sid, probe) for sid, probe, _ in items], hints=tuple(global_hints),
        context=context, usage_sink=usage_sink, usage_context=ctx,
        candidate_hints=candidate_hints or None)
    th = Thresholds.from_settings(get_settings())
    registered = registry.registered_logics()
    decided = []
    for sid, probe, hints in items:
        own = _split_outcome(outcome, sid)
        decisions = decide_all(probe.candidates, own.model_sections, hints=hints, th=th,
                               registered=registered)
        decided.append((sid, probe, hints, own, decisions,
                        source_decision(decisions, hints=hints, th=th, registered=registered)))
    routes: dict[int, StoredRoute] = {}
    async with pool.acquire() as conn, conn.transaction():
        for sid, probe, hints, own, decisions, source in decided:
            decision_id = await records.save_decision(
                conn, store_id, source_id=sid, entry=entry, owner_answer_id=owner_answer_id,
                probe=probe, owner_hints=hints, outcome=own, decisions=decisions, source=source,
                logical_call_id=ctx.logical_call_id if ctx else None)
            routes[sid] = StoredRoute(decision_id, probe.normalizer, list(decisions), source)
    return routes


def bundle_chunks(items: Sequence[tuple[int, ProbeResult, tuple[str, ...]]], *,
                  max_sources: int, max_chars: int,
                  max_images: int,
                  max_candidates: int) -> list[list[tuple[int, ProbeResult, tuple[str, ...]]]]:
    """순서를 지키며 상한(자료 수·글자·그림·표본 후보 수) 안에서 묶음을 나눈다(탐욕적).

    후보 수 상한은 묶음 분류 출력(후보마다 판정 한 줄)이 출력 토큰 상한에서 잘리지 않게 한다.

    자료 하나가 상한을 홀로 넘으면 그 자료만 한 묶음이 된다 — 1개짜리 묶음은 묶지 않는다.
    """
    chunks: list[list[tuple[int, ProbeResult, tuple[str, ...]]]] = []
    current: list[tuple[int, ProbeResult, tuple[str, ...]]] = []
    chars = images = cands = 0
    for item in items:
        summary = item[1].summary()
        c, i, k = summary["chars"], summary["images"], len(summary["sampled"])
        if current and (len(current) >= max_sources or chars + c > max_chars
                        or images + i > max_images or cands + k > max_candidates):
            chunks.append(current)
            current, chars, images, cands = [], 0, 0, 0
        current.append(item)
        chars += c
        images += i
        cands += k
    if current:
        chunks.append(current)
    return chunks


async def route_job_bundle(pool, store_id: int, *, job_id: int, source_ids: Sequence[int],
                           usage_sink, usage_base: tuple,
                           caches: dict[int, IntakeCache]) -> dict[int, StoredRoute]:
    """한 작업의 판정 없는 자료를 묶어 분류 1회(S1). 둘 미만이면 아무것도 하지 않는다.

    훑기 결과(다운로드·파싱)는 caches 에 둬 process_source 가 다시 쓴다. 훑기에 실패한 자료는
    묶음에서 빼고 경고만 남긴다(process_source 에서 지금처럼 실패한다). 묶음 분류가 실패하면
    그 묶음은 판정 없이 두고 경고만 남긴다 — process_source 가 자료마다 다시 분류한다
    (로직을 추정해 보내지 않는다). 작업은 멈추지 않는다(Review Focus 1).
    """
    from app.ingest import pipeline

    s = get_settings()
    if not s.intake_bundle_enabled:
        return {}
    pending: list[tuple[int, object, tuple[str, ...]]] = []
    async with pool.acquire() as conn:
        for sid in source_ids:
            if await records.latest_decision(conn, store_id, sid) is not None:
                continue
            row = await repo.get_source(conn, store_id, sid)
            if row is None:
                continue
            if row["source_type"] in ("VOICE", "VIDEO"):
                # 음성·영상은 묶지 않는다(S4) — 미리 내려받고 훑기 STT 를 내면 디스크·비용만
                # 늘고 아끼는 건 분류 한 번뿐이다. process_source 에서 지금처럼 따로 간다
                continue
            pending.append((sid, row, tuple(await records.source_owner_hints(conn, store_id,
                                                                             sid))))
    if len(pending) < 2:
        return {}

    # 여기부터 연결 없음 — 다운로드·STT·분류 모델 호출 중 DB 연결을 쥐지 않는다
    probed: list[tuple[int, ProbeResult, tuple[str, ...]]] = []
    for sid, row, hints in pending:
        try:
            probe = await probe_source(pool, store_id, row,
                                       cache=caches.setdefault(sid, IntakeCache()),
                                       usage_sink=usage_sink, usage_base=usage_base)
        except Exception as exc:
            logger.warning("묶음 훑기 실패 — 그 자료는 따로 처리한다 job=%s source=%s %s: %s",
                           job_id, sid, type(exc).__name__, exc)
            continue
        probed.append((sid, probe, hints))

    routes: dict[int, StoredRoute] = {}
    chunks = bundle_chunks(probed, max_sources=s.intake_bundle_max_sources,
                           max_chars=s.intake_bundle_max_chars,
                           max_images=s.intake_bundle_max_images,
                           max_candidates=s.intake_bundle_max_candidates)
    for n, chunk in enumerate(chunks, start=1):
        if len(chunk) < 2:
            continue
        ctx = pipeline._ctx_for(usage_base, chunk[0][0], "CLASSIFY", segment_id=f"bundle{n}")
        try:
            routes.update(await _classify_bundle(
                pool, store_id, chunk, context=None, global_hints=(), usage_sink=usage_sink,
                ctx=ctx, entry="UPLOAD", owner_answer_id=None))
        except Exception as exc:
            logger.warning("묶음 분류 실패 — 자료마다 다시 분류한다 job=%s sources=%s %s: %s",
                           job_id, [c[0] for c in chunk], type(exc).__name__, exc)
    logger.info("작업 묶음 분류 job=%s 대기 %d 훑기 %d 묶음 %d 판정 %d", job_id, len(pending),
                len(probed), sum(1 for c in chunks if len(c) >= 2), len(routes))
    return routes


async def route_owner_answer(pool, store_id: int, *, owner_answer_id: int, answer_source_id: int,
                             question: str, answer: str, attachment_source_ids: Sequence[int],
                             usage_sink, usage_base: tuple | None) -> dict[int, StoredRoute]:
    """점주 답변 = 답변 글 + 첨부 한 묶음의 판정(Phase B B-D1). source_id → 판정.

    자료마다 최신 판정이 있으면 그대로 쓴다. 판정이 없는 자료만 훑어 **한 번** 분류한다.
    후보 id 는 `s{source_id}:c{n}` 로 묶고, 결과를 자료별로 나눠 접두어를 뗀 뒤 저장한다 —
    첨부 작업의 `plan_extraction` 이 전처리 구간 id(`c1..`)와 맞춰야 하기 때문이다.
    칩은 첨부 자료 칩의 합집합, 맥락은 직원 질문, 원장 문맥은 답변 자료의 CLASSIFY 다.
    분류 실패는 IntakeClassificationError 로 올라간다(조용히 다른 로직으로 보내지 않는다).
    """
    from app.ingest import pipeline
    from app.ingest.intake import probe_text

    order = [answer_source_id] + [s for s in attachment_source_ids if s != answer_source_id]
    routes: dict[int, StoredRoute] = {}
    hints_of: dict[int, tuple[str, ...]] = {}
    rows: dict[int, object] = {}
    async with pool.acquire() as conn:
        for sid in order:
            stored = await records.latest_decision(conn, store_id, sid)
            if stored is not None:
                routes[sid] = stored
                continue
            hints_of[sid] = tuple(await records.source_owner_hints(conn, store_id, sid))
            if sid != answer_source_id:
                row = await repo.get_source(conn, store_id, sid)
                if row is None:
                    # 첨부 행이 사라졌다(다른 매장·삭제). 묶음에서 빼고 답변 처리는 이어간다
                    logger.warning("점주 답변 첨부 자료가 없다 store=%s source=%s", store_id, sid)
                    hints_of.pop(sid)
                    continue
                rows[sid] = row
    missing = [sid for sid in order if sid in hints_of]
    if not missing:
        logger.info("점주 답변 판정 재사용 answer=%s 자료 %d", owner_answer_id, len(routes))
        return routes

    # 여기부터 연결 없음 — 다운로드·STT·분류 모델 호출 중 DB 연결을 쥐지 않는다
    probes: dict[int, ProbeResult] = {}
    for sid in missing:
        if sid == answer_source_id:
            probes[sid] = probe_text.probe_owner_text(question, answer)
        else:
            probes[sid] = await probe_source(pool, store_id, rows[sid], cache=IntakeCache(),
                                             usage_sink=usage_sink, usage_base=usage_base)
    attachment_hints: list[str] = []
    for sid in attachment_source_ids:
        for h in hints_of.get(sid, ()):
            if h not in attachment_hints:
                attachment_hints.append(h)
    ctx = pipeline._ctx_for(usage_base, answer_source_id, "CLASSIFY")
    bundle = await _classify_bundle(
        pool, store_id, [(sid, probes[sid], hints_of[sid]) for sid in missing],
        context=f"직원 질문: {question}", global_hints=tuple(attachment_hints),
        usage_sink=usage_sink, ctx=ctx, entry="OWNER_ANSWER", owner_answer_id=owner_answer_id)
    for sid in missing:
        routes[sid] = bundle[sid]
        logger.info("점주 답변 판정 answer=%s source=%s 정규화기 %s 자료 로직 %s",
                    owner_answer_id, sid, bundle[sid].normalizer, bundle[sid].source.logic)
    return routes


async def probe_source(pool, store_id: int, src, *, cache: IntakeCache, usage_sink,
                       usage_base) -> ProbeResult:
    """정규화기를 코드로 가르고 훑는다. 받은 파일·읽은 결과는 cache 에 둬 전처리가 다시 쓴다."""
    from app.ingest import pipeline
    from app.ingest.intake import grouping, probe_media, probe_text
    from app.ingest.preprocess import audio, docx, document, kakao, storage, video

    s = get_settings()
    source_id = src["source_id"]
    source_type = src["source_type"]
    ext = capabilities.extension_of(src["file_url"] or "")

    if s.ingest_mode == "mock":
        # 원본을 받지 않는다. mock 의 PDF 는 글 자료(DOC_TEXT)로 보고, 확장자를 모르면
        # 입력 종류의 기본 정규화기로 본다
        try:
            normalizer = registry.normalizer_for(source_type, ext, pdf_has_text=True)
        except ValueError:
            if source_type not in _MOCK_DEFAULT_NORMALIZER:
                raise
            normalizer = _MOCK_DEFAULT_NORMALIZER[source_type]
        return ProbeResult(normalizer, (
            Candidate("c1", Locator("WHOLE", "", ""), pipeline.MOCK_PLACEHOLDER),))

    # 음성·영상에 저장된 전사문이 있으면 그 앞부분을 표본으로 쓴다 — 훑기 STT·다운로드 없음.
    # 전처리도 같은 전사문을 재사용한다
    if source_type in ("VOICE", "VIDEO"):
        async with pool.acquire() as conn:
            row = await (repo.get_voice(conn, source_id) if source_type == "VOICE"
                         else repo.get_video(conn, source_id))
        transcript = row["transcript"] if row else None
        if transcript:
            normalizer = registry.normalizer_for(source_type, ext, pdf_has_text=False)
            return ProbeResult(normalizer, (
                Candidate("c1", Locator("WHOLE", "", ""),
                          transcript[:s.intake_probe_text_chars]),))

    path = await pipeline._download(pool, store_id, src, cache=cache)
    is_pdf = source_type == "SCAN" and ext == "pdf"
    if is_pdf and cache.pdf is None:
        cache.pdf = document.pdf_pages(path)
    normalizer = registry.normalizer_for(source_type, ext,
                                         pdf_has_text=bool(cache.pdf and cache.pdf.has_text))
    workdir = storage.workdir(source_id)

    if normalizer == "DOC_TEXT":
        if is_pdf:
            groups = grouping.group_pdf_pages(cache.pdf.blocks, max_sections=s.intake_max_sections)
        else:
            if cache.docx is None:
                cache.docx = docx.read_docx(path)
            if not cache.docx.blocks:
                raise docx.UnsupportedDocument("docx 에 읽을 글이 없다")
            groups = grouping.group_docx(cache.docx, max_sections=s.intake_max_sections,
                                         min_chars=s.intake_min_section_chars)
        return probe_text.probe_groups("DOC_TEXT", groups, budget_chars=s.intake_probe_text_chars)

    if normalizer == "CHAT":
        if ext == "txt":
            if cache.chat_text is None:
                raw = path.read_text(encoding="utf-8", errors="replace")
                # 전처리와 같은 설정으로 파싱해야 구간 글이 추출 입력과 같다
                cache.chat_text = kakao.parse(
                    raw, message_numbers=bool(getattr(s, "extract_locator_hints", False))
                )["parsed_text"]
            groups = grouping.group_chat(cache.chat_text, max_sections=s.intake_max_sections)
            return probe_text.probe_groups("CHAT", groups, budget_chars=s.intake_probe_text_chars)
        # 대화 캡처 — 그림 한 장을 WHOLE 후보 하나로
        image = await probe_media.probe_doc_image(
            path, workdir, max_images=1, px=s.intake_probe_image_px, max_sections=1,
            page_count=1)
        return ProbeResult("CHAT", tuple(
            Candidate(c.candidate_id, Locator("WHOLE", "", ""), c.text, c.images, c.sampled)
            for c in image.candidates), complete=True)

    if normalizer == "DOC_IMAGE":
        return await probe_media.probe_doc_image(
            path, workdir, max_images=s.intake_probe_max_images, px=s.intake_probe_image_px,
            max_sections=s.intake_max_sections,
            page_count=cache.pdf.page_count if cache.pdf else 1)

    # 음성·영상 — 훑기 STT 는 본 추출 전사에 재사용하지 않는다(계획 P3). 원장 문맥은 probe{i}
    def ctx_for(i: int):
        return pipeline._ctx_for(usage_base, source_id, "STT", segment_id=f"probe{i}")

    async def transcribe(clip: Path, usage_context) -> str:
        text, _segments, _model = await audio.transcribe_detailed(
            clip, usage_sink=usage_sink, usage_context=usage_context)
        return text

    if normalizer == "AUDIO":
        meta = await audio.probe(path)
        return await probe_media.probe_audio(
            path, workdir, duration_sec=int(meta.get("duration_sec") or 0),
            windows=s.intake_probe_av_windows, window_sec=s.intake_probe_av_window_sec,
            transcribe=transcribe, usage_context_for=ctx_for)

    if normalizer == "VIDEO":
        meta = await video.probe(path)
        return await probe_media.probe_video(
            path, workdir, duration_sec=int(meta.get("duration_sec") or 0),
            has_audio=bool(meta.get("has_audio")), keyframes=s.intake_probe_video_keyframes,
            windows=s.intake_probe_av_windows, window_sec=s.intake_probe_av_window_sec,
            px=s.intake_probe_image_px, transcribe=transcribe, usage_context_for=ctx_for)

    raise ValueError(f"업로드 훑기가 없는 정규화기다: {normalizer}")
