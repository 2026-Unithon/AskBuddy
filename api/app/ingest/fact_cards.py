"""사실 카드 판 쓰기·블록/근거 고정·occurrence 처분 (W3a · W3-2 고정 · W3-3).

검증된 카드 계획(`card_plan.EntityPlanResult`)을 DB 에 쓴다. 카드 제목·본문은 직접 만들지 않고
`card_plan` 의 렌더링을 쓴다. 대상의 기존 카드 상태로 NEW / REASSEMBLE / DEFER 를 가른다.

- 공개된 카드·수동 배정·점주가 만든 초안·사실 블록이 없는 레거시 카드는 한 줄도 쓰지 않는다(DEFER).
- 카드 판·블록·블록 사실·판별 근거는 만든 뒤 고치지 않는다. 내용이 바뀌면 새 판을 만든다.
- occurrence 는 LINKED 로 올리거나 REVIEW_PENDING 사유만 바꾼다. EXCLUDED(점주 결정)는 건드리지
  않고, LINKED 를 REVIEW_PENDING 으로 내리지 않는다.

모든 DB 함수는 store_id 를 필수 인자로 받고 모든 SQL 이 store_id 로 좁힌다(D1).
호출자가 트랜잭션과 매장 지식 잠금(`entities.lock_store_knowledge`)을 쥔다.
"""
from __future__ import annotations

import json
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import asyncpg

from app.ingest import card_plan
from app.ingest import repository as repo
from app.ingest.card_plan import EntityGroup, EntityPlanResult, ValidatedCard
from app.ingest.fact_assembly import _value_of

logger = logging.getLogger(__name__)

# occurrence REVIEW_PENDING 사유 (common §4)
REASON_ENTITY_UNRESOLVABLE = "ENTITY_UNRESOLVABLE"
REASON_EXISTING_CARD = "EXISTING_CARD"
REASON_CONCURRENT = "CONCURRENT_ASSEMBLY"
REASON_STALE_INPUT = "STALE_INPUT"
REASON_ASSEMBLY_FAILED = "ASSEMBLY_FAILED"

# 카드 검수 표시 (knowledge_cards.needs_review_reason, varchar(50))
REVIEW_NO_PROVENANCE = "NO_PROVENANCE"
REVIEW_CONFLICT = "FACT_CONFLICT_OPEN"
REVIEW_SUPERSEDED = "REASSEMBLY_SUPERSEDED"
FALLBACK_PREFIX = "FALLBACK:"
_REVIEW_REASON_MAX = 50

MAX_PROVENANCE = 50  # FactRevision.provenance 계약 상한과 같다
_MAX_RELINK_DEPTH = 50  # 출처 사슬을 RELINK 로 거슬러 가는 최대 단수
_DEFAULT_CATEGORY = "기타"
_TITLE_MAX = 200  # card_versions.title varchar(200)

# card_evidence.locator_type 이 받는 값. occurrence 위치 종류 중 LINE·BBOX 는 없다
_EVIDENCE_LOCATOR_TYPES = {"TIMESTAMP", "PAGE", "FRAME", "TEXT_RANGE", "MESSAGE", "WHOLE_SOURCE"}
# 위치 dict 는 그대로 둔다 — MESSAGE 위치의 키는 카톡 메시지 번호 "line" 이다({"line": N})
_EVIDENCE_LOCATOR_ALIAS = {"LINE": "MESSAGE", "BBOX": "PAGE"}


@dataclass(frozen=True)
class EntityCardState:
    entity_id: int
    mode: str  # "NEW" | "REASSEMBLE" | "DEFER"
    card_ids: tuple[int, ...]  # REASSEMBLE: 다시 쓸 자동 초안(card_id 오름차순) · DEFER: 관련 카드 전부
    reason: str | None  # DEFER 일 때 REASON_EXISTING_CARD


@dataclass(frozen=True)
class Origin:
    occurrence_id: int | None
    owner_answer_id: int | None
    source_id: int | None
    locator_type: str | None
    locator: dict | None


@dataclass(frozen=True)
class WrittenEntity:
    entity_id: int
    card_ids: tuple[int, ...]  # 쓰거나 다시 쓴 카드(계획 카드 순)
    new_version_ids: tuple[int, ...]  # 이번에 만든 판(같은 내용이라 건너뛴 카드는 없음)
    linked_fact_ids: tuple[int, ...]
    # 쓰기 직전 잠금 아래 다시 본 상태가 달라 아무것도 쓰지 않았을 때의 사유(EXISTING_CARD)
    deferred_reason: str | None = None


@dataclass(frozen=True)
class DispositionCounts:
    total: int  # 이 자료의 source_fact_occurrences 행 수
    missing: int  # 그중 fact_occurrences 행이 없는 수
    linked: int
    review_pending: dict[str, int]  # 사유 → 건수
    excluded: dict[str, int]


# ── 순수 규칙 ──────────────────────────────────────────────────────────────

def card_review_reason(*, missing_provenance: bool, model_error: str | None,
                       open_conflict: bool) -> str | None:
    """카드 검수 표시 하나. 출처 없음 > 대체 계획 > 열린 충돌 순."""
    if missing_provenance:
        return REVIEW_NO_PROVENANCE
    if model_error:
        return (FALLBACK_PREFIX + model_error)[:_REVIEW_REASON_MAX]
    if open_conflict:
        return REVIEW_CONFLICT
    return None


def cap_origins(origins: Sequence[Origin], limit: int = MAX_PROVENANCE) -> tuple[Origin, ...]:
    """점주 답변 출처 전부(answer_id 순) 다음 occurrence 출처(occurrence_id 순)로 limit 개까지."""
    owners = sorted((o for o in origins if o.owner_answer_id is not None),
                    key=lambda o: o.owner_answer_id)
    occurrences = sorted((o for o in origins if o.owner_answer_id is None
                          and o.occurrence_id is not None),
                         key=lambda o: o.occurrence_id)
    return tuple([*owners, *occurrences][:limit])


def _status_count(status: str) -> int:
    """asyncpg execute 상태 문자열("UPDATE 3", "INSERT 0 2")의 행 수."""
    try:
        return int(status.split()[-1])
    except (ValueError, IndexError):
        return 0


def _locator(value) -> dict:
    """jsonb 위치. asyncpg 는 코덱이 없으면 문자열로 준다."""
    if value is None:
        return {}
    if isinstance(value, str):
        return json.loads(value)
    return dict(value)


def _pinning(card: ValidatedCard) -> tuple:
    return tuple((b.block_id, b.kind, b.order, tuple(b.fact_revision_ids)) for b in card.blocks)


def _evidence_locator(origin: Origin) -> tuple[str, dict]:
    """occurrence 위치 → card_evidence 위치. 받지 않는 종류는 같은 뜻의 종류로, 없으면 자료 전체."""
    kind = origin.locator_type or "WHOLE_SOURCE"
    kind = _EVIDENCE_LOCATOR_ALIAS.get(kind, kind)
    if kind not in _EVIDENCE_LOCATOR_TYPES:
        return "WHOLE_SOURCE", {}
    return kind, dict(origin.locator or {})


# ── 상태 판정 ──────────────────────────────────────────────────────────────

async def entity_card_state(conn: asyncpg.Connection, store_id: int,
                            entity_id: int) -> EntityCardState:
    """대상의 기존 카드로 NEW / REASSEMBLE / DEFER 를 가른다. 카드 행을 잠그지 않는다."""
    return await _card_state(conn, store_id, entity_id, lock=False)


async def _card_state(conn: asyncpg.Connection, store_id: int, entity_id: int, *,
                      lock: bool) -> EntityCardState:
    """lock 이면 관련 카드 행을 `for update` 로 잠근 채 판정한다(쓰기 트랜잭션 안에서만)."""
    rows = await conn.fetch(
        "with recursive merged(entity_id) as ("
        "  select $2::bigint"
        "  union"
        "  select e.entity_id from knowledge_entities e"
        "    join merged m on e.merged_into_entity_id = m.entity_id"
        "   where e.store_id = $1"
        ") "
        "select c.card_id, c.published_version_id, c.assignment_type, c.review_status, "
        "       v.change_source, "
        "       exists (select 1 from card_block_facts b "
        "                where b.store_id = c.store_id "
        "                  and b.card_version_id = c.draft_version_id) as has_block_facts, "
        "       coalesce(c.entity_id in (select entity_id from merged), false) as in_merged "
        "from knowledge_cards c "
        "left join card_versions v on v.store_id = c.store_id "
        "  and v.version_id = c.draft_version_id "
        "where c.store_id = $1 and c.review_status <> 'EXCLUDED' "
        "  and (c.entity_id in (select entity_id from merged) "
        "       or exists (select 1 from card_facts cf "
        "                  join source_fact_revision_links l on l.store_id = cf.store_id "
        "                    and l.source_fact_id = cf.fact_id "
        "                  join knowledge_facts k on k.store_id = l.store_id "
        "                    and k.fact_id = l.fact_id "
        "                  where cf.store_id = c.store_id and cf.card_id = c.card_id "
        "                    and k.entity_id = $2)) "
        "order by c.card_id" + (" for update of c" if lock else ""),
        store_id, entity_id)
    if not rows:
        return EntityCardState(entity_id, "NEW", (), None)
    card_ids = tuple(int(r["card_id"]) for r in rows)
    replaceable = all(
        r["published_version_id"] is None
        and r["assignment_type"] == "AUTOMATIC"
        and r["review_status"] in ("PENDING", "NEEDS_REVIEW")
        and r["change_source"] == "EXTRACTION"
        and r["has_block_facts"]
        and r["in_merged"]
        for r in rows)
    if replaceable:
        return EntityCardState(entity_id, "REASSEMBLE", card_ids, None)
    return EntityCardState(entity_id, "DEFER", card_ids, REASON_EXISTING_CARD)


async def entity_fact_ids(conn: asyncpg.Connection, store_id: int, entity_id: int) -> list[int]:
    rows = await conn.fetch(
        "select fact_id from knowledge_facts where store_id = $1 and entity_id = $2 "
        "order by fact_id", store_id, entity_id)
    return [int(r["fact_id"]) for r in rows]


# ── 출처 ───────────────────────────────────────────────────────────────────

async def provenance_for(conn: asyncpg.Connection, store_id: int,
                         fact_revision_ids: Sequence[int]) -> dict[int, tuple[Origin, ...]]:
    """판마다 출처. RELINK 판은 병합·분리 전 판의 출처를 이어받는다(최대 50단)."""
    ids = sorted({int(r) for r in fact_revision_ids})
    if not ids:
        return {}
    chains: dict[int, list[int]] = {r: [r] for r in ids}
    frontier: dict[int, int] = {r: r for r in ids}  # 시작 판 → 사슬의 지금 끝
    for _ in range(_MAX_RELINK_DEPTH):
        if not frontier:
            break
        rows = await conn.fetch(
            "select r.fact_revision_id, r.supersedes_revision_id from fact_revisions r "
            "join fact_revision_meta m on m.store_id = r.store_id "
            "  and m.fact_revision_id = r.fact_revision_id "
            "where r.store_id = $1 and r.fact_revision_id = any($2::bigint[]) "
            "  and m.change_kind = 'RELINK' and r.supersedes_revision_id is not null",
            store_id, sorted(set(frontier.values())))
        previous = {int(r["fact_revision_id"]): int(r["supersedes_revision_id"]) for r in rows}
        advanced: dict[int, int] = {}
        for root, tail in frontier.items():
            prev = previous.get(tail)
            if prev is not None and prev not in chains[root]:
                chains[root].append(prev)
                advanced[root] = prev
        frontier = advanced

    every = sorted({r for chain in chains.values() for r in chain})
    by_revision: dict[int, list[Origin]] = {}
    for r in await conn.fetch(
            "select occurrence_id, fact_revision_id, source_id, locator_type, locator "
            "from fact_occurrences where store_id = $1 and fact_revision_id = any($2::bigint[]) "
            "and disposition <> 'EXCLUDED'", store_id, every):
        by_revision.setdefault(int(r["fact_revision_id"]), []).append(Origin(
            occurrence_id=int(r["occurrence_id"]), owner_answer_id=None,
            source_id=int(r["source_id"]), locator_type=r["locator_type"],
            locator=_locator(r["locator"])))
    for r in await conn.fetch(
            "select fact_revision_id, owner_answer_id from fact_owner_answer_links "
            "where store_id = $1 and fact_revision_id = any($2::bigint[])", store_id, every):
        by_revision.setdefault(int(r["fact_revision_id"]), []).append(Origin(
            occurrence_id=None, owner_answer_id=int(r["owner_answer_id"]),
            source_id=None, locator_type=None, locator=None))

    result: dict[int, tuple[Origin, ...]] = {}
    for root, chain in chains.items():
        seen: dict[tuple, Origin] = {}
        for rev in chain:
            for o in by_revision.get(rev, ()):
                seen.setdefault((o.occurrence_id, o.owner_answer_id), o)
        capped = cap_origins(list(seen.values()))
        if len(capped) < len(seen):
            logger.warning("W3a 근거 상한 — store=%s 판 %s 출처 %d 중 %d 만 고정한다",
                           store_id, root, len(seen), len(capped))
        result[root] = capped
    return result


# ── 카드 판 쓰기 ───────────────────────────────────────────────────────────

async def create_extraction_draft(conn: asyncpg.Connection, store_id: int, card_id: int, *,
                                  title: str, content: str, confidence: float,
                                  entity_id: int) -> int:
    """새 EXTRACTION 초안 판을 만들고 카드의 초안 포인터·제목·본문을 한 문장으로 옮긴다."""
    title = title[:_TITLE_MAX]
    version_id = await conn.fetchval(
        "insert into card_versions "
        "(store_id, card_id, version_no, title, content, change_source, created_by) "
        "select $1, $2, coalesce(max(version_no), 0) + 1, $3, $4, 'EXTRACTION', null "
        "from card_versions where store_id = $1 and card_id = $2 "
        "returning version_id",
        store_id, card_id, title, content)
    # 같은 문장에서 draft_version_id 를 바꾸므로 레거시 쓰기 트리거가 판을 따로 만들지 않는다
    await conn.execute(
        "update knowledge_cards set title = $3, content = $4, draft_version_id = $5, "
        "confidence = $6, entity_id = $7 where store_id = $1 and card_id = $2",
        store_id, card_id, title, content, version_id, confidence, entity_id)
    return int(version_id)


async def _pinned(conn: asyncpg.Connection, store_id: int, card_version_id: int) -> tuple:
    """판에 고정된 블록(블록 id·종류·순서·블록 사실 순서). 없으면 빈 튜플."""
    blocks = await conn.fetch(
        "select block_id, kind, block_order from card_version_blocks "
        "where store_id = $1 and card_version_id = $2 order by block_order",
        store_id, card_version_id)
    if not blocks:
        return ()
    facts: dict[str, list[int]] = {}
    for r in await conn.fetch(
            "select block_id, fact_revision_id from card_block_facts "
            "where store_id = $1 and card_version_id = $2 order by block_id, position",
            store_id, card_version_id):
        facts.setdefault(r["block_id"], []).append(int(r["fact_revision_id"]))
    return tuple((b["block_id"], b["kind"], b["block_order"], tuple(facts.get(b["block_id"], ())))
                 for b in blocks)


async def pin_card_version(conn: asyncpg.Connection, store_id: int, card_version_id: int,
                           card: ValidatedCard, provenance: Mapping[int, Sequence[Origin]]) -> None:
    """판에 블록·블록 사실·판별 근거를 고정한다. 이미 고정됐으면 같아야 한다(불변)."""
    existing = await _pinned(conn, store_id, card_version_id)
    if existing:
        if existing != _pinning(card):
            raise RuntimeError(
                f"카드 판 {card_version_id} 의 블록 고정이 이미 다르게 있다 — 판은 불변이다")
        return
    await conn.executemany(
        "insert into card_version_blocks "
        "(store_id, card_version_id, block_id, kind, block_order, raw_span_id) "
        "values ($1, $2, $3, $4, $5, null)",
        [(store_id, card_version_id, b.block_id, b.kind, b.order) for b in card.blocks])
    await conn.executemany(
        "insert into card_block_facts "
        "(store_id, card_version_id, block_id, fact_revision_id, position) "
        "values ($1, $2, $3, $4, $5)",
        [(store_id, card_version_id, b.block_id, rid, pos)
         for b in card.blocks for pos, rid in enumerate(b.fact_revision_ids, start=1)])
    rows = [(store_id, card_version_id, rid, o.occurrence_id, o.owner_answer_id)
            for rid in card.fact_revision_ids() for o in provenance.get(rid, ())]
    if rows:
        await conn.executemany(
            "insert into card_version_fact_provenance "
            "(store_id, card_version_id, fact_revision_id, occurrence_id, owner_answer_id) "
            "values ($1, $2, $3, $4, $5)", rows)


async def _source_fact_ids(conn: asyncpg.Connection, store_id: int,
                           fact_ids: Sequence[int]) -> list[int]:
    rows = await conn.fetch(
        "select source_fact_id from source_fact_revision_links "
        "where store_id = $1 and fact_id = any($2::bigint[]) order by source_fact_id",
        store_id, sorted(set(fact_ids)))
    return [int(r["source_fact_id"]) for r in rows]


async def write_entity_cards(conn: asyncpg.Connection, store_id: int, *, source_id: int,
                             job_id: int | None, category_version: int,
                             categories: Mapping[str, int], state: EntityCardState,
                             group: EntityGroup, result: EntityPlanResult) -> WrittenEntity:
    """대상 하나의 계획 카드를 쓴다. 호출자가 트랜잭션·매장 지식 잠금을 쥔다."""
    # DB 를 치기 전에 전제를 확인한다
    if not result.cards:
        raise ValueError("쓸 카드가 없다 — 카드 없는 계획은 검수 대기로 처리한다")
    if state.mode not in ("NEW", "REASSEMBLE"):
        raise ValueError(f"NEW·REASSEMBLE 만 쓴다: mode={state.mode}")
    if not (state.entity_id == group.entity_id == result.entity_id):
        raise ValueError(
            f"대상이 어긋난다: state={state.entity_id} group={group.entity_id} "
            f"result={result.entity_id}")

    facts = {f.fact_revision_id: f for f in group.facts}
    placed_revisions = sorted({r for c in result.cards for r in c.fact_revision_ids()})
    missing_facts = [r for r in placed_revisions if r not in facts]
    if missing_facts:
        raise ValueError(f"묶음에 없는 판이 계획에 있다: {missing_facts[:5]}")
    placed_fact_ids = sorted({facts[r].fact_id for r in placed_revisions})

    # 점주 승인·편집·이동은 매장 지식 잠금이 아니라 카드 행 잠금만 쓴다. 판정 뒤 점주가 커밋했을
    # 수 있으므로 관련 카드 행을 잠그고 다시 판정한다. 달라졌으면 한 줄도 쓰지 않는다(D13)
    locked = await _card_state(conn, store_id, group.entity_id, lock=True)
    if locked.mode != state.mode or locked.card_ids != state.card_ids:
        logger.warning("W3a 카드 쓰기 보류 — store=%s 대상 %s 판정 %s%s → 잠금 뒤 %s%s",
                       store_id, group.entity_id, state.mode, state.card_ids,
                       locked.mode, locked.card_ids)
        await mark_pending(conn, store_id, source_id=source_id,
                           fact_ids=[f.fact_id for f in group.facts],
                           reason=REASON_EXISTING_CARD)
        return WrittenEntity(entity_id=group.entity_id, card_ids=(), new_version_ids=(),
                             linked_fact_ids=(), deferred_reason=REASON_EXISTING_CARD)

    provenance = await provenance_for(conn, store_id, placed_revisions)

    # 출처 자료 제목
    source_ids = sorted({o.source_id for origins in provenance.values() for o in origins
                         if o.source_id is not None})
    source_names: dict[int, str] = {}
    if source_ids:
        for r in await conn.fetch(
                "select source_id, title, source_type from sources "
                "where store_id = $1 and source_id = any($2::bigint[])", store_id, source_ids):
            title = (r["title"] or "").strip()
            source_names[int(r["source_id"])] = title or f"{r['source_type']} 자료"

    # 열린 충돌에 낀 사실
    conflicted: set[int] = set()
    for r in await conn.fetch(
            "select fact_id_low, fact_id_high from fact_conflicts "
            "where store_id = $1 and status = 'OPEN' "
            "and (fact_id_low = any($2::bigint[]) or fact_id_high = any($2::bigint[]))",
            store_id, placed_fact_ids):
        conflicted.update((int(r["fact_id_low"]), int(r["fact_id_high"])))
    conflicted &= set(placed_fact_ids)

    # 사실 신뢰도(0~100) — 이어진 원장 사실 중 가장 높은 값
    fact_confidence: dict[int, float] = {
        int(r["fact_id"]): float(r["confidence"] or 0) for r in await conn.fetch(
            "select l.fact_id, max(sf.confidence) as confidence "
            "from source_fact_revision_links l "
            "join source_facts sf on sf.store_id = l.store_id and sf.fact_id = l.source_fact_id "
            "where l.store_id = $1 and l.fact_id = any($2::bigint[]) group by l.fact_id",
            store_id, placed_fact_ids)}

    # 카드 짝 — 남는 기존 카드는 검수 표시만 바꾸고 판은 그대로 둔다
    existing = list(state.card_ids) if state.mode == "REASSEMBLE" else []
    for leftover in existing[len(result.cards):]:
        await conn.execute(
            "update knowledge_cards set review_status = 'NEEDS_REVIEW', "
            "needs_review_reason = $3 where store_id = $1 and card_id = $2 "
            "and review_status in ('PENDING','NEEDS_REVIEW')",
            store_id, leftover, REVIEW_SUPERSEDED)

    card_ids: list[int] = []
    new_versions: list[int] = []
    placement: dict[int, tuple[int, str]] = {}  # fact_id → (card_id, block_id) 첫 자리
    for index, card in enumerate(result.cards):
        revisions = card.fact_revision_ids()
        card_fact_ids = sorted({facts[r].fact_id for r in revisions})
        origins = [o for r in revisions for o in provenance.get(r, ())]
        card_sources = sorted({o.source_id for o in origins if o.source_id is not None})
        content = card_plan.render_card(
            card, facts, evidence=[source_names[s] for s in card_sources if s in source_names])
        missing = card_plan.render_missing(card, facts, content)
        if missing:
            raise RuntimeError(f"렌더링이 사실을 빠뜨렸다 — 저장하지 않는다: 판 {missing[:5]}")
        reason = card_review_reason(
            missing_provenance=any(not provenance.get(r) for r in revisions),
            model_error=result.model_error,
            open_conflict=any(f in conflicted for f in card_fact_ids))
        category_id = categories.get(card.category_name) or categories.get(_DEFAULT_CATEGORY)
        if category_id is None:
            raise RuntimeError("시스템 카테고리 '기타'가 없습니다.")
        confidence = min((fact_confidence.get(f, 0.0) for f in card_fact_ids), default=0.0)

        if index < len(existing):
            card_id = existing[index]
            current = await conn.fetchrow(
                "select c.draft_version_id, v.title, v.content from knowledge_cards c "
                "join card_versions v on v.store_id = c.store_id "
                "  and v.version_id = c.draft_version_id "
                "where c.store_id = $1 and c.card_id = $2", store_id, card_id)
            same = (current is not None and current["title"] == card.title[:_TITLE_MAX]
                    and current["content"] == content
                    and await _pinned(conn, store_id, current["draft_version_id"])
                    == _pinning(card))
            if same:
                version_id, is_new = int(current["draft_version_id"]), False
            else:
                version_id = await create_extraction_draft(
                    conn, store_id, card_id, title=card.title, content=content,
                    confidence=confidence, entity_id=card.entity_id)
                is_new = True
        else:
            card_id = await repo.insert_card(
                conn, store_id, category_id=category_id, source_id=source_id,
                title=card.title, content=content, confidence=confidence,
                origin_job_id=job_id, category_version=category_version,
                entity_id=card.entity_id)
            version_id = await conn.fetchval(
                "select draft_version_id from knowledge_cards where store_id = $1 and card_id = $2",
                store_id, card_id)
            if version_id is None:
                raise RuntimeError(f"card {card_id}의 최초 버전이 생성되지 않았습니다.")
            version_id, is_new = int(version_id), True

        if is_new:
            new_versions.append(version_id)
            await pin_card_version(conn, store_id, version_id, card, provenance)
            # 출처 자료마다 근거 위치 하나 — 그 자료의 가장 앞 occurrence
            first: dict[int, Origin] = {}
            for o in sorted((o for o in origins if o.occurrence_id is not None),
                            key=lambda o: o.occurrence_id):
                first.setdefault(o.source_id, o)
            for sid in sorted(first):
                locator_type, locator = _evidence_locator(first[sid])
                await conn.execute(
                    "insert into card_evidence (store_id, version_id, source_id, locator_type, "
                    "locator) values ($1, $2, $3, $4, $5::jsonb)",
                    store_id, version_id, sid, locator_type,
                    json.dumps(locator, ensure_ascii=False))
            # 레거시 facts 교체 — 코드 이전이 끝나면 끊는다
            await conn.execute(
                "delete from facts f using knowledge_cards k "
                "where f.card_id = k.card_id and k.store_id = $1 and k.card_id = $2",
                store_id, card_id)
            seen_facts: set[int] = set()
            legacy: list[tuple[str, str, str, float]] = []
            for r in revisions:
                f = facts[r]
                if f.fact_id in seen_facts:
                    continue
                seen_facts.add(f.fact_id)
                legacy.append(((f.subject or group.canonical_name)[:100],
                               (f.predicate or "")[:100], _value_of(f)[:500],
                               fact_confidence.get(f.fact_id, 0.0)))
            await repo.insert_facts(conn, card_id, legacy)
            await repo.link_card_facts(conn, store_id, card_id,
                                       await _source_fact_ids(conn, store_id, card_fact_ids))

        await conn.execute(
            "update knowledge_cards set review_status = $3, needs_review_reason = $4 "
            "where store_id = $1 and card_id = $2 and review_status in ('PENDING','NEEDS_REVIEW')",
            store_id, card_id, "NEEDS_REVIEW" if reason else "PENDING", reason)

        card_ids.append(card_id)
        for b in card.blocks:
            for r in b.fact_revision_ids:
                placement.setdefault(facts[r].fact_id, (card_id, b.block_id))

    # 처분 — 배치된 사실의 모든 자료·모든 판 occurrence 를 첫 자리로 잇는다. EXCLUDED 는 그대로
    order = sorted(placement)
    await conn.execute(
        "update fact_occurrences o set disposition = 'LINKED', reason = null, "
        "card_id = p.card_id, block_id = p.block_id, decided_by = null, decided_at = now() "
        "from fact_revisions r, "
        "     unnest($2::bigint[], $3::bigint[], $4::varchar[]) as p(fact_id, card_id, block_id) "
        "where o.store_id = $1 and r.store_id = o.store_id "
        "  and r.fact_revision_id = o.fact_revision_id "
        "  and r.fact_id = p.fact_id and o.disposition <> 'EXCLUDED'",
        store_id, order, [placement[f][0] for f in order], [placement[f][1] for f in order])
    await repo.set_assembly_state(conn, store_id,
                                  await _source_fact_ids(conn, store_id, placed_fact_ids),
                                  "LINKED")
    logger.info("W3a 카드 쓰기 store=%s 대상 %s mode=%s 카드 %d · 새 판 %d · 사실 %d",
                store_id, group.entity_id, state.mode, len(card_ids), len(new_versions),
                len(placed_fact_ids))
    return WrittenEntity(entity_id=group.entity_id, card_ids=tuple(card_ids),
                         new_version_ids=tuple(new_versions),
                         linked_fact_ids=tuple(placed_fact_ids))


# ── occurrence 처분 ────────────────────────────────────────────────────────

async def mark_pending(conn: asyncpg.Connection, store_id: int, *, source_id: int,
                       fact_ids: Sequence[int], reason: str) -> int:
    """이 자료의 REVIEW_PENDING occurrence 사유를 바꾼다. LINKED·EXCLUDED 는 그대로. 바뀐 행 수."""
    status = await conn.execute(
        "update fact_occurrences o set reason = $4, decided_at = now() "
        "from fact_revisions r "
        "where o.store_id = $1 and o.source_id = $2 and r.store_id = o.store_id "
        "  and r.fact_revision_id = o.fact_revision_id and r.fact_id = any($3::bigint[]) "
        "  and o.disposition = 'REVIEW_PENDING'",
        store_id, source_id, sorted({int(f) for f in fact_ids}), reason)
    return _status_count(status)


async def record_unresolvable_occurrences(conn: asyncpg.Connection, store_id: int,
                                          source_id: int) -> int:
    """대상을 정하지 못해 판이 없는 원장 사실의 위치마다 검수 대기 occurrence. 넣은 행 수."""
    status = await conn.execute(
        "insert into fact_occurrences (store_id, source_id, fact_revision_id, locator_type, "
        "locator, source_content_hash, disposition, reason, source_fact_occurrence_id) "
        "select o.store_id, o.source_id, null, o.locator_type, o.locator, s.content_hash, "
        "       'REVIEW_PENDING', $3, o.occurrence_id "
        "from source_fact_occurrences o "
        "join sources s on s.store_id = o.store_id and s.source_id = o.source_id "
        "where o.store_id = $1 and o.source_id = $2 "
        "  and not exists (select 1 from source_fact_revision_links l "
        "                  where l.store_id = o.store_id and l.source_fact_id = o.fact_id) "
        "on conflict (store_id, source_fact_occurrence_id) "
        "where source_fact_occurrence_id is not null do nothing",
        store_id, source_id, REASON_ENTITY_UNRESOLVABLE)
    return _status_count(status)


async def disposition_counts(conn: asyncpg.Connection, store_id: int,
                             source_id: int) -> DispositionCounts:
    """이 자료의 원장 위치 수·처분 누락 수·처분별 건수."""
    row = await conn.fetchrow(
        "select count(*) as total, count(*) filter (where f.occurrence_id is null) as missing "
        "from source_fact_occurrences o "
        "left join fact_occurrences f on f.store_id = o.store_id "
        "  and f.source_fact_occurrence_id = o.occurrence_id "
        "where o.store_id = $1 and o.source_id = $2",
        store_id, source_id)
    linked = 0
    pending: dict[str, int] = {}
    excluded: dict[str, int] = {}
    for r in await conn.fetch(
            "select disposition, reason, count(*) as n from fact_occurrences "
            "where store_id = $1 and source_id = $2 group by disposition, reason",
            store_id, source_id):
        n = int(r["n"])
        if r["disposition"] == "LINKED":
            linked += n
        elif r["disposition"] == "REVIEW_PENDING":
            pending[r["reason"]] = pending.get(r["reason"], 0) + n
        else:
            excluded[r["reason"]] = excluded.get(r["reason"], 0) + n
    return DispositionCounts(total=int(row["total"]), missing=int(row["missing"]), linked=linked,
                             review_pending=pending, excluded=excluded)
