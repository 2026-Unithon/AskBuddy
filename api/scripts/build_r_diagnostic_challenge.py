"""유료 진단 실행용 소형 challenge 를 만든다 — 사실은 그대로, 질문만 고른다.

P3 의 고정 challenge(사실 26개)에서 **사실 전부를 그대로 싣고** 질문만 골라 담는다.
사실을 줄이면 검색 난이도가 달라져 기존 기록과 비교할 수 없다.

    # 기존 질문 하나만
    python scripts/build_r_diagnostic_challenge.py --source <frozen.json> --case O01 --output <out.json>

    # 새로 쓴 질문(파일)으로
    python scripts/build_r_diagnostic_challenge.py --source <frozen.json> --authored <case.json> --output <out.json>

새로 쓴 질문의 정답은 **합성(에이전트 작성)이며 사람 검토를 받지 않았다.** 원본
challenge 의 `truth_kind` 를 그대로 물려받아 그 사실을 숨기지 않는다.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.r_fact_evaluation import challenge_hash, validate_challenge  # noqa: E402


def build(source: dict, cases: list[dict], note: str) -> dict:
    result = dict(source)
    result["cases"] = cases
    result["parent_challenge_hash"] = source["content_sha256"]
    result["status"] = "DIAGNOSTIC_SUBSET_NOT_A_CAMPAIGN"
    result["execution"] = {"status": "NOT_RUN", "pass_rate": None, "model_calls": 0}
    result["representation_note"] = (
        source.get("representation_note", "") + " | " + note).strip(" |")
    result.pop("content_sha256", None)
    result["content_sha256"] = challenge_hash(result)
    validate_challenge(result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--case", action="append", default=[])
    parser.add_argument("--authored", type=Path, action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--note", default="Diagnostic subset of the frozen fact challenge.")
    args = parser.parse_args(argv)

    source = json.loads(args.source.read_text(encoding="utf-8"))
    by_id = {case["case_id"]: case for case in source["cases"]}

    cases: list[dict] = []
    for case_id in args.case:
        if case_id not in by_id:
            raise SystemExit(f"원본에 없는 case: {case_id}")
        cases.append(by_id[case_id])
    for path in args.authored:
        cases.append(json.loads(path.read_text(encoding="utf-8")))
    if not cases:
        raise SystemExit("--case 또는 --authored 로 질문을 하나 이상 고른다")
    if len({c["case_id"] for c in cases}) != len(cases):
        raise SystemExit("case_id 가 겹친다")

    result = build(source, cases, args.note)
    if args.output.exists():
        raise SystemExit(f"이미 있는 파일을 덮지 않는다: {args.output}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
    turns = sum(len(c["turns"]) for c in cases)
    print(f"{args.output} — 사실 {len(result['facts'])}개 유지, 질문 {len(cases)}개 / 턴 {turns}개")
    print(f"content_sha256: {result['content_sha256']}")
    print(f"truth_kind: {result['truth_kind']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
