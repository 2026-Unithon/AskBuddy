"""W1-2 잘린 출력 감지·복구.

출력이 잘린 응답(finish_reason=MAX_TOKENS)은 성공으로 처리하지 않는다. 구간을 반으로
나눠 다시 뽑고, 끝까지 잘리면 그 구간을 실패 구간으로 남긴다(PARTIAL). 구간 없는
자료는 명확한 오류로 멈춘다. 외부 모델은 부르지 않는다 — Gemini SDK 는 합성 대역이다.
"""
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

import pytest

from app.config import Settings
from app.contracts.usage import UsageContext
from app.ingest import extract, raw_responses, recovery
from app.ingest.extract import gemini
from app.ingest.pipeline import _extract_facts_all, _split_input
from app.ingest.preprocess.video import split_by_time
from app.ingest.schemas import CardPlanBatch, ExtractedAssertion, FactExtractionResult


class FakeRawSink:
    def __init__(self):
        self.saved, self.marks = [], []

    async def save(self, context, response):
        self.saved.append((context, response))
        return 100 + len(self.saved)

    async def mark_parsed(self, store_id, raw_response_id, *, parsed_ok, error):
        self.marks.append((raw_response_id, parsed_ok, error))


def _ctx(stage="EXTRACT"):
    return UsageContext(store_id="7", cost_phase="REGISTRATION", stage=stage,
                        logical_call_id=f"job3:src5:{stage.lower()}", job_id="3", source_id="5")


def _gemini_settings(**kw):
    return NS(**({"gemini_api_key": "synthetic", "gemini_model": "gemini-synthetic",
                  "ingest_mode": "real", "extract_temperature": 0.0, "gemini_request_timeout_sec": 300,
                  "extract_max_output_tokens": 4000, "assemble_max_output_tokens": 6000} | kw))


def _pipeline_settings(depth=2, concurrency=1):
    return NS(extract_truncation_split_max_depth=depth, extract_segment_concurrency=concurrency)


def _facts_json(lines: list[str]) -> str:
    return json.dumps({"assertions": [
        dict(local_ref=f"f{i}", original_assertion=line, subject=line, attribute="값",
             value=str(i), confidence=.9, requires=[f"f{i - 1}"] if i > 1 else [])
        for i, line in enumerate(lines, 1)]}, ensure_ascii=False)


def _truncating_call(limit: int, calls: list):
    """자료 줄 수가 limit 을 넘으면 잘린 응답을, 아니면 그 줄들의 사실을 준다."""
    async def fake_call(prompt, media, schema=None, max_output_tokens=None):
        body = prompt.split("<<", 1)[1].rsplit(">>", 1)[0] if "<<" in prompt else ""
        lines = [ln for ln in body.splitlines() if ln.startswith("줄")]
        calls.append(lines)
        if len(lines) > limit:
            return gemini.CallResult('{"assertions": [{"local_ref": "f1"', {}, "MAX_TOKENS")
        return gemini.CallResult(_facts_json(lines), {}, "STOP")
    return fake_call


async def _run_real(segments, *, text="", limit=1, depth=2, concurrency=1,
                    checkpoint=None, sink=None, calls=None):
    """실제 gemini 경로(기록·파싱)를 돌리되 모델 호출만 대역으로 바꾼다."""
    calls = [] if calls is None else calls
    base = (7, 3, "REGISTRATION", "PRODUCT", None, None)
    prompt_template = "사실만 뽑아라\n<<{transcript}>>"
    with patch.object(extract, "get_settings", return_value=NS(ingest_mode="real")), \
         patch.object(gemini, "get_settings", return_value=_gemini_settings()), \
         patch.object(gemini, "FACTS_PROMPT_PATH",
                      NS(read_text=lambda encoding=None: prompt_template)), \
         patch.object(gemini, "_call", _truncating_call(limit, calls)), \
         patch("app.config.get_settings", return_value=_pipeline_settings(depth, concurrency)):
        return await _extract_facts_all(
            source_id=5, source_type="VOICE", text=text, media=[], glossary=[],
            segments=segments, usage_base=base, raw_sink=sink, checkpoint=checkpoint)


# ── 설정: 출력 상한·분할·timeout 이 config 에 모인다 ────────────────────

def test_settings_gather_limits_with_behaviour_preserving_defaults():
    s = Settings(_env_file=None)
    # 측정 전이라 출력 상한은 비워 둔다 — 공급자 기본값 그대로(기존 동작)
    assert s.extract_max_output_tokens is None and s.assemble_max_output_tokens is None
    # 분할 재추출은 새 기능이다. 플래그(깊이) 기본값은 꺼 둔다
    assert s.extract_truncation_split_max_depth == 0
    assert s.extract_segment_concurrency == 1
    assert s.video_segment_overlap_sec == 0
    # 이미 있던 값은 옮기기만 한다
    assert s.gemini_file_active_timeout_sec == 600 and s.gemini_file_poll_sec == 5


def test_overlap_must_be_smaller_than_window():
    with pytest.raises(ValueError):
        Settings(_env_file=None, video_segment_sec=60, video_segment_overlap_sec=60)


# ── gemini: max_output_tokens 전달 ──────────────────────────────────────

@pytest.mark.asyncio
async def test_call_passes_max_output_tokens_to_config():
    res = NS(text="{}", usage_metadata=None, candidates=[])
    generate = AsyncMock(return_value=res)
    client = NS(aio=NS(models=NS(generate_content=generate)))
    with patch.object(gemini, "get_settings", return_value=_gemini_settings()), \
         patch("google.genai.Client", return_value=client):
        await gemini._call("p", [], FactExtractionResult, max_output_tokens=1234)
    assert generate.await_args.kwargs["config"].max_output_tokens == 1234


_PLAN_ENTITIES = [{"대상": "음료Z", "사실": [
    {"id": "F1", "규격": "", "순서": 0, "부정": False}]}]


@pytest.mark.asyncio
async def test_extract_and_assemble_use_their_own_limits():
    seen = []

    async def fake_call(prompt, media, schema=None, max_output_tokens=None):
        seen.append(max_output_tokens)
        body = (_facts_json(["줄1"]) if schema is FactExtractionResult
                else CardPlanBatch().model_dump_json())
        return gemini.CallResult(body, {}, "STOP")

    with patch.object(gemini, "get_settings", return_value=_gemini_settings()), \
         patch.object(gemini, "_call", fake_call):
        await gemini.extract_facts(source_id=5, source_type="VOICE", text="t", glossary=[])
        await gemini.assemble_plan(source_id=5, entities=_PLAN_ENTITIES, category_names=["기타"],
                                   glossary=[])
    assert seen == [4000, 6000]


# ── gemini: 잘린 응답은 성공이 아니다 ───────────────────────────────────

@pytest.mark.asyncio
async def test_truncated_extract_is_rejected_and_marked_even_if_json_parses():
    """잘린 응답이 우연히 올바른 JSON 이어도 성공으로 처리하지 않는다."""
    sink = FakeRawSink()
    call = AsyncMock(return_value=gemini.CallResult(_facts_json(["줄1"]), {}, "MAX_TOKENS"))
    with patch.object(gemini, "get_settings", return_value=_gemini_settings()), \
         patch.object(gemini, "_call", call):
        with pytest.raises(raw_responses.TruncatedOutputError):
            await gemini.extract_facts(source_id=5, source_type="VOICE", text="t", glossary=[],
                                       usage_context=_ctx(), raw_sink=sink)
    # 같은 호출을 되풀이하지 않는다 — 잘림은 호출 예외가 아니다
    assert call.await_count == 1
    assert sink.saved[0][1].finish_reason == "MAX_TOKENS"
    raw_id, ok, error = sink.marks[0]
    assert raw_id == 101 and ok is False and "MAX_TOKENS" in error


@pytest.mark.asyncio
async def test_truncated_assembly_fails_clearly():
    sink = FakeRawSink()
    body = CardPlanBatch().model_dump_json()
    with patch.object(gemini, "get_settings", return_value=_gemini_settings()), \
         patch.object(gemini, "_call", AsyncMock(return_value=gemini.CallResult(body, {}, "MAX_TOKENS"))):
        with pytest.raises(raw_responses.TruncatedOutputError, match="조립"):
            await gemini.assemble_plan(source_id=5, entities=_PLAN_ENTITIES, category_names=["기타"],
                                       glossary=[], usage_context=_ctx("ASSEMBLE"), raw_sink=sink)
    assert sink.marks[0][1] is False


# ── 분할 규칙 ──────────────────────────────────────────────────────────

def test_split_input_halves_text_on_line_boundary():
    assert _split_input("a\nb\nc\nd", []) == [("a\nb", []), ("c\nd", [])]
    assert _split_input("a\nb\nc", []) == [("a", []), ("b\nc", [])]


def test_split_input_halves_media_front_and_back():
    media = [Path(f"f{i}.jpg") for i in range(5)]
    assert _split_input("설명", media) == [("설명", media[:2]), ("설명", media[2:])]
    assert _split_input("a\nb", media[:2]) == [("a", media[:1]), ("b", media[1:2])]


def test_split_input_refuses_what_cannot_be_halved():
    assert _split_input("한 줄", []) is None
    assert _split_input("", []) is None
    # 첨부 하나(문서·캡처)는 글을 나눠도 매번 통째로 들어가 출력이 줄지 않는다
    assert _split_input("a\nb", [Path("doc.pdf")]) is None


# ── 파이프라인: 분할 재추출 ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_truncated_segment_is_split_and_all_facts_are_gathered():
    sink, calls, saved = FakeRawSink(), [], []

    async def checkpoint(assertions, segment_id):
        saved.append((segment_id, [a.local_ref for a in assertions]))

    outcome = await _run_real([("줄1\n줄2", []), ("줄3", [])], limit=1, sink=sink,
                              calls=calls, checkpoint=checkpoint)
    assert calls == [["줄1", "줄2"], ["줄1"], ["줄2"], ["줄3"]]
    assert [a.subject for a in outcome.assertions] == ["줄1", "줄2", "줄3"]
    assert [a.local_ref for a in outcome.assertions] == ["seg1.1:f1", "seg1.2:f1", "seg2:f1"]
    # 하위 결과는 부모 구간으로 합친다 — seg{i} 구성이 그대로다
    assert [a.segment_id for a in outcome.assertions] == ["seg1", "seg1", "seg2"]
    assert outcome.segments_total == 2 and outcome.failed_segment_ids == []
    assert saved == [("seg1", ["seg1.1:f1", "seg1.2:f1"]), ("seg2", ["seg2:f1"])]
    # 잘린 응답도 원래 응답으로 남고 실패로 표시된다
    assert [c.segment_id for c, _ in sink.saved] == ["seg1", "seg1.1", "seg1.2", "seg2"]
    assert [r.finish_reason for _, r in sink.saved] == ["MAX_TOKENS", "STOP", "STOP", "STOP"]
    assert [m[1] for m in sink.marks] == [False, True, True, True]
    # 논리 호출 ID 가 하위 경로마다 다르다 (원장 unique)
    ids = [c.logical_call_id for c, _ in sink.saved]
    assert len(set(ids)) == 4 and ids[1].endswith(":seg1.1")
    assert outcome.raw_response_ids == {"seg1.1": 102, "seg1.2": 103, "seg2": 104}


@pytest.mark.asyncio
async def test_requires_are_prefixed_with_sub_path():
    outcome = await _run_real([("줄1\n줄2\n줄3\n줄4", [])], limit=2)
    first = [a for a in outcome.assertions if a.local_ref.startswith("seg1.1:")]
    assert [a.local_ref for a in first] == ["seg1.1:f1", "seg1.1:f2"]
    assert first[1].requires == ["seg1.1:f1"]


@pytest.mark.asyncio
async def test_split_recurses_until_depth_limit():
    calls = []
    outcome = await _run_real([("줄1\n줄2\n줄3\n줄4", [])], limit=1, depth=2, calls=calls)
    assert [a.local_ref for a in outcome.assertions] == [
        "seg1.1.1:f1", "seg1.1.2:f1", "seg1.2.1:f1", "seg1.2.2:f1"]
    assert len(calls) == 7


@pytest.mark.asyncio
async def test_segment_that_keeps_truncating_is_partial_with_parent_id():
    sink, saved = FakeRawSink(), []

    async def checkpoint(assertions, segment_id):
        saved.append(segment_id)

    # seg1 은 깊이 1 로 나눠도 반쪽(줄 2개)이 여전히 잘린다
    outcome = await _run_real([("줄1\n줄2\n줄3\n줄4", []), ("줄5", [])], limit=1, depth=1,
                              sink=sink, checkpoint=checkpoint)
    assert outcome.failed_segment_ids == ["seg1"] and outcome.segments_failed == 1
    assert outcome.segments_total == 2
    # 부분 결과를 원장에 적지 않는다 — PARTIAL 재시도가 seg1 전체를 다시 뽑는다
    assert saved == ["seg2"]
    assert [a.local_ref for a in outcome.assertions] == ["seg2:f1"]
    # 한 반쪽이 끝내 잘리면 나머지 반쪽은 부르지 않는다 — 어차피 구간 전체를 다시 뽑는다
    assert [r.finish_reason for _, r in sink.saved].count("MAX_TOKENS") == 2


@pytest.mark.asyncio
async def test_partial_success_inside_segment_still_fails_whole_segment():
    # 앞 반쪽은 되고 뒤 반쪽은 더 못 나눈다(한 줄에도 잘림)
    async def fake_extract_facts(**kw):
        if "줄2" in kw["text"]:
            raise raw_responses.TruncatedOutputError("합성 잘림")
        return FactExtractionResult.model_validate_json(_facts_json(["줄1"]))

    with patch.object(extract, "extract_facts", side_effect=fake_extract_facts), \
         patch("app.config.get_settings", return_value=_pipeline_settings(depth=3)):
        outcome = await _extract_facts_all(
            source_id=5, source_type="VOICE", text="", media=[], glossary=[],
            segments=[("줄1\n줄2", []), ("줄3", [])])
    assert outcome.failed_segment_ids == ["seg1"]
    assert [a.local_ref for a in outcome.assertions] == ["seg2:f1"]


@pytest.mark.asyncio
async def test_split_disabled_by_default_depth_zero_fails_segment_with_one_call():
    calls = []
    outcome = await _run_real([("줄1\n줄2", []), ("줄3", [])], limit=1, depth=0, calls=calls)
    assert outcome.failed_segment_ids == ["seg1"]
    assert calls == [["줄1", "줄2"], ["줄3"]]


@pytest.mark.asyncio
async def test_unsegmented_source_splits_with_whole_prefix():
    outcome = await _run_real([], text="줄1\n줄2", limit=1)
    assert [a.local_ref for a in outcome.assertions] == ["whole.1:f1", "whole.2:f1"]
    assert all(a.segment_id is None for a in outcome.assertions)
    assert outcome.segments_total == 1 and outcome.failed_segment_ids == []


@pytest.mark.asyncio
async def test_unsegmented_source_untruncated_keeps_plain_refs():
    outcome = await _run_real([], text="줄1", limit=1)
    assert [a.local_ref for a in outcome.assertions] == ["f1"]


@pytest.mark.asyncio
async def test_unsegmented_source_that_keeps_truncating_fails_clearly():
    saved = []

    async def checkpoint(assertions, segment_id):
        saved.append(segment_id)

    with pytest.raises(raw_responses.TruncatedOutputError, match="잘"):
        await _run_real([], text="줄1\n줄2\n줄3\n줄4", limit=1, depth=1, checkpoint=checkpoint)
    assert saved == []


@pytest.mark.asyncio
async def test_all_segments_truncating_is_a_failure_not_success():
    with pytest.raises(RuntimeError, match="모든 구간"):
        await _run_real([("줄1\n줄2", []), ("줄3\n줄4", [])], limit=0, depth=1)


# ── 동시 호출 수 ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_segment_concurrency_runs_in_parallel_but_merges_in_order():
    running = {"now": 0, "max": 0}

    async def fake_extract_facts(**kw):
        running["now"] += 1
        running["max"] = max(running["max"], running["now"])
        await asyncio.sleep(0.01 if "줄1" in kw["text"] else 0)
        running["now"] -= 1
        return FactExtractionResult.model_validate_json(_facts_json([kw["text"]]))

    with patch.object(extract, "extract_facts", side_effect=fake_extract_facts), \
         patch("app.config.get_settings", return_value=_pipeline_settings(concurrency=2)):
        outcome = await _extract_facts_all(
            source_id=5, source_type="VOICE", text="", media=[], glossary=[],
            segments=[("줄1", []), ("줄2", []), ("줄3", [])])
    assert running["max"] == 2
    assert [a.local_ref for a in outcome.assertions] == ["seg1:f1", "seg2:f1", "seg3:f1"]


# ── 겹침 · 복구 구성 ───────────────────────────────────────────────────

def test_split_by_time_overlap_repeats_boundary_lines():
    segs = [{"start": 50, "end": 55, "text": "앞 구간 끝"}, {"start": 70, "end": 75, "text": "뒤"}]
    with patch("app.ingest.preprocess.video.get_settings",
               return_value=NS(frame_interval_sec=3, video_max_frames_to_model=20)):
        plain = split_by_time(segs, [], 60)
        overlapped = split_by_time(segs, [], 60, overlap_sec=15)
    assert "앞 구간 끝" not in plain[1][0]
    assert "앞 구간 끝" in overlapped[1][0] and len(overlapped) == len(plain)


def test_layout_hash_unchanged_without_overlap_and_changed_with_it(tmp_path):
    base = dict(video_segment_sec=60, frame_interval_sec=3, video_max_frames_to_model=20,
                video_input_mode="frames", pdf_input_mode="HYBRID")
    src = dict(source_type="VIDEO")
    legacy = recovery.layout_hash(src, "", [], [("t", [])], NS(**base))
    zero = recovery.layout_hash(src, "", [], [("t", [])], NS(**base, video_segment_overlap_sec=0))
    some = recovery.layout_hash(src, "", [], [("t", [])], NS(**base, video_segment_overlap_sec=10))
    assert legacy == zero and zero != some


@pytest.mark.asyncio
async def test_file_active_timeout_comes_from_settings(tmp_path):
    path = tmp_path / "v.mp4"
    path.write_bytes(b"x")
    processing = NS(state=NS(name="PROCESSING"), name="files/1")
    client = NS(aio=NS(files=NS(upload=AsyncMock(return_value=processing),
                                get=AsyncMock(return_value=processing))))
    with patch.object(gemini, "get_settings",
                      return_value=NS(gemini_file_active_timeout_sec=0, gemini_file_poll_sec=0)):
        with pytest.raises(TimeoutError, match="0초"):
            await gemini._upload_native(client, path, "video/mp4")
