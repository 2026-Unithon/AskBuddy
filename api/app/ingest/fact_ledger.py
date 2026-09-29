"""W2-2 원장 → 사실 판(revision)·occurrence 연결, 점주 답변 사실, 충돌 조회 — DB 함수.

규칙 (w2-common A-2·A-4·A-5, task-2, 컨트롤러 결정 F·G):
  - 원장 사실마다 대상을 정하고, 같은 사실(같은 identity_key)이 있으면 그 head 판에 잇는다(MATCHED).
    없으면 새 사실·새 판을 만든다(CREATED). 판은 불변이며 원장(source_facts)도 고치지 않는다
  - 같은 slot 의 다른 값은 새 사실로 남기고 충돌 쌍(OPEN)만 적는다. 기본 선택·승자는 없다
  - occurrence 는 REVIEW_PENDING(사유 필수)으로만 만든다. 카드 블록에 잇는 LINKED 는 W3 다
  - 점주 답변 사실은 파일 출처를 만들지 않는다. fact_occurrences 행은 만들지 않고(결정 F),
    출처는 fact_owner_answer_links 에 남는다(결정 H). 새 사실이면 판 메타에도 owner_answer_id 가 있다
  - 기존 카드 행을 쓰지 않는다(결정 G)
  - 모든 조회·쓰기는 store_id 로 좁힌다(D1)
동시성: 연결을 시작할 때 매장 잠금(lock_store_knowledge)을 한 번 잡는다.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass

import asyncpg

from app.ingest.entities import EntityUnresolvable, lock_store_knowledge, resolve_entity
from app.ingest.entity_names import normalize_subject, parse_variant
from app.ingest.fact_keys import (FactShape, identity_key, original_missing,
                                  shape_from_ledger, slot_key, value_signature)

log = logging.getLogger(__name__)

__all__ = ["LinkOutcome", "link_source_facts", "record_owner_answer_fact", "open_conflicts_for",
           "list_open_conflicts", "card_entity_for", "shape_from_ledger"]

_ORIGINAL_MISSING = "ORIGINAL_MISSING"
_LOCAL_REF_MAX = 40   # source_facts.local_ref 는 40자로 잘려 저장된다


@dataclass(frozen=True)
class LinkOutcome:
    created: int
    matched: int
    skipped: tuple[int, ...]   # 대상 결정 불가 source_fact id
    occurrences: int
    conflicts: int


_EMPTY = LinkOutcome(created=0, matched=0, skipped=(), occurrences=0, conflicts=0)


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def _json_list(value) -> list:
    if value is None:
        return []
    if isinstance(value, str):
        return json.loads(value) if value.strip() else []
    return list(value)


async def _find_same_fact(conn: asyncpg.Connection, store_id: int,
                          ident: str) -> asyncpg.Record | None:
    """같은 사실 — 같은 매장·같은 identity_key 중 가장 작은 fact_id (A-4)."""
    return await conn.fetchrow(
        "select fact_id, head_revision_id, entity_id from knowledge_facts "
        "where store_id = $1 and identity_key = $2 order by fact_id limit 1",
        store_id, ident)


async def _record_conflicts(conn: asyncpg.Connection, store_id: int, fact_id: int) -> int:
    """이 사실과 같은 slot·다른 identity 의 사실마다 OPEN 충돌 쌍을 남긴다. 새로 남긴 수를 돌려준다.

    정정(Task 3)·재연결(Task 5)도 이 헬퍼만 쓴다. 두 사실은 그대로 남는다.
    결정 I: 점주가 기각(DISMISSED)한 쌍은 두 사실의 값(value_signature)이 기각 당시 판과 같으면
    다시 열지 않는다. 값이 바뀌었거나 마지막 결정이 RESOLVED·OBSOLETE 면 새 OPEN 행을 남긴다.
    """
    me = await conn.fetchrow(
        "select k.entity_id, k.slot_key, k.identity_key, r.quantity_value, r.quantity_unit, "
        "r.value_text, r.polarity "
        "from knowledge_facts k "
        "join fact_revisions r on r.store_id = k.store_id "
        "  and r.fact_revision_id = k.head_revision_id "
        "where k.store_id = $1 and k.fact_id = $2",
        store_id, fact_id)
    if me is None:
        return 0
    others = await conn.fetch(
        "select k.fact_id, r.quantity_value, r.quantity_unit, r.value_text, r.polarity "
        "from knowledge_facts k "
        "join fact_revisions r on r.store_id = k.store_id "
        "  and r.fact_revision_id = k.head_revision_id "
        "where k.store_id = $1 and k.slot_key = $2 and k.identity_key <> $3 "
        "and k.fact_id <> $4 order by k.fact_id",
        store_id, me["slot_key"], me["identity_key"], fact_id)
    added = 0
    for other in others:
        low, high = sorted((fact_id, other["fact_id"]))
        if await _still_dismissed(conn, store_id, low, high,
                                  {fact_id: me, other["fact_id"]: other}):
            continue
        mine_numeric = me["quantity_value"] is not None
        other_numeric = other["quantity_value"] is not None
        kind = ("NUMERIC" if mine_numeric and other_numeric
                else "TEXT" if not mine_numeric and not other_numeric else "MIXED")
        conflict_id = await conn.fetchval(
            "insert into fact_conflicts "
            "(store_id, entity_id, slot_key, fact_id_low, fact_id_high, value_kind) "
            "values ($1, $2, $3, $4, $5, $6) "
            "on conflict (store_id, fact_id_low, fact_id_high) where status = 'OPEN' do nothing "
            "returning conflict_id",
            store_id, me["entity_id"], me["slot_key"], low, high, kind)
        if conflict_id is not None:
            added += 1
    return added


def _signature(row) -> tuple:
    return value_signature(row["polarity"] or "AFFIRM", row["quantity_value"],
                           row["quantity_unit"], row["value_text"])


async def _still_dismissed(conn: asyncpg.Connection, store_id: int, low: int, high: int,
                           current: dict) -> bool:
    """이 쌍의 마지막 결정이 기각이고 두 사실의 값이 기각 당시 판과 같은가 (결정 I).

    current = {fact_id: 지금 head 판의 값 칸}. 기각 당시 판 id 는 resolution.dismissed_revision_ids 에 있다.
    판은 불변이라 그 id 로 당시 값을 다시 읽는다. 기록이 없으면(예전 행) 다시 연다.
    """
    decided = await conn.fetchrow(
        "select conflict_id, status, resolution from fact_conflicts "
        "where store_id = $1 and fact_id_low = $2 and fact_id_high = $3 and status <> 'OPEN' "
        "order by conflict_id desc limit 1",
        store_id, low, high)
    if decided is None or decided["status"] != "DISMISSED":
        return False
    resolution = decided["resolution"]
    if isinstance(resolution, str):
        resolution = json.loads(resolution)
    at_dismissal = (resolution or {}).get("dismissed_revision_ids") or {}
    revision_of = {fid: at_dismissal.get(str(fid)) for fid in (low, high)}
    if any(rev is None for rev in revision_of.values()):
        return False
    then = {r["fact_revision_id"]: r for r in await conn.fetch(
        "select fact_revision_id, polarity, quantity_value, quantity_unit, value_text "
        "from fact_revisions where store_id = $1 and fact_revision_id = any($2::bigint[])",
        store_id, [int(rev) for rev in revision_of.values()])}
    for fid, rev in revision_of.items():
        old = then.get(int(rev))
        if old is None or _signature(old) != _signature(current[fid]):
            return False
    return True


async def _create_fact(conn: asyncpg.Connection, store_id: int, *, entity_id: int,
                       shape: FactShape, slot: str, ident: str, change_kind: str,
                       reason: str | None, owner_answer_id: int | None,
                       actor_id: int | None) -> tuple[int, int]:
    """새 사실 + 첫 판 + 메타 + head 포인터. (fact_id, fact_revision_id)."""
    fact_id = await conn.fetchval(
        "insert into knowledge_facts (store_id, entity_id, identity_key, slot_key) "
        "values ($1, $2, $3, $4) returning fact_id",
        store_id, entity_id, ident, slot)
    revision_id = await conn.fetchval(
        "insert into fact_revisions (store_id, fact_id, entity_id, original_assertion, assertion, "
        "subject, predicate, variant_temperature, variant_size, quantity_value, quantity_unit, "
        "value_text, polarity, step_order, conditions, exceptions, supersedes_revision_id, "
        "created_by) "
        "values ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, "
        "$15::jsonb, $16::jsonb, null, $17) returning fact_revision_id",
        store_id, fact_id, entity_id, shape.original_assertion, shape.assertion,
        shape.subject, shape.predicate, shape.variant_temperature, shape.variant_size,
        shape.quantity_value, shape.quantity_unit, shape.value_text, shape.polarity,
        shape.step_order, _json(list(shape.conditions)), _json(list(shape.exceptions)),
        actor_id)
    await conn.execute(
        "insert into fact_revision_meta (fact_revision_id, store_id, fact_id, change_kind, "
        "identity_key, slot_key, variant_other, reason, owner_answer_id) "
        "values ($1, $2, $3, $4, $5, $6, $7, $8, $9)",
        revision_id, store_id, fact_id, change_kind, ident, slot, shape.variant_other,
        reason, owner_answer_id)
    await conn.execute(
        "update knowledge_facts set head_revision_id = $3, updated_at = now() "
        "where store_id = $1 and fact_id = $2 and head_revision_id is null",
        store_id, fact_id, revision_id)
    return fact_id, revision_id


def _occurrence_reason(row) -> str:
    """원장 행의 occurrence 사유. 이름 hint 는 DB 없이 이름 규칙으로만 다시 계산한다."""
    parts = normalize_subject(row["subject"] or "")
    _, reason = shape_from_ledger(row, parse_variant(row["variant"]),
                                  parts.temperature_hint, parts.size_hint)
    return reason


async def link_source_facts(conn: asyncpg.Connection, store_id: int, source_id: int,
                            source_fact_ids: list[int]) -> LinkOutcome:
    """원장 사실을 대상·판·occurrence 로 잇는다. 같은 자료를 다시 넣어도 늘지 않는다.

    호출자의 트랜잭션 안에서 돈다(_persist_ledger 의 checkpoint 트랜잭션과 같다).
    """
    if not source_fact_ids:
        return _EMPTY
    await lock_store_knowledge(conn, store_id)
    ids = sorted({int(i) for i in source_fact_ids})
    rows = await conn.fetch(
        "select fact_id, subject, variant, attribute, value, unit, polarity, conditions, "
        "exceptions, step_order, requires, local_ref, original_assertion "
        "from source_facts where store_id = $1 and source_id = $2 and fact_id = any($3::bigint[]) "
        "order by fact_id",
        store_id, source_id, ids)
    if not rows:
        return _EMPTY

    row_ids = [r["fact_id"] for r in rows]
    existing = await conn.fetch(
        "select source_fact_id, fact_revision_id from source_fact_revision_links "
        "where store_id = $1 and source_fact_id = any($2::bigint[])",
        store_id, row_ids)
    revision_of: dict[int, int] = {r["source_fact_id"]: r["fact_revision_id"] for r in existing}

    created = matched = conflicts = 0
    skipped: list[int] = []
    new_revisions: list[tuple[asyncpg.Record, int]] = []   # (원장 행, CREATED 판)
    for row in rows:
        sf_id = row["fact_id"]
        if sf_id in revision_of:
            continue   # 재투입 — 이미 이어진 사실
        try:
            entity = await resolve_entity(
                conn, store_id, row["subject"] or "", actor_id=None,
                origin_payload={"source_fact_id": sf_id, "source_id": source_id})
        except EntityUnresolvable:
            log.warning("대상 결정 불가 — 판을 만들지 않는다 store=%s source=%s source_fact=%s "
                        "subject=%r", store_id, source_id, sf_id, row["subject"])
            skipped.append(sf_id)
            continue
        shape, _ = shape_from_ledger(row, parse_variant(row["variant"]),
                                     entity.temperature_hint, entity.size_hint)
        slot = slot_key(entity.entity_id, shape)
        ident = identity_key(entity.entity_id, shape)
        same = await _find_same_fact(conn, store_id, ident)
        if same is not None:
            link_kind = "MATCHED"
            fact_id, revision_id = same["fact_id"], same["head_revision_id"]
            matched += 1
        else:
            link_kind = "CREATED"
            fact_id, revision_id = await _create_fact(
                conn, store_id, entity_id=entity.entity_id, shape=shape, slot=slot, ident=ident,
                change_kind="EXTRACTION",
                reason=_ORIGINAL_MISSING if original_missing(row) else None,
                owner_answer_id=None, actor_id=None)
            conflicts += await _record_conflicts(conn, store_id, fact_id)
            new_revisions.append((row, revision_id))
            created += 1
        await conn.execute(
            "insert into source_fact_revision_links "
            "(store_id, source_fact_id, fact_id, fact_revision_id, entity_id, link_kind) "
            "values ($1, $2, $3, $4, $5, $6) "
            "on conflict (store_id, source_fact_id) do nothing",
            store_id, sf_id, fact_id, revision_id, entity.entity_id, link_kind)
        revision_of[sf_id] = revision_id

    # 선행 관계 — CREATED 판만. 뒤쪽 행의 판까지 다 만든 뒤 한 번에 잇는다
    for row, revision_id in new_revisions:
        await _link_requires(conn, store_id, source_id, row, revision_id, rows, revision_of)

    occurrences = await _link_occurrences(conn, store_id, source_id, rows, revision_of)
    outcome = LinkOutcome(created=created, matched=matched, skipped=tuple(skipped),
                          occurrences=occurrences, conflicts=conflicts)
    log.info("W2 연결 store=%s source=%s 새 판 %d · 같은 사실 %d · 결정 불가 %d · "
             "occurrence %d · 충돌 %d", store_id, source_id, created, matched, len(skipped),
             occurrences, conflicts)
    return outcome


async def _link_requires(conn: asyncpg.Connection, store_id: int, source_id: int, row,
                         revision_id: int, batch: list, revision_of: dict[int, int]) -> None:
    """원장 requires(local_ref 목록) → 같은 자료 사실의 판으로 fact_revision_requires 를 잇는다.

    이번 호출의 행에서 먼저 찾고, 없으면 같은 자료에서 그 이름표가 한 행뿐일 때만 쓴다.
    자기 참조·없는 참조·판이 없는 참조(결정 불가)는 건너뛴다.
    """
    for ref in _json_list(row["requires"]):
        key = str(ref)[:_LOCAL_REF_MAX]
        target_ids = [r["fact_id"] for r in batch if r["local_ref"] == key]
        if not target_ids:
            target_ids = [r["fact_id"] for r in await conn.fetch(
                "select fact_id from source_facts "
                "where store_id = $1 and source_id = $2 and local_ref = $3",
                store_id, source_id, key)]
        if len(target_ids) != 1:
            continue
        target_revision = revision_of.get(target_ids[0])
        if target_revision is None:
            target_revision = await conn.fetchval(
                "select fact_revision_id from source_fact_revision_links "
                "where store_id = $1 and source_fact_id = $2",
                store_id, target_ids[0])
        if target_revision is None or target_revision == revision_id:
            continue
        await conn.execute(
            "insert into fact_revision_requires (store_id, fact_revision_id, requires_revision_id) "
            "values ($1, $2, $3) on conflict do nothing",
            store_id, revision_id, target_revision)


async def _link_occurrences(conn: asyncpg.Connection, store_id: int, source_id: int,
                            rows: list, revision_of: dict[int, int]) -> int:
    """원장 위치(source_fact_occurrences) 한 행마다 판 occurrence 한 행. 재처리해도 늘지 않는다."""
    linked = [r for r in rows if r["fact_id"] in revision_of]
    if not linked:
        return 0
    reasons = {r["fact_id"]: _occurrence_reason(r) for r in linked}
    content_hash = await conn.fetchval(
        "select content_hash from sources where store_id = $1 and source_id = $2",
        store_id, source_id)
    located = await conn.fetch(
        "select occurrence_id, fact_id, locator_type, locator "
        "from source_fact_occurrences "
        "where store_id = $1 and source_id = $2 and fact_id = any($3::bigint[]) "
        "order by occurrence_id",
        store_id, source_id, list(reasons))
    added = 0
    for occ in located:
        occurrence_id = await conn.fetchval(
            "insert into fact_occurrences (store_id, source_id, fact_revision_id, locator_type, "
            "locator, source_content_hash, disposition, reason, source_fact_occurrence_id) "
            "values ($1, $2, $3, $4, $5::jsonb, $6, 'REVIEW_PENDING', $7, $8) "
            "on conflict (store_id, source_fact_occurrence_id) "
            "where source_fact_occurrence_id is not null do nothing "
            "returning occurrence_id",
            store_id, source_id, revision_of[occ["fact_id"]], occ["locator_type"],
            occ["locator"] if isinstance(occ["locator"], str) else _json(occ["locator"]),
            content_hash, reasons[occ["fact_id"]], occ["occurrence_id"])
        if occurrence_id is not None:
            added += 1
    return added


async def record_owner_answer_fact(
        conn: asyncpg.Connection, store_id: int, *, owner_answer_id: int, subject: str,
        attribute: str, value: str, unit: str | None, variant: str | None, polarity: str,
        conditions: list[str], exceptions: list[str], step_order: int | None,
        original_assertion: str, actor_id: int | None) -> tuple[int, int]:
    """점주 답변에서 온 사실. (fact_id, fact_revision_id).

    파일 출처를 만들지 않는다 — sources·fact_occurrences 행이 없다(결정 F). 같은 사실이 이미 있으면
    새 판을 만들지 않고 그 사실의 head 를 돌려준다. 없으면 새 사실·판을 만들고 메타에
    change_kind=OWNER_ANSWER·owner_answer_id 를 남긴다. 두 경우 모두 fact_owner_answer_links 에
    점주 답변 출처를 한 행 남긴다(결정 H, 멱등). 다른 매장의 답변이면 ValueError.
    W2 에는 호출자가 없다(W3 가 잇는다).
    """
    await lock_store_knowledge(conn, store_id)
    # 매장 일치는 메타 트리거도 막지만, 같은 사실로 이어져 메타를 쓰지 않는 경우도 여기서 막는다
    answer_store = await conn.fetchval(
        "select pq.store_id from owner_answers oa "
        "join pending_questions pq on pq.question_id = oa.question_id "
        "where oa.answer_id = $1 and pq.store_id = $2",
        owner_answer_id, store_id)
    if answer_store is None:
        raise ValueError(f"이 매장의 점주 답변이 아니다 (store={store_id}, answer={owner_answer_id})")

    entity = await resolve_entity(conn, store_id, subject, actor_id=actor_id,
                                  origin_payload={"owner_answer_id": owner_answer_id})
    row = {"subject": subject, "attribute": attribute, "value": value, "unit": unit,
           "polarity": polarity, "step_order": step_order, "conditions": list(conditions),
           "exceptions": list(exceptions), "original_assertion": original_assertion}
    shape, _ = shape_from_ledger(row, parse_variant(variant),
                                 entity.temperature_hint, entity.size_hint)
    slot = slot_key(entity.entity_id, shape)
    ident = identity_key(entity.entity_id, shape)
    same = await _find_same_fact(conn, store_id, ident)
    if same is not None:
        fact_id, revision_id = same["fact_id"], same["head_revision_id"]
    else:
        fact_id, revision_id = await _create_fact(
            conn, store_id, entity_id=entity.entity_id, shape=shape, slot=slot, ident=ident,
            change_kind="OWNER_ANSWER",
            reason=_ORIGINAL_MISSING if original_missing(row) else None,
            owner_answer_id=owner_answer_id, actor_id=actor_id)
        await _record_conflicts(conn, store_id, fact_id)
    # 점주 답변 출처 (결정 H) — 새 사실이든 같은 사실이든 한 행. 다시 불러도 늘지 않는다
    await conn.execute(
        "insert into fact_owner_answer_links "
        "(store_id, fact_id, fact_revision_id, owner_answer_id) values ($1, $2, $3, $4) "
        "on conflict (store_id, fact_id, owner_answer_id) do nothing",
        store_id, fact_id, revision_id, owner_answer_id)
    return fact_id, revision_id


async def open_conflicts_for(conn: asyncpg.Connection, store_id: int,
                             fact_id: int) -> list[asyncpg.Record]:
    """이 사실이 낀 OPEN 충돌 쌍."""
    return await conn.fetch(
        "select conflict_id, entity_id, slot_key, fact_id_low, fact_id_high, value_kind, "
        "status, detected_at from fact_conflicts "
        "where store_id = $1 and status = 'OPEN' and $2 in (fact_id_low, fact_id_high) "
        "order by conflict_id",
        store_id, fact_id)


async def list_open_conflicts(conn: asyncpg.Connection, store_id: int, *,
                              entity_id: int | None) -> list[dict]:
    """검수용 — slot 마다 충돌하는 사실 목록과 각 사실의 근거.

    정렬은 최근 근거 시각 내림차순, 같으면 점주 출처 먼저, 그다음 fact_id 다.
    첫 항목에 뜻을 주는 칸(기본 선택·승자)을 싣지 않는다.
    """
    pairs = await conn.fetch(
        "select conflict_id, entity_id, slot_key, fact_id_low, fact_id_high, value_kind, "
        "detected_at from fact_conflicts "
        "where store_id = $1 and status = 'OPEN' and ($2::bigint is null or entity_id = $2) "
        "order by entity_id, slot_key, conflict_id",
        store_id, entity_id)
    if not pairs:
        return []
    fact_ids = sorted({p["fact_id_low"] for p in pairs} | {p["fact_id_high"] for p in pairs})
    heads = {r["fact_id"]: r for r in await conn.fetch(
        "select k.fact_id, k.entity_id, r.fact_revision_id, r.original_assertion, r.predicate, "
        "r.variant_temperature, r.variant_size, r.quantity_value, r.quantity_unit, r.value_text, "
        "r.polarity, r.step_order, r.conditions, r.exceptions, "
        "m.change_kind, m.owner_answer_id, m.created_at as revision_created_at "
        "from knowledge_facts k "
        "join fact_revisions r on r.store_id = k.store_id and r.fact_revision_id = k.head_revision_id "
        "left join fact_revision_meta m on m.store_id = k.store_id "
        "  and m.fact_revision_id = k.head_revision_id "
        "where k.store_id = $1 and k.fact_id = any($2::bigint[])",
        store_id, fact_ids)}
    evidence: dict[int, list[dict]] = {fid: [] for fid in fact_ids}
    for r in await conn.fetch(
            "select r.fact_id, o.occurrence_id, o.source_id, s.source_type, s.title, "
            "s.created_at as source_created_at, o.locator_type, o.locator, o.created_at "
            "from fact_occurrences o "
            "join fact_revisions r on r.store_id = o.store_id "
            "  and r.fact_revision_id = o.fact_revision_id "
            "join sources s on s.store_id = o.store_id and s.source_id = o.source_id "
            "where o.store_id = $1 and r.fact_id = any($2::bigint[]) "
            "order by o.occurrence_id",
            store_id, fact_ids):
        evidence[r["fact_id"]].append({
            "origin": "SOURCE", "source_id": r["source_id"], "source_type": r["source_type"],
            "source_title": r["title"], "source_created_at": r["source_created_at"],
            "locator_type": r["locator_type"],
            "locator": json.loads(r["locator"]) if isinstance(r["locator"], str) else r["locator"],
            "owner_answer_id": None, "created_at": r["created_at"]})
    # 점주 답변 출처는 fact_owner_answer_links 에 있다(결정 F·H)
    for r in await conn.fetch(
            "select l.fact_id, l.owner_answer_id, l.created_at "
            "from fact_owner_answer_links l "
            "where l.store_id = $1 and l.fact_id = any($2::bigint[]) order by l.link_id",
            store_id, fact_ids):
        evidence[r["fact_id"]].append({
            "origin": "OWNER_ANSWER", "source_id": None, "source_type": None,
            "source_title": None, "source_created_at": None, "locator_type": None,
            "locator": None, "owner_answer_id": r["owner_answer_id"],
            "created_at": r["created_at"]})

    def fact_item(fid: int) -> dict:
        head = heads[fid]
        items = evidence[fid]
        latest = max((e["created_at"] for e in items), default=head["revision_created_at"])
        return {
            "fact_id": fid, "fact_revision_id": head["fact_revision_id"],
            "original_assertion": head["original_assertion"], "predicate": head["predicate"],
            "variant_temperature": head["variant_temperature"],
            "variant_size": head["variant_size"],
            "quantity_value": head["quantity_value"], "quantity_unit": head["quantity_unit"],
            "value_text": head["value_text"], "polarity": head["polarity"],
            "step_order": head["step_order"],
            "conditions": _json_list(head["conditions"]),
            "exceptions": _json_list(head["exceptions"]),
            "latest_evidence_at": latest,
            "has_owner_origin": any(e["owner_answer_id"] is not None for e in items),
            "evidence": items,
        }

    groups: dict[tuple[int, str], dict] = {}
    for p in pairs:
        group = groups.setdefault((p["entity_id"], p["slot_key"]), {
            "entity_id": p["entity_id"], "slot_key": p["slot_key"],
            "conflict_ids": [], "value_kinds": [], "fact_ids": set()})
        group["conflict_ids"].append(p["conflict_id"])
        if p["value_kind"] not in group["value_kinds"]:
            group["value_kinds"].append(p["value_kind"])
        group["fact_ids"].update((p["fact_id_low"], p["fact_id_high"]))

    result = []
    for group in groups.values():
        facts = [fact_item(fid) for fid in group.pop("fact_ids") if fid in heads]
        facts.sort(key=lambda f: (-f["latest_evidence_at"].timestamp(),
                                  0 if f["has_owner_origin"] else 1, f["fact_id"]))
        group["facts"] = facts
        result.append(group)
    return result


async def card_entity_for(conn: asyncpg.Connection, store_id: int,
                          source_fact_ids: list[int]) -> int | None:
    """카드가 고른 원장 사실들이 이어진 대상이 정확히 하나면 그 id, 아니면 None.

    대상은 연결 당시 값(source_fact_revision_links.entity_id — 이력으로 남긴다)이 아니라 사실의 지금
    대상(knowledge_facts.entity_id)이다. 병합·분리·재연결(Task 5) 뒤 재처리에서 옛 대상을 싣지 않는다.
    """
    if not source_fact_ids:
        return None
    rows = await conn.fetch(
        "select distinct k.entity_id from source_fact_revision_links l "
        "join knowledge_facts k on k.store_id = l.store_id and k.fact_id = l.fact_id "
        "where l.store_id = $1 and l.source_fact_id = any($2::bigint[])",
        store_id, sorted({int(i) for i in source_fact_ids}))
    return rows[0]["entity_id"] if len(rows) == 1 else None
