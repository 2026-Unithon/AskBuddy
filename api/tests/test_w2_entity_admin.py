"""W2-4 ③ 대상 병합·분리·재연결 — 인자 검증과 SQL 순서·인자.

DB 는 부르지 않는다. FakeConn 이 SQL 을 기록하고 조회에는 미리 정한 값을 돌려준다.
실제 DB 동작(판 불변·충돌 재계산·별칭 이동·공개본 보존)은 scripts/verify_w_entity_revision.py 의 S1~S5 가 본다.
"""
import inspect
import json
import re
from contextlib import asynccontextmanager
from decimal import Decimal

import pytest

from app.ingest import entity_admin as ea
from app.ingest import fact_ledger
from app.ingest.entities import AliasTaken
from app.ingest.fact_keys import FactShape, identity_key, slot_key
from app.ingest.fact_revisions import StaleFactRevision

STORE, FACT, HEAD, NEW_REV, FROM, TO, ACTOR = 3, 70, 700, 701, 9, 12, 11
NEW_ENTITY = 40


def _head(**over):
    row = dict(fact_revision_id=HEAD, fact_id=FACT, entity_id=FROM,
               original_assertion="우유 스팀 온도 65도", assertion="우유 스팀 온도는 65도",
               subject="우유", predicate="스팀 온도", variant_temperature=None, variant_size=None,
               quantity_value=Decimal("65"), quantity_unit="°c", value_text=None,
               polarity="AFFIRM", step_order=None,
               conditions=json.dumps(["바쁠 때"]), exceptions=json.dumps([]))
    row.update(over)
    return row


class FakeConn:
    """SQL 을 기록한다. 응답은 SQL 조각 → 값 또는 args 를 받는 함수(먼저 맞는 조각)."""

    def __init__(self, responses=None):
        self.calls: list[tuple[str, str, tuple]] = []
        self.responses = {
            "from knowledge_facts where store_id = $1 and fact_id = $2 for update":
                lambda args: dict(fact_id=args[1], entity_id=FROM, head_revision_id=HEAD),
            "select status from knowledge_entities": "ACTIVE",
            "from fact_revisions where store_id = $1 and fact_revision_id = $2": _head(),
            "select variant_other from fact_revision_meta": None,
            "insert into fact_revisions": NEW_REV,
            "update knowledge_facts": "UPDATE 1",
            "insert into knowledge_entities": NEW_ENTITY,
            "insert into knowledge_entity_aliases": 500,
        }
        self.responses.update(responses or {})

    def _answer(self, sql, args):
        for key, value in self.responses.items():
            if key in sql:
                return value(args) if callable(value) else value
        return None

    async def execute(self, sql, *args):
        self.calls.append(("execute", sql, args))
        answer = self._answer(sql, args)
        return answer if isinstance(answer, str) else "INSERT 0 1"

    async def fetchval(self, sql, *args):
        self.calls.append(("fetchval", sql, args))
        return self._answer(sql, args)

    async def fetchrow(self, sql, *args):
        self.calls.append(("fetchrow", sql, args))
        return self._answer(sql, args)

    async def fetch(self, sql, *args):
        self.calls.append(("fetch", sql, args))
        answer = self._answer(sql, args)
        return answer if isinstance(answer, list) else []

    @asynccontextmanager
    async def transaction(self):
        yield

    def sql(self, fragment):
        return [c for c in self.calls if fragment in c[1]]

    def writes(self):
        return [c for c in self.calls
                if c[1].lstrip().lower().startswith(("insert", "update", "delete"))]


def order_of(conn, fragment):
    return next(i for i, c in enumerate(conn.calls) if fragment in c[1])


def _events(conn):
    return [c[2] for c in conn.sql("insert into knowledge_entity_events")]


async def _relink(conn, **kw):
    kw.setdefault("fact_id", FACT)
    kw.setdefault("expected_head_revision_id", HEAD)
    kw.setdefault("to_entity_id", TO)
    kw.setdefault("reason", "잘못 합친 사실")
    return await ea.relink_fact(conn, STORE, actor_id=ACTOR, **kw)


# ── 인자 검증 — DB 호출 없음 ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_relink_blank_reason_is_rejected_before_db():
    conn = FakeConn()
    with pytest.raises(ValueError):
        await _relink(conn, reason="  ")
    assert conn.calls == []


@pytest.mark.asyncio
async def test_split_without_facts_is_rejected_before_db():
    conn = FakeConn()
    with pytest.raises(ValueError):
        await ea.split_entity(conn, STORE, entity_id=FROM, fact_ids=[],
                              new_canonical_name="우유 거품", move_alias_norms=[], actor_id=ACTOR)
    assert conn.calls == []


@pytest.mark.parametrize("name", ["", "   ", "!!!"])
@pytest.mark.asyncio
async def test_split_unresolvable_name_is_rejected_before_db(name):
    conn = FakeConn()
    with pytest.raises(ValueError):
        await ea.split_entity(conn, STORE, entity_id=FROM, fact_ids=[FACT],
                              new_canonical_name=name, move_alias_norms=[], actor_id=ACTOR)
    assert conn.calls == []


@pytest.mark.asyncio
async def test_split_blank_alias_norm_is_rejected_before_db():
    conn = FakeConn()
    with pytest.raises(ValueError):
        await ea.split_entity(conn, STORE, entity_id=FROM, fact_ids=[FACT],
                              new_canonical_name="우유 거품", move_alias_norms=[" "],
                              actor_id=ACTOR)
    assert conn.calls == []


@pytest.mark.asyncio
async def test_self_merge_is_rejected_before_db():
    conn = FakeConn()
    with pytest.raises(ValueError):
        await ea.merge_entities(conn, STORE, keep_entity_id=FROM, merged_entity_id=FROM,
                                actor_id=ACTOR, candidate_id=None)
    assert conn.calls == []


@pytest.mark.parametrize("decision", ["CONFIRMED_SAME", "PENDING", "YES"])
@pytest.mark.asyncio
async def test_decide_candidate_rejects_other_decisions_before_db(decision):
    conn = FakeConn()
    with pytest.raises(ValueError):
        await ea.decide_candidate(conn, STORE, 5, decision=decision, actor_id=ACTOR)
    assert conn.calls == []


# ── relink_fact ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_relink_to_same_entity_is_rejected_without_writes():
    conn = FakeConn()
    with pytest.raises(ValueError):
        await _relink(conn, to_entity_id=FROM)
    assert conn.writes() == []


@pytest.mark.asyncio
async def test_relink_to_merged_entity_is_rejected_without_writes():
    conn = FakeConn({"select status from knowledge_entities": "MERGED"})
    with pytest.raises(ValueError):
        await _relink(conn)
    assert conn.writes() == []


@pytest.mark.asyncio
async def test_relink_to_unknown_or_other_store_entity_is_lookup_error():
    conn = FakeConn({"select status from knowledge_entities": None})
    with pytest.raises(LookupError):
        await _relink(conn)
    assert conn.writes() == []
    status_query = conn.sql("select status from knowledge_entities")[0]
    assert "store_id = $1" in status_query[1] and status_query[2][:2] == (STORE, TO)


@pytest.mark.asyncio
async def test_relink_stale_head_writes_nothing():
    conn = FakeConn({"from knowledge_facts where store_id = $1 and fact_id = $2 for update":
                     lambda args: dict(fact_id=FACT, entity_id=FROM, head_revision_id=HEAD + 5)})
    with pytest.raises(StaleFactRevision):
        await _relink(conn)
    assert conn.writes() == []


@pytest.mark.asyncio
async def test_relink_appends_relink_revision_with_same_values():
    conn = FakeConn()
    assert await _relink(conn) == NEW_REV
    assert order_of(conn, "pg_advisory_xact_lock") < order_of(conn, "for update") \
        < order_of(conn, "insert into fact_revisions")
    args = conn.sql("insert into fact_revisions")[0][2]
    head = _head()
    # store, fact, entity=TO, 원문·문장·주어·속성·규격·값 모두 head 그대로, supersedes=HEAD
    assert args[:3] == (STORE, FACT, TO)
    assert args[3:15] == (head["original_assertion"], head["assertion"], head["subject"],
                          head["predicate"], None, None, Decimal("65"), "°c", None,
                          "AFFIRM", None, json.dumps(["바쁠 때"], ensure_ascii=False))
    assert args[16:] == (HEAD, ACTOR)
    shape = FactShape(subject="우유", predicate="스팀 온도", variant_temperature=None,
                      variant_size=None, variant_other=None, quantity_value=Decimal("65"),
                      quantity_unit="°c", value_text=None, polarity="AFFIRM", step_order=None,
                      conditions=("바쁠 때",), exceptions=(),
                      original_assertion=head["original_assertion"], assertion=head["assertion"])
    meta = conn.sql("insert into fact_revision_meta")[0][2]
    assert meta[3] == "RELINK" and meta[8] == "잘못 합친 사실"
    assert meta[4:6] == (identity_key(TO, shape), slot_key(TO, shape))
    cas = conn.sql("update knowledge_facts")[0][2]
    assert cas[:5] == (STORE, FACT, HEAD, NEW_REV, TO)
    events = _events(conn)
    assert len(events) == 1
    store, action, entity, other, fact, revision, actor, payload = events[0]
    assert (store, action, entity, other, fact, revision, actor) == \
        (STORE, "RELINK_FACT", FROM, TO, FACT, NEW_REV, ACTOR)
    assert json.loads(payload) == {"reason": "잘못 합친 사실", "from_revision_id": HEAD}


# ── split_entity ────────────────────────────────────────────────────────────

def _split_conn(*, entity_facts=(FACT,), aliases=(), alias_owner=None, **extra):
    responses = {
        "and fact_id = any($3::bigint[])": [dict(fact_id=f) for f in entity_facts],
        "and alias_norm = any($3::text[])": [
            dict(alias_id=100 + i, alias_norm=a, alias_raw=a.upper())
            for i, a in enumerate(aliases)],
        "select entity_id from knowledge_entity_aliases": alias_owner,
    }
    responses.update(extra)
    return FakeConn(responses)


async def _split(conn, **kw):
    kw.setdefault("fact_ids", [FACT])
    kw.setdefault("new_canonical_name", "우유 거품")
    kw.setdefault("move_alias_norms", [])
    return await ea.split_entity(conn, STORE, entity_id=FROM, actor_id=ACTOR, **kw)


@pytest.mark.asyncio
async def test_split_rejects_fact_of_other_entity_without_writes():
    conn = _split_conn(entity_facts=())
    with pytest.raises(ValueError):
        await _split(conn)
    assert conn.writes() == []


@pytest.mark.asyncio
async def test_split_rejects_merged_entity_without_writes():
    conn = _split_conn(**{"select status from knowledge_entities": "MERGED"})
    with pytest.raises(ValueError):
        await _split(conn)
    assert conn.writes() == []


@pytest.mark.asyncio
async def test_split_rejects_alias_not_owned_by_entity_without_writes():
    conn = _split_conn(aliases=())
    with pytest.raises(ValueError):
        await _split(conn, move_alias_norms=["스팀우유"])
    assert conn.writes() == []


@pytest.mark.asyncio
async def test_split_name_taken_by_other_entity_is_alias_taken_without_writes():
    conn = _split_conn(alias_owner=77)
    with pytest.raises(AliasTaken):
        await _split(conn)
    assert conn.writes() == []


@pytest.mark.asyncio
async def test_split_creates_entity_moves_aliases_relinks_and_records_history():
    conn = _split_conn(aliases=("스팀우유",))
    assert await _split(conn, move_alias_norms=["스팀우유"]) == NEW_ENTITY
    entity = conn.sql("insert into knowledge_entities")[0][2]
    assert entity == (STORE, "우유 거품", "우유거품", ACTOR)
    # 옮길 별칭은 원 대상에서 retire 한 뒤 새 대상 OWNER 로 다시 만든다
    retire = conn.sql("update knowledge_entity_aliases set retired_at")
    assert [c[2] for c in retire] == [(STORE, 100, FROM)]
    alias_inserts = [c[2] for c in conn.sql("insert into knowledge_entity_aliases")]
    assert (STORE, NEW_ENTITY, "스팀우유", "스팀우유".upper(), "OWNER", ACTOR) in alias_inserts
    assert (STORE, NEW_ENTITY, "우유거품", "우유 거품", "SYSTEM", ACTOR) in alias_inserts
    owner_insert = next(i for i, c in enumerate(conn.calls)
                        if "insert into knowledge_entity_aliases" in c[1] and "OWNER" in c[2])
    assert order_of(conn, "update knowledge_entity_aliases set retired_at") < owner_insert
    # 사실은 새 대상으로 재연결(새 판)
    assert conn.sql("insert into fact_revisions")[0][2][2] == NEW_ENTITY
    candidate = conn.sql("insert into knowledge_entity_candidates")[0]
    assert "'SPLIT'" in candidate[1] and "'CONFIRMED_DIFFERENT'" in candidate[1]
    assert "on conflict (store_id, entity_id_low, entity_id_high) do update" in candidate[1]
    assert candidate[2][:3] == (STORE, FROM, NEW_ENTITY)
    actions = [e[1] for e in _events(conn)]
    assert actions == ["CREATE", "ALIAS_RETIRE", "ALIAS_ADD", "RELINK_FACT", "SPLIT"]
    split = _events(conn)[-1]
    assert split[2:4] == (FROM, NEW_ENTITY)
    payload = json.loads(split[-1])
    assert payload["fact_ids"] == [FACT] and payload["moved_aliases"] == ["스팀우유"]


@pytest.mark.asyncio
async def test_split_name_equal_to_moved_alias_is_allowed_and_not_duplicated():
    # 새 이름의 정규화가 원 대상의 옮길 별칭이면 AliasTaken 이 아니다. SYSTEM 별칭은 따로 만들지 않는다
    conn = _split_conn(aliases=("우유거품",), alias_owner=FROM)
    assert await _split(conn, move_alias_norms=["우유거품"]) == NEW_ENTITY
    alias_inserts = [c[2] for c in conn.sql("insert into knowledge_entity_aliases")]
    assert alias_inserts == [(STORE, NEW_ENTITY, "우유거품", "우유거품".upper(), "OWNER", ACTOR)]


# ── merge_entities ──────────────────────────────────────────────────────────

KEEP, GONE = 12, 9


def _merge_conn(*, statuses=(("ACTIVE", KEEP), ("ACTIVE", GONE)), facts=(70, 71),
                aliases=("카페라테",), candidate=None, **extra):
    responses = {
        "from knowledge_entities where store_id = $1 and entity_id = any($2::bigint[])":
            [dict(entity_id=e, status=s) for s, e in statuses],
        "from knowledge_entity_candidates where store_id = $1 and candidate_id = $2":
            candidate,
        "select fact_id from knowledge_facts where store_id = $1 and entity_id = $2":
            [dict(fact_id=f) for f in facts],
        "and retired_at is null order by alias_id": [
            dict(alias_id=200 + i, alias_norm=a, alias_raw=a) for i, a in enumerate(aliases)],
        "from knowledge_facts where store_id = $1 and fact_id = $2 for update":
            lambda args: dict(fact_id=args[1], entity_id=GONE, head_revision_id=HEAD),
    }
    responses.update(extra)
    return FakeConn(responses)


async def _merge(conn, candidate_id=None):
    return await ea.merge_entities(conn, STORE, keep_entity_id=KEEP, merged_entity_id=GONE,
                                   actor_id=ACTOR, candidate_id=candidate_id)


@pytest.mark.asyncio
async def test_merge_requires_both_entities_active():
    conn = _merge_conn(statuses=(("ACTIVE", KEEP), ("MERGED", GONE)))
    with pytest.raises(ValueError):
        await _merge(conn)
    assert conn.writes() == []


@pytest.mark.asyncio
async def test_merge_with_missing_entity_is_lookup_error():
    conn = _merge_conn(statuses=(("ACTIVE", KEEP),))
    with pytest.raises(LookupError):
        await _merge(conn)
    assert conn.writes() == []


@pytest.mark.parametrize("candidate", [
    dict(entity_id_low=5, entity_id_high=KEEP, status="PENDING"),     # 다른 쌍
    dict(entity_id_low=GONE, entity_id_high=KEEP, status="DISMISSED"),  # 이미 결정
])
@pytest.mark.asyncio
async def test_merge_rejects_unrelated_or_decided_candidate(candidate):
    conn = _merge_conn(candidate=candidate)
    with pytest.raises(ValueError):
        await _merge(conn, candidate_id=8)
    assert conn.writes() == []


@pytest.mark.asyncio
async def test_merge_relinks_moves_aliases_marks_merged_and_confirms_candidate():
    conn = _merge_conn(candidate=dict(entity_id_low=GONE, entity_id_high=KEEP, status="PENDING"))
    assert await _merge(conn, candidate_id=8) == 2
    revisions = conn.sql("insert into fact_revisions")
    assert [c[2][1:3] for c in revisions] == [(70, KEEP), (71, KEEP)]
    assert [c[2] for c in conn.sql("update knowledge_entity_aliases set retired_at")] == \
        [(STORE, 200, GONE)]
    assert (STORE, KEEP, "카페라테", "카페라테", "OWNER", ACTOR) in \
        [c[2] for c in conn.sql("insert into knowledge_entity_aliases")]
    merged = conn.sql("set status = 'MERGED'")
    assert len(merged) == 1 and merged[0][2] == (STORE, GONE, KEEP)
    confirm = conn.sql("update knowledge_entity_candidates")
    assert len(confirm) == 1 and "'CONFIRMED_SAME'" in confirm[0][1]
    assert confirm[0][2] == (STORE, GONE, KEEP, ACTOR)
    # 사실을 모두 옮긴 뒤에 MERGED 로 바꾼다
    last_relink = max(i for i, c in enumerate(conn.calls) if "insert into fact_revisions" in c[1])
    assert last_relink < order_of(conn, "set status = 'MERGED'")
    actions = [e[1] for e in _events(conn)]
    assert actions == ["RELINK_FACT", "RELINK_FACT", "ALIAS_RETIRE", "ALIAS_ADD", "MERGE"]
    merge = _events(conn)[-1]
    assert merge[2:4] == (KEEP, GONE)
    assert json.loads(merge[-1]) == {"fact_ids": [70, 71], "moved_aliases": ["카페라테"],
                                     "candidate_id": 8}


# ── decide_candidate ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_decide_candidate_records_event():
    conn = FakeConn({"update knowledge_entity_candidates":
                     lambda args: dict(entity_id_low=4, entity_id_high=6)})
    await ea.decide_candidate(conn, STORE, 5, decision="CONFIRMED_DIFFERENT", actor_id=ACTOR)
    update = conn.sql("update knowledge_entity_candidates")[0]
    assert "status = 'PENDING'" in update[1] and update[2] == (STORE, 5, "CONFIRMED_DIFFERENT",
                                                               ACTOR)
    events = _events(conn)
    assert len(events) == 1 and events[0][1:4] == ("CANDIDATE_DECIDED", 4, 6)
    assert json.loads(events[0][-1]) == {"candidate_id": 5, "decision": "CONFIRMED_DIFFERENT"}


@pytest.mark.parametrize("existing, error", [(None, LookupError), ("DISMISSED", ValueError)])
@pytest.mark.asyncio
async def test_decide_candidate_only_pending(existing, error):
    conn = FakeConn({"select status from knowledge_entity_candidates": existing})
    with pytest.raises(error):
        await ea.decide_candidate(conn, STORE, 5, decision="DISMISSED", actor_id=ACTOR)
    assert _events(conn) == []


# ── 공개본·카드·제안 불변 (결정 G) ───────────────────────────────────────────

def test_entity_admin_never_writes_cards_snapshots_or_proposals():
    source = inspect.getsource(ea).lower()
    for table in ("knowledge_cards", "card_versions", "knowledge_snapshots",
                  "knowledge_publications", "upload_change_proposals", "card_facts"):
        assert not re.search(rf"(insert into|update|delete from)\s+{table}\b", source), table


# ── 연결 당시 대상이 아니라 지금 대상 (병합·재연결 뒤) ─────────────────────────

@pytest.mark.asyncio
async def test_card_entity_for_uses_current_fact_entity():
    conn = FakeConn({"from source_fact_revision_links": [dict(entity_id=TO)]})
    assert await fact_ledger.card_entity_for(conn, STORE, [5, 6]) == TO
    query = conn.sql("from source_fact_revision_links")[0][1]
    assert "join knowledge_facts k" in query and "k.entity_id" in query
