"""W3b — 카드 사실 편집 저장 (PUT /cards/{card_id}/facts).

한 트랜잭션 안에서(호출자가 연다) 바뀐 사실만 새 판(OWNER_CORRECTION / OWNER_ADD)으로 남기고,
새 OWNER_EDIT 카드 초안 판(서버 렌더링 본문 + 블록·블록 사실·근거 고정)을 만든다.
공개판은 재승인(POST /cards/{id}/approve) 전까지 그대로다. 공개 경로·계약은 건드리지 않는다.

점주가 고치거나 더한 사실의 출처는 점주 입력 자료(sources.source_type='OWNER_TEXT', 파일 없음)
한 행과 판마다 fact_occurrences(LINE n) 로 남긴다(Q1-A).

잠금 순서: 매장 지식 잠금 → 카드 행 for update (W3a 와 같다, 교착 없음).
모든 SQL 은 store_id 로 좁힌다(D1). 처분 갱신은 이 카드를 가리키는 행만 고친다(설계 D-12).
"""
from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Mapping, Sequence

from app.cards import repository as cards_repo
from app.cards.fact_edit_plan import (
    EditError,
    EditPlan,
    NormalizedFields,
    PlannedAdd,
    build_plan,
)
from app.cards.fact_edit_repo import (
    EDIT_BLOCK_MOVED,
    classify_head,
    load_card_fact_state,
    load_plan_facts,
)
from app.cards.fact_edit_schemas import (
    EditModify,
    FactEditRequest,
    FactEditResult,
    FactRevisionResult,
)
from app.ingest import card_plan
from app.ingest.card_plan import PlanFact, ValidatedCard
from app.ingest.entities import lock_store_knowledge
from app.ingest.fact_cards import (
    Origin,
    card_review_reason,
    pin_card_version,
    provenance_for,
    replace_legacy_facts,
    write_version_evidence,
)
from app.ingest.fact_keys import FactShape, identity_key, slot_key
from app.ingest.fact_ledger import _create_fact, _record_conflicts
from app.ingest.fact_revisions import FactChange, StaleFactRevision, revise_fact

logger = logging.getLogger(__name__)

REASON_OWNER_REMOVED = "OWNER_REMOVED"
CORRECTION_REASON = "카드 사실 편집"
ADD_REASON = "카드 사실 추가"
OWNER_TEXT_TITLE = "카드 직접 입력 · {title}"
_TITLE_MAX = 200

# 오류 코드 → 서버 메시지 (common §8 문장)
_MESSAGES = {
    "CARD_NOT_FOUND": "카드를 찾을 수 없습니다.",
    "CARD_EXCLUDED": "제외된 카드를 먼저 복원해 주세요.",
    "NOT_FACT_CARD": "사실 단위로 고칠 수 있는 카드가 아닙니다.",
    "CARD_VERSION_CONFLICT": "그사이 카드가 바뀌었어요. 최신 내용을 불러온 뒤 다시 고쳐 주세요.",
    "FACT_CHANGED_ELSEWHERE": "이 사실은 다른 곳에서 먼저 고쳐졌어요. 빼고 새로 넣어 주세요.",
    "FACT_MOVED_ENTITY": "메뉴 정리가 바뀌어 이 카드에서 고칠 수 없어요.",
    "CARD_ENTITY_MOVED": "메뉴 정리가 바뀌어 이 카드에서 고칠 수 없어요.",
    "IDEMPOTENCY_CONFLICT": "같은 요청 키로 다른 내용이 이미 저장됐어요. 새로고침 뒤 다시 시도해 주세요.",
    "FACT_VALUE_NOT_IN_SENTENCE": "숫자 칸과 문장 속 숫자가 달라요. 문장도 같이 고쳐 주세요.",
    "STEP_REQUIRES_ORDER": "먼저 해야 하는 단계보다 앞으로 옮길 수 없어요.",
    "FACT_REQUIRED_BY_OTHER": "다른 단계가 이 내용을 먼저 필요로 해서 뺄 수 없어요.",
    "STEP_KIND_CHANGE": "순서 단계를 일반 내용으로(또는 반대로) 바꾸려면 빼고 새로 넣어 주세요.",
    "FACT_DUPLICATE_IN_CARD": "이 카드에 이미 같은 내용이 있어요.",
    "VARIANT_UNRESOLVED": "어떤 규격(HOT/ICE·사이즈)인지 알 수 없어요. 규격을 고르거나 문장을 고쳐 주세요.",
    "CARD_WOULD_BE_EMPTY": '사실이 하나도 남지 않아요. 카드를 지우려면 "카드 지우기"를 눌러 주세요.',
}
_GENERIC = "이 변경은 저장할 수 없어요. 새로고침 뒤 다시 시도해 주세요."


def message_for(code: str) -> str:
    """오류 코드의 한국어 한 문장. 표에 없으면(배치·집합·칸 오류) 공통 문장."""
    return _MESSAGES.get(code, _GENERIC)


def request_hash(req: FactEditRequest) -> str:
    """멱등 대조용 본문 hash. 멱등 키 자체는 넣지 않는다(common §7)."""
    return hashlib.sha256(req.model_dump_json(exclude={"idempotency_key"}).encode()).hexdigest()


def _one_line(text: str) -> str:
    # 렌더링 본문과 같은 규칙 — 사실 하나는 한 줄
    return card_plan._one_line(text.strip())


def owner_text_lines(card: ValidatedCard, new_ids: set[int]) -> list[tuple[int, int, str]]:
    """점주 입력 자료의 줄: (줄 번호, 판 id, 블록 id). 새 카드 판의 블록 순 → 줄 순, 판마다 한 줄."""
    out: list[tuple[int, int, str]] = []
    seen: set[int] = set()
    for b in card.blocks:
        for rid in b.fact_revision_ids:
            if rid in new_ids and rid not in seen:
                seen.add(rid)
                out.append((len(out) + 1, rid, b.block_id))
    return out


def first_blocks(card: ValidatedCard, facts: Mapping[int, PlanFact]) -> dict[int, str]:
    """fact_id → 새 카드 안 첫 블록 id."""
    out: dict[int, str] = {}
    for b in card.blocks:
        for rid in b.fact_revision_ids:
            out.setdefault(facts[rid].fact_id, b.block_id)
    return out


def add_shape(entity_name: str, n: NormalizedFields) -> FactShape:
    """ADD 의 판 재료(common §7). 주어 = 카드 대상 이름."""
    return FactShape(
        subject=entity_name, predicate=n.predicate,
        variant_temperature=n.temperature, variant_size=n.size, variant_other=None,
        quantity_value=n.quantity, quantity_unit=n.unit, value_text=n.value_text,
        polarity=n.polarity, step_order=n.step_order,
        conditions=tuple(n.conditions), exceptions=tuple(n.exceptions),
        original_assertion=n.sentence, assertion=n.sentence)


def modify_change(item: EditModify, n: NormalizedFields, base: PlanFact) -> FactChange:
    """MODIFY → revise_fact 의 FactChange. 값 칸은 점주가 보낸 원래 문자열로 다시 가른다.

    단위 칸이 비면 "" 를 넘긴다 — None 이면 revise_fact 가 옛 단위를 물려받아 계획과 달라진다.
    값을 지우는 경우(정규화 수치·서술값 모두 None 인데 고정 판에는 값이 있음)는 FactChange 로
    표현할 수 없어(value="" 는 서술값 "" 이 된다) 저장하지 않는다 — 보고서 BLOCKED 항목.
    """
    had_value = base.quantity_value is not None or base.value_text is not None
    if n.quantity is None and n.value_text is None:
        if had_value:
            raise EditError(422, "FACT_FIELD_INVALID",
                            {"ref": base.fact_revision_id, "field": "value"})
        value, unit = None, None  # 고정 판에도 값이 없다 — 그대로
    else:
        value, unit = item.fact.value, item.fact.unit or ""
    return FactChange(
        value=value, unit=unit, polarity=n.polarity, conditions=tuple(n.conditions),
        exceptions=tuple(n.exceptions), step_order=n.step_order,
        assertion=n.sentence, original_assertion=n.sentence)


async def _next_edit_id(conn) -> int:
    # 결과(result) 안에 edit_id 를 담아야 하는데 표가 불변이라 먼저 번호를 받는다
    return int(await conn.fetchval(
        "select nextval(pg_get_serial_sequence('card_fact_edits', 'edit_id'))"))


async def _insert_edit(conn, store_id: int, *, edit_id: int, card_id: int, req: FactEditRequest,
                       req_hash: str, to_version_id: int | None, owner_source_id: int | None,
                       owner_text: str | None, result: FactEditResult, actor_id: int) -> None:
    await conn.execute(
        "insert into card_fact_edits (store_id, edit_id, card_id, idempotency_key, request_hash, "
        "from_version_id, to_version_id, changed, owner_text_source_id, owner_text, result, "
        "actor_id) overriding system value "
        "values ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11::jsonb, $12)",
        store_id, edit_id, card_id, req.idempotency_key, req_hash, req.expected_version_id,
        to_version_id, to_version_id is not None, owner_source_id, owner_text,
        json.dumps(result.model_dump(mode="json"), ensure_ascii=False), actor_id)


async def _result(conn, store_id: int, card_id: int, *, edit_id: int, changed: bool,
                  revisions: Sequence[FactRevisionResult]) -> FactEditResult:
    row = await cards_repo.mutation_row(conn, store_id, card_id)
    return FactEditResult(
        card_id=int(row["card_id"]), review_status=row["review_status"],
        draft_version_id=row["draft_version_id"],
        published_version_id=row["published_version_id"], updated_at=row["updated_at"],
        changed=changed, edit_id=edit_id, revisions=list(revisions))


async def create_owner_edit_version(conn, store_id: int, card_id: int, *, title: str,
                                    content: str, actor_id: int) -> int:
    """새 OWNER_EDIT 초안 판 + 카드 초안 포인터·제목·본문을 한 문장으로 옮긴다(레거시 트리거 판 없음)."""
    title = title[:_TITLE_MAX]
    version_id = await conn.fetchval(
        "insert into card_versions "
        "(store_id, card_id, version_no, title, content, change_source, created_by) "
        "select $1, $2, coalesce(max(version_no), 0) + 1, $3, $4, 'OWNER_EDIT', $5 "
        "from card_versions where store_id = $1 and card_id = $2 "
        "returning version_id",
        store_id, card_id, title, content, actor_id)
    await conn.execute(
        "update knowledge_cards set title = $3, content = $4, draft_version_id = $5 "
        "where store_id = $1 and card_id = $2",
        store_id, card_id, title, content, version_id)
    return int(version_id)


async def _check_heads(conn, store_id: int, plan: EditPlan,
                       entity_id: int) -> dict[int, int]:
    """MODIFY 마다 쓸 head(expected). 읽기 화면과 같은 classify_head 판정.

    knowledge_facts 행이 없는 사실은 결과에 없다 — 편집 가능으로 보지 않고 다른 곳에서 바뀐 것으로 막는다.
    """
    pinned = {m.base.fact_id: m.base.fact_revision_id for m in plan.modifies}
    heads = await classify_head(conn, store_id, pinned, entity_id)
    expected: dict[int, int] = {}
    for m in plan.modifies:
        fid, rid = m.base.fact_id, m.base.fact_revision_id
        info = heads.get(fid)
        if info is None:
            raise EditError(409, "FACT_CHANGED_ELSEWHERE",
                            {"fact_id": fid, "fact_revision_id": rid, "head_revision_id": None})
        if info.edit_block == EDIT_BLOCK_MOVED:
            raise EditError(409, "FACT_MOVED_ENTITY", {"fact_id": fid, "fact_revision_id": rid})
        if info.edit_block is not None or info.editable_base is None:
            raise EditError(409, "FACT_CHANGED_ELSEWHERE",
                            {"fact_id": fid, "fact_revision_id": rid,
                             "head_revision_id": info.head_revision_id})
        expected[fid] = info.editable_base
    return expected


async def _identities(conn, store_id: int, revision_ids: Sequence[int]) -> dict[int, str]:
    rows = await conn.fetch(
        "select fact_revision_id, identity_key from fact_revision_meta "
        "where store_id = $1 and fact_revision_id = any($2::bigint[])",
        store_id, sorted(set(revision_ids)))
    return {int(r["fact_revision_id"]): r["identity_key"] for r in rows}


def _check_added_duplicates(adds: Sequence[PlannedAdd], entity_id: int, entity_name: str,
                            existing: Mapping[int, str]) -> None:
    """ADD 의 identity 가 최종 카드의 다른 사실(KEEP·MODIFY 결과·다른 ADD)과 같으면 422."""
    taken = set(existing.values())
    for a in adds:
        ident = identity_key(entity_id, add_shape(entity_name, a.fields))
        if ident in taken:
            raise EditError(422, "FACT_DUPLICATE_IN_CARD", {"ref": a.client_ref})
        taken.add(ident)


async def save_fact_edit(conn, store_id: int, *, card_id: int, actor_id: int,
                         req: FactEditRequest) -> FactEditResult:
    """사실 편집 저장. 호출자가 트랜잭션을 연다. 실패는 EditError(라우터가 ApiError 로)."""
    # 1. 잠금
    await lock_store_knowledge(conn, store_id)
    card = await cards_repo.get_card_for_update(conn, store_id, card_id)
    if card is None:
        raise EditError(404, "CARD_NOT_FOUND")
    if card["review_status"] == "EXCLUDED":
        raise EditError(409, "CARD_EXCLUDED")

    # 2. 멱등 — 버전 CAS 보다 먼저(성공 뒤 재시도가 충돌로 보이지 않게)
    req_hash = request_hash(req)
    prior = await conn.fetchrow(
        "select request_hash, result from card_fact_edits "
        "where store_id = $1 and card_id = $2 and idempotency_key = $3",
        store_id, card_id, req.idempotency_key)
    if prior is not None:
        if prior["request_hash"] != req_hash:
            raise EditError(409, "IDEMPOTENCY_CONFLICT")
        stored = prior["result"]
        return FactEditResult.model_validate(
            json.loads(stored) if isinstance(stored, str) else stored)

    # 3. 버전 CAS
    if card["draft_version_id"] != req.expected_version_id:
        raise EditError(409, "CARD_VERSION_CONFLICT",
                        {"current_version_id": card["draft_version_id"]})

    # 4. 상태·계획
    state = await load_card_fact_state(conn, store_id, card_id, int(card["draft_version_id"]))
    if state is None:
        raise EditError(409, "NOT_FACT_CARD")
    if state.entity_problem is not None or state.entity_id is None:
        raise EditError(409, "CARD_ENTITY_MOVED",
                        {"entity_problem": state.entity_problem or "MIXED_ENTITY"})
    plan = build_plan(state, req)
    entity_id = state.entity_id

    # 5. 바뀐 것 없음 — 편집 기록만
    if not plan.changed:
        edit_id = await _next_edit_id(conn)
        result = await _result(conn, store_id, card_id, edit_id=edit_id, changed=False,
                               revisions=())
        await _insert_edit(conn, store_id, edit_id=edit_id, card_id=card_id, req=req,
                           req_hash=req_hash, to_version_id=None, owner_source_id=None,
                           owner_text=None, result=result, actor_id=actor_id)
        return result

    # 6. MODIFY — head 판정을 모두 끝낸 뒤 쓴다
    expected = await _check_heads(conn, store_id, plan, entity_id)
    items = {i.fact_revision_id: i for b in req.blocks for i in b.items
             if isinstance(i, EditModify)}
    changes = {m.temp_id: modify_change(items[m.base.fact_revision_id], m.fields, m.base)
               for m in plan.modifies}
    id_map: dict[int, int] = {}
    for m in plan.modifies:
        try:
            id_map[m.temp_id] = await revise_fact(
                conn, store_id, fact_id=m.base.fact_id,
                expected_head_revision_id=expected[m.base.fact_id], change=changes[m.temp_id],
                change_kind="OWNER_CORRECTION", actor_id=actor_id, reason=CORRECTION_REASON)
        except (StaleFactRevision, LookupError):
            raise EditError(409, "FACT_CHANGED_ELSEWHERE",
                            {"fact_id": m.base.fact_id,
                             "fact_revision_id": m.base.fact_revision_id,
                             "head_revision_id": None}) from None

    # 7. ADD — 카드 안 같은 사실 검사 뒤 새 사실
    if plan.adds:
        existing = await _identities(conn, store_id,
                                     [*plan.kept_ids, *(id_map[m.temp_id] for m in plan.modifies)])
        _check_added_duplicates(plan.adds, entity_id, state.entity_name, existing)
    for a in plan.adds:
        shape = add_shape(state.entity_name, a.fields)
        fact_id, rev_id = await _create_fact(
            conn, store_id, entity_id=entity_id, shape=shape,
            slot=slot_key(entity_id, shape), ident=identity_key(entity_id, shape),
            change_kind="OWNER_ADD", reason=ADD_REASON, owner_answer_id=None,
            actor_id=actor_id)
        await _record_conflicts(conn, store_id, fact_id)
        id_map[a.temp_id] = rev_id

    # 8. 임시 id → 실제 판
    new_ids = set(id_map.values())
    real = await load_plan_facts(conn, store_id, [*new_ids, *plan.kept_ids])
    for m in plan.modifies:
        got, want = real[id_map[m.temp_id]], m.fields
        if (got.quantity_value, got.quantity_unit, got.value_text, got.polarity) != (
                want.quantity, want.unit, want.value_text, want.polarity):
            raise RuntimeError(f"새 판 값이 계획과 다르다 — 저장하지 않는다: 판 {got.fact_revision_id}")
    card_v, facts = plan.bind(id_map, real)

    # 9. 점주 입력 자료 + 새 판 occurrence (Q1-A)
    owner_source_id: int | None = None
    owner_text: str | None = None
    if new_ids:
        lines = owner_text_lines(card_v, new_ids)
        owner_text = "\n".join(_one_line(facts[rid].original_assertion) for _, rid, _ in lines)
        owner_source_id = int(await conn.fetchval(
            "insert into sources (store_id, uploaded_by, source_type, title, file_url, "
            "content_hash, status, processed_at) "
            "values ($1, $2, 'OWNER_TEXT', $3, null, null, 'DONE', now()) returning source_id",
            store_id, actor_id, OWNER_TEXT_TITLE.format(title=state.title)[:_TITLE_MAX]))
        digest = hashlib.sha256(owner_text.encode()).hexdigest()
        await conn.executemany(
            "insert into fact_occurrences (store_id, source_id, fact_revision_id, locator_type, "
            "locator, source_content_hash, disposition, reason, card_id, block_id, decided_by, "
            "decided_at) values ($1, $2, $3, 'LINE', $4::jsonb, $5, 'LINKED', null, $6, $7, $8, "
            "now())",
            [(store_id, owner_source_id, rid, json.dumps({"line": n}), digest, card_id,
              block_id, actor_id) for n, rid, block_id in lines])

    # 10. 근거·본문
    revisions = card_v.fact_revision_ids()
    provenance = await provenance_for(conn, store_id, revisions)
    no_origin = [r for r in revisions if not provenance.get(r)]
    if any(r in new_ids for r in no_origin):
        raise RuntimeError(f"새 판에 근거가 없다 — 저장하지 않는다: {sorted(no_origin)[:5]}")
    origins: list[Origin] = [o for r in revisions for o in provenance.get(r, ())]
    source_ids = sorted({o.source_id for o in origins if o.source_id is not None})
    names: dict[int, str] = {}
    if source_ids:
        for r in await conn.fetch(
                "select source_id, title, source_type from sources "
                "where store_id = $1 and source_id = any($2::bigint[])", store_id, source_ids):
            names[int(r["source_id"])] = (r["title"] or "").strip() or f"{r['source_type']} 자료"
    content = card_plan.render_card(card_v, facts,
                                    evidence=[names[s] for s in source_ids if s in names])
    missing = card_plan.render_missing(card_v, facts, content)
    if missing:
        raise RuntimeError(f"렌더링이 사실을 빠뜨렸다 — 저장하지 않는다: 판 {missing[:5]}")

    # 11. 새 카드 판·고정·근거·레거시
    version_id = await create_owner_edit_version(conn, store_id, card_id, title=state.title,
                                                 content=content, actor_id=actor_id)
    await pin_card_version(conn, store_id, version_id, card_v, provenance)
    await write_version_evidence(
        conn, store_id, version_id, origins,
        excerpts={owner_source_id: owner_text} if owner_source_id is not None else None)
    fact_ids = sorted({facts[r].fact_id for r in revisions})
    confidence = {int(r["fact_id"]): float(r["confidence"] or 0) for r in await conn.fetch(
        "select l.fact_id, max(sf.confidence) as confidence "
        "from source_fact_revision_links l "
        "join source_facts sf on sf.store_id = l.store_id and sf.fact_id = l.source_fact_id "
        "where l.store_id = $1 and l.fact_id = any($2::bigint[]) group by l.fact_id",
        store_id, fact_ids)}
    await replace_legacy_facts(conn, store_id, card_id, revisions, facts, state.entity_name,
                               confidence)

    # 12. 처분 — 이 카드를 가리키는 LINKED 행만
    deleted_fact_ids = sorted({p.fact.fact_id for p in state.pinned
                               if p.fact.fact_revision_id in set(plan.deleted_ids)}
                              - set(fact_ids))
    for fid in deleted_fact_ids:
        other = await conn.fetchrow(
            "select k.card_id, bf.block_id from knowledge_cards k "
            "join card_block_facts bf on bf.store_id = k.store_id "
            "  and bf.card_version_id = k.draft_version_id "
            "join card_version_blocks b on b.store_id = bf.store_id "
            "  and b.card_version_id = bf.card_version_id and b.block_id = bf.block_id "
            "join fact_revisions r on r.store_id = bf.store_id "
            "  and r.fact_revision_id = bf.fact_revision_id "
            "where k.store_id = $1 and k.card_id <> $2 and k.review_status <> 'EXCLUDED' "
            "  and r.fact_id = $3 "
            "order by k.card_id, b.block_order, bf.position limit 1",
            store_id, card_id, fid)
        if other is not None:
            await conn.execute(
                "update fact_occurrences o set card_id = $4, block_id = $5 "
                "from fact_revisions r "
                "where o.store_id = $1 and r.store_id = o.store_id "
                "  and r.fact_revision_id = o.fact_revision_id and r.fact_id = $3 "
                "  and o.disposition = 'LINKED' and o.card_id = $2",
                store_id, card_id, fid, int(other["card_id"]), other["block_id"])
        else:
            await conn.execute(
                "update fact_occurrences o set disposition = 'EXCLUDED', reason = $4, "
                "card_id = null, block_id = null, decided_by = $5, decided_at = now() "
                "from fact_revisions r "
                "where o.store_id = $1 and r.store_id = o.store_id "
                "  and r.fact_revision_id = o.fact_revision_id and r.fact_id = $3 "
                "  and o.disposition = 'LINKED' and o.card_id = $2",
                store_id, card_id, fid, REASON_OWNER_REMOVED, actor_id)
    blocks = first_blocks(card_v, facts)
    order = sorted(blocks)
    await conn.execute(
        "update fact_occurrences o set block_id = p.block_id "
        "from fact_revisions r, unnest($3::bigint[], $4::varchar[]) as p(fact_id, block_id) "
        "where o.store_id = $1 and r.store_id = o.store_id "
        "  and r.fact_revision_id = o.fact_revision_id and r.fact_id = p.fact_id "
        "  and o.disposition = 'LINKED' and o.card_id = $2",
        store_id, card_id, order, [blocks[f] for f in order])

    # 13. 검수 상태 (D-16) — APPROVED 는 그대로
    from_status = card["review_status"]
    if from_status in ("PENDING", "NEEDS_REVIEW"):
        open_conflict = bool(await conn.fetchval(
            "select exists (select 1 from fact_conflicts where store_id = $1 "
            "and status = 'OPEN' and (fact_id_low = any($2::bigint[]) "
            "or fact_id_high = any($2::bigint[])))", store_id, fact_ids))
        reason = card_review_reason(missing_provenance=bool(no_origin), model_error=None,
                                    open_conflict=open_conflict)
        await conn.execute(
            "update knowledge_cards set review_status = $3, needs_review_reason = $4 "
            "where store_id = $1 and card_id = $2 "
            "and review_status in ('PENDING','NEEDS_REVIEW')",
            store_id, card_id, "NEEDS_REVIEW" if reason else "PENDING", reason)

    # 14. 사건·편집 기록
    edit_id = await _next_edit_id(conn)
    result_revisions = [
        FactRevisionResult(op="MODIFY", base_fact_revision_id=m.base.fact_revision_id,
                           fact_revision_id=id_map[m.temp_id])
        for m in plan.modifies
    ] + [FactRevisionResult(op="ADD", client_ref=a.client_ref, fact_revision_id=id_map[a.temp_id])
         for a in plan.adds]
    # 요청 순서(임시 id -1, -2, …)
    temp_of = {id_map[m.temp_id]: m.temp_id for m in plan.modifies}
    temp_of.update({id_map[a.temp_id]: a.temp_id for a in plan.adds})
    result_revisions.sort(key=lambda r: -temp_of[r.fact_revision_id])
    result = await _result(conn, store_id, card_id, edit_id=edit_id, changed=True,
                           revisions=result_revisions)
    await cards_repo.add_event(
        conn, store_id, card_id, actor_id, "EDIT_DRAFT",
        from_status=from_status, to_status=result.review_status,
        metadata={"kind": "FACT_EDIT", "edit_id": edit_id,
                  "from_version_id": req.expected_version_id, "to_version_id": version_id,
                  "added": len(plan.adds), "modified": len(plan.modifies),
                  "deleted": len(plan.deleted_ids), "steps_reordered": plan.steps_reordered,
                  "display_reordered": plan.display_reordered})
    await _insert_edit(conn, store_id, edit_id=edit_id, card_id=card_id, req=req,
                       req_hash=req_hash, to_version_id=version_id,
                       owner_source_id=owner_source_id, owner_text=owner_text, result=result,
                       actor_id=actor_id)
    logger.info("W3b 사실 편집 store=%s card=%s 판 %s → %s · 수정 %d 추가 %d 삭제 %d",
                store_id, card_id, req.expected_version_id, version_id, len(plan.modifies),
                len(plan.adds), len(plan.deleted_ids))
    return result
