"""계약을 JSON schema 로 내보내고 고정 test vector 를 만든다 (CP-02).

  python scripts/export_contract_schemas.py          # schema/ 에 쓴다
  python scripts/export_contract_schemas.py --check  # 코드와 다르면 실패

**왜 파일로 내보내는가.** W 와 R 이 같은 계약을 쓴다는 것을 사람 말이 아니라
파일로 고정한다. 계약을 고치면 export 가 달라지고, `--check` 가 CI 에서 걸린다 —
"한쪽만 고쳤다" 를 런타임까지 끌고 가지 않는다.

hash test vector 가 특히 중요하다. canonical JSON 규칙을 누가 무심코 바꾸면
(키 정렬을 빼거나 실수 표기를 바꾸면) 같은 승인 상태가 다른 hash 를 내고,
그 순간 과거 답변의 재현이 끊긴다. 고정된 기대 hash 가 그걸 잡는다.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.contracts import (  # noqa: E402
    AnswerPlan,
    CardBlock,
    CardPlan,
    ChatResponse,
    ErrorEnvelope,
    ExtractionEnvelope,
    FactProvenance,
    FactRevision,
    OutboxEvent,
    PrepareIndexRequest,
    PrepareIndexResult,
    PublishedCard,
    PublishedKnowledgeSnapshot,
    PublishKnowledgeRequest,
    PublishKnowledgeResult,
    QuestionContext,
    RawSpan,
    ValidateAndSaveAnswerRequest,
    digest,
    snapshot_digest,
    snapshot_payload,
)

OUT = Path(__file__).resolve().parents[1] / "schema"

MODELS = {
    "extraction": ExtractionEnvelope,
    "card_plan": CardPlan,
    "published_knowledge": PublishedKnowledgeSnapshot,
    "answer_plan": AnswerPlan,
    "chat_response": ChatResponse,
    "question_context": QuestionContext,
    "validate_and_save_answer": ValidateAndSaveAnswerRequest,
    "error_envelope": ErrorEnvelope,
    "prepare_index_request": PrepareIndexRequest,
    "prepare_index_result": PrepareIndexResult,
    "publish_knowledge_request": PublishKnowledgeRequest,
    "publish_knowledge_result": PublishKnowledgeResult,
    "outbox_event": OutboxEvent,
}


def sample_snapshot() -> PublishedKnowledgeSnapshot:
    """test vector 용 고정 입력. 시각·ID 를 박아 둬 실행마다 같은 값이 나온다.

    실제 매장 자료를 쓰지 않는다. 합성 값이다.
    """
    prov = FactProvenance(occurrence_id="50", source_id="60")
    facts = (
        FactRevision(
            fact_revision_id="9", fact_id="4", entity_id="30",
            original_assertion="  들여쓴 원문\n", assertion="정리된 표현",
            order=2, requires=("10",), provenance=(prov,)),
        FactRevision(
            fact_revision_id="10", fact_id="5", entity_id="30",
            original_assertion="먼저 확인한다", assertion="먼저 확인한다",
            order=1, provenance=(FactProvenance(occurrence_id="51",
                                                source_id="60"),)),
    )
    blocks = (
        CardBlock(block_id="b2", kind="RAW", order=2, raw_span_id="70"),
        CardBlock(block_id="b1", kind="STEPS", order=1,
                  fact_revision_ids=("9", "10")),
    )
    card = PublishedCard(card_id="20", card_version_id="21", entity_id="30",
                         title="합성 카드", blocks=blocks)
    spans = (RawSpan(raw_span_id="70", source_id="60", text="승인된 원문 그대로"),)
    payload_source = dict(
        store_id="1", knowledge_revision="7", snapshot_id="10",
        created_at=datetime(2026, 9, 14, tzinfo=timezone.utc),
        glossary_version="g1", renderer_version="r1",
        cards=(card,), fact_revisions=facts, raw_spans=spans,
    )
    # hash 는 내용에서 계산한다. 사람이 적어 넣지 않는다
    probe = PublishedKnowledgeSnapshot(snapshot_hash="sha256:" + "0" * 64,
                                       **payload_source)
    return PublishedKnowledgeSnapshot(snapshot_hash=snapshot_digest(probe),
                                      **payload_source)


def build() -> dict[str, str]:
    files = {name: json.dumps(model.model_json_schema(), ensure_ascii=False,
                              indent=2, sort_keys=True) + "\n"
             for name, model in MODELS.items()}
    snap = sample_snapshot()
    vectors = {
        "note": "canonical JSON 규칙이 바뀌면 여기 값이 달라진다. 그때 과거 인용의 재현이 끊긴다",
        "empty_object": digest({}),
        "int_is_decimal_string": digest({"n": 1}),
        "float_and_int_differ": [digest({"n": 1}), digest({"n": 1.0})],
        "unicode_is_not_normalized": digest({"t": "  들여쓴 원문\n"}),
        "key_order_does_not_matter": [digest({"a": "1", "b": "2"}),
                                      digest({"b": "2", "a": "1"})],
        "bigint_id_keeps_precision": digest({"id": "9007199254740993"}),
        "snapshot_hash": snap.snapshot_hash,
        "snapshot_payload_excludes": ["snapshot_id", "created_at", "snapshot_hash"],
    }
    files["_test_vectors"] = json.dumps(vectors, ensure_ascii=False,
                                        indent=2, sort_keys=True) + "\n"
    files["_sample_snapshot_payload"] = json.dumps(
        snapshot_payload(snap), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    return files


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="쓰지 않고 기존 파일과 다른지만 본다")
    args = ap.parse_args()

    files = build()
    OUT.mkdir(exist_ok=True)
    stale = []
    for name, text in files.items():
        path = OUT / f"{name}.json"
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != text:
                stale.append(path.name)
        else:
            path.write_text(text, encoding="utf-8")

    if args.check:
        if stale:
            print("계약이 바뀌었는데 export 가 갱신되지 않았다:", ", ".join(stale))
            print("python scripts/export_contract_schemas.py 로 다시 내보낸다")
            return 1
        print(f"export {len(files)}개 최신")
        return 0
    print(f"{OUT} 에 {len(files)}개 파일을 썼다")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
