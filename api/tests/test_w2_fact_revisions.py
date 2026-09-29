"""W2-3 수정은 새 revision — 정정 판·legacy 이관·충돌 기각의 SQL 순서·인자.

DB 는 부르지 않는다. FakeConn 이 SQL 을 기록하고 조회에는 미리 정한 행을 돌려준다.
실제 DB 동작(불변 트리거·CAS·충돌 해소)은 scripts/verify_w_entity_revision.py 의 V1~V6 이 본다.
"""
import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.ingest import fact_revisions as fr
from app.ingest.fact_keys import FactShape, identity_key, slot_key
from app.ingest.fact_revisions import FactChange, StaleFactRevision

STORE, FACT, HEAD, NEW, ENTITY, ACTOR = 3, 70, 700, 701, 9, 11


def _head_revision(**over):
    row = dict(fact_revision_id=HEAD, fact_id=FACT, entity_id=ENTITY,
               original_assertion="음료Z 시럽 20ml", assertion="음료Z 시럽 20ml",
               subject="음료Z", predicate="시럽", variant_temperature="ICE", variant_size=None,
               quantity_value=Decimal("20"), quantity_unit="ml", value_text=None,
               polarity="AFFIRM", step_order=2,
               conditions=json.dumps(["바쁠 때"]), exceptions=json.dumps(["디카페인"]))
    row.update(over)
    return row


def _shape_of(row, variant_other=None) -> FactShape:
    return FactShape(
        subject=row["subject"], predicate=row["predicate"],
        variant_temperature=row["variant_temperature"], variant_size=row["variant_size"],
        variant_other=variant_other, quantity_value=row["quantity_value"],
        quantity_unit=row["quantity_unit"], value_text=row["value_text"],
        polarity=row["polarity"], step_order=row["step_order"],
        conditions=tuple(json.loads(row["conditions"])),
        exceptions=tuple(json.loads(row["exceptions"])),
        original_assertion=row["original_assertion"], assertion=row["assertion"])


class FakeConn:
    """SQL 을 기록한다. 응답은 SQL 조각 → 값 목록(순서대로 소비)."""

    def __init__(self, *, head_id=HEAD, head=None, variant_other=None, cas="UPDATE 1",
                 open_conflicts=(), extra=None):
        self.calls: list[tuple[str, str, tuple]] = []
        head = head or _head_revision()
        self.responses = {
            "from knowledge_facts where store_id = $1 and fact_id = $2 for update":
                dict(fact_id=FACT, entity_id=ENTITY, head_revision_id=head_id),
            "from fact_revisions where store_id = $1 and fact_revision_id = $2": head,
            "select variant_other from fact_revision_meta": variant_other,
            "insert into fact_revisions": NEW,
            "update knowledge_facts": cas,
            "from fact_conflicts c": list(open_conflicts),
        }
        self.responses.update(extra or {})

    def _answer(self, sql):
        for key, value in self.responses.items():
            if key in sql:
                return value
        return None

    async def execute(self, sql, *args):
        self.calls.append(("execute", sql, args))
        answer = self._answer(sql)
        return answer if isinstance(answer, str) else "INSERT 0 1"

    async def fetchval(self, sql, *args):
        self.calls.append(("fetchval", sql, args))
        return self._answer(sql)

    async def fetchrow(self, sql, *args):
        self.calls.append(("fetchrow", sql, args))
        return self._answer(sql)

    async def fetch(self, sql, *args):
        self.calls.append(("fetch", sql, args))
        answer = self._answer(sql)
        return answer if isinstance(answer, list) else []

    @asynccontextmanager
    async def transaction(self):
        yield

    def sql(self, fragment):
        return [c for c in self.calls if fragment in c[1]]


def order_of(conn, fragment):
    return next(i for i, c in enumerate(conn.calls) if fragment in c[1])


def _change(**kw):
    kw.setdefault("original_assertion", "시럽은 30ml 로 바꿨어요")
    return FactChange(**kw)


async def _revise(conn, change=None, **kw):
    kw.setdefault("change_kind", "OWNER_CORRECTION")
    kw.setdefault("expected_head_revision_id", HEAD)
    return await fr.revise_fact(conn, STORE, fact_id=FACT, change=change or _change(value="30"),
                                actor_id=ACTOR, **kw)


# ── 인자 검증 ────────────────────────────────────────────────────────────────

def test_empty_original_assertion_is_rejected():
    with pytest.raises(ValueError):
        FactChange(value="30", original_assertion="")
    with pytest.raises(ValueError):
        FactChange(value="30", original_assertion="   ")


@pytest.mark.asyncio
async def test_owner_answer_without_owner_answer_id_is_rejected_before_db():
    conn = FakeConn()
    with pytest.raises(ValueError):
        await _revise(conn, change_kind="OWNER_ANSWER", owner_answer_id=None)
    assert conn.calls == []


@pytest.mark.asyncio
async def test_owner_correction_with_owner_answer_id_is_rejected_before_db():
    conn = FakeConn()
    with pytest.raises(ValueError):
        await _revise(conn, change_kind="OWNER_CORRECTION", owner_answer_id=5)
    assert conn.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["LEGACY_CORRECTION", "RELINK", "EXTRACTION", "owner_correction"])
async def test_revise_fact_rejects_other_change_kinds(kind):
    conn = FakeConn()
    with pytest.raises(ValueError):
        await _revise(conn, change_kind=kind)
    assert conn.calls == []


# ── head 확인 ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_stale_head_raises_and_inserts_nothing():
    conn = FakeConn(head_id=699)
    with pytest.raises(StaleFactRevision):
        await _revise(conn)
    assert not [c for c in conn.calls if c[1].lstrip().lower().startswith(("insert", "update"))]


@pytest.mark.asyncio
async def test_missing_fact_raises_lookup_error():
    conn = FakeConn()
    conn.responses["from knowledge_facts where store_id = $1 and fact_id = $2 for update"] = None
    with pytest.raises(LookupError):
        await _revise(conn)
    assert not conn.sql("insert into")


@pytest.mark.asyncio
async def test_cas_miss_raises_stale():
    conn = FakeConn(cas="UPDATE 0")
    with pytest.raises(StaleFactRevision):
        await _revise(conn)


# ── 새 판 = head 복사 + 바뀐 칸 ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_value_only_change_keeps_conditions_exceptions_step_and_unit():
    conn = FakeConn(variant_other="레귤러컵")
    new_id = await _revise(conn, change=_change(value="30"), reason="점주 정정")
    assert new_id == NEW

    # 잠금이 가장 먼저, 그다음 사실 행 for update(매장 한정)
    assert "pg_advisory_xact_lock" in conn.calls[0][1]
    locked = conn.sql("for update")[0]
    assert locked[2] == (STORE, FACT)

    insert = conn.sql("insert into fact_revisions")[0][2]
    (store, fact, entity, original, assertion, subject, predicate, temp, size, qty, unit,
     text, polarity, step, conditions, exceptions, supersedes, created_by) = insert
    assert (store, fact, entity) == (STORE, FACT, ENTITY)
    assert original == assertion == "시럽은 30ml 로 바꿨어요"
    assert (subject, predicate, temp, size) == ("음료Z", "시럽", "ICE", None)
    assert (qty, unit, text) == (Decimal("30"), "ml", None)
    assert (polarity, step) == ("AFFIRM", 2)
    assert json.loads(conditions) == ["바쁠 때"] and json.loads(exceptions) == ["디카페인"]
    assert (supersedes, created_by) == (HEAD, ACTOR)

    expected = _shape_of(_head_revision(quantity_value=Decimal("30")), variant_other="레귤러컵")
    meta = conn.sql("insert into fact_revision_meta")[0][2]
    (rev_id, store, fact, kind, ident, slot, other, applied_at, reason, answer, legacy) = meta
    assert (rev_id, store, fact, kind) == (NEW, STORE, FACT, "OWNER_CORRECTION")
    assert ident == identity_key(ENTITY, expected) and slot == slot_key(ENTITY, expected)
    assert other == "레귤러컵"
    assert applied_at is None          # SQL 이 coalesce(..., now())
    assert (reason, answer, legacy) == ("점주 정정", None, None)

    # 요구 관계 복사 — 옛 판 → 새 판
    requires = conn.sql("insert into fact_revision_requires")[0][2]
    assert requires == (STORE, NEW, HEAD)

    # CAS 는 판·메타·요구 뒤에, 기대 head 로
    cas = conn.sql("update knowledge_facts")[0]
    assert cas[2][:3] == (STORE, FACT, HEAD) and NEW in cas[2]
    order = [c[1] for c in conn.calls]
    first = lambda frag: next(i for i, s in enumerate(order) if frag in s)
    assert (first("insert into fact_revisions") < first("insert into fact_revision_meta")
            < first("insert into fact_revision_requires") < first("update knowledge_facts"))

    # 옛 판·옛 메타·원장은 건드리지 않는다
    assert not conn.sql("update fact_revisions") and not conn.sql("update fact_revision_meta")
    assert not conn.sql("delete from") and not conn.sql("source_facts set")
    # 정정은 occurrence·점주 답변 연결을 만들지 않는다
    assert not conn.sql("fact_occurrences") and not conn.sql("fact_owner_answer_links")


@pytest.mark.asyncio
async def test_non_numeric_new_value_does_not_inherit_unit():
    conn = FakeConn()
    await _revise(conn, change=_change(value="반 컵"))
    insert = conn.sql("insert into fact_revisions")[0][2]
    assert insert[9:12] == (None, None, "반 컵")


@pytest.mark.asyncio
async def test_explicit_fields_and_assertion_override():
    conn = FakeConn()
    applied = datetime(2026, 9, 1, tzinfo=timezone.utc)
    await _revise(conn, change=_change(value="2", unit="분", polarity="NEGATE",
                                       conditions=(), exceptions=("주말",), step_order=3,
                                       assertion="시럽 2분"), applied_at=applied)
    insert = conn.sql("insert into fact_revisions")[0][2]
    assert insert[3:5] == ("시럽은 30ml 로 바꿨어요", "시럽 2분")
    assert insert[9:14] == (Decimal("2"), "min", None, "NEGATE", 3)
    assert json.loads(insert[14]) == [] and json.loads(insert[15]) == ["주말"]
    assert conn.sql("insert into fact_revision_meta")[0][2][7] == applied


@pytest.mark.asyncio
async def test_owner_answer_revision_records_meta_and_owner_link_not_occurrence():
    conn = FakeConn(extra={"from owner_answers oa": STORE})
    await _revise(conn, change_kind="OWNER_ANSWER", owner_answer_id=55)
    meta = conn.sql("insert into fact_revision_meta")[0][2]
    assert (meta[3], meta[9]) == ("OWNER_ANSWER", 55)
    link = conn.sql("insert into fact_owner_answer_links")[0][2]
    assert link == (STORE, FACT, NEW, 55)
    assert not conn.sql("fact_occurrences")      # 결정 F


@pytest.mark.asyncio
async def test_owner_answer_from_other_store_is_rejected():
    conn = FakeConn(extra={"from owner_answers oa": None})
    with pytest.raises(ValueError):
        await _revise(conn, change_kind="OWNER_ANSWER", owner_answer_id=55)
    assert not conn.sql("insert into")


# ── 충돌 ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_conflict_resolved_when_values_converge_obsolete_when_slot_leaves():
    corrected = _shape_of(_head_revision(quantity_value=Decimal("30")))
    same_ident = identity_key(ENTITY, corrected)
    same_slot = slot_key(ENTITY, corrected)
    conn = FakeConn(open_conflicts=[
        dict(conflict_id=1, other_identity=same_ident, other_slot=same_slot),
        dict(conflict_id=2, other_identity="x" * 64, other_slot=same_slot),
        dict(conflict_id=3, other_identity="y" * 64, other_slot="z" * 64),
    ])
    await _revise(conn)
    updates = {c[2][1]: c[2] for c in conn.sql("update fact_conflicts")}
    assert set(updates) == {1, 3}
    assert updates[1][2] == "RESOLVED"
    assert json.loads(updates[1][3]) == {"by": "CORRECTION", "fact_revision_id": NEW}
    assert updates[1][4] == ACTOR
    assert updates[3][2] == "OBSOLETE"
    # 새 쌍 계산은 Task 2 헬퍼 _record_conflicts — 새 head 기준으로 같은 conn 에서 부른다
    helper = conn.sql("from knowledge_facts k")
    assert helper and helper[0][2] == (STORE, FACT)
    assert order_of(conn, "update knowledge_facts") < order_of(conn, "from knowledge_facts k")


# ── legacy 이관 ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_legacy_without_corrected_value_returns_none():
    conn = FakeConn(extra={"from source_facts": dict(fact_id=5, corrected_value=None,
                                                     corrected_at=None, corrected_by=None)})
    assert await fr.import_legacy_correction(conn, STORE, source_fact_id=5) is None
    assert not conn.sql("insert into")


@pytest.mark.asyncio
async def test_legacy_without_link_returns_none():
    conn = FakeConn(extra={
        "from source_facts": dict(fact_id=5, corrected_value="30", corrected_at=None,
                                  corrected_by=None),
        "from source_fact_revision_links": None})
    assert await fr.import_legacy_correction(conn, STORE, source_fact_id=5) is None
    assert not conn.sql("insert into")


@pytest.mark.asyncio
async def test_legacy_already_imported_returns_existing_revision():
    conn = FakeConn(extra={
        "from source_facts": dict(fact_id=5, corrected_value="30", corrected_at=None,
                                  corrected_by=None),
        "from source_fact_revision_links": FACT,
        "legacy_source_fact_id = $2": 650})
    assert await fr.import_legacy_correction(conn, STORE, source_fact_id=5) == 650
    assert not conn.sql("insert into")


@pytest.mark.asyncio
async def test_legacy_import_appends_revision_with_legacy_fields():
    at = datetime(2026, 9, 10, tzinfo=timezone.utc)
    conn = FakeConn(extra={
        "from source_facts": dict(fact_id=5, corrected_value="25", corrected_at=at,
                                  corrected_by=ACTOR),
        "from source_fact_revision_links": FACT,
        "legacy_source_fact_id = $2": None})
    assert await fr.import_legacy_correction(conn, STORE, source_fact_id=5) == NEW
    insert = conn.sql("insert into fact_revisions")[0][2]
    assert insert[3:5] == ("25", "25") and insert[9:11] == (Decimal("25"), "ml")
    assert (insert[16], insert[17]) == (HEAD, ACTOR)
    meta = conn.sql("insert into fact_revision_meta")[0][2]
    assert (meta[3], meta[7], meta[8], meta[10]) == (
        "LEGACY_CORRECTION", at, "source_facts.corrected_value 이관", 5)
    assert not conn.sql("source_facts set")


# ── 충돌 기각 ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_dismiss_open_conflict():
    conn = FakeConn()
    conn.responses = {"from fact_conflicts c": dict(
        status="OPEN", fact_id_low=70, fact_id_high=80, low_head=700, high_head=800)}
    await fr.dismiss_conflict(conn, STORE, 8, actor_id=ACTOR, note="둘 다 맞음")
    locked = conn.sql("from fact_conflicts c")[0]
    assert locked[2] == (STORE, 8) and "for update" in locked[1]
    update = conn.sql("update fact_conflicts")[0]
    assert "status = 'OPEN'" in update[1] and "'DISMISSED'" in update[1]
    assert update[2][:3] == (STORE, 8, ACTOR)


@pytest.mark.asyncio
async def test_dismiss_non_open_conflict_raises_value_error():
    conn = FakeConn()
    conn.responses = {"from fact_conflicts c": dict(
        status="DISMISSED", fact_id_low=70, fact_id_high=80, low_head=700, high_head=800)}
    with pytest.raises(ValueError):
        await fr.dismiss_conflict(conn, STORE, 8, actor_id=ACTOR, note=None)
    assert not conn.sql("update fact_conflicts")


@pytest.mark.asyncio
async def test_dismiss_missing_conflict_raises_lookup_error():
    conn = FakeConn()
    conn.responses = {"from fact_conflicts c": None}
    with pytest.raises(LookupError):
        await fr.dismiss_conflict(conn, STORE, 8, actor_id=ACTOR, note=None)


# ── 결정 I: 기각한 쌍은 값이 바뀔 때만 다시 연다 ─────────────────────────────

from app.ingest import fact_ledger  # noqa: E402
from app.ingest.fact_keys import value_signature  # noqa: E402


def test_value_signature_ignores_wording_and_scale():
    assert value_signature("AFFIRM", Decimal("275"), "ml", None) \
        == value_signature("AFFIRM", Decimal("275.0"), "ml", None)
    assert value_signature("AFFIRM", None, None, "컵에  얼음") \
        == value_signature("AFFIRM", None, None, "컵에 얼음")
    assert value_signature("AFFIRM", Decimal("20"), "ml", None) \
        != value_signature("AFFIRM", Decimal("30"), "ml", None)
    assert value_signature("AFFIRM", Decimal("20"), "ml", None) \
        != value_signature("NEGATE", Decimal("20"), "ml", None)
    assert value_signature("AFFIRM", Decimal("20"), "ml", None) \
        != value_signature("AFFIRM", Decimal("20"), "g", None)


def _head(fact_id, revision_id, qty):
    return dict(fact_id=fact_id, head_revision_id=revision_id, entity_id=ENTITY,
                slot_key="s" * 64, identity_key=f"i{qty}", polarity="AFFIRM",
                quantity_value=Decimal(qty), quantity_unit="ml", value_text=None)


class LedgerConn:
    """_record_conflicts 용 — 나(me)·상대·마지막 결정 행·기각 당시 판."""

    def __init__(self, me, other, decided, dismissed_revisions):
        self.me, self.other, self.decided = me, other, decided
        self.dismissed_revisions = dismissed_revisions
        self.inserts = []

    async def fetchrow(self, sql, *args):
        if "from knowledge_facts k" in sql:
            return self.me
        if "status <> 'OPEN'" in sql:
            return self.decided
        raise AssertionError(sql)

    async def fetch(self, sql, *args):
        if "k.slot_key = $2" in sql:
            return [self.other]
        if "fact_revision_id = any(" in sql:
            assert args[0] == STORE
            return self.dismissed_revisions
        raise AssertionError(sql)

    async def fetchval(self, sql, *args):
        assert "insert into fact_conflicts" in sql
        self.inserts.append(args)
        return 99


def _dismissed(low_rev, high_rev):
    return dict(conflict_id=5, status="DISMISSED", resolution=json.dumps(
        {"note": None, "dismissed_revision_ids": {"70": low_rev, "80": high_rev}}))


def _rev(revision_id, qty):
    return dict(fact_revision_id=revision_id, polarity="AFFIRM", quantity_value=Decimal(qty),
                quantity_unit="ml", value_text=None)


@pytest.mark.asyncio
async def test_dismissed_pair_stays_dismissed_when_values_unchanged():
    # 70 은 문구·조건만 바뀐 새 head(702), 값은 기각 당시(700)와 같다
    conn = LedgerConn(_head(70, 702, "20"), _head(80, 800, "30"), _dismissed(700, 800),
                      [_rev(700, "20"), _rev(800, "30")])
    assert await fact_ledger._record_conflicts(conn, STORE, 70) == 0
    assert conn.inserts == []


@pytest.mark.asyncio
async def test_dismissed_pair_reopens_when_a_value_changed():
    conn = LedgerConn(_head(70, 702, "25"), _head(80, 800, "30"), _dismissed(700, 800),
                      [_rev(700, "20"), _rev(800, "30")])
    assert await fact_ledger._record_conflicts(conn, STORE, 70) == 1
    assert conn.inserts[0][3:5] == (70, 80)


@pytest.mark.asyncio
async def test_resolved_pair_that_splits_again_reopens():
    decided = dict(conflict_id=5, status="RESOLVED",
                   resolution=json.dumps({"by": "CORRECTION", "fact_revision_id": 701}))
    conn = LedgerConn(_head(70, 702, "20"), _head(80, 800, "30"), decided, [])
    assert await fact_ledger._record_conflicts(conn, STORE, 70) == 1


@pytest.mark.asyncio
async def test_dismiss_records_heads_of_both_facts():
    conn = FakeConn()
    conn.responses = {"from fact_conflicts c": dict(
        status="OPEN", fact_id_low=70, fact_id_high=80, low_head=700, high_head=800)}
    await fr.dismiss_conflict(conn, STORE, 8, actor_id=ACTOR, note="둘 다 맞음")
    update = conn.sql("update fact_conflicts")[0]
    assert json.loads(update[2][3]) == {"note": "둘 다 맞음",
                                        "dismissed_revision_ids": {"70": 700, "80": 800}}
