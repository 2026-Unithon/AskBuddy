"""로컬 데모 계정 비밀번호를 demo1234 로 맞춘다."""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import bcrypt
from dotenv import load_dotenv
import asyncpg

load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=True)

EMAILS = {
    "데모 사장님": "owner@demo.cafe",
    "박지호": "jiho@demo.cafe",
    "김민준": "minjun@demo.cafe",
    "이서연": "seoyeon@demo.cafe",
}


async def main() -> None:
    password_hash = bcrypt.hashpw(b"demo1234", bcrypt.gensalt(rounds=12)).decode()
    conn = await asyncpg.connect(os.environ["SUPABASE_DB_URL"])
    try:
        for name, email in EMAILS.items():
            await conn.execute(
                """
                update public.users
                set email = $1, password_hash = $2
                where name = $3
                """,
                email,
                password_hash,
                name,
            )
        rows = await conn.fetch(
            "select name, email, left(password_hash, 29) as h from public.users order by user_id"
        )
        for r in rows:
            print(dict(r))
        print("hash_for_seed=", password_hash)
        print("verify=", bcrypt.checkpw(b"demo1234", password_hash.encode()))
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
