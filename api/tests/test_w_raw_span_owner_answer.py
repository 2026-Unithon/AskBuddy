"""RawSpan 이 자료 출처뿐 아니라 점주 답변 출처도 가질 수 있는지 고정한다 (W 2026-09-27).

둘 중 정확히 하나만 있어야 한다 — 둘 다 있으면 어느 쪽이 진짜 출처인지 알 수 없고,
둘 다 없으면 R 이 인용 끊김·삭제 대상 판정을 할 근거가 없다.

기존 snapshot fixture 의 hash 가 이 변경으로 흔들리면 안 된다. hash 가 바뀐다는 것은
과거에 발행된 답변의 재현이 끊긴다는 뜻이다.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from pydantic import ValidationError

from app.config import get_settings
from app.contracts.hashing import knowledge_content_payload, verify_snapshot_hash
from app.contracts.snapshot import PublishedKnowledgeSnapshot, RawSpan

FIXTURE = (Path(__file__).resolve().parent
           / "fixtures" / "contracts" / "v1" / "snapshot.json")


class TestRawSpanOwnerAnswerOrigin(unittest.TestCase):
    def test_source_only_span_is_valid(self):
        span = RawSpan(raw_span_id="1", source_id="2", text="a")
        self.assertEqual(span.source_id, "2")
        self.assertIsNone(span.owner_answer_id)

    def test_owner_answer_only_span_is_valid(self):
        span = RawSpan(raw_span_id="1", owner_answer_id="9", text="a")
        self.assertEqual(span.owner_answer_id, "9")
        self.assertIsNone(span.source_id)

    def test_both_origins_is_rejected(self):
        with self.assertRaises(ValidationError):
            RawSpan(raw_span_id="1", source_id="2", owner_answer_id="9", text="a")

    def test_neither_origin_is_rejected(self):
        with self.assertRaises(ValidationError):
            RawSpan(raw_span_id="1", text="a")

    def test_existing_snapshot_hash_still_verifies(self):
        raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
        snapshot = PublishedKnowledgeSnapshot(**raw)
        verify_snapshot_hash(snapshot)  # 예외 없으면 통과

    def test_source_span_payload_keys_are_unchanged(self):
        span = RawSpan(raw_span_id="70", source_id="60", text="승인된 원문 그대로")
        snapshot = _snapshot_with_span(span)
        payload = knowledge_content_payload(snapshot)
        self.assertEqual(len(payload["raw_spans"]), 1)
        item = payload["raw_spans"][0]
        self.assertEqual(set(item.keys()), {"raw_span_id", "source_id", "text", "locator"})

    def test_owner_answer_span_payload_adds_key(self):
        span = RawSpan(raw_span_id="70", owner_answer_id="60", text="점주 답변 원문")
        snapshot = _snapshot_with_span(span)
        payload = knowledge_content_payload(snapshot)
        item = payload["raw_spans"][0]
        self.assertEqual(
            set(item.keys()),
            {"raw_span_id", "source_id", "text", "locator", "owner_answer_id"})
        self.assertIsNone(item["source_id"])
        self.assertEqual(item["owner_answer_id"], "60")

    def test_settings_default_is_off(self):
        self.assertFalse(get_settings().w_owner_answer_raw_publish)


def _snapshot_with_span(span: RawSpan) -> PublishedKnowledgeSnapshot:
    """raw_spans 만 뽑아 hashing 을 검사할 최소 snapshot 을 만든다.

    RawSpan 은 어느 카드도 인용하지 않으면 orphan 검사에 걸리므로, 이 테스트는
    snapshot 전체 유효성이 아니라 payload 직렬화만 본다 — 검증을 우회하려면
    필드를 직접 채운 얕은 객체로 충분하다.
    """
    class _Bare:
        store_id = "1"
        glossary_version = "glossary/v1"
        renderer_version = "fake-renderer/v1"
        cards: tuple = ()
        fact_revisions: tuple = ()
        raw_spans = (span,)

    return _Bare()


if __name__ == "__main__":
    unittest.main()
