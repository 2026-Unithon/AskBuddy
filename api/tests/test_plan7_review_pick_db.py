"""계획 7 Task 6: 충돌에서 고르지 않은 값은 '틀린 값'으로 기억하고, 다시 충돌을 열거나 조립에 들어가지 않는다.

실제 스키마(일회용 DB). PLAN7_TEST_DB_URL 이 없으면 건너뛴다.
"""
import unittest

from tests._plan7_db import ENABLED, SKIP_REASON, drop_db, fresh_db, seed_store

from app.ingest import fact_assembly, fact_ledger, fact_revisions


async def fact(conn, store, entity, ident, slot, value):
    fact_id = await conn.fetchval(
        "insert into knowledge_facts (store_id, entity_id, identity_key, slot_key) values ($1, $2, $3, $4) returning fact_id",
        store, entity, ident, slot)
    rev = await conn.fetchval(
        "insert into fact_revisions (store_id, fact_id, entity_id, original_assertion, assertion, subject, value_text, polarity) "
        "values ($1, $2, $3, $4, $4, '합성 메뉴', $5, 'AFFIRM') returning fact_revision_id",
        store, fact_id, entity, f"토핑={value}", value)
    await conn.execute("update knowledge_facts set head_revision_id = $3 where store_id = $1 and fact_id = $2", store, fact_id, rev)
    return fact_id


@unittest.skipUnless(ENABLED, SKIP_REASON)
class ReviewPickTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.conn, self.name = await fresh_db()
        self.store = await seed_store(self.conn)
        self.entity = await self.conn.fetchval(
            "insert into knowledge_entities (store_id, canonical_name, name_norm) values ($1, '합성 메뉴', '합성메뉴') returning entity_id", self.store)
        self.a = await fact(self.conn, self.store, self.entity, "id-30g", "slot-topping", "휘핑 30g")
        self.b = await fact(self.conn, self.store, self.entity, "id-90g", "slot-topping", "휘핑 90g")
        await fact_ledger._record_conflicts(self.conn, self.store, self.b)
        self.conflict = await self.conn.fetchval(
            "select conflict_id from fact_conflicts where store_id = $1 and status = 'OPEN'", self.store)

    async def asyncTearDown(self):
        await drop_db(self.conn, self.name)

    async def test_choose_keeps_one_and_marks_other_rejected(self):
        rejected = await fact_revisions.choose_conflict(self.conn, self.store, self.conflict, keep_fact_id=self.a, actor_id=1)
        self.assertEqual(rejected, self.b)
        row = await self.conn.fetchrow("select status, resolution from fact_conflicts where conflict_id = $1", self.conflict)
        self.assertEqual(row["status"], "RESOLVED")
        self.assertTrue(await self.conn.fetchval(
            "select exists(select 1 from fact_rejections where store_id = $1 and fact_id = $2)", self.store, self.b))

    async def test_rejected_value_does_not_reopen(self):
        await fact_revisions.choose_conflict(self.conn, self.store, self.conflict, keep_fact_id=self.a, actor_id=1)
        # 같은 값을 다시 올린 것처럼 충돌 기록을 다시 돌린다
        self.assertEqual(await fact_ledger._record_conflicts(self.conn, self.store, self.b), 0)
        self.assertEqual(await fact_ledger._record_conflicts(self.conn, self.store, self.a), 0)

    async def test_rejected_value_is_left_out_of_assembly(self):
        await fact_revisions.choose_conflict(self.conn, self.store, self.conflict, keep_fact_id=self.a, actor_id=1)
        groups = await fact_assembly.load_entity_groups(self.conn, self.store, [self.entity])
        ids = {f.fact_id for g in groups.groups for f in g.facts}
        self.assertIn(self.a, ids)
        self.assertNotIn(self.b, ids)

    async def test_choose_rejects_fact_outside_pair_and_other_store(self):
        with self.assertRaises(ValueError):
            await fact_revisions.choose_conflict(self.conn, self.store, self.conflict, keep_fact_id=999999, actor_id=1)
        with self.assertRaises(LookupError):
            await fact_revisions.choose_conflict(self.conn, self.store + 999, self.conflict, keep_fact_id=self.a, actor_id=1)

    async def test_unit_variants_still_open_for_owner(self):
        # 0.5oz 와 15ml 처럼 단위만 다른 두 값도 서버가 묶지 않는다(사장님이 고른다)
        c = await fact(self.conn, self.store, self.entity, "id-oz", "slot-base", "0.5oz")
        d = await fact(self.conn, self.store, self.entity, "id-ml", "slot-base", "15ml")
        self.assertEqual(await fact_ledger._record_conflicts(self.conn, self.store, d), 1)


@unittest.skipUnless(ENABLED, SKIP_REASON)
class ReviewItemsDbTest(ReviewPickTest):
    async def test_load_review_items_for_card_facts(self):
        from app.cards.review_items import load_review_items
        items = await load_review_items(self.conn, self.store, [self.a])
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].label, "토핑")
        self.assertEqual([o.text for o in items[0].options], ["휘핑 30g", "휘핑 90g"])
        self.assertEqual(await load_review_items(self.conn, self.store + 999, [self.a]), [])


@unittest.skipUnless(ENABLED, SKIP_REASON)
class SameQuestionDbTest(ReviewPickTest):
    async def test_identical_text_pair_is_not_a_conflict(self):
        # 한 문장을 두 번 뽑아 글이 같다(띄어쓰기만 다름) → 묻지 않는다
        c = await fact(self.conn, self.store, self.entity, "id-c1", "slot-cube", "치즈 큐브 6e a")
        d = await fact(self.conn, self.store, self.entity, "id-c2", "slot-cube", "치즈큐브 6ea")
        self.assertEqual(await fact_ledger._record_conflicts(self.conn, self.store, d), 0)

    async def test_one_pick_settles_repeated_question(self):
        # 30g(a) · 90g(b) 에 같은 글 90g 사실이 하나 더(e). 두 충돌이 같은 질문이라 한 번 고르면 둘 다 끝
        e = await fact(self.conn, self.store, self.entity, "id-90g-2", "slot-topping", "휘핑 90g")
        await fact_ledger._record_conflicts(self.conn, self.store, e)
        from app.cards.review_items import load_review_items
        self.assertEqual(len(await load_review_items(self.conn, self.store, [self.a, self.b, e])), 1)
        await fact_revisions.choose_conflict(self.conn, self.store, self.conflict, keep_fact_id=self.a, actor_id=1)
        self.assertEqual(await load_review_items(self.conn, self.store, [self.a, self.b, e]), [])
        self.assertTrue(await self.conn.fetchval(
            "select exists(select 1 from fact_rejections where store_id = $1 and fact_id = $2)", self.store, e))


@unittest.skipUnless(ENABLED, SKIP_REASON)
class SameStatementMigrationTest(ReviewPickTest):
    async def test_migration_closes_stored_identical_conflicts(self):
        from pathlib import Path
        c = await fact(self.conn, self.store, self.entity, "id-s1", "slot-s", "요거트파우더 3래들")
        d = await fact(self.conn, self.store, self.entity, "id-s2", "slot-s", "요거 트파우더 3래들")
        low, high = sorted((c, d))
        same = await self.conn.fetchval(
            "insert into fact_conflicts (store_id, entity_id, slot_key, fact_id_low, fact_id_high, value_kind) "
            "values ($1, $2, 'slot-s', $3, $4, 'TEXT') returning conflict_id", self.store, self.entity, low, high)
        sql = (Path(__file__).resolve().parents[2] / "supabase/migrations/20261108120400_same_statement_conflicts.sql").read_text()
        await self.conn.execute(sql)
        status = {r["conflict_id"]: r["status"] for r in await self.conn.fetch("select conflict_id, status from fact_conflicts")}
        self.assertEqual(status[same], "OBSOLETE")
        self.assertEqual(status[self.conflict], "OPEN")  # 30g · 90g 는 진짜 다른 값
