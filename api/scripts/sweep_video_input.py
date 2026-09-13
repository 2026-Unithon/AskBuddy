"""추출 실험 스윕 — 프레임 수·입력 모드·온도를 바꿔가며 E-O0 를 잰다.

  # 같은 설정을 3회 반복해 변동폭을 잰다. 다른 실험보다 이게 먼저다
  python scripts/sweep_video_input.py --store store-b --repeat 3

  # 프레임 수 쓸기 (20 / 60 / 전부)
  python scripts/sweep_video_input.py --store store-b --frames 20,60,0

  # 온도 쓸기
  python scripts/sweep_video_input.py --store store-b --temps 0.0,0.2,0.4,0.6

  # native 영상까지 포함
  python scripts/sweep_video_input.py --store store-b --frames 20,60,0 --native

  # 짧은 클립으로 먼저 (원가를 재보고 전체 투입을 정한다)
  python scripts/sweep_video_input.py --store store-b --native --clip 300

**변동폭을 모르면 어떤 실험도 해석할 수 없다.** 같은 설정 3회의 편차보다 작은
차이는 신호가 아니라 잡음이다. `--repeat` 를 먼저 돌려 그 선을 정한다.

한 번에 하나씩만 바꾼다 (0절 실험 규율). 프레임 수를 바꿀 때 모드는 고정이고,
모드를 바꿀 때 프레임 수는 기준값으로 되돌린다.

각 조합마다 매장을 초기화하고 다시 추출한다. 이전 카드가 남아 있으면
"이번 설정이 만든 카드" 가 아니라 "누적된 카드" 를 채점하게 된다.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable


def run(cmd: list[str], env: dict[str, str] | None = None) -> int:
    merged = {**os.environ, **(env or {})}
    print(f"\n$ {' '.join(cmd)}"
          + (f"   [{', '.join(f'{k}={v}' for k, v in (env or {}).items())}]" if env else ""))
    return subprocess.run(cmd, cwd=ROOT, env=merged).returncode


def make_clip(store_dir: Path, seconds: int) -> Path:
    """원본에서 앞 N초를 잘라 클립을 만든다. 원가를 재보기 위한 축소판이다."""
    import json
    manifest = json.loads((store_dir / "manifest.json").read_text(encoding="utf-8"))
    src = next(e for e in manifest["sources"] if e["type"] == "VIDEO")
    origin = store_dir / src["file"]
    clip = origin.with_name(f"{origin.stem}-clip{seconds}s{origin.suffix}")
    if clip.exists():
        print(f"  클립 재사용 {clip.name}")
        return clip
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-t", str(seconds),
         "-i", str(origin), "-c", "copy", str(clip)],
        check=True,
    )
    print(f"  클립 생성 {clip.name} ({clip.stat().st_size / 1e6:.0f}MB)")
    return clip


def main() -> int:
    ap = argparse.ArgumentParser(description="영상 입력 실험 (E4)")
    ap.add_argument("--store", required=True)
    ap.add_argument("--frames", default="", help="쉼표 구분. 0 은 상한 없음. 예: 20,60,0")
    ap.add_argument("--temps", default="", help="쉼표 구분 온도. 예: 0.0,0.2,0.4")
    ap.add_argument("--repeat", type=int, default=0,
                    help="현재 설정을 N회 반복해 변동폭을 잰다. 다른 축과 같이 쓰지 않는다")
    ap.add_argument("--native", action="store_true", help="native 영상 조합을 추가한다")
    ap.add_argument("--clip", type=int, default=0,
                    help="원본 앞 N초만 쓰는 클립을 만들어 native 를 먼저 재본다")
    ap.add_argument("--reps", type=int, default=3,
                    help="조합마다 반복할 횟수. 추출이 비결정적이라 1회로는 판정할 수 없다")
    ap.add_argument("--fresh-sources", action="store_true",
                    help="자료를 다시 올리고 STT 도 다시 돌린다. 기본은 재사용(빠르고 STT 변동 제거)")
    ap.add_argument("--allow-holdout", action="store_true")
    args = ap.parse_args()

    store_dir = ROOT / "eval" / "data" / args.store
    if args.clip:
        make_clip(store_dir, args.clip)

    combos: list[tuple[str, dict[str, str]]] = []

    if args.repeat:
        # 변동폭 측정. 설정을 바꾸지 않고 같은 조건을 반복한다
        if args.frames or args.temps or args.native:
            print("--repeat 는 다른 축과 같이 쓰지 않는다. "
                  "변동폭은 설정을 고정한 채 재야 한다", file=sys.stderr)
            return 2
        combos = [(f"VAR-{i}", {}) for i in range(1, args.repeat + 1)]
    else:
        for raw in [f for f in args.frames.split(",") if f.strip()]:
            n = int(raw)
            label = f"E4-frames{'ALL' if n == 0 else n}"
            combos.append((label, {"VIDEO_INPUT_MODE": "frames",
                                   "VIDEO_MAX_FRAMES_TO_MODEL": str(n)}))
        for raw in [t for t in args.temps.split(",") if t.strip()]:
            temp = float(raw)
            combos.append((f"E-temp{temp:g}", {"EXTRACT_TEMPERATURE": str(temp)}))
        if args.native:
            combos.append(("E4-native", {"VIDEO_INPUT_MODE": "native"}))

    if not combos:
        print("실행할 조합이 없다. --repeat / --frames / --temps / --native 중 하나를 준다",
              file=sys.stderr)
        return 2

    reps = 1 if args.repeat else max(1, args.reps)
    total = len(combos) * reps
    print(f"조합 {len(combos)}개 × {reps}회 = 실행 {total}건")
    print(f"  {', '.join(label for label, _ in combos)}")

    failed = []
    for label, env in combos:
        for rep in range(1, reps + 1):
            reset = [PY, "scripts/reset_eval_store.py", "--store", args.store]
            if not args.fresh_sources:
                reset.append("--keep-sources")
            if run(reset) != 0:
                failed.append(f"{label}#{rep} (reset)")
                continue
            run_label = label if reps == 1 else f"{label}#{rep}"
            cmd = [PY, "scripts/run_extract_eval.py", "--store", args.store,
                   "--label", run_label]
            if not args.fresh_sources:
                cmd.append("--reuse-sources")
            if args.allow_holdout:
                cmd.append("--allow-holdout")
            if run(cmd, env) != 0:
                failed.append(run_label)

    print("\n" + "=" * 60)
    if failed:
        print(f"실패: {', '.join(failed)}")
    if args.repeat:
        print("변동폭 확인: python scripts/variance_report.py --store " + args.store)
    print("비교: python scripts/track_progress.py 로 PROGRESS.md 갱신")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
