"""실제 DB: W3a 대상 단위 사실 조립 합성 종단 검증. 모델은 합성 대역이다(비용 0).

verify_w_publication_flow.verify() 끝에서 부른다(verify_r_schema_rebuild 가 부르는 W 검증).
시나리오마다 새 합성 매장을 만든다. 사실 원장은 verify_w3_flag_readiness._process 로 만든다
(W2 두 플래그 켬, 옛 조립 대역).
  L1 대상 단위 입력 — 두 자료의 같은 대상 사실이 한 묶음으로, 규격 미해결 판은 뺀다
  L2 병합 뒤 입력 — 살아 있는 대상만, RELINK head, 선행이 fact_id 로 그대로 풀린다
  L3 격리 — 다른 매장 id 로 부르면 빈 결과
  L4 사실 조립 호출 기록 — 원래 응답(ASSEMBLE·plan0)·원가 시도, 같은 입력 재사용
  P1~P12 카드 판·블록·근거 고정과 occurrence 처분(fact_cards). 원장은 _persist_ledger 로 직접
    만들어 옛 조립 카드를 만들지 않는다
  E1~E12 파이프라인 연결 종단 — process_source·job_worker 를 합성 대역으로 돌린다(플래그 켬/끔)
  B1~B7 공개판에 사실 싣기 — 레거시 판 불변, 사실 블록·사실 판·근거·실제 대상 id, R 검색·답변 소비,
    재공개 결정성, 점주 편집 판, 근거 없음·대상 불일치 거절
출력 줄 머리는 `PASS W3a <시나리오 id> <설명>`.
"""
import hashlib
import json
from contextlib import ExitStack, contextmanager
from decimal import Decimal
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

import asyncpg

import app.config
from app.cards import repository as cards_repo
from app.config import Settings
from app.contracts.common import Quantity, Variant
from app.contracts.usage import UsageContext
from app.ingest import (card_plan, entities, extract, fact_assembly, fact_cards, job_worker,
                        pipeline)
from app.ingest import repository as repo
from app.ingest.card_plan import ProposedBlock, ProposedCard, fact_sort_key
from app.ingest.fact_revisions import FactChange, revise_fact
from app.ingest.entities import find_entity_by_alias
from app.ingest.entity_admin import merge_entities
from app.ingest.entity_names import normalize_alias
from app.ingest.extract import gemini, mock
from app.ingest.raw_responses import DbRawResponseSink
from app.ingest.reuse import CACHE_STATE_REUSED
from app.ingest.schemas import (CardPlanBatch, ExtractedAssertion, ExtractedCard, ExtractedFact,
                                ExtractionResult, FactExtractionResult, PlannedBlock, PlannedCard)
from app.learn.answer_storage import save_answer
from app.learn.planner import decide
from app.publish.approval import CardChange, publish_cards
from app.reg.hybrid import hybrid_search, read_current_index
from app.usage.recorder import DbUsageSink
from verify_w3_flag_readiness import _process
from verify_w_entity_revision import _MODEL_SETTINGS, _fact, _new_owner_answer, _w2_counts
from verify_w_partial_extraction import _new_source, _seed

Z, B = "음료Z", "합성음료B"


def _checker(scenario: str):
    def check(name: str, ok: bool) -> None:
        assert ok, f"W3a {scenario} {name}"
        print(f"PASS W3a {scenario} {name}")
    return check


async def _revision_of(db, store, source, attribute):
    """원장 사실 → 이어진 사실의 fact_id·head 판."""
    return await db.fetchrow(
        "select k.fact_id, k.head_revision_id from source_facts f "
        "join source_fact_revision_links l on l.store_id = f.store_id "
        "  and l.source_fact_id = f.fact_id "
        "join knowledge_facts k on k.store_id = l.store_id and k.fact_id = l.fact_id "
        "where f.store_id=$1 and f.source_id=$2 and f.attribute=$3 "
        "order by f.fact_id limit 1", store, source, attribute)


async def _store_with_z(db, pool, *, run_tag):
    """자료 A(ICE 물·단계 1·2)와 자료 B(HOT 물·디카페인)를 처리한 합성 매장."""
    user, s, job = await _seed(db)
    src_a = await _new_source(db, s, user, "SCAN")
    await _process(db, pool, s, user, src_a, [("합성 자료 본문 A", [
        _fact("f1", Z, "물", "225", "ml", variant="ICE"),
        _fact("f2", Z, "얼음 담기", "컵에 얼음", variant="ICE", order=1),
        _fact("f3", Z, "샷 붓기", "샷을 붓는다", variant="ICE", order=2, requires=["f2"]),
    ])], run_tag=run_tag)
    src_b = await _new_source(db, s, user, "SCAN")
    await _process(db, pool, s, user, src_b, [("합성 자료 본문 B", [
        _fact("f1", "음료 Z", "물", "275", "ml", variant="HOT"),
        _fact("f2", Z, "카페인", "줄임", variant="디카페인"),
    ])], run_tag=run_tag + 1)
    z = await find_entity_by_alias(db, s, normalize_alias(Z))
    return NS(user=user, store=s, job=job, src_a=src_a, src_b=src_b, z=z)


async def _l1(db, pool):
    check = _checker("L1")
    w = await _store_with_z(db, pool, run_tag=701)
    on_a = await fact_assembly.entities_for_source(db, w.store, w.src_a)
    on_b = await fact_assembly.entities_for_source(db, w.store, w.src_b)
    check("대상 단위 — 두 자료 모두 음료Z 대상 하나", w.z is not None and on_a == on_b == [w.z])
    loaded = await fact_assembly.load_entity_groups(db, w.store, [w.z])
    water_ice = await _revision_of(db, w.store, w.src_a, "물")
    step1 = await _revision_of(db, w.store, w.src_a, "얼음 담기")
    step2 = await _revision_of(db, w.store, w.src_a, "샷 붓기")
    water_hot = await _revision_of(db, w.store, w.src_b, "물")
    decaf = await _revision_of(db, w.store, w.src_b, "카페인")
    check("묶음 하나", len(loaded.groups) == 1 and loaded.groups[0].entity_id == w.z)
    group = loaded.groups[0]
    ids = [f.fact_revision_id for f in group.facts]
    check("A·B 사실(디카페인 제외) 넷이 fact_sort_key 순",
          ids == [water_hot["head_revision_id"], step1["head_revision_id"],
                  step2["head_revision_id"], water_ice["head_revision_id"]]
          and list(group.facts) == sorted(group.facts, key=fact_sort_key))
    by_id = {f.fact_revision_id: f for f in group.facts}
    check("수치는 Decimal — 275·225",
          by_id[water_hot["head_revision_id"]].quantity_value == Decimal("275")
          and isinstance(by_id[water_ice["head_revision_id"]].quantity_value, Decimal)
          and by_id[water_ice["head_revision_id"]].quantity_value == Decimal("225"))
    check("단계 2 의 선행 = (단계 1 의 fact_id,)",
          by_id[step2["head_revision_id"]].requires_fact_ids == (step1["fact_id"],)
          and by_id[step2["head_revision_id"]].step_order == 2)
    check("디카페인 판은 held — VARIANT_UNRESOLVED",
          [(h.fact_revision_id, h.reason) for h in loaded.held]
          == [(decaf["head_revision_id"], fact_assembly.REASON_VARIANT_UNRESOLVED)])
    return w, group


async def _l2(db, pool):
    check = _checker("L2")
    w = await _store_with_z(db, pool, run_tag=711)
    src_c = await _new_source(db, w.store, w.user, "SCAN")
    await _process(db, pool, w.store, w.user, src_c, [("합성 자료 본문 C", [
        _fact("f1", B, "컵 준비", "컵을 꺼낸다", order=1),
        _fact("f2", B, "시럽 넣기", "시럽을 넣는다", order=2, requires=["f1"]),
    ])], run_tag=713)
    b = await find_entity_by_alias(db, w.store, normalize_alias(B))
    cup = await _revision_of(db, w.store, src_c, "컵 준비")
    syrup = await _revision_of(db, w.store, src_c, "시럽 넣기")
    check("병합 전 — 자료 C 는 합성음료B 대상",
          await fact_assembly.entities_for_source(db, w.store, src_c) == [b] and b != w.z)
    await merge_entities(db, w.store, keep_entity_id=w.z, merged_entity_id=b,
                         actor_id=w.user, candidate_id=None)
    check("병합 뒤 — 자료 C 의 대상은 살아 있는 음료Z 하나",
          await fact_assembly.entities_for_source(db, w.store, src_c) == [w.z])
    loaded = await fact_assembly.load_entity_groups(db, w.store, [w.z, b])
    check("묶음은 살아 있는 대상 하나", [g.entity_id for g in loaded.groups] == [w.z])
    group = loaded.groups[0]
    moved = {f.fact_id: f for f in group.facts if f.fact_id in (cup["fact_id"], syrup["fact_id"])}
    heads = {r["fact_id"]: r for r in await db.fetch(
        "select k.fact_id, k.head_revision_id, m.change_kind from knowledge_facts k "
        "join fact_revision_meta m on m.store_id = k.store_id "
        "  and m.fact_revision_id = k.head_revision_id "
        "where k.store_id=$1 and k.fact_id = any($2::bigint[])",
        w.store, [cup["fact_id"], syrup["fact_id"]])}
    check("옮긴 두 사실 — 묶음의 판이 RELINK head",
          set(moved) == set(heads)
          and all(moved[k].fact_revision_id == heads[k]["head_revision_id"]
                  and heads[k]["change_kind"] == "RELINK" for k in heads)
          and all(moved[k].fact_revision_id != r["head_revision_id"]
                  for k, r in ((cup["fact_id"], cup), (syrup["fact_id"], syrup))))
    check("묶음의 판 모두 entity_id == 음료Z", all(f.entity_id == w.z for f in group.facts))
    check("선행이 fact_id 로 그대로 풀린다",
          moved[syrup["fact_id"]].requires_fact_ids == (cup["fact_id"],))


async def _l3(db, pool, w):
    check = _checker("L3")
    _, other, _ = await _seed(db)
    tables = ("knowledge_facts", "fact_revisions", "knowledge_entities",
              "source_fact_revision_links")

    async def counts(store):
        return {t: await db.fetchval(f"select count(*) from {t} where store_id=$1", store)
                for t in tables}

    before = await counts(other)
    on_other = await fact_assembly.entities_for_source(db, other, w.src_a)
    loaded = await fact_assembly.load_entity_groups(db, other, [w.z])
    check("다른 매장 id → 대상 없음·묶음 없음·held 없음",
          on_other == [] and loaded.groups == () and loaded.held == ())
    check("그 매장 행 수 불변", await counts(other) == before)


async def _l4(db, pool, w, group):
    check = _checker("L4")
    model_calls = []

    async def fake_call(prompt, media, schema=None, max_output_tokens=None):
        assert schema is CardPlanBatch, schema
        model_calls.append(prompt)
        entities = json.loads(prompt.split(fact_assembly.PLAN_INPUT_MARKER, 1)[1])
        body = mock._planned(entities, categories)
        return gemini.CallResult(body.model_dump_json(), {}, "STOP")

    categories = list(await repo.enabled_categories(db, w.store))
    model_settings = NS(**vars(_MODEL_SETTINGS), extract_reuse_enabled=True)
    settings = Settings(_env_file=None, w_entity_revision_enabled=True,
                        w_upload_proposals_enabled=True)

    async def run(base):
        with ExitStack() as stack:
            for obj, name, replacement in [
                (app.config, "get_settings", lambda: settings),
                (extract, "get_settings", lambda: NS(ingest_mode="real")),
                (gemini, "get_settings", lambda: model_settings),
                (gemini, "_call", fake_call),
            ]:
                stack.enter_context(patch.object(obj, name, replacement))
            return await fact_assembly.plan_entities(
                source_id=w.src_a, groups=[group], categories=categories, glossary=[],
                usage_sink=DbUsageSink(pool), raw_sink=DbRawResponseSink(pool),
                context_for=lambda i: pipeline._ctx_for(
                    base, w.src_a, "ASSEMBLE", segment_id=f"plan{i}"),
                strict=True)

    async def raw_rows():
        return await db.fetchval(
            "select count(*) from extraction_raw_responses where store_id=$1 "
            "and stage='ASSEMBLE' and segment_id='plan0'", w.store)

    async def attempts():
        return await db.fetch(
            "select cache_state, status from ai_usage_attempts where store_id=$1 "
            "and stage='ASSEMBLE' and segment_id='plan0' order by usage_attempt_id", w.store)

    first = await run((w.store, None, "REGISTRATION", "PRODUCT", None, None))
    check("호출 1회 — 배치 1·실패 0·제안 있음",
          len(model_calls) == 1 and first.batch_count == 1 and first.failed_entity_ids == ()
          and len(first.proposals.get(w.z, ())) == 1)
    check("원래 응답 ASSEMBLE·plan0 1행", await raw_rows() == 1)
    rows = await attempts()
    check("원가 시도 1행(SUCCEEDED)", len(rows) == 1 and rows[0]["status"] == "SUCCEEDED")
    # 같은 입력 — 재사용 키는 논리 호출 ID 와 무관하다. 원가 원장 unique(논리 호출·시도 번호)를
    # 피하려고 두 번째는 작업 범위 문맥으로 부른다
    second = await run((w.store, w.job, "REGISTRATION", "PRODUCT", None, 2))
    check("같은 입력 다시 → 재사용(모델 대역 호출 수 그대로)·제안 같음",
          len(model_calls) == 1 and second.proposals == first.proposals)
    rows = await attempts()
    check("원래 응답 행 그대로 1, 재사용 시도는 REUSED 로 남는다",
          await raw_rows() == 1 and len(rows) == 2 and rows[1]["cache_state"] == CACHE_STATE_REUSED)


# ── P: 카드 판·블록·근거 고정과 occurrence 처분 (fact_cards) ────────────────

def _assertion(ref, subject, attribute, value, unit="", *, variant="", order=0, requires=(),
               neg=False, conditions=(), exceptions=(), ts=0):
    a = _fact(ref, subject, attribute, value, unit, variant=variant, order=order,
              requires=requires, ts=ts)
    a.update(polarity="NEGATE" if neg else "AFFIRM", conditions=list(conditions),
             exceptions=list(exceptions))
    return a


async def _ledger(db, store, source, facts, *, title=None):
    """원장만 만든다(카드 없음). W2 연결로 대상·판·REVIEW_PENDING occurrence 가 생긴다."""
    if title is not None:
        await db.execute("update sources set title=$3 where store_id=$1 and source_id=$2",
                         store, source, title)
    settings = Settings(_env_file=None, w_entity_revision_enabled=True)
    assertions = [ExtractedAssertion.model_validate(f) for f in facts]
    with patch.object(app.config, "get_settings", lambda: settings):
        async with db.transaction():
            await pipeline._persist_ledger(db, store, source, "SCAN", assertions)


async def _entity(db, store, name):
    return await find_entity_by_alias(db, store, normalize_alias(name))


async def _plan(db, store, entity_id, proposals=None):
    """대상 묶음 → 합성 계획(mock._planned) → 서버 검증. proposals 를 주면 그것으로 검증한다."""
    loaded = await fact_assembly.load_entity_groups(db, store, [entity_id])
    group = next(g for g in loaded.groups if g.entity_id == entity_id)
    if proposals is None:
        batch = fact_assembly.build_plan_batches([group], limit=200)[0]
        found, _ = fact_assembly.proposals_from_output(
            batch, mock._planned(batch.payload, ["레시피"]))
        proposals = found[entity_id]
    return group, card_plan.plan_entity(group, proposals)


async def _write(db, store, source, job, group, result, state=None):
    """한 트랜잭션 + 매장 지식 잠금 안에서 상태 판정·쓰기."""
    async with db.transaction():
        await entities.lock_store_knowledge(db, store)
        if state is None:
            state = await fact_cards.entity_card_state(db, store, group.entity_id)
        categories = await repo.enabled_categories(db, store)
        written = await fact_cards.write_entity_cards(
            db, store, source_id=source, job_id=job, category_version=1, categories=categories,
            state=state, group=group, result=result)
    return state, written


async def _pins(db, store, version_id):
    """판에 고정된 블록·블록 사실·근거 행."""
    blocks = [tuple(r) for r in await db.fetch(
        "select block_id, kind, block_order, raw_span_id from card_version_blocks "
        "where store_id=$1 and card_version_id=$2 order by block_order", store, version_id)]
    facts = [tuple(r) for r in await db.fetch(
        "select block_id, fact_revision_id, position from card_block_facts "
        "where store_id=$1 and card_version_id=$2 order by block_id, position", store, version_id)]
    prov = [tuple(r) for r in await db.fetch(
        "select fact_revision_id, occurrence_id, owner_answer_id from card_version_fact_provenance "
        "where store_id=$1 and card_version_id=$2 order by provenance_id", store, version_id)]
    return blocks, facts, prov


def _expected_pins(card):
    blocks = [(b.block_id, b.kind, b.order, None) for b in card.blocks]
    facts = sorted((b.block_id, rid, pos) for b in card.blocks
                   for pos, rid in enumerate(b.fact_revision_ids, start=1))
    return blocks, facts


async def _occurrences_of(db, store, revision_ids):
    """판들의 EXCLUDED 아닌 occurrence → {(판, occurrence)}."""
    return {(r["fact_revision_id"], r["occurrence_id"]) for r in await db.fetch(
        "select fact_revision_id, occurrence_id from fact_occurrences where store_id=$1 "
        "and fact_revision_id = any($2::bigint[]) and disposition <> 'EXCLUDED'",
        store, list(revision_ids))}


async def _card(db, store, card_id):
    return await db.fetchrow(
        "select card_id, entity_id, source_id, origin_job_id, review_status, needs_review_reason, "
        "title, content, draft_version_id, published_version_id from knowledge_cards "
        "where store_id=$1 and card_id=$2", store, card_id)


async def _versions(db, store, card_id):
    return await db.fetch(
        "select version_id, version_no, change_source, title, content from card_versions "
        "where store_id=$1 and card_id=$2 order by version_no", store, card_id)


async def _source_occurrences(db, store, source):
    return await db.fetch(
        "select o.occurrence_id, o.fact_revision_id, r.fact_id, o.disposition, o.reason, "
        "o.card_id, o.block_id from fact_occurrences o "
        "left join fact_revisions r on r.store_id = o.store_id "
        "  and r.fact_revision_id = o.fact_revision_id "
        "where o.store_id=$1 and o.source_id=$2 order by o.occurrence_id", store, source)


def _first_block(card, facts):
    """fact_id → 카드 안 첫 블록 id."""
    out: dict[int, str] = {}
    for b in card.blocks:
        for rid in b.fact_revision_ids:
            out.setdefault(facts[rid].fact_id, b.block_id)
    return out


async def _legacy_counts(db, store, card_id):
    facts = await db.fetchval(
        "select count(*) from facts f join knowledge_cards k on k.card_id = f.card_id "
        "where k.store_id=$1 and k.card_id=$2", store, card_id)
    links = await db.fetchval(
        "select count(*) from card_facts where store_id=$1 and card_id=$2", store, card_id)
    evidence = await db.fetchval(
        "select count(*) from card_evidence e join knowledge_cards k on k.store_id = e.store_id "
        "where k.store_id=$1 and k.card_id=$2 and e.version_id in "
        "(select version_id from card_versions where store_id=$1 and card_id=$2)",
        store, card_id)
    return facts, links, evidence


async def _store_p1(db):
    """자료 A — 음료Z ICE 물·ICE 단계 1·2(2 가 1 선행·조건)·규격 없는 부정(예외)."""
    user, s, job = await _seed(db)
    src_a = await _new_source(db, s, user, "SCAN")
    await _ledger(db, s, src_a, [
        _assertion("f1", Z, "물", "225", "ml", variant="ICE"),
        _assertion("f2", Z, "얼음 담기", "컵에 얼음", variant="ICE", order=1),
        _assertion("f3", Z, "샷 붓기", "샷을 붓는다", variant="ICE", order=2, requires=["f2"],
                   conditions=["얼음이 녹기 전"]),
        _assertion("f4", Z, "시럽", "넣지 않는다", neg=True, exceptions=["손님 요청 시"]),
    ], title="합성 자료 A")
    return NS(user=user, store=s, job=job, src_a=src_a, z=await _entity(db, s, Z))


async def _p1(db):
    check = _checker("P1")
    w = await _store_p1(db)
    group, result = await _plan(db, w.store, w.z)
    check("계획 — 카드 1·모델 계획 통과", len(result.cards) == 1 and result.model_error is None)
    state, written = await _write(db, w.store, w.src_a, w.job, group, result)
    check("상태 NEW", state.mode == "NEW" and state.card_ids == () and state.reason is None)
    card = result.cards[0]
    facts = {f.fact_revision_id: f for f in group.facts}
    card_id = written.card_ids[0]
    row = await _card(db, w.store, card_id)
    check("카드 1 — 대상·자료·작업·PENDING·검수 사유 없음",
          len(written.card_ids) == 1 and row["entity_id"] == w.z and row["source_id"] == w.src_a
          and row["origin_job_id"] == w.job and row["review_status"] == "PENDING"
          and row["needs_review_reason"] is None)
    check("제목 — 규격이 섞여 '음료Z'", row["title"] == Z == card.title)
    versions = await _versions(db, w.store, card_id)
    check("판 1 EXTRACTION·초안 포인터",
          len(versions) == 1 and versions[0]["change_source"] == "EXTRACTION"
          and row["draft_version_id"] == versions[0]["version_id"]
          and written.new_version_ids == (versions[0]["version_id"],))
    expected = card_plan.render_card(card, facts, evidence=["합성 자료 A"])
    check("본문 == render_card(근거 줄 포함)",
          row["content"] == versions[0]["content"] == expected
          and expected.endswith("근거: 합성 자료 A"))
    blocks, block_facts, prov = await _pins(db, w.store, row["draft_version_id"])
    exp_blocks, exp_facts = _expected_pins(card)
    check("블록·블록 사실이 계획과 같다", blocks == exp_blocks and block_facts == exp_facts)
    occ = await _occurrences_of(db, w.store, card.fact_revision_ids())
    check("근거 행 — 판마다 그 판의 occurrence",
          {(r, o) for r, o, _ in prov} == occ and len(prov) == len(occ) == 4
          and all(a is None for _, _, a in prov))
    legacy_facts, links, evidence = await _legacy_counts(db, w.store, card_id)
    check("card_evidence 1·레거시 facts = 사실 수", evidence == 1 and legacy_facts == 4)
    ledger = {r["fact_id"] for r in await db.fetch(
        "select fact_id from source_facts where store_id=$1 and source_id=$2", w.store, w.src_a)}
    linked = {r["fact_id"] for r in await db.fetch(
        "select fact_id from card_facts where store_id=$1 and card_id=$2", w.store, card_id)}
    check("card_facts 가 자료 A 원장 사실을 잇는다", linked == ledger and links == 4)
    first = _first_block(card, facts)
    rows = await _source_occurrences(db, w.store, w.src_a)
    check("자료 A occurrence 전부 LINKED(카드·첫 블록)",
          rows and all(r["disposition"] == "LINKED" and r["reason"] is None
                       and r["card_id"] == card_id and r["block_id"] == first[r["fact_id"]]
                       and r["block_id"].startswith("b") for r in rows))
    states = {r["assembly_state"] for r in await db.fetch(
        "select assembly_state from source_facts where store_id=$1 and source_id=$2",
        w.store, w.src_a)}
    check("원장 assembly_state = LINKED", states == {"LINKED"})
    check("계약 CardPlan 통과", card.to_card_plan().entity_id == str(w.z))
    check("WrittenEntity 사실 = 대상 사실",
          written.linked_fact_ids == tuple(await fact_cards.entity_fact_ids(db, w.store, w.z)))
    return w, card_id


async def _p2_p3(db, w, card_id):
    check = _checker("P2")
    v1 = (await _card(db, w.store, card_id))["draft_version_id"]
    pins_v1 = await _pins(db, w.store, v1)
    src_b = await _new_source(db, w.store, w.user, "SCAN")
    await _ledger(db, w.store, src_b, [_assertion("f1", "음료 Z", "물", "275", "ml",
                                                  variant="HOT")], title="합성 자료 B")
    w.src_b = src_b
    group, result = await _plan(db, w.store, w.z)
    state, written = await _write(db, w.store, src_b, w.job, group, result)
    check("상태 REASSEMBLE(P1 카드)", state.mode == "REASSEMBLE" and state.card_ids == (card_id,))
    row = await _card(db, w.store, card_id)
    versions = await _versions(db, w.store, card_id)
    check("같은 카드·판 2 EXTRACTION·초안 포인터 판 2",
          written.card_ids == (card_id,) and len(versions) == 2
          and versions[1]["version_no"] == 2 and versions[1]["change_source"] == "EXTRACTION"
          and row["draft_version_id"] == versions[1]["version_id"]
          and written.new_version_ids == (versions[1]["version_id"],))
    check("판 1 의 블록·블록 사실·근거 그대로", await _pins(db, w.store, v1) == pins_v1)
    card = result.cards[0]
    facts = {f.fact_revision_id: f for f in group.facts}
    hot = await _revision_of(db, w.store, src_b, "물")
    check("판 2 에 자료 B 사실·근거 줄에 두 자료",
          hot["head_revision_id"] in card.fact_revision_ids()
          and row["content"] == card_plan.render_card(
              card, facts, evidence=["합성 자료 A", "합성 자료 B"])
          and row["content"].endswith("근거: 합성 자료 A, 합성 자료 B"))
    blocks, block_facts, _ = await _pins(db, w.store, row["draft_version_id"])
    check("판 2 블록 고정이 계획과 같다", (blocks, block_facts) == _expected_pins(card))
    legacy_facts, _, _ = await _legacy_counts(db, w.store, card_id)
    check("레거시 facts 가 새 사실 수(5)로 교체", legacy_facts == 5)
    first = _first_block(card, facts)
    rows = [*await _source_occurrences(db, w.store, w.src_a),
            *await _source_occurrences(db, w.store, src_b)]
    check("A·B occurrence 모두 판 2 블록으로 LINKED",
          all(r["disposition"] == "LINKED" and r["card_id"] == card_id
              and r["block_id"] == first[r["fact_id"]] for r in rows))

    check = _checker("P3")

    async def counts():
        return (len(await _versions(db, w.store, card_id)),
                await _pins(db, w.store, (await _card(db, w.store, card_id))["draft_version_id"]),
                await _legacy_counts(db, w.store, card_id))

    before = await counts()
    group, result = await _plan(db, w.store, w.z)
    state, again = await _write(db, w.store, src_b, w.job, group, result)
    check("같은 입력 다시 — REASSEMBLE·새 판 없음",
          state.mode == "REASSEMBLE" and again.new_version_ids == ()
          and again.card_ids == (card_id,))
    check("판 수·블록·근거·card_facts·facts·card_evidence 그대로", await counts() == before)


async def _fresh_written(db, *, title="합성 자료"):
    """새 매장 — 음료Z 물·단계 하나를 NEW 로 쓴 카드."""
    user, s, job = await _seed(db)
    src = await _new_source(db, s, user, "SCAN")
    await _ledger(db, s, src, [
        _assertion("f1", Z, "물", "225", "ml", variant="ICE"),
        _assertion("f2", Z, "얼음 담기", "컵에 얼음", variant="ICE", order=1),
    ], title=title)
    z = await _entity(db, s, Z)
    group, result = await _plan(db, s, z)
    _, written = await _write(db, s, src, job, group, result)
    return NS(user=user, store=s, job=job, src=src, z=z, card=written.card_ids[0])


async def _p4(db, w, card_id):
    check = _checker("P4")
    await db.execute("update knowledge_cards set review_status='APPROVED' "
                     "where store_id=$1 and card_id=$2", w.store, card_id)
    approved = await _card(db, w.store, card_id)
    state = await fact_cards.entity_card_state(db, w.store, w.z)
    check("(a) 승인(공개 포인터) → DEFER",
          approved["published_version_id"] is not None and state.mode == "DEFER"
          and state.card_ids == (card_id,) and state.reason == fact_cards.REASON_EXISTING_CARD)

    f = await _fresh_written(db)
    check("새 매장 — 자동 사실 카드면 REASSEMBLE",
          (await fact_cards.entity_card_state(db, f.store, f.z)).mode == "REASSEMBLE")
    await db.execute("update knowledge_cards set assignment_type='MANUAL' "
                     "where store_id=$1 and card_id=$2", f.store, f.card)
    state = await fact_cards.entity_card_state(db, f.store, f.z)
    check("(b) 수동 배정 → DEFER", state.mode == "DEFER" and state.card_ids == (f.card,))

    f = await _fresh_written(db)
    row = await _card(db, f.store, f.card)
    await cards_repo.create_draft(db, f.store, f.card, title=row["title"],
                                  content=row["content"] + " 점주 보탬", actor_id=f.user,
                                  source_version_id=row["draft_version_id"])
    state = await fact_cards.entity_card_state(db, f.store, f.z)
    check("(c) 점주 편집 초안 → DEFER", state.mode == "DEFER" and state.card_ids == (f.card,))

    user, s, _ = await _seed(db)
    src = await _new_source(db, s, user, "SCAN")
    await _ledger(db, s, src, [_assertion("f1", Z, "물", "225", "ml", variant="ICE")])
    z = await _entity(db, s, Z)
    other = (await repo.enabled_categories(db, s))["기타"]
    legacy = await repo.insert_card(db, s, category_id=other, source_id=src, title="레거시 카드",
                                    content="레거시 본문", confidence=50, entity_id=z)
    state = await fact_cards.entity_card_state(db, s, z)
    check("(d) 블록 없는 레거시 카드 → DEFER", state.mode == "DEFER" and state.card_ids == (legacy,))
    await db.execute("update knowledge_cards set review_status='EXCLUDED' "
                     "where store_id=$1 and card_id=$2", s, legacy)
    state = await fact_cards.entity_card_state(db, s, z)
    check("(e) 그 카드 EXCLUDED → NEW", state.mode == "NEW" and state.card_ids == ())
    loose = await repo.insert_card(db, s, category_id=other, source_id=src, title="대상 없는 카드",
                                   content="레거시 본문", confidence=50)
    ledger_ids = [r["fact_id"] for r in await db.fetch(
        "select fact_id from source_facts where store_id=$1 and source_id=$2", s, src)]
    await repo.link_card_facts(db, s, loose, ledger_ids)
    state = await fact_cards.entity_card_state(db, s, z)
    check("(f) entity 없는 카드가 card_facts 로 대상 사실을 이음 → DEFER",
          state.mode == "DEFER" and state.card_ids == (loose,))

    user, s, job = await _seed(db)
    src = await _new_source(db, s, user, "SCAN")
    await _ledger(db, s, src, [
        _assertion("f1", Z, "물", "225", "ml", variant="ICE"),
        _assertion("f2", B, "컵 준비", "컵을 꺼낸다", order=1),
    ])
    z, b = await _entity(db, s, Z), await _entity(db, s, B)
    cards = []
    for entity_id in (z, b):
        group, result = await _plan(db, s, entity_id)
        cards.append((await _write(db, s, src, job, group, result))[1].card_ids[0])
    await merge_entities(db, s, keep_entity_id=z, merged_entity_id=b, actor_id=user,
                         candidate_id=None)
    state = await fact_cards.entity_card_state(db, s, z)
    check("(g) 병합된 대상의 자동 사실 카드도 포함 → REASSEMBLE",
          state.mode == "REASSEMBLE" and state.card_ids == tuple(sorted(cards)))


async def _occ_snapshot(db, store, source):
    return {r["occurrence_id"]: (r["disposition"], r["reason"], r["card_id"], r["block_id"])
            for r in await _source_occurrences(db, store, source)}


async def _p5(db):
    check = _checker("P5")
    user, s, job = await _seed(db)
    src_c = await _new_source(db, s, user, "SCAN")
    await _ledger(db, s, src_c, [
        _assertion("f1", Z, "물", "225", "ml", variant="ICE"),
        _assertion("f2", B, "컵 준비", "컵을 꺼낸다"),
        _assertion("f3", B, "시럽", "넣는다"),
    ])
    src_d = await _new_source(db, s, user, "SCAN")
    await _ledger(db, s, src_d, [_assertion("f1", B, "컵 준비", "컵을 꺼낸다")])
    z, b = await _entity(db, s, Z), await _entity(db, s, B)
    group, result = await _plan(db, s, z)
    await _write(db, s, src_c, job, group, result)
    cup = await _revision_of(db, s, src_c, "컵 준비")
    syrup = await _revision_of(db, s, src_c, "시럽")
    excluded = await db.fetchval(
        "update fact_occurrences set disposition='EXCLUDED', reason='점주 제외' "
        "where store_id=$1 and source_id=$2 and fact_revision_id=$3 returning occurrence_id",
        s, src_c, syrup["head_revision_id"])
    before_c = await _occ_snapshot(db, s, src_c)
    before_d = await _occ_snapshot(db, s, src_d)
    fact_ids = [*await fact_cards.entity_fact_ids(db, s, z),
                *await fact_cards.entity_fact_ids(db, s, b)]
    changed = await fact_cards.mark_pending(db, s, source_id=src_c, fact_ids=fact_ids,
                                            reason=fact_cards.REASON_STALE_INPUT)
    after_c = await _occ_snapshot(db, s, src_c)
    pending = [o for o, v in before_c.items() if v[0] == "REVIEW_PENDING"]
    check("바뀐 행 = 자료 C 의 REVIEW_PENDING 행(컵 준비 하나)",
          changed == len(pending) == 1
          and after_c[pending[0]][:2] == ("REVIEW_PENDING", fact_cards.REASON_STALE_INPUT)
          and cup["fact_id"] in fact_ids)
    check("LINKED·점주 EXCLUDED 행 그대로",
          all(after_c[o] == v for o, v in before_c.items() if o not in pending)
          and after_c[excluded] == ("EXCLUDED", "점주 제외", None, None)
          and any(v[0] == "LINKED" for v in after_c.values()))
    check("다른 자료 행 그대로", await _occ_snapshot(db, s, src_d) == before_d and before_d)


async def _p6_p7(db):
    user, s, _ = await _seed(db)
    src = await _new_source(db, s, user, "SCAN")
    await _ledger(db, s, src, [
        _assertion("f1", Z, "물", "225", "ml", variant="ICE"),
        _assertion("f2", "!!!", "기호", "알 수 없음"),
    ])
    before = await fact_cards.disposition_counts(db, s, src)
    check = _checker("P6")
    added = await fact_cards.record_unresolvable_occurrences(db, s, src)
    rows = await db.fetch(
        "select o.fact_revision_id, o.disposition, o.reason from fact_occurrences o "
        "join source_fact_occurrences so on so.store_id = o.store_id "
        "  and so.occurrence_id = o.source_fact_occurrence_id "
        "join source_facts f on f.store_id = so.store_id and f.fact_id = so.fact_id "
        "where o.store_id=$1 and o.source_id=$2 and f.subject = '!!!'", s, src)
    check("결정 불가 위치마다 판 없는 ENTITY_UNRESOLVABLE 행",
          added >= 1 and len(rows) == added
          and all(r["fact_revision_id"] is None and r["disposition"] == "REVIEW_PENDING"
                  and r["reason"] == fact_cards.REASON_ENTITY_UNRESOLVABLE for r in rows))
    check("다시 불러도 0", await fact_cards.record_unresolvable_occurrences(db, s, src) == 0)

    check = _checker("P7")
    after = await fact_cards.disposition_counts(db, s, src)
    total = await db.fetchval("select count(*) from source_fact_occurrences "
                              "where store_id=$1 and source_id=$2", s, src)
    direct = {(r["disposition"], r["reason"]): r["n"] for r in await db.fetch(
        "select disposition, reason, count(*) n from fact_occurrences "
        "where store_id=$1 and source_id=$2 group by 1, 2", s, src)}
    check("호출 전 누락 ≥1, 호출 뒤 0", before.missing >= 1 and before.missing == added
          and after.missing == 0)
    check("합계·처분별 건수 = 직접 센 값",
          after.total == before.total == total
          and after.linked == direct.get(("LINKED", None), 0)
          and after.review_pending == {k[1]: n for k, n in direct.items()
                                       if k[0] == "REVIEW_PENDING"}
          and after.excluded == {k[1]: n for k, n in direct.items() if k[0] == "EXCLUDED"}
          and after.review_pending.get(fact_cards.REASON_ENTITY_UNRESOLVABLE) == added)


async def _p8(db):
    check = _checker("P8")
    user, s, job = await _seed(db)
    src = await _new_source(db, s, user, "SCAN")
    await _ledger(db, s, src, [
        _assertion("f1", Z, "물", "225", "ml", variant="ICE"),
        _assertion("f2", B, "컵 준비", "컵을 꺼낸다", order=1),
    ])
    z, b = await _entity(db, s, Z), await _entity(db, s, B)
    cup = await _revision_of(db, s, src, "컵 준비")
    await merge_entities(db, s, keep_entity_id=z, merged_entity_id=b, actor_id=user,
                         candidate_id=None)
    head = await db.fetchrow(
        "select k.head_revision_id, m.change_kind, r.supersedes_revision_id "
        "from knowledge_facts k join fact_revision_meta m on m.store_id = k.store_id "
        "  and m.fact_revision_id = k.head_revision_id "
        "join fact_revisions r on r.store_id = k.store_id "
        "  and r.fact_revision_id = k.head_revision_id "
        "where k.store_id=$1 and k.fact_id=$2", s, cup["fact_id"])
    group, result = await _plan(db, s, z)
    _, written = await _write(db, s, src, job, group, result)
    row = await _card(db, s, written.card_ids[0])
    _, _, prov = await _pins(db, s, row["draft_version_id"])
    relinked = {o for r, o, _ in prov if r == head["head_revision_id"]}
    before_merge = {o for _, o in await _occurrences_of(db, s, [cup["head_revision_id"]])}
    check("병합 RELINK head 의 근거 = 병합 전 판의 occurrence",
          head["change_kind"] == "RELINK"
          and head["supersedes_revision_id"] == cup["head_revision_id"]
          and relinked == before_merge and relinked
          and row["needs_review_reason"] is None and row["review_status"] == "PENDING")

    user, s, job = await _seed(db)
    src = await _new_source(db, s, user, "SCAN")
    await _ledger(db, s, src, [
        _assertion("f1", Z, "물", "225", "ml", variant="ICE"),
        _assertion("f2", Z, "얼음 개수", "4", "개", variant="ICE"),
    ])
    z = await _entity(db, s, Z)
    water = await _revision_of(db, s, src, "물")
    ice = await _revision_of(db, s, src, "얼음 개수")
    answer = await _new_owner_answer(db, s, user, "w3a-p8", "음료Z 얼음은 5개")
    owner_rev = await revise_fact(
        db, s, fact_id=ice["fact_id"], expected_head_revision_id=ice["head_revision_id"],
        change=FactChange(value="5", original_assertion="음료Z 얼음은 5개"),
        change_kind="OWNER_ANSWER", actor_id=user, owner_answer_id=answer)
    corrected = await revise_fact(
        db, s, fact_id=water["fact_id"], expected_head_revision_id=water["head_revision_id"],
        change=FactChange(value="300", original_assertion="음료Z 물은 300ml"),
        change_kind="OWNER_CORRECTION", actor_id=user)
    group, result = await _plan(db, s, z)
    _, written = await _write(db, s, src, job, group, result)
    row = await _card(db, s, written.card_ids[0])
    _, _, prov = await _pins(db, s, row["draft_version_id"])
    check("점주 정정 head — 그 판 근거 없음 → NO_PROVENANCE",
          not [p for p in prov if p[0] == corrected]
          and row["review_status"] == "NEEDS_REVIEW"
          and row["needs_review_reason"] == fact_cards.REVIEW_NO_PROVENANCE)
    check("점주 답변 head — 근거 행이 점주 답변", [p for p in prov if p[0] == owner_rev]
          == [(owner_rev, None, answer)])


async def _p9(db):
    check = _checker("P9")
    user, s, job = await _seed(db)
    sources = []
    for text, value, variant in (("합성 자료 1", "225", "ICE"), ("합성 자료 2", "250", "ICE"),
                                 ("합성 자료 3", "275", "HOT")):
        src = await _new_source(db, s, user, "SCAN")
        await _ledger(db, s, src, [_assertion("f1", Z, "물", value, "ml", variant=variant)],
                      title=text)
        sources.append(src)
    z = await _entity(db, s, Z)
    conflicts = await db.fetchval("select count(*) from fact_conflicts "
                                  "where store_id=$1 and status='OPEN'", s)
    group, result = await _plan(db, s, z)
    _, written = await _write(db, s, sources[0], job, group, result)
    row = await _card(db, s, written.card_ids[0])
    check("열린 충돌 → NEEDS_REVIEW·FACT_CONFLICT_OPEN",
          conflicts >= 1 and result.model_error is None and row["review_status"] == "NEEDS_REVIEW"
          and row["needs_review_reason"] == fact_cards.REVIEW_CONFLICT)
    hot = next(f for f in group.facts if f.variant_temperature == "HOT")
    ice = next(f for f in group.facts if f.variant_temperature == "ICE")
    mixed = [ProposedCard("레시피", (ProposedBlock(
        "QUANTITIES", tuple(f.fact_revision_id for f in group.facts)),))]
    group, result = await _plan(db, s, z, proposals=mixed)
    _, written = await _write(db, s, sources[0], job, group, result)
    row = await _card(db, s, written.card_ids[0])
    check("HOT/ICE 섞인 제안 → 대체 계획·FALLBACK:PLAN_VARIANT_MIXED(충돌보다 우선)",
          hot.fact_revision_id != ice.fact_revision_id
          and result.model_error == card_plan.PLAN_VARIANT_MIXED
          and row["needs_review_reason"] == "FALLBACK:PLAN_VARIANT_MIXED")


async def _p10(db):
    check = _checker("P10")
    user, s, job = await _seed(db)
    src = await _new_source(db, s, user, "SCAN")
    await _ledger(db, s, src, [_assertion("f1", Z, "물", "225", "ml", variant="ICE")])
    z = await _entity(db, s, Z)
    group, result = await _plan(db, s, z)
    first = (await _write(db, s, src, job, group, result))[1].card_ids[0]
    # 같은 대상의 자동 카드 둘 — 첫 카드를 잠시 제외해 둘째도 NEW 로 쓴 뒤 되돌린다
    await db.execute("update knowledge_cards set review_status='EXCLUDED' "
                     "where store_id=$1 and card_id=$2", s, first)
    second = (await _write(db, s, src, job, group, result))[1].card_ids[0]
    await db.execute("update knowledge_cards set review_status='PENDING' "
                     "where store_id=$1 and card_id=$2", s, first)
    second_before = await _card(db, s, second)
    src2 = await _new_source(db, s, user, "SCAN")
    await _ledger(db, s, src2, [_assertion("f1", Z, "물", "275", "ml", variant="HOT")])
    group, result = await _plan(db, s, z)
    state, written = await _write(db, s, src2, job, group, result)
    check("REASSEMBLE 기존 2·계획 1",
          state.mode == "REASSEMBLE" and state.card_ids == (first, second)
          and len(result.cards) == 1 and written.card_ids == (first,))
    check("첫 카드 새 판", len(await _versions(db, s, first)) == 2
          and written.new_version_ids == ((await _card(db, s, first))["draft_version_id"],))
    row = await _card(db, s, second)
    check("둘째 카드 NEEDS_REVIEW·REASSEMBLY_SUPERSEDED·판 그대로",
          row["review_status"] == "NEEDS_REVIEW"
          and row["needs_review_reason"] == fact_cards.REVIEW_SUPERSEDED
          and row["draft_version_id"] == second_before["draft_version_id"]
          and len(await _versions(db, s, second)) == 1)


async def _p12(db):
    """판정(REASSEMBLE) 뒤 점주 편집·승인이 먼저 커밋되면 쓰기가 아무것도 바꾸지 않는다."""
    check = _checker("P12")
    for action in ("편집", "승인"):
        f = await _fresh_written(db)
        src2 = await _new_source(db, f.store, f.user, "SCAN")
        await _ledger(db, f.store, src2, [_assertion("f1", Z, "물", "275", "ml", variant="HOT")])
        group, result = await _plan(db, f.store, f.z)
        state = await fact_cards.entity_card_state(db, f.store, f.z)
        row = await _card(db, f.store, f.card)
        if action == "편집":
            await cards_repo.create_draft(db, f.store, f.card, title=row["title"],
                                          content=row["content"] + " 점주 보탬", actor_id=f.user,
                                          source_version_id=row["draft_version_id"])
        else:
            await db.execute("update knowledge_cards set review_status='APPROVED' "
                             "where store_id=$1 and card_id=$2", f.store, f.card)
        before = (await _card(db, f.store, f.card), await _versions(db, f.store, f.card),
                  await _legacy_counts(db, f.store, f.card),
                  await _occ_snapshot(db, f.store, f.src))
        cards_before = await db.fetchval("select count(*) from knowledge_cards where store_id=$1",
                                         f.store)
        _, written = await _write(db, f.store, src2, f.job, group, result, state=state)
        after = (await _card(db, f.store, f.card), await _versions(db, f.store, f.card),
                 await _legacy_counts(db, f.store, f.card),
                 await _occ_snapshot(db, f.store, f.src))
        pending = await _source_occurrences(db, f.store, src2)
        check(f"점주 {action} 뒤 쓰기 — 아무것도 쓰지 않음·EXISTING_CARD",
              state.mode == "REASSEMBLE" and written.deferred_reason == "EXISTING_CARD"
              and written.card_ids == () and written.new_version_ids == ()
              and after == before
              and await db.fetchval("select count(*) from knowledge_cards where store_id=$1",
                                    f.store) == cards_before
              and pending and all(r["disposition"] == "REVIEW_PENDING"
                                  and r["reason"] == fact_cards.REASON_EXISTING_CARD
                                  for r in pending))
        if action == "편집":
            check("점주 초안 포인터 그대로(OWNER_EDIT)",
                  after[1][-1]["change_source"] == "OWNER_EDIT"
                  and after[0]["draft_version_id"] == after[1][-1]["version_id"])
        else:
            check("공개 포인터 그대로", after[0]["published_version_id"] is not None
                  and after[0]["review_status"] == "APPROVED")


async def _p11(db, w, card_id):
    check = _checker("P11")
    other_user, other, _ = await _seed(db)
    state = await fact_cards.entity_card_state(db, other, w.z)
    revs = [r["fact_revision_id"] for r in await db.fetch(
        "select fact_revision_id from fact_revisions where store_id=$1", w.store)]
    check("다른 매장 id — 상태 NEW·행 없음", state.mode == "NEW" and state.card_ids == ())
    changed = await fact_cards.mark_pending(
        db, other, source_id=w.src_a, fact_ids=await fact_cards.entity_fact_ids(db, w.store, w.z),
        reason=fact_cards.REASON_STALE_INPUT)
    counts = await fact_cards.disposition_counts(db, other, w.src_a)
    prov = await fact_cards.provenance_for(db, other, revs)
    check("다른 매장 id — mark_pending 0·집계 0·출처 빈 값",
          changed == 0 and counts.total == counts.missing == counts.linked == 0
          and counts.review_pending == {} and counts.excluded == {}
          and set(prov) == set(revs) and all(v == () for v in prov.values())
          and await fact_cards.entity_fact_ids(db, other, w.z) == [])
    version = (await _card(db, w.store, card_id))["draft_version_id"]
    try:
        await db.execute("update card_version_fact_provenance set created_at = now() "
                         "where store_id=$1 and card_version_id=$2", w.store, version)
        check("근거 행 UPDATE → 예외", False)
    except asyncpg.RaiseError:
        check("근거 행 UPDATE → 예외", True)
    try:
        await db.execute(
            "insert into card_version_fact_provenance (store_id, card_version_id, "
            "fact_revision_id, occurrence_id) select $1, $2, fact_revision_id, occurrence_id "
            "from card_version_fact_provenance where store_id=$3 and card_version_id=$2 limit 1",
            other, version, w.store)
        check("다른 매장 판을 가리키는 근거 행 → FK 예외", False)
    except asyncpg.ForeignKeyViolationError:
        check("다른 매장 판을 가리키는 근거 행 → FK 예외", True)
    other_answer = await _new_owner_answer(db, other, other_user, "w3a-p11")
    try:
        await db.execute(
            "insert into card_version_fact_provenance (store_id, card_version_id, "
            "fact_revision_id, owner_answer_id) values ($1, $2, $3, $4)",
            w.store, version, revs[0], other_answer)
        check("점주 답변 매장 불일치 → 트리거 예외", False)
    except asyncpg.RaiseError as exc:
        check("점주 답변 매장 불일치 → 트리거 예외", "매장" in str(exc))


# ── E: 파이프라인 연결 종단 (process_source·job_worker, Task 5) ─────────────

_W2_REASONS = {"W2_UNASSEMBLED", "VARIANT_SUBJECT_MISMATCH", "VARIANT_MULTI"}
CUP, SOAP, MACHINE = "컵", "세제", "머신"


def _w3a_settings(*, fact_assembly=True, proposals=False, concurrency=1, batch_facts=200,
                  hints=False):
    return Settings(_env_file=None, w_entity_revision_enabled=True,
                    w_upload_proposals_enabled=proposals,
                    w_fact_assembly_enabled=fact_assembly, assemble_concurrency=concurrency,
                    assemble_batch_facts=batch_facts, extract_segment_concurrency=2,
                    extract_locator_hints=hints)


def _fake_model(parts, category, calls, *, plan_override=None, fail_batches=()):
    """합성 모델 대역. 사실 추출 → 구간 사실, 사실 조립 → mock._planned(또는 override),
    그 밖(옛 조립) → 주어마다 카드 하나(W3-0 대역과 같다). 호출 기록을 calls 에 남긴다.

    fail_batches 는 이 대역이 받은 사실 조립 호출 번호(0부터)다.
    """
    segmented = len(parts) > 1
    cited = [(f"seg{index}:{f['local_ref']}" if segmented else f["local_ref"], f)
             for index, (_, facts) in enumerate(parts, start=1) for f in facts]
    plan_no = [0]

    async def fake_call(prompt, media, schema=None, max_output_tokens=None):
        if schema is not None and issubclass(schema, FactExtractionResult):
            facts = next(f for text, f in parts if text in prompt)
            calls.append(("FACTS", ()))
            body = schema.model_validate({"assertions": facts})
            return gemini.CallResult(body.model_dump_json(), {}, "STOP")
        if schema is CardPlanBatch:
            payload = json.loads(prompt.split(fact_assembly.PLAN_INPUT_MARKER, 1)[1])
            n = plan_no[0]
            plan_no[0] += 1
            calls.append(("PLAN", tuple(e["이름"] for e in payload)))
            if n in fail_batches:
                raise ValueError(f"합성 배치 실패 {n}")
            body = (plan_override or mock._planned)(payload, [category])
            return gemini.CallResult(body.model_dump_json(), {}, "STOP")
        calls.append(("LEGACY", ()))
        by_subject: dict[str, list[ExtractedFact]] = {}
        for ref, f in cited:
            by_subject.setdefault(f["subject"], []).append(ExtractedFact(
                object_name=f["subject"], attribute=f["attribute"], value=f["value"],
                confidence=.9, ref=ref))
        cards = [ExtractedCard(category_name=category, title=subject, content="합성 카드",
                               confidence=.9, facts=facts)
                 for subject, facts in by_subject.items()]
        return gemini.CallResult(ExtractionResult(cards=cards).model_dump_json(), {}, "STOP")

    return fake_call


@contextmanager
def _w3a_patches(pool, settings, fake_call, parts=None, *, hints=False):
    model_settings = NS(**{**vars(_MODEL_SETTINGS), "extract_reuse_enabled": True,
                           "extract_locator_hints": hints})
    replacements = [
        (pipeline, "get_pool", lambda: pool),
        (job_worker, "get_pool", lambda: pool),
        (job_worker, "create_ingest_completed_notification", AsyncMock(return_value=None)),
        (job_worker, "deliver_notification", AsyncMock(return_value=None)),
        (pipeline.shutil, "rmtree", lambda *a, **kw: None),
        (app.config, "get_settings", lambda: settings),
        (extract, "get_settings", lambda: NS(ingest_mode="real")),
        (gemini, "get_settings", lambda: model_settings),
        (gemini, "_call", fake_call),
    ]
    if parts is not None:
        if len(parts) > 1:
            preprocessed = ("합성 자료 본문", [], [(text, []) for text, _ in parts])
        else:
            preprocessed = (parts[0][0], [], [])
        replacements.append((pipeline, "_preprocess", AsyncMock(return_value=preprocessed)))
    with ExitStack() as stack:
        for obj, name, replacement in replacements:
            stack.enter_context(patch.object(obj, name, replacement))
        yield


async def _queue(db, store, user, source, *, status):
    job_id = await db.fetchval(
        "insert into ingest_jobs (store_id, created_by, title, status, category_version, "
        "prompt_version) values ($1,$2,'W3a 종단 검증',$3,1,'v1') returning job_id",
        store, user, status)
    await db.execute("update sources set status='UPLOADED' where store_id=$1 and source_id=$2",
                     store, source)
    await db.execute("insert into ingest_job_sources(store_id,job_id,source_id,status) "
                     "values($1,$2,$3,'QUEUED')", store, job_id, source)
    return job_id


async def _process_w3a(db, pool, store, user, source, parts, *, run_tag, fact_assembly=True,
                       proposals=False, concurrency=1, batch_facts=200, plan_override=None,
                       fail_batches=(), hints=False, expect="DONE"):
    """process_source 를 합성 대역으로 돌린다(verify_w3_flag_readiness._process 방식).

    parts = [(구간 글, 사실 목록)]. 둘 이상이면 구간으로 나눠 동시에 2개씩 뽑는다.
    """
    job_id = await _queue(db, store, user, source, status="EXTRACTING")
    category = next(iter(await repo.enabled_categories(db, store)))
    calls: list = []
    fake = _fake_model(parts, category, calls, plan_override=plan_override,
                       fail_batches=fail_batches)
    settings = _w3a_settings(fact_assembly=fact_assembly, proposals=proposals,
                             concurrency=concurrency, batch_facts=batch_facts, hints=hints)
    with _w3a_patches(pool, settings, fake, parts, hints=hints):
        await pipeline.process_source(store, source, job_id=job_id, run_tag=run_tag)
    state = await db.fetchrow("select status, error_message from sources "
                              "where store_id=$1 and source_id=$2", store, source)
    assert state["status"] == expect, f"처리 결과 {state['status']} {state['error_message']}"
    return NS(job=job_id, calls=calls, error=state["error_message"])


def _plans(calls):
    return [names for kind, names in calls if kind == "PLAN"]


async def _store_cards(db, store):
    return await db.fetch(
        "select card_id, entity_id, review_status, needs_review_reason, title, content, "
        "draft_version_id, published_version_id from knowledge_cards where store_id=$1 "
        "order by card_id", store)


async def _entity_cards(db, store, entity_id):
    return [r["card_id"] for r in await db.fetch(
        "select card_id from knowledge_cards where store_id=$1 and entity_id=$2 order by card_id",
        store, entity_id)]


async def _occ_of(db, store, source, subject):
    """자료의 occurrence 중 원장 주어가 subject 인 것."""
    return await db.fetch(
        "select o.disposition, o.reason, o.card_id, o.block_id, o.fact_revision_id, "
        "o.locator_type, o.locator from fact_occurrences o "
        "join source_fact_occurrences so on so.store_id = o.store_id "
        "  and so.occurrence_id = o.source_fact_occurrence_id "
        "join source_facts f on f.store_id = so.store_id and f.fact_id = so.fact_id "
        "where o.store_id=$1 and o.source_id=$2 and f.subject=$3 order by o.occurrence_id",
        store, source, subject)


def _all(rows, disposition, reason=None, card_id=None):
    return bool(rows) and all(
        r["disposition"] == disposition and r["reason"] == reason
        and (card_id is None or r["card_id"] == card_id) for r in rows)


async def _w2_reason_rows(db, store, source):
    return await db.fetchval(
        "select count(*) from fact_occurrences where store_id=$1 and source_id=$2 "
        "and (reason = 'W2_UNASSEMBLED' or reason like 'VARIANT\\_%')", store, source)


def _disposition_text(counts):
    return f"LINKED {counts.linked} · 대기 {dict(sorted(counts.review_pending.items()))}"


async def _block_shape(db, store, version_id):
    """판의 블록(종류·순서·블록 사실 원문 순서)."""
    rows = await db.fetch(
        "select b.block_order, b.kind, r.original_assertion from card_version_blocks b "
        "join card_block_facts f on f.store_id = b.store_id "
        "  and f.card_version_id = b.card_version_id and f.block_id = b.block_id "
        "join fact_revisions r on r.store_id = f.store_id "
        "  and r.fact_revision_id = f.fact_revision_id "
        "where b.store_id=$1 and b.card_version_id=$2 order by b.block_order, f.position",
        store, version_id)
    shape: dict[tuple, list[str]] = {}
    for r in rows:
        shape.setdefault((r["block_order"], r["kind"]), []).append(r["original_assertion"])
    return sorted(shape.items())


_E1_PARTS = [
    ("구간1 합성 본문 — 음료Z ICE 물 225ml, 얼음, 샷", [
        _assertion("f1", Z, "물", "225", "ml", variant="ICE", ts=5),
        _assertion("f2", Z, "얼음 담기", "컵에 얼음", variant="ICE", order=1, ts=10),
        _assertion("f3", Z, "샷 붓기", "샷을 붓는다", variant="ICE", order=2, requires=["f2"],
                   conditions=["얼음이 녹기 전"], ts=15),
    ]),
    ("구간2 합성 본문 — 시럽 없음, 컵 355ml", [
        _assertion("f1", Z, "시럽", "넣지 않는다", neg=True, exceptions=["손님 요청 시"], ts=65),
        _assertion("f2", CUP, "크기", "355", "ml", ts=70),
    ]),
]


async def _e1(db, pool):
    check = _checker("E1")
    user, s, _ = await _seed(db)
    src_a = await _new_source(db, s, user, "VIDEO")
    run = await _process_w3a(db, pool, s, user, src_a, _E1_PARTS, run_tag=801)
    z, cup = await _entity(db, s, Z), await _entity(db, s, CUP)
    cards = await _store_cards(db, s)
    check("카드 2(음료Z·컵) PENDING·검수 사유 없음",
          len(cards) == 2 and {c["entity_id"] for c in cards} == {z, cup}
          and all(c["review_status"] == "PENDING" and c["needs_review_reason"] is None
                  for c in cards))
    card_z = next(c for c in cards if c["entity_id"] == z)
    shapes = {c["entity_id"]: await _block_shape(db, s, c["draft_version_id"]) for c in cards}
    check("블록 고정 — 음료Z 사실 4·컵 사실 1",
          sum(len(v) for _, v in shapes[z]) == 4 and sum(len(v) for _, v in shapes[cup]) == 1
          and [k[1] for k, _ in shapes[z]] == ["QUANTITIES", "STEPS", "NOTES"])
    originals = [f["original_assertion"] for _, facts in _E1_PARTS for f in facts
                 if f["subject"] == Z]
    check("본문에 모든 원문·조건·예외",
          all(o in card_z["content"] for o in originals)
          and "얼음이 녹기 전" in card_z["content"] and "손님 요청 시" in card_z["content"])
    rows = await _source_occurrences(db, s, src_a)
    check("A occurrence 전부 LINKED", len(rows) == 5 and _all(rows, "LINKED"))
    check("A 행에 W2_UNASSEMBLED·VARIANT_* 사유 0", await _w2_reason_rows(db, s, src_a) == 0)
    counts = await fact_cards.disposition_counts(db, s, src_a)
    check(f"처분 누락 0 — {_disposition_text(counts)}",
          counts.missing == 0 and counts.total == 5 and counts.linked == 5)
    check("원래 응답 ASSEMBLE·plan0 1행", await db.fetchval(
        "select count(*) from extraction_raw_responses where store_id=$1 "
        "and stage='ASSEMBLE' and segment_id='plan0'", s) == 1)
    plans = _plans(run.calls)
    check("사실 조립 호출 1(대상 둘)·옛 조립(ExtractionResult) 호출 0",
          len(plans) == 1 and set(plans[0]) == {Z, CUP}
          and not [c for c in run.calls if c[0] == "LEGACY"])
    return NS(user=user, store=s, src_a=src_a, z=z, cup=cup, card_z=card_z["card_id"])


async def _e2(db, pool, w):
    check = _checker("E2")
    src_b = await _new_source(db, w.store, w.user, "SCAN")
    await _process_w3a(db, pool, w.store, w.user, src_b, [(
        "합성 자료 본문 B — HOT 물 275ml", [_assertion("f1", "음료 Z", "물", "275", "ml",
                                                   variant="HOT")])], run_tag=802)
    w.src_b = src_b
    check("음료Z 대상 카드 1장 — 같은 card_id",
          await _entity_cards(db, w.store, w.z) == [w.card_z])
    versions = await _versions(db, w.store, w.card_z)
    row = await _card(db, w.store, w.card_z)
    check("판 2 — 둘 다 EXTRACTION, 초안 포인터 판 2",
          len(versions) == 2 and all(v["change_source"] == "EXTRACTION" for v in versions)
          and row["draft_version_id"] == versions[1]["version_id"])
    check("B occurrence LINKED(음료Z 카드)",
          _all(await _source_occurrences(db, w.store, src_b), "LINKED", card_id=w.card_z))
    a_rows = await _occ_of(db, w.store, w.src_a, Z)
    off_block = await db.fetchval(
        "select count(*) from fact_occurrences o "
        "join fact_revisions r on r.store_id = o.store_id "
        "  and r.fact_revision_id = o.fact_revision_id "
        "where o.store_id=$1 and o.source_id=$2 and o.card_id=$3 and not exists ("
        "  select 1 from card_block_facts b join fact_revisions br "
        "    on br.store_id = b.store_id and br.fact_revision_id = b.fact_revision_id "
        "  where b.store_id = o.store_id and b.card_version_id=$4 "
        "    and b.block_id = o.block_id and br.fact_id = r.fact_id)",
        w.store, w.src_a, w.card_z, row["draft_version_id"])
    check("A 의 음료Z occurrence 가 판 2 블록 id",
          len(a_rows) == 4 and _all(a_rows, "LINKED", card_id=w.card_z) and off_block == 0)
    counts = await fact_cards.disposition_counts(db, w.store, src_b)
    check(f"B 처분 — {_disposition_text(counts)}", counts.missing == 0 and counts.linked == 1)


async def _e3(db, pool, w):
    check = _checker("E3")

    async def snapshot():
        row = await _card(db, w.store, w.card_z)
        return (len(await _versions(db, w.store, w.card_z)),
                await _pins(db, w.store, row["draft_version_id"]),
                await _legacy_counts(db, w.store, w.card_z),
                await _w2_counts(db, w.store),
                await _occ_snapshot(db, w.store, w.src_b))

    before = await snapshot()
    run = await _process_w3a(db, pool, w.store, w.user, w.src_b, [(
        "합성 자료 본문 B — HOT 물 275ml", [_assertion("f1", "음료 Z", "물", "275", "ml",
                                                   variant="HOT")])], run_tag=803)
    check("판 수·블록·근거·레거시·W2 표 행 수·occurrence 그대로", await snapshot() == before)
    reused = await db.fetchval(
        "select count(*) from ai_usage_attempts where store_id=$1 and stage='ASSEMBLE' "
        "and cache_state=$2 and job_id=$3", w.store, CACHE_STATE_REUSED, run.job)
    check("사실 조립 모델 대역 호출 0(재사용 시도 1)", _plans(run.calls) == [] and reused == 1)


def _mixed_plan(payload, categories):
    """대상마다 모든 사실을 QUANTITIES 블록 하나에 — 규격이 섞인다."""
    return CardPlanBatch(cards=[
        PlannedCard(entity=e["대상"], category_name=categories[0],
                    blocks=[PlannedBlock(kind="QUANTITIES", facts=[f["id"] for f in e["사실"]])])
        for e in payload])


async def _e4(db, pool):
    check = _checker("E4")
    user, s, _ = await _seed(db)
    src = await _new_source(db, s, user, "SCAN")
    await _process_w3a(db, pool, s, user, src, [("합성 자료 본문 E4 — HOT 275ml, ICE 225ml", [
        _assertion("f1", Z, "물", "275", "ml", variant="HOT"),
        _assertion("f2", Z, "물", "225", "ml", variant="ICE"),
    ])], run_tag=804, plan_override=_mixed_plan)
    cards = await _store_cards(db, s)
    check("카드 1 NEEDS_REVIEW·FALLBACK:PLAN_VARIANT_MIXED",
          len(cards) == 1 and cards[0]["review_status"] == "NEEDS_REVIEW"
          and cards[0]["needs_review_reason"] == "FALLBACK:PLAN_VARIANT_MIXED")
    mixed = await db.fetchval(
        "select count(*) from (select f.block_id from card_block_facts f "
        "join fact_revisions r on r.store_id = f.store_id "
        "  and r.fact_revision_id = f.fact_revision_id "
        "where f.store_id=$1 and f.card_version_id=$2 group by f.block_id "
        "having count(distinct coalesce(r.variant_temperature,'') || '|' "
        "  || coalesce(r.variant_size,'')) > 1) x", s, cards[0]["draft_version_id"])
    placed = await db.fetchval("select count(*) from card_block_facts where store_id=$1 "
                               "and card_version_id=$2", s, cards[0]["draft_version_id"])
    check("블록 규격 섞임 0·사실 2 모두 배치", mixed == 0 and placed == 2)
    check("occurrence LINKED", _all(await _source_occurrences(db, s, src), "LINKED",
                                    card_id=cards[0]["card_id"]))


async def _e5(db, pool, w):
    check = _checker("E5")
    await db.execute("update knowledge_cards set review_status = 'APPROVED' "
                     "where store_id = $1 and card_id = $2", w.store, w.card_z)
    before = await _card(db, w.store, w.card_z)
    versions = len(await _versions(db, w.store, w.card_z))
    src_c = await _new_source(db, w.store, w.user, "SCAN")
    run = await _process_w3a(db, pool, w.store, w.user, src_c, [(
        "합성 자료 본문 C — 시럽 20ml, 뚜껑", [
            _assertion("f1", Z, "시럽", "20", "ml"),
            _assertion("f2", CUP, "뚜껑", "1", "개")])], run_tag=805, proposals=True)
    after = await _card(db, w.store, w.card_z)
    check("음료Z 카드 판 수·공개·초안 포인터 그대로",
          before["published_version_id"] is not None
          and len(await _versions(db, w.store, w.card_z)) == versions
          and (after["published_version_id"], after["draft_version_id"])
          == (before["published_version_id"], before["draft_version_id"]))
    check("C 의 음료Z occurrence REVIEW_PENDING/EXISTING_CARD",
          _all(await _occ_of(db, w.store, src_c, Z), "REVIEW_PENDING",
               fact_cards.REASON_EXISTING_CARD))
    check("C 의 컵 occurrence LINKED", _all(await _occ_of(db, w.store, src_c, CUP), "LINKED"))
    status = await db.fetchval(
        "select status from upload_change_proposals where store_id=$1 and source_id=$2 "
        "and entity_id=$3", w.store, src_c, w.z)
    check("업로드 제안(C, 음료Z) PENDING_REVIEW", status == "PENDING_REVIEW")
    check("이번 사실 조립 페이로드에 음료Z 없음", _plans(run.calls) == [(CUP,)])
    counts = await fact_cards.disposition_counts(db, w.store, src_c)
    check(f"C 처분 — {_disposition_text(counts)}",
          counts.missing == 0 and counts.linked == 1
          and counts.review_pending == {fact_cards.REASON_EXISTING_CARD: 1})


_E6_TEXT = ("[#1] 합성 대화 시작\n[#2] !!! 기호 알 수 없음\n[#3] 음료Z 디카페인 카페인 줄임\n"
            "[#4] 컵 크기 355ml")


def _line(fact, line):
    fact["evidence"] = {"timestamp_sec": 0, "line": line}
    return fact


async def _e6(db, pool):
    check = _checker("E6")
    user, s, _ = await _seed(db)
    src = await _new_source(db, s, user, "KAKAO")
    await _process_w3a(db, pool, s, user, src, [(_E6_TEXT, [
        _line(_assertion("f1", "!!!", "기호", "알 수 없음"), 2),
        _line(_assertion("f2", Z, "카페인", "줄임", variant="디카페인"), 3),
        _line(_assertion("f3", CUP, "크기", "355", "ml"), 4),
    ])], run_tag=806, hints=True)
    odd = await _occ_of(db, s, src, "!!!")
    check("결정 불가 — 판 없는 ENTITY_UNRESOLVABLE",
          _all(odd, "REVIEW_PENDING", fact_cards.REASON_ENTITY_UNRESOLVABLE)
          and all(r["fact_revision_id"] is None for r in odd))
    check("미상 규격 — VARIANT_UNRESOLVED",
          _all(await _occ_of(db, s, src, Z), "REVIEW_PENDING",
               fact_assembly.REASON_VARIANT_UNRESOLVED))
    cup_rows = await _occ_of(db, s, src, CUP)
    cup = await _entity(db, s, CUP)
    cards = await _entity_cards(db, s, cup)
    check("컵 사실 LINKED", len(cards) == 1 and _all(cup_rows, "LINKED", card_id=cards[0]))
    located = sorted((r["locator_type"], json.loads(r["locator"])["line"])
                     for r in [*odd, *await _occ_of(db, s, src, Z), *cup_rows])
    check("카톡 위치 — occurrence 모두 LINE 메시지 번호",
          located == [("LINE", 2), ("LINE", 3), ("LINE", 4)])
    evidence = await db.fetch(
        "select e.locator_type, e.locator from card_evidence e join knowledge_cards k "
        "on k.store_id = e.store_id and k.draft_version_id = e.version_id "
        "where k.store_id=$1 and k.card_id=$2", s, cards[0])
    check("카드 근거 위치 — MESSAGE {line: 4}",
          [(r["locator_type"], json.loads(r["locator"])) for r in evidence]
          == [("MESSAGE", {"line": 4})])
    counts = await fact_cards.disposition_counts(db, s, src)
    check(f"처분 누락 0 — {_disposition_text(counts)}",
          counts.missing == 0 and counts.linked == 1
          and counts.review_pending == {fact_cards.REASON_ENTITY_UNRESOLVABLE: 1,
                                        fact_assembly.REASON_VARIANT_UNRESOLVED: 1})


async def _e7(db, pool):
    check = _checker("E7")
    user, s, _ = await _seed(db)
    src = await _new_source(db, s, user, "SCAN")
    run = await _process_w3a(db, pool, s, user, src, [("합성 자료 본문 E7 — 전원, 세제", [
        _assertion("f1", MACHINE, "전원 끄기", "전원을 끈다", order=1),
        _assertion("f2", SOAP, "세제 넣기", "세제를 넣는다", order=2, requires=["f1"]),
    ])], run_tag=807)
    soap, machine = await _entity(db, s, SOAP), await _entity(db, s, MACHINE)
    check("세제 — DATA_REQUIRES_OUTSIDE_ENTITY·카드 없음",
          await _entity_cards(db, s, soap) == []
          and _all(await _occ_of(db, s, src, SOAP), "REVIEW_PENDING",
                   card_plan.DATA_REQUIRES_OUTSIDE_ENTITY))
    check("모델 페이로드에 세제 없음", _plans(run.calls) == [(MACHINE,)])
    cards = await _entity_cards(db, s, machine)
    check("머신 카드 생성·LINKED", len(cards) == 1
          and _all(await _occ_of(db, s, src, MACHINE), "LINKED", card_id=cards[0]))


_E8_FACTS = [
    _assertion("f1", Z, "물", "225", "ml"),
    _assertion("f2", B, "시럽", "20", "ml"),
    _assertion("f3", CUP, "크기", "355", "ml"),
]


async def _prepare(db, pool, store, source, settings, fake, *, strict):
    categories = list(await repo.enabled_categories(db, store))
    with _w3a_patches(pool, settings, fake):
        return await pipeline._prepare_fact_assembly(
            pool, store, source, categories=categories, glossary=[],
            usage_sink=DbUsageSink(pool), raw_sink=DbRawResponseSink(pool),
            usage_base=(store, None, "REGISTRATION", "PRODUCT", None, None), strict=strict)


async def _persist_prepared(db, pool, store, source, job, settings, prepared):
    with _w3a_patches(pool, settings, None):
        async with db.transaction():
            categories = await repo.enabled_categories(db, store)
            return await pipeline._persist_fact_cards(db, store, source, categories, prepared,
                                                      job_id=job, category_version=1)


async def _e8(db, pool):
    check = _checker("E8")
    user, s, job = await _seed(db)
    src = await _new_source(db, s, user, "SCAN")
    await _ledger(db, s, src, _E8_FACTS)
    category = next(iter(await repo.enabled_categories(db, s)))
    calls: list = []
    settings = _w3a_settings(batch_facts=1)
    prepared = await _prepare(db, pool, s, src, settings,
                              _fake_model([], category, calls, fail_batches={1}), strict=False)
    order = list(prepared.entity_ids)
    check("(a) 배치 3·배치 1 대상만 실패",
          len(order) == 3 and prepared.planning.batch_count == 3
          and prepared.planning.failed_entity_ids == (order[1],))
    created = await _persist_prepared(db, pool, s, src, job, settings, prepared)
    check("(a) 배치 0·2 대상 카드 저장",
          created == 2 and all([len(await _entity_cards(db, s, e)) == 1 for e in (order[0], order[2])])
          and await _entity_cards(db, s, order[1]) == [])
    names = {e: (await db.fetchval("select canonical_name from knowledge_entities "
                                   "where store_id=$1 and entity_id=$2", s, e)) for e in order}
    check("(a) 배치 1 대상 occurrence ASSEMBLY_FAILED",
          _all(await _occ_of(db, s, src, names[order[1]]), "REVIEW_PENDING",
               fact_cards.REASON_ASSEMBLY_FAILED))
    check("(a) 처분 누락 0", (await fact_cards.disposition_counts(db, s, src)).missing == 0)

    user, s, _ = await _seed(db)
    src = await _new_source(db, s, user, "SCAN")
    run = await _process_w3a(db, pool, s, user, src, [("합성 자료 본문 E8", _E8_FACTS)],
                             run_tag=808, batch_facts=1, fail_batches={1}, expect="FAILED")
    check("(b) strict — 자료 FAILED·카드 조립 실패",
          "카드 조립 실패" in (run.error or "") and len(_plans(run.calls)) == 3)
    check("(b) 새 카드·판 0", await db.fetchval(
        "select count(*) from knowledge_cards where store_id=$1", s) == 0
        and await db.fetchval("select count(*) from card_versions where store_id=$1", s) == 0)
    rows = await _source_occurrences(db, s, src)
    check("(b) occurrence 는 W2 사유 그대로",
          len(rows) == 3 and all(r["disposition"] == "REVIEW_PENDING"
                                 and r["reason"] in _W2_REASONS for r in rows))


_E9_PARTS = [("합성 자료 본문 E9", [
    _assertion("f1", Z, "물", "225", "ml", variant="ICE"),
    _assertion("f2", Z, "얼음 담기", "컵에 얼음", variant="ICE", order=1),
    _assertion("f3", B, "시럽", "20", "ml"),
    _assertion("f4", CUP, "크기", "355", "ml"),
])]


async def _e9(db, pool):
    check = _checker("E9")
    outcome = {}
    for concurrency in (1, 4):
        user, s, _ = await _seed(db)
        src = await _new_source(db, s, user, "SCAN")
        await _process_w3a(db, pool, s, user, src, _E9_PARTS, run_tag=809 + concurrency,
                           concurrency=concurrency, batch_facts=1)
        cards = sorted(await _store_cards(db, s), key=lambda c: c["title"])
        shape = [(c["title"], c["content"], await _block_shape(db, s, c["draft_version_id"]))
                 for c in cards]
        segments = {r["segment_id"] for r in await db.fetch(
            "select segment_id from extraction_raw_responses where store_id=$1 "
            "and stage='ASSEMBLE'", s)}
        attempts = await db.fetchval("select count(*) from ai_usage_attempts where store_id=$1 "
                                     "and stage='ASSEMBLE'", s)
        outcome[concurrency] = (shape, segments, attempts)
    check("동시 1·4 — 카드 (제목, 본문, 블록 종류·순서·사실 원문 순서) 같다",
          len(outcome[1][0]) == 3 and outcome[1][0] == outcome[4][0])
    check("원래 응답 segment_id {plan0, plan1, plan2}",
          outcome[1][1] == outcome[4][1] == {"plan0", "plan1", "plan2"})
    check("사용량 시도 3 으로 같다", outcome[1][2] == outcome[4][2] == 3)


async def _run_job(db, pool, store, user, source, parts, *, fact_assembly=True):
    job_id = await _queue(db, store, user, source, status="QUEUED")
    category = next(iter(await repo.enabled_categories(db, store)))
    fake = _fake_model(parts, category, [])
    with _w3a_patches(pool, _w3a_settings(fact_assembly=fact_assembly), fake, parts):
        await job_worker.process_ingest_job(store, job_id)
    return await db.fetchrow(
        "select status, card_count, error_code, error_message from ingest_job_sources "
        "where store_id=$1 and job_id=$2 and source_id=$3", store, job_id, source)


async def _e10(db, pool):
    check = _checker("E10")
    user, s, _ = await _seed(db)
    src1 = await _new_source(db, s, user, "SCAN")
    row = await _run_job(db, pool, s, user, src1, [("합성 자료 본문 E10-1", [
        _assertion("f1", Z, "물", "225", "ml", variant="ICE")])])
    check("새 카드 자료 — card_count 1·SUCCEEDED",
          (row["status"], row["card_count"]) == ("SUCCEEDED", 1))
    z = await _entity(db, s, Z)
    await db.execute("update knowledge_cards set review_status = 'APPROVED' "
                     "where store_id = $1 and entity_id = $2", s, z)
    src2 = await _new_source(db, s, user, "SCAN")
    row = await _run_job(db, pool, s, user, src2, [("합성 자료 본문 E10-2", [
        _assertion("f1", Z, "시럽", "20", "ml")])])
    check("DEFER 만 있는 자료 — card_count 0·NO_RESULT·새 문구",
          (row["status"], row["card_count"], row["error_code"], row["error_message"])
          == ("NO_RESULT", 0, "NO_RESULT", job_worker.NO_NEW_CARD_PENDING_MESSAGE)
          and row["error_message"] == "새 카드 없이 검수할 사실이 남았습니다.")
    user, s, _ = await _seed(db)
    src3 = await _new_source(db, s, user, "SCAN")
    row = await _run_job(db, pool, s, user, src3, [("합성 자료 본문 E10-3", [])],
                         fact_assembly=False)
    check("플래그 꺼짐 — 지금 문구",
          (row["status"], row["card_count"], row["error_message"])
          == ("NO_RESULT", 0, "추출된 업무 카드가 없습니다."))


async def _e11(db, pool):
    check = _checker("E11")
    user, s, job = await _seed(db)
    src_x = await _new_source(db, s, user, "SCAN")
    await _ledger(db, s, src_x, [_assertion("f1", Z, "물", "225", "ml", variant="ICE")])
    category = next(iter(await repo.enabled_categories(db, s)))
    settings = _w3a_settings()
    prepared = await _prepare(db, pool, s, src_x, settings, _fake_model([], category, []),
                              strict=True)
    z = await _entity(db, s, Z)
    check("X 준비 — 음료Z NEW", prepared.states[z].mode == "NEW")
    src_y = await _new_source(db, s, user, "SCAN")
    await _process_w3a(db, pool, s, user, src_y, [("합성 자료 본문 E11 Y", [
        _assertion("f1", Z, "물", "275", "ml", variant="HOT")])], run_tag=811)
    (card_y,) = await _entity_cards(db, s, z)
    draft = (await _card(db, s, card_y))["draft_version_id"]
    x_rev = await _revision_of(db, s, src_x, "물")
    in_y = await db.fetchval("select count(*) from card_block_facts where store_id=$1 "
                             "and card_version_id=$2 and fact_revision_id=$3",
                             s, draft, x_rev["head_revision_id"])
    check("Y 카드 입력에 X 사실 포함", in_y == 1)
    cards_before = await _store_cards(db, s)
    versions_before = await _versions(db, s, card_y)
    created = await _persist_prepared(db, pool, s, src_x, job, settings, prepared)
    check("X 저장 — 새 카드·판 0",
          created == 0 and await _store_cards(db, s) == cards_before
          and await _versions(db, s, card_y) == versions_before)
    check("X occurrence 는 Y 가 쓴 카드로 LINKED",
          _all(await _source_occurrences(db, s, src_x), "LINKED", card_id=card_y))
    check("처분 누락 0", (await fact_cards.disposition_counts(db, s, src_x)).missing == 0)


async def _e12(db, pool):
    check = _checker("E12")
    user, s, _ = await _seed(db)
    src = await _new_source(db, s, user, "VIDEO")
    run = await _process_w3a(db, pool, s, user, src, _E1_PARTS, run_tag=812,
                             fact_assembly=False)
    check("옛 조립 대역(ExtractionResult) 호출·사실 조립 호출 0",
          [c for c in run.calls if c[0] == "LEGACY"] and _plans(run.calls) == [])
    check("card_block_facts·card_version_fact_provenance 0행", all([
        await db.fetchval(f"select count(*) from {t} where store_id=$1", s) == 0
        for t in ("card_block_facts", "card_version_fact_provenance")]))
    rows = await _source_occurrences(db, s, src)
    check("occurrence 는 W2 사유 그대로",
          len(rows) == 5 and all(r["disposition"] == "REVIEW_PENDING"
                                 and r["reason"] in _W2_REASONS for r in rows))
    cards = await _store_cards(db, s)
    check("카드 본문 = 옛 대역 본문", len(cards) == 2
          and all(c["content"] == "합성 카드" for c in cards))


# ── B: 공개판에 사실 싣기 (publish/content) ─────────────────────────────────

_VECTOR = [1.0] + [0.0] * 1535


def _hex(store, source):
    """합성 자료 지문 — 매장 안에서 자료마다 달라야 한다(sources 고유 색인)."""
    return hashlib.sha256(f"합성 자료 {store}:{source}".encode()).hexdigest()


async def _fake_embedder(texts, *, context, sink=None):
    return [list(_VECTOR) for _ in texts]


async def _member(db, store, user):
    return await db.fetchval(
        "insert into store_members (store_id, user_id, member_role) values ($1,$2,'OWNER') "
        "returning member_id", store, user)


async def _publish(pool, store, member, user, changes, key):
    usage = UsageContext(store_id=str(store), cost_phase="OPERATING", cost_purpose="PRODUCT",
                         stage="EMBED", operation_id=f"w3a-publish:{key}",
                         logical_call_id=f"w3a-publish:{key}:embed")
    with patch("app.reg.index_preparation.recorded_embeddings", _fake_embedder):
        return await publish_cards(pool, store_id=store, member_id=member, actor_user_id=user,
                                   changes=changes, idempotency_key=key, usage_context=usage)


async def _approve(db, pool, w, card_id, key):
    draft = (await _card(db, w.store, card_id))["draft_version_id"]
    return await _publish(pool, w.store, w.member, w.user, [CardChange(card_id, draft, draft)],
                          key)


async def _index(pool, store):
    async with pool.acquire() as conn:
        snapshot, _, _ = await read_current_index(conn, store_id=store)
    return snapshot


async def _hashed_source(db, store, user):
    """자료 지문(64 소문자 16진)이 있는 합성 자료 — 공개 근거의 source_content_hash 대조용."""
    source = await _new_source(db, store, user, "SCAN")
    await db.execute("update sources set content_hash=$3 where store_id=$1 and source_id=$2",
                     store, source, _hex(store, source))
    return source


async def _fact_store(db, pool, parts, *, run_tag):
    """새 합성 매장 + 점주 멤버 + 사실 카드(플래그 켬 처리)."""
    user, s, _ = await _seed(db)
    member = await _member(db, s, user)
    src = await _hashed_source(db, s, user)
    await _process_w3a(db, pool, s, user, src, parts, run_tag=run_tag)
    return NS(user=user, store=s, member=member, src=src)


async def _pinned(db, store, version_id):
    """판에 고정된 (블록 순서대로 (block_id, kind, order, 블록 사실 id 문자열들)), 고정 판 id."""
    blocks, facts, _ = await _pins(db, store, version_id)
    by_block: dict[str, list[str]] = {}
    for block_id, rid, _ in facts:
        by_block.setdefault(block_id, []).append(str(rid))
    shaped = [(b, kind, order, tuple(by_block.get(b, ()))) for b, kind, order, _ in blocks]
    return shaped, {rid for _, rid, _ in facts}


def _shape(card):
    return [(b.block_id, b.kind, b.order, b.fact_revision_ids)
            for b in sorted(card.blocks, key=lambda b: b.order)]


async def _snapshot_row(db, store, snapshot_id):
    return dict(await db.fetchrow("select * from knowledge_snapshots where store_id=$1 "
                                  "and snapshot_id=$2", store, snapshot_id))


_B1_LEGACY = [("합성 자료 본문 B1 — 컵 355ml", [_assertion("f1", CUP, "크기", "355", "ml")])]
_B_Z = [("합성 자료 본문 B — 음료Z ICE 물 225ml, 얼음, 샷, 시럽 없음", [
    _assertion("f1", Z, "물", "225", "ml", variant="ICE"),
    _assertion("f2", Z, "얼음 담기", "컵에 얼음", variant="ICE", order=1),
    _assertion("f3", Z, "샷 붓기", "샷을 붓는다", variant="ICE", order=2, requires=["f2"]),
    _assertion("f4", Z, "시럽", "넣지 않는다", neg=True),
])]


async def _b1(db, pool):
    check = _checker("B1")
    user, s, _ = await _seed(db)
    w = NS(user=user, store=s, member=await _member(db, s, user))
    src = await _hashed_source(db, s, user)
    await _process_w3a(db, pool, s, user, src, _B1_LEGACY, run_tag=901, fact_assembly=False)
    (legacy,) = [c["card_id"] for c in await _store_cards(db, s)]
    first = await _approve(db, pool, w, legacy, "w3a-b1-legacy")
    check("레거시 카드 공개 PUBLISHED", first.status == "PUBLISHED")
    snap = await _index(pool, s)
    card = snap.card(str(legacy))
    check("fact_revisions == ()·entity_id == card_id·RAW 블록",
          snap.fact_revisions == () and card.entity_id == str(legacy)
          and card.blocks and all(b.kind == "RAW" and b.raw_span_id for b in card.blocks))
    spans = {b.raw_span_id for b in card.blocks}
    before_card = card.model_dump()
    before_spans = [r.model_dump() for r in snap.raw_spans if r.raw_span_id in spans]
    before_row = await _snapshot_row(db, s, first.snapshot_id)

    src_z = await _hashed_source(db, s, user)
    await _process_w3a(db, pool, s, user, src_z, _B_Z, run_tag=902)
    z = await _entity(db, s, Z)
    (card_z,) = await _entity_cards(db, s, z)
    second = await _approve(db, pool, w, card_z, "w3a-b1-fact")
    snap2 = await _index(pool, s)
    check("사실 카드 더 공개 — PUBLISHED·사실 실림",
          second.status == "PUBLISHED" and snap2.snapshot_id != snap.snapshot_id
          and len(snap2.fact_revisions) == 4)
    check("레거시 PublishedCard·RawSpan 완전히 같다",
          snap2.card(str(legacy)).model_dump() == before_card
          and [r.model_dump() for r in snap2.raw_spans if r.raw_span_id in spans]
          == before_spans)
    check("앞 snapshot 행(snapshot_hash 포함) 불변",
          await _snapshot_row(db, s, first.snapshot_id) == before_row
          and before_row["snapshot_hash"] == snap.snapshot_hash)


async def _b2(db, pool):
    check = _checker("B2")
    w = await _fact_store(db, pool, _B_Z, run_tag=911)
    w.z = await _entity(db, w.store, Z)
    (w.card,) = await _entity_cards(db, w.store, w.z)
    draft = (await _card(db, w.store, w.card))["draft_version_id"]
    result = await _approve(db, pool, w, w.card, "w3a-b2")
    check("사실 카드 공개 PUBLISHED", result.status == "PUBLISHED")
    snap = await _index(pool, w.store)
    card = snap.card(str(w.card))
    check("entity_id == 음료Z 대상·card_version 은 승인 판",
          card.entity_id == str(w.z) and card.card_version_id == str(draft))
    shape, pinned = await _pinned(db, w.store, draft)
    check("블록이 고정과 같은 순서·사실", _shape(card) == shape
          and all(kind != "RAW" for _, kind, _, _ in shape))
    check("fact_revisions == 고정 판 전부",
          [f.fact_revision_id for f in snap.fact_revisions] == [str(r) for r in sorted(pinned)])
    water = await _revision_of(db, w.store, w.src, "물")
    step1 = await _revision_of(db, w.store, w.src, "얼음 담기")
    step2 = await _revision_of(db, w.store, w.src, "샷 붓기")
    fact_water = snap.fact(str(water["head_revision_id"]))
    check("수치 Quantity(225, ml)·규격 ICE",
          fact_water.quantity == Quantity(value="225", unit="ml")
          and fact_water.variant == Variant(temperature="ICE") and fact_water.value_text is None)
    check("단계 2 requires == (단계 1 판,)",
          snap.fact(str(step2["head_revision_id"])).requires
          == (str(step1["head_revision_id"]),)
          and snap.fact(str(step2["head_revision_id"])).order == 2)
    prov = {(r["fact_revision_id"], r["occurrence_id"], r["source_id"]) for r in await db.fetch(
        "select p.fact_revision_id, p.occurrence_id, o.source_id "
        "from card_version_fact_provenance p join fact_occurrences o "
        "  on o.store_id = p.store_id and o.occurrence_id = p.occurrence_id "
        "where p.store_id=$1 and p.card_version_id=$2", w.store, draft)}
    published = {(int(f.fact_revision_id), int(p.occurrence_id), int(p.source_id))
                 for f in snap.fact_revisions for p in f.provenance}
    check("근거 == card_version_fact_provenance occurrence·sha256 지문",
          published == prov and len(prov) == 4
          and all(p.source_content_hash == "sha256:" + _hex(w.store, w.src)
                  and p.owner_answer_id is None
                  for f in snap.fact_revisions for p in f.provenance))
    docs = await db.fetch(
        "select d.block_id from knowledge_publications k "
        "join r_index_publications p on p.store_id = k.store_id "
        "  and p.snapshot_id = k.current_snapshot_id "
        "join r_index_documents d on d.store_id = p.store_id and d.prepared_id = p.prepared_id "
        "where k.store_id=$1 and d.card_id=$2 order by d.block_id", w.store, w.card)
    check("R 색인 문서 — 블록마다 1",
          [r["block_id"] for r in docs] == sorted(b for b, _, _, _ in shape))
    w.card_dump = card.model_dump()
    w.facts_dump = {f.fact_revision_id: f.model_dump() for f in snap.fact_revisions}
    w.snapshot_id = result.snapshot_id
    return w


async def _b3(db, pool):
    check = _checker("B3")
    fact = _assertion("f1", "라테", "milk_amount", "225", "ml", variant="HOT")
    fact["original_assertion"] = "HOT 라테 우유 225ml"
    w = await _fact_store(db, pool, [("합성 자료 본문 B3 — HOT 라테 우유 225ml", [fact])],
                          run_tag=921)
    (card_id,) = [c["card_id"] for c in await _store_cards(db, w.store)]
    result = await _approve(db, pool, w, card_id, "w3a-b3")
    check("라테 사실 카드 공개 PUBLISHED", result.status == "PUBLISHED")
    question = "HOT 라테 우유 얼마나?"
    found = await hybrid_search(pool, store_id=w.store, question=question,
                                query_vector=list(_VECTOR))
    card = found.snapshot.card(str(card_id))
    (published_fact,) = found.snapshot.fact_revisions
    check("공개판 사실 — 원문·수치·규격",
          published_fact.original_assertion == "HOT 라테 우유 225ml"
          and published_fact.quantity == Quantity(value="225", unit="ml")
          and published_fact.variant == Variant(temperature="HOT"))
    check("hybrid_search 후보에 그 블록",
          any(c.card_id == str(card_id) and c.block_id in {b.block_id for b in card.blocks}
              for c in found.candidates))
    session = await db.fetchval(
        "insert into chat_sessions (store_id, member_id, contract_version) "
        "values ($1,$2,'v2') returning session_id", w.store, w.member)
    decision = decide(found, store_id=w.store, question=question)
    saved = await save_answer(
        pool, store_id=w.store, member_id=w.member, session_id=session,
        request_id="w3a-b3-question", question=question, snapshot=found.snapshot,
        plan=decision.plan, resolved=decision.resolved,
        confirmed_slots=decision.confirmed_slots, semantic_context=decision.semantic_context)
    response = saved.response
    citations = [(c.fact_revision_id, c.source_id, c.block_id) for c in response.citations]
    print(f"INFO W3a B3 공개판(제목 {card.title!r}) → action={response.action} "
          f"reason={decision.plan.escalation_reason} citations={citations}")
    (provenance,) = published_fact.provenance
    name = "R 답변 ANSWER·인용 사실·자료 == 공개판"
    ok = bool(response.action == "ANSWER" and response.citations
              and response.citations[0].fact_revision_id == published_fact.fact_revision_id
              and response.citations[0].source_id == provenance.source_id == str(w.src))
    if not ok:
        print(f"FAIL W3a B3 {name} (action={response.action}, "
              f"reason={decision.plan.escalation_reason})")
    check(name, ok)


async def _b4(db, pool, w):
    check = _checker("B4")
    src = await _hashed_source(db, w.store, w.user)
    await _process_w3a(db, pool, w.store, w.user, src, [(
        "합성 자료 본문 B4 — 음료Z ICE 물 225ml", [
            _assertion("f1", Z, "물", "225", "ml", variant="ICE")])], run_tag=931)
    added = await db.fetch("select fact_revision_id, disposition, reason from fact_occurrences "
                           "where store_id=$1 and source_id=$2", w.store, src)
    check("새 자료 occurrence 는 같은 head 판·EXISTING_CARD 대기",
          len(added) == 1 and str(added[0]["fact_revision_id"]) in w.facts_dump
          and (added[0]["disposition"], added[0]["reason"])
          == ("REVIEW_PENDING", fact_cards.REASON_EXISTING_CARD))
    result = await _publish(pool, w.store, w.member, w.user, [], "w3a-b4-republish")
    snap = await _index(pool, w.store)
    check("재공개 PUBLISHED·새 snapshot",
          result.status == "PUBLISHED" and result.snapshot_id != w.snapshot_id)
    check("PublishedCard·FactRevision 이 B2 와 같다(근거 늘지 않음)",
          snap.card(str(w.card)).model_dump() == w.card_dump
          and {f.fact_revision_id: f.model_dump() for f in snap.fact_revisions}
          == w.facts_dump)


async def _b5(db, pool):
    check = _checker("B5")
    w = await _fact_store(db, pool, _B_Z, run_tag=941)
    (card_id,) = [c["card_id"] for c in await _store_cards(db, w.store)]
    check("사실 카드 먼저 공개", (await _approve(db, pool, w, card_id, "w3a-b5-a")).status
          == "PUBLISHED" and (await _index(pool, w.store)).fact_revisions)
    async with db.transaction():
        draft = (await _card(db, w.store, card_id))["draft_version_id"]
        edited = await cards_repo.create_draft(
            db, w.store, card_id, title="음료Z 점주 편집", content="합성 점주 편집 본문",
            actor_id=w.user, source_version_id=draft)
    result = await _approve(db, pool, w, card_id, "w3a-b5-b")
    snap = await _index(pool, w.store)
    card = snap.card(str(card_id))
    check("점주 편집 판 공개 PUBLISHED", result.status == "PUBLISHED"
          and card.card_version_id == str(edited))
    check("편집 판은 RAW 블록·entity_id == card_id·그 카드 사실 없음(알려진 한계)",
          card.entity_id == str(card_id)
          and all(b.kind == "RAW" and b.raw_span_id for b in card.blocks)
          and snap.fact_revisions == ())


async def _two_card_store(db, pool, run_tag):
    """음료Z·컵 사실 카드 둘. 컵 카드를 먼저 공개해 기존 공개판을 만든다."""
    w = await _fact_store(db, pool, [("합성 자료 본문 B6 — 음료Z ICE 물 225ml, 컵 355ml", [
        _assertion("f1", Z, "물", "225", "ml", variant="ICE"),
        _assertion("f2", Z, "얼음 담기", "컵에 얼음", variant="ICE", order=1),
        _assertion("f3", CUP, "크기", "355", "ml")])], run_tag=run_tag)
    w.z, w.cup = await _entity(db, w.store, Z), await _entity(db, w.store, CUP)
    (w.card_z,) = await _entity_cards(db, w.store, w.z)
    (w.card_cup,) = await _entity_cards(db, w.store, w.cup)
    first = await _approve(db, pool, w, w.card_cup, f"w3a-{run_tag}-cup")
    assert first.status == "PUBLISHED", first
    w.before = (await _index(pool, w.store)).model_dump()
    w.publication = dict(await db.fetchrow(
        "select * from knowledge_publications where store_id=$1", w.store))
    w.draft_z = (await _card(db, w.store, w.card_z))["draft_version_id"]
    return w


async def _unchanged(db, pool, w):
    return ((await _index(pool, w.store)).model_dump() == w.before
            and dict(await db.fetchrow("select * from knowledge_publications where store_id=$1",
                                       w.store)) == w.publication
            and (await _card(db, w.store, w.card_z))["published_version_id"] is None)


async def _b6(db, pool):
    check = _checker("B6")
    w = await _two_card_store(db, pool, 951)
    water = await _revision_of(db, w.store, w.src, "물")
    deleted = await db.execute(
        "delete from card_version_fact_provenance where store_id = $1 "
        "and card_version_id = $2 and fact_revision_id = $3",
        w.store, w.draft_z, water["head_revision_id"])
    check("근거 행 1 삭제", deleted == "DELETE 1")
    result = await _approve(db, pool, w, w.card_z, "w3a-b6")
    check("공개 NO_PROVENANCE", result.status == "NO_PROVENANCE")
    check("기존 공개판·발행 포인터·카드 공개 포인터 그대로", await _unchanged(db, pool, w))


async def _b7(db, pool):
    check = _checker("B7")
    w = await _two_card_store(db, pool, 961)
    cup_rev = await _revision_of(db, w.store, w.src, "크기")
    block, position = (await db.fetchrow(
        "select block_id, max(position) from card_block_facts where store_id=$1 "
        "and card_version_id=$2 group by block_id order by block_id limit 1",
        w.store, w.draft_z))
    await db.execute(
        "insert into card_block_facts (store_id, card_version_id, block_id, fact_revision_id, "
        "position) values ($1,$2,$3,$4,$5)",
        w.store, w.draft_z, block, cup_rev["head_revision_id"], position + 1)
    result = await _approve(db, pool, w, w.card_z, "w3a-b7")
    check("다른 대상 판이 섞인 판 공개 INVALID_CONTENT(예외 아님)",
          result.status == "INVALID_CONTENT")
    check("기존 공개판·발행 포인터·카드 공개 포인터 그대로", await _unchanged(db, pool, w))


async def verify(pool, admin) -> None:
    db = admin
    w, group = await _l1(db, pool)
    await _l2(db, pool)
    await _l3(db, pool, w)
    await _l4(db, pool, w, group)
    p, card_id = await _p1(db)
    await _p2_p3(db, p, card_id)
    await _p4(db, p, card_id)
    await _p5(db)
    await _p6_p7(db)
    await _p8(db)
    await _p9(db)
    await _p10(db)
    await _p11(db, p, card_id)
    await _p12(db)
    e = await _e1(db, pool)
    await _e2(db, pool, e)
    await _e3(db, pool, e)
    await _e4(db, pool)
    await _e5(db, pool, e)
    await _e6(db, pool)
    await _e7(db, pool)
    await _e8(db, pool)
    await _e9(db, pool)
    await _e10(db, pool)
    await _e11(db, pool)
    await _e12(db, pool)
    await _b1(db, pool)
    b = await _b2(db, pool)
    await _b3(db, pool)
    await _b4(db, pool, b)
    await _b5(db, pool)
    await _b6(db, pool)
    await _b7(db, pool)
    print("PASS W3a all scenarios")
