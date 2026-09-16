"""AI 검토 메모를 원래 표본에 붙인다. 채점·정답·사람 판정은 변경하지 않는다."""
import argparse
import json
from collections import Counter
from pathlib import Path

API = Path(__file__).resolve().parents[1]


def annotate(packet, notes):
    if notes["inputs_hash"] != packet["inputs_hash"] or notes["scorer_version"] != packet["scorer_version"]:
        raise ValueError("검토 입력/채점기 hash 불일치")
    entries = [*packet["covered_sample"], *packet["all_undetermined"]]
    ids = {e["truth"]["fact_id"] for e in entries}
    reviews = {}
    for group in notes["groups"]:
        for fact_id in group["ids"]:
            if fact_id in reviews or fact_id not in ids:
                raise ValueError("중복/표본 외 검토 ID")
            reviews[fact_id] = {k: v for k, v in group.items() if k != "ids"}
    if set(reviews) != ids:
        raise ValueError("미검토 표본 있음")
    output = []
    for entry in entries:
        fact_id = entry["truth"]["fact_id"]
        review = dict(reviews[fact_id])
        review.update(notes.get("overrides", {}).get(fact_id, {}))
        review.update(reviewer_kind="AI", human_verdict=None,
                      source_key=entry["truth"]["source_key"], locator=entry["truth"].get("locator"))
        output.append({**entry, "ai_review": review})
    return dict(scope="AI_EVIDENCE_REVIEW_NOT_HUMAN_ACCEPTANCE_NOT_SCORER_TUNING",
                inputs_hash=packet["inputs_hash"], scorer_version=packet["scorer_version"],
                source_qa=notes["source_qa"], limitations=notes["limitations"],
                counts=dict(Counter(e["ai_review"]["status"] for e in output)), entries=output)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("packet_dir", type=Path)
    args = ap.parse_args()
    directory = args.packet_dir.resolve()
    if not directory.is_relative_to(API / "eval/reports"):
        ap.error("Git 제외 eval/reports 하위만 허용")
    packet = json.loads((directory / "review_packet.json").read_text())
    notes = json.loads((directory / "review_annotations.json").read_text())
    result = annotate(packet, notes)
    with (directory / "reviewed_packet.json").open("x", encoding="utf-8") as file:
        json.dump(result, file, ensure_ascii=False, indent=2)
    print(json.dumps(result["counts"], ensure_ascii=False))


if __name__ == "__main__":
    main()
