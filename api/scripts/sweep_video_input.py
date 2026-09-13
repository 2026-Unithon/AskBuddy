"""E4 영상 입력 실험 — 프레임 수와 입력 모드를 바꿔가며 E-O0 를 잰다.

  # 프레임 수 쓸기 (20 / 60 / 전부)
  python scripts/sweep_video_input.py --store store-a --frames 20,60,0

  # native 영상까지 포함
  python scripts/sweep_video_input.py --store store-a --frames 20,60,0 --native

  # 짧은 클립으로 먼저 (원가를 재보고 전체 투입을 정한다)
  python scripts/sweep_video_input.py --store store-a --native --clip 300

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
    ap.add_argument("--native", action="store_true", help="native 영상 조합을 추가한다")
    ap.add_argument("--clip", type=int, default=0,
                    help="원본 앞 N초만 쓰는 클립을 만들어 native 를 먼저 재본다")
    ap.add_argument("--allow-holdout", action="store_true")
    args = ap.parse_args()

    store_dir = ROOT / "eval" / "data" / args.store
    if args.clip:
        make_clip(store_dir, args.clip)

    combos: list[tuple[str, dict[str, str]]] = []
    for raw in [f for f in args.frames.split(",") if f.strip()]:
        n = int(raw)
        label = f"E4-frames{'ALL' if n == 0 else n}"
        combos.append((label, {"VIDEO_INPUT_MODE": "frames",
                               "VIDEO_MAX_FRAMES_TO_MODEL": str(n)}))
    if args.native:
        combos.append(("E4-native", {"VIDEO_INPUT_MODE": "native"}))

    if not combos:
        print("실행할 조합이 없다. --frames 또는 --native 를 준다", file=sys.stderr)
        return 2

    print(f"조합 {len(combos)}개: {', '.join(label for label, _ in combos)}")
    failed = []
    for label, env in combos:
        if run([PY, "scripts/reset_eval_store.py", "--store", args.store]) != 0:
            failed.append(f"{label} (reset)")
            continue
        cmd = [PY, "scripts/run_extract_eval.py", "--store", args.store, "--label", label]
        if args.allow_holdout:
            cmd.append("--allow-holdout")
        if run(cmd, env) != 0:
            failed.append(label)

    print("\n" + "=" * 60)
    if failed:
        print(f"실패: {', '.join(failed)}")
    print("비교: python scripts/track_progress.py 로 PROGRESS.md 갱신")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
