"""R 유료 캠페인 사전등록 파일을 만들고, 끝난 실행을 등록과 대조한다.

유료 호출 **전에** 한 번 돌려 `registration.json` 을 남긴다. 그 파일의 hash 가
`compare_campaign` 의 `registration_ref` 이고, 실행 중에는
`prereg.authorize_live_call` 이 예산 상한을 본다.

    # ① 등록 (유료 실행 전)
    .venv/Scripts/python.exe scripts/register_r_campaign.py \
        --challenge ../output/<run>/frozen-challenge.json \
        --snapshot  ../output/<run>/published-snapshot.json \
        --sources   ../output/<run>/evaluator-sources.json \
        --purpose "P4 실제 품질·지연 인수" --registered-by "R 담당" \
        --provider-mode LIVE --usd-cap 2.50 \
        --approved-by "점주" --approved-at 2026-10-14T02:00:00+09:00 \
        --approval-ref "2026-10-14 대화 승인" \
        --must-have ../output/<run>/must-have-ids.json \
        --output ../output/<run>/registration.json

    # ② 사후 대조 (캠페인 보고가 나온 뒤)
    .venv/Scripts/python.exe scripts/register_r_campaign.py \
        --registration ../output/<run>/registration.json \
        --check-report ../output/<run>/campaign-report.json

이 스크립트는 모델을 부르지 않는다. 등록 자체가 승인이 아니다 — `--approved-*`
는 사용자가 실제로 준 승인을 옮겨 적는 칸이다.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.contracts.hashing import digest  # noqa: E402
from app.team.prereg import (  # noqa: E402
    CampaignRegistration,
    build_registration,
    check_campaign,
    registration_hash,
)

DEFAULT_EVALUATORS = (
    "app/team/prereg.py",
    "app/team/v2_campaign.py",
    "app/team/v2_evaluation.py",
    "app/team/answer_metrics.py",
)


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _with_prefix(value: str) -> str:
    return value if value.startswith("sha256:") else f"sha256:{value}"


def _turn_ids(challenge: dict) -> list[str]:
    """고정 분모. 미실행 턴도 빼지 않는다(실험설계 — 분모를 줄이지 않는다)."""
    ids: list[str] = []
    for case in challenge["cases"]:
        for index, _turn in enumerate(case["turns"], start=1):
            ids.append(f"{case['case_id']}#{index}")
    return ids


def _evaluator_hashes(names: list[str]) -> dict[str, str]:
    hashes = {}
    for name in names:
        path = ROOT / name
        if not path.exists():
            raise SystemExit(f"채점기 파일이 없다: {name}")
        hashes[name] = digest(path.read_text(encoding="utf-8"))
    return hashes


def _register(args: argparse.Namespace) -> int:
    challenge = _read_json(args.challenge)
    snapshot = _read_json(args.snapshot)
    sources = _read_json(args.sources)

    question_ids = _turn_ids(challenge)
    must_have = tuple(_read_json(args.must_have)) if args.must_have else ()
    unknown = sorted(set(must_have) - set(question_ids))
    if unknown:
        raise SystemExit(f"분모 밖의 필수 질문 ID: {unknown}")
    if not must_have:
        print("경고: 필수 질문 0개로 등록한다. 안전성 차단이 걸리지 않는다 (D18).",
              file=sys.stderr)

    budget = None
    if args.provider_mode == "LIVE":
        missing = [name for name in ("usd_cap", "approved_by", "approved_at", "approval_ref")
                   if getattr(args, name) in (None, "")]
        if missing:
            raise SystemExit(f"유료 등록에 필요한 승인 정보가 없다: {missing}")
        budget = dict(usd_cap=args.usd_cap, krw_cap=args.krw_cap,
                      fx_krw_per_usd=args.fx_krw_per_usd,
                      approved_by=args.approved_by,
                      approved_at=datetime.fromisoformat(args.approved_at),
                      approval_ref=args.approval_ref)

    registration, ref = build_registration(
        registered_at=datetime.fromisoformat(args.registered_at) if args.registered_at
        else datetime.now().astimezone(),
        registered_by=args.registered_by,
        purpose=args.purpose,
        manifest_hash=_with_prefix(challenge["content_sha256"]),
        truth_kind=args.truth_kind,
        truth_version=challenge["schema_version"] if args.truth_version is None else args.truth_version,
        snapshot_id=str(snapshot["snapshot_id"]),
        knowledge_revision=str(snapshot["knowledge_revision"]),
        snapshot_hash=_with_prefix(snapshot["snapshot_hash"]),
        evaluator_hashes=_evaluator_hashes(args.evaluator or list(DEFAULT_EVALUATORS)),
        source_manifest_hash=digest(sources),
        question_ids=tuple(question_ids),
        must_have_ids=must_have,
        run_kind=args.run_kind,
        repeat_count=args.repeats,
        control_count=args.controls,
        min_median_delta=args.min_median_delta,
        cost_neutral=args.cost_neutral,
        provider_mode=args.provider_mode,
        model_ids=tuple(args.model),
        failure_policy=dict(timeout_as=args.timeout_as,
                            per_call_timeout_seconds=args.per_call_timeout_seconds,
                            retry_limit=args.retry_limit,
                            partial_run=args.partial_run),
        budget=budget,
    )

    if args.output.exists():
        # 등록을 덮어쓰면 "나중에 고친 사전등록" 이 된다
        raise SystemExit(f"이미 있는 파일을 덮지 않는다: {args.output}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(registration.model_dump(mode="json"), ensure_ascii=False, indent=2,
                   sort_keys=True) + "\n", encoding="utf-8")
    print(f"등록 파일: {args.output}")
    print(f"registration_ref: {ref}")
    print(f"{args.run_kind} / 질문 분모 {len(question_ids)}개 / 필수 {len(must_have)}개 / "
          f"반복 {args.repeats}회 + 대조 {args.controls}회")
    if budget:
        print(f"예산 상한 {budget['usd_cap']} USD — 승인 {budget['approved_by']} "
              f"({budget['approval_ref']})")
    return 0


def _check(args: argparse.Namespace) -> int:
    registration = CampaignRegistration(**_read_json(args.registration))
    report = _read_json(args.check_report)
    problems = check_campaign(report, registration)
    print(f"registration_ref: {registration_hash(registration)}")
    if problems:
        print("사전등록과 어긋남:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("등록대로 실행됐다. (품질 통과·승격은 별도 판정이다)")
    gate = report.get("gate") or {}
    print(f"산술 게이트 eligible={gate.get('eligible')} "
          f"median_delta={gate.get('median_delta')} "
          f"blocking={gate.get('blocking_reasons')}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--challenge", type=Path)
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--sources", type=Path)
    parser.add_argument("--must-have", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--purpose")
    parser.add_argument("--registered-by")
    parser.add_argument("--registered-at")
    parser.add_argument("--truth-kind", choices=("SYNTHETIC", "HUMAN_REVIEWED"),
                        default="SYNTHETIC")
    parser.add_argument("--truth-version")
    parser.add_argument("--evaluator", action="append")
    # CAMPAIGN 은 승격을 다투는 A/B, DIAGNOSTIC 은 소수 질문을 들여다보는 실행이다.
    # 진단은 반복 하한이 없고 대표 개선량을 적지 않는다(점수를 내지 않으므로).
    parser.add_argument("--run-kind", choices=("CAMPAIGN", "DIAGNOSTIC"), default="CAMPAIGN")
    parser.add_argument("--repeats", type=int)
    parser.add_argument("--controls", type=int)
    parser.add_argument("--min-median-delta", type=int)
    parser.add_argument("--cost-neutral", action="store_true")
    parser.add_argument("--provider-mode", choices=("SYNTHETIC", "LIVE"), default="SYNTHETIC")
    parser.add_argument("--model", action="append", default=[])
    parser.add_argument("--timeout-as", choices=("FALSE", "UNJUDGED"), default="UNJUDGED")
    parser.add_argument("--per-call-timeout-seconds", type=int, default=30)
    parser.add_argument("--retry-limit", type=int, default=1)
    parser.add_argument("--partial-run", choices=("DISCARD_RUN", "KEEP_AS_UNJUDGED"),
                        default="DISCARD_RUN")
    parser.add_argument("--usd-cap")
    parser.add_argument("--krw-cap")
    parser.add_argument("--fx-krw-per-usd")
    parser.add_argument("--approved-by")
    parser.add_argument("--approved-at")
    parser.add_argument("--approval-ref")
    parser.add_argument("--registration", type=Path)
    parser.add_argument("--check-report", type=Path)
    args = parser.parse_args(argv)

    if args.check_report:
        if not args.registration:
            raise SystemExit("--check-report 는 --registration 과 함께 쓴다")
        return _check(args)

    campaign = args.run_kind == "CAMPAIGN"
    if args.repeats is None:
        args.repeats = 3 if campaign else 1
    if args.controls is None:
        args.controls = 3 if campaign else 0
    if campaign and args.min_median_delta is None:
        args.min_median_delta = 5
    missing = [name for name in ("challenge", "snapshot", "sources", "output",
                                 "purpose", "registered_by")
               if getattr(args, name) in (None, "")]
    if missing:
        raise SystemExit(f"등록에 필요한 인자가 없다: {missing}")
    if not args.model:
        raise SystemExit("--model 로 쓸 모델을 명시한다 (config.py 의 값과 같아야 한다)")
    return _register(args)


if __name__ == "__main__":
    raise SystemExit(main())
