"""격리 실제 DB: 합성 카드 2장으로 W 공개 경로 전체를 통과시킨다 (Task 7).

verify_r_schema_rebuild 가 만든 새 UUID DB(모든 migration 적용)의 연결만 받는다.
외부 호출은 전부 합성이다 — R 색인 준비의 임베딩, 옛 색인 호환 임베딩, 점주 답변
관계 분석(build_knowledge_plan)을 고정 대역으로 바꾼다. 실제 SQL·트리거·잠금·
savepoint·R 읽기 쪽 hash/manifest 검사는 그대로 돈다.
"""
import asyncio
from contextlib import ExitStack, contextmanager
from unittest.mock import patch

from app.cards import repository as card_repo
from app.cards import router as card_router
from app.cards.owner_answer_worker import process_next_owner_event
from app.config import get_settings
from app.contracts.usage import UsageContext
from app.db_session import ShortSession
from app.errors import ApiError
from app.ingest.embed.service import PreparedEmbedding
from app.learn import knowledge_apply
from app.learn.knowledge_apply import approve_owner_proposal, publish_new_proposal
from app.learn.knowledge_loop import KnowledgePlan
from app.learn.owner_delivery import submit_owner_answer
from app.learn.owner_handoff import finish_owner_review
from app.publish import approval
from app.publish.approval import CardChange, publish_cards
from app.publish.content import current_manifest
from app.reg.hybrid import hybrid_search, read_current_index

# 합성 벡터. 0 이 아닌 1536 차원이면 R 준비 검사를 통과한다
VECTOR = [1.0] + [0.0] * 1535


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

    async def fake_prepare_embedding(store_id, title, content, **kwargs):
        text = f"{title}\n{content}".strip()
        settings = get_settings()
        return PreparedEmbedding(store_id, text, list(VECTOR), settings.embedding_model,
                                 settings.embedding_dim)

    @contextmanager
    def owner_answer_publish(on: bool):
        # 설정 객체는 lru_cache 하나이므로 속성을 바꾸면 모든 모듈이 같은 값을 본다
        with patch.object(get_settings(), "w_owner_answer_raw_publish", on):
            yield

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

    async def seed_card(store, title, content, *, with_source=True):
        source_id = None
        if with_source:
            source_id = await admin.fetchval(
                "insert into sources(store_id,uploaded_by,source_type,status,title) values($1,$2,'KAKAO','DONE',$3) returning source_id",
                store["sid"], store["uid"], f"{title} 자료")
            # 승인 라우트의 비용 귀속(card_usage_context)이 이어받을 원본 작업 기록
            await admin.execute(
                """insert into ai_usage_attempts(store_id,cost_phase,stage,logical_call_id,requested_model,source_id)
                values($1,'REGISTRATION','EXTRACT',$2,'synthetic-extract',$3)""",
                store["sid"], f"synthetic-extract:{source_id}", source_id)
        card_id = await admin.fetchval(
            "insert into knowledge_cards(store_id,category_id,source_id,title,content,confidence) values($1,$2,$3,$4,$5,90) returning card_id",
            store["sid"], store["category"], source_id, title, content)
        return card_id

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

    async def edit(store, card_id, title, content):
        async with pool.acquire() as conn:
            async with conn.transaction():
                draft = await conn.fetchval(
                    "select draft_version_id from knowledge_cards where store_id=$1 and card_id=$2 for update",
                    store["sid"], card_id)
                return await card_repo.create_draft(
                    conn, store["sid"], card_id, title=title, content=content,
                    actor_id=store["uid"], source_version_id=draft)

    with ExitStack() as stack:
        stack.enter_context(patch("app.reg.index_preparation.recorded_embeddings", fake_embedder))
        stack.enter_context(patch.object(card_router, "prepare_embedding", fake_prepare_embedding))
        stack.enter_context(patch.object(knowledge_apply, "prepare_embedding", fake_prepare_embedding))
        stack.enter_context(patch.object(card_router, "get_pool", lambda: pool))

        s1 = await seed_store("W 공개")
        s2 = await seed_store("W 다른")

        # 다른 매장 카드를 먼저 공개해 둔다. 매장 1의 어떤 판에도 섞이면 안 된다
        other = await seed_card(s2, "다른 매장 카드", "다른 매장 원문")
        other_v = (await card_row(s2, other))["draft_version_id"]
        result = await publish(s2, [change(other, other_v)], "w-other-first")
        check("other store publishes independently", result.status == "PUBLISHED")

        # -- 1. 첫 승인 --------------------------------------------------------
        a = await seed_card(s1, "합성 카드 A", "A 첫 원문\n\n둘째 문단")
        b = await seed_card(s1, "합성 카드 B", "B 첫 원문")
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
        check("1 short card fixed as one source-cited RAW block",
              [blk.block_id for blk in snap.card(str(a)).blocks] == ["raw1"]
              and all(r.source_id is not None and r.owner_answer_id is None for r in snap.raw_spans))
        first_snapshot = result.snapshot_id

        # -- 2. A만 수정·재승인 -------------------------------------------------
        a2 = await edit(s1, a, "합성 카드 A", "A 둘째 원문")
        calls_before_edit = len(embed_calls)
        result = await publish(s1, [change(a, a2)], "w-a-second")
        check("2 only changed A is embedded while B vector is reused",
              len(embed_calls) == calls_before_edit+1
              and embed_inputs[-1] == ['합성 카드 A\nA 둘째 원문'])
        versions = await snapshot_versions(s1, result.snapshot_id)
        check("2 re-approval moves only A",
              result.status == "PUBLISHED" and versions == {a: a2, b: b1}
              and result.knowledge_revision == 2
              and (await card_row(s1, a))["published_version_id"] == a2)
        check("2 old snapshot keeps A's old version",
              (await snapshot_versions(s1, first_snapshot))[a] == a1)
        snap = await current_index(s1)
        check("2 R index serves new A text",
              next(r.text for r in snap.raw_spans
                   if r.raw_span_id == snap.card(str(a)).blocks[0].raw_span_id) == "A 둘째 원문")

        # -- 3. 준비 뒤 초안이 또 바뀐다 → STALE ---------------------------------
        a3 = await edit(s1, a, "합성 카드 A", "A 셋째 원문")
        before_pub, before_count = await publication(s1), await snapshot_count(s1)
        injected = {}

        async def concurrent_edit():
            injected["version"] = await edit(s1, a, "합성 카드 A", "A 넷째 원문")

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

        # -- 7. 출처 없는 카드 ---------------------------------------------------
        c = await seed_card(s1, "합성 카드 C", "C 점주 답변 원문", with_source=False)
        c1 = (await card_row(s1, c))["draft_version_id"]
        count = await snapshot_count(s1)
        result = await publish(s1, [change(c, c1)], "w-c-noprov")
        check("7 no provenance with flag OFF",
              result.status == "NO_PROVENANCE" and await snapshot_count(s1) == count
              and (await card_row(s1, c))["published_version_id"] is None
              and not await admin.fetchval(
                  "select exists(select 1 from card_version_blocks where store_id=$1 and card_version_id=$2)",
                  s1["sid"], c1))
        question = await admin.fetchval(
            """insert into pending_questions(store_id,member_id,question_text,contract_version,semantic_key)
            values($1,$2,'C 는 어떻게 하나요','v2','synthetic-c') returning question_id""", s1["sid"], s1["mid"])
        answer_c = await admin.fetchval(
            "insert into owner_answers(question_id,answered_by,answer_text,card_id) values($1,$2,'C 점주 답변 원문',$3) returning answer_id",
            question, s1["uid"], c)
        with owner_answer_publish(True):
            result = await publish(s1, [change(c, c1)], "w-c-owner")
        spans = await admin.fetch(
            """select r.source_id,r.owner_answer_id from card_version_blocks b
            join raw_spans r on r.store_id=b.store_id and r.raw_span_id=b.raw_span_id
            where b.store_id=$1 and b.card_version_id=$2""", s1["sid"], c1)
        check("7 flag ON publishes owner answer card",
              result.status == "PUBLISHED"
              and await snapshot_versions(s1, result.snapshot_id) == {b: b1, c: c1})
        check("7 raw span cites owner answer",
              len(spans) == 1 and spans[0]["source_id"] is None and spans[0]["owner_answer_id"] == answer_c)
        snap = await current_index(s1)
        check("7 R snapshot carries owner answer span",
              any(r.owner_answer_id == str(answer_c) for r in snap.raw_spans)
              and {x.card_id for x in snap.cards} == {str(b), str(c)})

        # -- 8. 다른 매장 답변으로 raw_span → 트리거 ------------------------------
        q2 = await admin.fetchval(
            """insert into pending_questions(store_id,member_id,question_text,contract_version,semantic_key)
            values($1,$2,'다른 매장 질문','v2','synthetic-other') returning question_id""", s2["sid"], s2["mid"])
        answer_other = await admin.fetchval(
            "insert into owner_answers(question_id,answered_by,answer_text) values($1,$2,'다른 매장 답') returning answer_id",
            q2, s2["uid"])
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

        # -- 9. 점주 답변 worker -------------------------------------------------
        plans = []

        async def fake_plan(conn, store_id, question_text, answer_text, **kwargs):
            return plans.pop(0)

        async def owner_event(key, text):
            qid = await admin.fetchval(
                """insert into pending_questions(store_id,member_id,question_text,contract_version,semantic_key)
                values($1,$2,$3,'v2',$4) returning question_id""",
                s1["sid"], s1["mid"], f"{key} 질문", f"synthetic-{key}")
            reply = await submit_owner_answer(pool, store_id=s1["sid"], member_id=s1["mid"],
                                              question_id=qid, request_id=f"w-publish-{key}",
                                              answer=text, expected_revision=0)
            return int(reply["owner_answer_id"])

        def plan(relation, target=None, target_version=None, title="", content="", auto=False):
            return KnowledgePlan(relation_type=relation, target_card_id=target,
                                 target_version_id=target_version, category_id=s1["category"],
                                 category_name="기타", proposed_title=title, proposed_content=content,
                                 reason="합성 관계", auto_publish=auto)

        async def knowledge_state(answer_id):
            return await admin.fetchrow(
                "select status,result from r_owner_knowledge_states where store_id=$1 and owner_answer_id=$2",
                s1["sid"], answer_id)

        stack.enter_context(patch("app.cards.owner_answer_worker.build_knowledge_plan", fake_plan))
        revision = (await publication(s1))["knowledge_revision"]

        identical = await owner_event("identical", "B 첫 원문")
        plans.append(plan("IDENTICAL", b, b1, "합성 카드 B", "B 첫 원문"))
        status = await process_next_owner_event(pool, store_id=s1["sid"])
        state = await knowledge_state(identical)
        check("9 IDENTICAL links published card",
              status == "LINKED" and state["status"] == "LINKED"
              and (await publication(s1))["knowledge_revision"] == revision
              and await admin.fetchval("select card_id from owner_answers where answer_id=$1", identical) == b)

        new = await owner_event("new", "새 답변 원문")
        plans.append(plan("NEW", title="합성 새 카드", content="새 답변 원문", auto=True))
        with owner_answer_publish(True):
            status = await process_next_owner_event(pool, store_id=s1["sid"])
        new_card = await admin.fetchval("select card_id from owner_answers where answer_id=$1", new)
        pub = await publication(s1)
        versions = await snapshot_versions(s1, pub["current_snapshot_id"])
        state = await knowledge_state(new)
        check("9 NEW publishes new card into snapshot",
              status == "PUBLISHED" and new_card in versions
              and pub["knowledge_revision"] == revision + 1
              and state["status"] == "PUBLISHED"
              and await admin.fetchval(
                  "select status from knowledge_change_proposals where store_id=$1 and answer_id=$2",
                  s1["sid"], new) == "PUBLISHED")
        check("9 NEW card served by R index",
              str(new_card) in {x.card_id for x in (await current_index(s1)).cards})

        supplement = await owner_event("supplement", "B 보완 원문")
        plans.append(plan("SUPPLEMENT", b, b1, "합성 카드 B", "B 첫 원문\n\nB 보완 원문"))
        status = await process_next_owner_event(pool, store_id=s1["sid"])
        proposal = await admin.fetchrow(
            "select proposal_id,status from knowledge_change_proposals where store_id=$1 and answer_id=$2",
            s1["sid"], supplement)
        check("9 SUPPLEMENT goes to review without publishing",
              status == "REVIEW" and proposal["status"] == "PENDING_REVIEW"
              and (await knowledge_state(supplement))["status"] == "REVIEW"
              and (await publication(s1))["knowledge_revision"] == revision + 1
              and (await card_row(s1, b))["published_version_id"] == b1)

        # 자동 공개 가능 NEW 라도 플래그가 꺼져 있으면 초안만 남기고 검수로 넘긴다
        review_new = await owner_event("new-review", "검수 대기 새 답변")
        plans.append(plan("NEW", title="합성 검수 카드", content="검수 대기 새 답변", auto=True))
        status = await process_next_owner_event(pool, store_id=s1["sid"])
        review_card = await admin.fetchval("select card_id from owner_answers where answer_id=$1", review_new)
        review_proposal = await admin.fetchrow(
            "select proposal_id,status from knowledge_change_proposals where store_id=$1 and answer_id=$2",
            s1["sid"], review_new)
        check("9 NEW with flag OFF becomes REVIEW with unpublished draft",
              status == "REVIEW" and review_proposal["status"] == "PENDING_REVIEW"
              and (await knowledge_state(review_new))["status"] == "REVIEW"
              and review_card is not None
              and (await card_row(s1, review_card))["published_version_id"] is None
              and (await publication(s1))["knowledge_revision"] == revision + 1)
        check("9 no event left", await process_next_owner_event(pool, store_id=s1["sid"]) is None)

        # -- 10. 나중 승인(SUPPLEMENT) ----------------------------------------
        notified = []

        async def notify_r(conn, answer_id, card_id, version_id, knowledge_revision):
            pid = await conn.fetchval('''select proposal_id from knowledge_change_proposals
                where store_id=$1 and answer_id=$2''', s1['sid'], answer_id)
            await finish_owner_review(conn, store_id=s1['sid'], proposal_id=pid,
                owner_answer_id=answer_id, card_id=card_id, card_version_id=version_id,
                knowledge_revision=knowledge_revision)
            notified.append((conn.is_in_transaction(), answer_id, card_id, version_id, knowledge_revision))

        async def approve():
            return await approve_owner_proposal(
                pool, store_id=s1["sid"], member_id=s1["mid"], actor_user_id=s1["uid"],
                proposal_id=proposal["proposal_id"], usage_context=usage(s1, "proposal"),
                notify_r=notify_r)

        before_b = dict(await card_row(s1, b))
        before_pub = dict(await publication(s1))
        result = await approve()
        check("10 flag OFF proposal approval is NO_PROVENANCE",
              result.status == "NO_PROVENANCE" and not notified)
        check("10 flag OFF leaves card and proposal unchanged",
              dict(await card_row(s1, b)) == before_b and dict(await publication(s1)) == before_pub
              and await admin.fetchval(
                  "select status from knowledge_change_proposals where store_id=$1 and proposal_id=$2",
                  s1["sid"], proposal["proposal_id"]) == "PENDING_REVIEW")
        # 실제 W 공개 hook의 R 알림 실패가 카드·snapshot·제안까지 되돌리는지 확인한다.
        count_before = await snapshot_count(s1)
        try:
            with owner_answer_publish(True), patch('app.learn.owner_handoff.notify_publication',
                    side_effect=RuntimeError('synthetic review notification failure')):
                await approve()
        except RuntimeError:
            pass
        else:
            raise AssertionError('R review failure did not abort W publication')
        check("10 R completion failure rolls back W publication and review",
              dict(await publication(s1)) == before_pub
              and await snapshot_count(s1) == count_before
              and (await card_row(s1, b))['published_version_id'] == b1
              and (await knowledge_state(supplement))['status'] == 'REVIEW'
              and await admin.fetchval('''select status from knowledge_change_proposals
                  where store_id=$1 and proposal_id=$2''', s1['sid'], proposal['proposal_id']) == 'PENDING_REVIEW')
        with owner_answer_publish(True):
            result = await approve()
        b2 = (await card_row(s1, b))["published_version_id"]
        spans = await admin.fetch(
            """select r.source_id,r.owner_answer_id from card_version_blocks k
            join raw_spans r on r.store_id=k.store_id and r.raw_span_id=k.raw_span_id
            where k.store_id=$1 and k.card_version_id=$2""", s1["sid"], b2)
        check("10 flag ON proposal publishes new B version",
              result.status == "PUBLISHED" and b2 != b1
              and (await snapshot_versions(s1, result.snapshot_id))[b] == b2)
        check("10 new B version cites owner answer, not source",
              spans and all(r["source_id"] is None and r["owner_answer_id"] == supplement for r in spans))
        check("10 notify_r ran inside publication transaction",
              notified == [(True, supplement, b, b2, result.knowledge_revision)])
        check("10 proposal closed as PUBLISHED",
              await admin.fetchval(
                  "select status from knowledge_change_proposals where store_id=$1 and proposal_id=$2",
                  s1["sid"], proposal["proposal_id"]) == "PUBLISHED")
        with owner_answer_publish(True):
            result = await approve()
        check("10 replay is ALREADY_APPLIED", result.status == "ALREADY_APPLIED" and len(notified) == 1)

        # 검수 대기 NEW 제안: worker 가 만든 초안 카드를 재사용해 공개한다
        cards_before = await admin.fetchval("select count(*) from knowledge_cards where store_id=$1", s1["sid"])
        with owner_answer_publish(True):
            result = await approve_owner_proposal(
                pool, store_id=s1["sid"], member_id=s1["mid"], actor_user_id=s1["uid"],
                proposal_id=review_proposal["proposal_id"], usage_context=usage(s1, "proposal-new"),
                notify_r=notify_r)
        review_row = await card_row(s1, review_card)
        check("10 later approval of NEW reuses worker draft card",
              result.status == "PUBLISHED"
              and await admin.fetchval("select count(*) from knowledge_cards where store_id=$1", s1["sid"]) == cards_before
              and review_row["published_version_id"] == review_row["draft_version_id"]
              and (await snapshot_versions(s1, result.snapshot_id)).get(review_card) == review_row["draft_version_id"]
              and notified[-1][:3] == (True, review_new, review_card))
        check("10 real R receiver completes both reviewed proposals",
              (await knowledge_state(supplement))['status'] == 'PUBLISHED'
              and (await knowledge_state(review_new))['status'] == 'PUBLISHED')
        from verify_r_owner_citations import verify as verify_owner_citations
        await verify_owner_citations(pool, admin, store=s1, card_id=review_card,
                                     owner_answer_id=review_new, other_answer_id=answer_other)

        # -- 11. HTTP 승인 라우트 ----------------------------------------------
        d = await seed_card(s1, "합성 카드 D", "D 원문")
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
        check("11 approve route fills legacy card_embeddings",
              await admin.fetchval(
                  "select count(*) from card_embeddings where store_id=$1 and card_id=$2", s1["sid"], d) == 1)
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
        e = await seed_card(s1, "합성 카드 E", "E 원문")
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

        # 비었거나 너무 긴 원문을 승인하면 409 CARD_CONTENT_INVALID, 아무것도 남기지 않는다
        empty_new = await seed_card(s1, "합성 빈 카드", "")
        count = await snapshot_count(s1)
        try:
            await card_router.approve_card(empty_new, ShortSession(pool), claims)
        except ApiError as exc:
            invalid = exc.status_code == 409 and exc.code == "CARD_CONTENT_INVALID"
        else:
            invalid = False
        check("empty card approval is 409 CARD_CONTENT_INVALID",
              invalid and await snapshot_count(s1) == count
              and (await card_row(s1, empty_new))["published_version_id"] is None
              and not await admin.fetchval(
                  "select exists(select 1 from card_version_blocks where store_id=$1 and card_version_id=$2)",
                  s1["sid"], (await card_row(s1, empty_new))["draft_version_id"]))

        # -- 동시 공개: 둘 다 성공했다면 나중 판이 앞 판의 카드를 잃지 않는다 --
        f = await seed_card(s1, "합성 카드 F", "F 원문")
        g = await seed_card(s1, "합성 카드 G", "G 원문")
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
        h = await seed_card(s1, "합성 카드 H", "H 원문")
        i = await seed_card(s1, "합성 카드 I", "I 원문")
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
        # 레거시 R 경로(publish_new_proposal)는 publish_cards 없이 공개 포인터만 옮긴다
        legacy_q = await admin.fetchval(
            """insert into pending_questions(store_id,member_id,question_text,contract_version,semantic_key)
            values($1,$2,'레거시 질문','v2','synthetic-legacy') returning question_id""", s1["sid"], s1["mid"])
        legacy_answer = await admin.fetchval(
            "insert into owner_answers(question_id,answered_by,answer_text) values($1,$2,'레거시 답변 원문') returning answer_id",
            legacy_q, s1["uid"])
        legacy_proposal = await admin.fetchval(
            """insert into knowledge_change_proposals(store_id,answer_id,relation_type,category_id,
                   proposed_title,proposed_content,status)
            values($1,$2,'NEW',$3,'합성 레거시 카드','레거시 답변 원문','PENDING_REVIEW') returning proposal_id""",
            s1["sid"], legacy_answer, s1["category"])
        expected = dict(await admin.fetchrow(
            "select * from knowledge_change_proposals where store_id=$1 and proposal_id=$2",
            s1["sid"], legacy_proposal))
        prepared = await fake_prepare_embedding(s1["sid"], "합성 레거시 카드", "레거시 답변 원문")
        async with pool.acquire() as conn:
            async with conn.transaction():
                legacy_card, legacy_v = await publish_new_proposal(
                    conn, s1["sid"], legacy_proposal, s1["uid"], preparation=(expected, prepared))
        check("legacy publish_new_proposal moves pointer outside publish_cards",
              (await card_row(s1, legacy_card))["published_version_id"] == legacy_v
              and str(legacy_card) not in {x.card_id for x in (await current_index(s1)).cards})

        # 빈 원문으로 레거시 승인된 카드(ingest 즉시 승인 흉내)는 다른 승인을 막지 않는다
        empty_legacy = await seed_card(s1, "합성 빈 레거시 카드", "")
        await admin.execute("update knowledge_cards set is_verified=true where store_id=$1 and card_id=$2",
                            s1["sid"], empty_legacy)
        check("empty legacy card is approved with a pointer",
              (await card_row(s1, empty_legacy))["published_version_id"] is not None)

        # 플래그 OFF: 점주 답변 출처 레거시 카드는 빠지고, 빈 카드도 빠지고, 승인은 성공한다
        j = await seed_card(s1, "합성 카드 J", "J 원문")
        mutation = await card_router.approve_card(j, ShortSession(pool), claims)
        snap = await current_index(s1)
        ids = {x.card_id for x in snap.cards}
        check("bad unchanged legacy cards do not block another approval",
              mutation.review_status == "APPROVED" and str(j) in ids
              and str(empty_legacy) not in ids and str(legacy_card) not in ids
              and str(a) in ids and str(e) in ids)

        # 플래그 ON 으로 바꾸면 다음 공개가 현재 포인터로 manifest 를 만들어 레거시 카드를 싣는다
        k = await seed_card(s1, "합성 카드 K", "K 원문")
        with owner_answer_publish(True):
            await card_router.approve_card(k, ShortSession(pool), claims)
        snap = await current_index(s1)
        check("legacy-published card is included on the next publish",
              snap.card(str(legacy_card)) is not None
              and snap.card(str(legacy_card)).card_version_id == str(legacy_v)
              and str(k) in {x.card_id for x in snap.cards}
              and str(empty_legacy) not in {x.card_id for x in snap.cards})

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

    print(f"Verified {len(passed)} W publish checks")
