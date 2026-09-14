"""최초 기준선 측정 (W0).

  python scripts/run_baseline.py --store store-b
  python scripts/run_baseline.py --store store-b --reps 3

**고치기 전에 지금을 박아둔다.** 기준선 없이 개선하면 나중에 "좋아졌다" 고 말할
근거가 없다. 이미 두 번 속았다 — 대조군이 −11 인데 실험이 −2 였고, 사실상 같은
설정인 60장과 64장이 +5 를 냈다.

같은 설정으로 두 군(BASE, BASE-AA)을 돌린다. **둘 사이의 차이가 잡음의 크기다.**
그보다 작은 개선은 신호가 아니다 (D17·D18).

업로드·STT 는 건너뛰고 추출만 반복한다. 그래서 여기서 나오는 폭은 **추출 변동**이고
STT 변동(별도 측정 ~2%p)은 포함되지 않는다. 두 수를 합쳐 적지 않는다.
"""
from __future__ import annotations

import argparse
import asyncio
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(cmd: list[str]) -> int:
    print(f"\n$ {' '.join(cmd)}", flush=True)
    return subprocess.call(cmd, cwd=ROOT)


async def main() -> int:
    ap = argparse.ArgumentParser(description="기준선 측정 (W0)")
    ap.add_argument("--store", required=True)
    ap.add_argument("--reps", type=int, default=3,
                    help="군별 반복 횟수. 3회는 통계 보장이 아니라 최소선이다 (D17)")
    ap.add_argument("--groups", default="BASE,BASE-AA",
                    help="같은 설정의 두 군. 둘의 차이가 잡음 바닥이다")
    args = ap.parse_args()

    python = sys.executable
    groups = args.groups.split(",")
    started = time.perf_counter()

    for group in groups:
        for rep in range(1, args.reps + 1):
            # 반복끼리 카드가 쌓이면 이전 실행의 결과를 함께 채점하게 된다
            code = run([python, "scripts/reset_eval_store.py",
                        "--store", args.store, "--keep-sources"])
            if code:
                print(f"초기화 실패. 멈춘다.", file=sys.stderr)
                return code
            code = run([python, "scripts/run_extract_eval.py",
                        "--store", args.store, "--label", f"{group}#{rep}",
                        "--reuse-sources",
                        "--notes", "W0 기준선. 고치기 전 상태를 박아둔다"])
            if code:
                # 실패도 이 설정의 결과다. 감추지 않고 남긴 뒤 계속한다
                print(f"⚠ {group}#{rep} 실패 (종료 {code}). 기록하고 계속한다",
                      file=sys.stderr)

    print(f"\n총 {time.perf_counter() - started:.0f}초")
    print("\n" + "=" * 70)
    print("변동폭 (같은 설정 반복)")
    run([python, "scripts/variance_report.py", "--store", args.store,
         "--label-prefix", groups[0]])
    print("\n" + "=" * 70)
    print("A/A 대조 — 이 폭보다 작은 개선은 신호가 아니다")
    run([python, "scripts/compare_runs.py", "--store", args.store,
         "--a", groups[0], "--b", groups[1]])
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
