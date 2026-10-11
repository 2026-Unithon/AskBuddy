"""공개 조정자 `publish_cards` 의 순서·롤백 규칙을 검증한다 (W, Task 3).

DB·R 함수는 전부 patch 한다. 여기서 보는 것은 **무엇을 어떤 순서로 부르고,
언제 멈추고, 트랜잭션 안에서 무엇이 롤백되는가** 다. 실제 DB 는 Task 7 의
통합 스크립트가 돈다.
"""
from __future__ import annotations

import unittest
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from app.contracts.card import CardBlock
from app.contracts.errors import ErrorDetail
from app.contracts.hashing import digest, knowledge_content_payload, snapshot_digest
from app.contracts.publication import PrepareIndexResult
from app.contracts.snapshot import (
    KnowledgeContent,
    PublishedCard,
    PublishedKnowledgeSnapshot,
    RawSpan,
)
from app.errors import ApiError
from app.learn.approved_renderer import RENDERER_VERSION
from app.publish import approval
from app.publish.approval import (
    CardChange,
    PublishCardsResult,
    build_prepare_request,
    publish_cards,
    snapshot_hash_for,
)
from app.publish.content import InvalidContent, NoProvenance
from app.publish.service import PublishOutcome

STORE = 1
MOD = "app.publish.approval"


def _content(card_versions: dict[int, int]) -> KnowledgeContent:
    cards, spans = [], []
    for n, (card_id, version_id) in enumerate(sorted(card_versions.items()), start=1):
        span_id = str(900 + n)
        cards.append(PublishedCard(
            card_id=str(card_id), card_version_id=str(version_id),
            entity_id=str(card_id), title=f"카드 {card_id}",
            blocks=(CardBlock(block_id="raw1", kind="RAW", order=1,
                              raw_span_id=span_id),)))
        spans.append(RawSpan(raw_span_id=span_id, source_id="3", text=f"원문 {card_id}"))
    return KnowledgeContent(store_id=str(STORE), glossary_version="glossary/v1",
                            renderer_version=RENDERER_VERSION, cards=tuple(cards),
                            raw_spans=tuple(spans))


class FakeConn:
    def __init__(self, log: list):
        self.log = log

    @asynccontextmanager
    async def transaction(self):
        self.log.append("tx_begin")
        try:
            yield
        except BaseException:
            self.log.append("tx_rollback")
            raise
        self.log.append("tx_commit")


class FakePool:
    def __init__(self, log: list):
        self.log = log
        self.held = 0

    @asynccontextmanager
    async def acquire(self):
        self.held += 1
        self.log.append("acquire")
        try:
            yield FakeConn(self.log)
        finally:
            self.held -= 1
            self.log.append("release")


def _card(draft, published=None, status="NEEDS_REVIEW"):
    return dict(draft_version_id=draft, published_version_id=published,
                review_status=status)


class Harness:
    """patch 묶음. 각 테스트가 필요한 부분만 바꿔 쓴다."""

    def __init__(self):
        self.log: list = []
        self.pool = FakePool(self.log)
        self.manifest = {7: 70}
        # 준비 조회(변경 카드), tx 잠금 조회(manifest 전체)
        self.card_states = [{5: _card(50)},
                            {5: _card(50), 7: _card(70, published=70, status="APPROVED")}]
        self.operation: dict | None = None  # operations 선조회 결과
        self.read_cards_ids: list = []
        self.prepare_result = PrepareIndexResult(
            status="PREPARED", prepared_id="44", payload_hash="sha256:" + "a" * 64,
            index_config_version="r-block-index/v1",
            expires_at=datetime(2026, 9, 27, tzinfo=timezone.utc))
        self.publish_outcome = PublishOutcome(status="PUBLISHED", knowledge_revision=4,
                                              snapshot_id=12, publication_revision=4)
        self.no_provenance: set[int] = set()
        # 카드별로 공개 직전 내용 확인에서 던질 예외
        self.check_errors: dict[int, Exception] = {}
        self.build_errors: dict[int, Exception] = {}
        self.activate_exc: Exception | None = None
        self.prepare_calls: list = []
        self.publish_calls: list = []
        self.built_manifest: dict | None = None
        self.prepare_held: list[int] = []

    def start(self, test: unittest.TestCase):
        h = self

        async def read_publication(conn, *, store_id):
            h.log.append("read_publication")
            return dict(publication_revision=3, knowledge_revision=3,
                        current_snapshot_id=11, glossary_version="glossary/v1")

        async def read_cards(conn, *, store_id, card_ids, for_update):
            h.log.append("read_cards_locked" if for_update else "read_cards")
            h.read_cards_ids.append(sorted(card_ids))
            return h.card_states.pop(0)

        async def current_manifest(conn, *, store_id):
            return dict(h.manifest)

        async def build(conn, *, store_id, manifest, glossary_version):
            for card_id in manifest:
                h.log.append(f"check:{card_id}")
                if card_id in h.no_provenance:
                    raise NoProvenance(str(card_id))
                if card_id in h.check_errors:
                    raise h.check_errors[card_id]
                if card_id in h.build_errors:
                    raise h.build_errors[card_id]
            h.built_manifest = dict(manifest)
            return _content(manifest)

        async def prepare(pool, *, request, content, usage_context):
            h.prepare_held.append(h.pool.held)
            h.prepare_calls.append((request, content))
            h.log.append("prepare")
            return h.prepare_result

        async def lock_publication(conn, store_id):
            h.log.append("lock_publication")
            return dict(publication_revision=3, knowledge_revision=3)

        async def publish(conn, **kwargs):
            h.log.append("publish_knowledge")
            h.publish_calls.append(kwargs)
            return h.publish_outcome

        async def mark(conn, *, store_id, actor_user_id, change, card):
            h.log.append(f"mark:{change.card_id}")

        async def activate(conn, *, store_id, prepared_id, snapshot_id):
            h.log.append(f"activate:{prepared_id}:{snapshot_id}")
            if h.activate_exc:
                raise h.activate_exc

        async def read_operation(conn, *, store_id, member_id, idempotency_key):
            h.log.append("read_operation")
            return h.operation

        for name, fn in [("_read_operation", read_operation),
                         ("_read_publication", read_publication),
                         ("_read_cards", read_cards),
                         ("current_manifest", current_manifest),
                         ("build_knowledge_content", build),
                         ("prepare_index_request", prepare),
                         ("_lock_publication", lock_publication),
                         ("publish_knowledge", publish),
                         ("_mark_published", mark),
                         ("activate_prepared_index", activate)]:
            p = patch(f"{MOD}.{name}", side_effect=fn)
            p.start()
            test.addCleanup(p.stop)

    async def run(self, hook=None, changes=None, **kwargs):
        return await publish_cards(
            self.pool, store_id=STORE, member_id=2, actor_user_id=3,
            changes=changes if changes is not None else [CardChange(5, 50, 50)],
            idempotency_key="approve-key-0001", usage_context=object(),
            in_transaction=hook, **kwargs)


class PublishCardsTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.h = Harness()
        self.h.start(self)

    def _after_prepare(self):
        return self.h.log[self.h.log.index("prepare"):]

    async def test_happy_path_order_and_published(self):
        hook = AsyncMock(side_effect=lambda conn, sid, kr: self.h.log.append(f"hook:{sid}:{kr}"))
        result = await self.h.run(hook=hook)
        self.assertEqual(result, PublishCardsResult(status="PUBLISHED", snapshot_id=12,
                                                    knowledge_revision=4))
        self.assertEqual(self._after_prepare(), [
            "prepare", "acquire", "tx_begin", "lock_publication", "read_cards_locked",
            "publish_knowledge", "mark:5", "activate:44:12", "hook:12:4",
            "tx_commit", "release"])
        # R 준비 중에는 어떤 연결도 잡혀 있지 않다
        self.assertEqual(self.h.prepare_held, [0])
        # manifest 는 기존 공개 카드 + 변경 카드
        self.assertEqual(self.h.built_manifest, {7: 70, 5: 50})
        call = self.h.publish_calls[0]
        self.assertEqual(call["card_versions"], [(5, 50), (7, 70)])
        self.assertEqual(call["expected_publication_revision"], 3)
        self.assertEqual(call["idempotency_key"], "approve-key-0001")
        self.assertEqual(call["body_hash"], digest([dict(
            card_id=5, expected_draft_version_id=50, target_card_version_id=50)]))
        self.assertEqual(call["renderer_version"], RENDERER_VERSION)
        self.assertEqual(call["glossary_version"], "glossary/v1")
        self.assertEqual(call["snapshot_hash"],
                         snapshot_hash_for(_content({7: 70, 5: 50}), 4))

    async def test_after_prepare_runs_after_prepare_before_transaction(self):
        async def after_prepare():
            # R 준비 뒤·공개 트랜잭션 전이고, 연결을 잡고 있지 않다
            self.h.log.append(f"after_prepare:held={self.h.pool.held}")
            return True

        result = await self.h.run(after_prepare=after_prepare)
        self.assertEqual(result.status, "PUBLISHED")
        self.assertEqual(self._after_prepare()[:3],
                         ["prepare", "after_prepare:held=0", "acquire"])

    async def test_after_prepare_false_is_lease_lost_without_publish(self):
        result = await self.h.run(after_prepare=AsyncMock(return_value=False))
        self.assertEqual(result, PublishCardsResult(status="LEASE_LOST"))
        self.assertEqual(self.h.publish_calls, [])
        # 공개 트랜잭션을 열지 않는다
        self.assertNotIn("tx_begin", self._after_prepare())
        self.assertNotIn("lock_publication", self.h.log)

    async def test_after_prepare_not_called_when_prepare_fails(self):
        self.h.prepare_result = PrepareIndexResult(status="FAILED", error=ErrorDetail(
            code="INDEX_PREPARE_FAILED", message="실패", request_id="k", retryable=False))
        after_prepare = AsyncMock(return_value=True)
        result = await self.h.run(after_prepare=after_prepare)
        self.assertEqual(result.status, "PREPARE_FAILED")
        after_prepare.assert_not_awaited()

    async def test_prepare_request_matches_content(self):
        await self.h.run()
        request, content = self.h.prepare_calls[0]
        self.assertEqual(set(request.card_ids), {c.card_id for c in content.cards})
        self.assertEqual(request.expected_card_revisions, ())
        self.assertEqual(request.content_hash, digest(knowledge_content_payload(content)))
        self.assertEqual(request.idempotency.body_hash, digest(
            request.model_dump(mode="json", exclude={"idempotency"})))
        self.assertEqual(request.scope.member_id, "2")
        self.assertEqual(request.expected_publication_revision, "3")
        self.assertTrue(request.idempotency.key.startswith(
            "approve-key-0001:3:" + request.content_hash.split(":")[1][:16] + ":"))

    async def test_precheck_cas_mismatch_is_stale_without_prepare(self):
        self.h.card_states = [{5: _card(51)}]
        result = await self.h.run()
        self.assertEqual(result.status, "STALE")
        self.assertEqual(self.h.prepare_calls, [])

    async def test_target_must_equal_expected_draft(self):
        result = await self.h.run(changes=[CardChange(5, 50, 49)])
        self.assertEqual(result.status, "STALE")
        self.assertEqual(self.h.prepare_calls, [])

    async def test_excluded_card_is_stale(self):
        self.h.card_states = [{5: _card(50, status="EXCLUDED")}]
        result = await self.h.run()
        self.assertEqual(result.status, "STALE")
        self.assertEqual(self.h.prepare_calls, [])

    async def test_cas_changed_after_prepare_rolls_back(self):
        self.h.card_states = [{5: _card(50)}, {5: _card(52)}]
        result = await self.h.run()
        self.assertEqual(result.status, "STALE")
        self.assertEqual(self.h.publish_calls, [])
        self.assertIn("tx_rollback", self._after_prepare())

    async def test_publish_knowledge_stale_rolls_back(self):
        self.h.publish_outcome = PublishOutcome(status="STALE", publication_revision=5)
        result = await self.h.run()
        self.assertEqual(result.status, "STALE")
        after = self._after_prepare()
        self.assertIn("tx_rollback", after)
        self.assertFalse(any(e.startswith(("mark:", "activate:")) for e in after))

    async def test_prepare_failure_never_enters_transaction(self):
        self.h.prepare_result = PrepareIndexResult(status="FAILED", error=ErrorDetail(
            code="INDEX_PREPARE_FAILED", message="실패", request_id="k", retryable=False))
        result = await self.h.run()
        self.assertEqual(result, PublishCardsResult(status="PREPARE_FAILED",
                                                    error_code="INDEX_PREPARE_FAILED"))
        self.assertNotIn("tx_begin", self._after_prepare())
        self.assertEqual(self.h.publish_calls, [])

    async def test_activate_error_propagates_and_skips_hook(self):
        self.h.activate_exc = ApiError(409, "HASH_MISMATCH", "다르다")
        hook = AsyncMock()
        with self.assertRaises(ApiError):
            await self.h.run(hook=hook)
        hook.assert_not_awaited()
        self.assertIn("tx_rollback", self._after_prepare())

    async def test_hook_error_propagates_and_rolls_back(self):
        hook = AsyncMock(side_effect=RuntimeError("hook 실패"))
        with self.assertRaises(RuntimeError):
            await self.h.run(hook=hook)
        self.assertIn("tx_rollback", self._after_prepare())
        self.assertNotIn("tx_commit", self._after_prepare())

    async def test_already_applied_skips_activation(self):
        self.h.publish_outcome = PublishOutcome(status="ALREADY_APPLIED", knowledge_revision=4,
                                                snapshot_id=12, publication_revision=4)
        hook = AsyncMock()
        result = await self.h.run(hook=hook)
        self.assertEqual(result, PublishCardsResult(status="ALREADY_APPLIED", snapshot_id=12,
                                                    knowledge_revision=4))
        after = self._after_prepare()
        self.assertFalse(any(e.startswith(("mark:", "activate:")) for e in after))
        hook.assert_not_awaited()

    async def test_changed_card_without_provenance_stops_before_prepare(self):
        self.h.no_provenance = {5}
        result = await self.h.run()
        self.assertEqual(result.status, "NO_PROVENANCE")
        self.assertEqual(self.h.prepare_calls, [])
        # 블록 고정 트랜잭션은 통째로 롤백된다 — savepoint 와 바깥 트랜잭션 둘 다
        prep = self.h.log[self.h.log.index("read_publication"):]
        fix = prep[prep.index("tx_begin"):prep.index("release")]
        self.assertEqual(fix, ["tx_begin", "tx_begin", "check:5",
                               "tx_rollback", "tx_rollback"])
        self.assertNotIn("tx_commit", self.h.log)

    async def test_existing_card_without_provenance_is_dropped(self):
        self.h.no_provenance = {7}
        with self.assertLogs(MOD, level="WARNING"):
            result = await self.h.run()
        self.assertEqual(result.status, "PUBLISHED")
        self.assertEqual(self.h.built_manifest, {5: 50})
        self.assertEqual(self.h.publish_calls[0]["card_versions"], [(5, 50)])
        # 7 의 savepoint 만 롤백되고 바깥 블록 고정 트랜잭션은 커밋된다
        prep = self.h.log[self.h.log.index("read_publication"):]
        fix = [e for e in prep[:prep.index("release")] if not e.startswith("check:")]
        self.assertEqual(fix.count("tx_rollback"), 1)
        self.assertEqual(fix[-1], "tx_commit")

    def _body_hash(self):
        return digest([dict(card_id=5, expected_draft_version_id=50,
                            target_card_version_id=50)])

    async def test_committed_replay_returns_already_applied_without_prepare(self):
        self.h.operation = dict(status="SUCCEEDED", body_hash=self._body_hash(),
                                response={"knowledge_revision": 4, "snapshot_id": 12,
                                          "publication_revision": 4})
        # 공개 뒤 초안이 바뀌어도 같은 요청의 재시도는 이미 된 공개를 돌려준다
        self.h.card_states = [{5: _card(51)}]
        result = await self.h.run()
        self.assertEqual(result, PublishCardsResult(status="ALREADY_APPLIED",
                                                    snapshot_id=12, knowledge_revision=4))
        self.assertEqual(self.h.prepare_calls, [])
        self.assertEqual(self.h.publish_calls, [])
        self.assertNotIn("read_cards", self.h.log)

    async def test_replay_response_as_json_text(self):
        self.h.operation = dict(status="SUCCEEDED", body_hash=self._body_hash(),
                                response='{"knowledge_revision": 4, "snapshot_id": 12}')
        result = await self.h.run()
        self.assertEqual(result, PublishCardsResult(status="ALREADY_APPLIED",
                                                    snapshot_id=12, knowledge_revision=4))

    async def test_same_key_different_body_is_idempotency_conflict(self):
        self.h.operation = dict(status="SUCCEEDED", body_hash="sha256:" + "b" * 64,
                                response={"knowledge_revision": 4, "snapshot_id": 12})
        result = await self.h.run()
        self.assertEqual(result, PublishCardsResult(status="STALE",
                                                    error_code="IDEMPOTENCY_CONFLICT"))
        self.assertEqual(self.h.prepare_calls, [])

    async def test_started_operation_proceeds(self):
        # 앞선 시도가 결과를 못 남겼다 — 이어서 진행한다
        self.h.operation = dict(status="STARTED", body_hash=self._body_hash(), response=None)
        result = await self.h.run()
        self.assertEqual(result.status, "PUBLISHED")

    async def test_manifest_card_excluded_during_prepare_is_stale(self):
        self.h.card_states = [{5: _card(50)},
                              {5: _card(50), 7: _card(70, published=70, status="EXCLUDED")}]
        result = await self.h.run()
        self.assertEqual(result.status, "STALE")
        self.assertEqual(self.h.publish_calls, [])
        self.assertIn("tx_rollback", self._after_prepare())

    async def test_transaction_locks_all_manifest_cards(self):
        await self.h.run()
        self.assertEqual(self.h.read_cards_ids, [[5], [5, 7]])

    # -- final fix: 재발행(changes=[])·낡은 카드 빼기·원문 오류 --------------

    async def test_empty_changes_republishes_current_pointers(self):
        """changes=[] 는 현재 공개 포인터 그대로 재발행한다(final fix #1·#2)."""
        self.h.manifest = {7: 70, 9: 90}
        # 준비 단계 카드 CAS 조회는 없고, tx 에서 manifest 전체만 잠근다
        self.h.card_states = [{7: _card(70, published=70, status="APPROVED"),
                               9: _card(91, published=90, status="APPROVED")}]
        hook = AsyncMock()
        result = await self.h.run(changes=[], hook=hook)
        self.assertEqual(result.status, "PUBLISHED")
        self.assertEqual(self.h.read_cards_ids, [[7, 9]])
        self.assertNotIn("read_cards", self.h.log)
        self.assertEqual(self.h.built_manifest, {7: 70, 9: 90})
        call = self.h.publish_calls[0]
        self.assertEqual(call["card_versions"], [(7, 70), (9, 90)])
        self.assertEqual(call["body_hash"], digest([]))
        # 공개 포인터를 옮기지 않는다 — 검수 사건도 없다
        self.assertFalse(any(e.startswith("mark:") for e in self.h.log))
        self.assertIn("activate:44:12", self.h.log)
        hook.assert_awaited_once()

    async def test_empty_changes_replay_is_already_applied(self):
        self.h.operation = dict(status="SUCCEEDED", body_hash=digest([]),
                                response={"knowledge_revision": 4, "snapshot_id": 12})
        result = await self.h.run(changes=[])
        self.assertEqual(result.status, "ALREADY_APPLIED")
        self.assertEqual(self.h.prepare_calls, [])

    async def test_empty_changes_checks_manifest_excluded_during_prepare(self):
        self.h.card_states = [{7: _card(70, published=70, status="EXCLUDED")}]
        result = await self.h.run(changes=[])
        self.assertEqual(result.status, "STALE")
        self.assertEqual(self.h.publish_calls, [])

    async def test_empty_changes_publishes_empty_manifest_and_index(self):
        self.h.manifest = {}
        self.h.card_states = [{}]
        result = await self.h.run(changes=[])
        self.assertEqual(result.status, "PUBLISHED")
        self.assertEqual(self.h.prepare_calls[0][0].card_ids, ())
        self.assertEqual(self.h.prepare_calls[0][1].cards, ())
        self.assertEqual(self.h.publish_calls[0]['card_versions'], [])
        self.assertIn('activate:44:12', self.h.log)

    async def test_unchanged_card_pointer_moved_during_prepare_is_stale(self):
        # 준비 사이 레거시 경로가 7 의 공개 포인터를 옮겼다 — 옛 버전을 싣지 않는다
        self.h.card_states = [{5: _card(50)},
                              {5: _card(50), 7: _card(71, published=71, status="APPROVED")}]
        result = await self.h.run()
        self.assertEqual(result.status, "STALE")
        self.assertEqual(self.h.publish_calls, [])

    async def test_unchanged_bad_legacy_card_is_dropped_not_blocking(self):
        """변경하지 않는 카드의 어떤 고정·조립 실패도 그 카드만 뺀다(final fix #3)."""
        cases = [
            ("check", InvalidContent("빈 원문")),
            ("check", InvalidContent("블록 상한 초과")),
            ("check", ValueError("버전 없음")),
            ("build", ValueError("블록 없음")),
        ]
        for where, exc in cases:
            with self.subTest(where=where, exc=str(exc)):
                self.h = Harness()
                self.h.start(self)
                target = self.h.check_errors if where == "check" else self.h.build_errors
                target[7] = exc
                with self.assertLogs(MOD, level="WARNING"):
                    result = await self.h.run()
                self.assertEqual(result.status, "PUBLISHED")
                self.assertEqual(self.h.built_manifest, {5: 50})
                self.assertEqual(self.h.publish_calls[0]["card_versions"], [(5, 50)])
                prep = self.h.log[self.h.log.index("read_publication"):]
                fix = [e for e in prep[:prep.index("release")]
                       if not e.startswith("check:")]
                # 7 의 savepoint 만 롤백, 바깥 블록 고정 트랜잭션은 커밋
                self.assertEqual(fix.count("tx_rollback"), 1)
                self.assertEqual(fix[-1], "tx_commit")

    async def test_changed_card_invalid_content_rolls_back_whole_fix(self):
        self.h.check_errors[5] = InvalidContent("빈 원문")
        result = await self.h.run()
        self.assertEqual(result, PublishCardsResult(status="INVALID_CONTENT"))
        self.assertEqual(self.h.prepare_calls, [])
        self.assertNotIn("tx_commit", self.h.log)

    async def test_changed_card_contract_validation_is_invalid_content(self):
        import pydantic
        try:
            RawSpan(raw_span_id="1", source_id="3", text="")
        except pydantic.ValidationError as exc:
            self.h.build_errors[5] = exc
        result = await self.h.run()
        self.assertEqual(result.status, "INVALID_CONTENT")
        self.assertEqual(self.h.prepare_calls, [])

    async def test_changed_card_other_value_error_propagates(self):
        self.h.check_errors[5] = ValueError("카드 버전을 찾을 수 없다")
        with self.assertRaises(ValueError):
            await self.h.run()
        self.assertEqual(self.h.prepare_calls, [])

    async def test_long_idempotency_key_rejected(self):
        with self.assertRaises(ValueError):
            await publish_cards(self.h.pool, store_id=STORE, member_id=2,
                                actor_user_id=3, changes=[CardChange(5, 50, 50)],
                                idempotency_key="k" * 41, usage_context=object())
        self.assertEqual(self.h.log, [])

    async def test_member_id_required(self):
        with self.assertRaises(ValueError):
            await publish_cards(self.h.pool, store_id=STORE, member_id=None,
                                actor_user_id=3, changes=[CardChange(5, 50, 50)],
                                idempotency_key="approve-key-0001",
                                usage_context=object())


class SnapshotHashTest(unittest.TestCase):
    def test_matches_snapshot_digest(self):
        content = _content({5: 50, 12: 120})
        bound = PublishedKnowledgeSnapshot(
            **content.model_dump(), snapshot_id="99", knowledge_revision="4",
            created_at=datetime(2026, 9, 27, tzinfo=timezone.utc),
            snapshot_hash="sha256:" + "0" * 64)
        self.assertEqual(snapshot_hash_for(content, 4), snapshot_digest(bound))


class BuildPrepareRequestTest(unittest.TestCase):
    def test_key_uses_content_hash_prefix_and_time_window(self):
        content = _content({5: 50})
        with patch(f"{MOD}.time.time", return_value=1200.0):
            request = build_prepare_request(
                store_id=STORE, member_id=2, idempotency_key="approve-key-0001",
                content=content, expected_publication_revision=0)
        hex16 = digest(knowledge_content_payload(content)).split(":")[1][:16]
        self.assertEqual(request.idempotency.key, f"approve-key-0001:0:{hex16}:2")


class MarkPublishedTest(unittest.IsolatedAsyncioTestCase):
    async def _mark(self, published):
        conn = AsyncMock()
        with patch(f"{MOD}.card_repo.add_event", new=AsyncMock()) as add_event:
            await approval._mark_published(
                conn, store_id=STORE, actor_user_id=3, change=CardChange(5, 50, 50),
                card=_card(50, published=published))
        sql, *args = conn.execute.await_args.args
        self.assertIn("published_version_id = $3", sql)
        self.assertEqual(args, [STORE, 5, 50])
        return add_event.await_args

    async def test_first_publish_is_approve(self):
        call = await self._mark(None)
        self.assertEqual(call.args[:5][4], "APPROVE")
        self.assertEqual(call.kwargs["to_status"], "APPROVED")

    async def test_republish_edit(self):
        call = await self._mark(40)
        self.assertEqual(call.args[4], "PUBLISH_EDIT")


if __name__ == "__main__":
    unittest.main()
