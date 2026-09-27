"""`POST /cards/{card_id}/approve` 가 옛 즉시 색인 경로 대신 `publish_cards`
조정자를 쓰는지 검증한다 (W, Task 4).

`publish_cards` 자체의 순서·롤백은 test_w_publish_approval.py 가 본다. 여기서는
라우트가 CardChange 를 어떻게 조립하고, PublishCardsResult 의 각 상태를 어떤
오류로 매핑하는지만 본다. DB 는 라우트 안 직접 호출(사전 CAS 두 번)만 흉내 낸다.
"""
from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from contextlib import asynccontextmanager

from app.cards.router import approve_card, exclude_card, restore_card
from app.contracts.usage import UsageContext
from app.errors import ApiError
from app.publish import CardChange, PublishCardsResult

STORE = 1
USER = 2
MEMBER = 3
CARD = 7
DRAFT_VERSION = 70

MOD = "app.cards.router"


def _claims() -> dict:
    return {"user_id": USER, "store_id": STORE, "role": "OWNER"}


class FakeDb:
    """라우트가 직접 부르는 두 사전 조회(카드 CAS, member_id)만 흉내 낸다."""

    def __init__(self, expected_row, member_id, *, fetchrow_error: Exception | None = None):
        self.expected_row = expected_row
        self.member_id = member_id
        self.fetchrow_error = fetchrow_error
        self.fetchrow_calls: list = []
        self.fetchval_calls: list = []

    async def fetchrow(self, query, *args):
        self.fetchrow_calls.append((query, args))
        if self.fetchrow_error is not None:
            raise self.fetchrow_error
        return self.expected_row

    async def fetchval(self, query, *args):
        self.fetchval_calls.append((query, args))
        return self.member_id


def _expected_row(*, draft_version_id=DRAFT_VERSION, published_version_id=None,
                  review_status="NEEDS_REVIEW"):
    return dict(draft_version_id=draft_version_id,
                published_version_id=published_version_id,
                review_status=review_status)


def _usage_context() -> UsageContext:
    return UsageContext(store_id=str(STORE), stage="EMBED", cost_phase="OPERATING",
                        cost_purpose="PRODUCT", logical_call_id="card-embed:t",
                        operation_id="t")


class ApproveRouteTest(unittest.IsolatedAsyncioTestCase):
    def _patches(self, *, publish_result: PublishCardsResult):
        """approve_card 가 쓰는 외부 협력자를 전부 patch 한다."""
        patches = [
            patch(f"{MOD}.repo.get_version", new=AsyncMock(
                return_value=dict(title="제목", content="내용"))),
            patch(f"{MOD}.card_usage_context", new=AsyncMock(
                return_value=_usage_context())),
            patch(f"{MOD}.prepare_embedding", new=AsyncMock(return_value="PREPARED")),
            patch(f"{MOD}.embed_card", new=AsyncMock(return_value=1)),
            patch(f"{MOD}.get_pool", new=lambda: "POOL"),
            patch(f"{MOD}.publish_cards", new=AsyncMock(return_value=publish_result)),
            patch(f"{MOD}.repo.mutation_row", new=AsyncMock(return_value=dict(
                card_id=CARD, review_status="APPROVED", draft_version_id=DRAFT_VERSION,
                published_version_id=DRAFT_VERSION,
                updated_at=datetime(2026, 9, 27, tzinfo=timezone.utc)))),
        ]
        started = [p.start() for p in patches]
        for p in patches:
            self.addCleanup(p.stop)
        return started

    async def test_published_returns_mutation_row(self):
        self._patches(publish_result=PublishCardsResult(
            status="PUBLISHED", snapshot_id=12, knowledge_revision=4))
        db = FakeDb(_expected_row(), MEMBER)
        result = await approve_card(CARD, db, _claims())
        self.assertEqual(result.card_id, CARD)
        self.assertEqual(result.review_status, "APPROVED")

    async def test_already_applied_returns_mutation_row(self):
        self._patches(publish_result=PublishCardsResult(
            status="ALREADY_APPLIED", snapshot_id=12, knowledge_revision=4))
        db = FakeDb(_expected_row(), MEMBER)
        result = await approve_card(CARD, db, _claims())
        self.assertEqual(result.card_id, CARD)

    async def test_stale_maps_to_409_version_conflict(self):
        self._patches(publish_result=PublishCardsResult(status="STALE"))
        db = FakeDb(_expected_row(), MEMBER)
        with self.assertRaises(ApiError) as raised:
            await approve_card(CARD, db, _claims())
        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(raised.exception.code, "CARD_VERSION_CONFLICT")

    async def test_stale_idempotency_conflict_also_maps_to_409_version_conflict(self):
        self._patches(publish_result=PublishCardsResult(
            status="STALE", error_code="IDEMPOTENCY_CONFLICT"))
        db = FakeDb(_expected_row(), MEMBER)
        with self.assertRaises(ApiError) as raised:
            await approve_card(CARD, db, _claims())
        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(raised.exception.code, "CARD_VERSION_CONFLICT")

    async def test_no_provenance_maps_to_409(self):
        self._patches(publish_result=PublishCardsResult(status="NO_PROVENANCE"))
        db = FakeDb(_expected_row(), MEMBER)
        with self.assertRaises(ApiError) as raised:
            await approve_card(CARD, db, _claims())
        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(raised.exception.code, "CARD_NO_PROVENANCE")

    async def test_prepare_failed_maps_to_502_retryable(self):
        self._patches(publish_result=PublishCardsResult(
            status="PREPARE_FAILED", error_code="MODEL_UNAVAILABLE"))
        db = FakeDb(_expected_row(), MEMBER)
        with self.assertRaises(ApiError) as raised:
            await approve_card(CARD, db, _claims())
        self.assertEqual(raised.exception.status_code, 502)
        self.assertEqual(raised.exception.code, "CARD_PUBLISH_FAILED")
        self.assertTrue(raised.exception.retryable)

    async def test_prepare_failed_race_codes_map_to_409_version_conflict(self):
        """R 준비 경합에서 진 요청은 장애(502)가 아니라 충돌(409)이다(final fix #4)."""
        for code in ("STALE_PUBLICATION", "STALE_KNOWLEDGE", "IDEMPOTENCY_CONFLICT"):
            with self.subTest(code=code):
                self._patches(publish_result=PublishCardsResult(
                    status="PREPARE_FAILED", error_code=code))
                db = FakeDb(_expected_row(), MEMBER)
                with self.assertRaises(ApiError) as raised:
                    await approve_card(CARD, db, _claims())
                self.assertEqual(raised.exception.status_code, 409)
                self.assertEqual(raised.exception.code, "CARD_VERSION_CONFLICT")

    async def test_invalid_content_maps_to_409_content_invalid(self):
        self._patches(publish_result=PublishCardsResult(status="INVALID_CONTENT"))
        db = FakeDb(_expected_row(), MEMBER)
        with self.assertRaises(ApiError) as raised:
            await approve_card(CARD, db, _claims())
        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(raised.exception.code, "CARD_CONTENT_INVALID")
        self.assertEqual(raised.exception.message,
                         "카드 내용이 비어 있거나 너무 길어 공개할 수 없습니다.")

    async def test_builds_card_change_and_idempotency_key(self):
        _, _, _, _, _, publish_mock, _ = self._patches(publish_result=PublishCardsResult(
            status="PUBLISHED", snapshot_id=1, knowledge_revision=1))
        db = FakeDb(_expected_row(), MEMBER)
        await approve_card(CARD, db, _claims())
        publish_mock.assert_awaited_once()
        kwargs = publish_mock.await_args.kwargs
        self.assertEqual(kwargs["store_id"], STORE)
        self.assertEqual(kwargs["member_id"], MEMBER)
        self.assertEqual(kwargs["actor_user_id"], USER)
        self.assertEqual(kwargs["changes"], [CardChange(
            card_id=CARD, expected_draft_version_id=DRAFT_VERSION,
            target_card_version_id=DRAFT_VERSION)])
        self.assertEqual(kwargs["idempotency_key"], f"approve:{CARD}:{DRAFT_VERSION}")
        self.assertIn("in_transaction", kwargs)

    async def test_member_id_missing_raises_owner_only(self):
        self._patches(publish_result=PublishCardsResult(status="PUBLISHED"))
        db = FakeDb(_expected_row(), None)
        with self.assertRaises(ApiError) as raised:
            await approve_card(CARD, db, _claims())
        self.assertEqual(raised.exception.status_code, 403)
        self.assertEqual(raised.exception.code, "OWNER_ONLY")

    async def test_card_not_found_still_404(self):
        db = FakeDb(None, MEMBER)
        with self.assertRaises(ApiError) as raised:
            await approve_card(CARD, db, _claims())
        self.assertEqual(raised.exception.status_code, 404)
        self.assertEqual(raised.exception.code, "CARD_NOT_FOUND")

    async def test_draft_missing_still_409(self):
        db = FakeDb(_expected_row(draft_version_id=None), MEMBER)
        with self.assertRaises(ApiError) as raised:
            await approve_card(CARD, db, _claims())
        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(raised.exception.code, "CARD_DRAFT_MISSING")

    async def test_excluded_still_409(self):
        db = FakeDb(_expected_row(review_status="EXCLUDED"), MEMBER)
        with self.assertRaises(ApiError) as raised:
            await approve_card(CARD, db, _claims())
        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(raised.exception.code, "CARD_EXCLUDED")

    async def test_precheck_db_error_maps_to_502_not_raw_500(self):
        """CAS 조회 자체가 죽어도(일시적 asyncpg 오류) ApiError 502 로 잡혀야 한다.

        수정 전에는 이 조회가 try 밖에 있어 원시 예외가 그대로 올라갔다(Fix round 1 #1).
        """
        db_error = RuntimeError("connection reset by peer")
        db = FakeDb(None, MEMBER, fetchrow_error=db_error)
        with self.assertRaises(ApiError) as raised:
            await approve_card(CARD, db, _claims())
        self.assertEqual(raised.exception.status_code, 502)
        self.assertEqual(raised.exception.code, "CARD_PUBLISH_FAILED")
        self.assertTrue(raised.exception.retryable)
        self.assertIs(raised.exception.__cause__, db_error)

    async def test_unknown_publish_status_fails_loudly_not_silent_prepare_failed(self):
        """미정의 status 는 PREPARE_FAILED 분기를 조용히 타면 안 된다(Fix round 1 #2).

        RuntimeError 로 실패해 바깥 except Exception 이 502 로 매핑하되, 원인이
        RuntimeError(그 status 문자열 포함)인지까지 확인해 PREPARE_FAILED 분기와
        구분한다.
        """
        self._patches(publish_result=PublishCardsResult(status="SOMETHING_NEW"))
        db = FakeDb(_expected_row(), MEMBER)
        with self.assertRaises(ApiError) as raised:
            await approve_card(CARD, db, _claims())
        self.assertEqual(raised.exception.status_code, 502)
        self.assertEqual(raised.exception.code, "CARD_PUBLISH_FAILED")
        self.assertTrue(raised.exception.retryable)
        cause = raised.exception.__cause__
        self.assertIsInstance(cause, RuntimeError)
        self.assertIn("SOMETHING_NEW", str(cause))


class StatusDb:
    """제외·복원 라우트용 가짜 세션. 트랜잭션 경계와 커밋 여부를 기록한다."""

    def __init__(self, log: list, member_id=MEMBER):
        self.log = log
        self.member_id = member_id

    @asynccontextmanager
    async def transaction(self):
        self.log.append("tx_begin")
        yield
        self.log.append("tx_commit")

    async def execute(self, query, *args):
        self.log.append("update_status")

    async def fetchval(self, query, *args):
        self.log.append("member_lookup")
        return self.member_id


class ExcludeRestoreRepublishTest(unittest.IsolatedAsyncioTestCase):
    """제외·복원 커밋 뒤 현재 포인터로 best-effort 재발행한다(final fix #1)."""

    def setUp(self):
        self.log: list = []
        self.card = dict(card_id=CARD, review_status="APPROVED", published_version_id=70,
                         draft_version_id=70)
        log = self.log

        async def publish(pool, **kwargs):
            log.append("publish_cards")
            return self.publish_result

        self.publish_result = PublishCardsResult(status="PUBLISHED", snapshot_id=5,
                                                 knowledge_revision=5)
        self.publish = AsyncMock(side_effect=publish)
        patches = [
            patch(f"{MOD}.repo.get_card_for_update",
                  new=AsyncMock(side_effect=lambda *a: dict(self.card))),
            patch(f"{MOD}.repo.add_event", new=AsyncMock(return_value=801)),
            patch(f"{MOD}.repo.mutation_row", new=AsyncMock(side_effect=lambda *a: dict(
                card_id=CARD, review_status="APPROVED", draft_version_id=70,
                published_version_id=self.card["published_version_id"],
                updated_at=datetime(2026, 9, 27, tzinfo=timezone.utc)))),
            patch(f"{MOD}.card_usage_context", new=AsyncMock(return_value=_usage_context())),
            patch(f"{MOD}.get_pool", new=lambda: "POOL"),
            patch(f"{MOD}.publish_cards", new=self.publish),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def _assert_republished(self, kind):
        self.publish.assert_awaited_once()
        pool, = self.publish.await_args.args
        kwargs = self.publish.await_args.kwargs
        self.assertEqual(pool, "POOL")
        self.assertEqual(kwargs["changes"], [])
        self.assertEqual(kwargs["idempotency_key"], f"{kind}:{CARD}:801")
        self.assertLessEqual(len(kwargs["idempotency_key"]), 40)
        self.assertEqual((kwargs["store_id"], kwargs["member_id"], kwargs["actor_user_id"]),
                         (STORE, MEMBER, USER))
        self.assertEqual(kwargs["usage_context"], _usage_context())
        # 상태 변경이 커밋된 뒤에만 재발행한다
        self.assertLess(self.log.index("tx_commit"), self.log.index("publish_cards"))

    async def test_exclude_commits_then_republishes(self):
        await exclude_card(CARD, StatusDb(self.log), _claims())
        self._assert_republished("exclude")

    async def test_restore_commits_then_republishes(self):
        self.card["review_status"] = "EXCLUDED"
        await restore_card(CARD, StatusDb(self.log), _claims())
        self._assert_republished("restore")

    async def test_restore_of_never_published_card_does_not_republish(self):
        self.card.update(review_status="EXCLUDED", published_version_id=None)
        await restore_card(CARD, StatusDb(self.log), _claims())
        self.publish.assert_not_awaited()

    async def test_exclude_of_never_published_card_does_not_republish(self):
        self.card.update(review_status="PENDING", published_version_id=None)
        await exclude_card(CARD, StatusDb(self.log), _claims())
        self.publish.assert_not_awaited()

    async def test_republish_exception_is_logged_and_request_succeeds(self):
        self.publish.side_effect = RuntimeError("R 준비 장애")
        for route, status in ((exclude_card, "APPROVED"), (restore_card, "EXCLUDED")):
            with self.subTest(route=route.__name__):
                self.card["review_status"] = status
                with self.assertLogs(MOD, level="ERROR") as logs:
                    result = await route(CARD, StatusDb(self.log), _claims())
                self.assertEqual(result.card_id, CARD)
                self.assertIn("재발행 실패", logs.output[0])
                self.assertIn("Traceback", "\n".join(logs.output))

    async def test_republish_non_success_status_is_logged_and_request_succeeds(self):
        self.publish_result = PublishCardsResult(status="PREPARE_FAILED",
                                                 error_code="INDEX_PREPARE_FAILED")
        with self.assertLogs(MOD, level="WARNING") as logs:
            result = await exclude_card(CARD, StatusDb(self.log), _claims())
        self.assertEqual(result.card_id, CARD)
        self.assertIn("INDEX_PREPARE_FAILED", logs.output[0])

    async def test_missing_owner_membership_is_logged_not_raised(self):
        with self.assertLogs(MOD, level="ERROR"):
            result = await exclude_card(CARD, StatusDb(self.log, member_id=None), _claims())
        self.assertEqual(result.card_id, CARD)
        self.publish.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
