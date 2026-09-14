"""CP-01 R의 최초 동결 전 schema·합성 fixture export. W snapshot 동결과 별개다."""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.contracts.answer import AnswerPlan


def artifacts():
    common = {"snapshot_id": "2", "knowledge_revision": "1"}
    normal = [
        dict(common, action="ANSWER", selected_blocks=[dict(
            card_id="3", card_version_id="4", block_id="b1", fact_revision_ids=["6"])]),
        dict(common, action="CLARIFY", clarification_slot="temperature", allowed_options=["HOT", "ICE"],
             context_id="00000000-0000-4000-8000-000000000001"),
        dict(common, action="ESCALATE", escalation_reason="NO_APPROVED_EVIDENCE"),
        dict(common, action="REFUSE"), dict(common, action="SAFE_ROUTE"),
    ]
    rejected = [
        dict(common, action="ANSWER"),
        dict(normal[2], clarification_slot="temperature"),
        dict(normal[3], context_id=normal[1]["context_id"]),
        dict(normal[1], escalation_reason="NO_APPROVED_EVIDENCE"),
        dict(normal[0], knowledge_revision=1),
        dict(normal[0], snapshot_id="9223372036854775808"),
    ]
    return {"answer_plan.schema.json": AnswerPlan.model_json_schema(),
            "answer_plan.fixtures.json": {"accepted": normal, "rejected": rejected}}


def main():
    target = Path(__file__).resolve().parents[1] / "tests/fixtures/contracts/v1/r_answer"
    target.mkdir(parents=True, exist_ok=True)
    for name, payload in artifacts().items():
        (target / name).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
