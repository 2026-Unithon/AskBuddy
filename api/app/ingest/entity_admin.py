"""W2-4 ③ 대상 병합·분리·사실 재연결 — 이력과 함께. DB 함수.

규칙 (task-5, w2-common A-3·A-4·A-5, 컨트롤러 결정 G·I):
  - 판(fact_revisions)의 entity_id 는 불변이다. 재연결은 head 값을 그대로 복사하고 entity_id 만 바꾼
    새 판(change_kind RELINK)을 잇는다(Task 3 _append_revision). 옛 판·메타·occurrence 는 그대로다
  - 옛 슬롯의 OPEN 충돌은 OBSOLETE, 새 슬롯의 충돌은 Task 2 _record_conflicts 로 다시 계산한다
    (둘 다 _append_revision 안에서 한다. 기각 쌍은 값이 그대로면 다시 열지 않는다 — 결정 I)
  - 모든 변경은 knowledge_entity_events 에 남긴다(append-only). 같은 대상으로의 재연결 같은
    no-op 은 이력을 더럽히므로 ValueError 로 막는다
  - 카드·카드 버전·공개 snapshot·업로드 제안은 쓰지 않는다(결정 G). 카드의 entity_id 도 그대로다 —
    카드 재배치는 W3 검수에서 한다. 병합된 대상을 가리키는 옛 행은 merged_into_entity_id 로 따라간다
  - 모든 조회·쓰기는 store_id 로 좁힌다(D1). 매장 교차는 복합 FK 가 한 번 더 막는다
동시성: 매장 잠금(lock_store_knowledge) → 대상·사실 행 for update → 쓰기. 한 호출이 한 트랜잭션이다.
"""
from __future__ import annotations

import json
import logging
from typing import Literal

import asyncpg

from app.ingest.entities import (AliasTaken, EntityUnresolvable, _follow_merged,
                                 find_entity_by_alias, lock_store_knowledge)
from app.ingest.entity_names import normalize_subject
from app.ingest.fact_revisions import FactChange, _append_revision, _apply_change, _head_of, \
    _lock_fact

log = logging.getLogger(__name__)

__all__ = ["relink_fact", "split_entity", "merge_entities", "decide_candidate"]

_DECISIONS = ("CONFIRMED_DIFFERENT", "DISMISSED")


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def _required_reason(reason: str | None) -> str:
    text = (reason or "").strip()
    if not text:
        raise ValueError("재연결 사유는 비울 수 없다")
    return text


async def _event(conn: asyncpg.Connection, store_id: int, action: str, *, entity_id: int,
                 other_entity_id: int | None = None, fact_id: int | None = None,
                 fact_revision_id: int | None = None, actor_id: int | None,
                 payload: dict) -> None:
    await conn.execute(
        "insert into knowledge_entity_events (store_id, action, entity_id, other_entity_id, "
        "fact_id, fact_revision_id, actor_id, payload) "
        "values ($1, $2, $3, $4, $5, $6, $7, $8::jsonb)",
        store_id, action, entity_id, other_entity_id, fact_id, fact_revision_id, actor_id,
        _json(payload))


async def _entity_status(conn: asyncpg.Connection, store_id: int, entity_id: int) -> str:
    """대상 상태. 이 매장에 없으면(다른 매장 id 포함) LookupError. 행을 잠근다."""
    status = await conn.fetchval(
        "select status from knowledge_entities where store_id = $1 and entity_id = $2 "
        "for update",
        store_id, entity_id)
    if status is None:
        raise LookupError(f"대상이 없다 (store={store_id}, entity={entity_id})")
    return status


async def _relink_locked(conn: asyncpg.Connection, store_id: int, *, fact_row,
                         to_entity_id: int, actor_id: int | None, reason: str) -> int:
    """잠근 사실 행을 to_entity_id 로 옮기는 RELINK 판을 잇고 이력을 남긴다. 새 fact_revision_id.

    호출 전 조건: 매장 잠금·_lock_fact 완료, to_entity_id 는 이 매장의 ACTIVE 대상이고 지금 대상과 다르다.
    """
    head, variant_other = await _head_of(conn, store_id, fact_row["head_revision_id"])
    # 값·원문·문장·주어·속성·규격은 head 그대로. 바뀌는 것은 entity_id(와 그에 딸린 열쇠)뿐이다
    shape = _apply_change(head, variant_other, FactChange(
        original_assertion=head["original_assertion"], assertion=head["assertion"]))
    new_id = await _append_revision(
        conn, store_id, knowledge_fact_row=fact_row, shape=shape, entity_id=to_entity_id,
        change_kind="RELINK", actor_id=actor_id, reason=reason)
    await _event(conn, store_id, "RELINK_FACT", entity_id=fact_row["entity_id"],
                 other_entity_id=to_entity_id, fact_id=fact_row["fact_id"],
                 fact_revision_id=new_id, actor_id=actor_id,
                 payload={"reason": reason, "from_revision_id": fact_row["head_revision_id"]})
    return new_id


async def relink_fact(conn: asyncpg.Connection, store_id: int, *, fact_id: int,
                      expected_head_revision_id: int, to_entity_id: int, actor_id: int,
                      reason: str) -> int:
    """사실 하나를 다른 대상으로 옮긴다. 새 판 id.

    사유가 비었으면 DB 호출 전에 ValueError. 사실이 없으면 LookupError, head 가 기대와 다르면
    StaleFactRevision, 지금 대상과 같거나 옮길 대상이 MERGED 면 ValueError, 옮길 대상이 이 매장에
    없으면 LookupError — 모두 아무것도 쓰기 전에 막는다.
    """
    reason = _required_reason(reason)
    async with conn.transaction():
        await lock_store_knowledge(conn, store_id)
        row = await _lock_fact(conn, store_id, fact_id, expected_head_revision_id)
        if row["entity_id"] == to_entity_id:
            raise ValueError(f"이미 그 대상의 사실이다 (fact={fact_id}, entity={to_entity_id})")
        status = await _entity_status(conn, store_id, to_entity_id)
        if status != "ACTIVE":
            raise ValueError(f"병합된 대상으로는 옮기지 않는다 (entity={to_entity_id})")
        return await _relink_locked(conn, store_id, fact_row=row, to_entity_id=to_entity_id,
                                    actor_id=actor_id, reason=reason)


async def _retire_alias(conn: asyncpg.Connection, store_id: int, *, alias, from_entity_id: int,
                        to_entity_id: int, actor_id: int | None) -> None:
    """활성 별칭을 retire 하고 옮길 대상에 OWNER 별칭으로 다시 만든다. 두 쪽 모두 이력을 남긴다."""
    await conn.execute(
        "update knowledge_entity_aliases set retired_at = now() "
        "where store_id = $1 and alias_id = $2 and entity_id = $3 and retired_at is null",
        store_id, alias["alias_id"], from_entity_id)
    await _event(conn, store_id, "ALIAS_RETIRE", entity_id=from_entity_id,
                 other_entity_id=to_entity_id, actor_id=actor_id,
                 payload={"alias_id": alias["alias_id"], "alias_norm": alias["alias_norm"],
                          "moved_to_entity_id": to_entity_id})
    # 방금 retire 했으므로 매장 안 활성 별칭 유일성과 부딪히지 않는다
    new_alias = await conn.fetchval(
        "insert into knowledge_entity_aliases "
        "(store_id, entity_id, alias_norm, alias_raw, origin, created_by) "
        "values ($1, $2, $3, $4, $5, $6) returning alias_id",
        store_id, to_entity_id, alias["alias_norm"], alias["alias_raw"], "OWNER", actor_id)
    await _event(conn, store_id, "ALIAS_ADD", entity_id=to_entity_id,
                 other_entity_id=from_entity_id, actor_id=actor_id,
                 payload={"alias_id": new_alias, "alias_norm": alias["alias_norm"],
                          "alias_raw": alias["alias_raw"], "moved_from_alias_id": alias["alias_id"]})


async def split_entity(conn: asyncpg.Connection, store_id: int, *, entity_id: int,
                       fact_ids: list[int], new_canonical_name: str,
                       move_alias_norms: list[str], actor_id: int) -> int:
    """잘못 합친 대상에서 사실 일부를 새 대상으로 떼어 낸다. 새 entity_id.

    fact_ids 는 모두 지금 그 대상의 사실이어야 하고, move_alias_norms 는 모두 그 대상의 활성 별칭
    (정규화 값)이어야 한다. 하나라도 어긋나면 아무것도 쓰지 않고 ValueError(부분 실행 없음).
    새 이름의 정규화가 다른 활성 별칭이면 AliasTaken — 단 이번에 옮기는 원 대상 별칭이면 허용한다.
    두 대상은 후보 쌍 SPLIT·CONFIRMED_DIFFERENT 로 남아 다시 후보로 뜨지 않는다.
    """
    ids = sorted({int(f) for f in fact_ids})
    if not ids:
        raise ValueError("떼어 낼 사실이 없다")
    parts = normalize_subject(new_canonical_name or "")
    if not parts.name_norm:
        raise EntityUnresolvable(f"새 대상 이름을 정규화할 수 없다: {new_canonical_name!r}")
    moves = sorted({(a or "").strip() for a in move_alias_norms})
    if any(not a for a in moves):
        raise ValueError("옮길 별칭에 빈 값이 있다")

    async with conn.transaction():
        await lock_store_knowledge(conn, store_id)
        if await _entity_status(conn, store_id, entity_id) != "ACTIVE":
            raise ValueError(f"병합된 대상은 분리하지 않는다 (entity={entity_id})")
        owned = {r["fact_id"] for r in await conn.fetch(
            "select fact_id from knowledge_facts where store_id = $1 and entity_id = $2 "
            "and fact_id = any($3::bigint[])",
            store_id, entity_id, ids)}
        if owned != set(ids):
            raise ValueError(f"그 대상의 사실이 아니다 (entity={entity_id}, "
                             f"fact={sorted(set(ids) - owned)})")
        aliases = []
        if moves:
            aliases = list(await conn.fetch(
                "select alias_id, alias_norm, alias_raw from knowledge_entity_aliases "
                "where store_id = $1 and entity_id = $2 and alias_norm = any($3::text[]) "
                "and retired_at is null order by alias_id",
                store_id, entity_id, moves))
            if {a["alias_norm"] for a in aliases} != set(moves):
                raise ValueError(f"그 대상의 활성 별칭이 아니다 (entity={entity_id}, "
                                 f"alias={sorted(set(moves) - {a['alias_norm'] for a in aliases})})")
        owner = await find_entity_by_alias(conn, store_id, parts.name_norm)
        if owner is not None and not (owner == entity_id and parts.name_norm in moves):
            raise AliasTaken(f"이름 {parts.name_norm!r} 은 이미 다른 별칭이다")

        new_entity = await conn.fetchval(
            "insert into knowledge_entities (store_id, canonical_name, name_norm, created_by) "
            "values ($1, $2, $3, $4) returning entity_id",
            store_id, parts.display_name, parts.name_norm, actor_id)
        await _event(conn, store_id, "CREATE", entity_id=new_entity, other_entity_id=entity_id,
                     actor_id=actor_id, payload={"split_from_entity_id": entity_id,
                                                 "canonical_name": parts.display_name})
        if parts.name_norm not in moves:
            await conn.fetchval(
                "insert into knowledge_entity_aliases "
                "(store_id, entity_id, alias_norm, alias_raw, origin, created_by) "
                "values ($1, $2, $3, $4, $5, $6) returning alias_id",
                store_id, new_entity, parts.name_norm, new_canonical_name, "SYSTEM", actor_id)
        for alias in aliases:
            await _retire_alias(conn, store_id, alias=alias, from_entity_id=entity_id,
                                to_entity_id=new_entity, actor_id=actor_id)
        for fid in ids:
            row = await _lock_fact(conn, store_id, fid, None)
            await _relink_locked(conn, store_id, fact_row=row, to_entity_id=new_entity,
                                 actor_id=actor_id, reason=f"대상 분리 {entity_id} → {new_entity}")
        low, high = sorted((entity_id, new_entity))
        await conn.execute(
            "insert into knowledge_entity_candidates "
            "(store_id, entity_id_low, entity_id_high, reason, evidence, status, decided_by, "
            "decided_at) values ($1, $2, $3, 'SPLIT', $4::jsonb, 'CONFIRMED_DIFFERENT', $5, now()) "
            "on conflict (store_id, entity_id_low, entity_id_high) do update "
            "set reason = 'SPLIT', status = 'CONFIRMED_DIFFERENT', "
            "decided_by = excluded.decided_by, decided_at = excluded.decided_at",
            store_id, low, high, _json({"split_from_entity_id": entity_id}), actor_id)
        await _event(conn, store_id, "SPLIT", entity_id=entity_id, other_entity_id=new_entity,
                     actor_id=actor_id,
                     payload={"fact_ids": ids, "moved_aliases": [a["alias_norm"] for a in aliases],
                              "new_canonical_name": parts.display_name})
    log.info("W2 대상 분리 store=%s entity=%s → %s 사실 %d 별칭 %d", store_id, entity_id,
             new_entity, len(ids), len(aliases))
    return new_entity


def _as_object(value) -> dict:
    """jsonb 객체(문자열로 올 수 있다)를 dict 로."""
    if value is None:
        return {}
    if isinstance(value, str):
        return json.loads(value) if value.strip() else {}
    return dict(value)


async def _rehome_candidates(conn: asyncpg.Connection, store_id: int, *, keep_entity_id: int,
                             merged_entity_id: int, actor_id: int) -> None:
    """병합된 대상이 낀 (병합된 대상, 제3 대상) PENDING 후보를 정리한다 (W3-0 §3-3-1).

    keep 과 제3 대상 사이에 후보가 없으면 같은 이유·근거로 keep 쪽 PENDING 후보를 새로 만들고,
    이미 있으면(상태 무관 — 결정된 쌍은 다시 열지 않는다) 만들지 않는다. 어느 쪽이든 옛 후보는
    MERGED 로 닫고 이력 CANDIDATE_MOVED 를 남긴다. 제3 대상은 병합 사슬 끝으로 따라가고, 그것이
    keep 이면 새 후보 없이 닫기만 한다(이력 other_entity_id 는 원래 제3 대상).
    호출 전 조건: 같은 트랜잭션에서 매장 잠금을 잡았고 merged 는 이미 MERGED 다.
    """
    rows = await conn.fetch(
        "select candidate_id, entity_id_low, entity_id_high, reason, evidence "
        "from knowledge_entity_candidates "
        "where store_id = $1 and status = 'PENDING' and $2 in (entity_id_low, entity_id_high) "
        "and $3 not in (entity_id_low, entity_id_high) "
        "order by candidate_id for update",
        store_id, merged_entity_id, keep_entity_id)
    for row in rows:
        raw_third = (row["entity_id_high"] if row["entity_id_low"] == merged_entity_id
                     else row["entity_id_low"])
        # 제3 대상도 이미 병합됐을 수 있다 — 살아 있는 대상으로 따라간다
        third = await _follow_merged(conn, store_id, raw_third)
        new_id = None
        if third != keep_entity_id:
            low, high = sorted((keep_entity_id, third))
            evidence = _as_object(row["evidence"]) | {
                "moved_from_candidate_id": row["candidate_id"],
                "merged_entity_id": merged_entity_id}
            new_id = await conn.fetchval(
                "insert into knowledge_entity_candidates "
                "(store_id, entity_id_low, entity_id_high, reason, evidence) "
                "values ($1, $2, $3, $4, $5::jsonb) "
                "on conflict (store_id, entity_id_low, entity_id_high) do nothing "
                "returning candidate_id",
                store_id, low, high, row["reason"], _json(evidence))
        else:
            # 제3 대상이 이미 keep 으로 합쳐졌다 — (keep, keep) 쌍은 만들지 않고 닫기만 한다
            third = raw_third
        await conn.execute(
            "update knowledge_entity_candidates set status = 'MERGED', decided_by = $3, "
            "decided_at = now(), evidence = evidence || $4::jsonb "
            "where store_id = $1 and candidate_id = $2 and status = 'PENDING'",
            store_id, row["candidate_id"], actor_id,
            _json({"merged_into_entity_id": keep_entity_id, "replaced_by_candidate_id": new_id}))
        await _event(conn, store_id, "CANDIDATE_MOVED", entity_id=keep_entity_id,
                     other_entity_id=third, actor_id=actor_id,
                     payload={"from_candidate_id": row["candidate_id"], "to_candidate_id": new_id,
                              "merged_entity_id": merged_entity_id,
                              "outcome": "MOVED" if new_id is not None else "CLOSED"})


async def merge_entities(conn: asyncpg.Connection, store_id: int, *, keep_entity_id: int,
                         merged_entity_id: int, actor_id: int, candidate_id: int | None) -> int:
    """merged 대상을 keep 에 합친다(점주 확정). 옮긴 사실 수.

    merged 의 사실은 모두 RELINK 판으로 keep 에 옮기고, 활성 별칭은 retire 후 keep 의 OWNER 별칭으로
    다시 만든다. merged 는 MERGED·merged_into_entity_id=keep 이 된다. 같은 값이 된 두 사실은 둘 다
    남고 충돌이 아니다(A-4). 두 대상 쌍의 PENDING 후보는 CONFIRMED_SAME 으로 닫는다.
    candidate_id 를 주면 그 후보가 이 쌍의 PENDING 후보여야 한다(아니면 ValueError, 쓰기 없음).
    병합된 대상이 낀 다른 PENDING 후보는 keep 쪽으로 옮기거나(같은 쌍이 이미 있으면) MERGED 로 닫는다(W3-0).
    """
    if keep_entity_id == merged_entity_id:
        raise ValueError("자기 자신과는 병합하지 않는다")
    low, high = sorted((keep_entity_id, merged_entity_id))
    async with conn.transaction():
        await lock_store_knowledge(conn, store_id)
        rows = await conn.fetch(
            "select entity_id, status "
            "from knowledge_entities where store_id = $1 and entity_id = any($2::bigint[]) "
            "order by entity_id for update",
            store_id, [low, high])
        if len(rows) != 2:
            raise LookupError(f"대상이 없다 (store={store_id}, entity={low},{high})")
        if any(r["status"] != "ACTIVE" for r in rows):
            raise ValueError(f"ACTIVE 대상끼리만 병합한다 (entity={low},{high})")
        if candidate_id is not None:
            candidate = await conn.fetchrow(
                "select entity_id_low, entity_id_high, status "
                "from knowledge_entity_candidates where store_id = $1 and candidate_id = $2 "
                "for update",
                store_id, candidate_id)
            if candidate is None:
                raise LookupError(f"후보가 없다 (store={store_id}, candidate={candidate_id})")
            if (candidate["entity_id_low"], candidate["entity_id_high"]) != (low, high):
                raise ValueError(f"이 두 대상의 후보가 아니다 (candidate={candidate_id})")
            if candidate["status"] != "PENDING":
                raise ValueError(f"이미 결정한 후보다 (candidate={candidate_id}, "
                                 f"상태 {candidate['status']})")

        facts = [r["fact_id"] for r in await conn.fetch(
            "select fact_id from knowledge_facts where store_id = $1 and entity_id = $2 "
            "order by fact_id",
            store_id, merged_entity_id)]
        for fid in facts:
            row = await _lock_fact(conn, store_id, fid, None)
            await _relink_locked(conn, store_id, fact_row=row, to_entity_id=keep_entity_id,
                                 actor_id=actor_id,
                                 reason=f"대상 병합 {merged_entity_id} → {keep_entity_id}")
        aliases = list(await conn.fetch(
            "select alias_id, alias_norm, alias_raw from knowledge_entity_aliases "
            "where store_id = $1 and entity_id = $2 and retired_at is null order by alias_id",
            store_id, merged_entity_id))
        for alias in aliases:
            await _retire_alias(conn, store_id, alias=alias, from_entity_id=merged_entity_id,
                                to_entity_id=keep_entity_id, actor_id=actor_id)
        await conn.execute(
            "update knowledge_entities set status = 'MERGED', merged_into_entity_id = $3, "
            "updated_at = now() where store_id = $1 and entity_id = $2 and status = 'ACTIVE'",
            store_id, merged_entity_id, keep_entity_id)
        await conn.execute(
            "update knowledge_entity_candidates set status = 'CONFIRMED_SAME', decided_by = $4, "
            "decided_at = now() "
            "where store_id = $1 and entity_id_low = $2 and entity_id_high = $3 "
            "and status = 'PENDING'",
            store_id, low, high, actor_id)
        await _event(conn, store_id, "MERGE", entity_id=keep_entity_id,
                     other_entity_id=merged_entity_id, actor_id=actor_id,
                     payload={"fact_ids": facts, "moved_aliases": [a["alias_norm"] for a in aliases],
                              "candidate_id": candidate_id})
        # W3-0 §3-3-1 — 병합된 대상이 낀 다른 PENDING 후보를 keep 쪽으로 옮기거나 닫는다
        await _rehome_candidates(conn, store_id, keep_entity_id=keep_entity_id,
                                 merged_entity_id=merged_entity_id, actor_id=actor_id)
    log.info("W2 대상 병합 store=%s %s → %s 사실 %d 별칭 %d", store_id, merged_entity_id,
             keep_entity_id, len(facts), len(aliases))
    return len(facts)


async def decide_candidate(conn: asyncpg.Connection, store_id: int, candidate_id: int, *,
                           decision: Literal["CONFIRMED_DIFFERENT", "DISMISSED"],
                           actor_id: int) -> None:
    """같은 대상 후보를 '다른 대상'·'기각' 으로 닫는다. 같은 대상 확정은 merge_entities 가 한다.

    PENDING 만 닫는다. 없으면(다른 매장 id 포함) LookupError, 이미 결정했으면 ValueError.
    """
    if decision not in _DECISIONS:
        raise ValueError(f"decision 은 {_DECISIONS} 중 하나다: {decision!r}")
    async with conn.transaction():
        await lock_store_knowledge(conn, store_id)
        pair = await conn.fetchrow(
            "update knowledge_entity_candidates set status = $3, decided_by = $4, "
            "decided_at = now() "
            "where store_id = $1 and candidate_id = $2 and status = 'PENDING' "
            "returning entity_id_low, entity_id_high",
            store_id, candidate_id, decision, actor_id)
        if pair is None:
            status = await conn.fetchval(
                "select status from knowledge_entity_candidates "
                "where store_id = $1 and candidate_id = $2",
                store_id, candidate_id)
            if status is None:
                raise LookupError(f"후보가 없다 (store={store_id}, candidate={candidate_id})")
            raise ValueError(f"PENDING 후보만 결정한다 (candidate={candidate_id}, 상태 {status})")
        await _event(conn, store_id, "CANDIDATE_DECIDED", entity_id=pair["entity_id_low"],
                     other_entity_id=pair["entity_id_high"], actor_id=actor_id,
                     payload={"candidate_id": candidate_id, "decision": decision})
