"""W2-1 대상(entity) 조회·생성·별칭·후보·이력 — DB 함수.

규칙 (w2-common A-1·A-4, task-1):
  - 자동 병합은 정규화 이름이 정확히 같거나 같은 매장의 활성 별칭이 같을 때만이다
  - 비슷한 이름은 knowledge_entity_candidates 에 PENDING 후보로만 남긴다. 합치지 않는다
  - 모든 조회·쓰기는 store_id 로 좁힌다(D1). 매장 교차는 복합 FK 가 한 번 더 막는다
  - 대상 이름·별칭에 규격 낱말을 넣지 않는다. 떼어낸 hint 는 호출자가 규격으로 쓴다
  - 기존 카드(knowledge_cards)는 건드리지 않는다
동시성: 연결 단계를 시작할 때 호출자가 lock_store_knowledge 로 매장 잠금을 한 번 잡는다.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass

import asyncpg

from app.ingest.entity_names import candidate_reason, normalize_alias, normalize_subject

log = logging.getLogger(__name__)

# 병합 사슬을 따라가는 최대 단계. 넘으면 데이터가 꼬인 것이다(순환 포함)
_MAX_MERGE_HOPS = 5


class EntityUnresolvable(ValueError):
    """이름을 정규화하면 빈 문자열이라 대상을 정할 수 없다."""


class AliasTaken(ValueError):
    """같은 매장에서 그 별칭이 이미 다른 대상에 걸려 있다."""


class EntityMergeChainError(RuntimeError):
    """병합 사슬이 너무 길거나 순환한다."""


@dataclass(frozen=True)
class EntityResolution:
    entity_id: int
    name_norm: str
    created: bool
    temperature_hint: str | None
    size_hint: str | None
    candidate_ids: tuple[int, ...]   # 이번에 후보로 제안한 상대 대상 id (새 대상일 때만)


def _json(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False)


async def lock_store_knowledge(conn: asyncpg.Connection, store_id: int) -> None:
    """매장 지식 연결 잠금 (A-4). 트랜잭션 끝에 풀린다. 같은 트랜잭션에서 다시 잡아도 무해하다."""
    await conn.execute(
        "select pg_advisory_xact_lock(hashtextextended('askbuddy:w2:' || $1::bigint::text, 0))",
        store_id)


async def find_entity_by_alias(conn: asyncpg.Connection, store_id: int,
                               alias_norm: str) -> int | None:
    """활성 별칭이 가리키는 대상 id. 병합 사슬은 따라가지 않는다(resolve_entity 가 따라간다)."""
    return await conn.fetchval(
        "select entity_id from knowledge_entity_aliases "
        "where store_id = $1 and alias_norm = $2 and retired_at is null",
        store_id, alias_norm)


async def _follow_merged(conn: asyncpg.Connection, store_id: int, entity_id: int) -> int:
    """MERGED 대상이면 살아남은 대상까지 따라간다."""
    current = entity_id
    for _ in range(_MAX_MERGE_HOPS + 1):
        row = await conn.fetchrow(
            "select status, merged_into_entity_id from knowledge_entities "
            "where store_id = $1 and entity_id = $2", store_id, current)
        if row is None:
            raise EntityMergeChainError(f"대상이 없다 (store={store_id}, entity={current})")
        if row["status"] != "MERGED":
            return current
        current = row["merged_into_entity_id"]
    raise EntityMergeChainError(
        f"병합 사슬이 {_MAX_MERGE_HOPS}단을 넘는다 (store={store_id}, entity={entity_id})")


async def _propose_candidates(conn: asyncpg.Connection, store_id: int, entity_id: int,
                              name_norm: str, limit: int) -> tuple[int, ...]:
    """새 대상과 비슷한 이름의 다른 대상을 후보로만 남긴다. 합치지 않는다."""
    rows = await conn.fetch(
        "select a.entity_id, a.alias_id, a.alias_norm "
        "from knowledge_entity_aliases a "
        "join knowledge_entities e on e.store_id = a.store_id and e.entity_id = a.entity_id "
        "where a.store_id = $1 and a.retired_at is null and a.entity_id <> $2 "
        "and e.status = 'ACTIVE'",
        store_id, entity_id)
    best: dict[int, tuple[tuple, dict]] = {}
    for row in rows:
        reason = candidate_reason(name_norm, row["alias_norm"])
        if reason is None:
            continue
        # 우선순위: EDIT1 > CONTAINS, 그다음 길이 차 작은 순, 그다음 entity_id 순
        rank = (0 if reason == "EDIT1" else 1, abs(len(name_norm) - len(row["alias_norm"])),
                row["entity_id"])
        evidence = {"reason": reason, "new_norm": name_norm,
                    "existing_norm": row["alias_norm"], "existing_alias_id": row["alias_id"]}
        if row["entity_id"] not in best or rank < best[row["entity_id"]][0]:
            best[row["entity_id"]] = (rank, evidence)
    chosen = sorted(best.items(), key=lambda item: item[1][0])[:limit]
    for other_id, (_, evidence) in chosen:
        low, high = sorted((entity_id, other_id))
        # 이미 결정이 난 쌍(CONFIRMED_DIFFERENT·DISMISSED)은 unique 로 다시 생기지 않는다
        await conn.execute(
            "insert into knowledge_entity_candidates "
            "(store_id, entity_id_low, entity_id_high, reason, evidence) "
            "values ($1, $2, $3, $4, $5::jsonb) "
            "on conflict (store_id, entity_id_low, entity_id_high) do nothing",
            store_id, low, high, evidence["reason"], _json(evidence))
    return tuple(other_id for other_id, _ in chosen)


async def resolve_entity(conn: asyncpg.Connection, store_id: int, raw_subject: str, *,
                         actor_id: int | None, origin_payload: dict) -> EntityResolution:
    """사실의 subject 로 대상을 찾거나 만든다. 호출자가 lock_store_knowledge 를 먼저 잡는다."""
    from app.config import get_settings

    parts = normalize_subject(raw_subject)
    if not parts.name_norm:
        raise EntityUnresolvable(f"대상 이름을 정규화할 수 없다: {raw_subject!r}")

    def result(entity_id: int, created: bool, candidates: tuple[int, ...] = ()) -> EntityResolution:
        return EntityResolution(entity_id=entity_id, name_norm=parts.name_norm, created=created,
                                temperature_hint=parts.temperature_hint,
                                size_hint=parts.size_hint, candidate_ids=candidates)

    found = await find_entity_by_alias(conn, store_id, parts.name_norm)
    if found is not None:
        return result(await _follow_merged(conn, store_id, found), False)

    entity_id = await conn.fetchval(
        "insert into knowledge_entities (store_id, canonical_name, name_norm, created_by) "
        "values ($1, $2, $3, $4) returning entity_id",
        store_id, parts.display_name, parts.name_norm, actor_id)
    alias_id = await conn.fetchval(
        "insert into knowledge_entity_aliases "
        "(store_id, entity_id, alias_norm, alias_raw, origin, created_by) "
        "values ($1, $2, $3, $4, 'SYSTEM', $5) "
        "on conflict (store_id, alias_norm) where retired_at is null do nothing "
        "returning alias_id",
        store_id, entity_id, parts.name_norm, raw_subject, actor_id)
    if alias_id is None:
        # 잠금 밖에서 다른 트랜잭션이 먼저 만들었다. 방금 만든 빈 대상을 지우고 그쪽을 쓴다
        await conn.execute(
            "delete from knowledge_entities where store_id = $1 and entity_id = $2",
            store_id, entity_id)
        found = await find_entity_by_alias(conn, store_id, parts.name_norm)
        if found is None:
            raise EntityMergeChainError(f"별칭 충돌 뒤 대상을 찾지 못했다: {parts.name_norm!r}")
        return result(await _follow_merged(conn, store_id, found), False)

    await conn.execute(
        "insert into knowledge_entity_events (store_id, action, entity_id, actor_id, payload) "
        "values ($1, 'CREATE', $2, $3, $4::jsonb)",
        store_id, entity_id, actor_id, _json(origin_payload))

    limit = getattr(get_settings(), "w_entity_candidate_max", 0)
    candidates = ()
    if limit > 0:
        candidates = await _propose_candidates(conn, store_id, entity_id, parts.name_norm, limit)
    return result(entity_id, True, candidates)


async def add_owner_alias(conn: asyncpg.Connection, store_id: int, entity_id: int,
                          alias_raw: str, *, actor_id: int) -> int:
    """점주가 대상에 별칭을 단다. 이미 그 대상의 별칭이면 그 alias_id 를 돌려준다."""
    alias_norm = normalize_alias(alias_raw)
    if not alias_norm:
        raise EntityUnresolvable(f"별칭을 정규화할 수 없다: {alias_raw!r}")
    status = await conn.fetchval(
        "select status from knowledge_entities where store_id = $1 and entity_id = $2",
        store_id, entity_id)
    if status != "ACTIVE":
        raise ValueError(f"활성 대상이 아니다 (store={store_id}, entity={entity_id}, status={status})")

    existing = await conn.fetchrow(
        "select alias_id, entity_id from knowledge_entity_aliases "
        "where store_id = $1 and alias_norm = $2 and retired_at is null",
        store_id, alias_norm)
    if existing is not None:
        if existing["entity_id"] != entity_id:
            raise AliasTaken(f"별칭 {alias_norm!r} 은 이미 다른 대상의 것이다")
        return existing["alias_id"]

    alias_id = await conn.fetchval(
        "insert into knowledge_entity_aliases "
        "(store_id, entity_id, alias_norm, alias_raw, origin, created_by) "
        "values ($1, $2, $3, $4, 'OWNER', $5) "
        "on conflict (store_id, alias_norm) where retired_at is null do nothing "
        "returning alias_id",
        store_id, entity_id, alias_norm, alias_raw, actor_id)
    if alias_id is None:
        raise AliasTaken(f"별칭 {alias_norm!r} 이 방금 다른 곳에서 등록됐다")
    await conn.execute(
        "insert into knowledge_entity_events (store_id, action, entity_id, actor_id, payload) "
        "values ($1, 'ALIAS_ADD', $2, $3, $4::jsonb)",
        store_id, entity_id, actor_id,
        _json({"alias_id": alias_id, "alias_norm": alias_norm, "alias_raw": alias_raw}))
    return alias_id


async def list_candidates(conn: asyncpg.Connection, store_id: int, *,
                          status: str = "PENDING") -> list[asyncpg.Record]:
    """같은 대상 후보 목록. 두 대상의 이름을 함께 돌려준다."""
    return await conn.fetch(
        "select c.candidate_id, c.entity_id_low, c.entity_id_high, c.reason, c.evidence, "
        "c.status, c.decided_by, c.decided_at, c.created_at, "
        "lo.canonical_name as low_name, hi.canonical_name as high_name "
        "from knowledge_entity_candidates c "
        "join knowledge_entities lo on lo.store_id = c.store_id and lo.entity_id = c.entity_id_low "
        "join knowledge_entities hi on hi.store_id = c.store_id and hi.entity_id = c.entity_id_high "
        "where c.store_id = $1 and c.status = $2 "
        "order by c.created_at desc, c.candidate_id desc",
        store_id, status)
