"""고정 정답 분모: 중앙값 성능·만장일치 안정성·전체 반복 안전성. DB는 읽기만 한다."""
from __future__ import annotations
import argparse
import asyncio
import hashlib
import json
import re
import sys
from collections import Counter
from math import ceil
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import asyncpg
from dotenv import load_dotenv
from app.config import get_settings
from app.team.repeat_metrics import compare_repeats
from app.team.extraction import SCORER_VERSION
load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=True)


def _settings_hash(settings):
    if isinstance(settings, str):
        settings = json.loads(settings)
    payload = {k:v for k,v in (settings or {}).items() if k != "campaign"}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


async def fetch_group(conn, slug: str, prefix: str):
    attempts = await conn.fetch(
        "select n.run_id, n.status, n.card_count, n.settings from extraction_runs n "
        "join stores s on s.store_id=n.store_id where s.store_slug=$1 "
        "and (n.label=$2 or n.label ~ ('^' || $2 || '[#-][0-9]+$')) order by n.run_id", slug, prefix)
    rows = await conn.fetch(
        "select r.run_id, r.fact_id, r.verdict from extraction_results r "
        "join extraction_runs n on n.run_id=r.run_id join stores s on s.store_id=n.store_id "
        "where s.store_slug=$1 and (n.label=$2 or n.label ~ ('^' || $2 || '[#-][0-9]+$')) "
        "order by r.run_id, r.fact_id", slug, prefix)
    per_run = {int(a["run_id"]): {} for a in attempts}
    for row in rows:
        run = per_run[int(row["run_id"])]
        if row["fact_id"] in run:
            raise ValueError("중복 실행/사실 판정")
        run[row["fact_id"]] = row["verdict"]
    return sorted(per_run), dict(per_run=per_run,
        scorer_versions=sorted({(json.loads(a["settings"]) if isinstance(a["settings"], str) else (a["settings"] or {})).get("scorer_version", "UNKNOWN") for a in attempts}),
        failed=[int(a["run_id"]) for a in attempts if a["status"] != "SUCCEEDED" or not a["card_count"]],
        settings_hashes=sorted({_settings_hash(a["settings"]) for a in attempts}))


async def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--store", required=True)
    ap.add_argument("--a", required=True)
    ap.add_argument("--b", required=True)
    ap.add_argument("--detail", action="store_true")
    ap.add_argument("--control", action="store_true")
    ap.add_argument("--noise", type=int, help="동일 설정 A/A 전체 반복 성공 개수 max−min")
    args = ap.parse_args()
    if args.noise is not None and args.noise < 0:
        ap.error("--noise는 음수가 될 수 없다")
    if any(re.search(r"[.^$*+?()\[\]{}|\\]", label) for label in (args.a,args.b)):
        ap.error("라벨에 정규식 특수문자를 쓰지 않는다")
    if not re.fullmatch(r"store-[ab]", args.store):
        ap.error("dev store-a/store-b만 지원한다. holdout은 별도 사전등록 캠페인이다")
    slug = args.store.replace("store-", "eval-")
    conn = await asyncpg.connect(get_settings().supabase_db_url)
    try:
        runs_a, a = await fetch_group(conn, slug, args.a)
        runs_b, b = await fetch_group(conn, slug, args.b)
    finally:
        await conn.close()
    truth = json.loads((Path(__file__).resolve().parents[1]/"eval/data"/args.store/"truth/facts.json").read_text())["facts"]
    try:
        result = compare_repeats([a["per_run"][r] for r in runs_a], [b["per_run"][r] for r in runs_b], truth)
    except ValueError as exc:
        print(f"판정: 보류 — {exc}")
        return 1
    print(f"{slug} · 고정 분모 {result['denominator']}건 · run {runs_a} / {runs_b}")
    print(f"성능: 성공 {result['counts_a']} → {result['counts_b']}")
    print(f"  Δ={result['deltas']} · 중앙값 {result['median_delta']:+}건")
    print(f"안정성: {dict(Counter(result['transitions'].values()))}")
    print(f"안전성(모든 반복): 필수 악화 {result['must_have_regressions']} · 미판정 {result['must_have_unjudged']}")
    print(f"  안정 성공→변동 {result['stability_degraded']}")
    print(f"  이전 지시 제외 검사 {result['expected_exclusions']}건 · 실패/미판정 {result['expected_exclusions_failed_ids']}")
    versions_a, versions_b = a.get("scorer_versions", ["UNKNOWN"]), b.get("scorer_versions", ["UNKNOWN"])
    invalid = (a["failed"] or b["failed"] or len(a["settings_hashes"]) != 1 or len(b["settings_hashes"]) != 1
               or versions_a != [SCORER_VERSION] or versions_b != [SCORER_VERSION])
    if versions_a != [SCORER_VERSION] or versions_b != [SCORER_VERSION]:
        print(f"채점 버전 불일치: A={versions_a} B={versions_b} 현재={SCORER_VERSION}; 재채점 필요")
    if args.control:
        print(f"A/A: 승패 없음 · 전체 반복 폭 {result['control_width']}건")
        if invalid or a["settings_hashes"] != b["settings_hashes"]:
            print("판정: 보류 — 실패/조건 혼합이 있어 잡음 바닥으로 사용할 수 없다")
        else:
            print(f"다음 비교에 --noise {result['control_width']}")
    elif args.noise is None:
        print("판정: 보류 — A/A 대조군 폭 없음")
    else:
        threshold = max(5, ceil(args.noise*1.5))
        performance = result["median_delta"] >= threshold and sum(d>0 for d in result["deltas"])*3 >= len(result["deltas"])*2
        print(f"D18 성능 문턱 {threshold}건: {'충족' if performance else '미충족'}")
        if invalid or not result["safety_passed"]:
            print("판정: 차단 — 실패/설정 혼합/필수 안전성 미충족")
        else:
            print("판정: 보류 — 원장 재현율·원가·지연·동일 채점 버전 인수는 별도 확인 필요")
    if args.detail:
        meta = {f["fact_id"]: f for f in truth}
        for fid, transition in result["transitions"].items():
            if transition[0] != transition[1] or "VARIABLE" in transition:
                print(f"  {fid} / {meta[fid]['attribute']} · {transition} · "
                      f"A={[a['per_run'][r].get(fid, 'UNDETERMINED') for r in runs_a]} · "
                      f"B={[b['per_run'][r].get(fid, 'UNDETERMINED') for r in runs_b]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
