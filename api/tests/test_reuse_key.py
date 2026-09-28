"""W1-3 재사용 키 — 같은 입력이면 모델을 다시 부르지 않고, 입력이 하나라도 바뀌면 새로 부른다.

외부 모델은 부르지 않는다. Gemini 호출은 합성 대역, DB 는 메모리 sink 로 바꾼다.
"""
import json
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch

import pytest

from app.contracts.usage import UsageContext
from app.ingest import raw_responses, reuse
from app.ingest.extract import gemini, mock
from app.ingest.pipeline import _extract_facts_all
from app.ingest.schemas import ExtractionResult, FactExtractionResult

GOOD = json.dumps({"assertions": [dict(
    local_ref="f1", original_assertion="음료Z 물 10ml", subject="음료Z",
    attribute="물", value="10", unit="ml", confidence=.9)]})


def _ctx(stage="EXTRACT", *, store_id=7, source_id=5, purpose="PRODUCT", run_id=None,
         segment_id=None, call="job3r1:src5"):
    return UsageContext(store_id=str(store_id), cost_phase="REGISTRATION", cost_purpose=purpose,
                        stage=stage, logical_call_id=f"{call}:{stage.lower()}", job_id="3",
                        source_id=str(source_id), segment_id=segment_id,
                        extraction_run_id=str(run_id) if run_id else None)


def _settings(**over):
    base = dict(gemini_api_key="synthetic", gemini_model="gemini-synthetic",
                ingest_mode="real", extract_temperature=0.0,
                extract_reuse_enabled=True, extract_reuse_for_evaluation=False,
                pdf_input_mode="HYBRID", video_input_mode="frames",
                extract_max_output_tokens=None, assemble_max_output_tokens=None)
    base.update(over)
    return NS(**base)


class MemorySink:
    """extraction_raw_responses 를 흉내 낸다. 재사용 조회는 실제 SQL 과 같은 조건을 쓴다."""

    def __init__(self):
        self.rows: list[dict] = []

    async def save(self, context, response):
        row = dict(raw_response_id=len(self.rows) + 1, store_id=int(context.store_id),
                   reuse_key=response.reuse_key, response_text=response.response_text,
                   finish_reason=response.finish_reason, stage=response.stage,
                   mode=response.mode, parsed_ok=None)
        self.rows.append(row)
        return row["raw_response_id"]

    async def mark_parsed(self, store_id, raw_response_id, *, parsed_ok, error):
        for row in self.rows:
            if (row["store_id"] == store_id and row["raw_response_id"] == raw_response_id
                    and row["parsed_ok"] is None):
                row["parsed_ok"] = parsed_ok

    async def find_reusable(self, store_id, reuse_key):
        for row in self.rows:
            if (row["store_id"] == store_id and row["reuse_key"] == reuse_key
                    and row["parsed_ok"] is True
                    and row["finish_reason"] not in raw_responses.TRUNCATED_FINISH_REASONS):
                return reuse.ReusableResponse(row["raw_response_id"], row["response_text"],
                                              row["finish_reason"])
        return None


class MemoryUsage:
    def __init__(self):
        self.final = []

    async def start(self, attempt):
        return len(self.final) + 1

    async def finalize(self, attempt_id, attempt, known_cost, cost, price_status):
        self.final.append((attempt, known_cost, cost))


class Calls:
    """_call 대역. 부른 횟수를 센다."""

    def __init__(self, *replies):
        self.replies = list(replies) or [gemini.CallResult(GOOD, {"prompt_tokens": 3}, "STOP")]
        self.prompts = []

    async def __call__(self, prompt, media, schema=None, max_output_tokens=None):
        self.prompts.append(prompt)
        return self.replies[min(len(self.prompts), len(self.replies)) - 1]


async def _extract(sink, ctx, *, text="t", glossary=(), media=(), usage=None):
    return await gemini.extract_facts(source_id=int(ctx.source_id), source_type="VOICE",
                                      text=text, glossary=list(glossary), media=list(media),
                                      usage_sink=usage, usage_context=ctx, raw_sink=sink)


# ── 키 ─────────────────────────────────────────────────────────────────

def _key(**over):
    args = dict(store_id="7", source_id="5", stage="EXTRACT", model="m", mode="real",
                prompt="프롬프트", media_digests=[[".jpg", "aa"]], schema_version="S/1",
                temperature=0.0, max_output_tokens=None,
                pdf_input_mode="HYBRID", video_input_mode="frames")
    args.update(over)
    return reuse.reuse_key(**args)


def test_key_is_stable_and_bounded():
    assert _key() == _key()
    assert _key().startswith(reuse.KEY_PREFIX) and len(_key()) <= 200


@pytest.mark.parametrize("field,value", [
    ("store_id", "8"), ("source_id", "6"), ("stage", "ASSEMBLE"), ("model", "m2"),
    ("mode", "mock"), ("prompt", "프롬프트!"), ("media_digests", [[".jpg", "ab"]]),
    ("media_digests", [[".png", "aa"]]), ("schema_version", "S/2"), ("temperature", 0.2),
    ("max_output_tokens", 1024), ("pdf_input_mode", "TEXT"), ("video_input_mode", "native"),
])
def test_any_input_change_changes_key(field, value):
    assert _key(**{field: value}) != _key()


def test_key_has_no_evaluation_truth_input():
    """평가 정답은 런타임 입력이 아니다 — 키 인자에 끼어들 자리가 없다."""
    import inspect
    params = set(inspect.signature(reuse.reuse_key).parameters)
    assert not params & {"truth", "expected", "answer", "gold", "evaluation_run_id"}


@pytest.mark.asyncio
async def test_key_hashes_media_bytes_not_names(tmp_path):
    a, b = tmp_path / "a.jpg", tmp_path / "b.jpg"
    a.write_bytes(b"same"), b.write_bytes(b"same")
    s = _settings()
    ka = await reuse.key_for(_ctx(), s, model="m", mode="real", prompt="p", media=[a],
                             schema=FactExtractionResult, max_output_tokens=None)
    kb = await reuse.key_for(_ctx(), s, model="m", mode="real", prompt="p", media=[b],
                             schema=FactExtractionResult, max_output_tokens=None)
    b.write_bytes(b"diff")
    kc = await reuse.key_for(_ctx(), s, model="m", mode="real", prompt="p", media=[b],
                             schema=FactExtractionResult, max_output_tokens=None)
    assert ka == kb != kc
    assert await reuse.key_for(None, s, model="m", mode="real", prompt="p", media=[],
                               schema=None, max_output_tokens=None) is None


@pytest.mark.asyncio
async def test_key_for_fails_open_when_media_cannot_be_read(tmp_path):
    # 재사용은 절약이지 정합성 조건이 아니다 — 키를 못 만들면 키 없이 추출을 계속한다
    unreadable = tmp_path / "frames"          # 디렉터리 — read_bytes 가 OSError 를 낸다
    unreadable.mkdir()
    s = _settings()
    assert await reuse.key_for(_ctx(), s, model="m", mode="real", prompt="p", media=[unreadable],
                               schema=FactExtractionResult, max_output_tokens=None) is None


@pytest.mark.asyncio
async def test_key_for_fails_open_when_schema_version_fails():
    with patch.object(reuse, "schema_version", side_effect=ValueError("synthetic")):
        assert await reuse.key_for(_ctx(), _settings(), model="m", mode="real", prompt="p",
                                   media=[], schema=FactExtractionResult,
                                   max_output_tokens=None) is None


@pytest.mark.asyncio
async def test_extraction_continues_without_key_when_key_computation_fails():
    sink, calls = MemorySink(), Calls()
    with patch.object(gemini, "get_settings", return_value=_settings()), \
         patch.object(gemini, "_call", calls), \
         patch.object(reuse, "media_digests", side_effect=OSError("synthetic")):
        result = await _extract(sink, _ctx())
    assert len(calls.prompts) == 1 and len(result.assertions) == 1
    assert sink.rows[0]["reuse_key"] is None


@pytest.mark.parametrize("flags,ctx,allowed", [
    (dict(extract_reuse_enabled=False), _ctx(), False),
    ({}, _ctx(), True),
    ({}, _ctx(purpose="EVALUATION"), False),
    ({}, _ctx(run_id=11), False),
    (dict(extract_reuse_for_evaluation=True), _ctx(purpose="EVALUATION"), True),
    (dict(extract_reuse_for_evaluation=True), _ctx(run_id=11), True),
    (dict(extract_reuse_enabled=False, extract_reuse_for_evaluation=True),
     _ctx(purpose="EVALUATION"), False),
])
def test_lookup_allowed(flags, ctx, allowed):
    assert reuse.lookup_allowed(ctx, _settings(**flags)) is allowed


def test_config_defaults_reuse_on_for_product_off_for_evaluation():
    from app.config import Settings
    s = Settings(_env_file=None)
    assert s.extract_reuse_enabled is True and s.extract_reuse_for_evaluation is False


# ── gemini 경로 ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_same_input_twice_calls_model_once_and_ledgers_reuse():
    sink, usage, calls = MemorySink(), MemoryUsage(), Calls()
    with patch.object(gemini, "get_settings", return_value=_settings()), \
         patch.object(gemini, "_call", calls):
        first = await _extract(sink, _ctx(call="job3r1:src5"), usage=usage)
        second = await _extract(sink, _ctx(call="job3r2:src5"), usage=usage)
    assert len(calls.prompts) == 1
    assert len(sink.rows) == 1 and sink.rows[0]["reuse_key"].startswith(reuse.KEY_PREFIX)
    assert second.raw_response_id == first.raw_response_id == 1
    assert [a.model_dump() for a in second.assertions] == [a.model_dump() for a in first.assertions]
    paid, reused = usage.final
    assert paid[0].cache_state is None and paid[0].usage_status == "COMPLETE"
    attempt, known, cost = reused
    assert attempt.cache_state == "REUSED" and attempt.usage_status == "NOT_BILLABLE"
    assert attempt.status == "SUCCEEDED" and known == 0 and cost == 0
    assert "raw_response_id=1" in attempt.missing_reason
    assert attempt.context.logical_call_id == "job3r2:src5:extract"


@pytest.mark.asyncio
async def test_prompt_file_one_char_change_calls_again(tmp_path):
    prompt = tmp_path / "extract_facts.ko.txt"
    prompt.write_text(gemini.FACTS_PROMPT_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    sink, calls = MemorySink(), Calls()
    with patch.object(gemini, "get_settings", return_value=_settings()), \
         patch.object(gemini, "_call", calls), \
         patch.object(gemini, "FACTS_PROMPT_PATH", prompt):
        await _extract(sink, _ctx())
        await _extract(sink, _ctx())
        prompt.write_text(prompt.read_text(encoding="utf-8") + ".", encoding="utf-8")
        await _extract(sink, _ctx())
    assert len(calls.prompts) == 2
    assert len({r["reuse_key"] for r in sink.rows}) == 2


@pytest.mark.asyncio
async def test_glossary_change_calls_again():
    sink, calls = MemorySink(), Calls()
    with patch.object(gemini, "get_settings", return_value=_settings()), \
         patch.object(gemini, "_call", calls):
        await _extract(sink, _ctx(), glossary=[{"term": "샷"}])
        await _extract(sink, _ctx(), glossary=[{"term": "샷", "description": "에스프레소"}])
    assert len(calls.prompts) == 2


@pytest.mark.asyncio
async def test_truncated_response_is_never_reused():
    sink = MemorySink()
    calls = Calls(gemini.CallResult('{"assertions": [', {}, "MAX_TOKENS"),
                  gemini.CallResult(GOOD, {}, "STOP"))
    with patch.object(gemini, "get_settings", return_value=_settings()), \
         patch.object(gemini, "_call", calls):
        with pytest.raises(raw_responses.TruncatedOutputError):
            await _extract(sink, _ctx())
        result = await _extract(sink, _ctx())
    assert len(calls.prompts) == 2 and result.raw_response_id == 2
    assert sink.rows[0]["parsed_ok"] is False and sink.rows[0]["reuse_key"] == sink.rows[1]["reuse_key"]


@pytest.mark.asyncio
async def test_parse_failed_response_is_never_reused():
    sink = MemorySink()
    calls = Calls(gemini.CallResult('{"assertions": [', {}, "STOP"),
                  gemini.CallResult(GOOD, {}, "STOP"))
    with patch.object(gemini, "get_settings", return_value=_settings()), \
         patch.object(gemini, "_call", calls):
        with pytest.raises(RuntimeError, match="파싱 실패"):
            await _extract(sink, _ctx())
        await _extract(sink, _ctx())
    assert len(calls.prompts) == 2


@pytest.mark.asyncio
async def test_other_store_same_input_is_not_reused():
    sink, calls = MemorySink(), Calls()
    with patch.object(gemini, "get_settings", return_value=_settings()), \
         patch.object(gemini, "_call", calls):
        await _extract(sink, _ctx(store_id=7))
        await _extract(sink, _ctx(store_id=8))
    assert len(calls.prompts) == 2
    assert sink.rows[0]["reuse_key"] != sink.rows[1]["reuse_key"]


@pytest.mark.asyncio
async def test_other_store_row_is_not_returned_even_with_same_key():
    """키에 매장이 들어가지만, 조회도 매장으로 거른다 — 둘 중 하나가 깨져도 새지 않는다."""
    sink, calls = MemorySink(), Calls()
    with patch.object(gemini, "get_settings", return_value=_settings()), \
         patch.object(gemini, "_call", calls):
        await _extract(sink, _ctx(store_id=7))
        sink.rows[0]["store_id"] = 8          # 같은 키가 다른 매장 행에만 있다
        await _extract(sink, _ctx(store_id=7))
    assert len(calls.prompts) == 2


@pytest.mark.asyncio
async def test_evaluation_runs_do_not_reuse_by_default():
    sink, calls = MemorySink(), Calls()
    with patch.object(gemini, "get_settings", return_value=_settings()), \
         patch.object(gemini, "_call", calls):
        await _extract(sink, _ctx(purpose="EVALUATION", run_id=11))
        await _extract(sink, _ctx(purpose="EVALUATION", run_id=11))
    assert len(calls.prompts) == 2
    # 키는 남긴다 — 나중에 켜면 찾을 수 있다
    assert sink.rows[0]["reuse_key"] == sink.rows[1]["reuse_key"] is not None


@pytest.mark.asyncio
async def test_flag_off_still_stores_key_but_calls_model():
    sink, calls = MemorySink(), Calls()
    with patch.object(gemini, "get_settings", return_value=_settings(extract_reuse_enabled=False)), \
         patch.object(gemini, "_call", calls):
        await _extract(sink, _ctx())
        await _extract(sink, _ctx())
    assert len(calls.prompts) == 2 and all(r["reuse_key"] for r in sink.rows)


@pytest.mark.asyncio
async def test_stored_row_that_no_longer_parses_is_a_miss():
    sink, calls = MemorySink(), Calls()
    with patch.object(gemini, "get_settings", return_value=_settings()), \
         patch.object(gemini, "_call", calls):
        await _extract(sink, _ctx())
        sink.rows[0]["response_text"] = "{깨짐"
        result = await _extract(sink, _ctx())
    assert len(calls.prompts) == 2 and result.raw_response_id == 2


@pytest.mark.asyncio
async def test_lookup_error_falls_back_to_model_call():
    sink, calls = MemorySink(), Calls()

    async def broken(store_id, key):
        raise RuntimeError("합성 조회 실패")
    sink.find_reusable = broken
    with patch.object(gemini, "get_settings", return_value=_settings()), \
         patch.object(gemini, "_call", calls):
        result = await _extract(sink, _ctx())
    assert len(calls.prompts) == 1 and result.raw_response_id == 1


@pytest.mark.asyncio
async def test_assemble_reuses_same_facts_prompt():
    sink, calls = MemorySink(), Calls(gemini.CallResult(
        ExtractionResult().model_dump_json(), {}, "STOP"))
    kw = dict(source_id=5, facts=[{"ref": "f1"}], category_names=["기타"], glossary=[],
              raw_sink=sink)
    with patch.object(gemini, "get_settings", return_value=_settings()), \
         patch.object(gemini, "_call", calls):
        await gemini.assemble(usage_context=_ctx("ASSEMBLE"), **kw)
        await gemini.assemble(usage_context=_ctx("ASSEMBLE"), **kw)
        await gemini.assemble(usage_context=_ctx("ASSEMBLE"), **{**kw, "category_names": ["기타", "음료"]})
    assert len(calls.prompts) == 2


# ── mock 경로도 키를 계산·저장·조회한다 ────────────────────────────────

@pytest.mark.asyncio
async def test_mock_stores_key_and_reuses_when_enabled():
    sink = MemorySink()
    s = _settings(ingest_mode="mock")
    built = []
    real_build = mock._facts_result

    def counting(source_id):
        built.append(source_id)
        return real_build(source_id)

    with patch.object(mock, "get_settings", return_value=s), \
         patch.object(mock, "_facts_result", counting):
        first = await mock.extract_facts(source_id=5, source_type="VOICE", text="t", glossary=[],
                                         usage_context=_ctx(), raw_sink=sink)
        second = await mock.extract_facts(source_id=5, source_type="VOICE", text="t", glossary=[],
                                          usage_context=_ctx(), raw_sink=sink)
    assert built == [5] and len(sink.rows) == 1
    assert sink.rows[0]["reuse_key"].startswith(reuse.KEY_PREFIX) and sink.rows[0]["mode"] == "mock"
    assert second.raw_response_id == first.raw_response_id


@pytest.mark.asyncio
async def test_mock_key_differs_from_real_key_for_same_input():
    sink = MemorySink()
    with patch.object(mock, "get_settings", return_value=_settings(ingest_mode="mock")):
        await mock.extract_facts(source_id=5, source_type="VOICE", text="t", glossary=[],
                                 usage_context=_ctx(), raw_sink=sink)
    calls = Calls()
    with patch.object(gemini, "get_settings", return_value=_settings()), \
         patch.object(gemini, "_call", calls):
        await _extract(sink, _ctx())
    assert len(calls.prompts) == 1 and sink.rows[0]["reuse_key"] != sink.rows[1]["reuse_key"]


# ── 구간 단위 (pipeline) ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_segments_have_their_own_keys_and_rerun_calls_nothing():
    import app.ingest.extract as extract_pkg
    sink, calls = MemorySink(), Calls()
    base = (7, 3, "REGISTRATION", "PRODUCT", None, 1)
    kw = dict(source_id=5, source_type="VOICE", text="t", media=[], glossary=[],
              segments=[("구간 하나", []), ("구간 둘", [])], raw_sink=sink)
    with patch.object(extract_pkg, "get_settings", return_value=_settings()), \
         patch.object(gemini, "get_settings", return_value=_settings()), \
         patch.object(gemini, "_call", calls):
        first = await _extract_facts_all(usage_base=base, **kw)
        second = await _extract_facts_all(usage_base=(7, 3, "REGISTRATION", "PRODUCT", None, 2), **kw)
    assert len(calls.prompts) == 2 and len(sink.rows) == 2
    assert sink.rows[0]["reuse_key"] != sink.rows[1]["reuse_key"]
    assert [a.local_ref for a in second.assertions] == [a.local_ref for a in first.assertions]
    assert second.raw_response_ids == first.raw_response_ids
