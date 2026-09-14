"""C0 계획 검토용 순수 계약 반례. DB·네트워크·실자료를 사용하지 않는다.

api 디렉터리에서 python -B scripts/audit_c0_contracts.py 로 실행한다.
GAP은 목표 계약의 미구현을 뜻한다. 종료 1은 발견된 GAP, 종료 2는 실행 오류다.
스키마가 참조를 받는 것과 실제 승인/권한 검증은 별도라는 점을 확인한다.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pydantic import ValidationError

from app.contracts import (
    AnswerPlan, Assertion, CardBlock, ExtractionEnvelope, FactRevision,
    PublishedCard, PublishedKnowledgeSnapshot, SelectedBlock,
)


def snapshot(**changes):
    data = dict(
        store_id="1", knowledge_revision=1, snapshot_id="10",
        snapshot_hash="a" * 64, created_at=datetime(2026, 9, 14, tzinfo=timezone.utc),
        glossary_version="g1", renderer_version="r1",
        cards=[PublishedCard(
            card_id="20", card_version_id="21", entity_id="30", title="합성 음료",
            blocks=[CardBlock(block_id="b1", kind="NOTES", fact_revision_ids=["40"])],
        )],
        fact_revisions=[FactRevision(fact_revision_id="40", assertion="합성 사실")],
    )
    data.update(changes)
    return PublishedKnowledgeSnapshot(**data)


def duplicate_facts():
    return snapshot(fact_revisions=[
        FactRevision(fact_revision_id="40", assertion="첫 주장"),
        FactRevision(fact_revision_id="40", assertion="다른 주장"),
    ])


def duplicate_cards():
    card = snapshot().cards[0]
    return snapshot(cards=[card, card])


def duplicate_blocks():
    card = snapshot().cards[0].model_dump()
    card["blocks"] *= 2
    return snapshot(cards=[card])


def orphan_fact():
    return snapshot(fact_revisions=[
        FactRevision(fact_revision_id="40", assertion="공개 블록에 있는 사실"),
        FactRevision(fact_revision_id="41", assertion="공개 블록에 없는 사실"),
    ])


def self_dependency():
    return snapshot(fact_revisions=[
        FactRevision(fact_revision_id="40", assertion="자신을 선행으로 참조", requires=["40"]),
    ])


def missing_snapshot_fact():
    return snapshot(fact_revisions=[])


def missing_prerequisite():
    return snapshot(fact_revisions=[
        FactRevision(fact_revision_id="40", assertion="선행 필요", requires=["99"]),
    ])


def mixed_answer():
    return AnswerPlan(
        snapshot_id="10", knowledge_revision=1, action="ESCALATE",
        escalation_reason="근거 부족", clarification_slot="temperature",
        allowed_options=["HOT", "ICE"], context_id="ctx",
    )


def arbitrary_answer_references():
    return AnswerPlan(
        snapshot_id="999", knowledge_revision=999, action="ANSWER",
        selected_blocks=[SelectedBlock(
            card_id="888", card_version_id="777", block_id="absent",
            fact_revision_ids=["666"],
        )],
    )


def lost_original_whitespace():
    raw = "  승인된 원문\n"
    return Assertion(local_ref="a", original_assertion=raw).original_assertion != raw


def mutable_snapshot():
    value = snapshot()
    value.fact_revisions[0].assertion = "수정된 주장"
    value.cards[0].blocks[0].fact_revision_ids.append("999")
    return value.fact_revisions[0].assertion == "수정된 주장" and "999" in value.cards[0].blocks[0].fact_revision_ids


def raw_without_invented_fact():
    return CardBlock(block_id="raw", kind="RAW", fact_revision_ids=[])


def occurrence_identity_missing():
    from app.contracts import OccurrenceDisposition
    return "occurrence_id" not in OccurrenceDisposition.model_fields and "evidence_occurrence_id" not in OccurrenceDisposition.model_fields


def required_projection_fields_missing():
    fields = FactRevision.model_fields
    return "entity_id" not in fields and "order" not in fields and "provenance" not in PublishedKnowledgeSnapshot.model_fields


def incomplete_extraction():
    return ExtractionEnvelope(source_id="untrusted-model-id")


def run():
    # expectation: REJECT=목표상 거절, ACCEPT=목표상 표현 가능, FALSE=현재 결함이 없어야 함
    cases = [
        ("CONTROL_VALID", "ACCEPT", snapshot),
        ("CONTROL_MISSING_FACT", "REJECT", missing_snapshot_fact),
        ("CONTROL_MISSING_DEPENDENCY", "REJECT", missing_prerequisite),
        ("DUPLICATE_FACT_ID", "REJECT", duplicate_facts),
        ("DUPLICATE_CARD_ID", "REJECT", duplicate_cards),
        ("DUPLICATE_BLOCK_ID", "REJECT", duplicate_blocks),
        ("ORPHAN_PUBLIC_FACT", "REJECT", orphan_fact),
        ("SELF_DEPENDENCY", "REJECT", self_dependency),
        ("HASH_NOT_VERIFIED", "REJECT", lambda: snapshot(snapshot_hash="not-a-sha256")),
        ("NAIVE_TIME", "REJECT", lambda: snapshot(created_at=datetime(2026, 9, 14))),
        ("BIGINT_OVERFLOW", "REJECT", lambda: snapshot(store_id="99999999999999999999")),
        ("ACTION_FIELDS_MIXED", "REJECT", mixed_answer),
        ("ARBITRARY_ANSWER_IDS_SCHEMA_ONLY", "REJECT", arbitrary_answer_references),
        ("ORIGINAL_WHITESPACE_CHANGED", "FALSE", lost_original_whitespace),
        ("SNAPSHOT_MUTABLE", "FALSE", mutable_snapshot),
        ("LEGACY_RAW_NOT_REPRESENTABLE", "ACCEPT", raw_without_invented_fact),
        ("OCCURRENCE_KEY_MISSING", "FALSE", occurrence_identity_missing),
        ("ENTITY_ORDER_PROVENANCE_MISSING", "FALSE", required_projection_fields_missing),
        ("EXTRACTION_CONTEXT_RESULT_MISSING", "REJECT", incomplete_extraction),
    ]
    rows = []
    for case_id, expectation, fn in cases:
        try:
            value = fn()
            gap = bool(value) if expectation == "FALSE" else expectation == "REJECT"
            observed = "TRUE" if expectation == "FALSE" and value else "ACCEPTED"
            rows.append(dict(case_id=case_id, result="GAP" if gap else "PASS", observed=observed))
        except ValidationError:
            rows.append(dict(case_id=case_id, result="PASS" if expectation == "REJECT" else "GAP", observed="REJECTED"))
        except Exception as exc:
            rows.append(dict(case_id=case_id, result="ERROR", error_type=type(exc).__name__))
    counts = {kind: sum(r["result"] == kind for r in rows) for kind in ("PASS", "GAP", "ERROR")}
    print(json.dumps(dict(scope="offline_contract_audit_not_runtime_security_test", counts=counts, cases=rows), ensure_ascii=True, indent=2))
    return 2 if counts["ERROR"] else (1 if counts["GAP"] else 0)


if __name__ == "__main__":
    raise SystemExit(run())
