"""W1-4 근거 위치(occurrence) 보존과 추정 채우기 거절.

- 같은 사실이 여러 위치에 나오면 사실 한 행 + 위치 여러 개로 남는다.
- 위치 표지: PDF `[N쪽]`, 카톡 `[#N]`, 음성·영상 `[mm:ss]`.
- 서버는 입력에 없는 쪽·줄, 지어낸 단위·규격, 없는 선행 참조를 거절하고 사유를 남긴다.
외부 모델은 부르지 않는다. 모든 자료는 합성이다.
"""
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

import pytest

from app.ingest import occurrences, pipeline
from app.ingest.preprocess import kakao
from app.ingest.raw_responses import schema_version
from app.ingest.schemas import (Evidence, ExtractedAssertion,
                                FactExtractionResult, LocatedAssertion, LocatedEvidence,
                                LocatedFactExtractionResult)

ON = dict(locator_hints=True)
# 근거 없는 값 비우기 플래그(extract_clear_ungrounded_values) 켠 판. 기본은 기록만
CLEAR = dict(clear_ungrounded=True)


def _a(ref="f1", *, subject="음료Z", attribute="물", value="10", unit="", variant="",
       original="음료Z 물 10ml", page=0, line=0, ts=0, requires=()):
    return LocatedAssertion(
        local_ref=ref, original_assertion=original, subject=subject, attribute=attribute,
        value=value, unit=unit, variant=variant, confidence=.9, requires=list(requires),
        evidence=LocatedEvidence(page=page, line=line, timestamp_sec=ts))


PDF_TEXT = "[1쪽]\n음료Z 는 물 10ml 를 넣는다.\n\n[2쪽]\n다시 한번: 음료Z 는 물 10ml 를 넣는다."


# ── 스키마 ──────────────────────────────────────────────────────────────

def test_located_evidence_has_page_and_line_with_zero_defaults():
    ev = LocatedEvidence()
    assert (ev.page, ev.line, ev.timestamp_sec) == (0, 0, 0)
    schema = LocatedFactExtractionResult.model_json_schema()
    props = schema["$defs"]["LocatedEvidence"]["properties"]
    assert {"page", "line"} <= set(props)


def test_default_schemas_unchanged_by_locator_hints():
    # HEAD(630db77) 의 schemas.py 로 잰 값. 기본(위치 힌트 없음) 요청 스키마가 바뀌지 않았음을 못 박는다
    assert schema_version(FactExtractionResult) == "FactExtractionResult/286f526e798a"
    assert set(Evidence.model_fields) == {"source_id", "timestamp_sec"}


def test_schema_and_prompt_are_chosen_by_flag():
    from app.ingest.extract import gemini
    assert gemini.facts_schema(NS()) is FactExtractionResult
    assert gemini.facts_schema(NS(extract_locator_hints=False)) is FactExtractionResult
    assert gemini.facts_schema(NS(extract_locator_hints=True)) is LocatedFactExtractionResult
    off = gemini.render_facts_prompt(source_type="SCAN", text="t", glossary=[])
    on = gemini.render_facts_prompt(source_type="SCAN", text="t", glossary=[], locator_hints=True)
    assert off != on and "[#12]" in on and "[#12]" not in off
    # 재사용 키는 완성 프롬프트와 스키마 버전을 hash 한다 — 플래그를 따로 넣지 않아도 갈린다
    assert schema_version(FactExtractionResult) != schema_version(LocatedFactExtractionResult)


@pytest.mark.asyncio
async def test_reuse_key_differs_by_flag_without_a_flag_input():
    from app.config import Settings
    from app.contracts.usage import UsageContext
    from app.ingest import reuse
    from app.ingest.extract import gemini
    ctx = UsageContext(store_id="7", cost_phase="REGISTRATION", stage="EXTRACT",
                       logical_call_id="job3:src5:extract", job_id="3", source_id="5")
    keys = []
    for hints in (False, True):
        s = Settings(_env_file=None, extract_locator_hints=hints)
        keys.append(await reuse.key_for(
            ctx, s, model="m", mode="real",
            prompt=gemini.render_facts_prompt(source_type="SCAN", text="t", glossary=[],
                                              locator_hints=hints),
            media=[], schema=gemini.facts_schema(s), max_output_tokens=None))
    assert keys[0] != keys[1]


def test_assertion_raw_response_id_is_not_part_of_the_model_schema():
    schema = ExtractedAssertion.model_json_schema()
    assert "raw_response_id" not in schema["properties"]
    assert "_raw_response_id" not in schema["properties"]


# ── 전처리 표지 ─────────────────────────────────────────────────────────

def test_kakao_parsed_text_numbers_each_message():
    raw = ("2026년 8월 25일 오전 9:12, 사장님 : 우유는 냉장고 2단\n"
           "두 번째 줄\n"
           "2026년 8월 25일 오전 9:13, 알바 : 네\n")
    assert kakao.parse(raw)["parsed_text"].splitlines()[0] == "[08-25 09:12] 사장님: 우유는 냉장고 2단"
    parsed = kakao.parse(raw, message_numbers=True)
    lines = parsed["parsed_text"].splitlines()
    assert lines[0].startswith("[#1] [08-25 09:12] 사장님: 우유는 냉장고 2단")
    assert lines[1] == "두 번째 줄"
    assert lines[2].startswith("[#2] [08-25 09:13] 알바: 네")


def test_prompt_explains_page_and_line_markers():
    from app.ingest.extract.gemini import FACTS_LOCATOR_PROMPT_PATH, FACTS_PROMPT_PATH
    assert "[#12]" not in FACTS_PROMPT_PATH.read_text(encoding="utf-8")
    prompt = FACTS_LOCATOR_PROMPT_PATH.read_text(encoding="utf-8")
    assert "[3쪽]" in prompt and "[#12]" in prompt and "`page`" in prompt and "`line`" in prompt


# ── 위치 ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("source_type,evidence,expected", [
    ("SCAN", LocatedEvidence(page=2), ("PAGE", {"page": 2})),
    ("KAKAO", LocatedEvidence(line=7), ("LINE", {"line": 7})),
    ("VOICE", LocatedEvidence(timestamp_sec=65), ("TIMESTAMP", {"timestamp_sec": 65})),
    ("VIDEO", Evidence(timestamp_sec=5), ("TIMESTAMP", {"timestamp_sec": 5})),
    ("SCAN", LocatedEvidence(), ("WHOLE_SOURCE", {})),
    ("KAKAO", LocatedEvidence(timestamp_sec=40), ("WHOLE_SOURCE", {})),
    ("VOICE", LocatedEvidence(page=3), ("WHOLE_SOURCE", {})),
    ("SCAN", Evidence(), ("WHOLE_SOURCE", {})),
])
def test_locator_for(source_type, evidence, expected):
    assert occurrences.locator_for(source_type, evidence, **ON) == expected


def test_locator_for_ignores_page_and_line_by_default():
    assert occurrences.locator_for("SCAN", LocatedEvidence(page=2)) == ("WHOLE_SOURCE", {})
    assert occurrences.locator_for("KAKAO", LocatedEvidence(line=2)) == ("WHOLE_SOURCE", {})
    assert occurrences.locator_for("VOICE", Evidence(timestamp_sec=9)) == (
        "TIMESTAMP", {"timestamp_sec": 9})


def test_page_is_not_checked_by_default():
    items = [_a(page=9)]
    assert occurrences.validate_assertions(items, source_type="SCAN", text=PDF_TEXT,
                                           media=[]) == []


def test_occurrence_hash_ignores_local_ref_and_raw_response_but_not_location():
    h1 = occurrences.occurrence_hash(segment_id=None, locator_type="PAGE", locator={"page": 1})
    h2 = occurrences.occurrence_hash(segment_id=None, locator_type="PAGE", locator={"page": 2})
    assert h1 != h2
    assert h1 == occurrences.occurrence_hash(segment_id=None, locator_type="PAGE",
                                             locator={"page": 1})
    assert h1 != occurrences.occurrence_hash(segment_id="seg1", locator_type="PAGE",
                                             locator={"page": 1})


# ── 서버 검사 ───────────────────────────────────────────────────────────

def test_page_within_text_markers_is_kept():
    items = [_a(page=2)]
    reasons = occurrences.validate_assertions(items, source_type="SCAN", text=PDF_TEXT, media=[],
                                              **ON)
    assert reasons == [] and items[0].evidence.page == 2


def test_out_of_range_page_falls_back_to_whole_source_and_is_recorded():
    items = [_a(page=9)]
    reasons = occurrences.validate_assertions(items, source_type="SCAN", text=PDF_TEXT, media=[],
                                              **ON)
    assert items[0].evidence.page == 0
    assert occurrences.locator_for("SCAN", items[0].evidence) == ("WHOLE_SOURCE", {})
    assert len(reasons) == 1 and "f1" in reasons[0] and "9쪽" in reasons[0]


def test_page_of_attached_pdf_is_checked_against_its_page_count(tmp_path):
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-synthetic")
    with patch.object(occurrences, "pdf_page_count", return_value=3):
        ok = [_a(page=3)]
        assert occurrences.validate_assertions(
            ok, source_type="SCAN", text="(첨부한 문서를 읽고 판단할 것)", media=[pdf], **ON) == []
        bad = [_a(page=4)]
        reasons = occurrences.validate_assertions(
            bad, source_type="SCAN", text="(첨부한 문서를 읽고 판단할 것)", media=[pdf], **ON)
    assert ok[0].evidence.page == 3 and bad[0].evidence.page == 0 and len(reasons) == 1


def test_line_must_exist_among_kakao_markers():
    text = "[#1] [08-25 09:12] 사장님: 음료Z 물 10ml\n[#2] [08-25 09:13] 알바: 네"
    ok, bad = _a("f1", line=1), _a("f2", line=5)
    reasons = occurrences.validate_assertions([ok, bad], source_type="KAKAO", text=text, media=[],
                                              **ON)
    assert ok.evidence.line == 1 and bad.evidence.line == 0
    assert len(reasons) == 1 and "f2" in reasons[0] and "5" in reasons[0]


def test_page_or_line_on_a_source_without_that_locator_is_rejected():
    items = [_a(page=1, line=3, ts=12)]
    reasons = occurrences.validate_assertions(items, source_type="VOICE",
                                              text="[00:12] 음료Z 물 10ml", media=[], **ON)
    assert (items[0].evidence.page, items[0].evidence.line, items[0].evidence.timestamp_sec) == (0, 0, 12)
    assert len(reasons) == 2


def test_invented_unit_is_cleared_and_recorded_but_fact_kept():
    items = [_a(unit="g", original="음료Z 물 10")]
    reasons = occurrences.validate_assertions(items, source_type="SCAN",
                                              text="[1쪽]\n음료Z 물 10", media=[], **CLEAR)
    assert items[0].unit == "" and items[0].value == "10"
    assert len(reasons) == 1 and "단위" in reasons[0] and "'g'" in reasons[0]


def test_unit_present_in_text_or_as_a_known_alias_is_kept():
    items = [_a("f1", unit="ml", original="음료Z 물 10"), _a("f2", unit="ml", original="물 10밀리리터")]
    reasons = occurrences.validate_assertions(
        items, source_type="SCAN", text="[1쪽]\n음료Z 물 10ml\n물 10밀리리터", media=[])
    assert reasons == [] and [a.unit for a in items] == ["ml", "ml"]


def test_ascii_unit_does_not_match_inside_another_word():
    # 'l' 은 'ml' 안에도 있다 — 영문 글자 사이의 부분 일치는 근거가 아니다
    items = [_a(unit="l", original="음료Z 물 10ml")]
    reasons = occurrences.validate_assertions(items, source_type="SCAN",
                                              text="[1쪽]\n음료Z 물 10ml", media=[], **CLEAR)
    assert items[0].unit == "" and len(reasons) == 1


def test_invented_variant_is_cleared_and_recorded():
    items = [_a(variant="HOT", original="음료Z 물 10ml")]
    reasons = occurrences.validate_assertions(items, source_type="SCAN",
                                              text="[1쪽]\n음료Z 물 10ml", media=[], **CLEAR)
    assert items[0].variant == "" and len(reasons) == 1 and "규격" in reasons[0]


def test_ice_variant_backed_by_ice_procedure_is_kept():
    # 프롬프트 규칙 3 — 얼음 절차가 확인되면 ICE 라는 낱말이 없어도 ICE 다
    items = [_a(variant="ICE", original="컵에 얼음을 채우고 음료Z 를 붓는다")]
    reasons = occurrences.validate_assertions(
        items, source_type="SCAN", text="[1쪽]\n컵에 얼음을 채우고 음료Z 를 붓는다", media=[])
    assert reasons == [] and items[0].variant == "ICE"


def _needs_image_check(reasons, count):
    return (len(reasons) == count
            and all(occurrences.NEEDS_IMAGE_CHECK in r for r in reasons))


def test_media_only_input_keeps_unit_and_variant_and_records_image_check(tmp_path):
    image = tmp_path / "menu.png"
    image.write_bytes(b"synthetic")
    items = [_a(unit="g", variant="HOT", original="음료Z 물 10")]
    reasons = occurrences.validate_assertions(
        items, source_type="SCAN", text="(이미지 자료. 첨부한 그림을 읽고 판단할 것)", media=[image])
    assert (items[0].unit, items[0].variant) == ("g", "HOT") and _needs_image_check(reasons, 2)


def test_video_segment_transcript_plus_frames_keeps_value_seen_only_in_frames(tmp_path):
    frames = [tmp_path / "f1.jpg", tmp_path / "f2.jpg"]
    items = [_a(unit="g", variant="ICE", original="음료Z 원두 18", value="18")]
    reasons = occurrences.validate_assertions(
        items, source_type="VIDEO", text="[00:05] 원두를 18 정도 넣어요", media=frames)
    assert (items[0].unit, items[0].variant) == ("g", "ICE") and _needs_image_check(reasons, 2)


def test_pdf_both_mode_text_plus_document_keeps_value(tmp_path):
    pdf = tmp_path / "doc.pdf"
    text = "[1쪽]\n음료Z 물 10\n\n(첨부한 문서도 함께 읽고 판단할 것)"
    items = [_a(unit="ml", original="음료Z 물 10")]
    reasons = occurrences.validate_assertions(items, source_type="SCAN", text=text, media=[pdf])
    assert items[0].unit == "ml" and _needs_image_check(reasons, 1)


def test_pdf_hybrid_mode_with_visual_pages_keeps_value(tmp_path):
    pdf = tmp_path / "doc.pdf"
    text = ("[1쪽]\n음료Z 물 10\n\n"
            "(위 글에 없는 내용이 3쪽 에 그림·표로 있다. 첨부한 문서의 해당 쪽을 읽고 판단할 것)")
    items = [_a(variant="HOT", original="음료Z 물 10")]
    reasons = occurrences.validate_assertions(items, source_type="SCAN", text=text, media=[pdf])
    assert items[0].variant == "HOT" and _needs_image_check(reasons, 1)


def test_text_only_input_still_clears_with_clear_flag():
    items = [_a(unit="g", variant="HOT", original="음료Z 물 10")]
    reasons = occurrences.validate_assertions(items, source_type="SCAN",
                                              text="[1쪽]\n음료Z 물 10", media=[], **CLEAR)
    assert (items[0].unit, items[0].variant) == ("", "")
    assert len(reasons) == 2 and not any(occurrences.NEEDS_IMAGE_CHECK in r for r in reasons)


# ── 흔한 낱말 안의 단위·규격은 근거가 아니다 ─────────────────────────────

@pytest.mark.parametrize("unit,text", [
    ("도", "적정 온도를 확인한다"),          # 온도
    ("°C", "스팀도 함께 확인한다"),          # 조사 ~도
    ("분", "충분히 저어 섞는다"),            # 충분
    ("분", "나머지 부분은 버린다"),          # 부분
    ("초", "초콜릿 소스를 뿌린다"),          # 초콜릿
    ("ml", "재료를 미리 준비한다"),          # 미리(부사)
    ("%", "이번 달 프로모션 음료다"),        # 프로모션
])
def test_korean_unit_inside_a_common_word_is_not_grounding(unit, text):
    items = [_a(unit=unit, value="3", original="음료Z 시럽 3")]
    reasons = occurrences.validate_assertions(items, source_type="SCAN",
                                              text=f"[1쪽]\n{text}", media=[], **CLEAR)
    assert items[0].unit == "" and len(reasons) == 1


@pytest.mark.parametrize("unit,text", [
    ("분", "3분 동안 우린다"), ("분", "3 분 동안 우린다"), ("초", "5초 추출"),
    ("°C", "75도 물"), ("%", "10% 할인"), ("ml", "10 미리 넣는다"),
])
def test_unit_after_a_number_is_grounding(unit, text):
    items = [_a(unit=unit, value="0", original="음료Z")]
    assert occurrences.validate_assertions(items, source_type="SCAN",
                                           text=f"[1쪽]\n{text}", media=[]) == []
    assert items[0].unit == unit


def test_unit_after_a_non_numeric_value_is_grounding():
    items = [_a(unit="컵", value="반", original="우유 반 컵")]
    assert occurrences.validate_assertions(items, source_type="SCAN",
                                           text="[1쪽]\n우유 반 컵", media=[]) == []


@pytest.mark.parametrize("variant,text", [
    ("ICE", "얼음 보관은 냉동고 아래 칸"),
    ("ICE", "이 음료에는 얼음 투입 금지"),
    ("ICE", "얼음을 넣지 않는다"),
    ("ICE", "아이스크림을 올린다"),
    ("ICE", "제빙기 얼음 스쿱을 세척한다"),
    ("HOT", "뜨거운 물로 스팀 노즐을 닦는다"),
    ("HOT", "따뜻한 곳에 두지 않는다"),
])
def test_ice_hot_words_outside_spec_sense_are_not_grounding(variant, text):
    items = [_a(variant=variant, original="음료Z 시럽 3", value="3")]
    reasons = occurrences.validate_assertions(items, source_type="SCAN",
                                              text=f"[1쪽]\n{text}", media=[], **CLEAR)
    assert items[0].variant == "" and len(reasons) == 1


@pytest.mark.parametrize("variant,text", [
    ("ICE", "컵에 얼음을 채우고 붓는다"), ("ICE", "얼음과 함께 갈아 만든다"),
    ("ICE", "아이스 음료Z"), ("ICE", "ICED 음료Z"),
    ("HOT", "핫 음료Z"), ("HOT", "뜨거운 음료로 제공"), ("HOT", "HOT 275ml"),
])
def test_ice_hot_in_spec_sense_is_grounding(variant, text):
    items = [_a(variant=variant, original="음료Z", value="3")]
    assert occurrences.validate_assertions(items, source_type="SCAN",
                                           text=f"[1쪽]\n{text}", media=[]) == []


def test_nonexistent_requires_is_removed_and_recorded():
    items = [_a("seg1:f1"), _a("seg1:f2", requires=["seg1:f1", "seg1:f9"])]
    reasons = occurrences.validate_assertions(items, source_type="VIDEO",
                                              text="[00:01] 음료Z 물 10ml", media=[])
    assert items[1].requires == ["seg1:f1"]
    assert len(reasons) == 1 and "seg1:f9" in reasons[0]


# ── 파이프라인: 검사 위치와 원래 응답 ID ─────────────────────────────────

def _fake_extract(results):
    """구간 글에 따라 합성 결과를 돌려주는 대역. 원래 응답 ID 를 붙인다."""
    async def fake(*, source_id, source_type, text, glossary, media=(), usage_sink=None,
                   usage_context=None, raw_sink=None):
        assertions, raw_id = results[text]
        result = FactExtractionResult(assertions=[a.model_copy(deep=True) for a in assertions])
        result._raw_response_id = raw_id
        return result
    return fake


@pytest.mark.asyncio
async def test_extract_validates_before_the_ledger_checkpoint_and_keeps_raw_response_id():
    seen = []

    async def checkpoint(assertions, segment_id):
        seen.append([(a.local_ref, a.evidence.page, a.raw_response_id) for a in assertions])

    results = {PDF_TEXT: ([_a("f1", page=1), _a("f2", page=2), _a("f3", page=7)], 501)}
    with patch("app.ingest.extract.extract_facts", _fake_extract(results)), \
         patch("app.config.get_settings", return_value=NS(
             extract_truncation_split_max_depth=0, extract_segment_concurrency=1,
             extract_locator_hints=True)):
        outcome = await pipeline._extract_facts_all(
            source_id=5, source_type="SCAN", text=PDF_TEXT, media=[], glossary=[],
            segments=[], checkpoint=checkpoint)
    assert seen == [[("f1", 1, 501), ("f2", 2, 501), ("f3", 0, 501)]]
    assert any("f3" in r and "7쪽" in r for r in outcome.unresolved)


@pytest.mark.asyncio
async def test_segment_validation_uses_that_segment_text():
    segments = [("[00:01] 음료Z 물 10ml", []), ("[01:01] 음료Y 얼음 3개", [])]
    results = {segments[0][0]: ([_a("f1", unit="ml", ts=1)], 11),
               segments[1][0]: ([_a("f1", subject="음료Y", attribute="얼음", value="3",
                                    unit="ml", original="음료Y 얼음 3개", ts=61)], 12)}
    with patch("app.ingest.extract.extract_facts", _fake_extract(results)), \
         patch("app.config.get_settings", return_value=NS(
             extract_truncation_split_max_depth=0, extract_segment_concurrency=1,
             extract_clear_ungrounded_values=True)):
        outcome = await pipeline._extract_facts_all(
            source_id=5, source_type="VOICE", text="", media=[], glossary=[],
            segments=segments)
    assert [a.unit for a in outcome.assertions] == ["ml", ""]
    assert [a.raw_response_id for a in outcome.assertions] == [11, 12]
    assert len([r for r in outcome.unresolved if "seg2:f1" in r]) == 1


# ── 원장 + 위치 저장 ─────────────────────────────────────────────────────

class _OccurrenceConn:
    """위치 insert 를 받아 unique(fact_id, occurrence_hash) 를 흉내 낸다."""

    def __init__(self):
        self.rows: dict[tuple, tuple] = {}

    async def execute(self, query, *args):
        assert "insert into source_fact_occurrences" in query
        store_id, fact_id, segment_id, local_ref, locator_type, locator, raw_id, digest, flags = args
        self.rows.setdefault((fact_id, digest), (store_id, segment_id, local_ref,
                                                 locator_type, locator, raw_id, flags))
        return "INSERT 0 1"


@pytest.fixture(autouse=True)
def _no_ledger_link():
    # 원장 연결(대상·판)은 이 파일의 관심사가 아니다 — occurrence 쓰기만 본다
    with patch("app.ingest.fact_ledger.link_source_facts", AsyncMock()):
        yield


def _settings(hints=True):
    return NS(gemini_model="gemini-synthetic", extract_temperature=0.0, ingest_mode="mock",
              extract_locator_hints=hints)


@pytest.mark.asyncio
async def test_same_fact_on_two_pages_is_one_fact_with_two_occurrences():
    conn = _OccurrenceConn()
    a1, a2 = _a("f1", page=1), _a("f2", page=2)
    a1._raw_response_id = a2._raw_response_id = 501
    inserted = AsyncMock(return_value=[77, 77])   # 같은 content_hash → 같은 사실 행
    with patch.object(pipeline.repo, "insert_source_facts", inserted), \
         patch("app.config.get_settings", return_value=_settings()):
        ids = await pipeline._persist_ledger(conn, 3, 5, "SCAN", [a1, a2])
    rows = inserted.await_args.args[3]
    # 원장 행의 locator 는 사실마다 첫 위치를 담는다(첫 insert 가 이긴다)
    assert [(r["locator_type"], r["locator"]) for r in rows] == [("PAGE", {"page": 1}),
                                                                   ("PAGE", {"page": 2})]
    assert ids == {"f1": 77, "f2": 77}
    got = sorted((v[3], v[4], v[5]) for v in conn.rows.values())
    assert got == [("PAGE", '{"page": 1}', 501), ("PAGE", '{"page": 2}', 501)]
    assert all(k[0] == 77 and v[0] == 3 for k, v in conn.rows.items())


@pytest.mark.asyncio
async def test_retrying_the_same_extraction_adds_no_duplicate_occurrences():
    conn = _OccurrenceConn()
    with patch.object(pipeline.repo, "insert_source_facts", AsyncMock(return_value=[77, 77])), \
         patch("app.config.get_settings", return_value=_settings()):
        await pipeline._persist_ledger(conn, 3, 5, "SCAN", [_a("f1", page=1), _a("f2", page=2)])
        # 재시도 — 이름표와 원래 응답이 달라도 같은 위치면 같은 occurrence 다
        again = [_a("f7", page=2), _a("f8", page=1)]
        again[0]._raw_response_id = 999
        await pipeline._persist_ledger(conn, 3, 5, "SCAN", again)
    assert len(conn.rows) == 2


@pytest.mark.asyncio
async def test_voice_and_kakao_occurrences_carry_their_locator():
    conn = _OccurrenceConn()
    with patch.object(pipeline.repo, "insert_source_facts", AsyncMock(return_value=[1])), \
         patch("app.config.get_settings", return_value=_settings()):
        await pipeline._persist_ledger(conn, 3, 5, "VOICE", [_a(ts=65)])
    with patch.object(pipeline.repo, "insert_source_facts", AsyncMock(return_value=[2])), \
         patch("app.config.get_settings", return_value=_settings()):
        await pipeline._persist_ledger(conn, 3, 6, "KAKAO", [_a(line=4)])
    assert sorted((k[0], v[3], v[4]) for k, v in conn.rows.items()) == [
        (1, "TIMESTAMP", '{"timestamp_sec": 65}'), (2, "LINE", '{"line": 4}')]


@pytest.mark.asyncio
async def test_occurrence_insert_is_scoped_to_the_store():
    conn = _OccurrenceConn()
    await occurrences.insert_occurrences(conn, 3, [dict(
        fact_id=77, segment_id=None, local_ref="f1", locator_type="PAGE",
        locator={"page": 1}, raw_response_id=None)])
    (store_id, *_), = conn.rows.values()
    assert store_id == 3


def test_occurrence_sql_filters_by_store():
    import inspect
    src = inspect.getsource(occurrences.insert_occurrences) + inspect.getsource(
        occurrences.list_occurrences)
    assert src.count("store_id = $1") >= 3


@pytest.mark.asyncio
async def test_hints_off_still_writes_occurrences_but_ignores_page():
    conn = _OccurrenceConn()
    with patch.object(pipeline.repo, "insert_source_facts", AsyncMock(return_value=[77, 78])), \
         patch("app.config.get_settings", return_value=_settings(hints=False)):
        await pipeline._persist_ledger(conn, 3, 5, "SCAN", [_a("f1", page=1), _a("f2", value="11",
                                                                                 page=2)])
    assert sorted((k[0], v[3], v[4]) for k, v in conn.rows.items()) == [
        (77, "WHOLE_SOURCE", "{}"), (78, "WHOLE_SOURCE", "{}")]


@pytest.mark.asyncio
async def test_mock_extractor_uses_the_flag_schema():
    from app.ingest.extract import mock
    with patch.object(mock, "get_settings", return_value=NS(extract_locator_hints=False)):
        off = await mock.extract_facts(source_id=1, source_type="SCAN", text="t", glossary=[])
    with patch.object(mock, "get_settings", return_value=NS(extract_locator_hints=True)):
        on = await mock.extract_facts(source_id=1, source_type="SCAN", text="t", glossary=[])
    assert type(off) is FactExtractionResult and type(on) is LocatedFactExtractionResult
    assert [a.evidence.timestamp_sec for a in off.assertions] == [
        a.evidence.timestamp_sec for a in on.assertions]


# ── 최종 수정: 기본은 기록만 (값을 비우지 않는다) ─────────────────────────
# 글만 있는 입력(음성 전사·카톡·TEXT 모드 PDF)의 근거 판정은 오탐이 있다. 값을 비우면
# content_hash 가 바뀌고 HOT/ICE 가 합쳐질 수 있다(D19). 비우기는 플래그
# `extract_clear_ungrounded_values` 뒤에만 둔다. 판정은 check_flags 로 영속한다.


def test_default_text_only_keeps_value_and_records_verdict():
    items = [_a(unit="g", variant="HOT", original="음료Z 물 10")]
    reasons = occurrences.validate_assertions(items, source_type="SCAN",
                                              text="[1쪽]\n음료Z 물 10", media=[])
    assert (items[0].unit, items[0].variant) == ("g", "HOT")
    assert len(reasons) == 2
    assert items[0].check_flags == [
        {"field": "unit", "verdict": "UNGROUNDED_TEXT", "value": "g"},
        {"field": "variant", "verdict": "UNGROUNDED_TEXT", "value": "HOT"}]


def test_clear_flag_on_text_only_clears_and_records_cleared():
    items = [_a(unit="g", variant="HOT", original="음료Z 물 10")]
    occurrences.validate_assertions(items, source_type="SCAN",
                                    text="[1쪽]\n음료Z 물 10", media=[], **CLEAR)
    assert (items[0].unit, items[0].variant) == ("", "")
    assert [f["verdict"] for f in items[0].check_flags] == ["CLEARED", "CLEARED"]
    assert [f["value"] for f in items[0].check_flags] == ["g", "HOT"]


def test_media_input_records_needs_image_check_even_with_clear_flag(tmp_path):
    image = tmp_path / "menu.png"
    image.write_bytes(b"synthetic")
    items = [_a(unit="g", original="음료Z 물 10")]
    occurrences.validate_assertions(items, source_type="SCAN", text="", media=[image], **CLEAR)
    assert items[0].unit == "g"
    assert items[0].check_flags == [{"field": "unit", "verdict": "NEEDS_IMAGE_CHECK", "value": "g"}]


def test_removed_requires_is_recorded_in_check_flags():
    items = [_a("seg1:f1"), _a("seg1:f2", requires=["seg1:f1", "seg1:f9"])]
    occurrences.validate_assertions(items, source_type="VIDEO",
                                    text="[00:01] 음료Z 물 10ml", media=[])
    assert items[1].check_flags == [{"field": "requires", "verdict": "REMOVED", "value": "seg1:f9"}]
    assert items[0].check_flags == []


def test_check_flags_are_not_part_of_the_model_schema():
    assert "check_flags" not in ExtractedAssertion.model_json_schema()["properties"]
    assert schema_version(FactExtractionResult) == "FactExtractionResult/286f526e798a"


def test_check_flags_survive_deep_copy():
    a = _a(unit="g", original="음료Z 물 10")
    occurrences.validate_assertions([a], source_type="SCAN", text="음료Z 물 10", media=[])
    assert a.model_copy(deep=True).check_flags == a.check_flags


@pytest.mark.parametrize("unit,value,text", [
    ("샷", "2", "에스프레소 두 샷"),
    ("번", "3", "펌프 세 번"),
    ("분", "15", "십오 분"),
    ("분", "15", "십오분 우린다"),
    ("번", "12", "열두 번 젓는다"),
    ("컵", "0.5", "우유 반 컵"),
    ("분", "20", "이십 분 이내"),
])
def test_korean_number_words_before_unit_are_grounding(unit, value, text):
    assert occurrences.unit_grounded(unit, value, text)


@pytest.mark.parametrize("variant,text", [
    ("HOT", "따뜻하게 드실 경우"),
    ("HOT", "뜨겁게 드시는 분께는"),
    ("HOT", "따뜻한 건 머그에 담는다"),
    ("ICE", "차가운 음료로 제공"),
    ("ICE", "차갑게 드실 경우"),
    ("ICE", "시원한 걸로 주문하면"),
    ("L", "라지 사이즈"),
    ("R", "레귤러 사이즈"),
    ("S", "스몰 사이즈"),
    ("TALL", "톨 사이즈"),
    ("GRANDE", "그란데 사이즈"),
    ("LARGE", "라지 컵"),
])
def test_spoken_variant_words_are_grounding(variant, text):
    assert occurrences.variant_grounded(variant, text)


@pytest.mark.parametrize("variant,text", [
    ("ICE", "차가운 물로 헹군다"),
    ("HOT", "뜨겁게 데운 물로 세척한다"),
    ("L", "ml 단위로 잰다"),
])
def test_widened_variant_words_outside_spec_sense_are_not_grounding(variant, text):
    assert not occurrences.variant_grounded(variant, text)


@pytest.mark.asyncio
async def test_occurrence_row_carries_check_flags_but_hash_ignores_them():
    conn = _OccurrenceConn()
    a1 = _a("f1", unit="g", original="음료Z 물 10", page=1)
    occurrences.validate_assertions([a1], source_type="SCAN", text="음료Z 물 10", media=[])
    with patch.object(pipeline.repo, "insert_source_facts", AsyncMock(return_value=[77])), \
         patch("app.config.get_settings", return_value=_settings()):
        await pipeline._persist_ledger(conn, 3, 5, "SCAN", [a1])
        # 재시도 — 판정이 달라도(없어도) 같은 자리면 같은 occurrence 다
        await pipeline._persist_ledger(conn, 3, 5, "SCAN", [_a("f9", page=1)])
    assert len(conn.rows) == 1
    (row,) = conn.rows.values()
    assert row[-1] == '[{"field": "unit", "verdict": "UNGROUNDED_TEXT", "value": "g"}]'


@pytest.mark.asyncio
async def test_pipeline_passes_clear_flag_from_settings():
    segments = [("[00:01] 음료Z 물 10", [])]
    results = {segments[0][0]: ([_a("f1", unit="g", original="음료Z 물 10", ts=1)], 11)}
    for flag, expected in ((False, "g"), (True, "")):
        with patch("app.ingest.extract.extract_facts", _fake_extract(results)), \
             patch("app.config.get_settings", return_value=NS(
                 extract_truncation_split_max_depth=0, extract_segment_concurrency=1,
                 extract_clear_ungrounded_values=flag)):
            outcome = await pipeline._extract_facts_all(
                source_id=5, source_type="VOICE", text="", media=[], glossary=[],
                segments=segments)
        assert outcome.assertions[0].unit == expected


def test_clear_flag_defaults_off():
    from app.config import Settings
    assert Settings.model_fields["extract_clear_ungrounded_values"].default is False
