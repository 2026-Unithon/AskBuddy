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
from app.ingest.intake.decide import (Thresholds, decide_all, override_logic, owner_override,
                                      source_decision)
from app.ingest.intake.ir import Candidate, Locator, ProbeResult
from app.ingest.intake.records import StoredRoute
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


async def route_source(pool, store_id: int, src, *, cache: IntakeCache, usage_sink,
                       usage_base: tuple | None) -> StoredRoute:
    """자료의 판정. 최신 판정이 있으면 분류 0회로 돌려준다. 없으면 훑고 분류해 저장한다.

    분류 실패(모델 오류·JSON·후보 누락)는 IntakeClassificationError 로 올라가
    process_source 가 FAILED 로 멈춘다 — 조용히 다른 로직으로 보내지 않는다.
    """
    from app.ingest import pipeline

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


def _prefixed(source_id: int, probe: ProbeResult) -> ProbeResult:
    """묶음 분류용으로 후보 id 앞에 자료 접두어(`s{source_id}:`)를 붙인다."""
    return ProbeResult(probe.normalizer, tuple(
        replace(c, candidate_id=f"s{source_id}:{c.candidate_id}") for c in probe.candidates))


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
    outcome = await classify.classify(
        [_prefixed(sid, probes[sid]) for sid in missing], hints=tuple(attachment_hints),
        context=f"직원 질문: {question}", usage_sink=usage_sink, usage_context=ctx)

    th = Thresholds.from_settings(get_settings())
    registered = registry.registered_logics()
    decided = {}
    for sid in missing:
        own = _split_outcome(outcome, sid)
        hints = hints_of[sid]
        decisions = decide_all(probes[sid].candidates, own.model_sections, hints=hints, th=th,
                               registered=registered)
        source = source_decision(decisions, hints=hints, th=th, registered=registered)
        decided[sid] = (own, decisions, source)

    # 모든 자료가 판정된 뒤 한 트랜잭션으로 저장한다 — 묶음의 판정 행은 함께 남거나 함께 없다
    async with pool.acquire() as conn, conn.transaction():
        for sid in missing:
            own, decisions, source = decided[sid]
            decision_id = await records.save_decision(
                conn, store_id, source_id=sid, entry="OWNER_ANSWER",
                owner_answer_id=owner_answer_id, probe=probes[sid], owner_hints=hints_of[sid],
                outcome=own, decisions=decisions, source=source,
                logical_call_id=ctx.logical_call_id if ctx else None)
            routes[sid] = StoredRoute(decision_id, probes[sid].normalizer, list(decisions), source)
            logger.info("점주 답변 판정 answer=%s source=%s 정규화기 %s 자료 로직 %s",
                        owner_answer_id, sid, probes[sid].normalizer, source.logic)
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
            for c in image.candidates))

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
