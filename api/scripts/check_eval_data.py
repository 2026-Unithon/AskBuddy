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

# 브랜드명이 새어 들어가는 것을 막는다.
# 패턴 매칭은 쓰지 않는다 — "흑임자커피" 같은 익명화된 일반 메뉴명까지 잡아서 거짓 양성만 낸다.
# 대신 MENU_MAP.json 의 원본 표현(키)을 금칙어로 삼는다. 매핑을 만들면 검사도 따라 강해진다.
MENU_MAP = "MENU_MAP.json"
# 매핑에 없더라도 항상 막는 표현
_BRAND_ALWAYS = ("메가", "스타벅스", "이디야", "투썸", "컴포즈", "빽다방", "starbucks", "ediya")


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


def _brand_terms(store_dir: Path) -> list[str]:
    """금칙어 = MENU_MAP.json 의 원본 표현 + 상시 금지 목록."""
    terms = list(_BRAND_ALWAYS)
    mapping = store_dir / MENU_MAP
    if mapping.exists():
        try:
            data = json.loads(mapping.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return terms
        terms += [k for k in data if not k.startswith("_")]
    # 긴 것부터 봐야 "왕할메가커피" 가 "메가" 로 잘리지 않는다
    return sorted(set(terms), key=len, reverse=True)


def check_brand_leak(store_dir: Path, problems: list[str]) -> None:
    """브랜드 원본 표현이 산출물에 새어 들어갔는지 본다.

    MENU_MAP.json 자체는 검사하지 않는다. 원본↔익명 매핑을 담는 것이 그 파일의 용도다.
    대신 Git 에 올라가지 않는지만 확인한다.
    """
    terms = _brand_terms(store_dir)
    targets = [
        p for p in sorted(store_dir.rglob("*"))
        if p.is_file() and p.name != MENU_MAP and p.suffix in (".json", ".md", ".txt")
    ]
    for path in targets:
        for lineno, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            for term in terms:
                if term and term.lower() in line.lower():
                    _fail(
                        problems,
                        f"{path}:{lineno}: 브랜드 표현 '{term}'. "
                        f"MENU_MAP.json 의 익명 표현으로 바꾼다 (CLAUDE.md)",
                    )
                    break

    # 파일·디렉터리 이름에도 남으면 안 된다
    for path in sorted(store_dir.rglob("*")):
        for term in terms:
            if term.lower() in path.name.lower():
                _fail(problems, f"{path}: 파일명에 브랜드 표현 '{term}' 이 있다")
                break


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
