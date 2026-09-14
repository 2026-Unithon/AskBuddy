"""CP-03 — 공유 fixture 로 생산자와 소비자가 각자 통과하는지 본다 (§9).

소비자는 **파일에서 읽는다.** 생산자가 만든 파이썬 객체를 그대로 받으면 둘이 같은
착각을 공유해도 드러나지 않는다. 그래서 JSON 을 거쳐 온다.

manifest 의 기대 행동은 결과를 보고 고치지 않는다. 먼저 적어 둔 것을 그대로 쓴다.
"""
from __future__ import annotations

import asyncio
import json
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pydantic import ValidationError

from app.contracts import (
    AnswerPlan,
    AnswerPlanViolation,
    CardVisibilityRequest,
    ExtractionEnvelope,
    IdempotencyKey,
    OccurrenceDisposition,
    OutboxEvent,
    PrepareIndexRequest,
    PublishedKnowledgeSnapshot,
    PublishKnowledgeRequest,
    PublishKnowledgeResult,
    QuestionContext,
    SelectedBlock,
    TrustedScope,
    error,
    verify_snapshot_hash,
)
from app.fakes import FakeIndexer, FakeOutbox, FakeRenderer, RenderError

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "contracts" / "v1"
BLOCK_OF = {"900": "b1", "901": "b1", "902": "b1", "903": "b2", "904": "b2",
            "905": "b3", "906": "b3", "907": "b3"}
HASH = "sha256:" + "a" * 64


def load(name: str):
    return json.loads((FIXTURES / f"{name}.json").read_text("utf-8"))


def snapshot(name: str = "snapshot") -> PublishedKnowledgeSnapshot:
    return PublishedKnowledgeSnapshot.model_validate(load(name))


MANIFEST = load("manifest")
CASES = {c["id"]: c for c in MANIFEST["cases"]}


def plan(*fact_ids: str, action="ANSWER", revision="7", snapshot_id="100", **kw):
    blocks: dict[str, list[str]] = {}
    for fid in fact_ids:
        blocks.setdefault(BLOCK_OF[fid], []).append(fid)
    selected = tuple(
        SelectedBlock(card_id="200", card_version_id="210", block_id=block,
                      fact_revision_ids=tuple(ids))
        for block, ids in blocks.items())
    return AnswerPlan(snapshot_id=snapshot_id, knowledge_revision=revision,
                      action=action, selected_blocks=selected, **kw)


def raw_plan(**kw):
    return AnswerPlan(snapshot_id="100", knowledge_revision="7", action="ANSWER",
                      selected_blocks=(SelectedBlock(
                          card_id="200", card_version_id="210", block_id="b4",
                          raw_span_id="700"),), **kw)


class FixtureIntegrityTest(unittest.TestCase):
    def test_fixture_matches_the_code(self):
        import subprocess
        import sys
        result = subprocess.run(
            [sys.executable, "scripts/build_contract_fixtures.py", "--check"],
            cwd=FIXTURES.parents[3], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_snapshot_hash_survives_the_file(self):
        """파일을 거쳐도 hash 가 맞아야 W 산출물을 R 이 그대로 쓴다."""
        verify_snapshot_hash(snapshot())

    def test_no_real_store_names(self):
        """실제 상호·메뉴 고유명을 fixture 에 넣지 않는다."""
        text = (FIXTURES / "snapshot.json").read_text("utf-8")
        self.assertIn("음료 A", text)


class AnswerCaseTest(unittest.TestCase):
    """F01~F09 — 승인 지식으로 답하는 경로."""

    def setUp(self):
        self.snap = snapshot()
        self.renderer = FakeRenderer()

    def _render(self, p, **kw):
        return self.renderer.render(p, self.snap, store_id="1",
                                    request_id="r1", **kw)

    def _check(self, case_id: str, p, **kw):
        case = CASES[case_id]
        resp = self._render(p, **kw)
        self.assertEqual(resp.action, case["action"], case_id)
        cited = {c.fact_revision_id for c in resp.citations}
        for fid in case.get("must_cite", []):
            self.assertIn(fid, cited, f"{case_id} 는 {fid} 를 인용해야 한다")
        for fid in case.get("must_not_cite", []):
            self.assertNotIn(fid, cited, f"{case_id} 는 {fid} 를 인용하면 안 된다")
        for text in case.get("must_contain", []):
            self.assertIn(text, resp.message, case_id)
        return resp

    def test_F02_variant_is_cited_alone(self):
        self._check("F02", plan("900"))

    def test_F03_size_difference(self):
        self._check("F03", plan("902"))

    def test_F04_conditions_survive_rendering(self):
        """조건을 떼면 "225ml" 만 남아 다른 규격에 그대로 적용된다."""
        self._check("F04", plan("900"))

    def test_F05_negation_is_not_flattened(self):
        resp = self._check("F05", plan("903"))
        self.assertIn("않는다", resp.message)

    def test_F06_exception_is_shown(self):
        self._check("F06", plan("904"))

    def test_F07_steps_keep_their_order(self):
        resp = self._check("F07", plan("905", "906", "907"))
        lines = resp.message.split("\n")
        self.assertEqual([l[:2] for l in lines], ["기기", "세척", "10"])

    def test_F08_prerequisite_must_be_cited(self):
        """선행 사실을 빼면 전원을 켠 채 세척제를 넣게 된다."""
        with self.assertRaises(AnswerPlanViolation):
            self._render(plan("906"))
        self._check("F08", plan("905", "906"))

    def test_F09_legacy_raw_is_shown_as_approved(self):
        resp = self._render(raw_plan())
        self.assertEqual(resp.citations[0].raw_span_id, "700")
        self.assertIsNone(resp.citations[0].fact_revision_id)

    def test_F01_F10_F11_clarify_instead_of_guessing(self):
        """규격이 둘인데 하나를 고르면 절반은 틀린다."""
        for case_id in ("F01", "F10", "F11"):
            case = CASES[case_id]
            p = AnswerPlan(snapshot_id="100", knowledge_revision="7",
                           action="CLARIFY",
                           clarification_slot=case["clarification_slot"],
                           allowed_options=tuple(case.get("allowed_options",
                                                          ["A", "B"])),
                           context_id="00000000-0000-4000-8000-000000000001")
            resp = self._render(p)
            self.assertEqual(resp.action, "CLARIFY")
            self.assertIsNone(resp.pending_id, "되묻기는 점주를 부르지 않는다")

    def test_F12_F13_escalate_after_pending_is_saved(self):
        for case_id in ("F12", "F13", "F25"):
            p = AnswerPlan(snapshot_id="100", knowledge_revision="7",
                           action="ESCALATE", escalation_reason="근거 없음")
            resp = self._render(p, pending_id="800")
            self.assertEqual(resp.action, "ESCALATE", case_id)
            self.assertEqual(resp.pending_id, "800")

    def test_F25_injection_does_not_widen_the_scope(self):
        """지시문은 질문일 뿐이다. 승인 범위를 넓히지 않는다."""
        stolen = AnswerPlan(snapshot_id="100", knowledge_revision="7",
                            action="ANSWER", selected_blocks=(SelectedBlock(
                                card_id="999", card_version_id="999",
                                block_id="b1", fact_revision_ids=("900",)),))
        with self.assertRaises(AnswerPlanViolation):
            self._render(stolen)


class ScopeCaseTest(unittest.TestCase):
    """F14~F20 — 범위 밖 참조는 모양이 맞아도 거절된다."""

    def setUp(self):
        self.snap = snapshot()
        self.renderer = FakeRenderer()

    def test_F14_other_store_snapshot(self):
        other = snapshot("snapshot_other_store")
        with self.assertRaises(AnswerPlanViolation):
            self.renderer.render(plan("900"), other, store_id="1",
                                 request_id="r")

    def test_F15_draft_card_is_not_in_the_snapshot(self):
        p = plan("900").model_copy(update={"selected_blocks": (SelectedBlock(
            card_id="201", card_version_id="210", block_id="b1",
            fact_revision_ids=("900",)),)})
        with self.assertRaises(AnswerPlanViolation):
            self.renderer.render(p, self.snap, store_id="1", request_id="r")

    def test_F16_excluded_card_disappears_from_the_next_snapshot(self):
        """제외하면 판 번호가 오르고 그 카드는 더 이상 실리지 않는다."""
        indexer = FakeIndexer()
        result = asyncio.run(indexer.set_visibility(CardVisibilityRequest(
            scope=TrustedScope(store_id="1"),
            idempotency=IdempotencyKey(key="exclude-1", body_hash=HASH),
            card_id="200", action="EXCLUDE",
            expected_publication_revision="0", reason="내용이 바뀌었어요")))
        self.assertEqual(result.status, "PUBLISHED")
        self.assertEqual(indexer.store("1").excluded_cards, {"200"})
        self.assertEqual(result.knowledge_revision, "1")

    def test_F17_past_card_version(self):
        p = plan("900").model_copy(update={"selected_blocks": (SelectedBlock(
            card_id="200", card_version_id="209", block_id="b1",
            fact_revision_ids=("900",)),)})
        with self.assertRaises(AnswerPlanViolation):
            self.renderer.render(p, self.snap, store_id="1", request_id="r")

    def test_F18_stale_cache_revision(self):
        with self.assertRaises(AnswerPlanViolation):
            self.renderer.render(plan("900", revision="6"), self.snap,
                                 store_id="1", request_id="r")
        self.assertEqual(error("STALE_KNOWLEDGE", "다시 시도할게요",
                               request_id="r").http_status, 409)

    def test_F19_fact_outside_the_cited_block(self):
        p = plan("900").model_copy(update={"selected_blocks": (SelectedBlock(
            card_id="200", card_version_id="210", block_id="b1",
            fact_revision_ids=("903",)),)})
        with self.assertRaises(AnswerPlanViolation):
            self.renderer.render(p, self.snap, store_id="1", request_id="r")

    def test_F20_unsupported_schema_version(self):
        raw = load("snapshot")
        raw["schema_version"] = "published_knowledge/v2"
        with self.assertRaises(ValidationError):
            PublishedKnowledgeSnapshot.model_validate(raw)
        self.assertEqual(error("UNSUPPORTED_SCHEMA", "지원하지 않는 형식이에요",
                               request_id="r").http_status, 422)


class OutboxAndErrorTest(unittest.TestCase):
    """F21~F24 — 전달과 장애."""

    def _event(self, event_id: str, revision: str, store_id="1"):
        return OutboxEvent(event_id=event_id, store_id=store_id,
                           type="KNOWLEDGE_PUBLISHED", aggregate_id="100",
                           knowledge_revision=revision,
                           occurred_at=datetime.now(UTC))

    def test_F21_duplicate_out_of_order_and_gap(self):
        box = FakeOutbox()
        self.assertEqual(box.deliver(self._event("1", "1")), "APPLIED")
        self.assertEqual(box.deliver(self._event("1", "1")), "DUPLICATE")
        self.assertEqual(box.deliver(self._event("2", "2")), "APPLIED")
        # 늦게 온 옛 판을 반영하면 점주가 고친 값이 되살아난다
        self.assertEqual(box.deliver(self._event("3", "1")), "STALE")
        # 중간이 비면 조용히 넘어가지 않고 재동기화를 표시한다
        self.assertEqual(box.deliver(self._event("4", "9")), "RESYNC")
        self.assertIn("1", box.resync_needed)
        self.assertEqual(box.applied["1"], 9)

    def test_F22_model_failure_is_not_a_knowledge_gap(self):
        """장애를 지식 부족으로 만들면 점주에게 쓸데없는 알림이 쌓인다."""
        env = error("MODEL_UNAVAILABLE", "잠시 뒤 다시 시도해 주세요", request_id="r")
        self.assertEqual(env.http_status, 503)
        self.assertTrue(env.error.retryable)

    def test_F23_escalate_response_needs_a_saved_pending(self):
        p = AnswerPlan(snapshot_id="100", knowledge_revision="7",
                       action="ESCALATE", escalation_reason="근거 없음")
        with self.assertRaises(RenderError):
            FakeRenderer().render(p, snapshot(), store_id="1", request_id="r")

    def test_F24_owner_answer_event_is_deduplicated(self):
        box = FakeOutbox(consumer="staff-notify")
        event = OutboxEvent(event_id="9", store_id="1",
                            type="OWNER_ANSWER_SUBMITTED", aggregate_id="80",
                            owner_answer_id="80",
                            occurred_at=datetime.now(UTC))
        self.assertEqual(box.deliver(event), "APPLIED")
        self.assertEqual(box.deliver(event), "DUPLICATE")


class StateCaseTest(unittest.TestCase):
    """F26~F31 — 상태와 경합."""

    def test_F26_deleted_source_is_marked_not_hidden(self):
        """D20 — 자료를 지워도 답은 남고 인용에 끊김을 표시한다."""
        resp = FakeRenderer().render(plan("900"), snapshot(), store_id="1",
                                     request_id="r",
                                     availability={"600": "DELETED"})
        self.assertEqual(len(resp.broken_citations()), 1)
        self.assertEqual(resp.citations[0].source_availability, "DELETED")

    def test_F27_mixed_variants_render_only_what_was_chosen(self):
        resp = FakeRenderer().render(plan("900", "901"), snapshot(),
                                     store_id="1", request_id="r")
        self.assertEqual(resp.citation_count(), 2)
        self.assertIn("225", resp.message)
        self.assertIn("275", resp.message)

    def test_F28_duplicate_id_and_cycle_are_rejected(self):
        raw = load("snapshot")
        raw["fact_revisions"].append(raw["fact_revisions"][0])
        with self.assertRaises(ValidationError):
            PublishedKnowledgeSnapshot.model_validate(raw)

        cyclic = load("snapshot")
        by_id = {f["fact_revision_id"]: f for f in cyclic["fact_revisions"]}
        by_id["905"]["requires"] = ["907"]
        with self.assertRaises(ValidationError):
            PublishedKnowledgeSnapshot.model_validate(cyclic)

    def test_F29_context_ttl_and_session_ownership(self):
        ctx = QuestionContext(
            context_id="00000000-0000-4000-8000-000000000001", store_id="1", member_id="2",
            chat_session_id="3", contract_version="v2",
            expires_at=datetime.now(UTC) - timedelta(minutes=1),
            original_question="얼마나 넣어요?")
        self.assertLess(ctx.expires_at, datetime.now(UTC))
        env = error("CONTEXT_EXPIRED", "다시 질문해 주세요", request_id="r")
        self.assertEqual((env.http_status, env.error.retryable), (410, False))

    def test_F30_publish_is_compare_and_set(self):
        """예상 판이 어긋나면 STALE 이다. 마지막 쓰기가 이기지 않는다."""
        indexer = FakeIndexer()
        scope = TrustedScope(store_id="1")
        prep = asyncio.run(indexer.prepare_index(PrepareIndexRequest(
            scope=scope, idempotency=IdempotencyKey(key="prep-0001",
                                                    body_hash=HASH),
            card_ids=("200",), content_hash=HASH,
            expected_publication_revision="0", embedding_model="m",
            glossary_version="g", renderer_version="r")))
        self.assertEqual(prep.status, "PREPARED")

        def publish(key, expected):
            return asyncio.run(indexer.publish(PublishKnowledgeRequest(
                scope=scope, idempotency=IdempotencyKey(key=key,
                                                        body_hash=HASH),
                prepared_id=prep.prepared_id,
                expected_publication_revision=expected,
                approved_by="2", approved_at=datetime.now(UTC))))

        first = publish("pub-0001", "0")
        self.assertEqual(first.status, "PUBLISHED")
        # 다른 쪽이 옛 판 번호로 들어오면 덮어쓰지 못한다
        self.assertEqual(publish("pub-0002", "0").status, "STALE")
        # 같은 키 재시도는 판을 올리지 않는다
        replay = publish("pub-0001", "0")
        self.assertEqual(replay.status, "ALREADY_APPLIED")
        self.assertEqual(replay.knowledge_revision, first.knowledge_revision)
        self.assertEqual(indexer.store("1").knowledge_revision, 1)

    def test_F30_same_key_different_body_conflicts(self):
        indexer = FakeIndexer()
        scope = TrustedScope(store_id="1")

        def prepare(body_hash):
            return asyncio.run(indexer.prepare_index(PrepareIndexRequest(
                scope=scope,
                idempotency=IdempotencyKey(key="prep-0001", body_hash=body_hash),
                card_ids=("200",), content_hash=body_hash,
                expected_publication_revision="0", embedding_model="m",
                glossary_version="g", renderer_version="r")))

        self.assertEqual(prepare(HASH).status, "PREPARED")
        clash = prepare("sha256:" + "b" * 64)
        self.assertEqual(clash.error.code, "IDEMPOTENCY_CONFLICT")

    def test_F31_contract_version_combinations(self):
        """v1 소비자가 v2 를 조용히 읽지 않는다."""
        raw = load("snapshot")
        for version in ("published_knowledge/v0", "published_knowledge/v2", ""):
            with self.assertRaises(ValidationError):
                PublishedKnowledgeSnapshot.model_validate(
                    {**raw, "schema_version": version})
        self.assertEqual(PublishedKnowledgeSnapshot.model_validate(raw)
                         .schema_version, "published_knowledge/v1")


class DetailCaseTest(unittest.TestCase):
    """F32~F35 — 세부 보존."""

    def test_F32_raw_whitespace_survives_the_file(self):
        """파일을 거치면서 원문 공백이 사라지면 들여쓰기가 뜻하는 순서가 죽는다."""
        span = snapshot().raw_spans[0]
        self.assertEqual(span.text, "  마감 전 점검표\n  1) 냉장고 온도 확인\n")

    def test_F33_disposition_is_per_occurrence(self):
        one = OccurrenceDisposition(occurrence_id="5900", fact_revision_id="900",
                                    disposition="LINKED", card_id="200",
                                    block_id="b1")
        two = OccurrenceDisposition(occurrence_id="5901", fact_revision_id="900",
                                    disposition="EXCLUDED", reason="같은 내용 반복")
        self.assertEqual({one.occurrence_id, two.occurrence_id}, {"5900", "5901"})

    def test_F34_unobserved_cost_is_not_zero(self):
        """결측을 0 으로 합산하면 총액이 사실보다 싸 보인다."""
        from app.contracts.usage import UsageAttempt, UsageContext
        from app.usage.pricing import summarize

        def attempt(no, **kw):
            return UsageAttempt(
                context=UsageContext(store_id="1", cost_phase="OPERATING",
                                     stage="ANSWER", logical_call_id="c1",
                                     attempt_no=no),
                status="SUCCEEDED", requested_model="m",
                started_at=datetime.now(UTC), finished_at=datetime.now(UTC),
                **kw)

        rows = [attempt(1, usage_status="COMPLETE",
                        usage={"prompt_tokens": 10, "completion_tokens": 5}),
                attempt(2, usage_status="UNKNOWN",
                        missing_reason="공급자가 usage 를 보고하지 않았다")]
        result = summarize(rows)
        self.assertIsNone(result["total_cost_usd"])
        self.assertLess(result["observation_rate"], 1.0)

    def test_F35_citations_are_rechecked_at_read_time(self):
        """지금 권한·자료 상태를 덧입힌다. 과거 snapshot 을 고치지 않는다."""
        snap = snapshot()
        before = FakeRenderer().render(plan("900"), snap, store_id="1",
                                       request_id="r")
        after = FakeRenderer().render(plan("900"), snap, store_id="1",
                                      request_id="r",
                                      availability={"600": "UNAVAILABLE"})
        self.assertEqual(before.citations[0].source_availability, "AVAILABLE")
        self.assertEqual(after.citations[0].source_availability, "UNAVAILABLE")
        self.assertEqual(snap.snapshot_hash, snapshot().snapshot_hash)


class ActionCoverageTest(unittest.TestCase):
    def test_all_five_actions_and_error_are_covered(self):
        """다섯 action 과 ERROR 를 전부 낸다 (§9 인수 기준)."""
        renderer, snap = FakeRenderer(), snapshot()
        seen = set()
        seen.add(renderer.render(plan("900"), snap, store_id="1",
                                 request_id="r").action)
        seen.add(renderer.render(
            AnswerPlan(snapshot_id="100", knowledge_revision="7",
                       action="CLARIFY", clarification_slot="temperature",
                       allowed_options=("HOT", "ICE"), context_id="00000000-0000-4000-8000-000000000001"),
            snap, store_id="1", request_id="r").action)
        seen.add(renderer.render(
            AnswerPlan(snapshot_id="100", knowledge_revision="7",
                       action="ESCALATE", escalation_reason="근거 없음"),
            snap, store_id="1", request_id="r", pending_id="800").action)
        for action in ("REFUSE", "SAFE_ROUTE"):
            seen.add(renderer.render(
                AnswerPlan(snapshot_id="100", knowledge_revision="7",
                           action=action),
                snap, store_id="1", request_id="r").action)
        self.assertEqual(seen, {"ANSWER", "CLARIFY", "ESCALATE", "REFUSE",
                                "SAFE_ROUTE"})
        # ERROR 는 action 이 아니라 별도 봉투다 (§5.4)
        self.assertEqual(error("MODEL_UNAVAILABLE", "m", request_id="r")
                         .contract_version, "v2")

    def test_every_manifest_case_has_a_test(self):
        """fixture 만 늘리고 검사를 안 붙이면 목록이 통과의 증거처럼 보인다."""
        module = Path(__file__).read_text("utf-8")
        missing = [cid for cid in CASES if f"_{cid}_" not in module]
        self.assertEqual(missing, [], f"검사 없는 fixture: {missing}")
        self.assertEqual(len(CASES), 35)


if __name__ == "__main__":
    unittest.main()
