"""평가 매장의 자료·카드를 지운다. 추출을 다시 돌리기 위한 초기화다.

  python scripts/reset_eval_store.py --store store-a --dry-run
  python scripts/reset_eval_store.py --store store-a

**평가 매장(eval-*)에서만 동작한다.** demo-cafe 나 실제 매장에는 쓰지 않는다.
평가 실행 이력(extraction_runs·evaluation_runs)은 지우지 않는다 — 그건 영구 기록이다.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import asyncpg  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=True)

from app.config import get_settings  # noqa: E402

# FK 순서대로 지운다. 자식부터 부모로
STEPS = [
    ("facts",              "delete from facts where card_id in (select card_id from knowledge_cards where store_id=$1)"),
    ("card_evidence",      "delete from card_evidence where store_id=$1"),
    ("card_review_events", "delete from card_review_events where store_id=$1"),
    ("card_embeddings",    "delete from card_embeddings where store_id=$1"),
    ("카드 버전포인터 해제", "update knowledge_cards set draft_version_id=null, published_version_id=null where store_id=$1"),
    ("card_versions",      "delete from card_versions where store_id=$1"),
    ("knowledge_cards",    "delete from knowledge_cards where store_id=$1"),
    ("ingest_job_sources", "delete from ingest_job_sources where store_id=$1"),
    ("ingest_jobs",        "delete from ingest_jobs where store_id=$1"),
    ("source_video",       "delete from source_video where source_id in (select source_id from sources where store_id=$1)"),
    ("source_voice",       "delete from source_voice where source_id in (select source_id from sources where store_id=$1)"),
    ("source_kakao",       "delete from source_kakao where source_id in (select source_id from sources where store_id=$1)"),
    ("source_scan",        "delete from source_scan where source_id in (select source_id from sources where store_id=$1)"),
    ("source_frames",      "delete from source_frames where video_id in (select video_id from source_video where source_id in (select source_id from sources where store_id=$1))"),
    ("sources",            "delete from sources where store_id=$1"),
]


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", required=True, help="eval-a 또는 store-a 형식 둘 다 받는다")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    slug = args.store.replace("store-", "eval-")
    if not slug.startswith("eval-"):
        print(f"평가 매장에서만 쓴다. eval-* 가 아니다: {slug}", file=sys.stderr)
        return 1

    conn = await asyncpg.connect(get_settings().supabase_db_url)
    try:
        store_id = await conn.fetchval("select store_id from stores where store_slug=$1", slug)
        if store_id is None:
            print(f"매장이 없다: {slug}", file=sys.stderr)
            return 1

        before = await conn.fetchrow(
            "select (select count(*) from sources where store_id=$1) as src, "
            "       (select count(*) from knowledge_cards where store_id=$1) as cards",
            store_id,
        )
        print(f"{slug} (store_id={store_id}) — 자료 {before['src']}건 · 카드 {before['cards']}장")
        if args.dry_run:
            print("dry-run. 지우지 않았다")
            return 0

        async with conn.transaction():
            for name, sql in STEPS:
                result = await conn.execute(sql, store_id)
                n = result.rsplit(" ", 1)[-1]
                if n not in ("0",):
                    print(f"  {name:<22} {n}")
        print("초기화 완료. 평가 실행 이력은 그대로 남아 있다")
    finally:
        await conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
