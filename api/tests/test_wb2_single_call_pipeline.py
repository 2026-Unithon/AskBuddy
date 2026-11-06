"""Phase B 추가 S3 — 한 호출 경로. 무관이면 원장 없음, 재시도는 저장 판정 재사용."""
import asyncio
from contextlib import ExitStack
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.config import Settings
from app.ingest import pipeline
from app.ingest.intake import route as intake_route
from app.ingest.intake.decide import IntakeClassificationError, Ranked, SectionDecision
from app.ingest.intake.ir import Candidate, Locator, ProbeResult
from app.ingest.intake.records import StoredRoute
from app.ingest.pipeline import ExtractionOutcome, PreparedAssembly
from app.ingest.raw_responses import TruncatedOutputError
from app.ingest.schemas import IntakeFactExtractionResult, IntakeRank
from tests.test_w3a_pipeline_wiring import _ConnLease, _planning, _Tx

PROBE = ProbeResult("DOC_TEXT", (Candidate("c1", Locator("PAGE", "1", "1"), "음료Z 샷 2"),
                                 Candidate("c2", Locator("PAGE", "2", "2"), "마감")),
                    complete=True)


def _d(cid, logic):
    r = (Ranked(logic, 0.9),)
    return SectionDecision(cid, logic, () if logic == "NONE" else ("RECIPE",), False, False,
                           False, None, r, r)


def test_single_call_route_gives_every_candidate_the_ranking():
    result = IntakeFactExtractionResult(
        intake_ranking=[IntakeRank(logic="PROCEDURE", score=0.6),
                        IntakeRank(logic="RECIPE", score=0.3)], intake_reason="절차")
    decisions, source, outcome = intake_route.single_call_route(
        PROBE, result, hints=(), model="gemini-3.6-flash")
    assert [d.logic for d in decisions] == ["PROCEDURE", "PROCEDURE"]
    assert source.logic == "PROCEDURE" and decisions[0].extractors == ("RECIPE",)
    assert outcome.raw["single_call"] is True and set(outcome.model_sections) == {"c1", "c2"}


def test_single_call_route_without_ranking_is_error():
    with pytest.raises(IntakeClassificationError):
        intake_route.single_call_route(PROBE, IntakeFactExtractionResult(), hints=(),
                                       model="m")


def _run_source(tmp_path, *, route_value, single=None, single_error=None, settings=None):
    src = {"source_id": 7, "store_id": 1, "source_type": "SCAN",
           "file_url": "sources/1/scan/x.docx", "content_hash": "h", "status": "PROCESSING"}
    conn = AsyncMock()
    conn.transaction = MagicMock(side_effect=lambda: _Tx())
    conn.fetchval = AsyncMock(return_value=3)
    conn.fetch = AsyncMock(return_value=[])

    class Pool:
        def acquire(self):
            return _ConnLease(conn)

    async def fake_preprocess(pool, store_id, s, *, usage_sink=None, usage_context=None,
                              cache=None):
        cache.sections = {"c1": "[1쪽]\n음료Z 샷 2", "c2": "[2쪽]\n마감"}
        return "[1쪽]\n음료Z 샷 2\n\n[2쪽]\n마감", [], []

    m = NS(extract=AsyncMock(return_value=ExtractionOutcome([], [], 1, 0, [], {})),
           prepare=AsyncMock(return_value=PreparedAssembly((), {}, {}, (), {}, _planning())),
           classify_save=AsyncMock(return_value=StoredRoute(
               9, "DOC_TEXT", [_d("c1", "RECIPE"), _d("c2", "RECIPE")], _d("source", "RECIPE"))),
           single=AsyncMock(return_value=single, side_effect=single_error),
           none=AsyncMock(return_value=pipeline.INTAKE_NONE),
           failed=AsyncMock(),
           ledger=AsyncMock(return_value={}),
           layout=AsyncMock(return_value=ExtractionOutcome([], [], 1, 0, [], {})))
    patches = [
        patch.object(pipeline, "get_pool", return_value=Pool()),
        patch.object(intake_route, "route_source", AsyncMock(return_value=route_value)),
        patch.object(intake_route, "extract_with_intake", m.single),
        patch.object(intake_route, "classify_and_save", m.classify_save),
        patch.object(pipeline, "_preprocess", fake_preprocess),
        patch.object(pipeline, "_finish_intake_none", m.none),
        patch.object(pipeline, "_mark_failed", m.failed),
        patch.object(pipeline.recovery, "load", AsyncMock(return_value=None)),
        patch.object(pipeline.recovery, "replace", AsyncMock()),
        patch.object(pipeline.recovery, "layout_hash", return_value="h"),
        patch.object(pipeline.repo, "get_source", AsyncMock(return_value=src)),
        patch.object(pipeline.repo, "set_status", AsyncMock()),
        patch.object(pipeline.repo, "enabled_categories", AsyncMock(return_value={"기타": 1})),
        patch.object(pipeline.repo, "glossary", AsyncMock(return_value=[])),
        patch.object(pipeline.storage, "workdir", return_value=tmp_path / "w"),
        patch.object(pipeline, "_extract_facts_all", m.extract),
        patch.object(pipeline, "_record_segment_failures", AsyncMock()),
        patch.object(pipeline, "_prepare_fact_assembly", m.prepare),
        patch.object(pipeline, "_persist_fact_cards", AsyncMock(return_value=0)),
        patch.object(pipeline, "_persist_ledger", m.ledger),
        patch("app.ingest.layout.run_layout_extraction", m.layout),
        patch("app.config.get_settings", return_value=settings or Settings(_env_file=None)),
    ]
    with ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        result = asyncio.run(pipeline.process_source(1, 7, job_id=3))
    return result, m


PENDING = intake_route.SingleCallPending(PROBE, ())
DONE_RESULT = IntakeFactExtractionResult(intake_ranking=[IntakeRank(logic="RECIPE", score=0.9)])


def _single(logic):
    return intake_route.SingleCallResult(
        StoredRoute(11, "DOC_TEXT", [_d("c1", logic), _d("c2", logic)], _d("source", logic)),
        DONE_RESULT)


def test_single_call_prefetches_extraction(tmp_path):
    result, m = _run_source(tmp_path, route_value=PENDING, single=_single("RECIPE"))
    m.single.assert_awaited_once()
    assert m.extract.await_args.kwargs["prefetched"] is DONE_RESULT
    m.classify_save.assert_not_awaited()
    m.failed.assert_not_awaited()


def test_single_call_none_writes_nothing(tmp_path):
    # Review Focus 2
    result, m = _run_source(tmp_path, route_value=PENDING, single=_single("NONE"))
    assert result == pipeline.INTAKE_NONE
    m.extract.assert_not_awaited()
    m.ledger.assert_not_awaited()
    m.prepare.assert_not_awaited()


def test_truncated_single_call_falls_back_to_classify_then_normal_extract(tmp_path):
    result, m = _run_source(tmp_path, route_value=PENDING,
                            single_error=TruncatedOutputError("잘림"))
    m.classify_save.assert_awaited_once()
    assert m.extract.await_args.kwargs["prefetched"] is None
    m.failed.assert_not_awaited()


def test_single_call_without_ranking_fails_clearly(tmp_path):
    # 순위 없는 한 호출 결과는 다른 로직으로 보내지 않고 FAILED 로 멈춘다
    result, m = _run_source(tmp_path, route_value=PENDING,
                            single_error=IntakeClassificationError("순위 없음"))
    m.failed.assert_awaited_once()
    assert isinstance(m.failed.await_args.args[3], IntakeClassificationError)
    m.classify_save.assert_not_awaited()
    m.extract.assert_not_awaited()


def test_stored_route_skips_single_call_and_classify(tmp_path):
    # Review Focus 3 — 저장 판정(재시도·복구)이 오면 한 호출·분류 없이 보통 추출 경로
    stored = StoredRoute(9, "DOC_TEXT", [_d("c1", "RECIPE"), _d("c2", "RECIPE")],
                         _d("source", "RECIPE"))
    result, m = _run_source(tmp_path, route_value=stored)
    m.single.assert_not_awaited()
    m.classify_save.assert_not_awaited()
    assert m.extract.await_args.kwargs["prefetched"] is None


def test_layout_scan_classifies_instead_of_single_call(tmp_path):
    # 구역(LAYOUT) 추출로 갈 SCAN 자료는 한 호출 결과를 못 쓴다 — 두 번 내지 않게 분류만 한다
    s = Settings(_env_file=None).model_copy(update={"intake_single_call_small": True,
                                                    "scan_extract_mode": "LAYOUT"})
    result, m = _run_source(tmp_path, route_value=PENDING, single=_single("RECIPE"), settings=s)
    m.single.assert_not_awaited()
    m.classify_save.assert_awaited_once()
    m.layout.assert_awaited_once()
    m.extract.assert_not_awaited()
    m.failed.assert_not_awaited()


class _RLease:
    def __init__(self, conn=None):
        self.conn = conn or AsyncMock()

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, *exc):
        return False


class _RPool:
    def __init__(self):
        self.conn = AsyncMock()

    def acquire(self):
        return _RLease(self.conn)


SRC = {"source_id": 7, "store_id": 1, "source_type": "SCAN",
       "file_url": "sources/1/scan/x.docx"}
BASE = (1, 3, "REGISTRATION", "PRODUCT", None, 42)


def _route_source(**settings):
    s = Settings(_env_file=None).model_copy(update=settings)
    cls = AsyncMock()
    with patch.object(intake_route.records, "latest_decision", AsyncMock(return_value=None)), \
         patch.object(intake_route.records, "source_owner_hints", AsyncMock(return_value=("NOTICE",))), \
         patch.object(intake_route, "probe_source", AsyncMock(return_value=PROBE)), \
         patch.object(intake_route, "classify_and_save", cls), \
         patch.object(intake_route, "get_settings", return_value=s):
        out = asyncio.run(intake_route.route_source(
            _RPool(), 1, SRC, cache=intake_route.IntakeCache(), usage_sink=None,
            usage_base=BASE))
    return out, cls


def test_route_source_switch_off_classifies():
    out, cls = _route_source(intake_single_call_small=False)
    cls.assert_awaited_once()


def test_route_source_switch_on_returns_pending_without_classify():
    out, cls = _route_source(intake_single_call_small=True)
    assert isinstance(out, intake_route.SingleCallPending) and out.hints == ("NOTICE",)
    cls.assert_not_awaited()


def test_route_source_stored_decision_skips_single_call_even_when_on():
    # Review Focus 3 — 재시도·복구는 저장 판정을 그대로 쓴다
    stored = StoredRoute(9, "DOC_TEXT", [_d("c1", "RECIPE")], _d("source", "RECIPE"))
    s = Settings(_env_file=None).model_copy(update={"intake_single_call_small": True})
    probe = AsyncMock()
    cls = AsyncMock()
    with patch.object(intake_route.records, "latest_decision", AsyncMock(return_value=stored)), \
         patch.object(intake_route, "probe_source", probe), \
         patch.object(intake_route, "classify_and_save", cls), \
         patch.object(intake_route, "get_settings", return_value=s):
        out = asyncio.run(intake_route.route_source(
            _RPool(), 1, SRC, cache=intake_route.IntakeCache(), usage_sink=None,
            usage_base=BASE))
    assert out is stored
    probe.assert_not_awaited()
    cls.assert_not_awaited()


def test_classify_and_save_classifies_and_stores():
    # 지금 route_source 의 분류→결정→저장을 옮긴 것 — 원장 문맥 CLASSIFY, entry UPLOAD
    from app.ingest.intake.classify import ClassifyOutcome
    outcome = ClassifyOutcome({"c1": [Ranked("RECIPE", 0.9)], "c2": [Ranked("RECIPE", 0.9)]},
                              {}, "m", "d")
    cls = AsyncMock(return_value=outcome)
    save = AsyncMock(return_value=21)
    with patch.object(intake_route.classify, "classify", cls), \
         patch.object(intake_route.records, "save_decision", save):
        out = asyncio.run(intake_route.classify_and_save(
            _RPool(), 1, SRC, PROBE, hints=(), usage_sink=None, usage_base=BASE))
    assert out.decision_id == 21 and out.source.logic == "RECIPE"
    assert cls.await_args.kwargs["usage_context"].stage == "CLASSIFY"
    assert save.await_args.kwargs["entry"] == "UPLOAD"


def _extract_with_intake(result, hints=()):
    ext = AsyncMock(return_value=result)
    save = AsyncMock(return_value=31)
    with patch("app.ingest.extract.extract_facts_with_intake", ext), \
         patch.object(intake_route.records, "save_decision", save):
        out = asyncio.run(intake_route.extract_with_intake(
            _RPool(), 1, SRC, intake_route.SingleCallPending(PROBE, hints),
            text="음료Z 샷 2", media=[], glossary=[], usage_sink=None, usage_base=BASE,
            raw_sink=None))
    return out, ext, save


def test_extract_with_intake_uses_extract_ledger_context():
    out, ext, save = _extract_with_intake(DONE_RESULT)
    ctx = ext.await_args.kwargs["usage_context"]
    assert ctx.stage == "EXTRACT"
    assert save.await_args.kwargs["logical_call_id"] == ctx.logical_call_id
    assert out.result is DONE_RESULT and out.route.decision_id == 31


def test_extract_with_intake_saves_upload_single_call_decision():
    out, ext, save = _extract_with_intake(DONE_RESULT, hints=("RECIPE",))
    kw = save.await_args.kwargs
    assert kw["entry"] == "UPLOAD" and kw["owner_answer_id"] is None
    assert kw["outcome"].raw["single_call"] is True
    assert kw["owner_hints"] == ("RECIPE",)
    assert ext.await_args.kwargs["hints"] == ("RECIPE",)


def test_extract_with_intake_notice_ranking_routes_notice():
    result = IntakeFactExtractionResult(intake_ranking=[IntakeRank(logic="NOTICE", score=0.9)])
    out, _, _ = _extract_with_intake(result)
    assert out.route.source.logic == "NOTICE"


def test_extract_with_intake_without_ranking_saves_nothing():
    ext = AsyncMock(return_value=IntakeFactExtractionResult())
    save = AsyncMock(return_value=31)
    with patch("app.ingest.extract.extract_facts_with_intake", ext), \
         patch.object(intake_route.records, "save_decision", save):
        with pytest.raises(IntakeClassificationError):
            asyncio.run(intake_route.extract_with_intake(
                _RPool(), 1, SRC, PENDING, text="x", media=[], glossary=[],
                usage_sink=None, usage_base=BASE, raw_sink=None))
    save.assert_not_awaited()


def test_extract_facts_all_uses_prefetched_without_calling():
    from app.ingest.schemas import ExtractedAssertion
    a = ExtractedAssertion(local_ref="f1", original_assertion="음료Z 샷 2", subject="음료Z",
                           attribute="샷", value="2", unit="샷", confidence=0.9)
    pre = IntakeFactExtractionResult(assertions=[a], intake_ranking=[IntakeRank(logic="RECIPE", score=0.9)])
    called = AsyncMock()
    seen = []

    async def checkpoint(items, seg):
        seen.append((len(items), seg))

    with patch("app.ingest.extract.extract_facts", called), \
         patch("app.config.get_settings", return_value=Settings(_env_file=None)):
        out = asyncio.run(pipeline._extract_facts_all(
            source_id=7, source_type="SCAN", text="음료Z 샷 2", media=[], glossary=[],
            segments=[], checkpoint=checkpoint, prefetched=pre))
    called.assert_not_awaited()
    assert len(out.assertions) == 1 and seen == [(1, None)]


def test_single_call_chip_overturning_model_none_extracts_normally(tmp_path):
    # 최종 검토 I-1 — 모델 1위가 NONE 인데 점주 칩이 결정을 바꾸면, 꼬리 지시대로 비어 온
    # 한 호출 사실을 버리고 저장 판정으로 보통 추출 1회를 한다(빈 NO_RESULT 로 끝내지 않는다)
    raw = IntakeFactExtractionResult(
        intake_ranking=[IntakeRank(logic="NONE", score=0.5),
                        IntakeRank(logic="RECIPE", score=0.4)])
    decisions, source, _ = intake_route.single_call_route(
        PROBE, raw, hints=("RECIPE",), model="m")
    assert source.logic == "RECIPE" and source.hint_changed_decision
    single = intake_route.SingleCallResult(StoredRoute(11, "DOC_TEXT", decisions, source), raw)
    result, m = _run_source(tmp_path, route_value=intake_route.SingleCallPending(PROBE, ("RECIPE",)),
                            single=single)
    m.single.assert_awaited_once()
    m.none.assert_not_awaited()
    m.classify_save.assert_not_awaited()
    m.extract.assert_awaited_once()
    assert m.extract.await_args.kwargs["prefetched"] is None
    m.failed.assert_not_awaited()
