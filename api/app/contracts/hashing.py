"""canonical JSON 과 snapshot hash (C0 결정서 §3.4).

**같은 승인 상태는 언제 어디서 계산해도 같은 hash 가 나와야 한다.** 그래야
"이 답변은 그때 그 지식으로 냈다" 를 증명할 수 있고, 캐시·색인·재발행이 서로를
믿을 수 있다. 그래서 직렬화를 한 군데로 모은다 — 파이썬 기본 `json.dumps` 는
키 순서·공백·실수 표기가 호출부마다 달라진다.

규칙:
  - UTF-8, 키 정렬, 공백 없는 구분자
  - 숫자는 전부 decimal string. `1` 과 `1.0` 이 다른 hash 를 내지 않게 한다
  - NaN·Infinity 는 거절한다. JSON 이 아니고 비교도 불가능하다
  - 사실·카드는 ID 를 **수로** 정렬한다. 문자열 정렬이면 "10" 이 "9" 앞에 온다
  - 블록은 `order` 로 정렬하고, 조건·예외·절차의 순서는 **손대지 않는다**
  - 원문의 Unicode·공백을 정규화하지 않는다 (RV-07)

hash 대상에서 빼는 것: `snapshot_id`, `created_at`, `snapshot_hash` 자신,
그리고 자료 가용성 같은 가변 상태. 이것들이 들어가면 내용이 같은 두 발행이
다른 hash 를 갖게 되어 멱등 재시도를 구분할 수 없다.
"""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any

HASH_PREFIX = "sha256:"


def _scalar(value: Any) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            raise ValueError("NaN·Infinity 는 canonical JSON 에 담을 수 없다")
        return repr(value)
    return value


def canonicalize(value: Any) -> Any:
    """중첩 구조를 canonical 표현으로 바꾼다. 순서는 호출부가 이미 정해 둔다."""
    if isinstance(value, dict):
        return {str(k): canonicalize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [canonicalize(v) for v in value]
    return _scalar(value)


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        canonicalize(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def digest(value: Any) -> str:
    """`sha256:<64 소문자 16진>`."""
    return HASH_PREFIX + hashlib.sha256(canonical_json(value)).hexdigest()


def _by_id(items, key):
    # ID 는 canonical decimal string 이므로 수로 정렬한다
    return sorted(items, key=lambda x: int(getattr(x, key)))


def knowledge_content_payload(snapshot) -> dict:
    """발행 전후 공통 승인 내용. 임시 snapshot/revision을 발급하지 않는다."""
    return {
        "store_id": snapshot.store_id,
        "glossary_version": snapshot.glossary_version,
        "renderer_version": snapshot.renderer_version,
        "cards": [
            {
                "card_id": c.card_id,
                "card_version_id": c.card_version_id,
                "entity_id": c.entity_id,
                "variant": c.variant.model_dump(),
                "title": c.title,
                # 블록 순서는 의미다. order 로 고정하고 리스트 순서에 기대지 않는다
                "blocks": [
                    {
                        "block_id": b.block_id,
                        "kind": b.kind,
                        "order": b.order,
                        "fact_revision_ids": list(b.fact_revision_ids),
                        "raw_span_id": b.raw_span_id,
                    }
                    for b in sorted(c.blocks, key=lambda b: b.order)
                ],
            }
            for c in _by_id(snapshot.cards, "card_id")
        ],
        "fact_revisions": [
            {
                "fact_revision_id": f.fact_revision_id,
                "fact_id": f.fact_id,
                "entity_id": f.entity_id,
                "original_assertion": f.original_assertion,
                "assertion": f.assertion,
                "subject": f.subject,
                "predicate": f.predicate,
                "variant": f.variant.model_dump(),
                "quantity": f.quantity.model_dump() if f.quantity else None,
                "value_text": f.value_text,
                "polarity": f.polarity,
                "order": f.order,
                # 조건·예외의 순서는 뜻을 담는다. 정렬하지 않는다
                "conditions": list(f.conditions),
                "exceptions": list(f.exceptions),
                "requires": sorted(f.requires, key=int),
                "provenance": [
                    {
                        "occurrence_id": p.occurrence_id,
                        "source_id": p.source_id,
                        "source_content_hash": p.source_content_hash,
                        "locator": p.locator.model_dump(),
                    }
                    for p in _by_id(f.provenance, "occurrence_id")
                ],
            }
            for f in _by_id(snapshot.fact_revisions, "fact_revision_id")
        ],
        "raw_spans": [
            {
                "raw_span_id": r.raw_span_id,
                "source_id": r.source_id,
                "text": r.text,
                "locator": r.locator.model_dump(),
            }
            for r in _by_id(snapshot.raw_spans, "raw_span_id")
        ],
    }


def snapshot_payload(snapshot) -> dict:
    return {"schema_version": snapshot.schema_version,
            "knowledge_revision": snapshot.knowledge_revision,
            **knowledge_content_payload(snapshot)}


def snapshot_digest(snapshot) -> str:
    return digest(snapshot_payload(snapshot))


def verify_snapshot_hash(snapshot) -> None:
    """실린 hash 가 내용과 맞는지 확인한다.

    맞지 않으면 전달 중에 내용이 바뀌었거나 다른 발행의 hash 가 붙은 것이다.
    둘 다 그대로 답하면 안 되는 상태다.
    """
    actual = snapshot_digest(snapshot)
    if actual != snapshot.snapshot_hash:
        raise ValueError(
            f"snapshot hash 가 내용과 다르다: 실린 값 {snapshot.snapshot_hash}, "
            f"계산 값 {actual}")
