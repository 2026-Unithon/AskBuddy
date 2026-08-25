"""전사문 → 추출 결과만 본다. DB 에 쓰지 않는다.

    python scripts/extract_preview.py --file data/sample_transcript.ko.txt
    INGEST_MODE=real python scripts/extract_preview.py --file data/sample_transcript.ko.txt

프롬프트를 고칠 때 이걸로 돌린다. `api/prompts/extract_cards.ko.txt` 만 고치면 된다.
카드를 DB 에 넣어보려면 set_transcript.py 로 주입한 뒤 /ingest/process 를 친다.
"""
import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import asyncpg  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.ingest.extract import extract_cards  # noqa: E402

THRESHOLD_NOTE = "검수 우선 노출"


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", type=Path, required=True)
    ap.add_argument("--slug", default="demo-cafe")
    ap.add_argument("--source-type", default="VOICE",
                    choices=["VOICE", "VIDEO", "KAKAO", "SCAN"])
    ap.add_argument("--json", action="store_true", help="원본 JSON 만 출력")
    args = ap.parse_args()

    text = args.file.read_text(encoding="utf-8").strip()
    s = get_settings()

    conn = await asyncpg.connect(s.supabase_db_url)
    try:
        store_id = await conn.fetchval(
            "select store_id from stores where store_slug = $1", args.slug)
        if store_id is None:
            print(f"'{args.slug}' 매장이 없다", file=sys.stderr)
            return 1
        cats = [r["category_name"] for r in await conn.fetch(
            "select category_name from task_categories "
            "where store_id = $1 and is_enabled = true order by sort_order", store_id)]
        gloss = [dict(r) for r in await conn.fetch(
            "select term, variants, description from store_glossary where store_id = $1",
            store_id)]
    finally:
        await conn.close()

    result = await extract_cards(
        source_id=0, source_type=args.source_type, text=text,
        category_names=cats, glossary=gloss,
    )

    if args.json:
        print(json.dumps(result.model_dump(), ensure_ascii=False, indent=2))
        return 0

    print(f"모드 {s.ingest_mode} · 허용 카테고리 {cats} · 용어 {len(gloss)}건")
    print(f"전사문 {len(text)}자 → 카드 {len(result.cards)}건\n")

    threshold = s.confidence_threshold
    for i, c in enumerate(result.cards, 1):
        flag = f"  ← {THRESHOLD_NOTE} (D3 {threshold} 미만)" if c.confidence < threshold else ""
        known = "" if c.category_name in cats else "  ⚠ 허용 목록 밖!"
        print(f"[{i}] {c.title}  ({c.confidence:.2f}){flag}")
        print(f"    카테고리: {c.category_name}{known}")
        print(f"    {c.content}")
        for f in c.facts:
            print(f"      · {f.object_name} / {f.attribute} = {f.value}  ({f.confidence:.2f})")
        print()

    if result.unresolved:
        print("확인 불가 (카드로 만들지 않음):")
        for u in result.unresolved:
            print(f"  - {u}")

    bad = [c.category_name for c in result.cards if c.category_name not in cats]
    if bad:
        print(f"\n⚠ 허용 목록에 없는 카테고리 {set(bad)} — 프롬프트를 조여야 한다")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
