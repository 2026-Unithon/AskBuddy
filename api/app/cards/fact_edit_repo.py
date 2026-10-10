"""W3b — 사실 카드 읽기·편집이 함께 쓰는 DB 적재.

읽기 화면(GET /cards/{id}/facts)과 분석·저장이 같은 적재 함수를 쓴다. 그래야 화면에서 본 것과
저장이 판정하는 것이 같다. 모든 함수는 store_id 를 필수 위치 인자로 받고, 모든 SQL 에
`store_id = $n` 을 건다(RLS 미사용, D1). 쓰기는 하지 않는다.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from app.cards.fact_edit_plan import CardFactState, PinnedFact
from app.ingest.card_plan import PlanFact
from app.ingest.entity_names import normalize_alias
from app.ingest.fact_assembly import _json_list

# head 에서 고정 판까지 따라가는 최대 단수
MAX_HEAD_CHAIN = 50

EDIT_BLOCK_CHANGED = "CHANGED_ELSEWHERE"
EDIT_BLOCK_MOVED = "MOVED_ENTITY"


@dataclass(frozen=True)
class HeadInfo:
    fact_id: int
    pinned_revision_id: int
    head_revision_id: int
    head_entity_id: int
    editable_base: int | None  # 수정 기준으로 쓸 head(= 고정 판 또는 RELINK 로만 이어진 head). 못 쓰면 None
    edit_block: str | None  # None | "CHANGED_ELSEWHERE" | "MOVED_ENTITY"


async def load_plan_facts(
    conn, store_id: int, revision_ids: Sequence[int]
) -> dict[int, PlanFact]:
    """판 id → PlanFact. 선행은 W3a load_entity_groups 와 같은 규칙(대상 판의 fact_id, 자기 사실 제외)."""
    ids = sorted({int(r) for r in revision_ids})
    if not ids:
        return {}
    requires: dict[int, set[int]] = {}
    for q in await conn.fetch(
        "select q.fact_revision_id, t.fact_id from fact_revision_requires q "
        "join fact_revisions t on t.store_id = q.store_id "
        "  and t.fact_revision_id = q.requires_revision_id "
        "where q.store_id = $1 and q.fact_revision_id = any($2::bigint[])",
        store_id, ids,
    ):
        requires.setdefault(q["fact_revision_id"], set()).add(q["fact_id"])
    out: dict[int, PlanFact] = {}
    for r in await conn.fetch(
        "select r.fact_revision_id, r.fact_id, r.entity_id, r.subject, r.predicate, "
        "r.variant_temperature, r.variant_size, r.quantity_value, r.quantity_unit, "
        "r.value_text, r.polarity, r.step_order, r.conditions, r.exceptions, "
        "r.original_assertion, r.assertion "
        "from fact_revisions r "
        "where r.store_id = $1 and r.fact_revision_id = any($2::bigint[]) "
        "order by r.fact_revision_id",
        store_id, ids,
    ):
        rid, fid = r["fact_revision_id"], r["fact_id"]
        out[rid] = PlanFact(
            fact_revision_id=rid, fact_id=fid, entity_id=r["entity_id"],
            subject=r["subject"], predicate=r["predicate"],
            variant_temperature=r["variant_temperature"], variant_size=r["variant_size"],
            quantity_value=r["quantity_value"], quantity_unit=r["quantity_unit"],
            value_text=r["value_text"], polarity=r["polarity"], step_order=r["step_order"],
            conditions=_json_list(r["conditions"]), exceptions=_json_list(r["exceptions"]),
            original_assertion=r["original_assertion"], assertion=r["assertion"],
            requires_fact_ids=tuple(sorted(requires.get(rid, set()) - {fid})),
        )
    return out


async def load_card_fact_state(
    conn, store_id: int, card_id: int, version_id: int
) -> CardFactState | None:
    """카드 판이 고정한 블록·사실. 카드가 없거나 블록 사실이 하나도 없으면(= 사실 카드 아님) None.

    대상이 하나가 아니면 entity_problem="MIXED_ENTITY"(entity_id=None), 그 대상이 병합됐으면
    "MERGED_ENTITY". 호출자는 entity_problem 이 있으면 계획(build_plan)을 돌리지 않는다.
    """
    card = await conn.fetchrow(
        "select k.card_id, k.review_status, k.published_version_id, v.title "
        "from knowledge_cards k "
        "join card_versions v on v.store_id = k.store_id and v.card_id = k.card_id "
        "  and v.version_id = $3 "
        "where k.store_id = $1 and k.card_id = $2",
        store_id, card_id, version_id)
    if card is None:
        return None
    block_rows = await conn.fetch(
        "select block_id, kind, block_order from card_version_blocks "
        "where store_id = $1 and card_version_id = $2 order by block_order",
        store_id, version_id)
    fact_rows = await conn.fetch(
        "select bf.block_id, bf.fact_revision_id, bf.position "
        "from card_block_facts bf "
        "join card_version_blocks b on b.store_id = bf.store_id "
        "  and b.card_version_id = bf.card_version_id and b.block_id = bf.block_id "
        "where bf.store_id = $1 and bf.card_version_id = $2 "
        "order by b.block_order, bf.position",
        store_id, version_id)
    if not fact_rows:
        return None

    kinds = {b["block_id"]: b["kind"] for b in block_rows}
    order = {b["block_id"]: b["block_order"] for b in block_rows}
    # 어떤 DB 정렬이 와도 블록 순 → position 순을 지킨다
    fact_rows = sorted(fact_rows, key=lambda r: (order[r["block_id"]], r["position"]))
    facts = await load_plan_facts(conn, store_id, [r["fact_revision_id"] for r in fact_rows])
    pinned = tuple(
        PinnedFact(fact=facts[r["fact_revision_id"]], block_id=r["block_id"],
                   kind=kinds[r["block_id"]], position=r["position"])
        for r in fact_rows)

    entity_ids = sorted({p.fact.entity_id for p in pinned})
    entity_problem: str | None = None
    entity_id: int | None = None
    entity_name = ""
    alias_norms: frozenset[str] = frozenset()
    if len(entity_ids) != 1:
        entity_problem = "MIXED_ENTITY"
    else:
        entity_id = entity_ids[0]
        entity = next(iter(await conn.fetch(
            "select entity_id, canonical_name, merged_into_entity_id from knowledge_entities "
            "where store_id = $1 and entity_id = $2", store_id, entity_id)), None)
        if entity is not None:
            entity_name = entity["canonical_name"] or ""
            if entity["merged_into_entity_id"] is not None:
                entity_problem = "MERGED_ENTITY"
        aliases = await conn.fetch(
            "select alias_norm from knowledge_entity_aliases "
            "where store_id = $1 and entity_id = $2 and retired_at is null", store_id, entity_id)
        norms = {a["alias_norm"] for a in aliases}
        if entity_name:
            norms.add(normalize_alias(entity_name))
        alias_norms = frozenset(norms)

    return CardFactState(
        store_id=store_id, card_id=int(card["card_id"]), version_id=version_id,
        title=card["title"], review_status=card["review_status"],
        published_version_id=card["published_version_id"], entity_id=entity_id,
        entity_name=entity_name, alias_norms=alias_norms, entity_problem=entity_problem,
        blocks=tuple((b["block_id"], b["kind"], b["block_order"]) for b in block_rows),
        pinned=pinned)


async def classify_head(
    conn, store_id: int, pinned: Mapping[int, int], card_entity_id: int | None
) -> dict[int, HeadInfo]:
    """사실마다 head 가 고정 판과 어떻게 다른지 본다. pinned = {fact_id: 고정 판 id}.

    head ≠ 고정 판이면 head 에서 supersedes 를 따라 고정 판까지 가며 모든 판의
    change_kind 가 RELINK 인지 본다(최대 50단, 못 닿으면 CHANGED_ELSEWHERE).
    head 대상이 카드 대상과 다르면 MOVED_ENTITY(CHANGED_ELSEWHERE 보다 우선).
    knowledge_facts 에 행이 없는 사실은 결과에 넣지 않는다.
    """
    if not pinned:
        return {}
    heads = await conn.fetch(
        "select k.fact_id, k.head_revision_id, h.entity_id as head_entity_id "
        "from knowledge_facts k "
        "join fact_revisions h on h.store_id = k.store_id "
        "  and h.fact_revision_id = k.head_revision_id "
        "where k.store_id = $1 and k.fact_id = any($2::bigint[])",
        store_id, sorted(pinned))
    out: dict[int, HeadInfo] = {}
    for row in heads:
        fact_id = row["fact_id"]
        pinned_id = pinned[fact_id]
        head_id, head_entity = row["head_revision_id"], row["head_entity_id"]
        moved = card_entity_id is not None and head_entity != card_entity_id
        if moved:
            base, block = None, EDIT_BLOCK_MOVED  # CHANGED_ELSEWHERE 보다 우선
        elif head_id == pinned_id:
            base, block = pinned_id, None
        elif await _relink_chain(conn, store_id, head_id, pinned_id):
            base, block = head_id, None
        else:
            base, block = None, EDIT_BLOCK_CHANGED
        out[fact_id] = HeadInfo(fact_id, pinned_id, head_id, head_entity, base, block)
    return out


async def _relink_chain(conn, store_id: int, head_id: int, pinned_id: int) -> bool:
    """head 에서 고정 판 앞까지 모든 판이 RELINK 이고, 50단 안에 고정 판에 닿으면 True."""
    cur: int | None = head_id
    for _ in range(MAX_HEAD_CHAIN):
        if cur is None:
            return False
        step = await conn.fetchrow(
            "select r.fact_revision_id, r.supersedes_revision_id, m.change_kind "
            "from fact_revisions r "
            "left join fact_revision_meta m on m.store_id = r.store_id "
            "  and m.fact_revision_id = r.fact_revision_id "
            "where r.store_id = $1 and r.fact_revision_id = $2",
            store_id, cur)
        if step is None or step["change_kind"] != "RELINK":
            return False
        cur = step["supersedes_revision_id"]
        if cur == pinned_id:
            return True
    return False


def _as_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, str):
        value = json.loads(value)
    return dict(value) if isinstance(value, dict) else {}


def origin_kind(source_type: str | None, owner_answer_id: int | None) -> str:
    """근거 종류. 점주 답변 / 점주가 직접 입력한 자료 / 그 밖의 자료."""
    if owner_answer_id is not None:
        return "OWNER_ANSWER"
    return "OWNER_TEXT" if source_type == "OWNER_TEXT" else "SOURCE"


async def load_fact_rows(conn, store_id: int, state: CardFactState) -> dict[int, dict]:
    """판마다 화면 칸: change_kind, previous_sentence, origins(이 카드 판에 고정된 근거만).

    지금 occurrence 를 새로 모으지 않는다. 근거 정렬: 파일 근거 occurrence_id 순 → 점주 답변 id 순.
    """
    ids = sorted({p.fact.fact_revision_id for p in state.pinned})
    rows: dict[int, dict] = {
        rid: {"change_kind": None, "previous_sentence": None, "origins": []} for rid in ids}
    if not ids:
        return rows
    for r in await conn.fetch(
        "select r.fact_revision_id, m.change_kind, prev.original_assertion as previous_sentence "
        "from fact_revisions r "
        "left join fact_revision_meta m on m.store_id = r.store_id "
        "  and m.fact_revision_id = r.fact_revision_id "
        "left join fact_revisions prev on prev.store_id = r.store_id "
        "  and prev.fact_revision_id = r.supersedes_revision_id "
        "where r.store_id = $1 and r.fact_revision_id = any($2::bigint[])",
        store_id, ids,
    ):
        rows[r["fact_revision_id"]]["change_kind"] = r["change_kind"]
        rows[r["fact_revision_id"]]["previous_sentence"] = r["previous_sentence"]
    provenance = await conn.fetch(
        "select p.fact_revision_id, p.occurrence_id, p.owner_answer_id, "
        "coalesce(o.created_at, p.created_at) as created_at, o.source_id, o.locator_type, "
        "o.locator, s.source_type, coalesce(s.original_filename, s.title) as source_title, "
        "s.source_availability "
        "from card_version_fact_provenance p "
        "left join fact_occurrences o on o.store_id = p.store_id "
        "  and o.occurrence_id = p.occurrence_id "
        "left join sources s on s.store_id = o.store_id and s.source_id = o.source_id "
        "where p.store_id = $1 and p.card_version_id = $2 "
        "  and p.fact_revision_id = any($3::bigint[]) "
        "order by p.fact_revision_id, (p.occurrence_id is null), p.occurrence_id, "
        "p.owner_answer_id",
        store_id, state.version_id, ids)
    # DB 정렬에 기대지 않고 한 번 더 정렬한다(파일 근거 occurrence_id 순 → 점주 답변 id 순)
    provenance = sorted(provenance, key=lambda p: (
        p["fact_revision_id"], p["occurrence_id"] is None,
        p["occurrence_id"] or 0, p["owner_answer_id"] or 0))
    for p in provenance:
        answer_id = p["owner_answer_id"]
        if answer_id is not None:
            origin = {"kind": "OWNER_ANSWER", "source_id": None, "source_title": None,
                      "source_type": None, "source_availability": None, "locator_type": None,
                      "locator": {}, "owner_answer_id": answer_id,
                      "created_at": p["created_at"]}
        else:
            origin = {
                "kind": origin_kind(p["source_type"], None), "source_id": p["source_id"],
                "source_title": p["source_title"], "source_type": p["source_type"],
                "source_availability": p["source_availability"] or "AVAILABLE",
                "locator_type": p["locator_type"], "locator": _as_dict(p["locator"]),
                "owner_answer_id": None, "created_at": p["created_at"]}
        rows[p["fact_revision_id"]]["origins"].append(origin)
    return rows
