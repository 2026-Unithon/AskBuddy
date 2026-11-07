"""한 번 호출 추출 시험 세트를 만든다 (영상 제외).

평가 매장 자료(api/eval/data/store-*)를 자료 하나 = 사례 하나로 나누고, 사실 정답지를 자료별로 떼어 낸다.
합성 사장님 글(eval/single_call/owner_texts.json)과 합성 사진·카톡 캡처·글자 PDF(rendered_cases.json)도 사례로 더한다.

    cd api && python scripts/build_single_call_set.py --stores <평가 자료 폴더> --out eval/data/single-call-set

출력은 Git 제외 경로에만 둔다. 매장 식별자는 익명 slug 뿐이다.
"""
import argparse
import json
import shutil
from pathlib import Path

from render_single_call_cases import render_all

# 영상은 이번 시험 범위 밖(2026-10-16 잠정 보류)
SKIP_TYPES = {"VIDEO"}
FORMAT_OF = {"SCAN": "DOC_IMAGE", "KAKAO": "CHAT", "VOICE": "AUDIO_TRANSCRIPT", "DOC": "DOC_TEXT"}
# 자료별 주된 로직(보고용 묶음). 사실 하나하나의 로직이 아니다. 키는 source_key 의 마지막 조각
LOGIC_OF = {
    "recipebook": "RECIPE",
    "basestock": "RECIPE",
    "notice": "POLICY",
    "worklog": "MIXED",
    "handover": "MIXED",
    "closing": "PROCEDURE",
    "stock": "PROCEDURE",
    "service": "POLICY",
    "cleaning": "PROCEDURE",
    "checklist": "PROCEDURE",
    "hygiene": "POLICY",
    "timesheet": "REFERENCE",
}


def build_store_cases(stores: Path, out: Path) -> None:
    for store_dir in sorted(stores.glob("store-*")):
        manifest = json.loads((store_dir / "manifest.json").read_text(encoding="utf-8"))
        truth = json.loads((store_dir / "truth" / "facts.json").read_text(encoding="utf-8"))
        menu_map = store_dir / "MENU_MAP.json"
        for src in manifest["sources"]:
            if src["type"] in SKIP_TYPES:
                continue
            key = src["source_key"]
            case_dir = out / "cases" / key
            case_dir.mkdir(parents=True, exist_ok=True)
            source_file = store_dir / src["file"]
            meta = {
                "case_id": key,
                "origin": store_dir.name,
                "format": FORMAT_OF[src["type"]],
                "logic": LOGIC_OF[key.rsplit("-", 1)[-1]],
                "authority": src.get("authority"),
            }
            if src["type"] == "VOICE":
                # 음성은 전사본이 입력이다. 전사(whisper)는 유료라 승인 뒤 만든다
                shutil.copy2(source_file, case_dir / source_file.name)
                meta["input"] = "transcript.txt"
                meta["input_status"] = "READY" if (case_dir / "transcript.txt").exists() else "PENDING_TRANSCRIPT"
                meta["audio"] = source_file.name
            else:
                shutil.copy2(source_file, case_dir / f"input{source_file.suffix}")
                meta["input"] = f"input{source_file.suffix}"
                meta["input_status"] = "READY"
            if menu_map.exists():
                # 원본 메뉴명 → 정답지 메뉴명 치환표. 채점 때만 쓴다
                shutil.copy2(menu_map, case_dir / "MENU_MAP.json")
                meta["menu_map"] = "MENU_MAP.json"
            gold = {
                "case_id": key,
                "judged_by": truth["judged_by"],
                "judged_at": truth["judged_at"],
                "owner_confirmed": truth["owner_confirmed"],
                "facts": [f for f in truth["facts"] if f["source_key"] == key],
            }
            (case_dir / "gold.json").write_text(json.dumps(gold, ensure_ascii=False, indent=2), encoding="utf-8")
            (case_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def build_owner_text_cases(owner_texts: Path, out: Path) -> None:
    """합성 사장님 글. 상호·메뉴는 합성 이름이라 원본을 저장소에 둔다(eval/single_call/owner_texts.json)."""
    for item in json.loads(owner_texts.read_text(encoding="utf-8")):
        case_id = item["case_id"]
        case_dir = out / "cases" / case_id
        case_dir.mkdir(parents=True, exist_ok=True)
        (case_dir / "input.txt").write_text(item["text"], encoding="utf-8")
        meta = {"case_id": case_id, "origin": "synthetic", "format": "OWNER_TEXT", "logic": item["logic"],
                "input": "input.txt", "input_status": "READY"}
        facts = [{"fact_id": f"{case_id}-{i:03d}", **f, "source_key": case_id}
                 for i, f in enumerate(item["facts"], 1)]
        gold = {"case_id": case_id, "judged_by": "claude-synthetic", "judged_at": "2026-11-06",
                "owner_confirmed": "TEST", "note": "합성 글이라 정답을 글쓴이가 안다. 매장 사실 대비 수치가 아니다",
                "facts": facts}
        (case_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        (case_dir / "gold.json").write_text(json.dumps(gold, ensure_ascii=False, indent=2), encoding="utf-8")


def write_index(out: Path) -> list[dict]:
    """사례 폴더 전체를 훑어 목록을 만든다. 정답 초안(owner_confirmed=false)은 채점 대상이 아니다."""
    rows = []
    for case_dir in sorted((out / "cases").iterdir()):
        meta = json.loads((case_dir / "meta.json").read_text(encoding="utf-8"))
        gold = json.loads((case_dir / "gold.json").read_text(encoding="utf-8"))
        rows.append({**meta,
                     "gold_facts": len(gold["facts"]),
                     "gold_status": "DRAFT" if gold["owner_confirmed"] is False else "SCORABLE"})
    (out / "index.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stores", type=Path, required=True)
    ap.add_argument("--owner-texts", type=Path,
                    default=Path(__file__).resolve().parents[1] / "eval/single_call/owner_texts.json")
    ap.add_argument("--rendered", type=Path,
                    default=Path(__file__).resolve().parents[1] / "eval/single_call/rendered_cases.json")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    if (args.out / "cases").exists():
        # 사례 id 가 바뀌어도 옛 사례가 남지 않게 다시 만든다. 음성 전사본은 보존한다
        for case_dir in (args.out / "cases").iterdir():
            if not (case_dir / "transcript.txt").exists():
                shutil.rmtree(case_dir)
    build_store_cases(args.stores, args.out)
    build_owner_text_cases(args.owner_texts, args.out)
    # 합성 사진·카톡 캡처·글자 PDF (2026-11-07)
    render_all(args.rendered, args.out)
    for c in write_index(args.out):
        print(f"{c['case_id']:24} {c['format']:17} {c['logic']:10} gold={c['gold_facts']:<3} "
              f"{c['gold_status']:9} {c['input_status']}")


if __name__ == "__main__":
    main()
