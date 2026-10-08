"""대상 단위 사실 조립 입력·모델 호출 (W3a · W3-1 · W3-1b).

자료 단위가 아니라 **대상 단위**로 head 사실 판을 읽어 `card_plan.EntityGroup` 을 만들고,
묶음을 배치로 나눠 조립 모델을 동시에 부른 뒤 이름표를 판 id 로 되돌린다.
카드·occurrence 를 쓰지 않는다(저장은 뒤 단계). 모델 호출 중에는 DB 연결을 쥐지 않는다 —
`plan_entities` 는 연결을 받지 않는다.

모델 입력에는 이름표(E1…·F1…)만 싣는다. DB id 를 프롬프트에 넣지 않는다.
"""
from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from app.ingest import batching
from app.ingest.card_plan import (EntityGroup, PlanFact, ProposedBlock, ProposedCard,
                                  fact_sort_key, variant_label)
from app.ingest.entities import _follow_merged
from app.ingest.schemas import CardPlanBatch

logger = logging.getLogger(__name__)

# 프롬프트 마지막 절 머리. 이 줄 다음부터 끝까지가 입력 JSON 이다(합성 대역이 이것으로 읽는다)
PLAN_INPUT_MARKER = "## 대상별 사실 묶음"
REASON_VARIANT_UNRESOLVED = "VARIANT_UNRESOLVED"
REASON_ENTITY_MISMATCH = "ENTITY_MISMATCH"


@dataclass(frozen=True)
class HeldFact:
    """조립에서 뺀 head 판과 그 사유."""
    fact_revision_id: int
    fact_id: int
    entity_id: int
    reason: str


@dataclass(frozen=True)
class AssemblyInput:
    groups: tuple[EntityGroup, ...]  # 사실 1개 이상인 대상만, entity_id 오름차순
    held: tuple[HeldFact, ...]  # 조립에서 뺀 head 판


@dataclass(frozen=True)
class PlanBatch:
    index: int
    groups: tuple[EntityGroup, ...]
    payload: list[dict]  # 모델 입력 (이름표만)
    entity_handles: dict[str, int]  # "E1" → entity_id
    fact_handles: dict[str, int]  # "F1" → fact_revision_id


@dataclass(frozen=True)
class PlanningOutcome:
    proposals: dict[int, tuple[ProposedCard, ...]]  # 대상별 모델 제안(성공한 배치만)
    failed_entity_ids: tuple[int, ...]  # 호출·파싱이 실패한 배치의 대상(오름차순)
    unresolved: tuple[str, ...]
    batch_count: int
    errors: tuple[str, ...]  # f"plan{i}: {type(exc).__name__}: {exc}"


# ── DB 읽기 (짧은 연결) ──────────────────────────────────────────────────────

async def entities_for_source(conn, store_id: int, source_id: int) -> list[int]:
    """이 자료의 원장 사실이 이어진 대상들. 병합된 대상은 살아 있는 대상으로 바꾼다."""
    rows = await conn.fetch(
        "select distinct k.entity_id from source_fact_revision_links l "
        "join source_facts sf on sf.store_id = l.store_id and sf.fact_id = l.source_fact_id "
        "join knowledge_facts k on k.store_id = l.store_id and k.fact_id = l.fact_id "
        "where l.store_id = $1 and sf.source_id = $2 order by k.entity_id",
        store_id, source_id)
    live = {await _follow_merged(conn, store_id, r["entity_id"]) for r in rows}
    return sorted(live)


def _json_list(value) -> tuple[str, ...]:
    """jsonb 배열 → 문자열 튜플. asyncpg 는 코덱이 없으면 문자열로 준다."""
    if value is None:
        return ()
    if isinstance(value, str):
        value = json.loads(value)
    return tuple(str(v) for v in value)


async def load_entity_groups(conn, store_id: int, entity_ids: Sequence[int]) -> AssemblyInput:
    """대상들의 head 판을 읽어 조립 묶음으로 만든다. 규격을 못 푼 판·대상이 어긋난 판은 뺀다."""
    ids = sorted({int(e) for e in entity_ids})
    if not ids:
        return AssemblyInput(groups=(), held=())

    heads = await conn.fetch(
        "select k.fact_id, k.entity_id as fact_entity_id, r.fact_revision_id, "
        "r.entity_id as revision_entity_id, r.subject, r.predicate, "
        "r.variant_temperature, r.variant_size, r.quantity_value, r.quantity_unit, "
        "r.value_text, r.polarity, r.step_order, r.conditions, r.exceptions, "
        "r.original_assertion, r.assertion, m.variant_other "
        "from knowledge_facts k "
        "join fact_revisions r on r.store_id = k.store_id "
        "  and r.fact_revision_id = k.head_revision_id "
        "left join fact_revision_meta m on m.store_id = r.store_id "
        "  and m.fact_revision_id = r.fact_revision_id "
        "where k.store_id = $1 and k.entity_id = any($2::bigint[]) "
        "order by k.entity_id, r.fact_revision_id",
        store_id, ids)

    # 선행 — 판을 가리키지만 병합·분리 뒤에도 옛 판을 그대로 가리키므로 fact_id 로 푼다
    requires: dict[int, set[int]] = {}
    if heads:
        own_fact = {r["fact_revision_id"]: r["fact_id"] for r in heads}
        for q in await conn.fetch(
                "select q.fact_revision_id, t.fact_id from fact_revision_requires q "
                "join fact_revisions t on t.store_id = q.store_id "
                "  and t.fact_revision_id = q.requires_revision_id "
                "where q.store_id = $1 and q.fact_revision_id = any($2::bigint[])",
                store_id, list(own_fact)):
            if q["fact_id"] != own_fact[q["fact_revision_id"]]:
                requires.setdefault(q["fact_revision_id"], set()).add(q["fact_id"])

    names = {r["entity_id"]: r["canonical_name"] for r in await conn.fetch(
        "select entity_id, canonical_name from knowledge_entities "
        "where store_id = $1 and entity_id = any($2::bigint[])", store_id, ids)}

    held: list[HeldFact] = []
    by_entity: dict[int, list[PlanFact]] = {}
    for r in heads:
        rid, fid, eid = r["fact_revision_id"], r["fact_id"], r["fact_entity_id"]
        if r["variant_other"]:
            held.append(HeldFact(rid, fid, eid, REASON_VARIANT_UNRESOLVED))
            continue
        if r["revision_entity_id"] != eid:
            held.append(HeldFact(rid, fid, eid, REASON_ENTITY_MISMATCH))
            continue
        by_entity.setdefault(eid, []).append(PlanFact(
            fact_revision_id=rid, fact_id=fid, entity_id=eid,
            subject=r["subject"], predicate=r["predicate"],
            variant_temperature=r["variant_temperature"], variant_size=r["variant_size"],
            quantity_value=r["quantity_value"], quantity_unit=r["quantity_unit"],
            value_text=r["value_text"], polarity=r["polarity"], step_order=r["step_order"],
            conditions=_json_list(r["conditions"]), exceptions=_json_list(r["exceptions"]),
            original_assertion=r["original_assertion"], assertion=r["assertion"],
            requires_fact_ids=tuple(sorted(requires.get(rid, ()))),
        ))

    groups = tuple(
        EntityGroup(entity_id=eid, canonical_name=names.get(eid) or "",
                    facts=tuple(sorted(by_entity[eid], key=fact_sort_key)))
        for eid in sorted(by_entity))
    return AssemblyInput(groups=groups, held=tuple(held))


# ── 배치·이름표 ────────────────────────────────────────────────────────────

def _value_of(f: PlanFact) -> str:
    if f.quantity_value is not None:
        return f"{format(f.quantity_value.normalize(), 'f')} {f.quantity_unit or ''}".strip()
    return f.value_text or ""


def _batch(index: int, groups: list[EntityGroup]) -> PlanBatch:
    """배치 하나의 이름표·페이로드. 이름표는 배치마다 E1·F1 부터 다시 매긴다."""
    entity_handles: dict[str, int] = {}
    fact_handles: dict[str, int] = {}
    payload: list[dict] = []
    n = 0
    for e, group in enumerate(groups, start=1):
        entity_handles[f"E{e}"] = group.entity_id
        # 이름표를 먼저 다 매긴다 — 선행이 뒤에 오는 사실을 가리킬 수 있다
        handle_of: dict[int, str] = {}  # 이 묶음 안 fact_id → 이름표
        local: list[tuple[str, PlanFact]] = []
        for f in group.facts:
            n += 1
            handle = f"F{n}"
            fact_handles[handle] = f.fact_revision_id
            handle_of.setdefault(f.fact_id, handle)
            local.append((handle, f))
        payload.append({
            "대상": f"E{e}",
            "이름": group.canonical_name,
            "사실": [{
                "id": handle,
                "규격": "" if f.variant == (None, None) else variant_label(f.variant),
                "속성": f.predicate or "",
                "값": _value_of(f),
                "부정": f.polarity == "NEGATE",
                "조건": list(f.conditions),
                "예외": list(f.exceptions),
                "순서": f.step_order or 0,
                # 묶음 밖 선행은 뺀다 — 그런 묶음은 저장 전에 check_group 이 거른다
                "선행": [handle_of[r] for r in f.requires_fact_ids if r in handle_of],
                "원문": f.original_assertion,
            } for handle, f in local],
        })
    return PlanBatch(index=index, groups=tuple(groups), payload=payload,
                     entity_handles=entity_handles, fact_handles=fact_handles)


def build_plan_batches(groups: Sequence[EntityGroup], *, limit: int) -> list[PlanBatch]:
    """입력 순서대로 대상을 쌓다가 사실 수가 한도를 넘으면 끊는다. 대상 하나는 나누지 않는다."""
    batches: list[list[EntityGroup]] = []
    current: list[EntityGroup] = []
    count = 0
    for group in groups:
        if current and count + len(group.facts) > limit:
            batches.append(current)
            current, count = [], 0
        current.append(group)
        count += len(group.facts)
    if current:
        batches.append(current)
    return [_batch(i, b) for i, b in enumerate(batches)]


def proposals_from_output(batch: PlanBatch, out: CardPlanBatch
                          ) -> tuple[dict[int, tuple[ProposedCard, ...]], list[str]]:
    """모델 출력의 이름표를 판 id 로 되돌린다. 모르는 사실 이름표는 문자열 그대로 둔다
    (서버 검증이 PLAN_UNKNOWN_REF 로 거른다). 배치의 모든 대상이 키로 들어간다(제안 없으면 빈 튜플)."""
    by_entity: dict[int, list[ProposedCard]] = {g.entity_id: [] for g in batch.groups}
    notes: list[str] = []
    for card in out.cards:
        entity_id = batch.entity_handles.get(card.entity)
        if entity_id is None:
            notes.append(f"알 수 없는 대상 이름표 {card.entity}")
            continue
        by_entity[entity_id].append(ProposedCard(
            category_name=card.category_name,
            blocks=tuple(
                ProposedBlock(kind=b.kind,
                              refs=tuple(batch.fact_handles.get(h, h) for h in b.facts))
                for b in card.blocks)))
    proposals = {eid: tuple(cards) for eid, cards in by_entity.items()}
    return proposals, notes + list(out.unresolved)


# ── 모델 호출 (연결 없음) ──────────────────────────────────────────────────

async def plan_entities(*, source_id: int, groups: Sequence[EntityGroup], categories: list[str],
                        glossary: list[dict], usage_sink=None,
                        context_for: Callable[[int], object | None] | None = None,
                        raw_sink=None, strict: bool) -> PlanningOutcome:
    """대상 묶음을 배치로 나눠 조립 모델을 부른다. 결과는 배치 순서와 무관하게 결정적이다.

    strict 이면 배치 하나라도 실패할 때 멈춘다(index 순 첫 실패를 원인으로 단다).
    아니면 실패한 배치의 대상을 failed_entity_ids 로 돌려준다.
    """
    from app.config import get_settings
    from app.ingest import extract

    s = get_settings()
    limit = getattr(s, "assemble_batch_facts", 200)
    concurrency = getattr(s, "assemble_concurrency", 1)
    if not groups:
        return PlanningOutcome(proposals={}, failed_entity_ids=(), unresolved=(),
                               batch_count=0, errors=())

    started = time.perf_counter()
    batches = build_plan_batches(groups, limit=limit)

    def call_for(batch: PlanBatch):
        async def call():
            return await extract.assemble_card_plan(
                source_id=source_id, entities=batch.payload, category_names=categories,
                glossary=glossary, usage_sink=usage_sink,
                usage_context=(context_for(batch.index) if context_for else None),
                raw_sink=raw_sink)
        return call

    results = await batching.gather_in_order([call_for(b) for b in batches],
                                             concurrency=concurrency)

    proposals: dict[int, tuple[ProposedCard, ...]] = {}
    failed: list[int] = []
    unresolved: list[str] = []
    errors: list[str] = []
    first_exc: Exception | None = None
    for batch, result in zip(batches, results):
        if isinstance(result, Exception):
            first_exc = first_exc or result
            failed.extend(g.entity_id for g in batch.groups)
            errors.append(f"plan{batch.index}: {type(result).__name__}: {result}")
            continue
        found, notes = proposals_from_output(batch, result)
        proposals.update(found)
        unresolved.extend(notes)

    logger.info("W3a 조립 source=%s 배치 %d · 대상 %d · 실패 배치 %d (%.1fs)",
                source_id, len(batches), len(groups), len(errors),
                time.perf_counter() - started)
    if strict and first_exc is not None:
        raise RuntimeError("카드 조립 실패 — 저장한 추출 결과로 재시도해야 합니다.") from first_exc
    return PlanningOutcome(proposals=proposals, failed_entity_ids=tuple(sorted(failed)),
                           unresolved=tuple(unresolved), batch_count=len(batches),
                           errors=tuple(errors))
