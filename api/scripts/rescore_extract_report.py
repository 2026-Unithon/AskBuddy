"""보존된 실행 입력만 재채점한다. DB/유료 모델 호출·옛 판정 덮어쓰기 없음."""
import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.team.extraction import (ExtractionReport, SCORER_VERSION, aggregate, applicability,
                                normalize, variant_axis, score_expected_fact, match_fact_in_ledger, score_output, apply_evaluation_policy)


def rescore(data, policy=None):
    if data.get("store") not in {"eval-a", "eval-b"}:
        raise ValueError("dev 실행만 재평가한다. holdout은 별도 사전등록 캠페인이 필요하다")
    inputs=data.get("inputs")
    if not inputs or any(k not in inputs for k in ("cards","ledger","truth","source_types")):
        raise ValueError("실행 당시 카드·원장·정답 스냅샷 없음: 과거 판정만으로 재채점할 수 없다")
    truth, cards, ledger=inputs["truth"],inputs["cards"],inputs["ledger"]
    policy = policy or {}
    evaluated_truth = apply_evaluation_policy(truth, policy.get(data["store"], {}))
    axis=variant_axis(evaluated_truth)
    report=ExtractionReport()
    for fact in evaluated_truth:
        needs_variant=axis.get(normalize(fact.get("subject") or ""),False)
        fact={**fact,"applicability":applicability(fact,needs_variant)}
        hit, fid=match_fact_in_ledger(fact,ledger)
        report.add(fact,score_expected_fact(fact,cards,evaluated_truth,require_variant=needs_variant),
                   inputs["source_types"].get(fact.get("source_key"),"UNKNOWN"),in_ledger=hit,ledger_fact_id=fid)
    metrics=aggregate(report.rows,card_count=len(cards))
    metrics["output"]=score_output(ledger,truth)
    return dict(run_id=data["run_id"],store=data["store"],label=data["label"],
                scorer_version=SCORER_VERSION, results=report.rows, metrics=metrics,
                scorer_code_hash="sha256:"+hashlib.sha256((Path(__file__).resolve().parents[1]/"app/team/extraction.py").read_bytes()).hexdigest(),
                evaluation_policy=policy, evaluation_policy_hash="sha256:"+hashlib.sha256(json.dumps(policy,sort_keys=True).encode()).hexdigest(),
                input_hash="sha256:"+hashlib.sha256(json.dumps(inputs,sort_keys=True,ensure_ascii=False,separators=(",",":")).encode()).hexdigest(),
                scope="RESCORE_NOT_MODEL_IMPROVEMENT",inputs=inputs)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("report",type=Path)
    ap.add_argument("--out",type=Path,required=True)
    ap.add_argument("--policy",type=Path,help="원본 입력과 별도로 보존하는 승인 평가 라벨")
    args=ap.parse_args()
    if not re.fullmatch(r"extract\d+_eval-[ab]_[A-Za-z0-9_-]+\.json", args.report.name):
        ap.error("입력은 dev extract 실행 리포트만 허용한다. holdout/임의 입력을 읽지 않는다")
    if args.report.resolve()==args.out.resolve() or args.out.exists():
        ap.error("원본 또는 기존 결과를 덮어쓸 수 없다")
    try:
        result=rescore(json.loads(args.report.read_text(encoding="utf-8")),
                       json.loads(args.policy.read_text(encoding="utf-8")) if args.policy else None)
    except ValueError as exc:
        print(f"재평가 보류: {exc}",file=sys.stderr)
        return 1
    with args.out.open("x",encoding="utf-8") as output:
        json.dump(result,output,ensure_ascii=False,indent=2,default=str)
    print(f"재평가 완료: {args.out} ({SCORER_VERSION}); 모델 개선 판정 아님")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
