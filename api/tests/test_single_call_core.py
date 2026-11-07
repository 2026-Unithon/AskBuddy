"""한 번 호출 추출의 순수 로직 — 줄 번호, 끊김 판정, 이어서 뽑기 입력, 결과 합치기 (설계 §4-3·§4-4)."""
from app.ingest.extract import single_call as sc
from app.ingest.schemas import SingleCallExtractionResult


def _result(assertions=(), coverage=(), ranking=(("RECIPE", 0.9),)):
    return SingleCallExtractionResult.model_validate({
        "assertions": [
            {"local_ref": ref, "original_assertion": f"원문 {ref}", "subject": subj, "attribute": "양",
             "value": val, "confidence": 0.9, "evidence": {"line": line}}
            for ref, subj, val, line in assertions],
        "coverage": [{"line": n, "refs": list(refs), "no_content": nc} for n, refs, nc in coverage],
        "intake_ranking": [{"logic": lg, "score": sc_} for lg, sc_ in ranking],
    })


# ── 줄 번호 ──────────────────────────────────────────────────────────

def test_number_lines_skips_blank_and_page_marks():
    text = "[1쪽]\n제목\n\n우유 200ml\n[2쪽]\n얼음 가득"
    numbered, ids = sc.number_lines(text)
    assert numbered == "[1쪽]\n[#1] 제목\n\n[#2] 우유 200ml\n[2쪽]\n[#3] 얼음 가득"
    assert ids == [1, 2, 3]


def test_number_lines_reuses_existing_message_numbers():
    text = "[#1] 사장님: 안녕\n[#2] 사장님: 우유 2번"
    assert sc.number_lines(text) == (text, [1, 2])


def test_number_lines_placeholder_has_no_lines():
    # 사진·글자층 없는 PDF 의 안내문 한 줄은 자료 글이 아니다
    assert sc.number_lines("(첨부한 이미지를 보고 판단할 것)") == ("(첨부한 이미지를 보고 판단할 것)", [])


# ── 끊김 판정 ─────────────────────────────────────────────────────────

def test_all_lines_reported_is_complete():
    r = _result([("f1", "우유", "200ml", 2)], [(1, (), "제목"), (2, ("f1",), ""), (3, (), "인사")])
    j = sc.judge([1, 2, 3], r)
    assert j.unprocessed == [] and not j.empty


def test_missing_line_numbers_are_unprocessed():
    # 끊긴 호출: 앞 두 줄만 보고하고 멈췄다
    r = _result([("f1", "우유", "200ml", 2)], [(1, (), "제목"), (2, ("f1",), "")])
    assert sc.judge([1, 2, 3, 4], r).unprocessed == [3, 4]


def test_refs_to_missing_facts_are_unprocessed():
    r = _result([("f1", "우유", "200ml", 1)], [(1, ("f1",), ""), (2, ("f9",), "")])
    assert sc.judge([1, 2], r).unprocessed == [2]


def test_line_with_neither_refs_nor_reason_is_unprocessed():
    r = _result([("f1", "우유", "200ml", 1)], [(1, ("f1",), ""), (2, (), "")])
    assert sc.judge([1, 2], r).unprocessed == [2]


def test_media_only_empty_result_is_empty_unless_none():
    assert sc.judge([], _result()).empty
    assert not sc.judge([], _result(ranking=(("NONE", 0.9),))).empty
    assert not sc.judge([], _result([("f1", "우유", "200ml", 0)])).empty


def test_to_ranges_compresses():
    assert sc.to_ranges([3, 4, 5, 9, 11, 12]) == [(3, 5), (9, 9), (11, 12)]
    assert sc.to_ranges([]) == []


# ── 이어서 뽑기 입력 ──────────────────────────────────────────────────

def test_continuation_keeps_unprocessed_with_overlap_and_pages():
    numbered = "[1쪽]\n[#1] 가\n[#2] 나\n[#3] 다\n[#4] 라\n[2쪽]\n[#5] 마"
    out = sc.continuation_text(numbered, [4, 5], overlap=2)
    assert out == "[1쪽]\n[겹침] [#2] 나\n[겹침] [#3] 다\n[#4] 라\n[2쪽]\n[#5] 마"


# ── 합치기 ────────────────────────────────────────────────────────────

def test_merge_renames_refs_and_skips_duplicates():
    base = _result([("f1", "우유", "200ml", 1)], [(1, ("f1",), "")])
    more = _result([("f1", "우유", "200ml", 1), ("f2", "얼음", "가득", 2)], [(2, ("f2",), "")],
                   ranking=(("POLICY", 0.8),))
    merged = sc.merge(base, more, attempt=2)
    assert [(a.local_ref, a.subject) for a in merged.assertions] == [("f1", "우유"), ("a2f2", "얼음")]
    assert {c.line: c.refs for c in merged.coverage} == {1: ["f1"], 2: ["a2f2"]}
    # 자료 판정은 첫 성공 시도의 것을 유지한다
    assert merged.intake_ranking[0].logic == "RECIPE"
    assert sc.judge([1, 2], merged).unprocessed == []
