"""격리 E0: 승인 fixture 후보와 기존 원문 답변 경로를 동결한다.

실제 embedding/DB 검색 성능은 측정하지 않는다. 생성 답변을 정답으로 라벨링하거나
v1 HIT/MISS를 v2 action으로 변환하지 않는다. paid 호출과 .env 접근이 없다.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.contracts.hashing import verify_snapshot_hash
from app.contracts.snapshot import PublishedKnowledgeSnapshot
from app.learn.answering import compose_grounded_answer
from app.reg.retrieve import retrieve_question


def digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


async def record_baseline(fixture_dir: Path) -> dict:
    snapshot_bytes = (fixture_dir / "snapshot.json").read_bytes()
    manifest_bytes = (fixture_dir / "manifest.json").read_bytes()
    snapshot = PublishedKnowledgeSnapshot.model_validate_json(snapshot_bytes)
    verify_snapshot_hash(snapshot)
    manifest = json.loads(manifest_bytes)
    if (manifest["snapshot_hash"] != snapshot.snapshot_hash
            or manifest["store_id"] != snapshot.store_id):
        raise ValueError("fixture manifest/snapshot mismatch")
    extra_bytes = (fixture_dir / "r_baseline_cases.json").read_bytes()
    extra = json.loads(extra_bytes)
    cases = manifest["cases"] + extra["cases"]
    if len({case["id"] for case in cases}) != len(cases):
        raise ValueError("duplicate fixture case ID")
    facts = {fact.fact_revision_id: fact for fact in snapshot.fact_revisions}
    raw = {span.raw_span_id: span.text for span in snapshot.raw_spans}
    candidates = []
    for card in snapshot.cards:
        lines = []
        for block in sorted(card.blocks, key=lambda block: block.order):
            if block.raw_span_id:
                lines.append(raw[block.raw_span_id])
            else:
                for fid in block.fact_revision_ids:
                    fact = facts[fid]
                    lines.append("\n".join((fact.assertion, *fact.conditions, *fact.exceptions)))
        candidates.append(dict(id=int(card.card_id), version_id=int(card.card_version_id),
                               title=card.title, content="\n".join(lines), category="", score=1.0))

    class FixtureCandidates:
        async def fetch(self, sql, store_id, vector, limit):
            if str(store_id) != snapshot.store_id:
                raise ValueError("fixture tenant mismatch")
            return candidates[:limit]

    settings = SimpleNamespace(retrieval_threshold=.35, answer_mode="extractive")
    rows = []
    # Only isolated single-process CLI/tests use this harness. It is never called by product routes.
    with patch("app.reg.retrieve.embed_text", return_value=[0.0]), \
         patch("app.reg.retrieve.get_settings", return_value=settings), \
         patch("app.learn.answering.get_settings", return_value=settings):
        for case in cases:
            row = dict(case_id=case["id"], expected_action=case.get("action"),
                       expected=case, semantic_correct=None)
            if not case.get("question"):
                rows.append(row | dict(status="NOT_A_QUESTION", output=None))
                continue
            try:
                result = await retrieve_question(FixtureCandidates(), int(snapshot.store_id), case["question"])
                composition = (await compose_grounded_answer(case["question"], result["candidates"])
                               if result["kind"] == "hit" else None)
                rows.append(row | dict(status="RECORDED", legacy_kind=result["kind"],
                                       candidate_ids=[r["id"] for r in result["candidates"]],
                                       output=composition.content if composition else None,
                                       actual_v2_action=None,
                                       model_call_status=composition.model_call_status if composition else "NOT_CALLED"))
            except Exception as exc:
                rows.append(row | dict(status="ERROR", error_type=type(exc).__name__, output=None))
    root = Path(__file__).resolve().parents[2]
    source_files = ("app/team/baseline.py", "app/learn/answering.py", "app/reg/retrieve.py")
    return dict(schema_version="r_e0_fixture/v1", scope="SYNTHETIC_ORACLE_CANDIDATES_EXTRACTIVE",
                retrieval_quality_measured=False, semantic_quality_measured=False, paid_calls=0,
                projection_version="approved-assertions-conditions-exceptions/v1",
                snapshot_hash=snapshot.snapshot_hash, fixture_hash=digest(snapshot_bytes),
                truth_hash=digest(manifest_bytes + b"\x00" + extra_bytes),
                truth_components={"manifest.json": digest(manifest_bytes),
                                  "r_baseline_cases.json": digest(extra_bytes)}, store_id=snapshot.store_id,
                settings=dict(retrieval_threshold=.35, answer_mode="extractive", candidate_score=1.0),
                source_hashes={name: digest((root / name).read_bytes()) for name in source_files},
                case_count=len(rows), question_count=sum(bool(c.get("question")) for c in cases),
                error_count=sum(r["status"] == "ERROR" for r in rows), rows=rows)
