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
import hashlib
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


def _as_dict(settings) -> dict:
    if not settings:
        return {}
    return json.loads(settings) if isinstance(settings, str) else dict(settings)


def _hash_settings(settings) -> str:
    """스윕 값의 지문. 캠페인 메모는 설정이 아니므로 뺀다."""
    payload = {k: v for k, v in sorted(_as_dict(settings).items())
               if k not in ("campaign", "source_hashes")}
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()[:12]


def _hash_sources(settings) -> str:
    """입력 자료의 지문. 자료가 바뀌면 변동을 모델 탓으로 돌릴 수 없다."""
    payload = _as_dict(settings).get("source_hashes") or {}
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode()).hexdigest()[:12]


def _dig(d: dict, path: tuple[str, ...]):
    for key in path:
        if not isinstance(d, dict):
            return None
        d = d.get(key)
    return d


async def main() -> int:
    ap = argparse.ArgumentParser(description="반복 실행 변동폭")
    ap.add_argument("--store", required=True, help="store-b 또는 eval-b")
    ap.add_argument("--label-prefix", default="VAR",
                    help="실험군 라벨. 반복 번호(#1, -1)만 같은 군으로 묶는다")
    args = ap.parse_args()

    slug = args.store.replace("store-", "eval-")
    conn = await asyncpg.connect(get_settings().supabase_db_url)
    try:
        rows = await conn.fetch(
            """
            select r.run_id, r.label, r.status, r.metrics, r.card_count,
                   r.code_version, r.prompt_version, r.extract_model, r.settings
            from extraction_runs r
            join stores s on s.store_id = r.store_id
            -- 반복 번호만 한 군으로 묶는다. like 'BASE%' 로 잡으면
            -- 대조군 BASE-AA 까지 같은 군에 섞여 변동폭이 실험 차이로 오염된다
            where s.store_slug = $1
              and (r.label = $2 or r.label ~ ('^' || $2 || '[#-][0-9]+$'))
            order by r.run_id
            """,
            slug, args.label_prefix.rstrip("#-"),
        )
    finally:
        await conn.close()

    # 실패한 실행도 이 설정의 결과다. 성공만 세면 변동폭이 실제보다 좁아진다
    # 카드 0장은 성공으로 기록됐어도 측정이 아니다 (파이프라인이 돌지 않은 실행)
    def _valid(r):
        return r["status"] == "SUCCEEDED" and int(r["card_count"] or 0) > 0

    failed = [int(r["run_id"]) for r in rows if not _valid(r)]
    rows = [r for r in rows if _valid(r)]

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
    if failed:
        print(f"  ⚠ 실패한 실행 {len(failed)}회 (run {failed}) — 변동폭에 못 넣지만 "
              f"이 설정의 결과다. 실패율 {len(failed) / (len(failed) + len(runs)):.0%}")
    if len(codes) > 1 or len(prompts) > 1:
        print("  경고: 코드 또는 프롬프트 버전이 실행마다 다르다. 순수한 변동폭이 아니다")

    # 설정·입력이 같은 실행끼리만 변동폭이 의미를 갖는다
    settings_hashes = {_hash_settings(r["settings"]) for r in rows}
    if len(settings_hashes) > 1:
        print(f"  ⚠ 실행마다 설정이 다르다 {sorted(settings_hashes)} — "
              f"같은 조건의 변동폭이 아니다")
    source_hashes = {_hash_sources(r["settings"]) for r in rows}
    if len(source_hashes) > 1:
        print(f"  ⚠ 입력 자료가 실행마다 다르다 — 변동이 모델 때문인지 자료 때문인지 "
              f"가를 수 없다")
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
