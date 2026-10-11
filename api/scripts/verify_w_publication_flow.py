"""격리 실제 DB: 합성 카드 2장으로 W 공개 경로 전체를 통과시킨다 (Task 7).

verify_r_schema_rebuild 가 만든 새 UUID DB(모든 migration 적용)의 연결만 받는다.
외부 호출은 전부 합성이다 — R 색인 준비의 임베딩과 점주 답변 사실 추출
(extract_facts)을 고정 대역으로 바꾼다. 실제 SQL·트리거·잠금·
savepoint·R 읽기 쪽 hash/manifest 검사는 그대로 돈다.
§9 점주 답변 worker 는 `verify_owner_answer_worker` 가 새 매장에서 따로 돈다(Phase A 사실 경로).
Phase A Task 7: 모든 카드는 사실 카드 픽스처(seed_fact_card)로 만든다 — 원문(RAW) 카드 공개
경로와 카드 행 쓰기로 판을 만들던 레거시 트리거가 없어졌다. 12 구간은 점주 답변을 사실 경로
(추출만 합성)로 처리하고, 13 구간은 초기 색인 준비(bootstrap)를 확인한다.
"""
import asyncio
from contextlib import ExitStack
from unittest.mock import patch

from fastapi import BackgroundTasks

from app.cards import repository as card_repo
from app.cards import router as card_router
from app.cards import owner_answer_worker
from app.cards.owner_answer_worker import process_next_owner_event
from app.ingest import extract
from app.contracts.usage import UsageContext
from app.db_session import ShortSession
from app.errors import ApiError
from app.learn.knowledge_apply import approve_owner_proposal
from app.ingest import router as ingest_router
from app.ingest.schemas import CreateIngestJobRequest
from app.learn.owner_delivery import submit_owner_answer
from app.learn.owner_handoff import finish_owner_review
from app.publish import approval
from app.publish.approval import CardChange, publish_cards
from app.publish.bootstrap import READY, bootstrap_store_index, index_status
from app.publish.content import current_manifest
from app.reg.hybrid import hybrid_search, read_current_index
from _fact_card_fixture import (
    _mock_settings, _vectors, assertion, attribute_cost, blockless_card, edit_fact_value,
    publish_card, seed_fact_card)
from verify_w_fact_only import _extracting

# 합성 벡터. 0 이 아닌 1536 차원이면 R 준비 검사를 통과한다
VECTOR = [1.0] + [0.0] * 1535


# -- 9. 점주 답변 worker (Phase A 사실 경로) ------------------------------------
async def verify_owner_answer_worker(pool, admin):
    """점주 답변 → OWNER_TEXT 자료 → 사실 카드. 새 합성 매장에서 따로 돈다.

    관계 분석(build_knowledge_plan)은 더 이상 없다. 추출만 합성 대역이고 원장·조립(mock)·
    사실 카드·공개·R 완료 보고는 실제 코드다.
      IDENTICAL: 이미 공개된 같은 사실 → LINKED(공개판 불변)
      NEW: 새 대상 사실 → 새 사실 카드 자동 공개(PUBLISHED)
      SUPPLEMENT: 공개 카드에 새 사실 → REVIEW, 나중 승인(R 완료 접점 실제 호출)으로 공개
    """
    passed = []

    def check(name, ok):
        assert ok, name
        passed.append(name)
        print("PASS W publish", name)

    uid = await admin.fetchval(
        "insert into users(name,role) values('합성 W 답변 점주','OWNER') returning user_id")
    sid = await admin.fetchval(
        "insert into stores(owner_id,store_name,business_type) values($1,'합성 W 답변 매장','CAFE') returning store_id",
        uid)
    mid = await admin.fetchval(
        "insert into store_members(store_id,user_id,member_role) values($1,$2,'OWNER') returning member_id",
        sid, uid)
    await admin.execute(
        "insert into task_categories(store_id,category_name,is_system) values($1,'기타',true) "
        "on conflict (store_id, category_name) do nothing", sid)
    store = dict(uid=uid, sid=sid, mid=mid)

    async def owner_event(key, text):
        qid = await admin.fetchval(
            """insert into pending_questions(store_id,member_id,question_text,contract_version,semantic_key)
            values($1,$2,$3,'v2',$4) returning question_id""",
            sid, mid, f"{key} 질문", f"synthetic-w9-{key}")
        reply = await submit_owner_answer(pool, store_id=sid, member_id=mid, question_id=qid,
                                          request_id=f"w-publish-{key}", answer=text,
                                          expected_revision=0)
        return int(reply["owner_answer_id"])

    async def process(*assertions):
        settings = _mock_settings()
        with patch("app.ingest.extract.extract_facts", _extracting(*assertions)), \
                patch.object(extract, "get_settings", lambda: settings), \
                patch("app.reg.index_preparation.recorded_embeddings", _vectors):
            return await process_next_owner_event(pool, store_id=sid)

    async def knowledge_state(answer_id):
        return await admin.fetchval(
            "select status from r_owner_knowledge_states where store_id=$1 and owner_answer_id=$2",
            sid, answer_id)

    async def publication():
        return await admin.fetchrow(
            "select knowledge_revision,current_snapshot_id from knowledge_publications where store_id=$1",
            sid)

    async def card_row(card_id):
        return await admin.fetchrow(
            "select draft_version_id,published_version_id,review_status from knowledge_cards "
            "where store_id=$1 and card_id=$2", sid, card_id)

    async def proposal_of(answer_id):
        return await admin.fetchrow(
            "select proposal_id,relation_type,status,target_card_id from knowledge_change_proposals "
            "where store_id=$1 and answer_id=$2", sid, answer_id)

    async def current_cards():
        async with pool.acquire() as conn:
            snapshot, _, _ = await read_current_index(conn, store_id=sid)
        return {x.card_id: x.card_version_id for x in snapshot.cards}

    # 공개된 사실 카드 B (음료Z 물 225ml)
    water = assertion("f1", "음료Z", "물", "225", unit="ml")
    b, b1 = await seed_fact_card(pool, store_id=sid, owner_user_id=uid, assertions=[water],
                                 title="합성 W 답변 자료")
    published = await publish_card(pool, store_id=sid, member_id=mid, actor_user_id=uid, card_id=b)
    check("9 fact card B published", published.status == "PUBLISHED")
    revision = (await publication())["knowledge_revision"]

    identical = await owner_event("identical", "음료Z 물 225ml")
    status = await process(water)
    proposal = await proposal_of(identical)
    check("9 IDENTICAL fact links published card",
          status == "LINKED" and await knowledge_state(identical) == "LINKED"
          and (proposal["relation_type"], proposal["status"]) == ("IDENTICAL", "LINKED")
          and (await publication())["knowledge_revision"] == revision
          and (await card_row(b))["published_version_id"] == b1
          and await admin.fetchval("select card_id from owner_answers where answer_id=$1", identical) == b)

    new = await owner_event("new", "음료Y 얼음 150g")
    status = await process(assertion("f1", "음료Y", "얼음", "150", unit="g"))
    new_card = await admin.fetchval("select card_id from owner_answers where answer_id=$1", new)
    pub = await publication()
    check("9 NEW fact publishes new card into snapshot",
          status == "PUBLISHED" and new_card is not None and new_card != b
          and pub["knowledge_revision"] == revision + 1
          and await knowledge_state(new) == "PUBLISHED"
          and (await proposal_of(new))["status"] == "PUBLISHED")
    check("9 NEW card served by R index", str(new_card) in await current_cards())

    supplement = await owner_event("supplement", "음료Z 시럽 30ml")
    status = await process(assertion("f1", "음료Z", "시럽", "30", unit="ml"))
    proposal = await proposal_of(supplement)
    b_row = await card_row(b)
    check("9 SUPPLEMENT goes to review without publishing",
          status == "REVIEW" and proposal["relation_type"] == "SUPPLEMENT"
          and proposal["status"] == "PENDING_REVIEW" and proposal["target_card_id"] == b
          and await knowledge_state(supplement) == "REVIEW"
          and (await publication())["knowledge_revision"] == revision + 1
          and b_row["published_version_id"] == b1 and b_row["draft_version_id"] != b1)
    check("9 no event left", await process_next_owner_event(pool, store_id=sid) is None)

    # 나중 승인 — 실제 R 완료 접점(finish_owner_review)을 hook 안에서 부른다
    notified = []

    async def notify_r(conn, answer_id, card_id, version_id, knowledge_revision):
        pid = await conn.fetchval(
            "select proposal_id from knowledge_change_proposals where store_id=$1 and answer_id=$2",
            sid, answer_id)
        await finish_owner_review(conn, store_id=sid, proposal_id=pid, owner_answer_id=answer_id,
                                  card_id=card_id, card_version_id=version_id,
                                  knowledge_revision=knowledge_revision)
        notified.append((conn.is_in_transaction(), answer_id, card_id, version_id,
                         knowledge_revision))

    async def approve():
        context = UsageContext(store_id=str(sid), cost_phase="OPERATING", cost_purpose="PRODUCT",
                               stage="EMBED", operation_id="w-publish:proposal",
                               logical_call_id="w-publish:proposal:embed")
        with patch("app.reg.index_preparation.recorded_embeddings", _vectors):
            return await approve_owner_proposal(
                pool, store_id=sid, member_id=mid, actor_user_id=uid,
                proposal_id=proposal["proposal_id"], usage_context=context, notify_r=notify_r)

    before_pub = dict(await publication())
    try:
        with patch("app.learn.owner_handoff.notify_publication",
                   side_effect=RuntimeError("synthetic review notification failure")):
            await approve()
    except RuntimeError:
        pass
    else:
        raise AssertionError("R review failure did not abort W publication")
    check("9 R completion failure rolls back W publication and review",
          dict(await publication()) == before_pub
          and (await card_row(b))["published_version_id"] == b1
          and await knowledge_state(supplement) == "REVIEW"
          and (await proposal_of(supplement))["status"] == "PENDING_REVIEW")
    result = await approve()
    b2 = (await card_row(b))["published_version_id"]
    check("9 SUPPLEMENT approval publishes B's new fact draft",
          result.status == "PUBLISHED" and b2 == b_row["draft_version_id"]
          and (await current_cards()).get(str(b)) == str(b2))
    check("9 notify_r ran inside publication transaction",
          notified == [(True, supplement, b, b2, result.knowledge_revision)])
    check("9 proposal closed and R completed",
          (await proposal_of(supplement))["status"] == "PUBLISHED"
          and await knowledge_state(supplement) == "PUBLISHED")
    result = await approve()
    check("9 approval replay is ALREADY_APPLIED",
          result.status == "ALREADY_APPLIED" and len(notified) == 1)
    print(f"Verified {len(passed)} W owner answer worker checks")


async def verify(pool, admin):
    passed = []

    def check(name, ok):
        assert ok, name
        passed.append(name)
        print("PASS W publish", name)

    embed_calls = []
    embed_inputs = []
    # 준비와 공개 트랜잭션 사이에 끼워 넣을 동작(시나리오 3)
    between = []

    async def fake_embedder(texts, *, context, sink=None):
        embed_calls.append(context)
        embed_inputs.append(list(texts))
        if between:
            await between.pop(0)()
        return [list(VECTOR) for _ in texts]

    # -- seed -------------------------------------------------------------
    async def seed_store(name):
        uid = await admin.fetchval(
            "insert into users(name,role) values($1,'OWNER') returning user_id", f"합성 {name} 점주")
        sid = await admin.fetchval(
            "insert into stores(owner_id,store_name,business_type) values($1,$2,'CAFE') returning store_id",
            uid, f"합성 {name} 매장")
        mid = await admin.fetchval(
            "insert into store_members(store_id,user_id,member_role) values($1,$2,'OWNER') returning member_id",
            sid, uid)
        system = await admin.fetchval(
            "select category_id from task_categories where store_id=$1 and is_system and deleted_at is null",
            sid)
        if system is None:
            system = await admin.fetchval(
                "insert into task_categories(store_id,category_name,is_system) values($1,'기타',true) returning category_id",
                sid)
        return dict(uid=uid, sid=sid, mid=mid, category=system)

    async def seed_card(store, subject, value):
        """사실 카드 초안 하나(대상 `subject`, 사실 `물 {value}ml`). 공개하지 않는다."""
        card_id, _ = await seed_fact_card(
            pool, store_id=store["sid"], owner_user_id=store["uid"],
            assertions=[assertion("f1", subject, "물", value, unit="ml")],
            title=f"{subject} 자료")
        # 승인 라우트의 비용 귀속(card_usage_context)이 이어받을 원본 작업 기록
        await attribute_cost(admin, store_id=store["sid"], card_id=card_id)
        return card_id

    async def blockless(store, title):
        """사실 블록 없는 판 1 카드(출처 없음). 공개 경로가 거절해야 한다."""
        card_id, _ = await blockless_card(admin, store_id=store["sid"],
                                          category_id=store["category"], title=title,
                                          content=f"{title} 원문")
        return card_id

    def values(snap, card_id):
        """공개판에서 카드 블록이 가리키는 사실들의 수치."""
        ids = {rid for blk in snap.card(str(card_id)).blocks for rid in blk.fact_revision_ids}
        return {f.quantity.value for f in snap.fact_revisions
                if f.fact_revision_id in ids and f.quantity is not None}

    async def card_row(store, card_id):
        return await admin.fetchrow(
            "select draft_version_id,published_version_id,review_status,is_verified from knowledge_cards where store_id=$1 and card_id=$2",
            store["sid"], card_id)

    async def publication(store):
        return await admin.fetchrow(
            "select publication_revision,knowledge_revision,current_snapshot_id from knowledge_publications where store_id=$1",
            store["sid"])

    async def snapshot_count(store):
        return await admin.fetchval("select count(*) from knowledge_snapshots where store_id=$1", store["sid"])

    async def snapshot_versions(store, snapshot_id):
        rows = await admin.fetch(
            "select card_id,card_version_id from snapshot_card_versions where store_id=$1 and snapshot_id=$2",
            store["sid"], snapshot_id)
        return {r["card_id"]: r["card_version_id"] for r in rows}

    async def current_index(store):
        async with pool.acquire() as conn:
            snapshot, _, _ = await read_current_index(conn, store_id=store["sid"])
        return snapshot

    def usage(store, name):
        return UsageContext(store_id=str(store["sid"]), cost_phase="OPERATING", cost_purpose="PRODUCT",
                            stage="EMBED", operation_id=f"w-publish:{name}",
                            logical_call_id=f"w-publish:{name}:embed")

    async def publish(store, changes, key, **kwargs):
        return await publish_cards(
            pool, store_id=store["sid"], member_id=store["mid"], actor_user_id=store["uid"],
            changes=changes, idempotency_key=key, usage_context=usage(store, key), **kwargs)

    def change(card_id, version_id):
        return CardChange(card_id, version_id, version_id)

    async def edit(store, card_id, value):
        # 자유 글 편집(create_draft)은 없어졌다 — 사실 편집 라우트로 첫 사실 값만 바꾼다
        return await edit_fact_value(pool, store_id=store["sid"], owner_user_id=store["uid"],
                                     card_id=card_id, value=value,
                                     key=f"w-publish-edit-{card_id}-{value}")

    with ExitStack() as stack:
        stack.enter_context(patch("app.reg.index_preparation.recorded_embeddings", fake_embedder))
        stack.enter_context(patch.object(card_router, "get_pool", lambda: pool))

        s1 = await seed_store("W 공개")
        s2 = await seed_store("W 다른")

        # 다른 매장 카드를 먼저 공개해 둔다. 매장 1의 어떤 판에도 섞이면 안 된다
        other = await seed_card(s2, "다른 매장 카드", "300")
        other_v = (await card_row(s2, other))["draft_version_id"]
        result = await publish(s2, [change(other, other_v)], "w-other-first")
        check("other store publishes independently", result.status == "PUBLISHED")

        # -- 1. 첫 승인 --------------------------------------------------------
        a = await seed_card(s1, "합성 카드 A", "100")
        b = await seed_card(s1, "합성 카드 B", "200")
        a1 = (await card_row(s1, a))["draft_version_id"]
        b1 = (await card_row(s1, b))["draft_version_id"]
        result = await publish(s1, [change(a, a1), change(b, b1)], "w-first-approve")
        pub = await publication(s1)
        check("1 first approval publishes revision 1",
              result.status == "PUBLISHED" and result.knowledge_revision == 1
              and pub["knowledge_revision"] == 1 and pub["current_snapshot_id"] == result.snapshot_id)
        check("1 snapshot holds A and B",
              await snapshot_versions(s1, result.snapshot_id) == {a: a1, b: b1})
        rows = [await card_row(s1, c) for c in (a, b)]
        check("1 card pointers approved",
              all(r["review_status"] == "APPROVED" and r["is_verified"] for r in rows)
              and rows[0]["published_version_id"] == a1 and rows[1]["published_version_id"] == b1)
        snap = await current_index(s1)
        check("1 R read_current_index verifies hash and sees both cards",
              {c.card_id for c in snap.cards} == {str(a), str(b)}
              and snap.knowledge_revision == "1" and snap.snapshot_id == str(result.snapshot_id))
        check("1 fact card publishes fact blocks with source provenance only",
              all(blk.raw_span_id is None and blk.fact_revision_ids for blk in snap.card(str(a)).blocks)
              and not snap.raw_spans and values(snap, a) == {"100"}
              and all(p.source_id is not None and p.owner_answer_id is None
                      for f in snap.fact_revisions for p in f.provenance))
        first_snapshot = result.snapshot_id

        # -- 2. A만 수정·재승인 -------------------------------------------------
        a2 = await edit(s1, a, "110")
        calls_before_edit = len(embed_calls)
        result = await publish(s1, [change(a, a2)], "w-a-second")
        check("2 only changed A is embedded while B vector is reused",
              len(embed_calls) == calls_before_edit+1
              and len(embed_inputs[-1]) == 1 and "110" in embed_inputs[-1][0]
              and "합성 카드 A" in embed_inputs[-1][0])
        versions = await snapshot_versions(s1, result.snapshot_id)
        check("2 re-approval moves only A",
              result.status == "PUBLISHED" and versions == {a: a2, b: b1}
              and result.knowledge_revision == 2
              and (await card_row(s1, a))["published_version_id"] == a2)
        check("2 old snapshot keeps A's old version",
              (await snapshot_versions(s1, first_snapshot))[a] == a1)
        snap = await current_index(s1)
        check("2 R index serves new A fact value", values(snap, a) == {"110"})

        # -- 3. 준비 뒤 초안이 또 바뀐다 → STALE ---------------------------------
        a3 = await edit(s1, a, "120")
        before_pub, before_count = await publication(s1), await snapshot_count(s1)
        injected = {}

        async def concurrent_edit():
            injected["version"] = await edit(s1, a, "130")

        between.append(concurrent_edit)
        result = await publish(s1, [change(a, a3)], "w-a-stale")
        a4 = injected["version"]
        check("3 draft changed after prepare is STALE",
              result.status == "STALE" and dict(await publication(s1)) == dict(before_pub)
              and await snapshot_count(s1) == before_count
              and (await card_row(s1, a))["published_version_id"] == a2)

        # -- 4. activate 실패 → 전부 롤백 ----------------------------------------
        async def failing_activate(*args, **kwargs):
            raise ApiError(409, "HASH_MISMATCH", "합성 활성화 실패")

        with patch.object(approval, "activate_prepared_index", failing_activate):
            try:
                await publish(s1, [change(a, a4)], "w-a-activate")
            except ApiError as exc:
                raised = exc.code == "HASH_MISMATCH"
            else:
                raised = False
        check("4 activate failure raises", raised)
        check("4 activate failure keeps publication, pointers, snapshots",
              dict(await publication(s1)) == dict(before_pub)
              and await snapshot_count(s1) == before_count
              and (await card_row(s1, a))["published_version_id"] == a2
              and (await card_row(s1, a))["review_status"] == "APPROVED"
              and not await admin.fetchval(
                  "select exists(select 1 from operations where store_id=$1 and idempotency_key='w-a-activate')",
                  s1["sid"]))
        result = await publish(s1, [change(a, a4)], "w-a-activate")
        check("4 same request retries after rollback",
              result.status == "PUBLISHED" and result.knowledge_revision == 3
              and (await card_row(s1, a))["published_version_id"] == a4)
        applied = result

        # -- 5. 같은 멱등 키 재요청 ----------------------------------------------
        count = await snapshot_count(s1)
        calls = len(embed_calls)
        result = await publish(s1, [change(a, a4)], "w-a-activate")
        check("5 same key replays ALREADY_APPLIED without prepare",
              result.status == "ALREADY_APPLIED" and result.snapshot_id == applied.snapshot_id
              and result.knowledge_revision == 3 and await snapshot_count(s1) == count
              and len(embed_calls) == calls)
        result = await publish(s1, [change(b, b1)], "w-a-activate")
        check("5 same key different body rejected",
              result.status == "STALE" and result.error_code == "IDEMPOTENCY_CONFLICT")

        # -- 5b. 색인 준비 뒤 점유를 잃었다 → LEASE_LOST, 아무것도 쓰지 않는다 ----------
        before_pub, before_count = await publication(s1), await snapshot_count(s1)
        lease_calls = []

        async def lease_lost():
            lease_calls.append("after_prepare")
            return False

        result = await publish(s1, [change(a, a4)], "w-a-lease", after_prepare=lease_lost)
        check("5b lease lost after prepare returns LEASE_LOST without publishing",
              result.status == "LEASE_LOST" and lease_calls == ["after_prepare"]
              and dict(await publication(s1)) == dict(before_pub)
              and await snapshot_count(s1) == before_count
              and (await card_row(s1, a))["published_version_id"] == a4
              and not await admin.fetchval(
                  "select exists(select 1 from operations where store_id=$1 and idempotency_key='w-a-lease')",
                  s1["sid"]))

        # -- 6. A 제외 → R 검색에서 빠지고 과거 snapshot 은 남는다 --------------
        claims = dict(role="OWNER", user_id=s1["uid"], store_id=s1["sid"])
        count = await snapshot_count(s1)
        excluded = await card_router.exclude_card(a, ShortSession(pool), claims)
        snap = await current_index(s1)
        check("6 exclude route republishes current snapshot without A",
              await snapshot_count(s1) == count + 1
              and {x.card_id for x in snap.cards} == {str(b)}
              and a not in await snapshot_versions(s1, (await publication(s1))["current_snapshot_id"]))
        found = await hybrid_search(pool, store_id=s1["sid"], question="합성 카드", query_vector=VECTOR)
        check("6 excluded A leaves R search",
              excluded.review_status == "EXCLUDED"
              and {c.card_id for c in found.candidates} == {str(b)})
        check("6 R approval filter drops A",
              await admin.fetchval(
                  "select array_agg(card_id order by card_id) from knowledge_cards where store_id=$1 and review_status='APPROVED'",
                  s1["sid"]) == [b])
        check("6 past snapshots keep A rows",
              await admin.fetchval(
                  "select count(*) from snapshot_card_versions where store_id=$1 and card_id=$2",
                  s1["sid"], a) == 3)
        async with pool.acquire() as conn:
            check("6 next manifest drops excluded A",
                  await current_manifest(conn, store_id=s1["sid"]) == {b: b1})

        # -- 7. 사실 블록 없는 카드 --------------------------------------------
        # 원문(RAW) 카드·점주 답변 RAW span 공개는 없어졌다(Phase A). 블록 없는 판은 공개하지 않는다
        c = await blockless(s1, "합성 카드 C")
        c1 = (await card_row(s1, c))["draft_version_id"]
        count = await snapshot_count(s1)
        result = await publish(s1, [change(c, c1)], "w-c-blockless")
        check("7 card without fact blocks is INVALID_CONTENT and leaves no trace",
              result.status == "INVALID_CONTENT" and await snapshot_count(s1) == count
              and (await card_row(s1, c))["published_version_id"] is None
              and not await admin.fetchval(
                  "select exists(select 1 from card_version_blocks where store_id=$1 and card_version_id=$2)",
                  s1["sid"], c1))

        # -- 8. 다른 매장 답변으로 raw_span → 트리거 ------------------------------
        q2 = await admin.fetchval(
            """insert into pending_questions(store_id,member_id,question_text,contract_version,semantic_key)
            values($1,$2,'다른 매장 질문','v2','synthetic-other') returning question_id""", s2["sid"], s2["mid"])
        answer_other = await admin.fetchval(
            "insert into owner_answers(question_id,answered_by,answer_text) values($1,$2,'다른 매장 답') returning answer_id",
            q2, s2["uid"])
        # raw_spans 표·교차 매장 트리거는 남아 있으므로 계속 검사한다(공개 경로는 쓰지 않는다)
        for table, sql in (
            ("raw_spans", "insert into raw_spans(store_id,owner_answer_id,span_text) values($1,$2,'교차')"),
            ("card_versions",
             "update card_versions set owner_answer_id=$2 where store_id=$1 and version_id=" + str(c1)),
        ):
            try:
                async with admin.transaction():
                    await admin.execute(sql, s1["sid"], answer_other)
            except Exception as exc:
                rejected = "매장" in str(exc)
            else:
                rejected = False
            check(f"8 cross-store owner answer rejected by {table} trigger", rejected)

        # -- 9·10. 점주 답변 worker·나중 승인 — 사실 경로(Phase A), 새 매장에서 따로 돈다 --
        await verify_owner_answer_worker(pool, admin)

        # -- 11. HTTP 승인 라우트 ----------------------------------------------
        d = await seed_card(s1, "합성 카드 D", "400")
        count = await snapshot_count(s1)
        # 준비와 공개 사이 함께 실릴 카드 B 가 제외되면 공개하지 않는다(manifest 전체 잠금·CAS)
        async def exclude_b():
            await card_router.exclude_card(b, ShortSession(pool), claims)

        between.append(exclude_b)
        try:
            await card_router.approve_card(d, ShortSession(pool), claims)
        except ApiError as exc:
            conflict = exc.status_code == 409 and exc.code == "CARD_VERSION_CONFLICT"
        else:
            conflict = False
        # 끼어든 제외 라우트 자신은 B 없는 판을 재발행한다(+1). D 의 공개는 롤백된다
        check("11 manifest card excluded during prepare makes route 409",
              conflict and await snapshot_count(s1) == count + 1
              and str(b) not in {x.card_id for x in (await current_index(s1)).cards}
              and (await card_row(s1, d))["published_version_id"] is None)
        await card_router.restore_card(b, ShortSession(pool), claims)
        check("11 restore route republishes B back into R index",
              await snapshot_count(s1) == count + 2
              and str(b) in {x.card_id for x in (await current_index(s1)).cards})
        mutation = await card_router.approve_card(d, ShortSession(pool), claims)
        d1 = (await card_row(s1, d))["draft_version_id"]
        pub = await publication(s1)
        check("11 approve route publishes through publish_cards",
              mutation.review_status == "APPROVED" and mutation.published_version_id == d1
              and await snapshot_count(s1) == count + 3
              and (await snapshot_versions(s1, pub["current_snapshot_id"]))[d] == d1)
        count += 2
        check("11 approve route writes no legacy card_embeddings",
              await admin.fetchval(
                  "select count(*) from card_embeddings where store_id=$1", s1["sid"]) == 0)
        again = await card_router.approve_card(d, ShortSession(pool), claims)
        check("11 approve route replay is idempotent",
              again.published_version_id == d1 and await snapshot_count(s1) == count + 1)

        # 제외 뒤 여러 판이 나간 A 도 복원 라우트만으로 R 색인에 돌아온다(final fix #1)
        restored = await card_router.restore_card(a, ShortSession(pool), claims)
        snap = await current_index(s1)
        check("restore alone brings A back into R index",
              restored.review_status == "APPROVED" and restored.published_version_id == a4
              and snap.card(str(a)) is not None and snap.card(str(a)).card_version_id == str(a4)
              and (await snapshot_versions(s1, int(snap.snapshot_id)))[a] == a4)

        # 라우트로 승인 → 제외 → 복원 한 바퀴
        e = await seed_card(s1, "합성 카드 E", "500")
        await card_router.approve_card(e, ShortSession(pool), claims)
        e1 = (await card_row(s1, e))["published_version_id"]
        check("E approved through route is in R index",
              str(e) in {x.card_id for x in (await current_index(s1)).cards})
        await card_router.exclude_card(e, ShortSession(pool), claims)
        snap = await current_index(s1)
        check("E excluded through route is absent from new current snapshot",
              str(e) not in {x.card_id for x in snap.cards}
              and e not in await snapshot_versions(s1, int(snap.snapshot_id)))
        await card_router.restore_card(e, ShortSession(pool), claims)
        snap = await current_index(s1)
        check("E restored through route is back in current snapshot and R index",
              snap.card(str(e)) is not None and snap.card(str(e)).card_version_id == str(e1)
              and (await snapshot_versions(s1, int(snap.snapshot_id))).get(e) == e1)

        # 사실 블록 없는 판을 라우트로 승인하면 409 CARD_CONTENT_INVALID, 아무것도 남기지 않는다
        empty_new = await blockless(s1, "합성 빈 카드")
        count = await snapshot_count(s1)
        try:
            await card_router.approve_card(empty_new, ShortSession(pool), claims)
        except ApiError as exc:
            invalid = exc.status_code == 409 and exc.code == "CARD_CONTENT_INVALID"
        else:
            invalid = False
        check("blockless card approval is 409 CARD_CONTENT_INVALID",
              invalid and await snapshot_count(s1) == count
              and (await card_row(s1, empty_new))["published_version_id"] is None
              and not await admin.fetchval(
                  "select exists(select 1 from card_version_blocks where store_id=$1 and card_version_id=$2)",
                  s1["sid"], (await card_row(s1, empty_new))["draft_version_id"]))

        # -- 동시 공개: 둘 다 성공했다면 나중 판이 앞 판의 카드를 잃지 않는다 --
        f = await seed_card(s1, "합성 카드 F", "600")
        g = await seed_card(s1, "합성 카드 G", "700")
        fv = (await card_row(s1, f))["draft_version_id"]
        gv = (await card_row(s1, g))["draft_version_id"]
        results = await asyncio.gather(publish(s1, [change(f, fv)], "w-race-f"),
                                       publish(s1, [change(g, gv)], "w-race-g"))
        versions = await snapshot_versions(s1, (await publication(s1))["current_snapshot_id"])
        won = [card for card, r in zip((f, g), results) if r.status == "PUBLISHED"]
        check("race at least one concurrent publish wins",
              bool(won) and all(r.status in ("PUBLISHED", "STALE", "PREPARE_FAILED") for r in results))
        lost = [card for card, r in zip((f, g), results) if r.status != "PUBLISHED"]
        lost_pointers = [(await card_row(s1, card))["published_version_id"] for card in lost]
        check("race no lost update in current snapshot",
              all(card in versions for card in won) and all(p is None for p in lost_pointers))
        for card, version, r in zip((f, g), (fv, gv), results):
            if r.status != "PUBLISHED":
                retry = await publish(s1, [change(card, version)], f"w-race-retry-{card}")
                check("race loser retries cleanly", retry.status == "PUBLISHED")
        versions = await snapshot_versions(s1, (await publication(s1))["current_snapshot_id"])
        check("race both cards end up published", f in versions and g in versions)

        # 두 요청이 같은 판으로 준비를 마친 뒤 공개 트랜잭션에서 만나게 강제한다
        h = await seed_card(s1, "합성 카드 H", "800")
        i = await seed_card(s1, "합성 카드 I", "900")
        hv = (await card_row(s1, h))["draft_version_id"]
        iv = (await card_row(s1, i))["draft_version_id"]
        arrived = asyncio.Event()
        waiting = []

        async def barrier():
            waiting.append(1)
            if len(waiting) == 2:
                arrived.set()
            await asyncio.wait_for(arrived.wait(), 5)

        between.extend([barrier, barrier])
        count = await snapshot_count(s1)
        results = await asyncio.gather(publish(s1, [change(h, hv)], "w-race-h"),
                                       publish(s1, [change(i, iv)], "w-race-i"))
        statuses = sorted(r.status for r in results)
        versions = await snapshot_versions(s1, (await publication(s1))["current_snapshot_id"])
        check("race after both prepared one publishes and other is STALE",
              statuses == ["PUBLISHED", "STALE"] and await snapshot_count(s1) == count + 1
              and not between)
        winner, loser = ((h, hv), (i, iv)) if results[0].status == "PUBLISHED" else ((i, iv), (h, hv))
        check("race STALE loser leaves no trace",
              winner[0] in versions and loser[0] not in versions
              and (await card_row(s1, loser[0]))["published_version_id"] is None
              and not await admin.fetchval(
                  "select exists(select 1 from operations where store_id=$1 and idempotency_key=$2)",
                  s1["sid"], f"w-race-{'h' if loser[0] == h else 'i'}"))
        retry = await publish(s1, [change(*loser)], "w-race-retry-2")
        versions = await snapshot_versions(s1, retry.snapshot_id)
        check("race STALE loser retry keeps winner", retry.status == "PUBLISHED"
              and versions.get(h) == hv and versions.get(i) == iv and f in versions and g in versions)

        # -- 레거시 공개 경로·낡은 카드 자기 회복 (final fix #2·#3) ------------
        # 옛 R 경로가 남긴 낡은 공개 카드(사실 블록 없음)를 만든다 — 옛 함수는 지웠다(Phase A).
        # publish_cards 없이 공개 포인터만 옮긴 상태를 직접 재현한다
        legacy_card = await blockless(s1, "합성 레거시 카드")
        legacy_v = (await card_row(s1, legacy_card))["draft_version_id"]
        await admin.execute(
            "update knowledge_cards set published_version_id=$3 where store_id=$1 and card_id=$2",
            s1["sid"], legacy_card, legacy_v)
        check("legacy pointer-only card stays outside publish_cards snapshot",
              (await card_row(s1, legacy_card))["published_version_id"] == legacy_v
              and str(legacy_card) not in {x.card_id for x in (await current_index(s1)).cards})

        # 사실 블록 없는 레거시 공개 카드는 다른 승인을 막지 않고, 다음 공개에도 실리지 않는다
        j = await seed_card(s1, "합성 카드 J", "1000")
        mutation = await card_router.approve_card(j, ShortSession(pool), claims)
        snap = await current_index(s1)
        ids = {x.card_id for x in snap.cards}
        check("bad unchanged legacy cards do not block another approval",
              mutation.review_status == "APPROVED" and str(j) in ids
              and str(legacy_card) not in ids and str(a) in ids and str(e) in ids)
        k = await seed_card(s1, "합성 카드 K", "1100")
        await card_router.approve_card(k, ShortSession(pool), claims)
        snap = await current_index(s1)
        check("legacy blockless card stays out of the next publish",
              (await card_row(s1, legacy_card))["published_version_id"] == legacy_v
              and snap.card(str(legacy_card)) is None
              and str(k) in {x.card_id for x in snap.cards})

        # -- 매장 격리 ---------------------------------------------------------
        async with pool.acquire() as conn:
            manifest = await current_manifest(conn, store_id=s1["sid"])
        snap = await current_index(s1)
        leaked = await admin.fetchval(
            "select count(*) from snapshot_card_versions where store_id=$1 and card_id=$2", s1["sid"], other)
        check("isolation other store card never in store 1",
              other not in manifest and str(other) not in {x.card_id for x in snap.cards} and leaked == 0)
        other_snap = await current_index(s2)
        check("isolation other store snapshot unchanged",
              {x.card_id for x in other_snap.cards} == {str(other)} and other_snap.knowledge_revision == "1")

    # -- 12. 승인 → 검색 → 점주 답변 (사실 경로) ---------------------------------
    # 관계 분석(knowledge_loop)은 없어졌다(Phase A). 점주 답변은 OWNER_TEXT 자료 → 사실 →
    # 사실 카드로 간다. 추출만 합성 대역이고 원장·조립(mock)·공개·R 검색은 실제 코드다
    with ExitStack() as stack:
        stack.enter_context(patch("app.reg.index_preparation.recorded_embeddings", fake_embedder))
        stack.enter_context(patch.object(card_router, "get_pool", lambda: pool))

        s3 = await seed_store("W 종단")
        claims3 = dict(role="OWNER", user_id=s3["uid"], store_id=s3["sid"])

        async def owner_event3(key, text):
            qid = await admin.fetchval(
                """insert into pending_questions(store_id,member_id,question_text,contract_version,semantic_key)
                values($1,$2,$3,'v2',$4) returning question_id""",
                s3["sid"], s3["mid"], f"{key} 질문", f"synthetic-e2e-{key}")
            reply = await submit_owner_answer(pool, store_id=s3["sid"], member_id=s3["mid"],
                                              question_id=qid, request_id=f"w-e2e-{key}",
                                              answer=text, expected_revision=0)
            return int(reply["owner_answer_id"])

        async def process3(*assertions):
            settings = _mock_settings()
            with patch("app.ingest.extract.extract_facts", _extracting(*assertions)), \
                    patch.object(extract, "get_settings", lambda: settings):
                return await process_next_owner_event(pool, store_id=s3["sid"])

        # 승인 카드가 없는 매장: worker 가 첫 답변을 처리할 수 있다
        pending_first = await owner_event3("before-index", "음료Q 얼음 80g")
        async with pool.acquire() as conn:
            before = await index_status(conn, store_id=s3["sid"])
        check("12 store without approved cards is EMPTY", before.status == "EMPTY")
        warned = {}
        check("12 worker accepts empty store without active index",
              await owner_answer_worker._index_ready(pool, store_id=s3["sid"], warned=warned)
              and warned == {}
              and await admin.fetchval(
                  "select count(*) from outbox_consumptions where store_id=$1", s3["sid"]) == 0)
        first_status = await process3(assertion("f1", "음료Q", "얼음", "80", unit="g"))
        check("12 first owner answer is processed before any approved card",
              first_status in ("REVIEW", "PUBLISHED"))

        # 승인 → 검색
        e2e = await seed_card(s3, "합성 종단 카드", "70")
        mutation = await card_router.approve_card(e2e, ShortSession(pool), claims3)
        async with pool.acquire() as conn:
            after = await index_status(conn, store_id=s3["sid"])
        found = await hybrid_search(pool, store_id=s3["sid"], question="종단 카드", query_vector=VECTOR)
        check("12 approve route publishes and index becomes READY",
              mutation.review_status == "APPROVED" and after.status == READY)
        check("12 approved card is found by R search",
              str(e2e) in {c.card_id for c in found.candidates})

        check("12 worker now proceeds for READY store",
              await owner_answer_worker._index_ready(pool, store_id=s3["sid"], warned=warned)
              and warned == {})
        status = await process_next_owner_event(pool, store_id=s3["sid"])
        check("12 first owner answer is not consumed twice after approval",
              status is None
              and await admin.fetchval(
                  "select count(*) from knowledge_change_proposals where store_id=$1 and answer_id=$2",
                  s3["sid"], pending_first) == 1)
        # 공개 카드와 같은 사실 → LINKED(공개판 불변)
        published_before = (await card_row(s3, e2e))["published_version_id"]
        same = await owner_event3("same", "합성 종단 카드 물 70ml")
        status = await process3(assertion("f1", "합성 종단 카드", "물", "70", unit="ml"))
        check("12 identical owner fact links the published card",
              status == "LINKED"
              and await admin.fetchval("select card_id from owner_answers where answer_id=$1", same) == e2e
              and (await card_row(s3, e2e))["published_version_id"] == published_before)
        # 공개 카드 대상의 새 사실 → 그 카드 검수
        differ = await owner_event3("differ", "합성 종단 카드 시럽 10ml")
        status = await process3(assertion("f1", "합성 종단 카드", "시럽", "10", unit="ml"))
        proposal = await admin.fetchrow(
            "select relation_type,status,target_card_id from knowledge_change_proposals "
            "where store_id=$1 and answer_id=$2", s3["sid"], differ)
        check("12 new owner fact for published card goes to review against that card",
              status == "REVIEW" and proposal["status"] == "PENDING_REVIEW"
              and proposal["target_card_id"] == e2e
              and (await card_row(s3, e2e))["published_version_id"] == published_before)
        check("12 still no legacy card_embeddings",
              await admin.fetchval("select count(*) from card_embeddings where store_id=$1", s3["sid"]) == 0)

        # -- 13. 초기 색인 준비(bootstrap) --------------------------------------
        # 옛 색인 시절 승인만 된 매장(공개판·색인 없음)을 흉내 낸다
        s4 = await seed_store("W 준비")
        legacy_ok = await seed_card(s4, "합성 옛 승인 카드", "60")
        no_source = await blockless(s4, "합성 출처 없는 카드")
        # 옛 승인 흉내 — 레거시 트리거가 없으므로 공개 포인터를 직접 초안 판으로 둔다
        await admin.execute(
            "update knowledge_cards set is_verified=true, review_status='APPROVED', "
            "published_version_id=draft_version_id "
            "where store_id=$1 and card_id = any($2::bigint[])",
            s4["sid"], [legacy_ok, no_source])
        async with pool.acquire() as conn:
            missing = await index_status(conn, store_id=s4["sid"])
        check("13 approved store without publication is MISSING",
              missing.status == "MISSING" and missing.approved_cards == 2)
        try:
            await hybrid_search(pool, store_id=s4["sid"], question="옛 승인", query_vector=VECTOR)
        except ApiError as exc:
            unavailable = exc.code == "INDEX_UNAVAILABLE"
        else:
            unavailable = False
        check("13 R search is unavailable before bootstrap", unavailable)
        status4, result4 = await bootstrap_store_index(pool, store_id=s4["sid"])
        async with pool.acquire() as conn:
            ready = await index_status(conn, store_id=s4["sid"])
        ids4 = {x.card_id for x in (await current_index(s4)).cards}
        check("13 bootstrap publishes current approved cards",
              status4.status == "MISSING" and result4.status == "PUBLISHED" and ready.status == READY
              and str(legacy_ok) in ids4 and str(no_source) not in ids4)
        found4 = await hybrid_search(pool, store_id=s4["sid"], question="옛 승인", query_vector=VECTOR)
        check("13 R search works after bootstrap",
              str(legacy_ok) in {c.card_id for c in found4.candidates})
        again4, noop4 = await bootstrap_store_index(pool, store_id=s4["sid"])
        check("13 bootstrap on READY store is a no-op",
              again4.status == READY and noop4 is None
              and await snapshot_count(s4) == 1)
        check("13 bootstrap left other stores untouched",
              {x.card_id for x in (await current_index(s2)).cards} == {str(other)})

        # 데모 시드 재실행: 비용 기록(색인 준비의 임베딩)이 있는 매장은 지울 수 없다(비용 원장은 영구).
        # 지우지 않고 보관 처리해 같은 slug·이메일·초대코드로 새 매장을 만들 수 있어야 한다
        from demo_seed import archive_demo_store
        slug, email = "synthetic-demo", "synthetic-demo-owner@example.invalid"
        await admin.execute("update stores set store_slug=$2 where store_id=$1", s4["sid"], slug)
        await admin.execute("update users set email=$2 where user_id=$1", s4["uid"], email)
        await admin.execute(
            "insert into invite_codes(store_id,code,expires_at) values($1,'SYN-DEMO',now()+interval '1 day')",
            s4["sid"])
        usage_before = await admin.fetchval("select count(*) from ai_usage_attempts where store_id=$1", s4["sid"])
        async with admin.transaction():
            archived = await archive_demo_store(admin, slug, [email])
            new_uid = await admin.fetchval(
                "insert into users(name,role,email) values('합성 새 데모 점주','OWNER',$1) returning user_id", email)
            new_sid = await admin.fetchval(
                "insert into stores(owner_id,store_slug,store_name,business_type) values($1,$2,'합성 새 데모','CAFE') returning store_id",
                new_uid, slug)
            await admin.execute(
                "insert into invite_codes(store_id,code,expires_at) values($1,'SYN-DEMO',now()+interval '1 day')", new_sid)
        check("13 demo reseed archives old store instead of deleting it",
              archived == s4["sid"] and usage_before > 0
              and await admin.fetchval("select count(*) from ai_usage_attempts where store_id=$1", s4["sid"]) == usage_before
              and await admin.fetchval("select store_slug from stores where store_id=$1", s4["sid"]) != slug
              and await admin.fetchval("select store_id from stores where store_slug=$1", slug) == new_sid)

        # -- 14. 자료 삭제(D20) — tombstone, 원본 접근 해제, 카드·공개판 보존 ------------
        src3 = await admin.fetchval(
            "select source_id from knowledge_cards where store_id=$1 and card_id=$2", s3["sid"], e2e)
        pub_before = await publication(s3)
        try:
            await ingest_router.delete_ingest_source(
                src3, ShortSession(pool), dict(role="OWNER", user_id=s2["uid"], store_id=s2["sid"]))
        except ApiError as exc:
            cross = exc.status_code == 404
        else:
            cross = False
        check("14 other store cannot delete the source", cross
              and await admin.fetchval(
                  "select source_availability from sources where source_id=$1", src3) == "AVAILABLE")
        # 실제 처리 작업이 대기 중이면 삭제를 거절한다(자료 등록 호환 작업은 제외)
        real_job = await admin.fetchval(
            """insert into ingest_jobs(store_id,created_by,title,status,category_version,prompt_version)
            values($1,$2,'합성 처리 작업','EXTRACTING',1,'extract-cards-v1') returning job_id""",
            s3["sid"], s3["uid"])
        await admin.execute(
            "insert into ingest_job_sources(store_id,job_id,source_id,status) values($1,$2,$3,'EXTRACTING')",
            s3["sid"], real_job, src3)
        try:
            await ingest_router.delete_ingest_source(src3, ShortSession(pool), claims3)
        except ApiError as exc:
            busy = exc.code == "SOURCE_IN_PROGRESS"
        else:
            busy = False
        check("14 source being processed cannot be deleted", busy)
        await admin.execute(
            "update ingest_job_sources set status='SUCCEEDED' where store_id=$1 and job_id=$2",
            s3["sid"], real_job)
        removed = await ingest_router.delete_ingest_source(src3, ShortSession(pool), claims3)
        row3 = await admin.fetchrow(
            "select source_availability,deleted_at from sources where store_id=$1 and source_id=$2",
            s3["sid"], src3)
        check("14 delete leaves a tombstone",
              removed.source_availability == "DELETED" and not removed.already_deleted
              and row3["source_availability"] == "DELETED" and row3["deleted_at"] is not None)
        again3 = await ingest_router.delete_ingest_source(src3, ShortSession(pool), claims3)
        check("14 repeat delete is idempotent", again3.already_deleted)
        card3 = await card_row(s3, e2e)
        found3 = await hybrid_search(pool, store_id=s3["sid"], question="종단 카드", query_vector=VECTOR)
        check("14 approved card, publication and R index are untouched",
              card3["review_status"] == "APPROVED" and card3["published_version_id"] is not None
              and await publication(s3) == pub_before
              and str(e2e) in {c.card_id for c in found3.candidates})
        async with pool.acquire() as conn:
            card_src = await card_repo.get_card(conn, s3["sid"], e2e)
        check("14 card source reports DELETED availability",
              card_src["source_availability"] == "DELETED")
        try:
            await ingest_router.create_ingest_job(
                CreateIngestJobRequest(source_ids=[src3]), BackgroundTasks(),
                ShortSession(pool), claims3, None)
        except ApiError as exc:
            rejected = exc.code == "SOURCE_DELETED"
        else:
            rejected = False
        check("14 deleted source cannot start a new job", rejected)

    print(f"Verified {len(passed)} W publish checks")

    # W3a 대상 단위 사실 조립 — 기존 시나리오·패치 밖에서 새 매장으로 돈다
    from verify_w3a_fact_assembly import verify as verify_w3a
    await verify_w3a(pool, admin)

    # W3b 점주 사실 카드 편집 — W3a 뒤 새 매장으로 돈다
    from verify_w3b_card_fact_edit import verify as verify_w3b
    await verify_w3b(pool, admin)
