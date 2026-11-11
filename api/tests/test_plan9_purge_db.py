"""계획 9C: 매장 파기. 실제 스키마. PLAN7_TEST_DB_URL 이 없으면 건너뛴다."""
import unittest

from tests._plan7_db import ENABLED, SKIP_REASON, drop_db, fresh_db, seed_store

GUARDED = ["evaluation_results", "evaluation_runs", "extraction_results", "extraction_runs", "fact_revision_meta",
           "fact_revisions", "knowledge_entity_events", "knowledge_snapshots", "owner_answers", "r_answer_citations",
           "r_answer_receipts", "r_index_documents", "r_owner_answer_deliveries", "r_owner_answer_revisions",
           "r_search_lexicons", "task_categories"]


async def seed_immutable(conn, store):
    """지움이 막힌 행 셋(사실 판, snapshot, 기본 카테고리). FK 는 꺼진 채다."""
    await conn.execute(
        "insert into fact_revisions (store_id, fact_id, entity_id, original_assertion, assertion) values ($1, 1, 1, '원문', '사실')", store)
    await conn.execute(
        "insert into knowledge_snapshots (store_id, knowledge_revision, snapshot_hash, glossary_version, renderer_version) "
        "values ($1, 1, 'sha256:' || repeat('a', 64), 'g1', 'r1')", store)
    await conn.execute("insert into task_categories (store_id, category_name, is_system) values ($1, '기타', true)", store)


async def purge_mode(conn, store):
    await conn.execute("select set_config('askbuddy.purge_store_id', $1, true)", str(store))


@unittest.skipUnless(ENABLED, SKIP_REASON)
class PurgeGuardTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.conn, self.name = await fresh_db()
        self.store = await seed_store(self.conn)
        await seed_immutable(self.conn, self.store)
        await self.conn.execute("set session_replication_role = origin")

    async def asyncTearDown(self):
        await drop_db(self.conn, self.name)

    async def test_owner_id_is_nullable_and_columns_exist(self):
        rows = await self.conn.fetch(
            "select table_name, column_name, is_nullable from information_schema.columns where table_schema = 'public' "
            "and (table_name, column_name) in (('stores','owner_id'),('stores','closing_at'),('stores','purge_due_at'),"
            "('stores','deleted_at'),('users','deleted_at'))")
        self.assertEqual(len(rows), 5)
        self.assertTrue(all(r["is_nullable"] == "YES" for r in rows))

    async def test_every_delete_guard_has_the_purge_condition(self):
        rows = await self.conn.fetch(
            "select c.relname, pg_get_triggerdef(t.oid) as def from pg_trigger t join pg_class c on c.oid = t.tgrelid "
            "join pg_namespace n on n.oid = c.relnamespace where not t.tgisinternal and n.nspname = 'public' and (t.tgtype & 8) <> 0")
        guarded = {r["relname"] for r in rows if "askbuddy_purging" in r["def"]}
        unguarded = {r["relname"] for r in rows} - guarded
        self.assertEqual(guarded, set(GUARDED))
        # 장부만 조건 없이 남는다
        self.assertEqual(unguarded, {"ai_usage_attempts"})

    async def test_active_store_rows_stay_immutable(self):
        for table in ("fact_revisions", "knowledge_snapshots", "task_categories"):
            with self.assertRaises(Exception):
                await self.conn.execute(f"delete from {table} where store_id = $1", self.store)

    async def test_guc_alone_does_not_bypass(self):
        async with self.conn.transaction():
            await purge_mode(self.conn, self.store)
            self.assertFalse(await self.conn.fetchval("select askbuddy_purging($1)", self.store))
        with self.assertRaises(Exception):
            async with self.conn.transaction():
                await purge_mode(self.conn, self.store)
                await self.conn.execute("delete from fact_revisions where store_id = $1", self.store)

    async def test_bypass_refused_before_due(self):
        await self.conn.execute(
            "update stores set closing_at = now() - interval '29 days', purge_due_at = now() + interval '1 day' where store_id = $1", self.store)
        with self.assertRaises(Exception):
            async with self.conn.transaction():
                await purge_mode(self.conn, self.store)
                await self.conn.execute("delete from knowledge_snapshots where store_id = $1", self.store)

    async def test_bypass_after_due_only_for_that_store(self):
        # seed_store 처럼 트리거를 끈 채 넣는다(매장 insert 트리거가 기본 카테고리 '기타'를 만든다)
        await self.conn.execute("set session_replication_role = replica")
        other = await self.conn.fetchval(
            "insert into stores (store_name, business_type) values ('다른 합성 매장', 'CAFE') returning store_id")
        await seed_immutable(self.conn, other)
        await self.conn.execute("set session_replication_role = origin")
        await self.conn.execute(
            "update stores set closing_at = now() - interval '31 days', purge_due_at = now() - interval '1 day' where store_id = $1", self.store)
        async with self.conn.transaction():
            await purge_mode(self.conn, self.store)
            for table in ("fact_revisions", "knowledge_snapshots", "task_categories"):
                await self.conn.execute(f"delete from {table} where store_id = $1", self.store)
        with self.assertRaises(Exception):
            async with self.conn.transaction():
                await purge_mode(self.conn, self.store)
                await self.conn.execute("delete from fact_revisions where store_id = $1", other)

    async def test_bypass_does_not_leak_out_of_the_transaction(self):
        await self.conn.execute("update stores set closing_at = now(), purge_due_at = now() - interval '1 day' where store_id = $1", self.store)
        async with self.conn.transaction():
            await purge_mode(self.conn, self.store)
        self.assertFalse(await self.conn.fetchval("select askbuddy_purging($1)", self.store))


@unittest.skipUnless(ENABLED, SKIP_REASON)
class PurgeCatalogTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.conn, self.name = await fresh_db()

    async def asyncTearDown(self):
        await drop_db(self.conn, self.name)

    async def test_every_table_is_classified(self):
        from app.bootstrap import purge
        tables = {r["tablename"] for r in await self.conn.fetch("select tablename from pg_tables where schemaname = 'public'")}
        groups = [set(purge.PURGE_ORDER), set(purge.VIA_CASCADE), set(purge.KEEP), set(purge.USER_SCOPED)]
        self.assertEqual(len(purge.PURGE_ORDER), len(set(purge.PURGE_ORDER)))
        self.assertEqual(sum(len(g) for g in groups), len(set().union(*groups)))  # 한 표는 한 묶음에만
        self.assertEqual(set().union(*groups), tables)

    async def test_tables_with_store_id_are_deleted_directly_or_kept(self):
        from app.bootstrap import purge
        with_store = {r["table_name"] for r in await self.conn.fetch(
            "select c.table_name from information_schema.columns c join pg_tables t on t.tablename = c.table_name "
            "and t.schemaname = 'public' where c.table_schema = 'public' and c.column_name = 'store_id'")}
        self.assertEqual(with_store, (set(purge.PURGE_ORDER) - {"owner_answers"}) | set(purge.KEEP))

    async def test_cascade_tables_really_cascade_from_their_parent(self):
        from app.bootstrap import purge
        fks = await self.conn.fetch(
            "select c.relname as child, p.relname as parent, k.confdeltype::text as rule from pg_constraint k "
            "join pg_class c on c.oid = k.conrelid join pg_class p on p.oid = k.confrelid "
            "where k.contype = 'f' and k.connamespace = 'public'::regnamespace")
        reach = {}
        for row in fks:
            if row["rule"] == "c":
                reach.setdefault(row["child"], set()).add(row["parent"])

        def cascades_from(child, parent, seen=()):
            return any(p == parent or (p in purge.VIA_CASCADE and p not in seen and cascades_from(p, parent, seen + (p,)))
                       for p in reach.get(child, ()))
        for child, parent in purge.VIA_CASCADE.items():
            self.assertTrue(cascades_from(child, parent), f"{child} 는 {parent} 에서 cascade 로 지워지지 않는다")

    async def test_children_are_deleted_before_blocking_parents(self):
        from app.bootstrap import purge
        pos = {t: i for i, t in enumerate(purge.PURGE_ORDER)}
        where = lambda t: pos[t] if t in pos else pos[purge.VIA_CASCADE[t]]
        skip = set(purge.KEEP) | set(purge.USER_SCOPED)
        fks = await self.conn.fetch(
            "select c.relname as child, p.relname as parent from pg_constraint k "
            "join pg_class c on c.oid = k.conrelid join pg_class p on p.oid = k.confrelid "
            "where k.contype = 'f' and k.connamespace = 'public'::regnamespace and k.confdeltype in ('a', 'r')")
        late = [(r["child"], r["parent"]) for r in fks
                if r["child"] != r["parent"] and r["child"] not in skip and r["parent"] not in skip
                and not where(r["child"]) < where(r["parent"])]
        self.assertEqual(late, [])

    async def test_ledger_columns_are_the_reviewed_set(self):
        # R1: 장부에 사람 글이 들어갈 칸이 새로 생기면 파기 뒤에도 남는다. 칸이 바뀌면 여기서 멈추고 다시 본다
        cols = {r["column_name"] for r in await self.conn.fetch(
            "select column_name from information_schema.columns where table_schema = 'public' "
            "and table_name = 'ai_usage_attempts' and udt_name in ('varchar', 'text', 'jsonb')")}
        self.assertEqual(cols, {
            "cost_phase", "cost_purpose", "stage", "logical_call_id", "registration_campaign_id", "operation_id",
            "segment_id", "status", "requested_model", "reported_model", "provider_request_id", "mode", "prompt_hash",
            "config_hash", "rate_card_version", "error_code", "cache_state", "billable_unit_name", "raw_usage",
            "usage_status", "missing_reason", "currency", "price_status"})


@unittest.skipUnless(ENABLED, SKIP_REASON)
class PurgeStoreTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.conn, self.name = await fresh_db()
        self.store = await seed_store(self.conn)
        q = "insert into users (name, role) values ($1, $2) returning user_id"
        self.owner = await self.conn.fetchval(q, "사장", "OWNER")
        self.staff = await self.conn.fetchval(q, "알바", "STAFF")
        await self.conn.execute("update stores set owner_id = $2 where store_id = $1", self.store, self.owner)
        for uid, role in [(self.owner, "OWNER"), (self.staff, "STAFF")]:
            await self.conn.execute("insert into store_members (store_id, user_id, member_role) values ($1, $2, $3)", self.store, uid, role)
        await seed_immutable(self.conn, self.store)
        await self.conn.execute(
            "insert into sources (store_id, uploaded_by, source_type, file_url) values ($1, $2, 'SCAN', 'sources/1/scan/a.pdf')", self.store, self.owner)
        await self.conn.execute(
            "insert into ai_usage_attempts (store_id, cost_phase, stage, logical_call_id, requested_model) "
            "values ($1, 'OPERATING', 'ANSWER', 'answer:1', 'synthetic-model')", self.store)
        await self.conn.execute("set session_replication_role = origin")

    async def asyncTearDown(self):
        await drop_db(self.conn, self.name)

    async def due(self, store, days_ago):
        await self.conn.execute(
            "update stores set closing_at = now() - interval '40 days', purge_due_at = now() - make_interval(days => $2) where store_id = $1", store, days_ago)

    async def leftovers(self, store):
        from app.bootstrap import purge
        counts = {}
        for table in purge.PURGE_ORDER:
            if table == "owner_answers":
                continue
            n = await self.conn.fetchval(f"select count(*) from {table} where store_id = $1", store)
            if n:
                counts[table] = n
        return counts

    async def test_purge_refuses_before_due(self):
        from app.bootstrap import purge
        await self.due(self.store, -1)
        with self.assertRaises(purge.PurgeNotDue):
            await purge.purge_store(self.conn, store_id=self.store)
        self.assertNotEqual(await self.leftovers(self.store), {})

    async def test_purge_refuses_active_store(self):
        from app.bootstrap import purge
        with self.assertRaises(purge.PurgeNotDue):
            await purge.purge_store(self.conn, store_id=self.store)

    async def test_purge_empties_the_store_and_keeps_the_ledger(self):
        from app.bootstrap import purge
        await self.due(self.store, 1)
        removed = await purge.purge_store(self.conn, store_id=self.store)
        self.assertEqual(sorted(removed), sorted([self.owner, self.staff]))
        self.assertEqual(await self.leftovers(self.store), {})
        row = await self.conn.fetchrow("select owner_id, store_name, store_slug, deleted_at from stores where store_id = $1", self.store)
        self.assertEqual((row["owner_id"], row["store_name"], row["store_slug"]), (None, "삭제된 매장", None))
        self.assertIsNotNone(row["deleted_at"])
        self.assertEqual(await self.conn.fetchval("select count(*) from ai_usage_attempts where store_id = $1", self.store), 1)
        self.assertEqual(await self.conn.fetchval("select count(*) from users where user_id = any($1::bigint[])", [self.owner, self.staff]), 0)

    async def test_purge_twice_is_refused(self):
        from app.bootstrap import purge
        await self.due(self.store, 1)
        await purge.purge_store(self.conn, store_id=self.store)
        with self.assertRaises(purge.PurgeNotDue):
            await purge.purge_store(self.conn, store_id=self.store)

    async def test_other_store_untouched(self):
        from app.bootstrap import purge
        # 트리거를 끈 채 넣는다(매장 insert 트리거가 기본 카테고리 '기타'를 만든다)
        await self.conn.execute("set session_replication_role = replica")
        other = await self.conn.fetchval("insert into stores (store_name, business_type) values ('다른 합성 매장', 'CAFE') returning store_id")
        await seed_immutable(self.conn, other)
        # 알바는 다른 매장에도 속해 있다(R6)
        await self.conn.execute("insert into store_members (store_id, user_id, member_role) values ($1, $2, 'STAFF')", other, self.staff)
        await self.conn.execute("set session_replication_role = origin")
        before = await self.leftovers(other)
        await self.due(self.store, 1)
        removed = await purge.purge_store(self.conn, store_id=self.store)
        self.assertEqual(removed, [self.owner])
        self.assertEqual(await self.leftovers(other), before)
        self.assertEqual(await self.conn.fetchval("select name from users where user_id = $1", self.staff), "알바")

    async def test_failure_midway_rolls_everything_back(self):
        from app.bootstrap import purge
        await self.due(self.store, 1)
        before = await self.leftovers(self.store)
        original = purge.PURGE_ORDER
        purge.PURGE_ORDER = original[:10] + ("없는_표",) + original[10:]
        try:
            with self.assertRaises(Exception):
                await purge.purge_store(self.conn, store_id=self.store)
        finally:
            purge.PURGE_ORDER = original
        self.assertEqual(await self.leftovers(self.store), before)
        self.assertIsNone(await self.conn.fetchval("select deleted_at from stores where store_id = $1", self.store))

    async def pool(self):
        import asyncpg
        from tests._plan7_db import _db_url
        return await asyncpg.create_pool(_db_url(self.name), min_size=1, max_size=2)

    async def test_due_store_files_are_deleted_then_rows(self):
        from app.bootstrap import purge
        await self.due(self.store, 1)
        calls = []

        async def fake(bucket, paths):
            calls.append((bucket, sorted(paths)))
        pool = await self.pool()
        try:
            self.assertEqual(await purge.purge_due_stores(pool, delete_objects=fake), [self.store])
        finally:
            await pool.close()
        self.assertEqual(calls, [("sources", ["1/scan/a.pdf"])])
        self.assertEqual(await self.leftovers(self.store), {})

    async def test_storage_failure_keeps_db(self):
        from app.bootstrap import purge
        await self.due(self.store, 1)
        before = await self.leftovers(self.store)

        async def broken(bucket, paths):
            raise RuntimeError("storage down")
        pool = await self.pool()
        try:
            self.assertEqual(await purge.purge_due_stores(pool, delete_objects=broken), [])
        finally:
            await pool.close()
        self.assertEqual(await self.leftovers(self.store), before)

    async def test_not_due_store_is_skipped(self):
        from app.bootstrap import purge
        await self.due(self.store, -1)

        async def fake(bucket, paths):
            raise AssertionError("기한 전에는 파일을 지우지 않는다")
        pool = await self.pool()
        try:
            self.assertEqual(await purge.purge_due_stores(pool, delete_objects=fake), [])
        finally:
            await pool.close()

    async def test_external_url_is_not_ours_and_does_not_block(self):
        # 우리 Storage 가 아닌 주소는 지울 것이 없다. 그 때문에 파기가 영영 막히면 안 된다
        from app.bootstrap import purge
        await self.conn.execute(
            "insert into sources (store_id, uploaded_by, source_type, file_url) values ($1, $2, 'SCAN', 'https://example.com/a.pdf')",
            self.store, self.owner)
        await self.due(self.store, 1)
        calls = []

        async def fake(bucket, paths):
            calls.append((bucket, sorted(paths)))
        pool = await self.pool()
        try:
            self.assertEqual(await purge.purge_due_stores(pool, delete_objects=fake), [self.store])
        finally:
            await pool.close()
        self.assertEqual(calls, [("sources", ["1/scan/a.pdf"])])
