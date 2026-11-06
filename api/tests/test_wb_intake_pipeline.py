# api/tests/test_wb_intake_pipeline.py
"""Phase B — process_source 의 분류 단계 연결. 모델·DB 대역(test_w3a_pipeline_wiring 방식)."""
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.config import Settings
from app.ingest import job_worker, pipeline
from app.ingest.intake import route as intake_route
from app.ingest.intake.classify import ClassifyOutcome
from app.ingest.intake.decide import IntakeClassificationError, Ranked, SectionDecision
from app.ingest.intake.ir import Candidate, Locator, ProbeResult
from app.ingest.intake.records import StoredRoute
from app.ingest.pipeline import ExtractionOutcome, PreparedAssembly
from tests.test_w3a_pipeline_wiring import _ConnLease, _planning, _Tx, _worker

SECTIONS = {"c1": "[1쪽]\n음료Z 샷 2", "c2": "[2쪽]\n잡담", "c3": "[3쪽]\n음료Z 물 225ml"}
FULL = "\n\n".join(SECTIONS.values())


def _d(cid, logic):
    r = (Ranked(logic, 0.9),)
    return SectionDecision(cid, logic, () if logic == "NONE" else ("RECIPE",), False, False,
                           False, None, r, r)


def _route(normalizer, *logics, source=None):
    decisions = [_d(f"c{i}", l) for i, l in enumerate(logics, 1)]
    return StoredRoute(1, normalizer, decisions, _d("source", source or logics[0]))


async def _run(tmp_path, *, route, sections=None, text="본문", source_type="SCAN",
               notice_fact_ids=(), route_error=None, supported=(), **run_kw):
    """process_source 한 번(job 있음). 호출 순서를 log 로, 대역을 mocks 로 돌려준다."""
    log: list = []
    src = {"source_id": 7, "store_id": 1, "source_type": source_type,
           "file_url": "b/1/scan/x.docx", "content_hash": "h", "status": "PROCESSING"}
    conn = AsyncMock()
    conn.transaction = MagicMock(side_effect=lambda: _Tx())
    conn.fetchval = AsyncMock(return_value=3)
    # _notice_holds 의 occurrence 행 — 공지 구간(seg2)·자료 전체 공지(None)에서만 나온 사실
    conn.fetch = AsyncMock(return_value=[
        {"fact_id": f, "segment_id": "seg2" if source_type == "SCAN" else None,
         "other_support": f in supported} for f in notice_fact_ids])

    async def execute(sql, *args):
        if "CLASSIFYING" in sql:
            log.append("classifying")
    conn.execute = AsyncMock(side_effect=execute)

    class Pool:
        def acquire(self):
            return _ConnLease(conn)

    async def fake_route(pool, store_id, s, *, cache, usage_sink, usage_base):
        log.append("route")
        if route_error is not None:
            raise route_error
        return route

    async def fake_preprocess(pool, store_id, s, *, usage_sink=None, usage_context=None,
                              cache=None):
        log.append("preprocess")
        if cache is not None:  # 평가 실행은 입구 분류 없이 캐시도 없다
            cache.sections = sections
        return text, [], []

    mocks = NS(extract=AsyncMock(return_value=ExtractionOutcome([], [], 1, 0, [], {})),
               prepare=AsyncMock(return_value=PreparedAssembly((), {}, {}, (), {}, _planning())),
               persist=AsyncMock(return_value=0), set_status=AsyncMock(), failed=AsyncMock())
    with patch.object(pipeline, "get_pool", return_value=Pool()), \
         patch.object(intake_route, "route_source", fake_route), \
         patch.object(pipeline, "_preprocess", fake_preprocess), \
         patch.object(pipeline.recovery, "load", AsyncMock(return_value=None)), \
         patch.object(pipeline.recovery, "replace", AsyncMock()), \
         patch.object(pipeline.recovery, "layout_hash", return_value="h"), \
         patch.object(pipeline.repo, "get_source", AsyncMock(return_value=src)), \
         patch.object(pipeline.repo, "set_status", mocks.set_status), \
         patch.object(pipeline.repo, "enabled_categories", AsyncMock(return_value={"기타": 1})), \
         patch.object(pipeline.repo, "glossary", AsyncMock(return_value=[])), \
         patch.object(pipeline.storage, "workdir", return_value=tmp_path / "w"), \
         patch.object(pipeline, "_extract_facts_all", mocks.extract), \
         patch.object(pipeline, "_record_segment_failures", AsyncMock()), \
         patch.object(pipeline, "_prepare_fact_assembly", mocks.prepare), \
         patch.object(pipeline, "_persist_fact_cards", mocks.persist), \
         patch.object(pipeline, "_mark_failed", mocks.failed), \
         patch("app.config.get_settings", return_value=Settings(_env_file=None)):
        result = await pipeline.process_source(1, 7, job_id=3, **run_kw)
    return result, log, mocks


def _statuses(mocks):
    return [c.args[3] for c in mocks.set_status.await_args_list]


@pytest.mark.asyncio
async def test_classifies_once_before_preprocess_and_sets_classifying(tmp_path):
    result, log, m = await _run(tmp_path, route=_route("DOC_TEXT", "RECIPE"))
    assert result is None and log.count("route") == 1
    assert log.index("classifying") < log.index("route") < log.index("preprocess")
    m.extract.assert_awaited_once()


@pytest.mark.asyncio
async def test_source_none_skips_preprocess_and_extraction(tmp_path):
    result, log, m = await _run(tmp_path, route=_route("VIDEO", "NONE"), source_type="VIDEO")
    assert result == pipeline.INTAKE_NONE and "preprocess" not in log
    m.extract.assert_not_awaited()
    m.prepare.assert_not_awaited()
    assert _statuses(m)[-1] == "DONE"


@pytest.mark.asyncio
async def test_text_all_none_sections_skip_after_preprocess(tmp_path):
    result, log, m = await _run(tmp_path, route=_route("CHAT", "NONE", "NONE"),
                                source_type="KAKAO", sections={"c1": "a", "c2": "b"}, text="a\nb")
    assert result == pipeline.INTAKE_NONE and "preprocess" in log
    m.extract.assert_not_awaited()
    assert _statuses(m)[-1] == "DONE"


@pytest.mark.asyncio
async def test_none_section_removed_from_extraction_text(tmp_path):
    _, _, m = await _run(tmp_path, route=_route("DOC_TEXT", "RECIPE", "NONE", "RECIPE"),
                         sections=SECTIONS, text=FULL)
    assert m.extract.await_args.kwargs["text"] == "[1쪽]\n음료Z 샷 2\n\n[3쪽]\n음료Z 물 225ml"


@pytest.mark.asyncio
async def test_unchanged_text_when_nothing_dropped(tmp_path):
    # Review Focus 4 — 거른 것이 없으면 추출 입력이 전처리 결과와 바이트 단위로 같다(D16)
    _, _, m = await _run(tmp_path, route=_route("DOC_TEXT", "RECIPE", "RECIPE", "RECIPE"),
                         sections=SECTIONS, text=FULL)
    kw = m.extract.await_args.kwargs
    assert kw["text"] == FULL and kw["segments"] == []


@pytest.mark.asyncio
async def test_notice_facts_held_from_assembly(tmp_path):
    _, _, m = await _run(tmp_path, route=_route("DOC_TEXT", "RECIPE", "NOTICE", "RECIPE"),
                         sections=SECTIONS, text=FULL, notice_fact_ids=(501, 502))
    kw = m.extract.await_args.kwargs
    assert [s[0] for s in kw["segments"]] == ["[1쪽]\n음료Z 샷 2\n\n[3쪽]\n음료Z 물 225ml",
                                              "[2쪽]\n잡담"]
    assert m.prepare.await_args.kwargs["held_fact_ids"] == {501: "INTAKE_NOTICE",
                                                            502: "INTAKE_NOTICE"}


@pytest.mark.asyncio
async def test_media_notice_holds_every_fact(tmp_path):
    _, _, m = await _run(tmp_path, route=_route("VIDEO", "NOTICE"), source_type="VIDEO",
                         notice_fact_ids=(7001,))
    assert m.prepare.await_args.kwargs["held_fact_ids"] == {7001: "INTAKE_NOTICE"}


@pytest.mark.asyncio
async def test_classification_error_marks_failed(tmp_path):
    _, log, m = await _run(tmp_path, route=None,
                           route_error=IntakeClassificationError("분류 호출 실패: JSON"))
    m.failed.assert_awaited_once()
    assert isinstance(m.failed.await_args.args[3], IntakeClassificationError)
    assert "preprocess" not in log
    m.extract.assert_not_awaited()


# ── route_source: 재사용·새 분류 ─────────────────────────────────────────

class _Pool:
    def acquire(self):
        return _ConnLease(AsyncMock())


SRC = {"source_id": 7, "store_id": 1, "source_type": "SCAN", "file_url": "b/1/scan/x.docx"}
BASE = (1, 3, "REGISTRATION", "PRODUCT", None, 42)


@pytest.mark.asyncio
async def test_route_source_reuses_latest_decision():
    # Review Focus 2 — 재시도·복구에서 분류를 다시 부르지 않는다
    stored = _route("DOC_TEXT", "RECIPE")
    with patch.object(intake_route.records, "latest_decision", AsyncMock(return_value=stored)), \
         patch.object(intake_route.records, "source_owner_hints", AsyncMock(return_value=())), \
         patch.object(intake_route, "probe_source", AsyncMock()) as probe, \
         patch.object(intake_route.classify, "classify", AsyncMock()) as cls:
        got = await intake_route.route_source(_Pool(), 1, SRC, cache=intake_route.IntakeCache(),
                                              usage_sink=None, usage_base=BASE)
    assert got is stored
    probe.assert_not_awaited()
    cls.assert_not_awaited()


@pytest.mark.asyncio
async def test_route_source_classifies_and_saves_when_new():
    probe = ProbeResult("DOC_TEXT", (Candidate("c1", Locator("PAGE", "1", "1"), "글"),))
    outcome = ClassifyOutcome({"c1": [Ranked("RECIPE", 0.45), Ranked("PROCEDURE", 0.40)]},
                              {}, "gemini-3.6-flash", "abcd")
    save = AsyncMock(return_value=42)
    with patch.object(intake_route.records, "latest_decision", AsyncMock(return_value=None)), \
         patch.object(intake_route.records, "source_owner_hints",
                      AsyncMock(return_value=("PROCEDURE",))), \
         patch.object(intake_route.records, "save_decision", save), \
         patch.object(intake_route, "probe_source", AsyncMock(return_value=probe)), \
         patch.object(intake_route.classify, "classify", AsyncMock(return_value=outcome)) as cls, \
         patch.object(intake_route, "get_settings", return_value=Settings(_env_file=None)):
        got = await intake_route.route_source(_Pool(), 1, SRC, cache=intake_route.IntakeCache(),
                                              usage_sink=None, usage_base=BASE)
    # 칩 가산(0.15)으로 PROCEDURE 가 1위, 미등록이라 추출기는 RECIPE
    assert got.decision_id == 42 and got.normalizer == "DOC_TEXT"
    assert got.decisions[0].logic == "PROCEDURE" and got.decisions[0].extractors == ("RECIPE",)
    assert got.decisions[0].hint_changed_decision and got.source.logic == "PROCEDURE"
    kw = save.await_args.kwargs
    assert kw["entry"] == "UPLOAD" and kw["owner_hints"] == ("PROCEDURE",)
    assert kw["logical_call_id"].endswith(":classify")
    assert cls.await_args.kwargs["usage_context"].stage == "CLASSIFY"


# ── job_worker 메시지 ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_job_worker_maps_intake_none_message():
    # Review Focus 1
    pool, conn = _worker(linked_cards=0, pending=0)
    with patch.object(job_worker, "get_pool", return_value=pool), \
         patch.object(job_worker.pipeline, "process_source",
                      AsyncMock(return_value=pipeline.INTAKE_NONE)), \
         patch.object(job_worker, "_refresh_job", AsyncMock(return_value=("NO_RESULT", 0))), \
         patch.object(job_worker, "create_ingest_completed_notification",
                      AsyncMock(return_value=None)), \
         patch("app.config.get_settings", return_value=NS()):
        await job_worker.process_ingest_job(1, 2)
    rows = [c.args[4:] for c in conn.execute.await_args_list
            if "set status = $4, card_count = $5" in c.args[0]]
    # 자료 상태는 NO_RESULT 그대로, 코드는 INTAKE_NONE 으로 갈라 화면이 자료별 버튼을 고른다
    assert rows == [("NO_RESULT", 0, "INTAKE_NONE", job_worker.INTAKE_NONE_MESSAGE)]
    assert job_worker.INTAKE_NONE_MESSAGE == "업무 자료가 아니라고 판단해 추출하지 않았어요."


# ── fix round 1: 평가 실행·공지 받침·실제 전처리 바이트 동일 ──────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("run_kw", [{"cost_purpose": "EVALUATION"}, {"extraction_run_id": 9}])
async def test_evaluation_run_skips_intake_routing(tmp_path, run_kw):
    # 평가 실행은 지금까지와 같은 입력으로 잰다 — 판정·분류를 부르지 않는다
    _, log, m = await _run(tmp_path, route=_route("DOC_TEXT", "NONE"), **run_kw)
    assert "route" not in log and "preprocess" in log
    assert m.extract.await_args.kwargs["text"] == "본문"
    assert "held_fact_ids" not in m.prepare.await_args.kwargs


@pytest.mark.asyncio
async def test_supported_notice_fact_stays_in_assembly(tmp_path):
    # 공지에만 나왔어도 다른 자료가 받치는 사실(502)은 조립에 남고, 이 자료 occurrence 만 보류한다
    _, _, m = await _run(tmp_path, route=_route("DOC_TEXT", "RECIPE", "NOTICE", "RECIPE"),
                         sections=SECTIONS, text=FULL, notice_fact_ids=(501, 502),
                         supported=(502,))
    kw = m.prepare.await_args.kwargs
    assert kw["held_fact_ids"] == {501: "INTAKE_NOTICE"}
    assert kw["notice_fact_ids"] == frozenset({501, 502})


class _NullLease:
    async def __aenter__(self):
        return AsyncMock()

    async def __aexit__(self, *exc):
        return False


class _NullPool:
    def acquire(self):
        return _NullLease()


async def _plan_text_vs_plain(tmp_path, handler, src, path, *, settings):
    """같은 파일을 입구 분류 없이(기존) / 캐시와 함께(분류 뒤) 전처리하고, 전부 RECIPE 판정의
    추출 계획 글을 기존 전처리 글과 비교한다(D16)."""
    from app.ingest.intake.plan import plan_extraction

    async def download(pool, store_id, s, cache=None):
        return path

    with patch.object(pipeline, "_download", download), \
         patch.object(pipeline.repo, "get_scan", AsyncMock(return_value={"scan_id": 1})), \
         patch.object(pipeline.repo, "update_scan_result", AsyncMock()), \
         patch.object(pipeline.repo, "get_kakao", AsyncMock(return_value={"kakao_id": 1})), \
         patch.object(pipeline.repo, "update_kakao_result", AsyncMock()), \
         patch("app.config.get_settings", return_value=settings):
        plain, _, _ = await handler(_NullPool(), 1, src)
        cache = intake_route.IntakeCache(path=path)
        text, media, segments = await handler(_NullPool(), 1, src, cache=cache)
    normalizer = "DOC_TEXT" if src["source_type"] == "SCAN" else "CHAT"
    sections = intake_route.full_sections(cache, normalizer)
    assert sections and len(sections) >= 2  # 구간이 여럿이어야 다시 잇기를 검사한다
    decisions = [_d(cid, "RECIPE") for cid in sections]
    plan = plan_extraction(normalizer=normalizer, decisions=decisions, source=_d("source", "RECIPE"),
                           sections=sections)
    assert text == plain and media == [] and segments == []
    return plan, plain


@pytest.mark.asyncio
async def test_real_docx_preprocess_plan_text_is_byte_identical(tmp_path):
    from tests.test_wb_docx import _p, _tbl, make_docx
    body = (_p("음료Z 만들기", "Heading1") + _p("샷 2 넣는다") + _tbl([["물", "225ml"]])
            + _p("마감", "Heading1") + _p("기계를 닦는다"))
    path = make_docx(tmp_path, body)
    settings = Settings(_env_file=None, intake_min_section_chars=5)
    plan, plain = await _plan_text_vs_plain(
        tmp_path, pipeline._preprocess_scan,
        {"source_id": 7, "source_type": "SCAN", "file_url": "b/1/scan/x.docx"}, path,
        settings=settings)
    assert plan.text == plain and plan.segments is None


@pytest.mark.asyncio
async def test_real_kakao_preprocess_plan_text_is_byte_identical(tmp_path):
    path = tmp_path / "대화.txt"
    path.write_text("합성매장 님과 카카오톡 대화\n저장한 날짜 : 2026-10-01 10:00:00\n\n"
                    "2026. 10. 1. 오전 10:00, 점주 : 음료Z 샷 2\n"
                    "2026. 10. 2. 오전 11:00, 점주 : 음료Z 물 225ml\n"
                    "2026. 10. 2. 오전 11:05, 점주 : 얼음 가득\n", encoding="utf-8")
    plan, plain = await _plan_text_vs_plain(
        tmp_path, pipeline._preprocess_kakao,
        {"source_id": 8, "source_type": "KAKAO", "file_url": "b/1/kakao/x.txt"}, path,
        settings=Settings(_env_file=None))
    assert plan.text == plain and plan.segments is None
