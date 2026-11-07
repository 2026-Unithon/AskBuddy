"""한 번 호출 추출의 시도 반복 — 끊김→이어서 뽑기, 3번 실패 뒤 처리 안 된 범위, 빈 결과 (설계 §4-4, S7·S9)."""
import asyncio
from types import SimpleNamespace as NS
from unittest.mock import patch

import pytest

from app.ingest import raw_responses
from app.ingest.extract import single_call as sc
from app.ingest.providers import budget
from app.ingest.schemas import SingleCallExtractionResult

TEXT = "우유 200ml\n얼음 가득\n시럽 2펌프\n컵 뚜껑 닫기"


def _res(facts, coverage, ranking=(("RECIPE", 0.9),)):
    return SingleCallExtractionResult.model_validate({
        "assertions": [{"local_ref": r, "original_assertion": f"원문 {r}", "subject": s, "attribute": "양",
                        "value": v, "confidence": 0.9, "evidence": {"line": ln}} for r, s, v, ln in facts],
        "coverage": [{"line": n, "refs": list(refs), "no_content": nc} for n, refs, nc in coverage],
        "intake_ranking": [{"logic": lg, "score": x} for lg, x in ranking]})


def _run(replies, *, text=TEXT, media=(), only_lines=None):
    """`replies` 는 시도마다 돌려줄 결과 또는 던질 예외. 보낸 지시문을 함께 돌려준다."""
    prompts = []

    async def fake_once(prompt, media_, ctx, **_):
        prompts.append(prompt)
        r = replies[len(prompts) - 1]
        if isinstance(r, Exception):
            raise r
        return r

    settings = NS(extract_max_attempts=3, ingest_mode="real")
    with patch.object(sc, "_call_once", fake_once), patch.object(sc, "get_settings", return_value=settings):
        out = asyncio.run(sc.extract_single(
            source_id=1, source_type="SCAN", text=text, media=list(media), glossary=[], hints=(),
            usage_sink=None, usage_context=None, raw_sink=None, only_lines=only_lines))
    return out, prompts


def test_complete_first_attempt():
    full = _res([("f1", "우유", "200ml", 1)], [(1, ("f1",), ""), (2, (), "얼음 문장"), (3, (), "x"), (4, (), "y")])
    out, prompts = _run([full])
    assert out.attempts == 1 and out.unprocessed == []
    assert "[#1] 우유 200ml" in prompts[0] and "coverage" in prompts[0]


def test_truncated_then_continuation_fills_rest():
    first = _res([("f1", "우유", "200ml", 1)], [(1, ("f1",), ""), (2, (), "내용 없음")])
    rest = _res([("f1", "시럽", "2펌프", 3), ("f2", "뚜껑", "닫기", 4)], [(3, ("f1",), ""), (4, ("f2",), "")])
    out, prompts = _run([first, rest])
    assert out.attempts == 2 and out.unprocessed == []
    assert [a.subject for a in out.result.assertions] == ["우유", "시럽", "뚜껑"]
    # 두 번째 시도는 처리 안 된 줄(3·4)만, 앞 두 줄은 겹침 문맥으로
    assert "[#3] 시럽 2펌프" in prompts[1] and "[겹침] [#2] 얼음 가득" in prompts[1]
    assert "[#1] 우유 200ml" in prompts[1]  # 겹침 2줄 = 1·2
    assert "이어서 뽑기" in prompts[1]


def test_three_failures_keep_facts_and_report_remaining_range():
    first = _res([("f1", "우유", "200ml", 1)], [(1, ("f1",), "")])
    out, prompts = _run([first, raw_responses.TruncatedOutputError("잘림"), RuntimeError("503")])
    assert out.attempts == 3 and len(prompts) == 3
    assert [a.subject for a in out.result.assertions] == ["우유"]
    assert out.unprocessed == [{"from_line": 2, "to_line": 4, "reason": sc.CALL_FAILED,
                                "first_line": "얼음 가득", "attempts": 3}]


def test_all_attempts_fail_returns_no_result_and_whole_range():
    out, _ = _run([RuntimeError("a"), RuntimeError("b"), raw_responses.TruncatedOutputError("c")])
    assert out.result is None
    assert out.unprocessed == [{"from_line": 1, "to_line": 4, "reason": sc.TRUNCATED,
                                "first_line": "우유 200ml", "attempts": 3}]


def test_media_only_empty_is_retried_then_reported(tmp_path):
    img = tmp_path / "a.jpg"
    img.write_bytes(b"x")
    empty = _res([], [])
    out, prompts = _run([empty, empty, empty], text="(첨부한 이미지를 보고 판단할 것)", media=[img])
    assert len(prompts) == 3 and out.result is not None and out.result.assertions == []
    assert out.unprocessed == [{"from_line": 0, "to_line": 0, "reason": sc.EMPTY,
                                "first_line": "", "attempts": 3}]


def test_owner_retry_starts_from_given_lines():
    rest = _res([("f1", "뚜껑", "닫기", 4)], [(4, ("f1",), "")])
    out, prompts = _run([rest], only_lines=[4])
    assert out.unprocessed == [] and "[#4] 컵 뚜껑 닫기" in prompts[0] and "이어서 뽑기" in prompts[0]
    assert "[#1] 우유" not in prompts[0]


def test_budget_exceeded_is_not_retried():
    with pytest.raises(budget.BudgetExceeded):
        _run([budget.BudgetExceeded("상한")])
