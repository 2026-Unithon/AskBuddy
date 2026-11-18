"""계획 10 Task 13: 저장된 사실로 다시 조립해 초안 판을 만든다(공개 판은 그대로). 실제 스키마, 모델은 가짜."""
import unittest

from tests._plan7_db import ENABLED, SKIP_REASON, drop_db, fresh_db, seed_store
from tests.test_plan10_lines_api import _fact, _version

from app.ingest.card_plan import ProposedBlock, ProposedCard, ProposedLine


@unittest.skipUnless(ENABLED, SKIP_REASON)
class ReassembleTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.conn, self.name = await fresh_db()
        self.store = await seed_store(self.conn)
        await self.conn.execute("set session_replication_role = origin")
        self.entity = await self.conn.fetchval(
            "insert into knowledge_entities (store_id, canonical_name, name_norm) values ($1, '합성 꿀 커피', '합성꿀커피') returning entity_id",
            self.store)
        self.f_shot = await _fact(self.conn, self.store, self.entity, "shot", "샷=2", "2")
        self.f_ice = await _fact(self.conn, self.store, self.entity, "ice", "얼음=가득", "가득")
        self.card = await self.conn.fetchval(
            "insert into knowledge_cards (store_id, review_status, entity_id) values ($1, 'APPROVED', $2) returning card_id",
            self.store, self.entity)
        # 줄 없는 옛 공개 판(배포판 카드)
        self.published = await _version(self.conn, self.store, self.card, 1, [
            ("b1", "NOTES", None, [self.f_shot, self.f_ice], None)])
        await self.conn.execute(
            "update knowledge_cards set published_version_id = $3, draft_version_id = $3 where store_id = $1 and card_id = $2",
            self.store, self.card, self.published)
        self.calls = []

        async def fake_plan(groups):
            self.calls.append([g.entity_id for g in groups])
            return {g.entity_id: (ProposedCard("음료제작", (ProposedBlock(kind="STEPS", heading="HOT", lines=(
                ProposedLine("2샷 내리기", (self.f_shot,)), ProposedLine("얼음 가득", (self.f_ice,)))),)),) for g in groups}
        self.fake_plan = fake_plan

    async def asyncTearDown(self):
        await drop_db(self.conn, self.name)

    async def test_reassemble_makes_draft_with_lines_and_keeps_published(self):
        from scripts.reassemble_cards import reassemble_store
        out = await reassemble_store(self.conn, self.store, plan_call=self.fake_plan, dry_run=False)
        self.assertEqual(out["new_drafts"], 1)
        row = await self.conn.fetchrow(
            "select draft_version_id, published_version_id from knowledge_cards where store_id = $1 and card_id = $2",
            self.store, self.card)
        self.assertNotEqual(row["draft_version_id"], row["published_version_id"])
        self.assertEqual(row["published_version_id"], self.published)
        lines = await self.conn.fetch(
            "select text from card_version_lines where store_id = $1 and card_version_id = $2 order by line_no",
            self.store, row["draft_version_id"])
        self.assertEqual([r["text"] for r in lines], ["2샷 내리기", "얼음 가득"])

    async def test_dry_run_writes_nothing(self):
        from scripts.reassemble_cards import reassemble_store
        before = await self.conn.fetchval("select count(*) from card_versions where store_id = $1", self.store)
        out = await reassemble_store(self.conn, self.store, plan_call=self.fake_plan, dry_run=True)
        self.assertEqual(out["cards"], 1)
        self.assertEqual(await self.conn.fetchval("select count(*) from card_versions where store_id = $1", self.store), before)

    async def test_other_store_is_untouched(self):
        from scripts.reassemble_cards import reassemble_store
        out = await reassemble_store(self.conn, self.store + 999, plan_call=self.fake_plan, dry_run=False)
        self.assertEqual(out, {"cards": 0, "new_drafts": 0, "skipped_published_only": 0})
        self.assertEqual(self.calls, [])
