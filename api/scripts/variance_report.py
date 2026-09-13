"""같은 설정 반복 실행의 변동폭을 낸다.

  python scripts/variance_report.py --store store-b
  python scripts/variance_report.py --store store-b --label-prefix VAR-

**이 값보다 작은 차이는 신호가 아니라 잡음이다.**
프레임 수·온도·모드 실험 결과를 해석하기 전에 이 선을 먼저 정한다.

측정 도구의 오차가 측정하려는 효과보다 크면 실험은 성립하지 않는다.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import asyncpg  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=True)

from app.config import get_settings  # noqa: E402

# 변동폭을 볼 지표. (경로, 라벨, 퍼센트 표기인가)
METRICS = [
    (("loss",), "E-O0 손실", True),
    (("recall",), "재현율", True),
    (("must_have", "loss"), "치명 누락률", True),
    (("covered",), "담김 건수", False),
    (("card_count",), "생성 카드", False),
]


def _dig(d: dict, path: tuple[str, ...]):
    for key in path:
        if not isinstance(d, dict):
            return None
        d = d.get(key)
    return d


async def main() -> int:
    ap = argparse.ArgumentParser(description="반복 실행 변동폭")
    ap.add_argument("--store", required=True, help="store-b 또는 eval-b")
    ap.add_argument("--label-prefix", default="VAR-")
    args = ap.parse_args()

    slug = args.store.replace("store-", "eval-")
    conn = await asyncpg.connect(get_settings().supabase_db_url)
    try:
        rows = await conn.fetch(
            """
            select r.run_id, r.label, r.metrics, r.card_count, r.code_version,
                   r.prompt_version, r.extract_model, r.settings
            from extraction_runs r
            join stores s on s.store_id = r.store_id
            where s.store_slug = $1 and r.status = 'SUCCEEDED'
              and r.label like $2
            order by r.run_id
            """,
            slug, args.label_prefix + "%",
        )
    finally:
        await conn.close()

    if len(rows) < 2:
        print(f"반복 실행이 {len(rows)}건이다. 최소 2회가 필요하다.\n"
              f"  python scripts/sweep_video_input.py --store {args.store} --repeat 3",
              file=sys.stderr)
        return 1

    runs = []
    for r in rows:
        m = r["metrics"] if isinstance(r["metrics"], dict) else json.loads(r["metrics"])
        m["card_count"] = int(r["card_count"])
        runs.append({"run_id": int(r["run_id"]), "label": r["label"], "m": m,
                     "code": r["code_version"], "prompt": r["prompt_version"]})

    codes = {r["code"] for r in runs}
    prompts = {r["prompt"] for r in runs}
    print(f"{slug} · 반복 {len(runs)}회 (run {', '.join(str(r['run_id']) for r in runs)})")
    if len(codes) > 1 or len(prompts) > 1:
        print("  경고: 코드 또는 프롬프트 버전이 실행마다 다르다. 순수한 변동폭이 아니다")
    print()

    print(f"{'지표':<14}{'최소':>10}{'최대':>10}{'평균':>10}{'표준편차':>10}{'폭':>10}")
    print("-" * 64)
    lines = []
    for path, label, as_pct in METRICS:
        values = [_dig(r["m"], path) for r in runs]
        values = [float(v) for v in values if v is not None]
        if len(values) < 2:
            continue
        lo, hi = min(values), max(values)
        mean = statistics.mean(values)
        sd = statistics.stdev(values)
        span = hi - lo
        fmt = (lambda v: f"{v * 100:.1f}%") if as_pct else (lambda v: f"{v:.1f}")
        print(f"{label:<14}{fmt(lo):>10}{fmt(hi):>10}{fmt(mean):>10}{fmt(sd):>10}{fmt(span):>10}")
        lines.append((label, span, as_pct))

    print()
    print("판정 기준:")
    for label, span, as_pct in lines:
        shown = f"{span * 100:.1f}%p" if as_pct else f"{span:.1f}"
        print(f"  {label} — 실험 간 차이가 {shown} 이하면 잡음으로 본다")
    print()
    print("이 선보다 작은 차이로 설정을 바꾸지 않는다. 반복 횟수를 늘리면 선이 더 좁아진다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
