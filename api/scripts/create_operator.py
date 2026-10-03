"""운영자 계정 생성 (이슈 #33).

  python scripts/create_operator.py --email ops@example.com --name 운영자
  운영 서버: docker compose exec api python scripts/create_operator.py --email ... --name ...

비밀번호는 getpass 로 두 번 받는다. 인자·환경변수로 받지 않는다 (셸 기록에 남지 않게).
같은 이메일이 이미 있으면 역할을 바꾸지 않고 실패한다. 기존 점주 계정을 운영자로 승격하지 않는다.
"""
from __future__ import annotations

import argparse
import asyncio
import getpass
import sys
from collections.abc import Callable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import asyncpg  # noqa: E402
from pydantic import EmailStr, TypeAdapter, ValidationError  # noqa: E402

from app.auth.router import _hash_password  # noqa: E402
from app.config import get_settings  # noqa: E402

MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 128  # /ops/login 요청 상한과 같다
MAX_NAME_LENGTH = 50  # users.name varchar(50)


_EMAIL = TypeAdapter(EmailStr)


def normalize_email(raw: str) -> str:
    """/ops/login 과 같은 규칙으로 검증하고 소문자로 맞춘다. 로그인할 수 없는 이메일을 만들지 않는다."""
    try:
        return str(_EMAIL.validate_python(raw.strip())).lower()
    except ValidationError:
        raise SystemExit("이메일 형식이 올바르지 않다") from None


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="운영자 계정 생성")
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", required=True)
    return parser.parse_args(argv)


def read_password(prompt: Callable[[str], str] = getpass.getpass) -> str:
    first = prompt("비밀번호: ")
    second = prompt("비밀번호 확인: ")
    if first != second:
        raise SystemExit("두 비밀번호가 다르다")
    if not MIN_PASSWORD_LENGTH <= len(first) <= MAX_PASSWORD_LENGTH:
        raise SystemExit(f"비밀번호는 {MIN_PASSWORD_LENGTH}~{MAX_PASSWORD_LENGTH}자")
    return first


async def insert_operator(conn, email: str, name: str, password_hash: str) -> int:
    # store-isolation-ok: 운영자는 매장에 속하지 않는 users 행이다
    row = await conn.fetchrow(
        "insert into users (name, email, password_hash, role) "
        "values ($1, $2, $3, 'OPERATOR') "
        "on conflict (email) do nothing returning user_id",
        name, email, password_hash)
    if row is None:
        raise SystemExit("같은 이메일이 이미 있다. 기존 계정은 운영자로 바꾸지 않는다")
    return int(row["user_id"])


async def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    email = normalize_email(args.email)
    name = args.name.strip()
    if not name or len(name) > MAX_NAME_LENGTH:
        raise SystemExit(f"이름은 1~{MAX_NAME_LENGTH}자")
    password = read_password()
    conn = await asyncpg.connect(get_settings().supabase_db_url)
    try:
        user_id = await insert_operator(conn, email, name, _hash_password(password))
    finally:
        await conn.close()
    print(f"운영자 생성: user_id={user_id} email={email}")


if __name__ == "__main__":
    asyncio.run(main())
