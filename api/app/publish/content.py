"""카드 버전 → RAW 블록 고정과 KnowledgeContent 조립 (W, CP-05 / Task 2).

**카드 버전은 승인 시점의 원문을 그대로 얼려둔다.** typed 파싱이 아직 없는
지금은 원문 전체를 RAW 블록 몇 개로 쪼개 `raw_spans` 에 못박고, 그 뒤로는
`card_versions.content` 가 바뀌어도 이미 발행된 블록은 움직이지 않는다.
한 번 고정하면 다시 만들지 않는다(멱등) — 재실행마다 raw_span_id 가 새로
발급되면 이전 발행이 인용한 구간이 조용히 달라진다.

원문의 출처는 둘 중 하나다: 점주가 올린 자료(`knowledge_cards.source_id`),
또는 신입 질문에 점주가 직접 단 답변(`owner_answers`, D 2026-09-27). 어느 쪽도
없으면 공개할 근거가 없다는 뜻이므로 `NoProvenance` 로 멈춘다 — 근거 없이
싣지 않는다(불변식 6).
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
    RawSpan,
)
from app.learn.approved_renderer import RENDERER_VERSION

# 원문 한 조각의 최대 길이. RawSpan.text 계약의 상한과 같다 (app.contracts.snapshot)
RAW_SPAN_MAX = 4000
# 카드 하나에 담기는 블록 수 상한. PublishedCard.blocks 계약의 상한과 같다
MAX_BLOCKS = 20
# 사실 하나의 근거 상한. FactRevision.provenance 계약의 상한과 같다
MAX_FACT_PROVENANCE = 50


class NoProvenance(RuntimeError):
    """카드 버전에 공개 가능한 출처(자료·점주 답변)가 없다."""


class InvalidContent(ValueError):
    """카드 버전 원문이 비었거나 블록 상한을 넘어 공개판에 실을 수 없다.

    빈 원문은 블록 0개가 되어 조립 단계에서 뒤늦게 터지므로, 고정 단계에서
    이 예외로 명시적으로 멈춘다 — 블록 없는 버전을 조용히 만들지 않는다.
    """


def _split_raw_spans(content: str, max_len: int) -> list[str]:
    """빈 줄(`\\n\\n`) 경계로 `max_len` 이하 조각을 만든다.

    원문 공백을 하나도 버리지 않기 위해 구분자 `\\n\\n` 을 별도 토큰으로 남겨
    쪼갠다 — 조각을 순서대로 이어 붙이면 원문과 완전히 같아진다. 문단(또는
    구분자) 하나가 그 자체로 `max_len` 을 넘으면 문자 단위로 더 자른다.
    """
    if not content:
        return []

    parts: list[str] = []
    rest = content
    while True:
        idx = rest.find("\n\n")
        if idx == -1:
            if rest:
                parts.append(rest)
            break
        if idx > 0:
            parts.append(rest[:idx])
        parts.append("\n\n")
        rest = rest[idx + 2:]

    chunks: list[str] = []
    current = ""
    for part in parts:
        if len(current) + len(part) <= max_len:
            current += part
            continue
        if current:
            chunks.append(current)
            current = ""
        if len(part) <= max_len:
            current = part
            continue
        # 문단 하나가 상한을 넘는다 — 문자 단위로 잘라 각각 조각으로 만든다
        for i in range(0, len(part), max_len):
            piece = part[i:i + max_len]
            if len(piece) == max_len:
                chunks.append(piece)
            else:
                current = piece
    if current:
        chunks.append(current)
    return chunks


async def _resolve_provenance(
    conn, *, store_id: int, card_id: int, allow_owner_answer: bool,
) -> tuple[int | None, int | None]:
    """(source_id, owner_answer_id) 중 정확히 하나만 채워 돌려준다.

    (1) 자료 출처가 있으면 그것을 쓴다. (2) 없고 `allow_owner_answer` 면 그
    카드에 달린 가장 이른 점주 답변을 쓴다. `owner_answers` 에는 store_id 가
    없으므로 `pending_questions` 를 거쳐 매장을 확인한다. (3) 둘 다 없으면
    공개할 수 없다.
    """
    source_id = await conn.fetchval(
        "select source_id from knowledge_cards where store_id = $1 and card_id = $2",
        store_id, card_id)
    if source_id is not None:
        return source_id, None

    if allow_owner_answer:
        answer_id = await conn.fetchval(
            """
            select oa.answer_id
            from owner_answers oa
            join pending_questions pq on pq.question_id = oa.question_id
            where pq.store_id = $1 and oa.card_id = $2
            order by oa.answer_id asc
            limit 1
            """,
            store_id, card_id)
        if answer_id is not None:
            return None, answer_id

    raise NoProvenance(f"카드 {card_id} 에 공개 가능한 출처(자료·점주 답변)가 없다")


async def ensure_raw_blocks(
    conn, *, store_id: int, card_id: int, card_version_id: int,
    allow_owner_answer: bool,
) -> None:
    """카드 버전의 원문을 RAW 블록으로 고정한다.

    이미 블록이 있으면 아무것도 하지 않는다(멱등·불변) — 한 번 발행에 실린
    원문 구간은 원본이 나중에 바뀌어도 그대로 남아야 과거 인용이 재현된다.

    **트랜잭션은 호출부 책임이다.** 이 함수는 주어진 커넥션 위에서
    `raw_spans` 행과 `card_version_blocks` 행을 조각 수만큼 순서대로
    insert 할 뿐, 트랜잭션을 열거나 커밋하지 않는다. 여러 카드를 한 번에
    발행할 때 하나가 실패하면 이 함수가 만든 행도 함께 롤백돼야 하므로,
    호출부가 트랜잭션 블록 안에서만 이 함수를 부른다.
    """
    exists = await conn.fetchval(
        """
        select 1 from card_version_blocks
        where store_id = $1 and card_version_id = $2
        limit 1
        """,
        store_id, card_version_id)
    if exists:
        return

    version_row = await conn.fetchrow(
        """
        select content, owner_answer_id from card_versions
        where store_id = $1 and card_id = $2 and version_id = $3
        """,
        store_id, card_id, card_version_id)
    if version_row is None:
        raise ValueError(
            f"카드 버전을 찾을 수 없다: store={store_id} card={card_id} "
            f"version={card_version_id}")

    version_answer_id = version_row.get("owner_answer_id")
    if version_answer_id is not None:
        # 이 판의 본문은 점주 답변이다. 카드에 자료 출처가 있어도 그 자료를 인용하면
        # 자료에 없는 내용을 자료 근거로 싣게 된다. 판에 적힌 답변만 출처로 쓴다
        if not allow_owner_answer:
            raise NoProvenance(
                f"카드 {card_id} 판 {card_version_id} 은 점주 답변 출처라 아직 공개할 수 없다")
        source_id, owner_answer_id = None, version_answer_id
    else:
        source_id, owner_answer_id = await _resolve_provenance(
            conn, store_id=store_id, card_id=card_id,
            allow_owner_answer=allow_owner_answer)

    content = version_row["content"] or ""
    if not content.strip():
        raise InvalidContent(
            f"카드 버전 {card_version_id} 의 원문이 비어 있어 공개할 수 없다")

    chunks = _split_raw_spans(content, RAW_SPAN_MAX)
    if len(chunks) > MAX_BLOCKS:
        raise InvalidContent(
            f"카드 버전 {card_version_id} 의 원문이 {len(chunks)}조각으로 "
            f"쪼개져 상한 {MAX_BLOCKS}을 넘는다")

    for n, chunk in enumerate(chunks, start=1):
        raw_span_id = await conn.fetchval(
            """
            insert into raw_spans (store_id, source_id, owner_answer_id,
                                   span_text, locator_type, locator)
            values ($1, $2, $3, $4, 'WHOLE_SOURCE', '{}'::jsonb)
            returning raw_span_id
            """,
            store_id, source_id, owner_answer_id, chunk)
        await conn.execute(
            """
            insert into card_version_blocks (store_id, card_version_id,
                                             block_id, kind, block_order,
                                             raw_span_id)
            values ($1, $2, $3, 'RAW', $4, $5)
            """,
            store_id, card_version_id, f"raw{n}", n, raw_span_id)


async def current_manifest(conn, *, store_id: int) -> dict[int, int]:
    """지금 공개해야 할 카드 집합 — `{card_id: card_version_id}`.

    **현재 카드 포인터가 정본이다** (Ruling, final fix). 승인(`APPROVED`)되고
    `published_version_id` 가 있는 카드 전체를 그 공개 포인터 버전으로 싣는다.
    직전 snapshot 을 베끼지 않는 이유:
      - 제외 뒤 복원된 카드가 다음 공개에서 스스로 돌아온다.
      - 레거시 경로(공개 포인터를 직접 옮기는 R·ingest 경로)로 공개된 카드와,
        출처가 없어 한 번 빠졌던 카드(예: 점주 답변 공개 플래그 OFF)가 다음
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

async def _raw_block(conn, *, store_id: int, row, spans_by_id: dict[str, RawSpan]) -> CardBlock:
    """블록 행 하나를 CardBlock 으로. 원문 구간이 있으면 처음 볼 때 그 구간을 읽어 둔다."""
    raw_span_id = row["raw_span_id"]
    block = CardBlock(
        block_id=row["block_id"], kind=row["kind"],
        order=row["block_order"],
        raw_span_id=str(raw_span_id) if raw_span_id is not None else None)

    if raw_span_id is not None and str(raw_span_id) not in spans_by_id:
        span_row = await conn.fetchrow(
            """
            select raw_span_id, source_id, owner_answer_id, span_text
            from raw_spans
            where store_id = $1 and raw_span_id = $2
            """,
            store_id, raw_span_id)
        spans_by_id[str(raw_span_id)] = RawSpan(
            raw_span_id=str(span_row["raw_span_id"]),
            source_id=(str(span_row["source_id"])
                       if span_row["source_id"] is not None else None),
            owner_answer_id=(str(span_row["owner_answer_id"])
                              if span_row["owner_answer_id"] is not None
                              else None),
            text=span_row["span_text"])
    return block


async def _fact_card(
    conn, *, store_id: int, card_id: int, card_version_id: int, title: str,
    block_rows, fact_rows, spans_by_id: dict[str, RawSpan], allow_owner_answer: bool,
) -> tuple[PublishedCard, list[FactRevision]]:
    """사실 블록 카드 판 → (공개 카드, 그 판에 고정된 사실 판들).

    블록·블록 사실·근거는 모두 판에 고정된 행만 읽는다. 지금의 occurrence 를 새로
    모으지 않는다 — 같은 판을 언제 다시 공개해도 내용이 같아야 한다.
    """
    by_block: dict[str, list[int]] = {}
    for row in sorted(fact_rows, key=lambda r: (r["block_id"], r["position"])):
        by_block.setdefault(row["block_id"], []).append(row["fact_revision_id"])

    blocks: list[CardBlock] = []
    for row in block_rows:
        if row["raw_span_id"] is not None:
            blocks.append(await _raw_block(conn, store_id=store_id, row=row,
                                           spans_by_id=spans_by_id))
            continue
        blocks.append(CardBlock(
            block_id=row["block_id"], kind=row["kind"], order=row["block_order"],
            fact_revision_ids=tuple(str(r) for r in by_block.get(row["block_id"], ()))))

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
        elif allow_owner_answer:
            provenance[rid].append(FactProvenance(owner_answer_id=str(row["owner_answer_id"])))
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
    allow_owner_answer: bool = False,
) -> KnowledgeContent:
    """manifest 의 각 카드 버전을 읽어 불변 `KnowledgeContent` 로 조립한다.

    블록이 없는 버전은 `ensure_raw_blocks` 를 먼저 부르지 않은 것이므로
    `ValueError` 로 멈춘다 — 호출부가 발행 전에 순서를 보장해야 한다.

    **판의 종류는 플래그가 아니라 데이터로 가른다.** 판에 `card_block_facts` 행이
    없으면 레거시(RAW) 판이다 — `entity_id` 는 `card_id` 를 그대로 쓰고(Ruling, Task 2)
    공개 내용은 W3a 이전과 한 글자도 다르지 않다(이미 발행된 snapshot hash 불변).
    행이 있으면 사실 카드 판이다 — 블록 사실·그 사실 판·판에 고정된 근거와 실제
    대상 id 를 싣는다. 점주 답변 근거는 `allow_owner_answer` 일 때만 싣는다.
    """
    cards: list[PublishedCard] = []
    spans_by_id: dict[str, RawSpan] = {}
    facts_by_id: dict[int, FactRevision] = {}
    # entity_id 이름공간 충돌 검사용. 레거시 카드는 entity_id=str(card_id), 사실 카드는
    # 실제 대상 id 를 싣는다 — 둘 다 전역 identity 숫자라 같은 문자열이 될 수 있다
    legacy_entity_ids: set[str] = set()
    fact_entity_ids: set[str] = set()

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
        if not block_rows:
            raise ValueError(
                f"카드 버전 {card_version_id} 에 블록이 없다. "
                "ensure_raw_blocks 를 먼저 불러야 한다")

        fact_rows = await conn.fetch(
            """
            select block_id, fact_revision_id, position
            from card_block_facts
            where store_id = $1 and card_version_id = $2
            order by block_id, position
            """,
            store_id, card_version_id)

        title = (version_row["title"] or "").strip()
        title = title[:120] if title else "제목 없음"

        if fact_rows:
            card, facts = await _fact_card(
                conn, store_id=store_id, card_id=card_id, card_version_id=card_version_id,
                title=title, block_rows=block_rows, fact_rows=fact_rows,
                spans_by_id=spans_by_id, allow_owner_answer=allow_owner_answer)
            cards.append(card)
            fact_entity_ids.add(card.entity_id)
            fact_entity_ids.update(fact.entity_id for fact in facts)
            for fact in facts:
                rid = int(fact.fact_revision_id)
                facts_by_id[rid] = (_merge_fact(facts_by_id[rid], fact)
                                    if rid in facts_by_id else fact)
            continue

        # 레거시(RAW) 판 — W3a 이전 경로 그대로
        blocks: list[CardBlock] = []
        for row in block_rows:
            blocks.append(await _raw_block(conn, store_id=store_id, row=row,
                                           spans_by_id=spans_by_id))

        cards.append(PublishedCard(
            card_id=str(card_id), card_version_id=str(card_version_id),
            entity_id=str(card_id), title=title, blocks=tuple(blocks)))
        legacy_entity_ids.add(str(card_id))

    # R planner 는 질문이 가리킨 카드의 entity_id 로 snapshot 전체의 사실을 고른다.
    # 레거시 카드 id 와 사실 대상 id 가 같은 숫자면 다른 대상의 사실로 답하고 대상 일치
    # 검사도 통과한다. 계약에서 이름공간을 나누기 전까지는 공개를 거절한다(fail closed).
    # 사실 카드가 없으면 집합이 비어 레거시 판 결과는 이전과 같다
    collided = sorted(legacy_entity_ids & fact_entity_ids, key=int)
    if collided:
        raise InvalidContent(
            "레거시 카드 id 와 사실 카드 대상 id 가 같은 entity_id 를 쓴다: "
            f"{', '.join(collided)}. 계약에서 이름공간을 나누기 전까지 공개할 수 없다")

    return KnowledgeContent(
        store_id=str(store_id), glossary_version=glossary_version,
        renderer_version=RENDERER_VERSION, cards=tuple(cards),
        fact_revisions=tuple(facts_by_id[r] for r in sorted(facts_by_id)),
        raw_spans=tuple(spans_by_id.values()))
