"""사실 원장(source_facts)을 다수결 참조와 대조해 재현율과 값 충돌을 보고한다.

    python api/scripts/compare_reference.py --store store-a --source-key a-scan-recipebook \
        [--reference <path>] [--label <text>]

DB 는 읽기만 한다. 참조는 정답지가 아니다(build_consensus_reference.py 참고).
정규화·키 함수는 build_consensus_reference 것을 그대로 쓴다.
"""
from __future__ import annotations

import argparse
import asyncio
import collections
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from build_consensus_reference import blob, column, key, n, t  # noqa: E402

DATA_DIR = Path(__file__).resolve().parents[1] / "eval" / "data"
REPORT_DIR = Path(__file__).resolve().parents[1] / "eval" / "reports"
KINDS = ("PRICE", "NUM", "TXT", "STEP", "NEG")


def _name(subject) -> str:
    """대상명 정규화: 공백류를 지우고 HOT·ICE 표기를 뺀다."""
    return re.sub(r"(HOT|ICE)", "", n(subject), flags=re.I)


def _variant(v, subject=None) -> str:
    """variant 가 비어 있으면 대상명 글에 적힌 HOT/ICE 에서 읽는다."""
    out = n(v).upper()
    if not out and subject:
        m = re.search(r"(HOT|ICE)", n(subject), flags=re.I)
        out = m.group(1).upper() if m else ""
    return out


def _num_in(needle: str, text: str) -> bool:
    """숫자 바늘은 앞뒤에 숫자·소수점이 붙지 않은 자리에서만 맞춘다. 천 단위 쉼표는 지운다."""
    text = re.sub(r"(?<=\d),(?=\d)", "", text)
    return re.search(r"(?<![\d.])" + re.escape(needle) + r"(?!\d|\.\d)", text) is not None


def _needle(kk) -> str:
    """참조 키에서 원장 원문 안을 찾을 바늘을 만든다."""
    if kk[0] == "PRICE":
        return t(kk[1])
    if kk[0] == "NUM":
        return t(kk[1] + kk[2].replace("회", "번"))
    if kk[0] == "STEP":
        return t(kk[2])
    if kk[0] == "TXT":
        return t(kk[1])
    return ""


def _row_tables(reference_results):
    """참조에서 (대상명, variant) → row, 대상명 → row 집합."""
    exact, by_name = {}, collections.defaultdict(set)
    foot = collections.defaultdict(set)
    for f in reference_results:
        row = (f.get("consensus") or {}).get("row")
        nm = _name(f.get("subject"))
        if row == "각주":
            foot[nm].add(row)
        elif isinstance(row, int):
            exact.setdefault((nm, _variant(f.get("variant"), f.get("subject"))), row)
            by_name[nm].add(row)
    return exact, by_name, foot


def _find_row(fact, exact, by_name, foot=None):
    row = _find_menu_row(fact, exact, by_name)
    if row is None and foot:
        row = _find_menu_row(fact, {}, foot)
    return row


def _find_menu_row(fact, exact, by_name):
    nm = _name(fact.get("subject"))
    var = _variant(fact.get("variant"), fact.get("subject"))
    if (nm, var) in exact:
        return exact[(nm, var)]
    if nm in by_name:
        rows = by_name[nm]
        return next(iter(rows)) if len(rows) == 1 else None
    # 한쪽이 다른 쪽을 포함(2글자 이상). 후보가 여럿이면 모호해서 연결하지 않는다
    rows = set()
    for other, rs in by_name.items():
        short, long_ = sorted((nm, other), key=len)
        if len(short) >= 2 and short in long_:
            rows |= rs
    return next(iter(rows)) if len(rows) == 1 else None


def _recalled(kk, ref_fact, ledger_facts) -> bool:
    kind = kk[0]
    if kind == "NEG":
        return any(x.get("polarity") == "NEGATE" and column(x.get("attribute")) == kk[1]
                   for x in ledger_facts)
    nd = _needle(kk)
    for x in ledger_facts:
        if kind in ("PRICE", "NUM"):
            if key(x) == kk or (nd and _num_in(nd, blob(x))):
                return True
        elif nd and nd in blob(x):
            return True
    return False


def compare(reference_results: list[dict], ledger: list[dict]) -> dict:
    exact, by_name, foot = _row_tables(reference_results)

    ledger_by_row = collections.defaultdict(list)
    unmapped = collections.Counter()
    mapped = 0
    for x in ledger:
        row = _find_row(x, exact, by_name, foot)
        if row is None:
            unmapped[_name(x.get("subject"))] += 1
        else:
            mapped += 1
            ledger_by_row[row].append(x)

    by_kind = {k: {"total": 0, "recalled": 0} for k in KINDS}
    by_scope = {"메뉴": {"total": 0, "recalled": 0}, "각주": {"total": 0, "recalled": 0}}
    rows_total, rows_touched = set(), set()
    missed = []
    for f in reference_results:
        kk = key(f)
        if not kk:
            continue
        row = (f.get("consensus") or {}).get("row")
        hit = _recalled(kk, f, ledger_by_row.get(row, []))
        scope = by_scope["각주" if row == "각주" else "메뉴"]
        scope["total"] += 1
        scope["recalled"] += int(hit)
        by_kind[kk[0]]["total"] += 1
        if isinstance(row, int):
            rows_total.add(row)
        if hit:
            by_kind[kk[0]]["recalled"] += 1
            if isinstance(row, int):
                rows_touched.add(row)
        else:
            missed.append((row, kk[0], f.get("original_assertion")))

    total = sum(v["total"] for v in by_kind.values())
    recalled = sum(v["recalled"] for v in by_kind.values())
    missed.sort(key=lambda m: (str(m[0]).zfill(4)))

    # 값 충돌: 같은 row·칸에 단위가 같은 참조 값이 있는데 하나도 일치하지 않는 원장 NUM
    ref_nums = collections.defaultdict(list)
    for f in reference_results:
        kk, row = key(f), (f.get("consensus") or {}).get("row")
        if kk and kk[0] == "NUM" and isinstance(row, int):
            ref_nums[(row, column(f.get("attribute")), kk[2])].append(kk[1])
    conflicts = []
    for row, facts in ledger_by_row.items():
        for x in facts:
            kk = key(x)
            if not kk or kk[0] != "NUM":
                continue
            refs = ref_nums.get((row, column(x.get("attribute")), kk[2]))
            if refs and kk[1] not in refs:
                conflicts.append({"row": row, "ledger_value": kk[1] + kk[2],
                                  "reference_values": sorted(set(refs)),
                                  "original_assertion": x.get("original_assertion")})

    return {
        "reference_total": total,
        "recalled": recalled,
        "recall": round(recalled / total, 3) if total else 0.0,
        "by_kind": by_kind,
        "by_scope": by_scope,
        "menu_rows_total": len(rows_total),
        "menu_rows_touched": len(rows_touched),
        "price_recalled": by_kind["PRICE"]["recalled"],
        "ledger_total": len(ledger),
        "ledger_mapped": mapped,
        "ledger_unmapped": len(ledger) - mapped,
        "unmapped_subjects": unmapped.most_common(20),
        "conflicts": conflicts,
        "missed_examples": missed[:30],
    }


# ── CLI ────────────────────────────────────────────────────────────────────

def _jsonb(v):
    if isinstance(v, str):
        try:
            return json.loads(v)
        except ValueError:
            return [v]
    return v or []


async def _load_ledger(db_url: str, slug: str, source_key: str) -> list[dict]:
    import asyncpg

    conn = await asyncpg.connect(db_url, statement_cache_size=0)
    try:
        store_id = await conn.fetchval("select store_id from stores where store_slug = $1", slug)
        if store_id is None:
            raise SystemExit(f"매장 {slug} 없음")
        rows = await conn.fetch(
            """select f.subject, f.variant, f.attribute, f.value, f.unit, f.polarity,
                      f.conditions, f.exceptions, f.step_order, f.original_assertion
                 from source_facts f
                 join sources s on s.source_id = f.source_id and s.store_id = f.store_id
                where f.store_id = $1 and s.store_id = $1 and s.title = $2
                  and f.is_superseded is not true
                order by f.fact_id""",
            store_id, source_key)
    finally:
        await conn.close()
    out = []
    for r in rows:
        d = dict(r)
        d["conditions"], d["exceptions"] = _jsonb(d["conditions"]), _jsonb(d["exceptions"])
        out.append(d)
    return out


def _markdown(res, meta) -> str:
    L = ["# 참조 대조", ""]
    L += [f"- {k}: {v}" for k, v in meta.items()]
    L += ["", "## 지표", "", "| 항목 | 값 |", "|---|---|"]
    for k in ("reference_total", "recalled", "recall", "menu_rows_total", "menu_rows_touched",
              "price_recalled", "ledger_total", "ledger_mapped", "ledger_unmapped"):
        L.append(f"| {k} | {res[k]} |")
    L += ["", "| 종류 | 참조 | 재현 |", "|---|---|---|"]
    L += [f"| {k} | {v['total']} | {v['recalled']} |" for k, v in res["by_kind"].items()]
    L += ["", "| 범위 | 참조 | 재현 |", "|---|---|---|"]
    L += [f"| {k} | {v['total']} | {v['recalled']} |" for k, v in res["by_scope"].items()]
    L += ["", f"## 값 충돌 후보 ({len(res['conflicts'])})", ""]
    L += [f"- row {c['row']}: 원장 {c['ledger_value']} / 참조 {c['reference_values']} / {c['original_assertion']}"
          for c in res["conflicts"]]
    L += ["", "## 누락 예시 (row 순 앞 30)", ""]
    L += [f"- row {r} [{k}] {a}" for r, k, a in res["missed_examples"]]
    L += ["", "## 연결 안 된 대상명 상위", ""]
    L += [f"- {s}: {c}" for s, c in res["unmapped_subjects"]]
    return "\n".join(L) + "\n"


def main():
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=True)
    from app.config import get_settings

    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--store", required=True)
    ap.add_argument("--source-key", required=True)
    ap.add_argument("--reference")
    ap.add_argument("--label", default="")
    a = ap.parse_args()

    store_dir = DATA_DIR / a.store
    slug = json.loads((store_dir / "manifest.json").read_text())["store_slug"]
    if a.reference:
        ref_path = Path(a.reference)
    else:
        found = sorted((store_dir / "reference").glob(f"{a.source_key}__consensus*__*.json"),
                       key=lambda p: p.name)
        if not found:
            raise SystemExit("참조 파일이 없다")
        ref_path = found[-1]
    ref_bytes = ref_path.read_bytes()
    reference = json.loads(ref_bytes)["results"]

    s = get_settings()
    ledger = asyncio.run(_load_ledger(s.supabase_db_url, slug, a.source_key))
    res = compare(reference, ledger)

    meta = {
        "참조 파일": ref_path.name,
        "참조 sha256[:16]": hashlib.sha256(ref_bytes).hexdigest()[:16],
        "원장 사실 수": len(ledger),
        "label": a.label,
        "pdf_input_mode": s.pdf_input_mode,
        "extract_locator_hints": s.extract_locator_hints,
        "extract_truncation_split_max_depth": s.extract_truncation_split_max_depth,
    }
    print(f"재현율 {res['recalled']}/{res['reference_total']} = {res['recall']}  "
          f"메뉴행 {res['menu_rows_touched']}/{res['menu_rows_total']}  "
          f"가격 {res['price_recalled']}  원장 {res['ledger_total']} "
          f"(연결 {res['ledger_mapped']}/미연결 {res['ledger_unmapped']})  충돌 {len(res['conflicts'])}")
    for k, v in res["by_kind"].items():
        print(f"  {k}: {v['recalled']}/{v['total']}")

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base = REPORT_DIR / f"reference_compare_{a.source_key}_{stamp}"
    base.with_suffix(".json").write_text(
        json.dumps({"meta": meta, **res}, ensure_ascii=False, indent=1, default=str))
    base.with_suffix(".md").write_text(_markdown(res, meta))
    print("리포트:", base.with_suffix(".md"))


if __name__ == "__main__":
    main()
