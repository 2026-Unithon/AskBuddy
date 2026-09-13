"""평가 자료의 manifest·사실 정답지를 검증한다.

  python scripts/check_eval_data.py                 # 전체 매장
  python scripts/check_eval_data.py --store store-a

손으로 쓰는 JSON 은 반드시 깨진다. 라벨링을 한참 한 뒤에 발견하면 다시 해야 하므로
쓰는 중에 자주 돌린다. 위반이 있으면 종료 코드 1.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[1] / "eval" / "data"

SOURCE_TYPES = {"VIDEO", "VOICE", "SCAN", "KAKAO"}
# 자료 권위 등급 — 점주 답변 > 레시피북=최근공지 > 나머지 동등.
# 참고값일 뿐 자동 확정 근거가 아니다 (MVP 정본 5절)
AUTHORITY = {"OWNER_ANSWER": 1, "RECIPE_BOOK": 2, "NOTICE": 2, "OTHER": 3}
LOCATOR_TYPES = {"PAGE", "TIMESTAMP", "LINE", "WHOLE_SOURCE"}

# 브랜드명이 새어 들어가는 것을 막는다. 익명 slug 만 쓴다
_BRAND_HINT = re.compile(r"[가-힣A-Za-z]{2,}\s*(커피|카페|coffee|cafe)\b", re.I)


def _fail(problems: list[str], msg: str) -> None:
    problems.append(msg)


def check_manifest(path: Path, problems: list[str]) -> dict[str, str]:
    """source_key → type 매핑을 돌려준다."""
    try:
        m = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        _fail(problems, f"{path}: JSON 파싱 실패 — {e}")
        return {}

    if not str(m.get("store_slug", "")).startswith("eval-"):
        _fail(problems, f"{path}: store_slug 는 'eval-' 로 시작해야 한다 (익명 식별자)")
    if m.get("split") not in ("dev", "holdout"):
        _fail(problems, f"{path}: split 은 dev 또는 holdout 이어야 한다")

    keys: dict[str, str] = {}
    seen_types: set[str] = set()
    for i, src in enumerate(m.get("sources", [])):
        where = f"{path}: sources[{i}]"
        key = src.get("source_key")
        if not key:
            _fail(problems, f"{where}: source_key 가 없다")
            continue
        if key in keys:
            _fail(problems, f"{where}: source_key 중복 — {key}")
        stype = src.get("type")
        if stype not in SOURCE_TYPES:
            _fail(problems, f"{where}: type 이 {sorted(SOURCE_TYPES)} 중 하나여야 한다 (현재 {stype})")
        else:
            seen_types.add(stype)
        if src.get("authority") not in AUTHORITY:
            _fail(problems, f"{where}: authority 가 {sorted(AUTHORITY)} 중 하나여야 한다")
        rel = src.get("file")
        if not rel:
            _fail(problems, f"{where}: file 경로가 없다")
        elif not (path.parent / rel).exists():
            _fail(problems, f"{where}: 파일이 없다 — {rel}")
        keys[key] = stype or "?"

    missing = SOURCE_TYPES - seen_types
    if missing:
        _fail(
            problems,
            f"{path}: source type 이 빠졌다 — {sorted(missing)}. "
            f"4개 유형을 전부 포함해야 유형별 추출 손실을 잴 수 있다 (13.1)",
        )
    return keys


def check_facts(path: Path, source_keys: dict[str, str], problems: list[str]) -> int:
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        _fail(problems, f"{path}: JSON 파싱 실패 — {e}")
        return 0

    if d.get("schema") != "facts/v1":
        _fail(problems, f"{path}: schema 는 'facts/v1' 이어야 한다")
    if not d.get("judged_by") or d.get("judged_by") == "TODO":
        _fail(problems, f"{path}: judged_by 를 채운다. 누가 정한 정답인지 남겨야 이견을 푼다")
    if not d.get("judged_at"):
        _fail(problems, f"{path}: judged_at 을 채운다")
    if not d.get("owner_confirmed"):
        _fail(
            problems,
            f"{path}: owner_confirmed 가 false 다. "
            f"매장 사실 관계는 점주 확인이 필수다 (13.1)",
        )

    ids: set[str] = set()
    facts = d.get("facts", [])
    for i, f in enumerate(facts):
        where = f"{path}: facts[{i}]"
        fid = f.get("fact_id")
        if not fid:
            _fail(problems, f"{where}: fact_id 가 없다")
        elif fid in ids:
            _fail(problems, f"{where}: fact_id 중복 — {fid}")
        else:
            ids.add(fid)

        for field in ("subject", "attribute", "value"):
            if not f.get(field):
                _fail(problems, f"{where}: {field} 가 비었다")
        if not isinstance(f.get("must_have"), bool):
            _fail(problems, f"{where}: must_have 는 true/false 여야 한다")

        key = f.get("source_key")
        if key not in source_keys:
            _fail(problems, f"{where}: manifest 에 없는 source_key — {key}")

        loc = f.get("locator") or {}
        ltype = loc.get("type")
        if ltype not in LOCATOR_TYPES:
            _fail(problems, f"{where}: locator.type 이 {sorted(LOCATOR_TYPES)} 중 하나여야 한다")
        elif ltype == "TIMESTAMP" and not isinstance(loc.get("timestamp_sec"), (int, float)):
            _fail(problems, f"{where}: TIMESTAMP 에는 timestamp_sec 가 필요하다")
        elif ltype == "PAGE" and not isinstance(loc.get("page"), int):
            _fail(problems, f"{where}: PAGE 에는 page 가 필요하다")

        if ltype in ("TIMESTAMP",) and source_keys.get(key) not in ("VIDEO", "VOICE"):
            _fail(problems, f"{where}: TIMESTAMP locator 는 VIDEO·VOICE 자료에만 쓴다")

    # 같은 이름 다른 규격이 구분되는가 — 합치면 안 되는 쌍을 놓치지 않기 위한 검사
    by_subject: dict[str, set[str]] = {}
    for f in facts:
        by_subject.setdefault(f.get("subject", ""), set()).add(f.get("variant") or "")
    for subject, variants in by_subject.items():
        if len(variants) > 1 and "" in variants:
            _fail(
                problems,
                f"{path}: '{subject}' 에 variant 가 있는 사실과 없는 사실이 섞여 있다. "
                f"규격이 갈리면 전부 variant 를 채운다 (HOT/ICE 가 합쳐지는 것을 막는다)",
            )
    return len(facts)


def check_brand_leak(store_dir: Path, problems: list[str]) -> None:
    """JSON 안에 브랜드명이 새어 들어갔는지 본다."""
    for path in sorted(store_dir.rglob("*.json")):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            m = _BRAND_HINT.search(line)
            if m:
                _fail(
                    problems,
                    f"{path}:{lineno}: 브랜드·상호로 보이는 표현 '{m.group(0).strip()}'. "
                    f"익명 slug 만 쓴다 (CLAUDE.md)",
                )


def main() -> int:
    ap = argparse.ArgumentParser(description="평가 자료 검증")
    ap.add_argument("--store", default=None, help="예: store-a (기본: 전체)")
    args = ap.parse_args()

    if not DATA_DIR.exists():
        print(f"{DATA_DIR} 가 없다. 먼저 자료 디렉터리를 만든다.")
        return 1

    stores = [DATA_DIR / args.store] if args.store else sorted(
        d for d in DATA_DIR.iterdir() if d.is_dir()
    )
    problems: list[str] = []
    total_facts = 0

    for store_dir in stores:
        manifest = store_dir / "manifest.json"
        facts = store_dir / "truth" / "facts.json"
        if not manifest.exists():
            _fail(problems, f"{store_dir}: manifest.json 이 없다")
            continue
        keys = check_manifest(manifest, problems)
        if facts.exists():
            total_facts += check_facts(facts, keys, problems)
        else:
            print(f"  {store_dir.name}: truth/facts.json 아직 없음 (라벨링 전)")
        check_brand_leak(store_dir, problems)

    print(f"\n매장 {len(stores)}개 · 사실 {total_facts}건")
    if not problems:
        print("문제 없음")
        return 0
    print(f"\n문제 {len(problems)}건:\n")
    for p in problems:
        print(f"  {p}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
