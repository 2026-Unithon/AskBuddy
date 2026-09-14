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
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import asyncpg  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=True)

from app.config import get_settings  # noqa: E402

from app.team.extraction import (  # noqa: E402
    VERDICT_RANK as RANK,
    decide_majority as decide,
    decide_unanimous as decide_strict,
)


async def fetch_group(conn, slug: str, prefix: str) -> tuple[list[int], dict]:
    """라벨 접두사가 같은 실행들을 한 실험군으로 묶는다.

    **실패한 실행도 센다.** 성공한 실행만 모으면 절반씩 깨지는 설정이 멀쩡해
    보인다 — 실패는 그 설정의 성질이지 없던 일이 아니다 (D17).
    """
    attempts = await conn.fetch(
        """
        select n.run_id, n.status, n.card_count, n.settings
        from extraction_runs n
        join stores s on s.store_id = n.store_id
        where s.store_slug = $1
          -- 반복 실행은 "라벨#1" 또는 "라벨-1" 로 남는다. **반복 번호만** 묶는다 —
          -- like '라벨-%' 로 잡으면 "라벨-v2" 같은 다른 실험군까지 빨아들인다
          and (n.label = $2 or n.label ~ ('^' || $2 || '[#-][0-9]+$'))
        """,
        slug, prefix,
    )
    rows = await conn.fetch(
        """
        select n.run_id, r.fact_id, r.verdict, r.must_have, r.source_type,
               r.subject, r.variant, r.attribute
        from extraction_results r
        join extraction_runs n on n.run_id = r.run_id
        join stores s on s.store_id = n.store_id
        where s.store_slug = $1 and n.status = 'SUCCEEDED'
          -- 카드 0장 실행은 측정이 아니다. 이력은 남기되 집계에서 뺀다
          and coalesce(n.card_count, 0) > 0
          and (n.label = $2 or n.label ~ ('^' || $2 || '[#-][0-9]+$'))
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

    failed = sorted(int(a["run_id"]) for a in attempts
                    if a["status"] != "SUCCEEDED" or not (a["card_count"] or 0))
    # 설정이 실행마다 다르면 같은 실험군이 아니다. 결과를 설정에 귀속시킬 수 없다
    fingerprints = {_settings_hash(a["settings"]) for a in attempts
                    if a["status"] == "SUCCEEDED" and (a["card_count"] or 0)}
    return sorted(runs), {
        "verdicts": dict(per_fact), "meta": meta,
        "attempts": len(attempts), "failed": failed,
        "settings_hashes": sorted(fingerprints),
    }


def _settings_hash(settings) -> str:
    """실행 설정의 지문. 스윕 값이 섞인 실행을 한 군으로 묶지 않기 위해서다."""
    if not settings:
        return "none"
    if isinstance(settings, str):
        settings = json.loads(settings)
    # 캠페인 메모는 설정이 아니다. 같은 설정인지만 본다
    payload = {k: v for k, v in sorted(settings.items()) if k != "campaign"}
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()[:12]


async def main() -> int:
    ap = argparse.ArgumentParser(description="실험군 간 사실 단위 비교")
    ap.add_argument("--store", required=True)
    ap.add_argument("--a", required=True, help="기준군 라벨 (접두사)")
    ap.add_argument("--b", required=True, help="비교군 라벨 (접두사)")
    ap.add_argument("--detail", action="store_true", help="뒤집힌 사실을 전부 나열한다")
    ap.add_argument("--control", action="store_true",
                    help="이 비교가 A/A 대조군이다. 승패를 선언하지 않고 잡음 바닥만 낸다")
    ap.add_argument("--noise", type=int, default=None,
                    help="A/A 대조에서 관측한 순증의 절댓값. 승격 문턱 계산에 쓴다 (D18)")
    args = ap.parse_args()

    for label in (args.a, args.b):
        if re.search(r"[.^$*+?()\[\]{}|\\]", label):
            print(f"라벨에 정규식 특수문자를 쓰지 않는다: {label}", file=sys.stderr)
            return 1

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
    # 매장 이름(store-a·store-b)과 헷갈리지 않게 '군' 으로 적는다.
    # 두 군은 같은 매장·같은 자료이고 라벨만 다르다
    left, right = ("1회차", "2회차") if args.control else ("기준군", "비교군")
    print(f"  {left}  {args.a:<18} run {runs_a}")
    print(f"  {right}  {args.b:<18} run {runs_b}")
    print()

    # ── 분모 고정 ────────────────────────────────────────────────────────
    # 교집합으로 세면 한쪽에서 사라진 사실이 조용히 빠져 분모가 줄고, 남은 것만으로
    # 계산한 비율이 좋아 보인다. 정답지 전체를 분모로 쓴다 (D17).
    truth_path = (Path(__file__).resolve().parents[1] / "eval" / "data"
                  / args.store / "truth" / "facts.json")
    truth_ids = [f["fact_id"] for f in
                 json.loads(truth_path.read_text(encoding="utf-8"))["facts"]]
    denominator = len(truth_ids)
    shared = sorted(set(A["verdicts"]) & set(B["verdicts"]))
    absent = sorted(set(truth_ids) - set(shared))

    for name, group in ((args.a, A), (args.b, B)):
        if group["failed"]:
            print(f"  ⚠ {name}: 실패한 실행 {len(group['failed'])}회 "
                  f"(run {group['failed']}) — 실패도 그 설정의 결과다")
        if len(group["settings_hashes"]) > 1:
            print(f"  ⚠ {name}: 실행마다 설정이 다르다 {group['settings_hashes']} "
                  f"— 결과를 설정에 귀속시킬 수 없다")
    if absent:
        print(f"  ⚠ 두 군 모두에 판정이 없는 정답 {len(absent)}/{denominator}건. "
              f"분모에는 남긴다: {absent[:6]}{'…' if len(absent) > 6 else ''}")
    print()
    # ── 짝비교 ──────────────────────────────────────────────────────────
    # **만장일치가 기준이다.** 3회 반복의 다수결은 2:1 도 '안정' 으로 치는데,
    # 2:1 과 1:2 가 맞붙으면 순수한 잡음이 '개선 1건' 으로 기록된다.
    # 실측이 그랬다 — 같은 설정 두 묶음에서 다수결로 10건이 뒤집혔지만
    # 만장일치로는 단 한 건도 바뀌지 않았다.
    #
    # 대신 **흔들려서 빼둔 건수를 반드시 함께 낸다.** 엄격한 기준은 진짜 작은
    # 악화도 같이 가리므로, 얼마나 가렸는지 안 보이면 이번엔 반대로 속는다.
    improved, worsened, same = [], [], 0
    wobbly = []          # 한쪽이라도 3회가 갈린 사실. 판정하지 않고 세어만 둔다
    for fid in shared:
        va, sa = decide_strict(A["verdicts"][fid])
        vb, sb = decide_strict(B["verdicts"][fid])
        if not (sa and sb):
            wobbly.append((fid, A["verdicts"][fid], B["verdicts"][fid]))
            continue
        if RANK[vb] > RANK[va]:
            improved.append((fid, va, vb))
        elif RANK[vb] < RANK[va]:
            worsened.append((fid, va, vb))
        else:
            same += 1

    judged = len(shared) - len(wobbly)
    net = len(improved) - len(worsened)

    print(f"  분모 {denominator}건 (정답지 전체)")
    print(f"  ├ 만장일치 판정 {judged}건  — 3회가 양쪽 모두 같은 답")
    print(f"  ├ 흔들림     {len(wobbly)}건  — 3회가 갈려 판정하지 않음")
    print(f"  └ 양쪽 미판정 {len(absent)}건")
    if judged and len(wobbly) > judged:
        # 판정한 것보다 가린 것이 많으면 이 비교로는 아무 말도 할 수 없다
        print(f"  ⚠ 흔들린 사실이 판정한 사실보다 많다. 반복을 늘려야 한다 "
              f"(지금 군별 {min(len(runs_a), len(runs_b))}회)")
    print()
    print(f"  개선  {len(improved):>3}건   {right} 에서 판정이 올라감")
    print(f"  악화  {len(worsened):>3}건   {right} 에서 판정이 내려감")
    print(f"  동일  {same:>3}건")
    print(f"  ── 순증 {net:+}건  (만장일치 기준)")
    print()

    # 다수결로 세면 어떻게 나오는지 참고로만 보여준다. 판정에는 쓰지 않는다
    m_imp = m_wor = m_wob = 0
    for fid in shared:
        va, sa = decide(A["verdicts"][fid])
        vb, sb = decide(B["verdicts"][fid])
        if not (sa and sb):
            m_wob += 1
            continue
        if RANK[vb] > RANK[va]:
            m_imp += 1
        elif RANK[vb] < RANK[va]:
            m_wor += 1
    print(f"  (참고) 다수결로 세면 — 개선 {m_imp} · 악화 {m_wor} "
          f"· 순증 {m_imp - m_wor:+}건. 판정에는 쓰지 않는다")
    print()

    # ── 판정 ────────────────────────────────────────────────────────────
    if args.control:
        # A/A 대조는 같은 설정이다. 여기서 나온 차이는 전부 잡음이고,
        # 우열을 말하는 순간 잡음을 성과로 읽기 시작한다
        flips = len(improved) + len(worsened)
        threshold = max(5, round(abs(net) * 1.5))
        print("판정: **대조군이다. 승패는 없다.**")
        print(f"  같은 설정인데 만장일치 기준으로 {flips}건이 뒤집혔다 "
              f"(순증 {net:+}건).")
        print(f"  → 잡음 바닥 {abs(net)}건. 승격 문턱은 순증 {threshold}건 이상 "
              f"(D18: 대조군 폭 × 1.5, 최소 5건)")
        print(f"  흔들림 {len(wobbly)}건은 판정에서 뺐다 — 이만큼은 이 비교로 "
              f"아무 말도 못 한다")
        print(f"  다음 실험부터 --noise {abs(net)} 를 붙인다")
    elif args.noise is None:
        print(f"판정: 보류 — 순증 {net:+}건이지만 **잡음 바닥을 모른다.**")
        print("  같은 설정으로 A/A 대조를 먼저 돌린다:")
        print(f"    python scripts/run_baseline.py --store {args.store}")
        print("  그 결과를 --noise 로 넘겨야 승격 여부를 말할 수 있다 (D18)")
    else:
        threshold = max(5, round(args.noise * 1.5))
        if abs(net) < threshold:
            print(f"판정: 승격하지 않는다. 순증 {net:+}건이 문턱 {threshold}건에 못 미친다.")
            print(f"  대조군 폭 {args.noise}건 × 1.5 = {threshold}건 (D18)")
        else:
            direction = right if net > 0 else left
            print(f"판정: {direction} 승격 후보 (순증 {net:+}건 ≥ 문턱 {threshold}건).")
            print("  must_have 악화 0건·원장 재현율 비하락·3회 중 2회 같은 방향을 "
                  "함께 확인한다 (D18)")

    # must_have 는 D18 의 게이트다. 여기도 같은 기준으로 세고 흔들림을 함께 낸다
    mh_imp = sum(1 for f, _, _ in improved if A["meta"][f]["must_have"])
    mh_wor = sum(1 for f, _, _ in worsened if A["meta"][f]["must_have"])
    mh_wob = sum(1 for f, _, _ in wobbly if A["meta"][f]["must_have"])
    print(f"  필수(must_have) — 개선 {mh_imp}건 · 악화 {mh_wor}건 "
          f"· 흔들림 {mh_wob}건")
    if mh_wor == 0 and mh_wob:
        print(f"    악화 0건이지만 {mh_wob}건은 흔들려서 판정하지 못했다. "
              f"'악화 없음' 이 '확인했다' 는 뜻은 아니다")

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
