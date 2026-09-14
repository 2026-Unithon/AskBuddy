"""원본 파일 해시를 manifest 에 채운다 (W0).

  python scripts/backfill_source_hashes.py [--check]

**해시가 없으면 같은 자료로 잰 것인지 증명할 수 없다.** 영상을 다시 인코딩하거나
스캔을 다시 찍으면 입력이 조용히 달라지고, 기준선 대비 개선처럼 보이는 것이
사실은 입력이 바뀐 결과일 수 있다. 이미 프레임 실험에서 두 번 속았다.

`--check` 는 쓰지 않고 기록된 해시와 지금 파일이 같은지만 본다.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "eval" / "data"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="쓰지 않고 기록된 해시와 현재 파일이 같은지만 본다")
    args = ap.parse_args()

    changed = drifted = missing = 0
    for store in sorted(DATA.iterdir()):
        path = store / "manifest.json"
        if not path.exists():
            continue
        manifest = json.loads(path.read_text("utf-8"))
        for source in manifest["sources"]:
            target = store / source["file"]
            if not target.exists():
                print(f"  없음   {store.name}/{source['source_key']} → {source['file']}")
                missing += 1
                continue
            actual = sha256(target)
            recorded = source.get("sha256")
            if recorded == actual:
                continue
            if recorded and args.check:
                # 기록과 다르다. 입력이 바뀌었다는 뜻이고 기준선 비교가 깨진다
                print(f"  달라짐 {store.name}/{source['source_key']}: "
                      f"{recorded[:12]} → {actual[:12]}")
                drifted += 1
                continue
            if recorded:
                print(f"  갱신   {store.name}/{source['source_key']}")
            source["sha256"] = actual
            source["bytes"] = target.stat().st_size
            changed += 1
        if changed and not args.check:
            path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")

    if args.check:
        print(f"해시 확인 — 달라진 자료 {drifted}건, 찾을 수 없는 자료 {missing}건")
        return 1 if (drifted or missing) else 0
    print(f"해시 기록 {changed}건, 찾을 수 없는 자료 {missing}건")
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
