"""두 실험군을 사실 단위로 짝지어 비교한다.

  python scripts/compare_runs.py --store store-b --a "E4-frames20" --b "E4-frames60"
  python scripts/compare_runs.py --store store-b --a "E4-frames20" --b "E4-framesALL" --detail

왜 집계값으로 비교하지 않는가:
  추출이 비결정적이라 같은 설정을 3회 돌려도 손실률이 18.8%p 흔들린다 (V2 실측).
  "손실이 5%p 낮다" 는 그 잡음에 묻힌다.

  같은 사실을 양쪽에서 대조하면 공통 변동이 상쇄된다. 48건 중 37건은 어느 실행에서나
  같은 판정이므로 조용하고, 실제로 뒤집힌 것만 드러난다.

판정 규칙:
  실험군마다 여러 번 돌린 뒤 사실별 **다수결**로 대표 판정을 정한다.
  다수결이 갈리는 사실(예: COVERED 2 / MISSING 1)은 '불안정' 으로 따로 세고
  개선·악화 계산에서 뺀다. 잡음을 성과로 세지 않기 위해서다.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import asyncpg  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=True)

from app.config import get_settings  # noqa: E402

RANK = {"MISSING": 0, "PARTIAL": 1, "COVERED": 2}


async def fetch_group(conn, slug: str, prefix: str) -> tuple[list[int], dict]:
    """라벨 접두사가 같은 실행들을 한 실험군으로 묶는다."""
    rows = await conn.fetch(
        """
        select n.run_id, r.fact_id, r.verdict, r.must_have, r.source_type,
               r.subject, r.variant, r.attribute
        from extraction_results r
        join extraction_runs n on n.run_id = r.run_id
        join stores s on s.store_id = n.store_id
        where s.store_slug = $1 and n.status = 'SUCCEEDED'
          -- 반복 실행은 "라벨#1" 또는 "라벨-1" 로 남는다. 둘 다 한 군으로 묶는다
          and (n.label = $2 or n.label like $2 || '#%' or n.label like $2 || '-%')
        """,
        slug, prefix,
    )
    per_fact: dict[str, list[str]] = defaultdict(list)
    meta: dict[str, dict] = {}
    runs: set[int] = set()
    for r in rows:
        per_fact[r["fact_id"]].append(r["verdict"])
        meta[r["fact_id"]] = {
            "must_have": r["must_have"], "source_type": r["source_type"],
            "subject": r["subject"], "variant": r["variant"], "attribute": r["attribute"],
        }
        runs.add(int(r["run_id"]))
    return sorted(runs), {"verdicts": dict(per_fact), "meta": meta}


def decide(verdicts: list[str]) -> tuple[str, bool]:
    """다수결 판정과 안정 여부. 최빈값이 과반이 아니면 불안정이다."""
    counts = Counter(verdicts)
    top, n = counts.most_common(1)[0]
    return top, n * 2 > len(verdicts)


async def main() -> int:
    ap = argparse.ArgumentParser(description="실험군 간 사실 단위 비교")
    ap.add_argument("--store", required=True)
    ap.add_argument("--a", required=True, help="기준 실험군 라벨 (접두사)")
    ap.add_argument("--b", required=True, help="비교 실험군 라벨 (접두사)")
    ap.add_argument("--detail", action="store_true", help="뒤집힌 사실을 전부 나열한다")
    args = ap.parse_args()

    slug = args.store.replace("store-", "eval-")
    conn = await asyncpg.connect(get_settings().supabase_db_url)
    try:
        runs_a, A = await fetch_group(conn, slug, args.a)
        runs_b, B = await fetch_group(conn, slug, args.b)
    finally:
        await conn.close()

    for name, runs in ((args.a, runs_a), (args.b, runs_b)):
        if not runs:
            print(f"실행을 찾지 못했다: {name}", file=sys.stderr)
            return 1
        if len(runs) < 2:
            print(f"경고: {name} 이 {len(runs)}회뿐이다. 추출이 비결정적이라 "
                  f"최소 3회를 권한다")

    print(f"{slug}")
    print(f"  A  {args.a:<18} run {runs_a}")
    print(f"  B  {args.b:<18} run {runs_b}")
    print()

    shared = sorted(set(A["verdicts"]) & set(B["verdicts"]))
    improved, worsened, same = [], [], 0
    unstable = []

    for fid in shared:
        va, sa = decide(A["verdicts"][fid])
        vb, sb = decide(B["verdicts"][fid])
        if not (sa and sb):
            unstable.append((fid, A["verdicts"][fid], B["verdicts"][fid]))
            continue
        if RANK[vb] > RANK[va]:
            improved.append((fid, va, vb))
        elif RANK[vb] < RANK[va]:
            worsened.append((fid, va, vb))
        else:
            same += 1

    judged = len(shared) - len(unstable)
    net = len(improved) - len(worsened)
    print(f"대조한 사실 {len(shared)}건 중 판정 가능 {judged}건 "
          f"(불안정 {len(unstable)}건 제외)")
    print()
    print(f"  개선  {len(improved):>3}건   B 에서 판정이 올라감")
    print(f"  악화  {len(worsened):>3}건   B 에서 판정이 내려감")
    print(f"  동일  {same:>3}건")
    print(f"  ── 순증 {net:+}건")
    print()

    if net == 0:
        print("판정: 차이 없음.")
    elif abs(net) <= 1:
        print("판정: 차이가 1건 이하다. 설정을 바꿀 근거가 못 된다.")
    else:
        direction = "B 가 낫다" if net > 0 else "A 가 낫다"
        print(f"판정: {direction} (순증 {net:+}건). 불안정 사실을 뺀 값이다.")

    mh_imp = sum(1 for f, _, _ in improved if A["meta"][f]["must_have"])
    mh_wor = sum(1 for f, _, _ in worsened if A["meta"][f]["must_have"])
    if mh_imp or mh_wor:
        print(f"  그중 필수(must_have) — 개선 {mh_imp}건 · 악화 {mh_wor}건")

    by_type: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for f, _, _ in improved:
        by_type[A["meta"][f]["source_type"]][0] += 1
    for f, _, _ in worsened:
        by_type[A["meta"][f]["source_type"]][1] += 1
    if by_type:
        print("\nsource type 별 (개선/악화)")
        for stype, (i, w) in sorted(by_type.items()):
            print(f"  {stype:<7} +{i} / -{w}")

    if args.detail:
        for title, rows in (("개선", improved), ("악화", worsened)):
            if not rows:
                continue
            print(f"\n{title}")
            for fid, va, vb in rows:
                m = A["meta"][fid]
                print(f"  {fid:<9} {m['source_type']:<6} "
                      f"{m['subject']} {m['variant'] or ''} / {m['attribute']}"
                      f"   {va} → {vb}")
        if unstable:
            print(f"\n불안정 (판정에서 제외한 {len(unstable)}건)")
            for fid, va, vb in unstable:
                m = A["meta"][fid]
                print(f"  {fid:<9} {m['subject']} / {m['attribute']}"
                      f"   A={','.join(va)}  B={','.join(vb)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
