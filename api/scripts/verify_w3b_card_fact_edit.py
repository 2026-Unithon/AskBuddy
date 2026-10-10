"""실제 DB: W3b 점주 사실 카드 편집 합성 종단 검증. 모델·임베딩은 합성 대역이다(비용 0).

verify_w_publication_flow.verify() 끝에서 W3a 다음에 부른다(verify_r_schema_rebuild 가 부르는 W 검증).
시나리오마다 새 합성 매장을 만든다. 사실 카드는 verify_w3a_fact_assembly 의 도우미로 만든다.
  M1  migration — change_kind OWNER_ADD, 자료 OWNER_TEXT(작업 안 만듦), 편집 기록 불변·매장 FK
  R1~R3  읽기 (Task 3)
  D1  사실 카드에 PATCH /draft 는 409 FACT_CARD_TEXT_EDIT_BLOCKED, 판·포인터 그대로
  D2  레거시 카드는 PATCH /draft 가 그대로 새 판을 만든다, 상세 fact_card 가 사실 카드만 True
  P1~P3  분석 (Task 4)
  S1~S12 저장 (Task 5)
  A1~A3  재승인·R 소비·과거 인용 (Task 7)
출력 줄 머리는 `PASS W3b <시나리오 id> <설명>`.
"""
import asyncio
import json
from contextlib import ExitStack
from decimal import Decimal
from types import SimpleNamespace as NS
from unittest.mock import patch

import asyncpg

import app.config

from app.cards import router as card_router
from app.cards.fact_edit_schemas import FactEditRequest, FactParseRequest, FactVariant
from app.cards.schemas import DraftUpdateRequest
from app.config import Settings
from app.contracts.snapshot import KnowledgeContent
from app.db_session import ShortSession
from app.errors import ApiError
from app.ingest import extract, fact_cards
from app.ingest import repository as ingest_repo
from app.ingest.card_plan import ValidatedBlock, ValidatedCard
from app.ingest import fact_revisions as fr
from app.ingest.extract import gemini
from app.ingest.schemas import ExtractedAssertion, FactExtractionResult
from app.ingest.entities import lock_store_knowledge
from app.learn.answer_storage import save_answer
from app.learn.planner import decide
from app.publish.service import delete_source
from app.reg.hybrid import hybrid_search
from verify_w3a_fact_assembly import (_B1_LEGACY, _B_Z, _VECTOR, Z, _approve, _assertion, _card,
                                      _entity, _fact_store, _fake_embedder, _hashed_source,
                                      _index, _member, _pins, _process_w3a, _snapshot_row,
                                      _store_cards, _versions)
from verify_w_entity_revision import _MODEL_SETTINGS
from verify_w_partial_extraction import _seed


def _checker(scenario: str):
    def check(name: str, ok: bool) -> None:
        assert ok, f"W3b {scenario} {name}"
        print(f"PASS W3b {scenario} {name}")
    return check


def _w3b_settings(*, edit=True):
    return Settings(_env_file=None, w_entity_revision_enabled=True, w_fact_assembly_enabled=True,
                    w_fact_card_edit_enabled=edit)


def _owner_claims(w):
    return {"user_id": w.user, "store_id": w.store, "role": "OWNER"}


class _Rollback(Exception):
    pass


async def _raises(db, sql, *args, exc=asyncpg.PostgresError):
    """저장점 안에서 실행해 지정한 DB 오류가 나는지 본다. 오류 객체를 돌려준다(없으면 None)."""
    tr = db.transaction()
    await tr.start()
    try:
        await db.execute(sql, *args)
    except exc as error:
        await tr.rollback()
        return error
    await tr.rollback()
    return None


async def _job_counts(db, store):
    return (await db.fetchval("select count(*) from ingest_jobs where store_id=$1", store),
            await db.fetchval("select count(*) from ingest_job_sources where store_id=$1", store))


async def _m1(db, pool):
    check = _checker("M1")
    w = await _fact_store(db, pool, _B_Z, run_tag=1101)
    # 1. change_kind OWNER_ADD — 실제 판 하나를 이어 붙여 보고 롤백한다
    fact = await db.fetchrow("select fact_id, head_revision_id from knowledge_facts "
                             "where store_id=$1 order by fact_id limit 1", w.store)
    tr = db.transaction()
    await tr.start()
    try:
        row = await fr._lock_fact(db, w.store, fact["fact_id"], fact["head_revision_id"])
        head, other = await fr._head_of(db, w.store, row["head_revision_id"])
        shape = fr._apply_change(head, other, fr.FactChange(original_assertion="합성 추가 문장"))
        new_id = await fr._append_revision(
            db, w.store, knowledge_fact_row=row, shape=shape, entity_id=row["entity_id"],
            change_kind="OWNER_ADD", actor_id=w.user, reason="카드 사실 추가")
        kind = await db.fetchval("select change_kind from fact_revision_meta "
                                 "where store_id=$1 and fact_revision_id=$2", w.store, new_id)
    finally:
        await tr.rollback()
    check("fact_revision_meta 에 OWNER_ADD 메타가 들어간다(롤백함)", kind == "OWNER_ADD")
    definition = await db.fetchval(
        "select pg_get_constraintdef(oid) from pg_constraint where "
        "conname='fact_revision_meta_change_kind_check' and conrelid='fact_revision_meta'::regclass")
    check("change_kind 허용값 = 기존 5종 + OWNER_ADD",
          all(k in definition for k in ("EXTRACTION", "OWNER_CORRECTION", "OWNER_ANSWER", "RELINK",
                                        "LEGACY_CORRECTION", "OWNER_ADD")))
    # 2. OWNER_TEXT 자료는 추출 작업을 만들지 않고 VOICE 는 만든다
    user, s, _ = await _seed(db)
    before = await _job_counts(db, s)
    await db.execute("insert into sources (store_id, uploaded_by, source_type, title, status) "
                     "values ($1,$2,'OWNER_TEXT','카드 직접 입력 · 합성','DONE')", s, user)
    check("OWNER_TEXT 자료를 넣어도 ingest_jobs·ingest_job_sources 가 늘지 않는다",
          await _job_counts(db, s) == before)
    await db.execute("insert into sources (store_id, uploaded_by, source_type, title, status) "
                     "values ($1,$2,'VOICE','합성 음성','UPLOADED')", s, user)
    after = await _job_counts(db, s)
    check("VOICE 자료는 지금처럼 작업이 하나 생긴다",
          after == (before[0] + 1, before[1] + 1))
    bad = await _raises(db, "insert into sources (store_id, uploaded_by, source_type, status) "
                            "values ($1,$2,'NOPE','DONE')", s, user)
    check("모르는 source_type 은 여전히 거절", isinstance(bad, asyncpg.CheckViolationError))
    # 3. card_fact_edits — 불변, 매장 FK
    card = await _card(db, w.store, (await _store_cards(db, w.store))[0]["card_id"])
    edit_sql = ("insert into card_fact_edits (store_id, card_id, idempotency_key, request_hash, "
                "from_version_id, changed, result, actor_id) "
                "values ($1,$2,'key-m1-000001',repeat('a',64),$3,false,'{}'::jsonb,$4) "
                "returning edit_id")
    edit_id = await db.fetchval(edit_sql, w.store, card["card_id"], card["draft_version_id"], w.user)
    updated = await _raises(db, "update card_fact_edits set changed=false where edit_id=$1", edit_id)
    check("card_fact_edits UPDATE 는 예외(불변)", updated is not None and "불변" in str(updated))
    dup = await _raises(db, edit_sql.replace("returning edit_id", ""), w.store, card["card_id"],
                        card["draft_version_id"], w.user)
    check("같은 매장·카드·멱등 키는 하나만", isinstance(dup, asyncpg.UniqueViolationError))
    other_user, other_store, _ = await _seed(db)
    cross = await _raises(db, edit_sql.replace("returning edit_id", ""), other_store,
                          card["card_id"], card["draft_version_id"], other_user)
    check("다른 매장 card_id 로 넣으면 FK 위반",
          isinstance(cross, asyncpg.ForeignKeyViolationError))
    mismatch = await _raises(
        db, "insert into card_fact_edits (store_id, card_id, idempotency_key, request_hash, "
            "from_version_id, changed, owner_text, result, actor_id) "
            "values ($1,$2,'key-m1-000002',repeat('a',64),$3,false,'글','{}'::jsonb,$4)",
        w.store, card["card_id"], card["draft_version_id"], w.user)
    check("자료 id 와 전문은 함께 있거나 함께 없어야 한다",
          isinstance(mismatch, asyncpg.CheckViolationError))


async def _d1(db, pool):
    check = _checker("D1")
    w = await _fact_store(db, pool, _B_Z, run_tag=1111)
    (card_id,) = [c["card_id"] for c in await _store_cards(db, w.store)]
    before = await _card(db, w.store, card_id)
    versions = await _versions(db, w.store, card_id)
    req = DraftUpdateRequest(title="합성 제목", content="합성 본문",
                             expected_version_id=before["draft_version_id"])
    error = None
    with patch("app.config.get_settings", lambda: _w3b_settings()):
        try:
            await card_router.update_draft(card_id, req, ShortSession(pool), _owner_claims(w))
        except ApiError as e:
            error = e
    check("사실 카드 PATCH /draft 는 409 FACT_CARD_TEXT_EDIT_BLOCKED",
          error is not None and error.status_code == 409
          and error.code == "FACT_CARD_TEXT_EDIT_BLOCKED")
    after = await _card(db, w.store, card_id)
    check("카드 판 수·초안 포인터·제목·본문 그대로",
          len(await _versions(db, w.store, card_id)) == len(versions)
          and after["draft_version_id"] == before["draft_version_id"]
          and after["title"] == before["title"] and after["content"] == before["content"])


async def _d2(db, pool):
    check = _checker("D2")
    user, s, _ = await _seed(db)
    w = type("W", (), {})()
    w.user, w.store, w.member = user, s, await _member(db, s, user)
    src = await _hashed_source(db, s, user)
    await _process_w3a(db, pool, s, user, src, _B1_LEGACY, run_tag=1121, fact_assembly=False)
    (legacy,) = [c["card_id"] for c in await _store_cards(db, s)]
    legacy_card = await _card(db, s, legacy)
    versions = await _versions(db, s, legacy)
    with patch("app.config.get_settings", lambda: _w3b_settings()):
        detail = await card_router.get_card(legacy, ShortSession(pool), _owner_claims(w))
        check("레거시 카드 상세 fact_card=False, fact_edit_enabled=True(플래그 켬)",
              detail.fact_card is False and detail.fact_edit_enabled is True)
        req = DraftUpdateRequest(title="합성 레거시 편집", content="합성 레거시 본문",
                                 expected_version_id=legacy_card["draft_version_id"])
        await card_router.update_draft(legacy, req, ShortSession(pool), _owner_claims(w))
    new_versions = await _versions(db, s, legacy)
    check("레거시 카드는 PATCH /draft 가 새 OWNER_EDIT 판을 만든다",
          len(new_versions) == len(versions) + 1
          and any(v["change_source"] == "OWNER_EDIT" for v in new_versions))
    # 사실 카드의 상세
    f = await _fact_store(db, pool, _B_Z, run_tag=1122)
    (fact_card,) = [c["card_id"] for c in await _store_cards(db, f.store)]
    with patch("app.config.get_settings", lambda: _w3b_settings()):
        detail = await card_router.get_card(fact_card, ShortSession(pool), _owner_claims(f))
    check("사실 카드 상세 fact_card=True", detail.fact_card is True and detail.fact_edit_enabled)
    with patch("app.config.get_settings", lambda: _w3b_settings(edit=False)):
        detail = await card_router.get_card(fact_card, ShortSession(pool), _owner_claims(f))
    check("플래그 끄면 fact_edit_enabled=False(fact_card 는 그대로)",
          detail.fact_card is True and detail.fact_edit_enabled is False)


async def _two_source_fact_store(db, pool, *, run_tag):
    """자료 둘(ICE 수치·단계·부정 + HOT 수치·조건·예외)에서 온 사실 카드가 있는 합성 매장."""
    w = await _fact_store(db, pool, _B_Z, run_tag=run_tag)
    src_b = await _hashed_source(db, w.store, w.user)
    await _process_w3a(db, pool, w.store, w.user, src_b, [("합성 자료 본문 B2", [
        _assertion("g1", Z, "물", "275", "ml", variant="HOT", conditions=["바쁠 때"],
                   exceptions=["디카페인"]),
    ])], run_tag=run_tag + 1)
    w.src_b = src_b
    return w


async def _facts_view(pool, w, card_id, *, edit=True, claims=None):
    with patch("app.config.get_settings", lambda: _w3b_settings(edit=edit)):
        return await card_router.get_card_facts(card_id, ShortSession(pool),
                                                claims or _owner_claims(w))


async def _fact_card_id(db, store):
    for c in await _store_cards(db, store):
        blocks, facts, _ = await _pins(db, store, c["draft_version_id"])
        if facts:
            return c["card_id"], c["draft_version_id"], blocks, facts
    raise AssertionError("사실 카드가 없다")


async def _r1(db, pool):
    check = _checker("R1")
    w = await _two_source_fact_store(db, pool, run_tag=1131)
    card_id, version_id, blocks, facts = await _fact_card_id(db, w.store)
    view = await _facts_view(pool, w, card_id)
    check("초안 판·제목·대상·편집 가능",
          view.version_id == version_id and view.editable and view.entity_problem is None
          and view.entity_id is not None and view.entity_name == Z)
    check("블록 수·종류·순서가 card_version_blocks 와 같다",
          [(b.block_id, b.kind, b.order) for b in view.blocks]
          == [(b[0], b[1], b[2]) for b in blocks])
    stored = {}
    for block_id, rid, pos in facts:
        stored.setdefault(block_id, []).append((pos, rid))
    check("줄 순서·위치가 card_block_facts 와 같다",
          all([(f.position, f.fact_revision_id) for f in b.facts] == sorted(stored.get(b.block_id, []))
              for b in view.blocks))
    rows = [f for b in view.blocks for f in b.facts]
    for row in rows:
        pinned = await db.fetchval(
            "select count(*) from card_version_fact_provenance where store_id=$1 "
            "and card_version_id=$2 and fact_revision_id=$3", w.store, version_id,
            row.fact_revision_id)
        assert len(row.origins) == pinned, f"W3b R1 origins {row.fact_revision_id}"
    check("줄마다 origins 수가 고정 근거 행 수와 같다", all(r.origins for r in rows))
    source_ids = {o.source_id for r in rows for o in r.origins}
    check("두 자료의 근거가 모두 보인다", {w.src, w.src_b} <= source_ids)
    water = next(r for r in rows if r.value == "225")
    check("수치 줄 value/unit/규격", water.unit == "ml" and water.variant.temperature == "ICE"
          and water.polarity == "AFFIRM")
    neg = [r for r in rows if r.polarity == "NEGATE"]
    check("부정 줄 polarity NEGATE", len(neg) == 1)
    hot = next(r for r in rows if r.value == "275")
    check("조건·예외 그대로", hot.conditions == ["바쁠 때"] and hot.exceptions == ["디카페인"])
    steps = [r for r in rows if r.step_order is not None]
    check("단계 번호와 선행 라벨", len(steps) == 2 and any(
        req.label == f"{steps[0].step_order}번" for s_ in steps for req in s_.requires))
    check("판 정정 이력이 없는 줄은 이전 문장이 없다", all(r.previous_sentence is None for r in rows))
    check("head 가 그대로면 막힘 없음", all(r.edit_block is None for r in rows))
    # 자료 하나를 tombstone — 근거가 DELETED 로 보이고 줄은 남는다
    async with db.transaction():
        await delete_source(db, store_id=w.store, source_id=w.src)
    after = await _facts_view(pool, w, card_id)
    origins = [o for b in after.blocks for f in b.facts for o in f.origins if o.source_id == w.src]
    check("tombstone 한 자료의 근거는 DELETED, 줄 수는 그대로",
          origins and all(o.source_availability == "DELETED" for o in origins)
          and sum(len(b.facts) for b in after.blocks) == len(rows))
    other = [o for b in after.blocks for f in b.facts for o in f.origins if o.source_id == w.src_b]
    check("다른 자료는 AVAILABLE", other and all(o.source_availability == "AVAILABLE" for o in other))


async def _r2(db, pool):
    check = _checker("R2")
    w = await _fact_store(db, pool, _B_Z, run_tag=1141)
    card_id, *_ = await _fact_card_id(db, w.store)
    other_user, other_store, _ = await _seed(db)
    other = {"user_id": other_user, "store_id": other_store, "role": "OWNER"}
    error = None
    try:
        await _facts_view(pool, w, card_id, claims=other)
    except ApiError as e:
        error = e
    check("다른 매장 OWNER 는 404 CARD_NOT_FOUND",
          error is not None and error.status_code == 404 and error.code == "CARD_NOT_FOUND")
    staff = {"user_id": w.user, "store_id": w.store, "role": "STAFF"}
    error = None
    try:
        await _facts_view(pool, w, card_id, claims=staff)
    except ApiError as e:
        error = e
    check("STAFF 는 403 OWNER_ONLY",
          error is not None and error.status_code == 403 and error.code == "OWNER_ONLY")
    user, s, _ = await _seed(db)
    legacy_w = type("W", (), {})()
    legacy_w.user, legacy_w.store = user, s
    await _member(db, s, user)
    src = await _hashed_source(db, s, user)
    await _process_w3a(db, pool, s, user, src, _B1_LEGACY, run_tag=1142, fact_assembly=False)
    (legacy,) = [c["card_id"] for c in await _store_cards(db, s)]
    error = None
    try:
        await _facts_view(pool, legacy_w, legacy, claims=_owner_claims(legacy_w))
    except ApiError as e:
        error = e
    check("레거시 카드는 409 NOT_FACT_CARD",
          error is not None and error.status_code == 409 and error.code == "NOT_FACT_CARD")
    error = None
    try:
        await _facts_view(pool, w, card_id + 100000)
    except ApiError as e:
        error = e
    check("없는 카드 id 는 404", error is not None and error.status_code == 404)


async def _relink(db, store, fact_id, actor):
    """같은 문장·값으로 RELINK 판을 잇는다(W2 병합·분리가 이어 붙이는 방식과 같다)."""
    async with db.transaction():
        await lock_store_knowledge(db, store)
        row = await fr._lock_fact(db, store, fact_id, None)
        head, other = await fr._head_of(db, store, row["head_revision_id"])
        shape = fr._apply_change(head, other, fr.FactChange(
            original_assertion=head["original_assertion"]))
        return await fr._append_revision(
            db, store, knowledge_fact_row=row, shape=shape, entity_id=row["entity_id"],
            change_kind="RELINK", actor_id=actor, reason="합성 재연결")


async def _r3(db, pool):
    check = _checker("R3")
    w = await _fact_store(db, pool, _B_Z, run_tag=1151)
    card_id, version_id, _, facts = await _fact_card_id(db, w.store)
    base = await _facts_view(pool, w, card_id)
    rows = [f for b in base.blocks for f in b.facts]
    water = next(r for r in rows if r.value == "225")
    check("처음에는 어떤 줄도 막히지 않는다", all(r.edit_block is None for r in rows))
    new_id = await _relink(db, w.store, water.fact_id, w.user)
    view = await _facts_view(pool, w, card_id)
    after = next(f for b in view.blocks for f in b.facts if f.fact_id == water.fact_id)
    check("RELINK 만 이어진 head 는 막히지 않고 카드는 고정 판을 그대로 보인다",
          after.edit_block is None and after.fact_revision_id == water.fact_revision_id
          and view.editable)
    head = await db.fetchval("select head_revision_id from knowledge_facts where store_id=$1 "
                             "and fact_id=$2", w.store, water.fact_id)
    check("head 는 RELINK 새 판으로 옮겨졌다", head == new_id != water.fact_revision_id)
    # 다른 곳에서 정정 — 이어진 head 위에 OWNER_CORRECTION
    await fr.revise_fact(db, w.store, fact_id=water.fact_id, expected_head_revision_id=new_id,
                         change=fr.FactChange(value="230", original_assertion="합성 정정 230ml"),
                         change_kind="OWNER_CORRECTION", actor_id=w.user, reason="합성 정정")
    view = await _facts_view(pool, w, card_id)
    changed = next(f for b in view.blocks for f in b.facts if f.fact_id == water.fact_id)
    others = [f for b in view.blocks for f in b.facts if f.fact_id != water.fact_id]
    check("다른 곳 정정은 CHANGED_ELSEWHERE, 나머지 줄은 영향 없음",
          changed.edit_block == "CHANGED_ELSEWHERE" and all(f.edit_block is None for f in others))
    flag_off = await _facts_view(pool, w, card_id, edit=False)
    check("플래그를 끄면 editable=False(읽기는 된다)",
          flag_off.editable is False and len(flag_off.blocks) == len(view.blocks))


_FACT_TABLES = ("knowledge_facts", "fact_revisions", "card_versions")


async def _write_counts(db, store):
    return tuple([await db.fetchval(f"select count(*) from {t} where store_id=$1", store)
                  for t in _FACT_TABLES])


async def _parse(pool, w, card_id, req, *, settings=None, real_call=None, claims=None):
    """POST /cards/{id}/facts/parse 라우터 함수를 부른다. real_call 이 있으면 real 모드 + 합성 모델 대역."""
    settings = settings or _w3b_settings()
    with ExitStack() as stack:
        replacements = [
            (app.config, "get_settings", lambda: settings),
            (card_router, "get_pool", lambda: pool),
        ]
        if real_call is not None:
            replacements += [
                (extract, "get_settings", lambda: NS(ingest_mode="real")),
                (gemini, "get_settings", lambda: NS(**vars(_MODEL_SETTINGS))),
                (gemini, "_call", real_call),
            ]
        else:
            replacements.append((extract, "get_settings", lambda: NS(ingest_mode="mock")))
        for obj, name, replacement in replacements:
            stack.enter_context(patch.object(obj, name, replacement))
        return await card_router.parse_card_facts(card_id, req, ShortSession(pool),
                                                  claims or _owner_claims(w))


async def _p1(db, pool):
    check = _checker("P1")
    w = await _fact_store(db, pool, _B_Z, run_tag=1161)
    card_id, *_ = await _fact_card_id(db, w.store)
    before = await _write_counts(db, w.store)
    calls = []

    async def fake_call(prompt, media, schema=None, max_output_tokens=None):
        assert schema is FactExtractionResult, schema
        calls.append(prompt)
        payload = json.loads(prompt.split(gemini.PARSE_INPUT_MARKER + "\n", 1)[1])
        body = FactExtractionResult(assertions=[
            ExtractedAssertion(local_ref="o1", original_assertion="ICE 물은 230ml", subject=payload["entity_name"],
                               attribute="양", value="230", unit="ml", variant="ICE", confidence=0.9),
            ExtractedAssertion(local_ref="o2", original_assertion="다른음료Q 샷은 2개", subject="다른음료Q",
                               attribute="샷", value="2", unit="개", confidence=0.9),
        ])
        return gemini.CallResult(body.model_dump_json(), {}, "STOP")

    out = await _parse(pool, w, card_id, FactParseRequest(text="ICE 물은 230ml. 다른음료Q 샷은 2개"),
                       real_call=fake_call)
    check("모델 대역 호출 1회·제안 2·결과 경고 MULTIPLE_FACTS",
          len(calls) == 1 and len(out.proposals) == 2 and out.warnings == ["MULTIPLE_FACTS"])
    check("둘째 제안만 SUBJECT_MISMATCH",
          "SUBJECT_MISMATCH" not in out.proposals[0].warnings
          and "SUBJECT_MISMATCH" in out.proposals[1].warnings)
    check("프롬프트 입력에 DB id 가 없다",
          set(json.loads(calls[0].split(gemini.PARSE_INPUT_MARKER + "\n", 1)[1]))
          == {"entity_name", "card_variants", "mode", "base_sentence", "text"})
    usage = await db.fetch("select stage, logical_call_id from ai_usage_attempts where store_id=$1 "
        "and logical_call_id like 'card-parse:%'", w.store)
    check("원가 원장 EXTRACT 1행·logical_call_id card-parse:{카드}:…",
          len(usage) == 1 and usage[0]["stage"] == "EXTRACT"
          and usage[0]["logical_call_id"].startswith(f"card-parse:{card_id}:"))
    raw = await db.fetch("select source_id, stage, mode from extraction_raw_responses where store_id=$1 "
        "and logical_call_id like 'card-parse:%'", w.store)
    check("원래 응답 1행 — source_id 없음·EXTRACT·real",
          len(raw) == 1 and raw[0]["source_id"] is None and raw[0]["stage"] == "EXTRACT"
          and raw[0]["mode"] == "real")
    check("사실·판·카드 판 행 수 그대로", await _write_counts(db, w.store) == before)


async def _p2(db, pool):
    check = _checker("P2")
    w = await _fact_store(db, pool, _B_Z, run_tag=1171)
    card_id, *_ = await _fact_card_id(db, w.store)
    before = await _write_counts(db, w.store)
    out = await _parse(pool, w, card_id, FactParseRequest(text="ICE 물은 240ml 넣는다"))
    check("mock 모드 — 제안 1·수치 240 ml", len(out.proposals) == 1
          and out.proposals[0].fact.value == "240" and out.proposals[0].fact.unit == "ml")
    raw = await db.fetch("select mode, stage from extraction_raw_responses where store_id=$1 "
        "and logical_call_id like 'card-parse:%'", w.store)
    check("원래 응답 mode='mock'", len(raw) == 1 and raw[0]["mode"] == "mock")
    check("원가 원장 행 없음(mock 은 원가에 쓰지 않음)",
          await db.fetchval("select count(*) from ai_usage_attempts where store_id=$1 "
                          "and logical_call_id like 'card-parse:%'", w.store) == 0)
    check("사실·판·카드 판 행 수 그대로", await _write_counts(db, w.store) == before)


async def _api_error(coro):
    try:
        await coro
    except ApiError as e:
        return e
    return None


async def _p3(db, pool):
    check = _checker("P3")
    w = await _fact_store(db, pool, _B_Z, run_tag=1181)
    card_id, *_ = await _fact_card_id(db, w.store)
    req = FactParseRequest(text="ICE 물은 240ml")
    e = await _api_error(_parse(pool, w, card_id, req, settings=_w3b_settings(edit=False)))
    check("플래그 끄면 403 FACT_EDIT_DISABLED",
          e is not None and e.status_code == 403 and e.code == "FACT_EDIT_DISABLED")
    other_user, other_store, _ = await _seed(db)
    other = {"user_id": other_user, "store_id": other_store, "role": "OWNER"}
    e = await _api_error(_parse(pool, w, card_id, req, claims=other))
    check("다른 매장 카드는 404 CARD_NOT_FOUND", e is not None and e.status_code == 404)
    user, s, _ = await _seed(db)
    legacy_w = NS(user=user, store=s)
    await _member(db, s, user)
    src = await _hashed_source(db, s, user)
    await _process_w3a(db, pool, s, user, src, _B1_LEGACY, run_tag=1182, fact_assembly=False)
    (legacy,) = [c["card_id"] for c in await _store_cards(db, s)]
    e = await _api_error(_parse(pool, legacy_w, legacy, req))
    check("레거시 카드는 409 NOT_FACT_CARD",
          e is not None and e.status_code == 409 and e.code == "NOT_FACT_CARD")
    e = await _api_error(_parse(pool, w, card_id, req, settings=Settings(
        _env_file=None, w_fact_card_edit_enabled=True, card_fact_parse_max_chars=5)))
    check("글자 수 초과는 422 PARSE_TEXT_TOO_LONG(max_chars)",
          e is not None and e.status_code == 422 and e.code == "PARSE_TEXT_TOO_LONG"
          and e.details == {"max_chars": 5})
    w2 = await _fact_store(db, pool, _B_Z, run_tag=1183)
    _, _, _, other_facts = await _fact_card_id(db, w2.store)
    foreign = FactParseRequest(text="ICE 물은 240ml", mode="MODIFY",
                               base_fact_revision_id=other_facts[0][1])
    e = await _api_error(_parse(pool, w, card_id, foreign))
    check("MODIFY 기준 판이 다른 카드 판이면 422 PARSE_BASE_INVALID",
          e is not None and e.status_code == 422 and e.code == "PARSE_BASE_INVALID")
    _, _, _, own_facts = await _fact_card_id(db, w.store)
    ok = await _parse(pool, w, card_id, FactParseRequest(
        text="ICE 물은 240ml", mode="MODIFY", base_fact_revision_id=own_facts[0][1]))
    check("자기 카드 판이 기준이면 통과", ok.mode == "MODIFY" and len(ok.proposals) == 1)


# ── 저장 (Task 5) ───────────────────────────────────────────────────────────

# 음료Z — ICE 수치 2·단계 3(2번이 1번을 먼저 필요)·부정 메모 2·일반 메모
def _water(value="225"):
    # R 이 답하는 수치 속성(water_amount) — A2 에서 R 소비를 본다
    fact = _assertion("f1", Z, "water_amount", value, "ml", variant="ICE")
    fact["original_assertion"] = f"음료Z ICE 물 {value}ml"
    return fact


_S_Z = [("합성 자료 본문 S — 음료Z ICE 물 225ml, 시럽 20ml, 얼음·샷·뚜껑, 휘핑 없음, 홀더", [
    _water(),
    _assertion("f2", Z, "시럽", "20", "ml", variant="ICE"),
    _assertion("f3", Z, "얼음 담기", "컵에 얼음", variant="ICE", order=1),
    _assertion("f4", Z, "샷 붓기", "샷을 붓는다", variant="ICE", order=2, requires=["f3"]),
    _assertion("f5", Z, "뚜껑 닫기", "뚜껑을 닫는다", variant="ICE", order=3),
    _assertion("f6", Z, "휘핑", "올리지 않는다", neg=True),
    _assertion("f7", Z, "홀더", "끼운다"),
    _assertion("f8", Z, "얼음 추가", "하지 않는다", neg=True),
])]

_COUNT_TABLES = ("knowledge_facts", "fact_revisions", "card_versions", "card_block_facts",
                 "card_fact_edits", "card_review_events", "sources", "fact_occurrences")


async def _counts(db, store):
    return {t: await db.fetchval(f"select count(*) from {t} where store_id=$1", store)
            for t in _COUNT_TABLES}


def _j(value):
    return json.loads(value) if isinstance(value, str) else value


def _rows(view):
    return [f for b in view.blocks for f in b.facts]


def _find(view, **match):
    found = [f for f in _rows(view) if all(getattr(f, k) == v for k, v in match.items())]
    assert len(found) == 1, f"W3b 줄 찾기 {match}: {len(found)}"
    return found[0]


def _fields(f, **over):
    base = {"sentence": f.sentence, "polarity": f.polarity, "value": f.value, "unit": f.unit,
            "conditions": list(f.conditions), "exceptions": list(f.exceptions),
            "step_order": f.step_order}
    base.update(over)
    return base


def _body(view, key, *, modify=None, delete=(), adds=(), reorder=None, expected=None,
          extra_items=()):
    """읽기 화면 → 저장 요청. modify={판 id: 바꿀 칸}, adds=[(종류, (온도, 크기), ADD 항목)]."""
    modify = modify or {}
    blocks = []
    for b in view.blocks:
        facts = list(b.facts)
        if reorder and b.block_id in reorder:
            facts = [next(f for f in facts if f.fact_revision_id == r) for r in reorder[b.block_id]]
        items = []
        for f in facts:
            rid = f.fact_revision_id
            if rid in delete:
                continue
            if rid in modify:
                items.append({"op": "MODIFY", "fact_revision_id": rid,
                              "fact": _fields(f, **modify[rid])})
            else:
                items.append({"op": "KEEP", "fact_revision_id": rid})
        if b.kind == "STEPS":
            order = {f.fact_revision_id: modify.get(f.fact_revision_id, {}).get(
                "step_order", f.step_order) for f in b.facts}
            items.sort(key=lambda i: order[i["fact_revision_id"]])
        if items:
            blocks.append({"kind": b.kind, "items": items,
                           "variant": (b.variant.temperature, b.variant.size)})
    for kind, variant, item in adds:
        target = next((x for x in blocks if x["kind"] == kind and x["variant"] == variant), None)
        if target is None:
            blocks.append({"kind": kind, "items": [item], "variant": variant})
        else:
            target["items"].append(item)
    if extra_items:
        blocks[0]["items"] += list(extra_items)
    for x in blocks:
        x.pop("variant")
    return FactEditRequest.model_validate({
        "expected_version_id": expected or view.version_id, "idempotency_key": key,
        "blocks": blocks, "deleted_fact_revision_ids": list(delete)})


async def _save(pool, w, card_id, req, *, edit=True, claims=None):
    with patch("app.config.get_settings", lambda: _w3b_settings(edit=edit)):
        return await card_router.save_card_facts(card_id, req, ShortSession(pool),
                                                  claims or _owner_claims(w))


async def _edit_store(db, pool, run_tag, parts=None):
    w = await _fact_store(db, pool, parts or _S_Z, run_tag=run_tag)
    w.card, w.version, _, _ = await _fact_card_id(db, w.store)
    w.entity = await _entity(db, w.store, Z)
    return w


async def _snapshot_content(db, store, snapshot_id):
    raw = await db.fetchval(
        "select i.content from r_index_publications p join r_index_preparations i "
        "on i.store_id = p.store_id and i.prepared_id = p.prepared_id "
        "where p.store_id=$1 and p.snapshot_id=$2", store, snapshot_id)
    return (KnowledgeContent.model_validate_json(raw) if isinstance(raw, str)
            else KnowledgeContent.model_validate(raw))


async def _provenance_sources(db, store, version_id, rid):
    return await db.fetch(
        "select o.occurrence_id, o.source_id, o.locator_type, o.locator, o.disposition, "
        "o.card_id, o.block_id, o.decided_by, s.source_type from card_version_fact_provenance p "
        "join fact_occurrences o on o.store_id = p.store_id and o.occurrence_id = p.occurrence_id "
        "join sources s on s.store_id = o.store_id and s.source_id = o.source_id "
        "where p.store_id=$1 and p.card_version_id=$2 and p.fact_revision_id=$3",
        store, version_id, rid)


async def _s1(db, pool):
    check = _checker("S1")
    w = await _edit_store(db, pool, 1201)
    first = await _approve(db, pool, w, w.card, "w3b-s1-approve")
    assert first.status == "PUBLISHED", first
    published = (await _card(db, w.store, w.card))["published_version_id"]
    w.snapshot_id = first.snapshot_id
    w.snapshot_row = await _snapshot_row(db, w.store, first.snapshot_id)
    w.snapshot_dump = (await _snapshot_content(db, w.store, first.snapshot_id)).model_dump()
    view = await _facts_view(pool, w, w.card)
    water = _find(view, value="225")
    w.old_rid = water.fact_revision_id
    old_row = dict(await db.fetchrow("select * from fact_revisions where store_id=$1 "
                                     "and fact_revision_id=$2", w.store, w.old_rid))
    w.old_pins = await _pins(db, w.store, w.version)
    result = await _save(pool, w, w.card, _body(view, "w3b-s1-key-0001", modify={
        w.old_rid: {"sentence": "음료Z ICE 물 230ml", "value": "230"}}))
    check("changed·MODIFY 판 1·기준 = 고정 판",
          result.changed and len(result.revisions) == 1
          and result.revisions[0].op == "MODIFY"
          and result.revisions[0].base_fact_revision_id == w.old_rid)
    w.new_rid = result.revisions[0].fact_revision_id
    new = await db.fetchrow(
        "select r.supersedes_revision_id, r.created_by, r.quantity_value, r.quantity_unit, "
        "r.original_assertion, m.change_kind, m.reason from fact_revisions r "
        "join fact_revision_meta m on m.store_id = r.store_id "
        "  and m.fact_revision_id = r.fact_revision_id "
        "where r.store_id=$1 and r.fact_revision_id=$2", w.store, w.new_rid)
    check("새 판 OWNER_CORRECTION·supersedes=옛 판·작성자=점주·230 ml",
          new["change_kind"] == "OWNER_CORRECTION" and new["supersedes_revision_id"] == w.old_rid
          and new["created_by"] == w.user and new["quantity_value"] == Decimal("230")
          and new["quantity_unit"] == "ml" and new["original_assertion"] == "음료Z ICE 물 230ml"
          and new["reason"] == "카드 사실 편집")
    card = await _card(db, w.store, w.card)
    w.draft = result.draft_version_id
    check("공개 포인터 그대로·초안 = 새 카드 판",
          card["published_version_id"] == published == result.published_version_id
          and card["draft_version_id"] == w.draft != w.version)
    version = await db.fetchrow("select change_source, created_by, title, content "
                                "from card_versions where store_id=$1 and version_id=$2",
                                w.store, w.draft)
    check("새 카드 판 OWNER_EDIT·작성자 점주·제목 그대로·본문에 새 문장만",
          version["change_source"] == "OWNER_EDIT" and version["created_by"] == w.user
          and version["title"] == view.title and "음료Z ICE 물 230ml" in version["content"]
          and "음료Z ICE 물 225ml" not in version["content"]
          and card["content"] == version["content"])
    _, new_facts, _ = await _pins(db, w.store, w.draft)
    pinned = {rid for _, rid, _ in new_facts}
    old_ids = {rid for _, rid, _ in w.old_pins[1]}
    check("새 카드 판 블록 사실 = 옛 고정 − 옛 판 + 새 판",
          pinned == (old_ids - {w.old_rid}) | {w.new_rid})
    check("옛 판 행·옛 카드 판 블록·근거 그대로",
          dict(await db.fetchrow("select * from fact_revisions where store_id=$1 "
                                 "and fact_revision_id=$2", w.store, w.old_rid)) == old_row
          and await _pins(db, w.store, w.version) == w.old_pins)
    owner = await db.fetch("select source_id, file_url, content_hash, status, uploaded_by, title "
                           "from sources where store_id=$1 and source_type='OWNER_TEXT'", w.store)
    check("점주 입력 자료 1행 — 파일·지문 없음·DONE·점주·제목",
          len(owner) == 1 and owner[0]["file_url"] is None and owner[0]["content_hash"] is None
          and owner[0]["status"] == "DONE" and owner[0]["uploaded_by"] == w.user
          and owner[0]["title"] == f"카드 직접 입력 · {view.title}")
    w.owner_src = owner[0]["source_id"]
    check("점주 입력 자료에는 추출 작업이 없다",
          await db.fetchval("select count(*) from ingest_job_sources where store_id=$1 "
                            "and source_id=$2", w.store, w.owner_src) == 0)
    (prov,) = await _provenance_sources(db, w.store, w.draft, w.new_rid)
    w.owner_occ = prov["occurrence_id"]
    check("새 판 근거 = 점주 입력 자료 LINE 1·LINKED·이 카드·작성자",
          prov["source_id"] == w.owner_src and prov["locator_type"] == "LINE"
          and _j(prov["locator"]) == {"line": 1} and prov["disposition"] == "LINKED"
          and prov["card_id"] == w.card and prov["decided_by"] == w.user)
    others = [await _provenance_sources(db, w.store, w.draft, r) for r in pinned - {w.new_rid}]
    check("다른 줄 근거 = 옛 파일 근거",
          all(rows and all(r["source_id"] == w.src for r in rows) for rows in others))
    evidence = {r["source_id"]: r for r in await db.fetch(
        "select source_id, locator_type, locator, excerpt from card_evidence "
        "where store_id=$1 and version_id=$2", w.store, w.draft)}
    check("카드 근거 — 점주 입력 MESSAGE line 1·발췌 = 입력 글, 파일 자료는 발췌 없음",
          set(evidence) == {w.owner_src, w.src}
          and evidence[w.owner_src]["locator_type"] == "MESSAGE"
          and _j(evidence[w.owner_src]["locator"]) == {"line": 1}
          and evidence[w.owner_src]["excerpt"] == "음료Z ICE 물 230ml"
          and evidence[w.src]["excerpt"] is None)
    edit = await db.fetchrow("select * from card_fact_edits where store_id=$1 and card_id=$2",
                             w.store, w.card)
    check("편집 기록 — changed·판 이동·점주 입력 글·결과",
          edit["changed"] and edit["from_version_id"] == w.version
          and edit["to_version_id"] == w.draft and edit["owner_text_source_id"] == w.owner_src
          and edit["owner_text"] == "음료Z ICE 물 230ml" and edit["actor_id"] == w.user
          and _j(edit["result"])["edit_id"] == edit["edit_id"] == result.edit_id)
    event = await db.fetchrow("select action, from_status, to_status, metadata from "
                              "card_review_events where store_id=$1 and card_id=$2 "
                              "order by event_id desc limit 1", w.store, w.card)
    meta = _j(event["metadata"])
    check("사건 EDIT_DRAFT·kind FACT_EDIT·상태 APPROVED 그대로",
          event["action"] == "EDIT_DRAFT" and event["from_status"] == event["to_status"]
          == "APPROVED" and meta["kind"] == "FACT_EDIT" and meta["modified"] == 1
          and meta["to_version_id"] == w.draft and card["review_status"] == "APPROVED")
    return w


async def _s2(db, pool):
    check = _checker("S2")
    w = await _edit_store(db, pool, 1211)
    view = await _facts_view(pool, w, w.card)
    holder = _find(view, value="끼운다")
    result = await _save(pool, w, w.card, _body(view, "w3b-s2-key-0001", modify={
        holder.fact_revision_id: {"sentence": "음료Z 홀더는 매장 안에서 끼우지 않는다",
                                  "polarity": "NEGATE", "value": "끼우지 않는다",
                                  "conditions": ["매장 안에서"]}}))
    (rev,) = result.revisions
    new = await db.fetchrow("select polarity, conditions, quantity_value, value_text "
                            "from fact_revisions where store_id=$1 and fact_revision_id=$2",
                            w.store, rev.fact_revision_id)
    check("새 판 1·NEGATE·조건·수치 없음",
          result.changed and new["polarity"] == "NEGATE"
          and _j(new["conditions"]) == ["매장 안에서"] and new["quantity_value"] is None
          and new["value_text"] == "끼우지 않는다")
    content = (await _card(db, w.store, w.card))["content"]
    check("본문에 (조건: …) 과 새 문장",
          "음료Z 홀더는 매장 안에서 끼우지 않는다 (조건: 매장 안에서)" in content)
    after = await _facts_view(pool, w, w.card)
    row = _find(after, fact_revision_id=rev.fact_revision_id)
    check("읽기 화면 — NEGATE·이전 문장·OWNER_TEXT 근거",
          row.polarity == "NEGATE" and row.previous_sentence == holder.sentence
          and row.change_kind == "OWNER_CORRECTION"
          and [o.kind for o in row.origins] == ["OWNER_TEXT"])


async def _s3(db, pool):
    check = _checker("S3")
    w = await _edit_store(db, pool, 1221)
    view = await _facts_view(pool, w, w.card)
    water = _find(view, value="225")
    before = await _counts(db, w.store)
    result = await _save(pool, w, w.card, _body(view, "w3b-s3-key-0001", modify={
        water.fact_revision_id: {}}))
    after = await _counts(db, w.store)
    check("같은 값 MODIFY → changed=false·revisions 없음·초안 그대로",
          result.changed is False and result.revisions == []
          and result.draft_version_id == w.version)
    check("판·카드 판·사건·자료·occurrence 0 증가, 편집 기록 +1",
          after == {**before, "card_fact_edits": before["card_fact_edits"] + 1})
    edit = await db.fetchrow("select changed, to_version_id, owner_text from card_fact_edits "
                             "where store_id=$1 and card_id=$2", w.store, w.card)
    check("편집 기록 changed=false·새 판 없음·점주 입력 없음",
          (edit["changed"], edit["to_version_id"], edit["owner_text"]) == (False, None, None))


async def _s4(db, pool):
    check = _checker("S4")
    w = await _edit_store(db, pool, 1231)
    view = await _facts_view(pool, w, w.card)
    parsed = await _parse(pool, w, w.card, FactParseRequest(text="음료Z 카라멜 드리즐 15ml 뿌린다"))
    (proposal,) = parsed.proposals
    before = await _counts(db, w.store)
    add = {"op": "ADD", "client_ref": proposal.client_ref,
           "fact": proposal.fact.model_dump(mode="json")}
    variant = (proposal.fact.variant.temperature, proposal.fact.variant.size)
    result = await _save(pool, w, w.card, _body(view, "w3b-s4-key-0001",
                                                adds=[(proposal.block_kind, variant, add)]))
    (rev,) = result.revisions
    check("ADD 결과 — client_ref·새 판", rev.op == "ADD" and rev.client_ref == proposal.client_ref)
    after = await _counts(db, w.store)
    check("knowledge_facts +1·판 +1·카드 판 +1·점주 입력 자료 +1",
          after["knowledge_facts"] == before["knowledge_facts"] + 1
          and after["fact_revisions"] == before["fact_revisions"] + 1
          and after["card_versions"] == before["card_versions"] + 1
          and after["sources"] == before["sources"] + 1)
    fact = await db.fetchrow(
        "select k.entity_id, m.change_kind, m.reason, r.created_by, r.subject, "
        "r.supersedes_revision_id from fact_revisions r "
        "join knowledge_facts k on k.store_id = r.store_id and k.fact_id = r.fact_id "
        "join fact_revision_meta m on m.store_id = r.store_id "
        "  and m.fact_revision_id = r.fact_revision_id "
        "where r.store_id=$1 and r.fact_revision_id=$2", w.store, rev.fact_revision_id)
    check("새 사실 대상 = 카드 대상·OWNER_ADD·첫 판·작성자 점주",
          fact["entity_id"] == w.entity and fact["change_kind"] == "OWNER_ADD"
          and fact["reason"] == "카드 사실 추가" and fact["supersedes_revision_id"] is None
          and fact["created_by"] == w.user and fact["subject"] == Z)
    (prov,) = await _provenance_sources(db, w.store, result.draft_version_id,
                                        rev.fact_revision_id)
    check("LINKED occurrence(점주 입력 자료)", prov["disposition"] == "LINKED"
          and prov["source_type"] == "OWNER_TEXT" and prov["card_id"] == w.card)
    content = (await _card(db, w.store, w.card))["content"]
    check("본문에 새 문장", proposal.fact.sentence in content)


async def _other_card_with(db, w, rid):
    """같은 사실 판을 초안에 고정한 다른 카드(합성)."""
    categories = await ingest_repo.enabled_categories(db, w.store)
    other = await ingest_repo.insert_card(
        db, w.store, category_id=next(iter(categories.values())), source_id=w.src,
        title="음료Z 다른 카드", content="합성 다른 카드", confidence=0, entity_id=w.entity)
    version = (await _card(db, w.store, other))["draft_version_id"]
    await fact_cards.pin_card_version(db, w.store, version, ValidatedCard(
        entity_id=w.entity, title="음료Z 다른 카드", category_name="기타",
        variant=(None, None), blocks=(ValidatedBlock("b1", "NOTES", 1, (rid,), (None, None)),)),
        {})
    return other


async def _s5(db, pool):
    check = _checker("S5")
    w = await _edit_store(db, pool, 1241)
    first = await _approve(db, pool, w, w.card, "w3b-s5-approve")
    assert first.status == "PUBLISHED", first
    view = await _facts_view(pool, w, w.card)
    syrup, whip = _find(view, value="20"), _find(view, value="올리지 않는다")
    other = await _other_card_with(db, w, whip.fact_revision_id)
    old_pins = await _pins(db, w.store, w.version)
    result = await _save(pool, w, w.card, _body(
        view, "w3b-s5-key-0001", delete=[syrup.fact_revision_id, whip.fact_revision_id]))
    _, new_facts, _ = await _pins(db, w.store, result.draft_version_id)
    pinned = {rid for _, rid, _ in new_facts}
    check("새 카드 판에 삭제한 두 판이 없다·새 사실 판 0",
          not {syrup.fact_revision_id, whip.fact_revision_id} & pinned
          and result.revisions == [] and result.changed)
    check("옛 카드 판 고정 그대로", await _pins(db, w.store, w.version) == old_pins)
    snap = await _index(pool, w.store)
    check("승인판 snapshot 에는 그대로",
          {str(syrup.fact_revision_id), str(whip.fact_revision_id)}
          <= {f.fact_revision_id for f in snap.fact_revisions}
          and snap.card(str(w.card)).card_version_id == str(w.version))
    syrup_occ = await db.fetch(
        "select disposition, reason, card_id, block_id, decided_by from fact_occurrences "
        "where store_id=$1 and fact_revision_id=$2", w.store, syrup.fact_revision_id)
    check("다른 카드에 없는 사실 occurrence → EXCLUDED OWNER_REMOVED·decided_by·카드 없음",
          syrup_occ and all(r["disposition"] == "EXCLUDED" and r["reason"] == "OWNER_REMOVED"
                            and r["card_id"] is None and r["block_id"] is None
                            and r["decided_by"] == w.user for r in syrup_occ))
    whip_occ = await db.fetch(
        "select disposition, card_id, block_id from fact_occurrences "
        "where store_id=$1 and fact_revision_id=$2", w.store, whip.fact_revision_id)
    check("다른 카드에도 있는 사실 → 그 카드·블록으로 옮겨지고 LINKED",
          whip_occ and all((r["disposition"], r["card_id"], r["block_id"])
                           == ("LINKED", other, "b1") for r in whip_occ))
    kept = await db.fetch(
        "select o.block_id, o.fact_revision_id from fact_occurrences o "
        "where o.store_id=$1 and o.card_id=$2 and o.disposition='LINKED'", w.store, w.card)
    blocks_of = {}
    for block_id, rid, _ in new_facts:
        blocks_of.setdefault(rid, block_id)
    check("남은 사실 LINKED 행은 새 카드 판 블록을 가리킨다",
          kept and all(r["block_id"] == blocks_of[r["fact_revision_id"]] for r in kept))
    meta = _j((await db.fetchrow("select metadata from card_review_events where store_id=$1 "
                                 "and card_id=$2 order by event_id desc limit 1",
                                 w.store, w.card))["metadata"])
    check("사건 deleted=2", meta["deleted"] == 2 and meta["modified"] == 0)


async def _s6(db, pool):
    check = _checker("S6")
    w = await _edit_store(db, pool, 1251)
    view = await _facts_view(pool, w, w.card)
    shot, lid = _find(view, step_order=2), _find(view, step_order=3)
    result = await _save(pool, w, w.card, _body(view, "w3b-s6-key-0001", modify={
        shot.fact_revision_id: {"step_order": 3}, lid.fact_revision_id: {"step_order": 2}}))
    check("단계 2·3 맞바꿈 → 새 판 2", result.changed and len(result.revisions) == 2)
    new = {r.base_fact_revision_id: r.fact_revision_id for r in result.revisions}
    rows = {r["fact_revision_id"]: r for r in await db.fetch(
        "select fact_revision_id, step_order, original_assertion, quantity_value, value_text "
        "from fact_revisions where store_id=$1 and fact_revision_id = any($2::bigint[])",
        w.store, [shot.fact_revision_id, lid.fact_revision_id, *new.values()])}
    same_other = all(
        (rows[new[b]]["original_assertion"], rows[new[b]]["value_text"])
        == (rows[b]["original_assertion"], rows[b]["value_text"]) for b in new)
    check("새 판은 단계 번호만 다르다",
          same_other and rows[new[shot.fact_revision_id]]["step_order"] == 3
          and rows[new[lid.fact_revision_id]]["step_order"] == 2)
    content = (await _card(db, w.store, w.card))["content"]
    check("본문 번호 갱신", f"2. {lid.sentence}" in content and f"3. {shot.sentence}" in content)
    view = await _facts_view(pool, w, w.card)
    ice, shot = _find(view, step_order=1), _find(view, step_order=3)
    before = await _counts(db, w.store)
    e = await _api_error(_save(pool, w, w.card, _body(view, "w3b-s6-key-0002", modify={
        ice.fact_revision_id: {"step_order": 3}, shot.fact_revision_id: {"step_order": 1}})))
    check("선행 위반 맞바꿈 → 422 STEP_REQUIRES_ORDER",
          e is not None and e.status_code == 422 and e.code == "STEP_REQUIRES_ORDER")
    check("쓰기 0", await _counts(db, w.store) == before)
    notes = next(b for b in view.blocks if b.kind == "NOTES" and len(b.facts) >= 2)
    order = [f.fact_revision_id for f in reversed(notes.facts)]
    result = await _save(pool, w, w.card, _body(view, "w3b-s6-key-0003",
                                                reorder={notes.block_id: order}))
    after = await _counts(db, w.store)
    check("NOTES 자리 바꿈 → 판 0·카드 판 +1",
          result.changed and result.revisions == []
          and after["fact_revisions"] == before["fact_revisions"]
          and after["card_versions"] == before["card_versions"] + 1)
    old_blocks, old_facts, _ = await _pins(db, w.store, view.version_id)
    new_blocks, new_facts, _ = await _pins(db, w.store, result.draft_version_id)
    check("새 카드 판 position 만 다르다",
          old_blocks == new_blocks and {r for _, r, _ in old_facts} == {r for _, r, _ in new_facts}
          and old_facts != new_facts)
    after_view = await _facts_view(pool, w, w.card)
    moved = next(b for b in after_view.blocks if b.block_id == notes.block_id)
    check("읽기 화면 순서 = 보낸 순서", [f.fact_revision_id for f in moved.facts] == order)


async def _s7(db, pool):
    check = _checker("S7")
    w = await _edit_store(db, pool, 1261, parts=[("합성 자료 본문 S7 — 음료Z 물 HOT 225ml ICE 225ml", [
        _assertion("f1", Z, "물", "225", "ml", variant="HOT"),
        _assertion("f2", Z, "물", "225", "ml", variant="ICE"),
    ])])
    view = await _facts_view(pool, w, w.card)
    hot = _find(view, value="225", variant=FactVariant(temperature="HOT"))
    ice = _find(view, value="225", variant=FactVariant(temperature="ICE"))
    hot_block = next(b for b in view.blocks if any(f.fact_revision_id == hot.fact_revision_id
                                                   for f in b.facts))
    result = await _save(pool, w, w.card, _body(view, "w3b-s7-key-0001", modify={
        ice.fact_revision_id: {"sentence": "음료Z ICE 물 230ml", "value": "230"}}))
    (rev,) = result.revisions
    check("ICE 줄만 새 판", rev.base_fact_revision_id == ice.fact_revision_id)
    after = await _facts_view(pool, w, w.card)
    hot_after = next(b for b in after.blocks if b.block_id == hot_block.block_id)
    check("HOT 판·HOT 블록 그대로",
          [f.fact_revision_id for f in hot_after.facts] == [hot.fact_revision_id]
          and hot_after.variant.temperature == "HOT")
    head = await db.fetchval("select head_revision_id from knowledge_facts where store_id=$1 "
                             "and fact_id=$2", w.store, hot.fact_id)
    check("HOT 사실 head 그대로", head == hot.fact_revision_id)


async def _s8(db, pool):
    check = _checker("S8")
    w = await _edit_store(db, pool, 1271)
    view = await _facts_view(pool, w, w.card)
    water = _find(view, value="225")
    body = _body(view, "w3b-s8-key-0001", modify={
        water.fact_revision_id: {"sentence": "음료Z 물 230ml", "value": "230"}})
    first = await _save(pool, w, w.card, body)
    e = await _api_error(_save(pool, w, w.card, _body(view, "w3b-s8-key-0002", modify={
        water.fact_revision_id: {"sentence": "음료Z 물 240ml", "value": "240"}})))
    check("옛 expected → 409 CARD_VERSION_CONFLICT(current_version_id)",
          e is not None and e.status_code == 409 and e.code == "CARD_VERSION_CONFLICT"
          and e.details == {"current_version_id": first.draft_version_id})
    before = await _counts(db, w.store)
    again = await _save(pool, w, w.card, body)
    check("같은 키·같은 본문 → 같은 결과·행 증가 0",
          again == first and await _counts(db, w.store) == before)
    other = _body(view, "w3b-s8-key-0001", modify={
        water.fact_revision_id: {"sentence": "음료Z 물 250ml", "value": "250"}})
    e = await _api_error(_save(pool, w, w.card, other))
    check("같은 키·다른 본문 → 409 IDEMPOTENCY_CONFLICT",
          e is not None and e.status_code == 409 and e.code == "IDEMPOTENCY_CONFLICT")
    view = await _facts_view(pool, w, w.card)
    water = _find(view, value="230")
    before = await _counts(db, w.store)
    bodies = [_body(view, f"w3b-s8-race-{i:04d}", modify={
        water.fact_revision_id: {"sentence": f"음료Z 물 {260 + i}ml", "value": str(260 + i)}})
              for i in range(2)]
    # 설정 대역은 한 번만 건다(동시 작업마다 patch 를 열고 닫으면 서로 되돌린다)
    with patch("app.config.get_settings", lambda: _w3b_settings()):
        outcomes = await asyncio.wait_for(asyncio.gather(
            *(card_router.save_card_facts(w.card, b, ShortSession(pool), _owner_claims(w))
              for b in bodies),
            return_exceptions=True), timeout=60)
    ok = [o for o in outcomes if not isinstance(o, BaseException)]
    errors = [o for o in outcomes if isinstance(o, ApiError)]
    check("두 연결 동시 저장 → 하나 성공·하나 409(교착 없음)",
          len(ok) == 1 and len(errors) == 1 and errors[0].status_code == 409)
    after = await _counts(db, w.store)
    check("판 중복 없음 — 판 +1·카드 판 +1",
          after["fact_revisions"] == before["fact_revisions"] + 1
          and after["card_versions"] == before["card_versions"] + 1)


async def _s9(db, pool):
    check = _checker("S9")
    w = await _edit_store(db, pool, 1281)
    first = await _approve(db, pool, w, w.card, "w3b-s9-approve")
    assert first.status == "PUBLISHED", first
    view = await _facts_view(pool, w, w.card)
    before = await _counts(db, w.store)
    e = await _api_error(_save(pool, w, w.card, _body(
        view, "w3b-s9-key-0001", delete=[f.fact_revision_id for f in _rows(view)])))
    check("전부 삭제 → 422 CARD_WOULD_BE_EMPTY",
          e is not None and e.status_code == 422 and e.code == "CARD_WOULD_BE_EMPTY")
    check("쓰기 0", await _counts(db, w.store) == before)
    with patch.object(card_router, "get_pool", lambda: pool), \
            patch("app.reg.index_preparation.recorded_embeddings", _fake_embedder):
        excluded = await card_router.exclude_card(w.card, ShortSession(pool), _owner_claims(w))
    check("카드 지우기는 기존 제외 경로", excluded.review_status == "EXCLUDED")
    snap = await _index(pool, w.store)
    check("마지막 공개 카드 제외 → 재발행 snapshot 카드 0(정상 빈 공개판)",
          snap.snapshot_id != str(first.snapshot_id) and snap.cards == ())


async def _s10(db, pool):
    check = _checker("S10")
    w = await _edit_store(db, pool, 1291)
    view = await _facts_view(pool, w, w.card)
    water, syrup = _find(view, value="225"), _find(view, value="20")
    await fr.revise_fact(db, w.store, fact_id=water.fact_id,
                         expected_head_revision_id=water.fact_revision_id,
                         change=fr.FactChange(value="228", original_assertion="합성 다른 정정 228ml"),
                         change_kind="OWNER_CORRECTION", actor_id=w.user, reason="합성 정정")
    before = await _counts(db, w.store)
    e = await _api_error(_save(pool, w, w.card, _body(view, "w3b-s10-key-0001", modify={
        water.fact_revision_id: {"sentence": "음료Z 물 230ml", "value": "230"}})))
    check("다른 곳에서 고친 사실 MODIFY → 409 FACT_CHANGED_ELSEWHERE(details)",
          e is not None and e.status_code == 409 and e.code == "FACT_CHANGED_ELSEWHERE"
          and e.details["fact_id"] == water.fact_id
          and e.details["fact_revision_id"] == water.fact_revision_id)
    check("쓰기 0", await _counts(db, w.store) == before)
    relinked = await _relink(db, w.store, syrup.fact_id, w.user)
    result = await _save(pool, w, w.card, _body(view, "w3b-s10-key-0002", modify={
        syrup.fact_revision_id: {"sentence": "음료Z 시럽 25ml", "value": "25"}}))
    (rev,) = result.revisions
    sup = await db.fetchval("select supersedes_revision_id from fact_revisions where store_id=$1 "
                            "and fact_revision_id=$2", w.store, rev.fact_revision_id)
    check("RELINK 만 낀 사실은 성공·head(RELINK 판) 위에 새 판", sup == relinked)


async def _s11(db, pool):
    check = _checker("S11")
    w = await _edit_store(db, pool, 1301)
    x = await _edit_store(db, pool, 1302)
    view = await _facts_view(pool, w, w.card)
    foreign = _rows(await _facts_view(pool, x, x.card))[0].fact_revision_id
    other_before = await _counts(db, x.store)
    mine_before = await _counts(db, w.store)
    cases = {
        "KEEP": _body(view, "w3b-s11-key-0001",
                      extra_items=[{"op": "KEEP", "fact_revision_id": foreign}]),
        "MODIFY": _body(view, "w3b-s11-key-0002", extra_items=[{
            "op": "MODIFY", "fact_revision_id": foreign,
            "fact": {"sentence": "음료Z 물 1ml", "value": "1", "unit": "ml"}}]),
        "삭제": _body(view, "w3b-s11-key-0003").model_copy(
            update={"deleted_fact_revision_ids": [foreign]}),
    }
    for name, body in cases.items():
        e = await _api_error(_save(pool, w, w.card, body))
        check(f"다른 매장 판 id 를 {name} 에 → 422 FACT_SET_MISMATCH(unexpected 그대로)",
              e is not None and e.status_code == 422 and e.code == "FACT_SET_MISMATCH"
              and e.details["unexpected"] == [foreign])
    e = await _api_error(_save(pool, w, x.card, _body(
        await _facts_view(pool, x, x.card), "w3b-s11-key-0004")))
    check("다른 매장 카드 → 404 CARD_NOT_FOUND",
          e is not None and e.status_code == 404 and e.code == "CARD_NOT_FOUND")
    check("다른 매장·내 매장 행 변화 0",
          await _counts(db, x.store) == other_before and await _counts(db, w.store) == mine_before)


async def _s12(db, pool):
    check = _checker("S12")
    w = await _edit_store(db, pool, 1311)
    view = await _facts_view(pool, w, w.card)
    water = _find(view, value="225")
    body = _body(view, "w3b-s12-key-0001", modify={
        water.fact_revision_id: {"sentence": "음료Z 물 230ml", "value": "230"}})
    before = await _counts(db, w.store)
    e = await _api_error(_save(pool, w, w.card, body, edit=False))
    check("플래그 끔 → 403 FACT_EDIT_DISABLED",
          e is not None and e.status_code == 403 and e.code == "FACT_EDIT_DISABLED")
    check("쓰기 0", await _counts(db, w.store) == before)
    result = await _save(pool, w, w.card, body)
    card_before = await _card(db, w.store, w.card)
    src = await _hashed_source(db, w.store, w.user)
    await _process_w3a(db, pool, w.store, w.user, src, [(
        "합성 자료 본문 S12 — 음료Z ICE 물 225ml", [
            _assertion("f1", Z, "물", "225", "ml", variant="ICE")])], run_tag=1312)
    added = await db.fetch("select disposition, reason from fact_occurrences "
                           "where store_id=$1 and source_id=$2", w.store, src)
    check("W3a 자동 재조립은 점주 편집 카드를 DEFER(EXISTING_CARD)",
          added and all((r["disposition"], r["reason"])
                        == ("REVIEW_PENDING", fact_cards.REASON_EXISTING_CARD) for r in added))
    card_after = await _card(db, w.store, w.card)
    check("점주 편집 초안 그대로",
          card_after["draft_version_id"] == card_before["draft_version_id"]
          == result.draft_version_id and card_after["content"] == card_before["content"])


# ── 재승인·R 소비·과거 인용 ────────────────────────────────────────────────────

async def _a1(db, pool, w):
    check = _checker("A1")
    result = await _approve(db, pool, w, w.card, "w3b-a1-approve")
    check("편집 카드 재승인 PUBLISHED", result.status == "PUBLISHED")
    w.a1_snapshot = result.snapshot_id
    snap = await _index(pool, w.store)
    card = snap.card(str(w.card))
    check("새 snapshot 의 카드 판 = 편집 판·entity_id = 대상",
          card.card_version_id == str(w.draft) and card.entity_id == str(w.entity))
    ids = {f.fact_revision_id for f in snap.fact_revisions}
    check("fact_revisions 에 새 판·옛 판 없음", str(w.new_rid) in ids and str(w.old_rid) not in ids)
    (prov,) = snap.fact(str(w.new_rid)).provenance
    check("새 판 근거 source_id = 점주 입력 자료·occurrence·locator.line 1",
          prov.source_id == str(w.owner_src) and prov.occurrence_id == str(w.owner_occ)
          and prov.locator.type == "LINE" and prov.locator.line == 1
          and prov.owner_answer_id is None and prov.source_content_hash is not None)
    status = (await _card(db, w.store, w.card))
    check("카드 공개 포인터 = 편집 판", status["published_version_id"] == w.draft)


async def _a2(db, pool, w):
    check = _checker("A2")
    question = "아이스 음료Z 물 얼마나 넣어?"
    found = await hybrid_search(pool, store_id=w.store, question=question,
                                query_vector=list(_VECTOR))
    session = await db.fetchval(
        "insert into chat_sessions (store_id, member_id, contract_version) "
        "values ($1,$2,'v2') returning session_id", w.store, w.member)
    decision = decide(found, store_id=w.store, question=question)
    saved = await save_answer(
        pool, store_id=w.store, member_id=w.member, session_id=session,
        request_id="w3b-a2-question", question=question, snapshot=found.snapshot,
        plan=decision.plan, resolved=decision.resolved,
        confirmed_slots=decision.confirmed_slots, semantic_context=decision.semantic_context)
    response = saved.response
    citations = [(c.fact_revision_id, c.source_id, c.block_id) for c in response.citations]
    print(f"INFO W3b A2 action={response.action} reason={decision.plan.escalation_reason} "
          f"citations={citations}")
    name = "R 답변 ANSWER·인용 판 = 새 판·자료 = 점주 입력 자료"
    ok = bool(response.action == "ANSWER" and response.citations
              and any(c.fact_revision_id == str(w.new_rid)
                      and c.source_id == str(w.owner_src) for c in response.citations))
    if not ok:
        print(f"FAIL W3b A2 {name}")
    check(name, ok)


async def _a3(db, pool, w):
    check = _checker("A3")
    old = await _snapshot_content(db, w.store, w.snapshot_id)
    check("편집 전 snapshot 행(snapshot_hash 포함) 그대로",
          await _snapshot_row(db, w.store, w.snapshot_id) == w.snapshot_row)
    check("편집 전 snapshot 내용 그대로(옛 판·옛 근거)", old.model_dump() == w.snapshot_dump)
    ids = {f.fact_revision_id for f in old.fact_revisions}
    old_fact = old.fact(str(w.old_rid))
    check("옛 snapshot 에는 옛 판만·근거는 파일 자료",
          str(w.old_rid) in ids and str(w.new_rid) not in ids
          and all(p.source_id == str(w.src) for p in old_fact.provenance))
    check("옛 카드 판 블록 행 그대로", await _pins(db, w.store, w.version) == w.old_pins)


async def verify(pool, admin) -> None:
    db = admin
    await _m1(db, pool)
    await _r1(db, pool)
    await _r2(db, pool)
    await _r3(db, pool)
    await _d1(db, pool)
    await _d2(db, pool)
    await _p1(db, pool)
    await _p2(db, pool)
    await _p3(db, pool)
    s1 = await _s1(db, pool)
    await _s2(db, pool)
    await _s3(db, pool)
    await _s4(db, pool)
    await _s5(db, pool)
    await _s6(db, pool)
    await _s7(db, pool)
    await _s8(db, pool)
    await _s9(db, pool)
    await _s10(db, pool)
    await _s11(db, pool)
    await _s12(db, pool)
    await _a1(db, pool, s1)
    await _a2(db, pool, s1)
    await _a3(db, pool, s1)
    print("Verified W3b M1 R1~R3 D1 D2 P1~P3 S1~S12 A1~A3")
