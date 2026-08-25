"""로컬 개발용 JWT 발급. 관호님 /auth 가 붙기 전까지 쓴다.

    python scripts/dev_token.py                 # demo-cafe 점주 토큰
    python scripts/dev_token.py --slug demo-cafe --role OWNER

인증을 우회하는 엔드포인트를 만들지 않기 위한 스크립트다.
store_id 는 JWT 에서만 나와야 한다 (D1). ENV=local 에서만 쓴다.
"""
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import asyncpg  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.deps import create_token  # noqa: E402


async def mint(slug: str = "demo-cafe", role: str = "OWNER") -> str:
    """시드 매장의 토큰을 만든다. 다른 스크립트에서도 import 해서 쓴다."""
    s = get_settings()
    if s.env != "local":
        raise RuntimeError(f"ENV={s.env} — 이 함수는 local 에서만 쓴다")

    conn = await asyncpg.connect(s.supabase_db_url)
    try:
        row = await conn.fetchrow(
            "select s.store_id, m.user_id, m.member_id "
            "from stores s "
            "join store_members m on m.store_id = s.store_id and m.member_role = $2 "
            "where s.store_slug = $1 limit 1",
            slug, role,
        )
    finally:
        await conn.close()

    if row is None:
        raise LookupError(
            f"'{slug}' 매장의 {role} 를 찾지 못했다. db/002_seed_demo.sql 를 먼저 적용하라"
        )

    return create_token({
        "store_id": row["store_id"],
        "user_id": row["user_id"],
        "member_id": row["member_id"],
        "role": role,
    })


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", default="demo-cafe")
    ap.add_argument("--role", default="OWNER", choices=["OWNER", "STAFF"])
    args = ap.parse_args()

    try:
        print(await mint(args.slug, args.role))
    except (RuntimeError, LookupError) as e:
        print(e, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
