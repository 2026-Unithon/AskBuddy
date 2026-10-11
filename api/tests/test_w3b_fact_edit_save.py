"""W3b-5 사실 편집 저장 — 순서·멱등·head 판정·중복·처분 SQL 범위 (DB 없음, 합성 이름만).

실제 DB 동작(판·카드 판·근거·처분·재승인)은 scripts/verify_w3b_card_fact_edit.py 의 S1~S12, A1~A3 이 본다.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from app.cards import fact_edit as fe
from app.cards.fact_edit_plan import CardFactState, EditError, PinnedFact
from app.cards.fact_edit_repo import HeadInfo
from app.cards.fact_edit_schemas import FactEditRequest
from app.ingest.card_plan import PlanFact
from app.ingest.fact_cards import Origin
from app.ingest.fact_keys import FactShape, identity_key, parse_value
from app.ingest.fact_revisions import StaleFactRevision

pytestmark = pytest.mark.asyncio

STORE, CARD, ACTOR, ENTITY, DRAFT = 7, 40, 3, 9, 500
NOW = datetime(2026, 10, 9, tzinfo=timezone.utc)


def _fact(rid, fid, **over) -> PlanFact:
    base = dict(
        fact_revision_id=rid, fact_id=fid, entity_id=ENTITY, subject="음료Z", predicate="물",
        variant_temperature="ICE", variant_size=None, quantity_value=Decimal("225"),
        quantity_unit="ml", value_text=None, polarity="AFFIRM", step_order=None,
        conditions=(), exceptions=(), original_assertion="ICE 물 225ml",
        assertion="ICE 물 225ml", requires_fact_ids=())
    base.update(over)
    return PlanFact(**base)


WATER = _fact(101, 201)
SYRUP = _fact(102, 202, predicate="시럽", variant_temperature=None, quantity_value=None,
              quantity_unit=None, value_text="넣지 않는다", polarity="NEGATE",
              original_assertion="시럽은 넣지 않는다", assertion="시럽은 넣지 않는다")


def _state(**over) -> CardFactState:
    base = dict(
        store_id=STORE, card_id=CARD, version_id=DRAFT, title="음료Z", review_status="PENDING",
        published_version_id=None, entity_id=ENTITY, entity_name="음료Z",
        alias_norms=frozenset({"음료z"}), entity_problem=None,
        blocks=(("b1", "QUANTITIES", 1), ("b2", "NOTES", 2)),
        pinned=(PinnedFact(WATER, "b1", "QUANTITIES", 1), PinnedFact(SYRUP, "b2", "NOTES", 1)))
    base.update(over)
    return CardFactState(**base)


def _req(water_item=None, *, key="key-000001", expected=DRAFT, extra_notes=(), deleted=()):
    water = water_item or {"op": "KEEP", "fact_revision_id": 101}
    blocks = [{"kind": "QUANTITIES", "items": [water]}]
    notes = [] if 102 in deleted else [{"op": "KEEP", "fact_revision_id": 102}]
    notes += list(extra_notes)
    if notes:
        blocks.append({"kind": "NOTES", "items": notes})
    return FactEditRequest.model_validate({
        "expected_version_id": expected, "idempotency_key": key, "blocks": blocks,
        "deleted_fact_revision_ids": list(deleted)})


def _modify(sentence="ICE 물 230ml", value="230", unit="ml"):
    return {"op": "MODIFY", "fact_revision_id": 101,
            "fact": {"sentence": sentence, "value": value, "unit": unit}}


class FakeConn:
    """SQL 을 기록한다. answers = [(SQL 조각, 값 또는 함수)] 앞에서부터 맞춘다."""

    def __init__(self, answers=()):
        self.answers = list(answers)
        self.calls: list[tuple[str, str, tuple]] = []

    def _answer(self, sql, args):
        for fragment, answer in self.answers:
            if fragment in sql:
                return answer(*args) if callable(answer) else answer
        return None

    async def execute(self, sql, *args):
        self.calls.append(("execute", sql, args))
        return "UPDATE 1"

    async def executemany(self, sql, rows):
        self.calls.append(("executemany", sql, tuple(rows)))

    async def fetch(self, sql, *args):
        self.calls.append(("fetch", sql, args))
        got = self._answer(sql, args)
        return got if isinstance(got, list) else []

    async def fetchrow(self, sql, *args):
        self.calls.append(("fetchrow", sql, args))
        return self._answer(sql, args)

    async def fetchval(self, sql, *args):
        self.calls.append(("fetchval", sql, args))
        return self._answer(sql, args)

    def sql(self, fragment):
        return [c for c in self.calls if fragment in c[1]]


def _card_row(status="PENDING", draft=DRAFT):
    return {"card_id": CARD, "review_status": status, "draft_version_id": draft}


def _mutation(*_args):
    return {"card_id": CARD, "review_status": "PENDING", "draft_version_id": 900,
            "published_version_id": None, "updated_at": NOW}


@pytest.fixture
def env(monkeypatch):
    """저장 경로가 부르는 DB 함수 대역. order 에 부른 순서를 남긴다."""
    order: list[str] = []
    ns = type("Env", (), {})()
    ns.order = order

    async def lock(conn, store_id):
        order.append("lock")

    async def card_for_update(conn, store_id, card_id):
        order.append("card")
        return ns.card

    ns.card = _card_row()
    ns.state = _state()
    ns.heads = {201: HeadInfo(201, 101, 101, ENTITY, 101, None)}
    ns.real: dict[int, PlanFact] = {}
    ns.provenance = None
    monkeypatch.setattr(fe, "lock_store_knowledge", lock)
    monkeypatch.setattr(fe.cards_repo, "get_card_for_update", card_for_update)
    monkeypatch.setattr(fe.cards_repo, "mutation_row", AsyncMock(side_effect=_mutation))
    monkeypatch.setattr(fe.cards_repo, "add_event", AsyncMock(return_value=1))

    async def load_state(conn, store_id, card_id, version_id):
        order.append("state")
        return ns.state

    async def heads(conn, store_id, pinned, entity_id):
        order.append("heads")
        return {f: h for f, h in ns.heads.items() if f in pinned}

    async def plan_facts(conn, store_id, ids):
        known = {101: WATER, 102: SYRUP, **ns.real}
        return {i: known[i] for i in ids}

    async def provenance(conn, store_id, ids):
        if ns.provenance is not None:
            return ns.provenance
        return {i: (Origin(occurrence_id=1000 + i, owner_answer_id=None, source_id=60,
                           locator_type="WHOLE_SOURCE", locator={}),) for i in ids}

    monkeypatch.setattr(fe, "load_card_fact_state", load_state)
    monkeypatch.setattr(fe, "classify_head", heads)
    monkeypatch.setattr(fe, "load_plan_facts", plan_facts)
    monkeypatch.setattr(fe, "provenance_for", provenance)
    ns.revise = AsyncMock(return_value=301)
    ns.create = AsyncMock(return_value=(401, 402))
    monkeypatch.setattr(fe, "revise_fact", ns.revise)
    monkeypatch.setattr(fe, "_create_fact", ns.create)
    monkeypatch.setattr(fe, "_record_conflicts", AsyncMock(return_value=0))
    monkeypatch.setattr(fe, "pin_card_version", AsyncMock())
    monkeypatch.setattr(fe, "write_version_evidence", AsyncMock())
    monkeypatch.setattr(fe, "replace_legacy_facts", AsyncMock())
    return ns


def _conn(prior=None, identities=()):
    return FakeConn([
        ("from card_fact_edits", prior),
        ("nextval", 77),
        ("insert into sources", 600),
        ("insert into card_versions", 900),
        ("from fact_revision_meta", [{"fact_revision_id": r, "identity_key": k}
                                     for r, k in identities]),
        ("select source_id, title, source_type from sources",
         [{"source_id": 60, "title": "합성 자료", "source_type": "SCAN"},
          {"source_id": 600, "title": "카드 직접 입력 · 음료Z", "source_type": "OWNER_TEXT"}]),
        ("from fact_conflicts", False),
    ])


async def _save(conn, req):
    return await fe.save_fact_edit(conn, STORE, card_id=CARD, actor_id=ACTOR, req=req)


def _water_30():
    return _fact(301, 201, quantity_value=Decimal("230"), original_assertion="ICE 물 230ml",
                 assertion="ICE 물 230ml")


# ── 순서 ──────────────────────────────────────────────────────────────────

async def test_store_lock_before_card_row_lock(env):
    await _save(_conn(), _req())
    assert env.order[:2] == ["lock", "card"]


async def test_idempotent_replay_comes_before_version_cas(env):
    conn = _conn()
    env.real = {301: _water_30()}
    first = await _save(conn, _req(_modify()))
    [(_, _, args)] = conn.sql("insert into card_fact_edits")
    stored = {"request_hash": args[4], "result": args[10]}
    # 성공 뒤 같은 키 재요청 — 카드 초안은 이미 새 판(900)이라 CAS 면 409 였을 것
    env.card = _card_row(draft=900)
    replay_conn = _conn(prior=stored)
    again = await _save(replay_conn, _req(_modify()))
    assert again == first
    assert again.model_dump(mode="json") == json.loads(args[10])
    assert not replay_conn.sql("insert into") and env.revise.await_count == 1


async def test_same_key_other_body_is_idempotency_conflict(env):
    stored = {"request_hash": "0" * 64, "result": "{}"}
    with pytest.raises(EditError) as e:
        await _save(_conn(prior=stored), _req(_modify()))
    assert (e.value.status, e.value.code) == (409, "IDEMPOTENCY_CONFLICT")


async def test_stale_expected_version_is_conflict_with_current(env):
    with pytest.raises(EditError) as e:
        await _save(_conn(), _req(expected=DRAFT - 1))
    assert (e.value.status, e.value.code, e.value.details) == (
        409, "CARD_VERSION_CONFLICT", {"current_version_id": DRAFT})


async def test_missing_excluded_and_not_fact_card(env):
    env.card = None
    with pytest.raises(EditError) as e:
        await _save(_conn(), _req())
    assert (e.value.status, e.value.code) == (404, "CARD_NOT_FOUND")
    env.card = _card_row(status="EXCLUDED")
    with pytest.raises(EditError) as e:
        await _save(_conn(), _req())
    assert e.value.code == "CARD_EXCLUDED"
    env.card, env.state = _card_row(), None
    with pytest.raises(EditError) as e:
        await _save(_conn(), _req())
    assert (e.value.status, e.value.code) == (409, "NOT_FACT_CARD")


async def test_entity_problem_rejected_before_plan(env, monkeypatch):
    env.state = _state(entity_problem="MIXED_ENTITY", entity_id=None)
    plan = AsyncMock()
    monkeypatch.setattr(fe, "build_plan", plan)
    with pytest.raises(EditError) as e:
        await _save(_conn(), _req())
    assert (e.value.status, e.value.code, e.value.details) == (
        409, "CARD_ENTITY_MOVED", {"entity_problem": "MIXED_ENTITY"})
    plan.assert_not_called()


# ── 바뀐 것 없음 ─────────────────────────────────────────────────────────────

async def test_unchanged_writes_only_edit_record(env):
    conn = _conn()
    result = await _save(conn, _req(_modify(sentence="ICE 물 225ml", value="225")))
    assert result.changed is False and result.revisions == [] and result.edit_id == 77
    env.revise.assert_not_awaited()
    env.create.assert_not_awaited()
    assert not conn.sql("insert into card_versions") and not conn.sql("insert into sources")
    [(_, _, args)] = conn.sql("insert into card_fact_edits")
    # 편집 기록: changed=false, 새 판 없음, 점주 입력 없음
    assert (args[6], args[7], args[8], args[9]) == (None, False, None, None)
    fe.cards_repo.add_event.assert_not_awaited()


# ── MODIFY head 판정 ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("block, code", [("CHANGED_ELSEWHERE", "FACT_CHANGED_ELSEWHERE"),
                                         ("MOVED_ENTITY", "FACT_MOVED_ENTITY")])
async def test_blocked_head_is_409_without_revision(env, block, code):
    env.heads = {201: HeadInfo(201, 101, 150, ENTITY, None, block)}
    conn = _conn()
    with pytest.raises(EditError) as e:
        await _save(conn, _req(_modify()))
    assert (e.value.status, e.value.code) == (409, code)
    assert e.value.details["fact_id"] == 201 and e.value.details["fact_revision_id"] == 101
    env.revise.assert_not_awaited()
    assert not conn.sql("insert into")


async def test_missing_head_row_is_not_editable(env):
    env.heads = {}  # knowledge_facts 행이 없는 고정 사실
    with pytest.raises(EditError) as e:
        await _save(_conn(), _req(_modify()))
    assert (e.value.status, e.value.code) == (409, "FACT_CHANGED_ELSEWHERE")
    assert e.value.details == {"fact_id": 201, "fact_revision_id": 101, "head_revision_id": None}
    env.revise.assert_not_awaited()


async def test_stale_head_during_revise_is_409(env):
    env.revise.side_effect = StaleFactRevision("head 가 바뀌었다")
    with pytest.raises(EditError) as e:
        await _save(_conn(), _req(_modify()))
    assert (e.value.status, e.value.code) == (409, "FACT_CHANGED_ELSEWHERE")


async def test_relink_head_is_used_as_expected(env):
    env.heads = {201: HeadInfo(201, 101, 150, ENTITY, 150, None)}
    env.real = {301: _water_30()}
    await _save(_conn(), _req(_modify()))
    kwargs = env.revise.await_args.kwargs
    assert kwargs["expected_head_revision_id"] == 150 and kwargs["fact_id"] == 201
    assert kwargs["change_kind"] == "OWNER_CORRECTION" and kwargs["reason"] == "카드 사실 편집"
    change = kwargs["change"]
    # 단위 칸을 비워 보내지 않는다 — 옛 단위 상속을 막으려 "" 로 넘긴다
    assert (change.value, change.unit, change.original_assertion, change.assertion) == (
        "230", "ml", "ICE 물 230ml", "ICE 물 230ml")


# ── 값 지우기 (BLOCKED 확인) ──────────────────────────────────────────────────

async def test_empty_value_change_does_not_clear_value_text():
    # FactChange(value="") 는 parse_value("") 를 거쳐 서술값 "" 이 된다(None 이 아니다)
    assert parse_value("", None) == (None, None, "")


async def test_clearing_value_is_refused_before_writes(env):
    conn = _conn()
    with pytest.raises(EditError) as e:
        await _save(conn, _req(_modify(sentence="ICE 물을 넣는다", value=None, unit=None)))
    assert (e.value.status, e.value.code, e.value.details) == (
        422, "FACT_FIELD_INVALID", {"ref": 101, "field": "value"})
    env.revise.assert_not_awaited()
    assert not conn.sql("insert into")


# ── ADD ────────────────────────────────────────────────────────────────────

def _add(sentence, value=None, unit=None, ref="p1", **fact):
    return {"op": "ADD", "client_ref": ref,
            "fact": {"sentence": sentence, "value": value, "unit": unit, **fact}}


async def test_add_same_identity_as_kept_fact_is_422(env):
    add = _add("시럽은 넣지 않는다", value="넣지 않는다", polarity="NEGATE", predicate="시럽")
    shape = FactShape(subject="음료Z", predicate="시럽", variant_temperature=None,
                      variant_size=None, variant_other=None, quantity_value=None,
                      quantity_unit=None, value_text="넣지 않는다", polarity="NEGATE",
                      step_order=None, conditions=(), exceptions=(),
                      original_assertion="x", assertion="x")
    ident = identity_key(ENTITY, shape)
    conn = _conn(identities=[(101, "other"), (102, ident)])
    with pytest.raises(EditError) as e:
        await _save(conn, _req(extra_notes=[add]))
    assert (e.value.status, e.value.code, e.value.details) == (
        422, "FACT_DUPLICATE_IN_CARD", {"ref": "p1"})
    env.create.assert_not_awaited()


async def test_add_creates_owner_add_fact_and_owner_text(env):
    env.real = {402: _fact(402, 401, predicate="얼음", variant_temperature=None,
                           quantity_value=None, quantity_unit=None, value_text="가득",
                           original_assertion="얼음은 가득", assertion="얼음은 가득")}
    conn = _conn(identities=[(101, "a"), (102, "b")])
    result = await _save(conn, _req(extra_notes=[_add("얼음은 가득", value="가득",
                                                      predicate="얼음")]))
    kwargs = env.create.await_args.kwargs
    assert kwargs["change_kind"] == "OWNER_ADD" and kwargs["reason"] == "카드 사실 추가"
    assert kwargs["owner_answer_id"] is None and kwargs["actor_id"] == ACTOR
    assert kwargs["entity_id"] == ENTITY and kwargs["shape"].subject == "음료Z"
    assert [r.model_dump() for r in result.revisions] == [
        {"op": "ADD", "client_ref": "p1", "base_fact_revision_id": None, "fact_revision_id": 402}]
    [(_, _, src)] = conn.sql("insert into sources")
    assert src == (STORE, ACTOR, "카드 직접 입력 · 음료Z")
    [(_, _, rows)] = conn.sql("insert into fact_occurrences")
    assert rows == ((STORE, 600, 402, json.dumps({"line": 1}),
                     __import__("hashlib").sha256("얼음은 가득".encode()).hexdigest(),
                     CARD, "b2", ACTOR),)
    fe.write_version_evidence.assert_awaited_once()
    assert fe.write_version_evidence.await_args.kwargs["excerpts"] == {600: "얼음은 가득"}


# ── 처분 SQL 범위 ─────────────────────────────────────────────────────────────

async def test_disposition_sql_only_touches_this_card(env):
    env.real = {301: _water_30()}
    conn = _conn()
    conn.answers.insert(0, ("k.card_id <> $2", None))  # 다른 카드에 없음 → EXCLUDED
    result = await _save(conn, _req(_modify(), deleted=[102]))
    updates = conn.sql("update fact_occurrences")
    assert len(updates) == 2
    for _, sql, args in updates:
        assert "o.card_id = $2" in sql and "o.disposition = 'LINKED'" in sql
        assert args[0] == STORE and args[1] == CARD
    excluded = [c for c in updates if "EXCLUDED" in c[1]]
    assert excluded and excluded[0][2][2:] == (202, fe.REASON_OWNER_REMOVED, ACTOR)
    assert result.changed and [r.op for r in result.revisions] == ["MODIFY"]
    metadata = fe.cards_repo.add_event.await_args.kwargs["metadata"]
    assert metadata == {"kind": "FACT_EDIT", "edit_id": 77, "from_version_id": DRAFT,
                        "to_version_id": 900, "added": 0, "modified": 1, "deleted": 1,
                        "steps_reordered": 0, "display_reordered": False}


async def test_deleted_fact_moves_to_other_card(env):
    env.real = {301: _water_30()}
    conn = _conn()
    conn.answers.insert(0, ("k.card_id <> $2", {"card_id": 41, "block_id": "b3"}))
    await _save(conn, _req(_modify(), deleted=[102]))
    moved = [c for c in conn.sql("update fact_occurrences") if "set card_id = $4" in c[1]]
    assert moved and moved[0][2] == (STORE, CARD, 202, 41, "b3")
    assert not [c for c in conn.sql("update fact_occurrences") if "EXCLUDED" in c[1]]


async def test_all_sql_is_store_scoped(env):
    env.real = {301: _water_30()}
    conn = _conn()
    await _save(conn, _req(_modify(), deleted=[102]))
    for kind, sql, args in conn.calls:
        if "nextval" in sql:
            continue
        if kind == "executemany":
            assert all(row[0] == STORE for row in args), sql
        else:
            assert "store_id" in sql and args[0] == STORE, sql


# ── 라우터 ─────────────────────────────────────────────────────────────────

class _Db:
    def __init__(self):
        self.opened = 0

    def transaction(self):
        db = self

        class _Tx:
            async def __aenter__(self):
                db.opened += 1

            async def __aexit__(self, *exc):
                return False
        return _Tx()


async def test_route_maps_edit_error_and_uses_jwt_store(monkeypatch):
    from app.cards import router
    from app.errors import ApiError

    save = AsyncMock(side_effect=EditError(409, "CARD_VERSION_CONFLICT",
                                           {"current_version_id": 9}))
    monkeypatch.setattr(router.fact_edit, "save_fact_edit", save)
    db = _Db()
    with pytest.raises(ApiError) as e:
        await router.save_card_facts(CARD, _req(), db,
                                     {"user_id": ACTOR, "store_id": STORE, "role": "OWNER"})
    assert (e.value.status_code, e.value.code, e.value.details) == (
        409, "CARD_VERSION_CONFLICT", {"current_version_id": 9})
    assert e.value.message == fe.message_for("CARD_VERSION_CONFLICT")
    assert db.opened == 1
    assert save.await_args.args[1] == STORE and save.await_args.kwargs["actor_id"] == ACTOR
