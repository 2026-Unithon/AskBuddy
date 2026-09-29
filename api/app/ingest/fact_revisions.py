"""W2-3 수정은 새 revision — 점주 정정·점주 답변 정정·legacy 정정 이관·충돌 기각. DB 함수.

규칙 (task-3, w2-common A-4·A-5, 컨트롤러 결정 F·G·H):
  - 판(fact_revisions)과 판 메타는 불변이다. 정정은 head 를 복사해 바뀐 칸만 덮은 새 판을 넣고
    supersedes_revision_id 로 옛 판을 잇는다. 옛 판·옛 메타·원장(source_facts)은 쓰지 않는다
  - 대상·주어·속성·규격은 바꾸지 않는다(재연결은 Task 5 가 _append_revision 으로 한다)
  - 추출 원문(옛 판의 original_assertion)·정정 문장(새 판의 original_assertion)·적용 시점
    (meta.applied_at)·기록 시점(created_at)을 따로 남긴다
  - 점주 답변 정정은 fact_occurrences 를 만들지 않는다(결정 F). 출처는 판 메타의 owner_answer_id 와
    fact_owner_answer_links(결정 H)에 남는다. 점주 정정은 새 occurrence 를 만들지 않는다
  - source_facts.corrected_value 는 이관 입력으로만 읽는다. 공개 근거로 쓰지 않고 새로 쓰지도 않는다
  - 카드·card_versions·snapshot 을 건드리지 않는다(결정 G)
  - 모든 조회·쓰기는 store_id 로 좁힌다(D1)
동시성: 매장 잠금(lock_store_knowledge) → 사실 행 for update → head 확인 → 새 판 → CAS.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

import asyncpg

from app.ingest.entities import lock_store_knowledge
from app.ingest.fact_keys import FactShape, identity_key, parse_value, slot_key
from app.ingest.fact_ledger import _record_conflicts

log = logging.getLogger(__name__)

__all__ = ["FactChange", "StaleFactRevision", "revise_fact", "import_legacy_correction",
           "dismiss_conflict"]

_REVISE_KINDS = ("OWNER_CORRECTION", "OWNER_ANSWER")
_POLARITIES = ("AFFIRM", "NEGATE")
_LEGACY_REASON = "source_facts.corrected_value 이관"


@dataclass(frozen=True, kw_only=True)
class FactChange:
    """정정 내용. None 인 칸은 이전 판 값을 그대로 쓴다."""
    value: str | None = None
    unit: str | None = None
    polarity: str | None = None
    conditions: tuple[str, ...] | None = None
    exceptions: tuple[str, ...] | None = None
    step_order: int | None = None
    assertion: str | None = None
    # 필수 — 점주가 한 말(정정 문장·답변 원문). 새 판의 original_assertion 이 된다
    original_assertion: str

    def __post_init__(self) -> None:
        if not (self.original_assertion or "").strip():
            raise ValueError("original_assertion 은 비울 수 없다 — 점주가 한 말을 남긴다")
        if self.polarity is not None and self.polarity not in _POLARITIES:
            raise ValueError(f"polarity 는 {_POLARITIES} 중 하나다: {self.polarity!r}")


class StaleFactRevision(RuntimeError):
    """기대한 head 가 현재 head 가 아니다. 최신 판을 다시 읽고 정정한다."""


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def _json_tuple(value) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        value = json.loads(value) if value.strip() else []
    return tuple(str(item) for item in value)


def _decimal_text(value) -> str:
    return format(value.normalize(), "f")


def _new_value(head, change: FactChange):
    """(수치, 단위, 서술값). 값만 바꾸면 수치일 때만 head 의 단위를 물려받는다."""
    if change.value is None and change.unit is None:
        return head["quantity_value"], head["quantity_unit"], head["value_text"]
    if change.value is not None:
        if change.unit is not None:
            return parse_value(change.value, change.unit)
        quantity, unit, text = parse_value(change.value, None)
        if quantity is not None and unit is None:
            unit = head["quantity_unit"]
        return quantity, unit, text
    # 단위만 바뀜 — head 값을 새 단위로 다시 가른다
    base = (_decimal_text(head["quantity_value"]) if head["quantity_value"] is not None
            else head["value_text"] or "")
    return parse_value(base, change.unit)


def _apply_change(head, variant_other: str | None, change: FactChange) -> FactShape:
    """head 판 복사 + change 덮어쓰기. 대상·주어·속성·규격은 그대로다."""
    quantity, unit, text = _new_value(head, change)
    return FactShape(
        subject=head["subject"], predicate=head["predicate"],
        variant_temperature=head["variant_temperature"], variant_size=head["variant_size"],
        variant_other=variant_other,
        quantity_value=quantity, quantity_unit=unit, value_text=text,
        polarity=change.polarity if change.polarity is not None else head["polarity"],
        step_order=change.step_order if change.step_order is not None else head["step_order"],
        conditions=(tuple(change.conditions) if change.conditions is not None
                    else _json_tuple(head["conditions"])),
        exceptions=(tuple(change.exceptions) if change.exceptions is not None
                    else _json_tuple(head["exceptions"])),
        original_assertion=change.original_assertion,
        assertion=change.assertion or change.original_assertion,
    )


async def _lock_fact(conn: asyncpg.Connection, store_id: int, fact_id: int,
                     expected_head_revision_id: int | None) -> asyncpg.Record:
    """사실 행을 잠그고 head 를 확인한다. 없으면 LookupError, 어긋나면 StaleFactRevision.

    expected 가 None 이면 확인하지 않고 잠근 행의 head 를 기대값으로 쓴다(legacy 이관).
    """
    row = await conn.fetchrow(
        "select fact_id, entity_id, head_revision_id "
        "from knowledge_facts where store_id = $1 and fact_id = $2 for update",
        store_id, fact_id)
    if row is None:
        raise LookupError(f"사실이 없다 (store={store_id}, fact={fact_id})")
    if (expected_head_revision_id is not None
            and row["head_revision_id"] != expected_head_revision_id):
        raise StaleFactRevision(
            f"head 가 바뀌었다 (fact={fact_id}, 기대 {expected_head_revision_id}, "
            f"현재 {row['head_revision_id']})")
    return row


async def _head_of(conn: asyncpg.Connection, store_id: int,
                   revision_id: int) -> tuple[asyncpg.Record, str | None]:
    """head 판과 그 메타의 variant_other."""
    head = await conn.fetchrow(
        "select fact_revision_id, fact_id, entity_id, original_assertion, assertion, subject, "
        "predicate, variant_temperature, variant_size, quantity_value, quantity_unit, value_text, "
        "polarity, step_order, conditions, exceptions "
        "from fact_revisions where store_id = $1 and fact_revision_id = $2",
        store_id, revision_id)
    if head is None:
        raise LookupError(f"head 판이 없다 (store={store_id}, revision={revision_id})")
    variant_other = await conn.fetchval(
        "select variant_other from fact_revision_meta "
        "where store_id = $1 and fact_revision_id = $2",
        store_id, revision_id)
    return head, variant_other


async def _settle_conflicts(conn: asyncpg.Connection, store_id: int, fact_id: int, *,
                            new_revision_id: int, ident: str, slot: str, by: str,
                            actor_id: int | None) -> None:
    """이 사실이 낀 OPEN 충돌을 새 head 기준으로 정리한다. 점주 행동의 결과로만 불린다.

    상대와 값이 같아졌으면 RESOLVED, 상대와 slot 이 달라졌으면(조건·단계 정정, 재연결) OBSOLETE.
    둘 다 아니면 OPEN 그대로다. 두 사실은 어느 경우에도 남는다.
    """
    rows = await conn.fetch(
        "select c.conflict_id, o.identity_key as other_identity, o.slot_key as other_slot "
        "from fact_conflicts c "
        "join knowledge_facts o on o.store_id = c.store_id and o.fact_id = "
        "  case when c.fact_id_low = $2 then c.fact_id_high else c.fact_id_low end "
        "where c.store_id = $1 and c.status = 'OPEN' and $2 in (c.fact_id_low, c.fact_id_high) "
        "order by c.conflict_id",
        store_id, fact_id)
    resolution = _json({"by": by, "fact_revision_id": new_revision_id})
    for row in rows:
        if row["other_identity"] == ident:
            status = "RESOLVED"
        elif row["other_slot"] != slot:
            status = "OBSOLETE"
        else:
            continue
        await conn.execute(
            "update fact_conflicts set status = $3, resolution = $4::jsonb, decided_by = $5, "
            "decided_at = now() "
            "where store_id = $1 and conflict_id = $2 and status = 'OPEN'",
            store_id, row["conflict_id"], status, resolution, actor_id)


async def _append_revision(conn: asyncpg.Connection, store_id: int, *,
                           knowledge_fact_row, shape: FactShape, entity_id: int,
                           change_kind: str, actor_id: int | None,
                           reason: str | None = None, owner_answer_id: int | None = None,
                           legacy_source_fact_id: int | None = None,
                           applied_at: datetime | None = None) -> int:
    """잠근 사실 행(knowledge_fact_row)의 head 뒤에 새 판을 잇는다. 새 fact_revision_id.

    Task 5 relink_fact 도 이 헬퍼를 쓴다 — 서명을 바꾸지 않는다.
    호출 전 조건: 같은 트랜잭션에서 lock_store_knowledge 와 _lock_fact(for update)를 마쳤다.
    하는 일(순서 고정):
      1. fact_revisions 새 행 — supersedes_revision_id = 옛 head, created_by = actor_id
      2. fact_revision_meta — change_kind, 새 열쇠, variant_other(shape), applied_at(없으면 now()),
         reason, owner_answer_id, legacy_source_fact_id
      3. 옛 head 의 fact_revision_requires 를 새 판으로 복사(옛 판을 가리키는 다른 판의 requires 는 그대로)
      4. knowledge_facts CAS(head·entity·identity·slot). 영향 0 이면 StaleFactRevision
      5. 충돌 정리 — 값이 같아진 상대 RESOLVED, slot 이 갈라진 상대 OBSOLETE
         (resolution.by = 재연결이면 RELINK, 그 밖은 CORRECTION)
      6. Task 2 헬퍼 _record_conflicts 로 새 slot 의 OPEN 쌍 추가
    옛 판·옛 메타·occurrence 는 옮기거나 고치지 않는다.
    """
    fact_id = knowledge_fact_row["fact_id"]
    old_head = knowledge_fact_row["head_revision_id"]
    slot = slot_key(entity_id, shape)
    ident = identity_key(entity_id, shape)
    new_id = await conn.fetchval(
        "insert into fact_revisions (store_id, fact_id, entity_id, original_assertion, assertion, "
        "subject, predicate, variant_temperature, variant_size, quantity_value, quantity_unit, "
        "value_text, polarity, step_order, conditions, exceptions, supersedes_revision_id, "
        "created_by) "
        "values ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, "
        "$15::jsonb, $16::jsonb, $17, $18) returning fact_revision_id",
        store_id, fact_id, entity_id, shape.original_assertion, shape.assertion,
        shape.subject, shape.predicate, shape.variant_temperature, shape.variant_size,
        shape.quantity_value, shape.quantity_unit, shape.value_text, shape.polarity,
        shape.step_order, _json(list(shape.conditions)), _json(list(shape.exceptions)),
        old_head, actor_id)
    await conn.execute(
        "insert into fact_revision_meta (fact_revision_id, store_id, fact_id, change_kind, "
        "identity_key, slot_key, variant_other, applied_at, reason, owner_answer_id, "
        "legacy_source_fact_id) "
        "values ($1, $2, $3, $4, $5, $6, $7, coalesce($8::timestamptz, now()), $9, $10, $11)",
        new_id, store_id, fact_id, change_kind, ident, slot, shape.variant_other,
        applied_at, reason, owner_answer_id, legacy_source_fact_id)
    await conn.execute(
        "insert into fact_revision_requires (store_id, fact_revision_id, requires_revision_id) "
        "select store_id, $2, requires_revision_id from fact_revision_requires "
        "where store_id = $1 and fact_revision_id = $3 "
        "on conflict do nothing",
        store_id, new_id, old_head)
    status = await conn.execute(
        "update knowledge_facts set head_revision_id = $4, entity_id = $5, identity_key = $6, "
        "slot_key = $7, updated_at = now() "
        "where store_id = $1 and fact_id = $2 and head_revision_id = $3",
        store_id, fact_id, old_head, new_id, entity_id, ident, slot)
    if status.split()[-1] == "0":
        raise StaleFactRevision(f"head 가 바뀌었다 (fact={fact_id}, 기대 {old_head})")
    await _settle_conflicts(conn, store_id, fact_id, new_revision_id=new_id, ident=ident,
                            slot=slot, by="RELINK" if change_kind == "RELINK" else "CORRECTION",
                            actor_id=actor_id)
    await _record_conflicts(conn, store_id, fact_id)
    log.info("W2 새 판 store=%s fact=%s %s → %s (%s)", store_id, fact_id, old_head, new_id,
             change_kind)
    return new_id


async def _check_owner_answer_store(conn: asyncpg.Connection, store_id: int,
                                    owner_answer_id: int) -> None:
    # 메타 트리거도 막지만, 판을 넣기 전에 ValueError 로 먼저 막는다
    found = await conn.fetchval(
        "select pq.store_id from owner_answers oa "
        "join pending_questions pq on pq.question_id = oa.question_id "
        "where oa.answer_id = $1 and pq.store_id = $2",
        owner_answer_id, store_id)
    if found is None:
        raise ValueError(f"이 매장의 점주 답변이 아니다 (store={store_id}, answer={owner_answer_id})")


async def revise_fact(conn: asyncpg.Connection, store_id: int, *, fact_id: int,
                      expected_head_revision_id: int, change: FactChange,
                      change_kind: Literal["OWNER_CORRECTION", "OWNER_ANSWER"], actor_id: int,
                      owner_answer_id: int | None = None, reason: str | None = None,
                      applied_at: datetime | None = None) -> int:
    """점주 정정·점주 답변 정정을 새 판으로 남긴다. 새 fact_revision_id.

    OWNER_ANSWER 는 owner_answer_id 가 필수이고 그 밖은 None 이어야 한다(어기면 ValueError).
    head 가 expected 와 다르면 StaleFactRevision — 아무것도 쓰지 않는다.
    """
    if change_kind not in _REVISE_KINDS:
        raise ValueError(f"revise_fact 의 change_kind 는 {_REVISE_KINDS} 중 하나다: {change_kind!r}")
    if change_kind == "OWNER_ANSWER" and owner_answer_id is None:
        raise ValueError("OWNER_ANSWER 정정에는 owner_answer_id 가 필요하다")
    if change_kind != "OWNER_ANSWER" and owner_answer_id is not None:
        raise ValueError("owner_answer_id 는 OWNER_ANSWER 정정에만 쓴다")
    async with conn.transaction():
        await lock_store_knowledge(conn, store_id)
        if owner_answer_id is not None:
            await _check_owner_answer_store(conn, store_id, owner_answer_id)
        row = await _lock_fact(conn, store_id, fact_id, expected_head_revision_id)
        head, variant_other = await _head_of(conn, store_id, row["head_revision_id"])
        shape = _apply_change(head, variant_other, change)
        new_id = await _append_revision(
            conn, store_id, knowledge_fact_row=row, shape=shape, entity_id=row["entity_id"],
            change_kind=change_kind, actor_id=actor_id, reason=reason,
            owner_answer_id=owner_answer_id, applied_at=applied_at)
        if owner_answer_id is not None:
            # 점주 답변 출처(결정 H). 같은 답변이 이미 이 사실에 이어져 있으면 그 행을 둔다
            await conn.execute(
                "insert into fact_owner_answer_links "
                "(store_id, fact_id, fact_revision_id, owner_answer_id) values ($1, $2, $3, $4) "
                "on conflict (store_id, fact_id, owner_answer_id) do nothing",
                store_id, fact_id, new_id, owner_answer_id)
    return new_id


async def import_legacy_correction(conn: asyncpg.Connection, store_id: int, *,
                                   source_fact_id: int) -> int | None:
    """source_facts.corrected_value 를 LEGACY_CORRECTION 판으로 옮긴다. 새(또는 이미 옮긴) 판 id.

    corrected_value 가 없거나 비었으면 None. 원장 사실이 아직 판에 이어지지 않았으면 None
    (판이 없는 사실은 옮기지 않는다). 이미 옮겼으면 그 판 id(멱등). 원장은 읽기만 한다.
    """
    async with conn.transaction():
        await lock_store_knowledge(conn, store_id)
        ledger = await conn.fetchrow(
            "select fact_id, corrected_value, corrected_at, corrected_by "
            "from source_facts where store_id = $1 and fact_id = $2",
            store_id, source_fact_id)
        if ledger is None or not (ledger["corrected_value"] or "").strip():
            return None
        fact_id = await conn.fetchval(
            "select fact_id from source_fact_revision_links "
            "where store_id = $1 and source_fact_id = $2",
            store_id, source_fact_id)
        if fact_id is None:
            return None
        done = await conn.fetchval(
            "select fact_revision_id from fact_revision_meta "
            "where store_id = $1 and legacy_source_fact_id = $2",
            store_id, source_fact_id)
        if done is not None:
            return done
        # CAS 기대값은 지금의 head 다(잠근 행에서 읽는다)
        row = await _lock_fact(conn, store_id, fact_id, None)
        head, variant_other = await _head_of(conn, store_id, row["head_revision_id"])
        corrected = ledger["corrected_value"]
        shape = _apply_change(head, variant_other,
                              FactChange(value=corrected, original_assertion=corrected))
        return await _append_revision(
            conn, store_id, knowledge_fact_row=row, shape=shape, entity_id=row["entity_id"],
            change_kind="LEGACY_CORRECTION", actor_id=ledger["corrected_by"],
            reason=_LEGACY_REASON, legacy_source_fact_id=source_fact_id,
            applied_at=ledger["corrected_at"])


async def dismiss_conflict(conn: asyncpg.Connection, store_id: int, conflict_id: int, *,
                           actor_id: int, note: str | None) -> None:
    """점주가 충돌을 기각한다(두 값 모두 맞음 등). OPEN 만 DISMISSED 로, 두 사실은 그대로 남는다.

    없는 충돌이면 LookupError, OPEN 이 아니면 ValueError.
    resolution 에 기각 당시 두 사실의 head 판 id 를 남긴다(dismissed_revision_ids) — 값이 그대로면
    이후 판이 바뀌어도 다시 열지 않는다(결정 I, fact_ledger._record_conflicts).
    """
    async with conn.transaction():
        await lock_store_knowledge(conn, store_id)
        row = await conn.fetchrow(
            "select c.status, c.fact_id_low, c.fact_id_high, "
            "kl.head_revision_id as low_head, kh.head_revision_id as high_head "
            "from fact_conflicts c "
            "join knowledge_facts kl on kl.store_id = c.store_id and kl.fact_id = c.fact_id_low "
            "join knowledge_facts kh on kh.store_id = c.store_id and kh.fact_id = c.fact_id_high "
            "where c.store_id = $1 and c.conflict_id = $2 for update of c",
            store_id, conflict_id)
        if row is None:
            raise LookupError(f"충돌이 없다 (store={store_id}, conflict={conflict_id})")
        if row["status"] != "OPEN":
            raise ValueError(f"OPEN 충돌만 기각한다 (conflict={conflict_id}, 상태 {row['status']})")
        resolution = {"note": note, "dismissed_revision_ids": {
            str(row["fact_id_low"]): row["low_head"], str(row["fact_id_high"]): row["high_head"]}}
        await conn.execute(
            "update fact_conflicts set status = 'DISMISSED', decided_by = $3, decided_at = now(), "
            "resolution = $4::jsonb "
            "where store_id = $1 and conflict_id = $2 and status = 'OPEN'",
            store_id, conflict_id, actor_id, _json(resolution))
