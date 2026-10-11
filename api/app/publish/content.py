"""카드 버전 → KnowledgeContent 조립 (W, Phase A Task 2).

**공개판은 사실 블록 카드만 싣는다.** 사실 블록이 없는 판(원문 RAW 블록 판 포함)은
`InvalidContent` 로 멈춘다 — 원문을 통째로 얼려 싣는 경로는 없다. 근거는 판에 고정된
`card_version_fact_provenance` 의 자료 occurrence 만 싣고, 점주 답변 출처(파일 없음)는
싣지 않는다. 사실마다 공개 가능한 근거가 하나도 없으면 `NoProvenance` 로 멈춘다
(불변식 6).
"""
from __future__ import annotations

import json
import re
from decimal import Decimal

import pydantic

from app.contracts.card import CardBlock
from app.contracts.common import Quantity, Variant
from app.contracts.extraction import EvidenceLocator
from app.contracts.snapshot import (
    FactProvenance,
    FactRevision,
    KnowledgeContent,
    PublishedCard,
)
from app.learn.approved_renderer import RENDERER_VERSION

# 사실 하나의 근거 상한. FactRevision.provenance 계약의 상한과 같다
MAX_FACT_PROVENANCE = 50


class NoProvenance(RuntimeError):
    """사실 판에 공개 가능한 자료 출처가 없다."""


class InvalidContent(ValueError):
    """카드 판이 사실 블록 카드가 아니거나 내용이 어긋나 공개판에 실을 수 없다."""


async def current_manifest(conn, *, store_id: int) -> dict[int, int]:
    """지금 공개해야 할 카드 집합 — `{card_id: card_version_id}`.

    **현재 카드 포인터가 정본이다** (Ruling, final fix). 승인(`APPROVED`)되고
    `published_version_id` 가 있는 카드 전체를 그 공개 포인터 버전으로 싣는다.
    직전 snapshot 을 베끼지 않는 이유:
      - 제외 뒤 복원된 카드가 다음 공개에서 스스로 돌아온다.
      - 공개 포인터가 다른 경로로 옮겨진 카드와,
        출처가 없어 한 번 빠졌던 카드가 다음
        공개에서 저절로 다시 실린다 — snapshot 을 베끼면 한 번 빠진 카드는
        영영 돌아오지 않는다.
    제외·검수 대기 등 `APPROVED` 가 아닌 카드는 싣지 않는다.
    """
    rows = await conn.fetch(
        """
        select card_id, published_version_id as card_version_id
        from knowledge_cards
        where store_id = $1 and review_status = 'APPROVED'
          and published_version_id is not null
        order by card_id
        """,
        store_id)
    return {row["card_id"]: row["card_version_id"] for row in rows}


# ---------------------------------------------------------------------------
# 사실 카드 판 (W3a) — 순수 도우미
# ---------------------------------------------------------------------------

# occurrence 위치 종류 → 계약 EvidenceLocator 의 칸. 종류에 맞는 칸 하나만 싣는다
_LOCATOR_FIELD = {"PAGE": "page", "TIMESTAMP": "timestamp_sec", "LINE": "line", "BBOX": "bbox"}
_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
_SHA256_REF = re.compile(r"^sha256:[0-9a-f]{64}$")


def _evidence_locator(locator_type: str | None, locator) -> EvidenceLocator:
    """`fact_occurrences` 의 위치를 계약 위치로 옮긴다.

    저장된 jsonb 에는 영역 이름 같은 다른 키가 함께 있을 수 있다. 계약은 다른 키를
    받지 않으므로 종류에 맞는 키 하나만 고른다. 값이 없거나 계약 검증에 실패하면
    자료 전체(WHOLE_SOURCE)로 낮춘다 — 위치가 틀린 근거보다 넓은 근거가 낫다.
    """
    field = _LOCATOR_FIELD.get(locator_type or "")
    if field is None:
        return EvidenceLocator()
    if isinstance(locator, str):
        try:
            locator = json.loads(locator)
        except ValueError:
            return EvidenceLocator()
    if not isinstance(locator, dict) or locator.get(field) is None:
        return EvidenceLocator()
    try:
        return EvidenceLocator(type=locator_type, **{field: locator[field]})
    except (pydantic.ValidationError, TypeError):
        return EvidenceLocator()


def _hash_ref(raw: str | None) -> str | None:
    """자료 지문을 계약 표기 `sha256:<64 소문자 16진>` 로 맞춘다. 형식 밖이면 싣지 않는다."""
    if raw is None:
        return None
    if _SHA256_HEX.match(raw):
        return "sha256:" + raw
    if _SHA256_REF.match(raw):
        return raw
    return None


def _quantity_text(value: Decimal) -> str:
    """numeric 을 계약 수치 문자열로 — 뒤쪽 0 을 지우고 지수 표기를 쓰지 않는다."""
    return format(Decimal(value).normalize(), "f")


def _provenance_key(p: FactProvenance) -> tuple[bool, int]:
    # hash payload 의 정렬 규칙과 같다 — 파일 근거 먼저 occurrence_id 순, 다음 점주 답변
    return p.owner_answer_id is not None, int(p.occurrence_id or p.owner_answer_id)


def _ordered_provenance(items) -> tuple[FactProvenance, ...]:
    """근거를 한 규칙으로 — 같은 근거는 하나, 파일 근거 occurrence_id 순 다음 점주 답변 순, 50 개까지.

    카드 하나에 실린 사실과 여러 카드에서 합친 사실이 같은 순서를 가져야 공개 내용이
    SQL 순서에 기대지 않는다.
    """
    seen: dict[str, FactProvenance] = {}
    for p in items:
        seen.setdefault(p.model_dump_json(), p)
    return tuple(sorted(seen.values(), key=_provenance_key)[:MAX_FACT_PROVENANCE])


def _merge_fact(a: FactRevision, b: FactRevision) -> FactRevision:
    """여러 카드에 실린 같은 사실 판을 하나로 합친다.

    판은 불변이므로 근거·선행 밖의 칸이 다르면 데이터가 어긋난 것이다. 근거는
    카드 판마다 그때 고정한 것이라 다를 수 있어 합집합을 싣는다.
    """
    exclude = {"provenance", "requires"}
    if a.model_dump(exclude=exclude) != b.model_dump(exclude=exclude):
        raise InvalidContent(
            f"사실 판 {a.fact_revision_id} 가 카드마다 다른 내용으로 실렸다")
    provenance = _ordered_provenance((*a.provenance, *b.provenance))
    requires = sorted(set(a.requires) | set(b.requires), key=int)
    return FactRevision.model_validate(
        {**a.model_dump(), "provenance": [p.model_dump() for p in provenance],
         "requires": requires})


def _json_list(value) -> tuple[str, ...]:
    if isinstance(value, str):
        value = json.loads(value)
    return tuple(value or ())


# ---------------------------------------------------------------------------
# 조립
# ---------------------------------------------------------------------------

async def _fact_card(
    conn, *, store_id: int, card_id: int, card_version_id: int, title: str,
    block_rows, fact_rows,
) -> tuple[PublishedCard, list[FactRevision]]:
    """사실 블록 카드 판 → (공개 카드, 그 판에 고정된 사실 판들).

    블록·블록 사실·근거는 모두 판에 고정된 행만 읽는다. 지금의 occurrence 를 새로
    모으지 않는다 — 같은 판을 언제 다시 공개해도 내용이 같아야 한다.
    """
    by_block: dict[str, list[int]] = {}
    for row in sorted(fact_rows, key=lambda r: (r["block_id"], r["position"])):
        by_block.setdefault(row["block_id"], []).append(row["fact_revision_id"])

    blocks: list[CardBlock] = [
        CardBlock(
            block_id=row["block_id"], kind=row["kind"], order=row["block_order"],
            fact_revision_ids=tuple(str(r) for r in by_block.get(row["block_id"], ())))
        for row in block_rows]

    pinned = sorted({r for ids in by_block.values() for r in ids})
    revision_rows = {r["fact_revision_id"]: r for r in await conn.fetch(
        """
        select fact_revision_id, fact_id, entity_id, original_assertion, assertion,
               subject, predicate, variant_temperature, variant_size,
               quantity_value, quantity_unit, value_text, polarity, step_order,
               conditions, exceptions
        from fact_revisions
        where store_id = $1 and fact_revision_id = any($2::bigint[])
        """,
        store_id, pinned)}
    missing = [r for r in pinned if r not in revision_rows]
    if missing:
        raise InvalidContent(
            f"사실 카드 판 {card_version_id} 에 고정된 사실 판이 없다: {missing}")

    entity_ids = {row["entity_id"] for row in revision_rows.values()}
    if len(entity_ids) != 1:
        raise InvalidContent(f"사실 카드 판 {card_version_id} 의 대상이 하나가 아니다")
    (entity_id,) = entity_ids
    variants = {(row["variant_temperature"], row["variant_size"])
                for row in revision_rows.values()}
    card_variant = Variant()
    if len(variants) == 1:
        (temperature, size), = variants
        card_variant = Variant(temperature=temperature, size=size)

    # 선행은 fact_id 로 이어진 판을 가리킨다. 병합 판은 옛 판을 가리킬 수 있으므로
    # 이 판에 고정된 같은 fact_id 판으로 바꾼다
    pinned_by_fact: dict[int, set[int]] = {}
    for rid, row in revision_rows.items():
        pinned_by_fact.setdefault(row["fact_id"], set()).add(rid)
    requires: dict[int, set[int]] = {rid: set() for rid in pinned}
    for row in await conn.fetch(
        """
        select q.fact_revision_id, t.fact_id
        from fact_revision_requires q
        join fact_revisions t on t.store_id = q.store_id
         and t.fact_revision_id = q.requires_revision_id
        where q.store_id = $1 and q.fact_revision_id = any($2::bigint[])
        """,
        store_id, pinned):
        rid = row["fact_revision_id"]
        if row["fact_id"] == revision_rows[rid]["fact_id"]:
            continue  # 자기 사실의 옛 판을 가리키는 선행은 싣지 않는다
        targets = pinned_by_fact.get(row["fact_id"], set())
        if len(targets) != 1:
            raise InvalidContent(
                f"사실 카드 판 {card_version_id} 의 사실 {rid} 의 선행 사실이 카드에 없다")
        requires[rid] |= targets

    provenance: dict[int, list[FactProvenance]] = {rid: [] for rid in pinned}
    for row in await conn.fetch(
        """
        select p.provenance_id, p.fact_revision_id, p.occurrence_id, p.owner_answer_id,
               o.source_id, o.source_content_hash, o.locator_type, o.locator
        from card_version_fact_provenance p
        left join fact_occurrences o on o.store_id = p.store_id
         and o.occurrence_id = p.occurrence_id
        where p.store_id = $1 and p.card_version_id = $2
        order by p.fact_revision_id, p.provenance_id
        """,
        store_id, card_version_id):
        rid = row["fact_revision_id"]
        if rid not in provenance:
            continue
        if row["occurrence_id"] is not None:
            if row["source_id"] is None:
                # FK(card_version_fact_provenance_occurrence_fkey, ON DELETE 없음)가 참조된
                # occurrence 삭제를 막고 fact_occurrences.source_id 는 NOT NULL 이라 생기지 않는다.
                # 그래도 "None" 출처를 싣지 않고 멈춘다
                raise InvalidContent(
                    f"카드 판 {card_version_id} 의 근거 occurrence {row['occurrence_id']} 를 찾을 수 없다")
            provenance[rid].append(FactProvenance(
                occurrence_id=str(row["occurrence_id"]), source_id=str(row["source_id"]),
                source_content_hash=_hash_ref(row["source_content_hash"]),
                locator=_evidence_locator(row["locator_type"], row["locator"])))
        # 점주 답변 출처(파일 없음)는 공개하지 않는다 — 점주 답변 근거는
        # OWNER_TEXT 자료 occurrence 로 온다
    for rid in pinned:
        if not provenance[rid]:
            raise NoProvenance(
                f"카드 판 {card_version_id} 의 사실 {rid} 에 공개 가능한 출처가 없다")

    facts: list[FactRevision] = []
    for rid in pinned:
        row = revision_rows[rid]
        quantity = None
        if row["quantity_value"] is not None:
            quantity = Quantity(value=_quantity_text(row["quantity_value"]),
                                unit=row["quantity_unit"])
        facts.append(FactRevision(
            fact_revision_id=str(rid), fact_id=str(row["fact_id"]),
            entity_id=str(row["entity_id"]),
            original_assertion=row["original_assertion"], assertion=row["assertion"],
            subject=row["subject"], predicate=row["predicate"],
            variant=Variant(temperature=row["variant_temperature"],
                            size=row["variant_size"]),
            quantity=quantity,
            value_text=row["value_text"] if quantity is None else None,
            polarity=row["polarity"], order=row["step_order"],
            conditions=_json_list(row["conditions"]),
            exceptions=_json_list(row["exceptions"]),
            requires=tuple(str(r) for r in sorted(requires[rid])),
            provenance=_ordered_provenance(provenance[rid])))

    card = PublishedCard(
        card_id=str(card_id), card_version_id=str(card_version_id),
        entity_id=str(entity_id), variant=card_variant, title=title, blocks=tuple(blocks))
    return card, facts


async def build_knowledge_content(
    conn, *, store_id: int, manifest: dict[int, int], glossary_version: str,
) -> KnowledgeContent:
    """manifest 의 각 카드 버전을 읽어 불변 `KnowledgeContent` 로 조립한다.

    사실 블록 카드 판만 싣는다. 블록이 없거나, RAW 블록이 있거나, 블록 사실 행이
    없는 판은 `InvalidContent` 다 — 블록·블록 사실·사실 판·판에 고정된 근거와 실제
    대상 id 를 싣는다. 반환 `raw_spans` 는 언제나 비어 있다.
    """
    cards: list[PublishedCard] = []
    facts_by_id: dict[int, FactRevision] = {}

    for card_id, card_version_id in manifest.items():
        version_row = await conn.fetchrow(
            """
            select title from card_versions
            where store_id = $1 and card_id = $2 and version_id = $3
            """,
            store_id, card_id, card_version_id)
        if version_row is None:
            raise ValueError(
                f"카드 버전을 찾을 수 없다: store={store_id} card={card_id} "
                f"version={card_version_id}")

        block_rows = await conn.fetch(
            """
            select block_id, kind, block_order, raw_span_id
            from card_version_blocks
            where store_id = $1 and card_version_id = $2
            order by block_order
            """,
            store_id, card_version_id)
        fact_rows = await conn.fetch(
            """
            select block_id, fact_revision_id, position
            from card_block_facts
            where store_id = $1 and card_version_id = $2
            order by block_id, position
            """,
            store_id, card_version_id)
        if (not block_rows or not fact_rows
                or any(row["raw_span_id"] is not None for row in block_rows)):
            raise InvalidContent(
                f"카드 판 {card_version_id} 은 사실 블록 카드가 아니다 — 사실 카드만 공개한다")

        title = (version_row["title"] or "").strip()
        title = title[:120] if title else "제목 없음"

        card, facts = await _fact_card(
            conn, store_id=store_id, card_id=card_id, card_version_id=card_version_id,
            title=title, block_rows=block_rows, fact_rows=fact_rows)
        cards.append(card)
        for fact in facts:
            rid = int(fact.fact_revision_id)
            facts_by_id[rid] = (_merge_fact(facts_by_id[rid], fact)
                                if rid in facts_by_id else fact)

    return KnowledgeContent(
        store_id=str(store_id), glossary_version=glossary_version,
        renderer_version=RENDERER_VERSION, cards=tuple(cards),
        fact_revisions=tuple(facts_by_id[r] for r in sorted(facts_by_id)),
        raw_spans=())
