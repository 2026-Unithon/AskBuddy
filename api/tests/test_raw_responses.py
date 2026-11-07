"""W1-1 모델 원래 응답 저장 — 파싱 전에 남기고, 저장 실패면 멈추고, 매장 범위로만 다룬다.

외부 모델은 부르지 않는다. Gemini SDK 는 합성 대역으로 바꾼다.
"""
import enum
import json
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

import pytest

from app.contracts.usage import UsageContext
from app.ingest import extract, raw_responses
from app.ingest.extract import gemini, mock
from app.ingest import pipeline
from app.ingest.pipeline import _extract_facts_all
from app.ingest.schemas import (CardPlanBatch, Evidence, ExtractedAssertion,
                                FactExtractionResult)

ROOT = Path(__file__).resolve().parents[2]
GOOD = json.dumps({"assertions": [dict(
    local_ref="f1", original_assertion="음료Z 물 10ml", subject="음료Z",
    attribute="물", value="10", unit="ml", confidence=.9)]})


def _ctx(stage="EXTRACT", segment_id=None, store_id=7):
    return UsageContext(store_id=str(store_id), cost_phase="REGISTRATION", stage=stage,
                        logical_call_id=f"job3:src5:{stage.lower()}", job_id="3",
                        source_id="5", segment_id=segment_id)


class FakeRawSink:
    """저장 순서와 값을 기록한다. 실제 DB 대신 쓴다."""

    def __init__(self, fail_save=False, fail_mark=False):
        self.events, self.saved, self.marks = [], [], []
        self.fail_save, self.fail_mark = fail_save, fail_mark

    async def save(self, context, response):
        self.events.append("save")
        if self.fail_save:
            raise raw_responses.RawResponseWriteError("합성 저장 실패")
        self.saved.append((context, response))
        return 100 + len(self.saved)

    async def mark_parsed(self, store_id, raw_response_id, *, parsed_ok, error):
        self.events.append("mark")
        if self.fail_mark:
            raise RuntimeError("합성 표시 실패")
        self.marks.append((store_id, raw_response_id, parsed_ok, error))


def _real_settings():
    return NS(gemini_api_key="synthetic", gemini_model="gemini-synthetic",
              ingest_mode="real", extract_temperature=0.0, gemini_request_timeout_sec=300)


# ── _call: 응답 텍스트·usage·finish_reason ─────────────────────────────

class _Reason(enum.Enum):
    STOP = 1
    MAX_TOKENS = 2


@pytest.mark.asyncio
async def test_call_returns_text_usage_and_finish_reason_name():
    res = NS(text='{"assertions": []', usage_metadata=None,
             candidates=[NS(finish_reason=_Reason.MAX_TOKENS)])
    client = NS(aio=NS(models=NS(generate_content=AsyncMock(return_value=res))))
    with patch.object(gemini, "get_settings", return_value=_real_settings()), \
         patch("google.genai.Client", return_value=client):
        reply = await gemini._call("프롬프트", [], FactExtractionResult)
    assert reply.text == '{"assertions": []'
    assert reply.usage == {}
    assert reply.finish_reason == "MAX_TOKENS"
    assert reply.raw_response_id is None


@pytest.mark.asyncio
async def test_call_sets_request_timeout_from_settings():
    """응답이 오지 않는 Gemini 요청이 영원히 기다리지 않게 요청 시간 제한을 건다(실측에서 45분 멈춤)."""
    res = NS(text="{}", usage_metadata=None, candidates=[])
    client = NS(aio=NS(models=NS(generate_content=AsyncMock(return_value=res))))
    st = _real_settings()
    st.gemini_request_timeout_sec = 42
    with patch.object(gemini, "get_settings", return_value=st), \
         patch("google.genai.Client", return_value=client) as made:
        await gemini._call("프롬프트", [], FactExtractionResult)
    assert made.call_args.kwargs["http_options"].timeout == 42_000


def test_finish_reason_handles_missing_and_plain_values():
    assert gemini._finish_reason_of(NS(candidates=[])) is None
    assert gemini._finish_reason_of(NS()) is None
    assert gemini._finish_reason_of(NS(candidates=[NS(finish_reason=None)])) is None
    assert gemini._finish_reason_of(NS(candidates=[NS(finish_reason="STOP")])) == "STOP"


# ── _measured_call: 호출이 끝난 뒤, 파싱 전에 저장 ─────────────────────

@pytest.mark.asyncio
async def test_measured_call_saves_after_model_call_and_returns_id():
    sink = FakeRawSink()

    async def fake_call(prompt, media, schema, max_output_tokens=None):
        sink.events.append("call")
        return gemini.CallResult("본문", {"prompt_tokens": 3}, "STOP")

    with patch.object(gemini, "get_settings", return_value=_real_settings()), \
         patch.object(gemini, "_call", fake_call):
        reply = await gemini._measured_call("p", [], None, _ctx(segment_id="seg2"),
                                            prompt_hash="abc", schema=FactExtractionResult,
                                            raw_sink=sink)
    assert sink.events == ["call", "save"]
    assert reply.raw_response_id == 101 and reply.finish_reason == "STOP"
    context, response = sink.saved[0]
    assert context.segment_id == "seg2"
    assert response.stage == "EXTRACT" and response.mode == "real"
    assert response.model == "gemini-synthetic" and response.prompt_hash == "abc"
    assert response.response_text == "본문" and response.finish_reason == "STOP"
    assert response.usage == {"prompt_tokens": 3}
    assert response.schema_version == raw_responses.schema_version(FactExtractionResult)


@pytest.mark.asyncio
async def test_measured_call_without_context_does_not_record():
    """미리보기처럼 매장 문맥이 없으면 기록할 매장이 없다 — 저장하지 않는다."""
    with patch.object(gemini, "get_settings", return_value=_real_settings()), \
         patch.object(gemini, "_call", AsyncMock(return_value=gemini.CallResult("x", {}, None))):
        reply = await gemini._measured_call("p", [], None, None)
    assert reply.raw_response_id is None


@pytest.mark.asyncio
async def test_raw_sink_without_context_is_refused():
    with patch.object(gemini, "get_settings", return_value=_real_settings()), \
         patch.object(gemini, "_call", AsyncMock(return_value=gemini.CallResult("x", {}, None))):
        with pytest.raises(raw_responses.RawResponseWriteError):
            await gemini._measured_call("p", [], None, None, raw_sink=FakeRawSink())


# ── extract_facts / assemble: 파싱 결과 표시 ───────────────────────────

@pytest.mark.asyncio
async def test_parse_failure_keeps_raw_row_and_marks_error():
    sink = FakeRawSink()
    with patch.object(gemini, "get_settings", return_value=_real_settings()), \
         patch.object(gemini, "_call", AsyncMock(
             return_value=gemini.CallResult('{"assertions": [', {}, "STOP"))):
        # 잘림(MAX_TOKENS)은 W1-2 가 따로 거절한다 — 여기서는 형식 오류만 본다
        with pytest.raises(RuntimeError, match="파싱 실패"):
            await gemini.extract_facts(source_id=5, source_type="VOICE", text="t", glossary=[],
                                       usage_context=_ctx(), raw_sink=sink)
    assert sink.events == ["save", "mark"]
    assert sink.saved[0][1].response_text == '{"assertions": ['
    store_id, raw_id, ok, error = sink.marks[0]
    assert (store_id, raw_id, ok) == (7, 101, False) and error


@pytest.mark.asyncio
async def test_parse_success_marks_ok_and_exposes_raw_id():
    sink = FakeRawSink()
    with patch.object(gemini, "get_settings", return_value=_real_settings()), \
         patch.object(gemini, "_call", AsyncMock(return_value=gemini.CallResult(GOOD, {}, "STOP"))):
        result = await gemini.extract_facts(source_id=5, source_type="VOICE", text="t",
                                            glossary=[], usage_context=_ctx(), raw_sink=sink)
    assert result.raw_response_id == 101
    assert sink.marks == [(7, 101, True, None)]


@pytest.mark.asyncio
async def test_save_failure_stops_extraction_before_parse():
    """기록 없는 추출은 되짚을 수 없다 — 저장이 실패하면 결과를 쓰지 않는다."""
    sink = FakeRawSink(fail_save=True)
    with patch.object(gemini, "get_settings", return_value=_real_settings()), \
         patch.object(gemini, "_call", AsyncMock(return_value=gemini.CallResult(GOOD, {}, "STOP"))):
        with pytest.raises(raw_responses.RawResponseWriteError):
            await gemini.extract_facts(source_id=5, source_type="VOICE", text="t",
                                       glossary=[], usage_context=_ctx(), raw_sink=sink)
    assert sink.events == ["save"]


@pytest.mark.asyncio
async def test_mark_failure_does_not_discard_parsed_result():
    sink = FakeRawSink(fail_mark=True)
    with patch.object(gemini, "get_settings", return_value=_real_settings()), \
         patch.object(gemini, "_call", AsyncMock(return_value=gemini.CallResult(GOOD, {}, "STOP"))):
        result = await gemini.extract_facts(source_id=5, source_type="VOICE", text="t",
                                            glossary=[], usage_context=_ctx(), raw_sink=sink)
    assert len(result.assertions) == 1 and result.raw_response_id == 101


@pytest.mark.asyncio
async def test_assemble_plan_records_stage_assemble():
    sink = FakeRawSink()
    body = CardPlanBatch().model_dump_json()
    with patch.object(gemini, "get_settings", return_value=_real_settings()), \
         patch.object(gemini, "_call", AsyncMock(return_value=gemini.CallResult(body, {}, "STOP"))):
        result = await gemini.assemble_plan(source_id=5, entities=_PLAN_ENTITIES, category_names=["기타"],
                                            glossary=[], usage_context=_ctx("ASSEMBLE"), raw_sink=sink)
    assert sink.saved[0][1].stage == "ASSEMBLE"
    assert sink.saved[0][1].schema_version == raw_responses.schema_version(CardPlanBatch)
    assert result.raw_response_id == 101 and sink.marks[0][2] is True


_PLAN_ENTITIES = [{"대상": "음료Z", "사실": [
    {"id": "F1", "규격": "", "순서": 0, "부정": False}]}]


def test_private_raw_id_does_not_change_response_schema():
    """모델에 보내는 response_schema 가 바뀌면 실험 기준선이 바뀐다."""
    assert "raw_response_id" not in json.dumps(FactExtractionResult.model_json_schema())
    assert "raw_response_id" not in json.dumps(CardPlanBatch.model_json_schema())
    assert "raw_response_id" not in FactExtractionResult().model_dump()


# ── mock 경로도 같은 기록 ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_mock_extract_and_assemble_write_same_record():
    sink = FakeRawSink()
    facts = await mock.extract_facts(source_id=5, source_type="VOICE", text="t", glossary=[],
                                     usage_context=_ctx(), raw_sink=sink)
    cards = await mock.assemble_plan(source_id=5, entities=_PLAN_ENTITIES,
        category_names=["기타"], glossary=[], usage_context=_ctx("ASSEMBLE"), raw_sink=sink)
    (_, first), (_, second) = sink.saved
    assert first.mode == second.mode == "mock"
    assert (first.stage, second.stage) == ("EXTRACT", "ASSEMBLE")
    assert FactExtractionResult.model_validate_json(first.response_text).model_dump() == facts.model_dump()
    assert facts.raw_response_id == 101 and cards.raw_response_id == 102
    assert [m[2] for m in sink.marks] == [True, True]


@pytest.mark.asyncio
async def test_dispatcher_passes_raw_sink_to_mock():
    sink = FakeRawSink()
    with patch.object(extract, "get_settings", return_value=NS(ingest_mode="mock")):
        await extract.extract_facts(source_id=5, source_type="VOICE", text="t", glossary=[],
                                    usage_context=_ctx(), raw_sink=sink)
        await extract.assemble_card_plan(source_id=5, entities=[], category_names=[], glossary=[],
                                         usage_context=_ctx("ASSEMBLE"), raw_sink=sink)
    assert [r.stage for _, r in sink.saved] == ["EXTRACT", "ASSEMBLE"]


@pytest.mark.asyncio
async def test_pipeline_threads_raw_sink_and_collects_segment_ids():
    sink = FakeRawSink()
    base = (7, 3, "REGISTRATION", "PRODUCT", None, None)
    with patch.object(extract, "get_settings", return_value=NS(ingest_mode="mock")):
        outcome = await _extract_facts_all(
            source_id=5, source_type="VOICE", text="", media=[], glossary=[],
            segments=[("a", []), ("b", [])], usage_base=base, raw_sink=sink)
        await extract.assemble_card_plan(
            source_id=5, entities=_PLAN_ENTITIES, category_names=["기타"], glossary=[],
            usage_context=pipeline._ctx_for(base, 5, "ASSEMBLE"), raw_sink=sink)
    assert outcome.raw_response_ids == {"seg1": 101, "seg2": 102}
    assert [c.segment_id for c, _ in sink.saved] == ["seg1", "seg2", None]
    assert [r.stage for _, r in sink.saved] == ["EXTRACT", "EXTRACT", "ASSEMBLE"]


# ── DB 저장: 매장 범위 ────────────────────────────────────────────────

class _Pool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        pool = self

        class _Ctx:
            async def __aenter__(self):
                return pool.conn

            async def __aexit__(self, *exc):
                return False
        return _Ctx()


@pytest.mark.asyncio
async def test_db_sink_inserts_with_store_and_run_tag():
    conn = NS(fetchval=AsyncMock(return_value=55), execute=AsyncMock(return_value="UPDATE 1"))
    sink = raw_responses.DbRawResponseSink(_Pool(conn), run_tag=1234)
    response = raw_responses.RawResponse(
        stage="EXTRACT", model="m", mode="real", prompt_hash="h", schema_version="s",
        finish_reason="STOP", response_text="본문", usage={"prompt_tokens": 1})
    assert await sink.save(_ctx(segment_id="seg1"), response) == 55
    sql, *args = conn.fetchval.await_args.args
    assert "insert into extraction_raw_responses" in sql
    assert args[0] == 7 and 1234 in args and "seg1" in args and "본문" in args
    await sink.mark_parsed(7, 55, parsed_ok=False, error="bad")
    sql, *args = conn.execute.await_args.args
    assert "where store_id = $1 and raw_response_id = $2" in sql and args[:2] == [7, 55]


@pytest.mark.asyncio
async def test_db_sink_wraps_insert_errors():
    conn = NS(fetchval=AsyncMock(side_effect=OSError("down")))
    sink = raw_responses.DbRawResponseSink(_Pool(conn))
    response = raw_responses.RawResponse(
        stage="EXTRACT", model="m", mode="real", prompt_hash=None, schema_version=None,
        finish_reason=None, response_text="", usage={})
    with pytest.raises(raw_responses.RawResponseWriteError):
        await sink.save(_ctx(), response)


# ── migration 정적 검사 ───────────────────────────────────────────────

def test_migration_declares_table_without_cascade():
    files = list((ROOT / "supabase/migrations").glob("*_w_extraction_raw_responses.sql"))
    assert len(files) == 1 and files[0].name.split("_", 1)[0] > "20260927140000"
    sql = files[0].read_text(encoding="utf-8").lower()
    assert "create table if not exists extraction_raw_responses" in sql
    assert "on delete cascade" not in sql
    assert "where parsed_ok" in sql and "(store_id, reuse_key)" in sql


def test_outcome_raw_ids_default_is_not_a_shared_mutable():
    """NamedTuple 기본값은 모든 인스턴스가 한 객체를 공유한다 — 가변 dict 를 기본값으로 두지 않는다."""
    from app.ingest.pipeline import ExtractionOutcome
    first = ExtractionOutcome([], [], 1, 0, [])
    second = ExtractionOutcome([], [], 1, 0, [])
    assert first.raw_response_ids is None and second.raw_response_ids is None
    assert ExtractionOutcome._field_defaults["raw_response_ids"] is None
