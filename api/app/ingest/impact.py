"""W2-4 영향 카드 계산 · 업로드 검수 제안 (IDENTICAL|NEW|SUPPLEMENT|CONFLICT).

규칙 (w2-common A-6·A-7, task-4, 컨트롤러 결정 G):
  - 새 사실의 대상·규격·의존으로 영향 카드만 계산한다. 기존 카드 행(knowledge_cards·card_versions·
    배정·MANUAL·needs_review_reason)은 한 줄도 쓰지 않는다. 실제 재조립은 W3 다
  - 제안은 점주 답변 제안 표(knowledge_change_proposals)와 별개인 upload_change_proposals 에 남긴다.
    관계 어휘와 판정 순서만 같다(설계 R5)
  - 네 관계 모두 PENDING_REVIEW 로 남긴다. 자동 확정·자동 발행·권위/최신성 판정은 없다
  - 충돌 제안에 기본 선택·승자 칸이 없다(사용자 결정)
  - 모든 조회·쓰기는 store_id 로 좁힌다(D1)
"""
from __future__ import annotations

import json
import logging
from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable

import asyncpg

from app.ingest.entities import lock_store_knowledge

log = logging.getLogger(__name__)

__all__ = ["AffectedCards", "affected_cards", "classify_fact", "proposal_relation",
           "variant_compatible", "record_upload_proposals"]

IDENTICAL, NEW, SUPPLEMENT, CONFLICT = "IDENTICAL", "NEW", "SUPPLEMENT", "CONFLICT"


@dataclass(frozen=True)
class AffectedCards:
    card_ids: tuple[int, ...]
    by_fact_revision: dict[int, tuple[int, ...]]


def variant_compatible(temperature: str | None, size: str | None,
                       card_variants: Iterable[tuple[str | None, str | None]]) -> bool:
    """새 사실의 규격이 카드와 겹칠 수 있는가 (D19).

    온도·사이즈를 따로 본다. 한 축마다 새 사실에 값이 없거나, 카드에 이어진 사실에 그 축 정보가
    전혀 없거나, 같은 값의 사실이 있으면 통과한다. 한 카드에 HOT·ICE 가 함께 있을 수 있다.
    """
    variants = list(card_variants)

    def axis_ok(new: str | None, values: Iterable[str | None]) -> bool:
        if new is None:
            return True
        present = {v for v in values if v is not None}
        return not present or new in present

    return (axis_ok(temperature, (t for t, _ in variants))
            and axis_ok(size, (s for _, s in variants)))


def classify_fact(*, matched_approved: set[int], fact_card_ids: set[int],
                  conflict_card_ids: set[int], preexisting: bool) -> str:
    """사실 하나의 관계. 순수 함수.

    matched_approved  — 이 사실의 영향 카드 중 승인·공개된 카드
    fact_card_ids     — 이 사실이 이미 이어진 카드
    conflict_card_ids — 이 사실의 OPEN 충돌 상대가 이어진 카드
    preexisting       — 이 자료 전에 있던 사실(링크 MATCHED)
    """
    if not matched_approved:
        return NEW
    if preexisting and fact_card_ids & matched_approved:
        return IDENTICAL
    if conflict_card_ids & matched_approved:
        return CONFLICT
    return SUPPLEMENT


def proposal_relation(fact_relations: list[str], has_approved: bool) -> str:
    """제안 머리(자료 × 대상)의 관계. 순수 함수.

    승인 카드 없음 → NEW. 있으면 CONFLICT > SUPPLEMENT > IDENTICAL 이고, IDENTICAL 은 항목이
    전부 IDENTICAL 일 때만이다. 그 밖(예: IDENTICAL + NEW)은 SUPPLEMENT.
    """
    if not has_approved:
        return NEW
    if CONFLICT in fact_relations:
        return CONFLICT
    if fact_relations and all(r == IDENTICAL for r in fact_relations):
        return IDENTICAL
    return SUPPLEMENT


async def affected_cards(conn: asyncpg.Connection, store_id: int, fact_revision_ids: list[int], *,
                         exclude_source_id: int | None) -> AffectedCards:
    """이 판들의 사실이 영향을 주는 카드. 카드 행은 읽기만 한다.

    대상은 제외(EXCLUDED)가 아니고 exclude_source_id 자료의 카드가 아닌 카드다
    (자료는 자기 카드에 제안하지 않는다). 사실은 지금 head 판의 대상·규격으로 본다.
      (a) 카드 대상 = 사실 대상, 또는 (b) 카드에 이어진 사실의 대상 = 사실 대상 — 그리고 규격 호환
      (c) 카드에 이어진 사실과 이 사실이 fact_revision_requires 로 이어짐(어느 쪽이든)
    """
    ids = sorted({int(i) for i in fact_revision_ids})
    if not ids:
        return AffectedCards(card_ids=(), by_fact_revision={})
    facts = await conn.fetch(
        "select r.fact_revision_id, k.fact_id, k.entity_id, "
        "h.variant_temperature, h.variant_size "
        "from fact_revisions r "
        "join knowledge_facts k on k.store_id = r.store_id and k.fact_id = r.fact_id "
        "join fact_revisions h on h.store_id = k.store_id "
        "  and h.fact_revision_id = k.head_revision_id "
        "where r.store_id = $1 and r.fact_revision_id = any($2::bigint[]) "
        "order by r.fact_revision_id",
        store_id, ids)
    if not facts:
        return AffectedCards(card_ids=(), by_fact_revision={})
    fact_ids = sorted({f["fact_id"] for f in facts})
    entity_ids = sorted({f["entity_id"] for f in facts})

    # 의존 — 판 단위 선행 관계를 사실 단위로 올린다
    partners: dict[int, set[int]] = defaultdict(set)
    for dep in await conn.fetch(
            "select a.fact_id as fact_id, b.fact_id as required_fact_id "
            "from fact_revision_requires q "
            "join fact_revisions a on a.store_id = q.store_id "
            "  and a.fact_revision_id = q.fact_revision_id "
            "join fact_revisions b on b.store_id = q.store_id "
            "  and b.fact_revision_id = q.requires_revision_id "
            "where q.store_id = $1 "
            "and (a.fact_id = any($2::bigint[]) or b.fact_id = any($2::bigint[]))",
            store_id, fact_ids):
        partners[dep["fact_id"]].add(dep["required_fact_id"])
        partners[dep["required_fact_id"]].add(dep["fact_id"])
    dependent_ids = sorted({p for f in fact_ids for p in partners.get(f, ())})

    cards = await conn.fetch(
        "select c.card_id, c.entity_id from knowledge_cards c "
        "where c.store_id = $1 and c.review_status <> 'EXCLUDED' "
        "and ($2::bigint is null or c.source_id is distinct from $2) "
        "and (c.entity_id = any($3::bigint[]) or exists ("
        "  select 1 from card_facts cf "
        "  join source_fact_revision_links l on l.store_id = cf.store_id "
        "    and l.source_fact_id = cf.fact_id "
        "  join knowledge_facts k on k.store_id = l.store_id and k.fact_id = l.fact_id "
        "  where cf.store_id = c.store_id and cf.card_id = c.card_id "
        "  and (k.entity_id = any($3::bigint[]) or k.fact_id = any($4::bigint[])))) "
        "order by c.card_id",
        store_id, exclude_source_id, entity_ids, dependent_ids)
    if not cards:
        return AffectedCards(card_ids=(), by_fact_revision={f["fact_revision_id"]: ()
                                                              for f in facts})
    linked: dict[int, list] = defaultdict(list)
    for row in await conn.fetch(
            "select distinct cf.card_id, k.fact_id, k.entity_id, "
            "h.variant_temperature, h.variant_size "
            "from card_facts cf "
            "join source_fact_revision_links l on l.store_id = cf.store_id "
            "  and l.source_fact_id = cf.fact_id "
            "join knowledge_facts k on k.store_id = l.store_id and k.fact_id = l.fact_id "
            "join fact_revisions h on h.store_id = k.store_id "
            "  and h.fact_revision_id = k.head_revision_id "
            "where cf.store_id = $1 and cf.card_id = any($2::bigint[])",
            store_id, [c["card_id"] for c in cards]):
        linked[row["card_id"]].append(row)

    by_revision: dict[int, tuple[int, ...]] = {}
    for fact in facts:
        hit = []
        for card in cards:
            card_facts = linked.get(card["card_id"], [])
            # 규격은 이 카드에 이어진 사실 중 같은 대상의 사실로만 본다(다른 대상의 규격은 무관)
            same_entity_facts = [cf for cf in card_facts if cf["entity_id"] == fact["entity_id"]]
            same_entity = card["entity_id"] == fact["entity_id"] or bool(same_entity_facts)
            compatible = variant_compatible(
                fact["variant_temperature"], fact["variant_size"],
                [(cf["variant_temperature"], cf["variant_size"]) for cf in same_entity_facts])
            dependent = any(cf["fact_id"] in partners.get(fact["fact_id"], ())
                            for cf in card_facts)
            if (same_entity and compatible) or dependent:
                hit.append(card["card_id"])
        by_revision[fact["fact_revision_id"]] = tuple(hit)
    all_cards = tuple(sorted({c for hit in by_revision.values() for c in hit}))
    return AffectedCards(card_ids=all_cards, by_fact_revision=by_revision)


_RANK = "array['NEW','IDENTICAL','SUPPLEMENT','CONFLICT']::varchar[]"


async def record_upload_proposals(conn: asyncpg.Connection, store_id: int, source_id: int, *,
                                  job_id: int | None) -> int:
    """이 자료가 이은 모든 판을 대상별로 묶어 검수 제안을 남긴다. 남긴(또는 이미 있던) 제안 수.

    호출자의 트랜잭션 안에서 돈다(_persist). 다시 불러도 행이 늘지 않는다 — 머리는
    PENDING_REVIEW 이고 더 강한 관계일 때만 관계·영향 카드를 올린다. 항목은 머리가
    PENDING_REVIEW 일 때만 지금 계산으로 넣거나 고치고, 결정된 제안은 건드리지 않는다(결정 J).
    """
    await lock_store_knowledge(conn, store_id)
    links = await conn.fetch(
        "select l.fact_id, l.fact_revision_id, l.link_kind, k.entity_id "
        "from source_fact_revision_links l "
        "join source_facts sf on sf.store_id = l.store_id and sf.fact_id = l.source_fact_id "
        "join knowledge_facts k on k.store_id = l.store_id and k.fact_id = l.fact_id "
        "where l.store_id = $1 and sf.source_id = $2 "
        "order by l.fact_revision_id",
        store_id, source_id)
    if not links:
        return 0

    fact_of: dict[int, int] = {}
    entity_of: dict[int, int] = {}
    kinds: dict[int, set[str]] = defaultdict(set)
    for link in links:
        fact_of[link["fact_revision_id"]] = link["fact_id"]
        entity_of[link["fact_revision_id"]] = link["entity_id"]
        kinds[link["fact_id"]].add(link["link_kind"])
    # 이 자료의 어느 원장 행도 이 사실을 새로 만들지 않았다 = 이 자료 전에 있던 사실
    preexisting = {fid for fid, k in kinds.items() if k == {"MATCHED"}}
    fact_ids = sorted(kinds)

    affected = await affected_cards(conn, store_id, sorted(fact_of),
                                    exclude_source_id=source_id)
    info = {r["card_id"]: r for r in await conn.fetch(
        "select card_id, review_status, published_version_id from knowledge_cards "
        "where store_id = $1 and card_id = any($2::bigint[])",
        store_id, list(affected.card_ids))} if affected.card_ids else {}
    approved = {cid for cid, r in info.items()
                if r["review_status"] == "APPROVED" and r["published_version_id"] is not None}

    conflict_partners: dict[int, set[int]] = defaultdict(set)
    for pair in await conn.fetch(
            "select fact_id_low, fact_id_high from fact_conflicts "
            "where store_id = $1 and status = 'OPEN' "
            "and (fact_id_low = any($2::bigint[]) or fact_id_high = any($2::bigint[]))",
            store_id, fact_ids):
        conflict_partners[pair["fact_id_low"]].add(pair["fact_id_high"])
        conflict_partners[pair["fact_id_high"]].add(pair["fact_id_low"])
    related = sorted(set(fact_ids) | {p for ps in conflict_partners.values() for p in ps})
    cards_of: dict[int, set[int]] = defaultdict(set)
    for row in await conn.fetch(
            "select distinct l.fact_id, cf.card_id from source_fact_revision_links l "
            "join card_facts cf on cf.store_id = l.store_id and cf.fact_id = l.source_fact_id "
            "where l.store_id = $1 and l.fact_id = any($2::bigint[])",
            store_id, related):
        cards_of[row["fact_id"]].add(row["card_id"])

    groups: dict[int, list[dict]] = defaultdict(list)
    for revision_id, fact_id in fact_of.items():
        affected_ids = affected.by_fact_revision.get(revision_id, ())
        matched = set(affected_ids) & approved
        partners = conflict_partners.get(fact_id, set())
        relation = classify_fact(
            matched_approved=matched, fact_card_ids=cards_of.get(fact_id, set()),
            conflict_card_ids={c for p in partners for c in cards_of.get(p, ())},
            preexisting=fact_id in preexisting)
        groups[entity_of[revision_id]].append({
            "fact_revision_id": revision_id, "fact_id": fact_id, "relation": relation,
            "matched": matched, "conflict_fact_ids": sorted(partners),
            "affected_card_ids": list(affected_ids)})

    for entity_id, items in sorted(groups.items()):
        matched_ids = sorted({c for item in items for c in item["matched"]})
        relation = proposal_relation([i["relation"] for i in items], bool(matched_ids))
        matched_cards = [{"card_id": cid,
                          "published_version_id": info[cid]["published_version_id"],
                          "review_status": info[cid]["review_status"]} for cid in matched_ids]
        await conn.execute(
            "insert into upload_change_proposals as p "
            "(store_id, source_id, job_id, entity_id, relation_type, matched_cards) "
            "values ($1, $2, $3, $4, $5, $6::jsonb) "
            "on conflict (store_id, source_id, entity_id) do update "
            "set relation_type = excluded.relation_type, "
            "matched_cards = excluded.matched_cards, updated_at = now() "
            "where p.status = 'PENDING_REVIEW' "
            f"and array_position({_RANK}, excluded.relation_type) "
            f"> array_position({_RANK}, p.relation_type)",
            store_id, source_id, job_id, entity_id, relation,
            json.dumps(matched_cards, ensure_ascii=False))
        head = await conn.fetchrow(
            "select proposal_id, status from upload_change_proposals "
            "where store_id = $1 and source_id = $2 and entity_id = $3",
            store_id, source_id, entity_id)
        if head["status"] != "PENDING_REVIEW":
            # 결정 J — 점주가 결정한 제안은 그대로 둔다. 항목을 더하지도 고치지도 않는다
            continue
        for item in items:
            # 결정 J — 검수 전 제안의 항목은 지금 계산을 따른다 (머리는 올림 규칙 유지)
            await conn.execute(
                "insert into upload_change_proposal_facts "
                "(store_id, proposal_id, fact_revision_id, fact_id, relation_type, "
                "conflict_fact_ids, affected_card_ids) "
                "values ($1, $2, $3, $4, $5, $6::bigint[], $7::bigint[]) "
                "on conflict (store_id, proposal_id, fact_revision_id) do update "
                "set relation_type = excluded.relation_type, "
                "conflict_fact_ids = excluded.conflict_fact_ids, "
                "affected_card_ids = excluded.affected_card_ids",
                store_id, head["proposal_id"], item["fact_revision_id"], item["fact_id"],
                item["relation"], item["conflict_fact_ids"], item["affected_card_ids"])
    log.info("W2 업로드 제안 store=%s source=%s 대상 %d · 판 %d · 영향 카드 %d · 승인 %d",
             store_id, source_id, len(groups), len(fact_of), len(affected.card_ids),
             len(approved))
    return len(groups)
