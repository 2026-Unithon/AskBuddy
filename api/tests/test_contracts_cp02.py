"""CP-02 계약 테스트 — 발행·오류·채팅 DTO 와 canonical hash.

여기서 고정하는 것은 **두 파이프라인이 같은 것을 같은 방식으로 계산한다** 는 사실이다.
hash 규칙이 흔들리면 과거 답변의 재현이 끊기고, 오류 표가 흔들리면 클라이언트가
고칠 수 없는 요청을 영원히 되보낸다.
"""
from __future__ import annotations

import json
import subprocess
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

from pydantic import ValidationError

from app.contracts import (
    ERROR_TABLE,
    POLICY_MESSAGES,
    AnswerPlan,
    ApplyOwnerAnswerResult,
    CardVisibilityRequest,
    ChatResponse,
    Citation,
    ErrorDetail,
    ErrorEnvelope,
    ExtractionEnvelope,
    IdempotencyKey,
    OutboxEvent,
    PrepareIndexResult,
    PublishedKnowledgeSnapshot,
    PublishKnowledgeResult,
    QuestionContext,
    SelectedBlock,
    TrustedScope,
    ValidateAndSaveAnswerRequest,
    canonical_json,
    digest,
    error,
    snapshot_digest,
    snapshot_payload,
    verify_snapshot_hash,
)

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = ROOT / "schema"
HASH = "sha256:" + "a" * 64

sys.path.insert(0, str(ROOT / "scripts"))
from export_contract_schemas import sample_snapshot  # noqa: E402


class CanonicalJsonTest(unittest.TestCase):
    def test_key_order_does_not_change_the_hash(self):
        self.assertEqual(digest({"a": "1", "b": "2"}), digest({"b": "2", "a": "1"}))

    def test_numbers_become_decimal_strings(self):
        self.assertEqual(canonical_json({"n": 1}), b'{"n":"1"}')

    def test_int_and_float_are_not_the_same(self):
        """1 과 1.0 을 같게 만들면 수량 275 와 275.0 의 구분이 사라진다."""
        self.assertNotEqual(digest({"n": 1}), digest({"n": 1.0}))

    def test_nan_rejected(self):
        with self.assertRaises(ValueError):
            canonical_json({"n": float("nan")})

    def test_original_whitespace_survives(self):
        """원문을 정규화하면 같은 내용이 다른 hash 를 낸다 (RV-07)."""
        raw = "  들여쓴 원문\n"
        # JSON 이 줄바꿈을 이스케이프하는 것은 정상이다. 왕복해서 원문이 그대로인지 본다
        self.assertEqual(json.loads(canonical_json({"t": raw}))["t"], raw)
        self.assertNotEqual(digest({"t": raw}), digest({"t": raw.strip()}))

    def test_ids_sort_numerically_not_lexically(self):
        """문자열 정렬이면 "10" 이 "9" 앞에 온다 — 같은 내용이 두 hash 를 갖게 된다."""
        payload = snapshot_payload(sample_snapshot())
        ids = [f["fact_revision_id"] for f in payload["fact_revisions"]]
        self.assertEqual(ids, ["9", "10"])


class SnapshotHashTest(unittest.TestCase):
    def test_hash_matches_content(self):
        verify_snapshot_hash(sample_snapshot())

    def test_volatile_fields_are_excluded(self):
        """내용이 같은 두 발행이 다른 hash 를 가지면 멱등 재시도를 구분할 수 없다."""
        snap = sample_snapshot()
        later = snap.model_copy(update={
            "snapshot_id": "999",
            "created_at": datetime(2030, 1, 1, tzinfo=timezone.utc)})
        self.assertEqual(snapshot_digest(snap), snapshot_digest(later))

    def test_content_change_changes_the_hash(self):
        snap = sample_snapshot()
        other = snap.model_copy(update={"renderer_version": "r2"})
        self.assertNotEqual(snapshot_digest(snap), snapshot_digest(other))

    def test_wrong_hash_is_caught(self):
        snap = sample_snapshot().model_copy(update={"snapshot_hash": HASH})
        with self.assertRaises(ValueError):
            verify_snapshot_hash(snap)

    def test_block_order_is_hashed_not_list_order(self):
        """리스트 순서가 뒤집혀도 order 가 같으면 같은 발행이다."""
        snap = sample_snapshot()
        card = snap.cards[0]
        flipped = card.model_copy(update={"blocks": tuple(reversed(card.blocks))})
        self.assertEqual(snapshot_digest(snap),
                         snapshot_digest(snap.model_copy(update={"cards": (flipped,)})))


class RawSpanTest(unittest.TestCase):
    def test_block_cannot_point_at_a_missing_raw_span(self):
        """싣지 않은 원문 구간을 가리키면 R 이 보여줄 것이 없다."""
        snap = sample_snapshot()
        with self.assertRaises(ValidationError):
            PublishedKnowledgeSnapshot(
                **{**snap.model_dump(), "raw_spans": ()})

    def test_uncited_raw_span_is_rejected(self):
        snap = sample_snapshot()
        card = snap.cards[0]
        typed_only = card.model_copy(update={
            "blocks": tuple(b for b in card.blocks if b.raw_span_id is None)})
        with self.assertRaises(ValidationError):
            PublishedKnowledgeSnapshot(
                **{**snap.model_dump(), "cards": (typed_only.model_dump(),)})


class SchemaVersionTest(unittest.TestCase):
    def test_unknown_schema_version_rejected(self):
        """모르는 version 을 관대하게 받으면 다른 계약의 데이터를 이 계약으로 읽는다."""
        with self.assertRaises(ValidationError):
            ExtractionEnvelope(schema_version="extraction/v2", source_id="1",
                               result_status="NO_RESULT", unresolved=["이유"])

    def test_error_envelope_version_fixed(self):
        with self.assertRaises(ValidationError):
            ErrorEnvelope(contract_version="v1",
                          error=ErrorDetail(code="RATE_LIMITED", message="m",
                                            retryable=True, request_id="r",
                                            retry_after_ms=1))


class ErrorTableTest(unittest.TestCase):
    def test_every_code_has_a_status(self):
        from app.contracts.errors import ErrorCode
        codes = set(ErrorCode.__args__)
        self.assertEqual(codes, set(ERROR_TABLE))

    def test_caller_cannot_declare_semantic_errors_retryable(self):
        """고칠 수 없는 요청을 retryable 로 표시하면 같은 요청이 영원히 돌아온다."""
        with self.assertRaises(ValidationError):
            ErrorDetail(code="INVALID_CONTRACT", message="m", retryable=True,
                        request_id="r")

    def test_rate_limited_must_say_when_to_retry(self):
        with self.assertRaises(ValidationError):
            error("RATE_LIMITED", "잠시 후", request_id="r")
        env = error("RATE_LIMITED", "잠시 후", request_id="r", retry_after_ms=1000)
        self.assertEqual(env.http_status, 429)

    def test_context_expired_is_410_and_not_retryable(self):
        env = error("CONTEXT_EXPIRED", "다시 질문해 주세요", request_id="r")
        self.assertEqual((env.http_status, env.error.retryable), (410, False))

    def test_internal_details_have_no_field_to_live_in(self):
        """타 매장 ID·SQL·모델 원문이 새어 나갈 자리를 아예 두지 않는다 (§5.4)."""
        with self.assertRaises(ValidationError):
            ErrorDetail(code="STORAGE_FAILED", message="m", retryable=True,
                        request_id="r", details="select * from stores")


class PublicationTest(unittest.TestCase):
    def _idem(self):
        return IdempotencyKey(key="abcdefgh", body_hash=HASH)

    def test_prepared_result_carries_everything_needed(self):
        with self.assertRaises(ValidationError):
            PrepareIndexResult(status="PREPARED", prepared_id="1")
        with self.assertRaises(ValidationError):
            PrepareIndexResult(status="FAILED")

    def test_idempotent_replay_still_reports_the_revision(self):
        """어느 판이 됐는지 안 주면 재시도한 쪽이 성공 여부를 모른 채 또 부른다."""
        with self.assertRaises(ValidationError):
            PublishKnowledgeResult(status="ALREADY_APPLIED")
        ok = PublishKnowledgeResult(status="ALREADY_APPLIED", snapshot_id="10",
                                    snapshot_hash=HASH, knowledge_revision="7")
        self.assertEqual(ok.knowledge_revision, "7")

    def test_exclusion_requires_a_reason(self):
        with self.assertRaises(ValidationError):
            CardVisibilityRequest(scope=TrustedScope(store_id="1"),
                                  idempotency=self._idem(), card_id="20",
                                  action="EXCLUDE",
                                  expected_publication_revision="7")

    def test_outbox_event_carries_no_business_content(self):
        """원문을 실으면 권한이 바뀐 뒤에도 옛 내용이 전달된다 (§4.3)."""
        with self.assertRaises(ValidationError):
            OutboxEvent(event_id="1", store_id="1", type="KNOWLEDGE_PUBLISHED",
                        aggregate_id="10", knowledge_revision="7",
                        occurred_at=datetime.now(timezone.utc),
                        answer_text="점주 원문")

    def test_publication_event_needs_a_revision(self):
        with self.assertRaises(ValidationError):
            OutboxEvent(event_id="1", store_id="1", type="CARD_EXCLUDED",
                        aggregate_id="20",
                        occurred_at=datetime.now(timezone.utc))

    def test_published_owner_answer_states_its_revision(self):
        with self.assertRaises(ValidationError):
            ApplyOwnerAnswerResult(status="PUBLISHED")
        self.assertEqual(
            ApplyOwnerAnswerResult(status="LINKED", fact_revision_id="9").status,
            "LINKED")


class ChatResponseTest(unittest.TestCase):
    def _citation(self, **kw):
        base = dict(card_id="20", card_version_id="21", block_id="b1",
                    fact_revision_id="9", source_id="60")
        base.update(kw)
        return Citation(**base)

    def _resp(self, **kw):
        base = dict(request_id="r1", action="ANSWER", message="225ml 입니다",
                    snapshot_id="10", knowledge_revision="7",
                    citations=(self._citation(),))
        base.update(kw)
        return ChatResponse(**base)

    def test_answer_needs_citations(self):
        with self.assertRaises(ValidationError):
            self._resp(citations=())

    def test_citation_points_at_exactly_one_thing(self):
        with self.assertRaises(ValidationError):
            self._citation(raw_span_id="70")
        with self.assertRaises(ValidationError):
            self._citation(fact_revision_id=None)

    def test_deleted_source_is_marked_not_hidden(self):
        """D20 — 자료를 지워도 이미 나간 인용을 끊지 않고 끊김으로 표시한다."""
        resp = self._resp(citations=(self._citation(source_availability="DELETED"),))
        self.assertEqual(len(resp.broken_citations()), 1)

    def test_citation_count_is_rows_not_facts(self):
        """사실 개수로 부풀리지 않는다 (§5.2)."""
        resp = self._resp(citations=(self._citation(),
                                     self._citation(block_id="b2",
                                                    fact_revision_id="10")))
        self.assertEqual(resp.citation_count(), 2)

    def test_policy_actions_use_the_fixed_wording(self):
        """모델이 안전·개인정보 판단 문장을 만들지 않는다 (§5.4)."""
        for action, text in POLICY_MESSAGES.items():
            with self.assertRaises(ValidationError):
                self._resp(action=action, message="제가 판단하기에 괜찮아 보여요",
                           citations=())
            ok = self._resp(action=action, message=text, citations=())
            self.assertEqual(ok.message, text)

    def test_escalate_response_requires_a_saved_pending(self):
        """불변식 5 — WAITING 저장에 성공한 뒤에만 넘김 응답을 만든다."""
        with self.assertRaises(ValidationError):
            self._resp(action="ESCALATE", message="사장님께 여쭤볼게요", citations=())
        ok = self._resp(action="ESCALATE", message="사장님께 여쭤볼게요",
                        citations=(), pending_id="80")
        self.assertEqual(ok.pending_id, "80")

    def test_clarify_does_not_create_a_pending(self):
        with self.assertRaises(ValidationError):
            self._resp(action="CLARIFY", message="HOT 인가요 ICE 인가요?",
                       citations=(), context_id="00000000-0000-4000-8000-000000000001", clarification_slot="t",
                       allowed_options=("HOT", "ICE"), pending_id="80")


class QuestionContextTest(unittest.TestCase):
    def _ctx(self, **kw):
        base = dict(context_id="00000000-0000-4000-8000-000000000001", store_id="1", member_id="2",
                    chat_session_id="3", contract_version="v2",
                    expires_at=datetime.now(timezone.utc),
                    original_question="우유 얼마나 넣어요?")
        base.update(kw)
        return QuestionContext(**base)

    def test_confirmed_and_proposed_slots_stay_apart(self):
        """섞이면 모델의 짐작이 다음 턴에 '사용자가 확정한 값' 으로 굳는다."""
        with self.assertRaises(ValidationError):
            self._ctx(confirmed_slots={"temperature": "ICE"},
                      proposed_slots={"temperature": "HOT"})

    def test_clarify_turns_are_capped(self):
        """두 턴 되물어도 불명확하면 넘긴다. 무한히 되묻지 않는다 (§5.1)."""
        with self.assertRaises(ValidationError):
            self._ctx(clarify_turns=3)


class ValidateAndSaveTest(unittest.TestCase):
    def test_plan_must_match_the_expected_revision(self):
        """검증과 저장 사이에 판이 바뀌면 다른 지식으로 답한 것이 저장된다 (§4.2)."""
        plan = AnswerPlan(snapshot_id="10", knowledge_revision="7", action="ANSWER",
                          selected_blocks=(SelectedBlock(
                              card_id="20", card_version_id="21", block_id="b1",
                              fact_revision_ids=("9",)),))
        with self.assertRaises(ValidationError):
            ValidateAndSaveAnswerRequest(
                store_id="1", member_id="2", chat_session_id="3", request_id="r",
                expected_snapshot_id="10", expected_knowledge_revision="8",
                plan=plan)


class SchemaExportTest(unittest.TestCase):
    def test_export_is_current(self):
        """계약을 고치고 export 를 안 내보내면 W·R 이 다른 것을 보고 있게 된다."""
        result = subprocess.run(
            [sys.executable, "scripts/export_contract_schemas.py", "--check"],
            cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_test_vectors_match_the_code(self):
        vectors = json.loads((SCHEMA_DIR / "_test_vectors.json").read_text("utf-8"))
        self.assertEqual(vectors["empty_object"], digest({}))
        self.assertEqual(vectors["snapshot_hash"], sample_snapshot().snapshot_hash)
        self.assertEqual(vectors["bigint_id_keeps_precision"],
                         digest({"id": "9007199254740993"}))

    def test_schema_roundtrips_through_json(self):
        """직렬화하고 다시 읽어도 같은 값이어야 W 산출물을 R 이 그대로 쓴다."""
        snap = sample_snapshot()
        again = PublishedKnowledgeSnapshot.model_validate_json(
            snap.model_dump_json())
        self.assertEqual(again, snap)
        self.assertEqual(snapshot_digest(again), snap.snapshot_hash)


if __name__ == "__main__":
    unittest.main()
