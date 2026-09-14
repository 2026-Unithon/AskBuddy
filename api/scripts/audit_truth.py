"""정답지 감사 (W0).

  python scripts/audit_truth.py
  python scripts/audit_truth.py --json

**정답지를 믿을 수 있는지부터 확인한다.** 기준선을 재기 전에 분모가 무엇인지
합의해야 한다. 계획 문서에 `340건` 과 `278건` 이 같이 적혀 있었는데, 확인 전
합계를 확정 수치로 쓰지 않는다 — 어느 쪽이든 실제 파일이 정본이다.

보는 것:
  - 매장별 정답 수·판정자·판정일·점주 확인 상태
  - dev / holdout 분할과 **holdout 이 실제로 봉인돼 있는지**
  - 자료 유형(VIDEO·VOICE·SCAN·KAKAO) 과 범주 커버리지
  - 원본 해시가 기록돼 있는지 (같은 파일을 쓰고 있다는 증거)
  - 정답지에 상호·브랜드명이 섞이지 않았는지
  - truth 가 가리키는 source_key 가 manifest 에 실재하는지

`must_have` 는 따로 센다. 승격 판정에서 이것만은 악화가 0 이어야 한다 (D18).
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "eval" / "data"
MENU_MAP = DATA / "MENU_MAP.json"

# 익명화 뒤에도 남으면 안 되는 낱말. MENU_MAP 의 원본 키를 함께 본다
BUILT_IN_DENY = {"메가", "MEGA", "스타벅스", "STARBUCKS", "이디야", "투썸",
                 "컴포즈", "빽다방", "메가커피"}


def deny_tokens() -> set[str]:
    tokens = set(BUILT_IN_DENY)
    if MENU_MAP.exists():
        tokens |= {k for k in json.loads(MENU_MAP.read_text("utf-8")) if len(k) >= 2}
    return tokens


def audit_store(path: Path, deny: set[str]) -> dict:
    manifest = json.loads((path / "manifest.json").read_text("utf-8"))
    truth = json.loads((path / "truth" / "facts.json").read_text("utf-8"))
    facts = truth["facts"]

    sources = {s["source_key"]: s for s in manifest["sources"]}
    by_type = Counter(sources[f["source_key"]]["type"]
                      for f in facts if f["source_key"] in sources)
    dangling = sorted({f["source_key"] for f in facts if f["source_key"] not in sources})

    blob = json.dumps(truth, ensure_ascii=False) + json.dumps(manifest, ensure_ascii=False)
    leaked = sorted(t for t in deny if t in blob)

    return {
        "store": path.name,
        "slug": manifest["store_slug"],
        "split": manifest.get("split"),
        "facts": len(facts),
        "must_have": sum(1 for f in facts if f.get("must_have")),
        "judged_by": truth.get("judged_by"),
        "judged_at": truth.get("judged_at"),
        "owner_confirmed": truth.get("owner_confirmed"),
        "sources": len(sources),
        "by_type": dict(by_type),
        "missing_types": sorted({"VIDEO", "VOICE", "SCAN", "KAKAO"}
                                - {s["type"] for s in sources.values()}),
        "categories": dict(Counter(f.get("category_hint") for f in facts)),
        "no_locator": sum(1 for f in facts if not f.get("locator")),
        "sources_without_hash": sorted(k for k, s in sources.items()
                                       if not s.get("sha256")),
        "dangling_source_keys": dangling,
        "brand_leak": leaked,
        "duplicate_fact_ids": sorted(
            {i for i, n in Counter(f["fact_id"] for f in facts).items() if n > 1}),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    deny = deny_tokens()
    stores = [audit_store(p, deny) for p in sorted(DATA.iterdir())
              if (p / "manifest.json").exists()]

    if args.json:
        print(json.dumps(stores, ensure_ascii=False, indent=2))
        return 0

    total = sum(s["facts"] for s in stores)
    print(f"{'매장':<10}{'분할':>8}{'정답':>6}{'must':>6}{'자료':>5}  유형별")
    print("-" * 72)
    for s in stores:
        types = " ".join(f"{k}:{v}" for k, v in sorted(s["by_type"].items()))
        print(f"{s['store']:<10}{s['split'] or '—':>8}{s['facts']:>6}"
              f"{s['must_have']:>6}{s['sources']:>5}  {types}")
    print("-" * 72)
    print(f"{'합계':<10}{'':>8}{total:>6}"
          f"{sum(s['must_have'] for s in stores):>6}")
    print()
    print(f"**분모는 {total}건이다.** 계획 문서의 다른 수치는 확인 전 추정이었다.")
    print("  dev  ", sum(s["facts"] for s in stores if s["split"] == "dev"),
          "· holdout", sum(s["facts"] for s in stores if s["split"] == "holdout"))

    print("\n판정 이력")
    for s in stores:
        print(f"  {s['store']}: {s['judged_by']} / {s['judged_at']} / "
              f"점주확인 {s['owner_confirmed']}")

    problems = []
    for s in stores:
        for label, value in (("상호·브랜드명 노출", s["brand_leak"]),
                             ("manifest 에 없는 source_key", s["dangling_source_keys"]),
                             ("fact_id 중복", s["duplicate_fact_ids"]),
                             ("빠진 자료 유형", s["missing_types"])):
            if value:
                problems.append(f"  {s['store']} — {label}: {value}")
        if s["no_locator"]:
            problems.append(f"  {s['store']} — 근거 위치 없는 정답 {s['no_locator']}건")
        if s["sources_without_hash"]:
            problems.append(
                f"  {s['store']} — 원본 해시 없음: {s['sources_without_hash']}")

    print("\n확인 필요" if problems else "\n구조 문제 없음")
    for line in problems:
        print(line)

    print("\n점주 확인 상태가 TEST 인 정답은 '사람이 라벨링했다' 는 뜻이지")
    print("'점주가 맞다고 했다' 는 뜻이 아니다. 두 가지를 같은 칸에 적지 않는다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
