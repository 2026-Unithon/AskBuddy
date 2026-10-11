"""전사문 → 추출 결과만 본다. DB 에 쓰지 않는다.

    python scripts/extract_preview.py --file data/sample_transcript.ko.txt
    INGEST_MODE=real python scripts/extract_preview.py --file data/sample_transcript.ko.txt

정식 등록과 같은 사실 추출만 본다. 카드 조립은 원장·대상 상태가 필요해 DB 경로에서만 돈다.
프롬프트는 extract_facts.ko.txt 다.
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
from app.ingest.extract import extract_facts  # noqa: E402


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

    extracted = await extract_facts(
        source_id=0, source_type=args.source_type, text=text,
        glossary=gloss,
    )
    if args.json:
        print(json.dumps(extracted.model_dump(), ensure_ascii=False, indent=2))
        return 0

    print(f"모드 {s.ingest_mode} · 허용 카테고리 {cats} · 용어 {len(gloss)}건")
    print(f"전사문 {len(text)}자 → 사실 {len(extracted.assertions)}건\n")

    for i, a in enumerate(extracted.assertions, 1):
        variant = f" [{a.as_variant()}]" if a.as_variant() else ""
        print(f"[{i}] {a.subject}{variant} / {a.attribute} = {a.value}{(' ' + a.unit) if a.unit else ''}"
              f"  ({a.confidence:.2f})")

    if extracted.unresolved:
        print("\n확인 불가 (사실로 만들지 않음):")
        for u in extracted.unresolved:
            print(f"  - {u}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
