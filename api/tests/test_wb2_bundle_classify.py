"""Phase B 추가 S1 — 묶음 분류 공용 함수. 칩은 자기 자료에만 가산(Review Focus 5)."""
import asyncio
from unittest.mock import AsyncMock, patch

from app.config import Settings
from app.ingest.intake import classify, route
from app.ingest.intake.classify import ClassifyOutcome
from app.ingest.intake.decide import Ranked
from app.ingest.intake.ir import Candidate, Locator, ProbeResult


def _probe(text):
    return ProbeResult("DOC_TEXT", (Candidate("c1", Locator("PAGE", "1", "1"), text),),
                       complete=True)


def test_prompt_marks_candidate_hints():
    prompt, _ = classify.render_prompt(
        [route._prefixed(5, _probe("음료Z 샷 2")), route._prefixed(6, _probe("마감"))],
        hints=(), context=None, candidate_hints={"s5:c1": ("RECIPE", "NOTICE")})
    assert "### s5:c1 (DOC_TEXT PAGE 1~1) [점주 선택: RECIPE, NOTICE]" in prompt
    assert "### s6:c1 (DOC_TEXT PAGE 1~1)\n" in prompt


class _Lease:
    async def __aenter__(self):
        conn = AsyncMock()
        conn.transaction = lambda: _Tx()
        return conn

    async def __aexit__(self, *exc):
        return False


class _Tx:
    async def __aenter__(self):
        return None

    async def __aexit__(self, *exc):
        return False


class _Pool:
    def acquire(self):
        return _Lease()


def test_bundle_one_call_hints_only_boost_own_source():
    # 두 자료 모두 모델은 RECIPE .45 / PROCEDURE .40 — 5번 자료만 PROCEDURE 칩
    outcome = ClassifyOutcome(
        {"s5:c1": [Ranked("RECIPE", 0.45), Ranked("PROCEDURE", 0.40)],
         "s6:c1": [Ranked("RECIPE", 0.45), Ranked("PROCEDURE", 0.40)]},
        {"sections": []}, "gemini-3.6-flash", "abcd")
    saves = []

    async def save(conn, store_id, **kw):
        saves.append(kw)
        return 100 + len(saves)

    cls = AsyncMock(return_value=outcome)
    with patch.object(route.classify, "classify", cls), \
         patch.object(route.records, "save_decision", side_effect=save), \
         patch.object(route, "get_settings", return_value=Settings(_env_file=None)):
        routes = asyncio.run(route._classify_bundle(
            _Pool(), 7, [(5, _probe("가"), ("PROCEDURE",)), (6, _probe("나"), ())],
            context=None, global_hints=(), usage_sink=None, ctx=None, entry="UPLOAD",
            owner_answer_id=None))
    cls.assert_awaited_once()
    assert cls.await_args.kwargs["candidate_hints"] == {"s5:c1": ("PROCEDURE",)}
    assert routes[5].source.logic == "PROCEDURE" and routes[6].source.logic == "RECIPE"
    assert [s["entry"] for s in saves] == ["UPLOAD", "UPLOAD"]
    assert routes[5].decisions[0].candidate_id == "c1"  # 저장 판정은 접두어 없음
