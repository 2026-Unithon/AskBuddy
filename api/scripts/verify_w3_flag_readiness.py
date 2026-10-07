"""실제 DB: W3-0 — 두 W2 플래그를 켠 합성 종단 검증 (설계 §3-6). 모델은 합성 대역, 비용 0.

verify_w_entity_revision.verify() 끝에서 부른다(verify_r_schema_rebuild 가 부르는 W 검증).
한 합성 매장에서 차례로(번호는 설계 §3-6):
  T1 자료 A(영상 구간 2개, 동시 2) → 대상·판·occurrence·제안·같은 대상 후보
  T4 A 재처리 → W2 표 행 수·제안 머리·항목 그대로(중복 없음)
  T2 자료 B 의 HOT/ICE 동시 사실 → 원장·판 규격별 두 사실, 같은 자리 occurrence 둘, 나눔 표시,
     선행 관계는 갈라진 둘 다, 조립 ref 로 카드가 둘 다 잇고 LINKED
  T3 자료 C 의 다른 값 → 충돌 양쪽 보존·기본 선택 없음. A 카드 승인 뒤 재처리 → CONFLICT,
     matched_cards 를 지운 뒤 같은 순위 재처리 → 새 계산으로 갱신, 승인 카드가 하나 더 늘면
     같은 순위 재처리에서 matched_cards 가 두 카드로 갱신(§3-3-3)
  T5 대상 병합 → 후보 옮김·닫음(§3-3-1), 병합 뒤 재처리 → 제안 옮김(MOVED)·SUPERSEDED·중복 없음,
     살아 있는 대상의 제안이 이미 결정됐으면 옛 PENDING 제안 그대로(KEPT_PENDING, 결정 K),
     결정된 제안 그대로(§3-3-2)
  T6 대상 분리 → 이력 SPLIT, 공개본·카드 행·제안 그대로
  T7 점주 정정 → 새 head, 옛 이관 정정은 그 위에 얹히지 않음(§3-2)
  T8 플래그를 끈 뒤 처리 → 새 W2 행·제안·후보·이력 없음, HOT/ICE 는 나누지 않음
"""
import json
from contextlib import ExitStack
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

import asyncpg

import app.config
from app.config import Settings
from app.ingest import extract, pipeline
from app.ingest import repository as repo
from app.ingest.extract import gemini
from app.ingest.schemas import (ExtractedCard, ExtractedFact, ExtractionResult,
                                FactExtractionResult)
from verify_w_entity_revision import (_MODEL_SETTINGS, _VECTOR, _card_rows, _checker, _fact,
                                      _proposal_rows, _published_fingerprint, _rows_text,
                                      _w2_counts)
from verify_w_partial_extraction import _new_source, _seed

# 합성 대상 이름. A·B·C 는 서로 한 글자 차이(EDIT1), B1 은 B 와만 한 글자 차이다
A, B, C, D = "합성음료A", "합성음료B", "합성음료C", "합성음료B1"


async def _process(db, pool, store, user, source, parts, *, run_tag, flags=True):
    """process_source 를 합성 모델 대역으로 돌린다. parts = [(구간 글, 사실 목록)].

    parts 가 둘 이상이면 구간으로 나눠 동시에 2개씩 뽑는다. 하나면 구간 없는 자료다.
    조립 대역은 주어(subject)마다 카드 하나를 만들고, 나누기 전 이름표(seg1:f1·f1)를 인용한다.
    """
    job_id = await db.fetchval(
        "insert into ingest_jobs (store_id, created_by, title, status, category_version, "
        "prompt_version) values ($1,$2,'W3-0 종단 검증','EXTRACTING',1,'v1') returning job_id",
        store, user)
    await db.execute("update sources set status='UPLOADED' where store_id=$1 and source_id=$2",
                     store, source)
    await db.execute("insert into ingest_job_sources(store_id,job_id,source_id,status) "
                     "values($1,$2,$3,'QUEUED')", store, job_id, source)
    category = next(iter(await repo.enabled_categories(db, store)))
    segmented = len(parts) > 1
    cited = [(f"seg{index}:{f['local_ref']}" if segmented else f["local_ref"], f)
             for index, (_, facts) in enumerate(parts, start=1) for f in facts]

    async def fake_call(prompt, media, schema=None, max_output_tokens=None):
        if schema is not None and issubclass(schema, FactExtractionResult):
            facts = next(f for text, f in parts if text in prompt)
            body = FactExtractionResult.model_validate({"assertions": facts})
            return gemini.CallResult(body.model_dump_json(), {}, "STOP")
        by_subject: dict[str, list[ExtractedFact]] = {}
        for ref, f in cited:
            by_subject.setdefault(f["subject"], []).append(ExtractedFact(
                object_name=f["subject"], attribute=f["attribute"], value=f["value"],
                confidence=.9, ref=ref))
        cards = [ExtractedCard(category_name=category, title=subject, content="합성 카드",
                               confidence=.9, facts=facts)
                 for subject, facts in by_subject.items()]
        return gemini.CallResult(ExtractionResult(cards=cards).model_dump_json(), {}, "STOP")

    if segmented:
        preprocessed = ("합성 자료 본문", [], [(text, []) for text, _ in parts])
    else:
        preprocessed = (parts[0][0], [], [])
    settings = Settings(_env_file=None, w_entity_revision_enabled=flags,
                        w_upload_proposals_enabled=flags, extract_segment_concurrency=2)
    with ExitStack() as stack:
        for obj, name, replacement in [
            (pipeline, "get_pool", lambda: pool),
            (pipeline, "_preprocess", AsyncMock(return_value=preprocessed)),
            (pipeline.shutil, "rmtree", lambda *a, **kw: None),
            (app.config, "get_settings", lambda: settings),
            (extract, "get_settings", lambda: NS(ingest_mode="real")),
            (gemini, "get_settings", lambda: _MODEL_SETTINGS),
            (gemini, "_call", fake_call),
        ]:
            stack.enter_context(patch.object(obj, name, replacement))
        await pipeline.process_source(store, source, job_id=job_id, run_tag=run_tag)
    state = await db.fetchrow("select status, error_message from sources "
                              "where store_id=$1 and source_id=$2", store, source)
    assert state["status"] == "DONE", f"처리 실패: {state['status']} {state['error_message']}"


async def verify(db, dsn) -> None:
    from app.contracts.usage import UsageContext
    from app.ingest.entities import find_entity_by_alias, list_candidates
    from app.ingest.entity_admin import merge_entities, split_entity
    from app.ingest.entity_names import normalize_alias
    from app.ingest.fact_ledger import list_open_conflicts
    from app.ingest.fact_revisions import FactChange, import_legacy_correction, revise_fact
    from app.publish.approval import CardChange, publish_cards

    async def fake_embedder(texts, *, context, sink=None):
        return [list(_VECTOR) for _ in texts]

    user, s, _ = await _seed(db)
    member = await db.fetchval(
        "insert into store_members(store_id,user_id,member_role) values($1,$2,'OWNER') "
        "returning member_id", s, user)

    async def entity(name):
        return await find_entity_by_alias(db, s, normalize_alias(name))

    async def fact_of(source, attribute, value):
        """원장 사실 → 이어진 사실(knowledge_facts) 행."""
        return await db.fetchrow(
            "select f.fact_id as source_fact_id, k.fact_id, k.entity_id, k.head_revision_id "
            "from source_facts f "
            "join source_fact_revision_links l on l.store_id = f.store_id "
            "  and l.source_fact_id = f.fact_id "
            "join knowledge_facts k on k.store_id = l.store_id and k.fact_id = l.fact_id "
            "where f.store_id=$1 and f.source_id=$2 and f.attribute=$3 and f.value=$4 "
            "order by f.fact_id limit 1", s, source, attribute, value)

    async def proposals(source):
        return await db.fetch(
            "select proposal_id, entity_id, relation_type, status, matched_cards "
            "from upload_change_proposals where store_id=$1 and source_id=$2 "
            "order by proposal_id", s, source)

    async def events(action):
        return await db.fetch(
            "select entity_id, other_entity_id, payload from knowledge_entity_events "
            "where store_id=$1 and action=$2 order by event_id", s, action)

    async def publish(card_id, tag):
        """초안을 그대로 승인·발행한다(임베딩은 합성 벡터)."""
        draft = await db.fetchval("select draft_version_id from knowledge_cards "
                                  "where store_id=$1 and card_id=$2", s, card_id)
        with patch("app.reg.index_preparation.recorded_embeddings", fake_embedder):
            return await publish_cards(
                pool, store_id=s, member_id=member, actor_user_id=user,
                changes=[CardChange(card_id, draft, draft)],
                idempotency_key=f"w3-0-{tag}-publish",
                usage_context=UsageContext(
                    store_id=str(s), cost_phase="OPERATING", cost_purpose="PRODUCT",
                    stage="EMBED", operation_id=f"w3-0-{tag}",
                    logical_call_id=f"w3-0-{tag}:embed"))

    def pair(rows, x, y):
        return [r for r in rows if {r["entity_id_low"], r["entity_id_high"]} == {x, y}]

    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=4)
    try:
        # T1 — 자료 A: 영상 구간 2개를 동시에
        check = _checker("W3-0 T1")
        src_a = await _new_source(db, s, user, "VIDEO")
        parts_a = [
            ("구간1 합성 본문", [_fact("f1", A, "물", "200", "ml", ts=5),
                                _fact("f2", A, "시럽", "20", "ml", ts=8)]),
            ("구간2 합성 본문", [_fact("f1", A, "얼음", "100", "g", ts=65),
                                _fact("f2", B, "시럽", "15", "ml", ts=70)]),
        ]
        await _process(db, pool, s, user, src_a, parts_a, run_tag=601)
        counts_a = await _w2_counts(db, s)
        a_id, b_id = await entity(A), await entity(B)
        check("대상 2·사실 4·판 4·occurrence 4",
              a_id is not None and b_id is not None and a_id != b_id
              and (counts_a["knowledge_entities"], counts_a["knowledge_facts"],
                   counts_a["fact_revisions"], counts_a["fact_occurrences"]) == (2, 4, 4, 4))
        segments = sorted(r["segment_id"] for r in await db.fetch(
            "select distinct segment_id from source_facts where store_id=$1 and source_id=$2",
            s, src_a))
        check("두 구간이 모두 원장에 — seg1·seg2", segments == ["seg1", "seg2"])
        check("occurrence 는 모두 영상 시각(TIMESTAMP)", await db.fetchval(
            "select count(*) from fact_occurrences where store_id=$1 and source_id=$2 "
            "and locator_type='TIMESTAMP'", s, src_a) == 4)
        heads_a = await proposals(src_a)
        check("제안 2행(대상 A·B) 모두 NEW·PENDING_REVIEW",
              sorted(r["entity_id"] for r in heads_a) == sorted([a_id, b_id])
              and all((r["relation_type"], r["status"]) == ("NEW", "PENDING_REVIEW")
                      for r in heads_a))
        ab = pair(await list_candidates(db, s), a_id, b_id)
        check("A·B 같은 대상 후보 PENDING 1(EDIT1)", len(ab) == 1 and ab[0]["reason"] == "EDIT1")

        # T4 — A 재처리 → 중복 없음
        check = _checker("W3-0 T4")
        props_before = await _proposal_rows(db, s)
        await _process(db, pool, s, user, src_a, parts_a, run_tag=602)
        check("A 재처리 → W2 표 행 수 그대로", await _w2_counts(db, s) == counts_a)
        check("A 재처리 → 제안 머리·항목 그대로(updated_at 포함)",
              await _proposal_rows(db, s) == props_before)

        # T2 — 자료 B: HOT/ICE 동시 사실
        check = _checker("W3-0 T2")
        src_b = await _new_source(db, s, user, "SCAN")
        await _process(db, pool, s, user, src_b, [("합성 자료 본문 B", [
            _fact("f1", A, "에스프레소", "2", "샷", variant="HOT/ICE"),
            _fact("f2", A, "제조 순서", "잔에 붓는다", order=2, requires=["f1"]),
            _fact("f3", C, "시럽", "10", "ml"),
            _fact("f4", D, "시럽", "12", "ml")])], run_tag=603)
        ledger_b = await db.fetch(
            "select fact_id, local_ref, variant, assembly_state from source_facts "
            "where store_id=$1 and source_id=$2 and attribute='에스프레소' order by local_ref",
            s, src_b)
        check("원장 — f1~HOT(HOT)·f1~ICE(ICE) 두 행, HOT/ICE 한 행은 없다",
              [(r["local_ref"], r["variant"]) for r in ledger_b]
              == [("f1~HOT", "HOT"), ("f1~ICE", "ICE")])
        revs = await db.fetch(
            "select fact_revision_id, variant_temperature, quantity_value, original_assertion "
            "from fact_revisions where store_id=$1 and predicate='에스프레소' "
            "order by variant_temperature", s)
        check("판 둘 — HOT·ICE, 값 2·원문 같음",
              [r["variant_temperature"] for r in revs] == ["HOT", "ICE"]
              and {str(r["quantity_value"]) for r in revs} == {"2"}
              and len({r["original_assertion"] for r in revs}) == 1)
        marker = {"field": "variant", "verdict": "VARIANT_SPLIT", "value": "HOT/ICE",
                  "variant_split": "HOT_ICE", "from_ref": "f1"}
        located = await db.fetch(
            "select locator_type, locator::text loc, check_flags from source_fact_occurrences "
            "where store_id=$1 and fact_id = any($2::bigint[]) order by fact_id",
            s, [r["fact_id"] for r in ledger_b])
        check("원장 위치 둘 — 같은 자리, 둘 다 나눔 표시",
              len(located) == 2 and len({(o["locator_type"], o["loc"]) for o in located}) == 1
              and all(marker in json.loads(o["check_flags"]) for o in located))
        reasons = await db.fetch(
            "select reason from fact_occurrences where store_id=$1 "
            "and fact_revision_id = any($2::bigint[])", s, [r["fact_revision_id"] for r in revs])
        check("판 occurrence 둘 — W2_UNASSEMBLED, 매장에 VARIANT_MULTI 0",
              len(reasons) == 2 and all(r["reason"] == "W2_UNASSEMBLED" for r in reasons)
              and await db.fetchval("select count(*) from fact_occurrences where store_id=$1 "
                                    "and reason='VARIANT_MULTI'", s) == 0)
        step = await fact_of(src_b, "제조 순서", "잔에 붓는다")
        required = sorted(r["requires_revision_id"] for r in await db.fetch(
            "select requires_revision_id from fact_revision_requires "
            "where store_id=$1 and fact_revision_id=$2", s, step["head_revision_id"]))
        check("선행 관계 — 갈라진 두 판을 모두 가리킨다",
              required == sorted(r["fact_revision_id"] for r in revs))
        card_b = await db.fetchval("select card_id from knowledge_cards where store_id=$1 "
                                   "and source_id=$2 and title=$3", s, src_b, A)
        linked = {r["fact_id"] for r in await db.fetch(
            "select fact_id from card_facts where store_id=$1 and card_id=$2", s, card_b)}
        check("조립 ref f1 → 카드가 두 사실을 모두 잇고 LINKED",
              {r["fact_id"] for r in ledger_b} <= linked
              and all(r["assembly_state"] == "LINKED" for r in ledger_b))
        c_id, d_id = await entity(C), await entity(D)
        candidates = await list_candidates(db, s)
        check("후보 — (A,C)·(B,C)·(B,D) PENDING",
              all(len(pair(candidates, x, y)) == 1
                  for x, y in ((a_id, c_id), (b_id, c_id), (b_id, d_id))))

        # T3 — 자료 C: 다른 값 → 충돌 양쪽 보존, 승인 뒤 재처리
        check = _checker("W3-0 T3")
        src_c = await _new_source(db, s, user, "KAKAO")
        parts_c = [("합성 자료 본문 C", [_fact("f1", A, "물", "250", "ml")])]
        await _process(db, pool, s, user, src_c, parts_c, run_tag=604)
        groups = [g for g in await list_open_conflicts(db, s, entity_id=a_id)
                  if {str(f["quantity_value"]) for f in g["facts"]} == {"200", "250"}]
        check("200 ml·250 ml 두 사실 모두 남고 OPEN 충돌 1",
              len(groups) == 1 and len(groups[0]["facts"]) == 2
              and len(groups[0]["conflict_ids"]) == 1)
        forbidden = {"selected", "winner", "default", "chosen", "preferred"}
        check("기본 선택·승자 칸 없음", not (forbidden & set(groups[0]))
              and all(not (forbidden & set(f)) for f in groups[0]["facts"]))
        card_x = await db.fetchval(
            "select card_id from knowledge_cards where store_id=$1 and source_id=$2 "
            "and title=$3 order by card_id limit 1", s, src_a, A)
        published = await publish(card_x, "t3")
        check("A 카드 발행", published.status == "PUBLISHED")
        await _process(db, pool, s, user, src_c, parts_c, run_tag=605)
        head_c = next(r for r in await proposals(src_c) if r["entity_id"] == a_id)
        check("승인 뒤 재처리 → 머리 CONFLICT·matched_cards = [A 카드]",
              (head_c["relation_type"], head_c["status"]) == ("CONFLICT", "PENDING_REVIEW")
              and [m["card_id"] for m in json.loads(head_c["matched_cards"])] == [card_x])
        await db.execute("update upload_change_proposals set matched_cards='[]'::jsonb "
                         "where store_id=$1 and proposal_id=$2", s, head_c["proposal_id"])
        await _process(db, pool, s, user, src_c, parts_c, run_tag=606)
        again = next(r for r in await proposals(src_c) if r["entity_id"] == a_id)
        check("같은 순위(CONFLICT) 재처리 → matched_cards 새 계산으로 갱신(§3-3-3)",
              again["relation_type"] == "CONFLICT"
              and [m["card_id"] for m in json.loads(again["matched_cards"])] == [card_x])
        # 손으로 고치지 않고 실제로 영향 카드 묶음이 달라지는 경우 — 같은 대상 카드를 하나 더 발행
        check("자료 B 의 A 카드 발행", (await publish(card_b, "t3b")).status == "PUBLISHED")
        await _process(db, pool, s, user, src_c, parts_c, run_tag=613)
        grown = next(r for r in await proposals(src_c) if r["entity_id"] == a_id)
        check("같은 순위 재처리 + 승인 카드 하나 더 → 같은 제안의 matched_cards 가 두 카드로 갱신",
              grown["proposal_id"] == head_c["proposal_id"]
              and (grown["relation_type"], grown["status"]) == ("CONFLICT", "PENDING_REVIEW")
              and [m["card_id"] for m in json.loads(grown["matched_cards"])]
              == sorted([card_x, card_b]))

        # T5 — 대상 병합 → 후보·제안 정리
        check = _checker("W3-0 T5")
        src_e = await _new_source(db, s, user, "VOICE")
        src_f = await _new_source(db, s, user, "VOICE")
        src_h = await _new_source(db, s, user, "VOICE")
        parts_e = [("합성 자료 본문 E", [_fact("f1", B, "우유", "150", "ml")])]
        parts_f = [("합성 자료 본문 F", [_fact("f1", B, "얼음", "90", "g")])]
        # H 는 A·B 둘 다에 사실을 둔다 — 살아 있는 대상(A) 제안을 먼저 결정해 KEPT_PENDING 을 만든다
        parts_h = [("합성 자료 본문 H", [_fact("f1", A, "뚜껑", "1", "개"),
                                        _fact("f2", B, "빨대", "1", "개")])]
        await _process(db, pool, s, user, src_e, parts_e, run_tag=607)
        await _process(db, pool, s, user, src_f, parts_f, run_tag=608)
        await _process(db, pool, s, user, src_h, parts_h, run_tag=614)
        await db.execute("update upload_change_proposals set status='DISMISSED', decided_by=$3, "
                         "decided_at=now() where store_id=$1 and source_id=$2", s, src_f, user)
        await db.execute("update upload_change_proposals set status='DISMISSED', decided_by=$3, "
                         "decided_at=now() where store_id=$1 and source_id=$2 and entity_id=$4",
                         s, src_h, user, a_id)
        e_before = await proposals(src_e)
        f_dismissed = (await proposals(src_f))[0]["proposal_id"]
        h_before = {r["entity_id"]: r for r in await proposals(src_h)}
        check("H 제안 — A 는 DISMISSED, B 는 PENDING_REVIEW",
              set(h_before) == {a_id, b_id} and h_before[a_id]["status"] == "DISMISSED"
              and h_before[b_id]["status"] == "PENDING_REVIEW")
        heads_text = await _rows_text(db, "upload_change_proposals", "proposal_id", s)
        f_text = heads_text[f_dismissed]
        h_texts = {k: heads_text[r["proposal_id"]] for k, r in h_before.items()}
        bc = pair(candidates, b_id, c_id)[0]["candidate_id"]
        bd = pair(candidates, b_id, d_id)[0]["candidate_id"]
        await merge_entities(db, s, keep_entity_id=a_id, merged_entity_id=b_id, actor_id=user,
                             candidate_id=ab[0]["candidate_id"])
        rows = await db.fetch(
            "select candidate_id, entity_id_low, entity_id_high, status, decided_by, evidence "
            "from knowledge_entity_candidates where store_id=$1", s)
        by_id = {r["candidate_id"]: r for r in rows}
        check("병합된 대상이 낀 PENDING 후보 0", not [
            r for r in rows
            if r["status"] == "PENDING" and b_id in (r["entity_id_low"], r["entity_id_high"])])
        ac = pair(rows, a_id, c_id)
        check("(B,C) → MERGED 로 닫힘, (A,C) 는 PENDING 한 행 그대로",
              (by_id[bc]["status"], by_id[bc]["decided_by"]) == ("MERGED", user)
              and len(ac) == 1 and ac[0]["status"] == "PENDING")
        ad = pair(rows, a_id, d_id)
        check("(B,D) → MERGED, keep 쪽 (A,D) 새 PENDING 후보(옮긴 출처 기록)",
              by_id[bd]["status"] == "MERGED" and len(ad) == 1 and ad[0]["status"] == "PENDING"
              and json.loads(ad[0]["evidence"])["moved_from_candidate_id"] == bd)
        check("이력 CANDIDATE_MOVED 2 — MOVED·CLOSED", sorted(
            json.loads(e["payload"])["outcome"] for e in await events("CANDIDATE_MOVED"))
            == ["CLOSED", "MOVED"])
        await _process(db, pool, s, user, src_e, parts_e, run_tag=609)
        e_after = await proposals(src_e)
        check("병합 뒤 E 재처리 → 제안 1행, 같은 proposal_id 가 살아 있는 대상 A 로(MOVED)",
              len(e_after) == 1 and e_after[0]["proposal_id"] == e_before[0]["proposal_id"]
              and (e_after[0]["entity_id"], e_after[0]["status"]) == (a_id, "PENDING_REVIEW"))
        await _process(db, pool, s, user, src_a, parts_a, run_tag=610)
        a_after = await proposals(src_a)
        check("병합 뒤 A 재처리 → PENDING 제안은 대상 A 하나, 옛 B 제안은 SUPERSEDED",
              [r["entity_id"] for r in a_after if r["status"] == "PENDING_REVIEW"] == [a_id]
              and [r["status"] for r in a_after if r["entity_id"] == b_id] == ["SUPERSEDED"])
        await _process(db, pool, s, user, src_f, parts_f, run_tag=611)
        check("결정된 제안(F, DISMISSED) 행 그대로",
              (await _rows_text(db, "upload_change_proposals", "proposal_id", s))[f_dismissed]
              == f_text)
        await _process(db, pool, s, user, src_h, parts_h, run_tag=615)
        heads_text = await _rows_text(db, "upload_change_proposals", "proposal_id", s)
        h_after = await proposals(src_h)
        check("병합 뒤 H 재처리 → 살아 있는 A 제안이 결정됨 → 옛 B 제안 PENDING·대상 B 그대로, "
              "두 행 내용 그대로(KEPT_PENDING)",
              len(h_after) == 2
              and all(heads_text[r["proposal_id"]] == h_texts[k] for k, r in h_before.items()))
        kept = [json.loads(e["payload"]) for e in await events("PROPOSAL_MOVED")
                if json.loads(e["payload"])["outcome"] == "KEPT_PENDING"]
        check("KEPT_PENDING 이력 1 — 옛 B 제안 → 결정된 A 제안을 가리킨다",
              len(kept) == 1 and kept[0]["proposal_id"] == h_before[b_id]["proposal_id"]
              and kept[0]["into_proposal_id"] == h_before[a_id]["proposal_id"]
              and kept[0]["source_id"] == src_h)
        check("MERGED 대상 아래 PENDING 제안은 KEPT_PENDING 된 H 의 B 제안 하나뿐", [
            r["proposal_id"] for r in await db.fetch(
                "select p.proposal_id from upload_change_proposals p join knowledge_entities e "
                "on e.store_id = p.store_id and e.entity_id = p.entity_id "
                "where p.store_id=$1 and p.status='PENDING_REVIEW' and e.status='MERGED'", s)]
            == [h_before[b_id]["proposal_id"]])
        moved_events = [(e["entity_id"], e["other_entity_id"], json.loads(e["payload"]))
                        for e in await events("PROPOSAL_MOVED")]
        check("이력 PROPOSAL_MOVED — MOVED(E)·SUPERSEDED(A)·KEPT_PENDING(H), 모두 B → A",
              sorted((p["outcome"], p["source_id"]) for _, _, p in moved_events)
              == sorted([("MOVED", src_e), ("SUPERSEDED", src_a), ("KEPT_PENDING", src_h)])
              and all((live, merged) == (a_id, b_id) for live, merged, _ in moved_events))

        # T6 — 대상 분리 → 이력, 공개본·카드 행 불변
        check = _checker("W3-0 T6")
        all_cards = [r["card_id"] for r in await db.fetch(
            "select card_id from knowledge_cards where store_id=$1", s)]
        published_before = await _published_fingerprint(db, s)
        cards_before = await _card_rows(db, s, all_cards)
        props_before = await _proposal_rows(db, s)
        ice = await fact_of(src_a, "얼음", "100")
        new_entity = await split_entity(db, s, entity_id=a_id, fact_ids=[ice["fact_id"]],
                                        new_canonical_name="합성 얼음 대상",
                                        move_alias_norms=[], actor_id=user)
        moved = await db.fetchval("select entity_id from knowledge_facts where store_id=$1 "
                                  "and fact_id=$2", s, ice["fact_id"])
        check("분리 → 새 대상·사실 이동·이력 SPLIT 1",
              new_entity != a_id and moved == new_entity and len(await events("SPLIT")) == 1)
        check("공개본·카드 행·제안 그대로",
              await _published_fingerprint(db, s) == published_before
              and await _card_rows(db, s, all_cards) == cards_before
              and await _proposal_rows(db, s) == props_before)

        # T7 — 점주 정정 → 새 판, 옛 이관 정정은 그 위에 얹히지 않는다
        check = _checker("W3-0 T7")
        water = await fact_of(src_a, "물", "200")
        owner_rev = await revise_fact(
            db, s, fact_id=water["fact_id"], expected_head_revision_id=water["head_revision_id"],
            change=FactChange(value="210", original_assertion="물은 210ml 로 바꿨어요"),
            change_kind="OWNER_CORRECTION", actor_id=user)
        await db.execute("update source_facts set corrected_value='205', corrected_by=$3 "
                         "where store_id=$1 and fact_id=$2", s, water["source_fact_id"], user)
        first = await import_legacy_correction(db, s, source_fact_id=water["source_fact_id"])
        second = await import_legacy_correction(db, s, source_fact_id=water["source_fact_id"])
        head = await db.fetchval("select head_revision_id from knowledge_facts "
                                 "where store_id=$1 and fact_id=$2", s, water["fact_id"])
        check("점주 정정 → 새 head", owner_rev != water["head_revision_id"] and head == owner_rev)
        check("옛 corrected_value 이관 → None 두 번, head 그대로, LEGACY 판 0",
              first is None and second is None and head == owner_rev
              and await db.fetchval("select count(*) from fact_revision_meta where store_id=$1 "
                                    "and change_kind='LEGACY_CORRECTION'", s) == 0)

        # T8 — 플래그를 다시 끈 뒤 처리
        check = _checker("W3-0 T8")
        counts = await _w2_counts(db, s)
        props = await _proposal_rows(db, s)
        candidate_n = await db.fetchval(
            "select count(*) from knowledge_entity_candidates where store_id=$1", s)
        event_n = await db.fetchval(
            "select count(*) from knowledge_entity_events where store_id=$1", s)
        src_g = await _new_source(db, s, user, "SCAN")
        await _process(db, pool, s, user, src_g, [("합성 자료 본문 G", [
            _fact("f1", A, "에스프레소", "3", "샷", variant="HOT/ICE")])],
            run_tag=612, flags=False)
        check("꺼짐 → W2 표·제안·후보·이력 행 그대로",
              await _w2_counts(db, s) == counts and await _proposal_rows(db, s) == props
              and await db.fetchval("select count(*) from knowledge_entity_candidates "
                                    "where store_id=$1", s) == candidate_n
              and await db.fetchval("select count(*) from knowledge_entity_events "
                                    "where store_id=$1", s) == event_n)
        g_rows = await db.fetch("select local_ref, variant from source_facts "
                                "where store_id=$1 and source_id=$2", s, src_g)
        check("꺼짐 → HOT/ICE 는 나누지 않고 원장 한 행(이전과 같다)",
              [(r["local_ref"], r["variant"]) for r in g_rows] == [("f1", "HOT/ICE")])
        check("꺼짐 → 새 카드 entity_id null", await db.fetchval(
            "select count(*) from knowledge_cards where store_id=$1 and source_id=$2 "
            "and entity_id is not null", s, src_g) == 0)
    finally:
        await pool.close()
    print("PASS W3-0 flag readiness all scenarios")
