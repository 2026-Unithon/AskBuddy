"""평가용 매장(eval-a ~ eval-e)을 만든다. SPLIT.md 의 분할을 따른다.

  python scripts/seed_eval_stores.py --dry-run
  python scripts/seed_eval_stores.py

데모 매장(demo-cafe)과 분리한다. 평가 매장에는 브랜드명·상호를 넣지 않는다.
ENV=local 에서만 동작한다. 운영 DB 에 평가 매장을 만들지 않는다.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import asyncpg  # noqa: E402

from app.config import get_settings  # noqa: E402

# SPLIT.md 가 정본이다. 여기를 고치면 SPLIT.md 도 함께 고친다
STORES = [
    ("eval-a", "평가매장 A", "dev"),
    ("eval-b", "평가매장 B", "dev"),
    ("eval-c", "평가매장 C", "holdout"),
    ("eval-d", "평가매장 D", "holdout"),
    ("eval-e", "평가매장 E", "holdout"),
]


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    s = get_settings()
    if s.env != "local":
        print(f"ENV={s.env} — 평가 매장은 로컬에서만 만든다", file=sys.stderr)
        return 1

    conn = await asyncpg.connect(s.supabase_db_url)
    try:
        owner_id = await conn.fetchval("select user_id from users order by user_id limit 1")
        if owner_id is None:
            print("users 가 비어 있다. db/002_seed_demo.sql 을 먼저 적용한다", file=sys.stderr)
            return 1

        for slug, name, split in STORES:
            existing = await conn.fetchval(
                "select store_id from stores where store_slug = $1", slug
            )
            if existing:
                print(f"  {slug:<8} 이미 있음 (store_id={existing}, {split})")
                continue
            if args.dry_run:
                print(f"  {slug:<8} 생성 예정 ({split})")
                continue
            store_id = await conn.fetchval(
                """
                insert into stores (owner_id, store_slug, store_name, business_type)
                values ($1, $2, $3, 'CAFE')
                returning store_id
                """,
                owner_id, slug, name,
            )
            print(f"  {slug:<8} 생성 (store_id={store_id}, {split})")
    finally:
        await conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
