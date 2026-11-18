"""계획 10 Task 7: 보기 응답에 구역·줄, 저장 요청에 줄. 실제 스키마. PLAN7_TEST_DB_URL 이 없으면 건너뛴다."""
import unittest

from tests._plan7_db import ENABLED, SKIP_REASON, drop_db, fresh_db, seed_store

from app.cards.fact_edit_schemas import EditBlock, EditKeep, EditLine, EditModify, FactEditRequest, FactFields
from app.cards.router import get_card_facts, save_card_facts
from app.errors import ApiError


async def _fact(conn, store, entity, slot, sentence, value):
    fact_id = await conn.fetchval(
        "insert into knowledge_facts (store_id, entity_id, identity_key, slot_key) values ($1, $2, $3, $3) returning fact_id",
        store, entity, slot)
    rev = await conn.fetchval(
        "insert into fact_revisions (store_id, fact_id, entity_id, original_assertion, assertion, subject, value_text, polarity) "
        "values ($1, $2, $3, $4, $4, '합성 꿀 커피', $5, 'AFFIRM') returning fact_revision_id",
        store, fact_id, entity, sentence, value)
    await conn.execute("update knowledge_facts set head_revision_id = $3 where store_id = $1 and fact_id = $2", store, fact_id, rev)
    return rev


async def _version(conn, store, card, no, blocks):
    """blocks = [(block_id, kind, heading, [fact_revision_id…], [(text, [ids])…] 또는 None)]"""
    version = await conn.fetchval(
        "insert into card_versions (store_id, card_id, version_no, title, content, change_source) "
        "values ($1, $2, $3, '합성 꿀 커피', '-', 'EXTRACTION') returning version_id", store, card, no)
    for order, (block_id, kind, heading, facts, lines) in enumerate(blocks, start=1):
        await conn.execute(
            "insert into card_version_blocks (store_id, card_version_id, block_id, kind, block_order, heading) "
            "values ($1, $2, $3, $4, $5, $6)", store, version, block_id, kind, order, heading)
        for pos, rid in enumerate(facts, start=1):
            await conn.execute(
                "insert into card_block_facts (store_id, card_version_id, block_id, fact_revision_id, position) "
                "values ($1, $2, $3, $4, $5)", store, version, block_id, rid, pos)
        for n, (text, ids) in enumerate(lines or [], start=1):
            await conn.execute(
                "insert into card_version_lines (store_id, card_version_id, block_id, line_no, text, fact_revision_ids) "
                "values ($1, $2, $3, $4, $5, $6::bigint[])", store, version, block_id, n, text, ids)
    return version


@unittest.skipUnless(ENABLED, SKIP_REASON)
class LinesApiTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.conn, self.name = await fresh_db()
        self.store = await seed_store(self.conn)
        await self.conn.execute("set session_replication_role = origin")
        self.owner_claims = {"user_id": 1, "store_id": self.store, "role": "OWNER"}
        await self.conn.execute(
            "insert into users (user_id, name, email, role) overriding system value "
            "values (1, '합성 사장님', 'owner@synthetic.test', 'OWNER') on conflict do nothing")
        entity = await self.conn.fetchval(
            "insert into knowledge_entities (store_id, canonical_name, name_norm) values ($1, '합성 꿀 커피', '합성꿀커피') returning entity_id",
            self.store)
        self.f_shot = await _fact(self.conn, self.store, entity, "shot", "샷=2", "2")
        self.f_ice = await _fact(self.conn, self.store, entity, "ice", "얼음=가득", "가득")
        self.card = await self.conn.fetchval(
            "insert into knowledge_cards (store_id, review_status, entity_id) values ($1, 'APPROVED', $2) returning card_id",
            self.store, entity)
        self.published = await _version(self.conn, self.store, self.card, 1, [
            ("b1", "STEPS", "HOT", [self.f_shot, self.f_ice], [("2샷", [self.f_shot]), ("얼음 가득", [self.f_ice])])])
        # 초안 = 줄 없는 옛 판(배포판 카드 모양)
        self.version = await _version(self.conn, self.store, self.card, 2, [
            ("b1", "NOTES", None, [self.f_shot, self.f_ice], None)])
        await self.conn.execute(
            "update knowledge_cards set published_version_id = $3, draft_version_id = $4 where store_id = $1 and card_id = $2",
            self.store, self.card, self.published, self.version)

    async def asyncTearDown(self):
        await drop_db(self.conn, self.name)

    async def test_lines_fallback_for_old_version(self):
        view = await get_card_facts(self.card, self.conn, self.owner_claims)
        self.assertEqual([(l.line_no, l.text) for l in view.blocks[0].lines], [(1, "샷=2"), (2, "얼음=가득")])
        self.assertIsNone(view.blocks[0].heading)

    async def test_view_returns_stored_heading_and_lines(self):
        await self.conn.execute(
            "update knowledge_cards set draft_version_id = $3 where store_id = $1 and card_id = $2",
            self.store, self.card, self.published)
        view = await get_card_facts(self.card, self.conn, self.owner_claims)
        self.assertEqual(view.blocks[0].heading, "HOT")
        self.assertEqual([(l.text, l.fact_revision_ids) for l in view.blocks[0].lines],
                         [("2샷", [self.f_shot]), ("얼음 가득", [self.f_ice])])

    async def test_owner_line_edit_rewrites_facts(self):
        req = FactEditRequest(expected_version_id=self.version, idempotency_key="plan10-edit-1", blocks=[EditBlock(
            kind="STEPS", heading="HOT",
            items=[EditModify(op="MODIFY", fact_revision_id=self.f_shot, fact=FactFields(sentence="샷=3", value="3")),
                   EditKeep(op="KEEP", fact_revision_id=self.f_ice)],
            lines=[EditLine(text="얼음 가득", fact_revision_ids=[self.f_ice]), EditLine(text="3샷", fact_revision_ids=[self.f_shot])])])
        result = await save_card_facts(self.card, req, self.conn, self.owner_claims)
        rows = await self.conn.fetch(
            "select line_no, text, fact_revision_ids from card_version_lines where store_id = $1 and card_version_id = $2 order by line_no",
            self.store, result.draft_version_id)
        self.assertEqual([r["text"] for r in rows], ["얼음 가득", "3샷"])
        self.assertNotIn(self.f_shot, list(rows[1]["fact_revision_ids"]))  # 고친 사실은 새 판을 인용한다
        self.assertEqual(await self.conn.fetchval(
            "select heading from card_version_blocks where store_id = $1 and card_version_id = $2",
            self.store, result.draft_version_id), "HOT")

    async def test_line_only_reorder_is_a_change(self):
        # 사실은 그대로이고 줄 글·순서만 바꿔도 새 판이다
        req = FactEditRequest(expected_version_id=self.version, idempotency_key="plan10-edit-3", blocks=[EditBlock(
            kind="NOTES", items=[EditKeep(op="KEEP", fact_revision_id=self.f_shot), EditKeep(op="KEEP", fact_revision_id=self.f_ice)],
            lines=[EditLine(text="얼음 가득", fact_revision_ids=[self.f_ice]), EditLine(text="2샷", fact_revision_ids=[self.f_shot])])])
        result = await save_card_facts(self.card, req, self.conn, self.owner_claims)
        self.assertTrue(result.changed)
        self.assertEqual(await self.conn.fetchval(
            "select content from card_versions where store_id = $1 and version_id = $2", self.store, result.draft_version_id),
            "얼음 가득\n2샷")

    async def test_line_ref_outside_block_rejected(self):
        req = FactEditRequest(expected_version_id=self.version, idempotency_key="plan10-edit-2", blocks=[
            EditBlock(kind="NOTES", items=[EditKeep(op="KEEP", fact_revision_id=self.f_ice)],
                      lines=[EditLine(text="2샷", fact_revision_ids=[self.f_shot])]),
            EditBlock(kind="NOTES", items=[EditKeep(op="KEEP", fact_revision_id=self.f_shot)])])
        with self.assertRaises(ApiError) as err:
            await save_card_facts(self.card, req, self.conn, self.owner_claims)
        self.assertEqual(err.exception.code, "LINE_REF_OUTSIDE_BLOCK")

    async def test_staff_view_has_lines_of_published_version_only(self):
        from app.learn.recipe_blocks import published_fact_blocks
        blocks = await published_fact_blocks(self.conn, self.store, self.card, self.published)
        self.assertEqual([l["text"] for b in blocks for l in b["lines"]], ["2샷", "얼음 가득"])
        self.assertEqual(blocks[0]["heading"], "HOT")

    async def _use_published_as_draft(self):
        await self.conn.execute(
            "update knowledge_cards set draft_version_id = $3 where store_id = $1 and card_id = $2",
            self.store, self.card, self.published)

    async def test_review_write_keeps_other_lines(self):
        from app.cards.fact_edit_schemas import ReviewWriteRequest
        from app.cards.router import write_review_value
        await self._use_published_as_draft()
        result = await write_review_value(self.card, ReviewWriteRequest(
            fact_revision_id=self.f_ice, text="얼음은 컵 끝까지", expected_version_id=self.published,
            idempotency_key="plan10-review-1"), self.conn, self.owner_claims)
        rows = await self.conn.fetch(
            "select text from card_version_lines where store_id = $1 and card_version_id = $2 order by line_no",
            self.store, result.draft_version_id)
        self.assertEqual([r["text"] for r in rows], ["2샷", "얼음은 컵 끝까지"])

    async def test_revert_restores_old_lines(self):
        from app.cards.fact_edit_schemas import RevertRequest
        from app.cards.router import revert_fact_edit
        await self._use_published_as_draft()
        req = FactEditRequest(expected_version_id=self.published, idempotency_key="plan10-edit-4", blocks=[EditBlock(
            kind="STEPS", heading="ICE", items=[EditKeep(op="KEEP", fact_revision_id=self.f_shot),
                                               EditKeep(op="KEEP", fact_revision_id=self.f_ice)],
            lines=[EditLine(text="얼음 먼저", fact_revision_ids=[self.f_ice]), EditLine(text="투샷", fact_revision_ids=[self.f_shot])])])
        edited = await save_card_facts(self.card, req, self.conn, self.owner_claims)
        back = await revert_fact_edit(self.card, edited.edit_id, RevertRequest(idempotency_key="plan10-revert-1"),
                                      self.conn, self.owner_claims)
        rows = await self.conn.fetch(
            "select text from card_version_lines where store_id = $1 and card_version_id = $2 order by line_no",
            self.store, back.draft_version_id)
        self.assertEqual([r["text"] for r in rows], ["2샷", "얼음 가득"])
        self.assertEqual(await self.conn.fetchval(
            "select heading from card_version_blocks where store_id = $1 and card_version_id = $2",
            self.store, back.draft_version_id), "HOT")
