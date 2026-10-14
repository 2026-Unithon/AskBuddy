"""Phase B — 판정 기록·첨부 함수(대역 연결)와 사실 ext 전달."""
import asyncio
import json

from app.ingest.intake import records
from app.ingest.intake.decide import Ranked, SectionDecision
from app.ingest.intake.ir import Candidate, Locator, ProbeResult
from app.ingest.repository import insert_source_facts
from app.ingest.schemas import ExtractedAssertion

D = SectionDecision("c1", "RECIPE", ("RECIPE",), False, False, False, None,
                    (Ranked("RECIPE", 0.9),), (Ranked("RECIPE", 0.9),))
SRC = SectionDecision("source", "RECIPE", ("RECIPE",), False, False, False, None,
                      (Ranked("RECIPE", 0.9),), (Ranked("RECIPE", 0.9),))
PROBE = ProbeResult("DOC_TEXT", (Candidate("c1", Locator("PAGE", "1", "1"), "원문표본글"),))


class Conn:
    def __init__(self, row=None):
        self.calls, self.row = [], row

    async def fetchval(self, sql, *args):
        self.calls.append((sql, args)); return 7

    async def fetchrow(self, sql, *args):
        self.calls.append((sql, args)); return self.row

    async def fetch(self, sql, *args):
        self.calls.append((sql, args)); return [{"source_id": 3}, {"source_id": 5}]


def test_save_decision_store_first_and_no_raw_text():
    conn = Conn()
    from types import SimpleNamespace as NS
    outcome = NS(model_sections={"c1": [Ranked("RECIPE", 0.9)]}, raw={"sections": []},
                 model="gemini-3.6-flash", prompt_digest="abcd")
    got = asyncio.run(records.save_decision(
        conn, 11, source_id=3, entry="UPLOAD", owner_answer_id=None, probe=PROBE,
        owner_hints=("RECIPE",), outcome=outcome, decisions=[D], source=SRC,
        logical_call_id="job1:src3:classify"))
    sql, args = conn.calls[0]
    assert got == 7 and args[0] == 11 and args[1] == 3 and "intake_route_decisions" in sql
    # 표본 원문은 저장하지 않는다(B-D6) — 요약·hash 만
    assert "원문표본글" not in json.dumps(args, default=str, ensure_ascii=False)


def test_latest_decision_scoped_and_parsed():
    row = {"decision_id": 7, "normalizer": "DOC_TEXT", "decisions": json.dumps([D.as_dict()]),
           "source_decision": json.dumps(SRC.as_dict())}
    conn = Conn(row)
    got = asyncio.run(records.latest_decision(conn, 11, 3))
    sql, args = conn.calls[0]
    assert "store_id = $1" in sql and args == (11, 3)
    assert got.decisions == [D] and got.source == SRC


def test_attachments_scoped():
    conn = Conn()
    assert asyncio.run(records.attachments_for_question(conn, 11, 42)) == [3, 5]
    assert "store_id = $1" in conn.calls[0][0] and conn.calls[0][1] == (11, 42)


def test_assertion_ext_round_trip_not_in_schema():
    a = ExtractedAssertion(local_ref="f1", original_assertion="x", subject="s", attribute="a",
                           value="v", confidence=0.9)
    assert a.ext is None
    a.set_ext({"timing": "OPEN"})
    assert a.ext == {"timing": "OPEN"}
    assert "ext" not in ExtractedAssertion.model_json_schema()["properties"]  # 요청 스키마 불변(D16)


class _FactConn:
    def __init__(self):
        self.args = []

    async def fetchval(self, sql, *args):
        if "insert into source_facts" in sql:
            self.args.append(args)
            return 1
        raise AssertionError(sql[:40])


def test_insert_source_facts_passes_ext_last():
    conn = _FactConn()
    base = dict(subject="음료Z", attribute="얼음", value="3")
    asyncio.run(insert_source_facts(
        conn, 1, 7, [dict(base, ext={"timing": "OPEN"}), dict(base, value="4")],
        locator_type="WHOLE_SOURCE", locator={}))
    assert conn.args[0][-1] == json.dumps({"timing": "OPEN"}, ensure_ascii=False)
    assert conn.args[1][-1] is None
