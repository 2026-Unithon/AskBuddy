"""DEPRECATED — /auth 가 붙었으므로 기본 실행은 비활성화되어 있다.

정식 토큰 발급 (권장):
  POST /auth/login   { "email", "password", "role": "OWNER"|"STAFF" }
  POST /auth/signup → POST /auth/stores   (신규 점주)
  POST /auth/join                         (알바 + 초대코드)
시드: owner@demo.cafe / demo1234  role=OWNER

이 스크립트는 로컬 하위 호환용이다. 쓰려면 명시적으로 허용해야 한다.

  ALLOW_DEV_TOKEN=1 python scripts/dev_token.py
  python scripts/dev_token.py --force
  python scripts/dev_token.py --force --slug demo-cafe --role OWNER

인증 우회 HTTP 엔드포인트는 만들지 않는다. store_id 는 JWT 에만 넣는다 (D1).
ENV=local 에서만 동작한다.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import asyncpg  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.deps import create_token  # noqa: E402

_DISABLE_MSG = (
    "dev_token.py 는 비활성화되어 있다. "
    "POST /auth/login 을 사용하라 (예: owner@demo.cafe / demo1234, role=OWNER). "
    "로컬 임시 발급이 필요하면 ALLOW_DEV_TOKEN=1 또는 --force."
)


def _allowed(force: bool = False) -> bool:
    if force:
        return True
    return os.environ.get("ALLOW_DEV_TOKEN", "").strip() in ("1", "true", "TRUE", "yes")


async def mint(
    slug: str = "demo-cafe",
    role: str = "OWNER",
    *,
    force: bool = False,
) -> str:
    """시드 매장 JWT. 기본 거부. force=True 또는 ALLOW_DEV_TOKEN=1 일 때만 발급."""
    if not _allowed(force):
        raise RuntimeError(_DISABLE_MSG)

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
            slug,
            role,
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
    ap = argparse.ArgumentParser(
        description="DEPRECATED. 기본 비활성. --force 또는 ALLOW_DEV_TOKEN=1 필요.",
    )
    ap.add_argument("--slug", default="demo-cafe")
    ap.add_argument("--role", default="OWNER", choices=["OWNER", "STAFF"])
    ap.add_argument(
        "--force",
        action="store_true",
        help="비활성화를 무시하고 발급 (로컬 임시용)",
    )
    args = ap.parse_args()

    try:
        print(await mint(args.slug, args.role, force=args.force))
    except (RuntimeError, LookupError) as e:
        print(e, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
