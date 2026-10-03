"""운영자 계정 생성 스크립트 (이슈 #33)."""
import asyncio
import importlib.util
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parents[1] / "scripts/create_operator.py"
_spec = importlib.util.spec_from_file_location("create_operator", _PATH)
create_operator = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(create_operator)


def prompts(*answers):
    it = iter(answers)
    return lambda _label: next(it)


def test_password_must_match_twice():
    with pytest.raises(SystemExit):
        create_operator.read_password(prompts("long-enough-pass", "different-pass!"))


def test_password_min_length():
    with pytest.raises(SystemExit):
        create_operator.read_password(prompts("short", "short"))


def test_password_accepted():
    assert create_operator.read_password(prompts("long-enough-pass", "long-enough-pass")) == "long-enough-pass"


def test_password_is_not_an_argument():
    with pytest.raises(SystemExit):
        create_operator.parse_args(["--email", "ops@example.com", "--name", "운영자",
                                    "--password", "long-enough-pass"])


class Conn:
    def __init__(self, row):
        self.row = row
        self.sql = None
        self.args = None

    async def fetchrow(self, sql, *args):
        self.sql, self.args = sql, args
        return self.row


def test_insert_operator_role_without_overwriting():
    conn = Conn({"user_id": 9})
    user_id = asyncio.run(create_operator.insert_operator(conn, "ops@example.com", "운영자", "hash"))
    assert user_id == 9
    assert "'OPERATOR'" in conn.sql
    assert "on conflict (email) do nothing" in conn.sql
    assert "update" not in conn.sql.lower()
    assert conn.args == ("운영자", "ops@example.com", "hash")


def test_existing_email_fails_without_promotion():
    with pytest.raises(SystemExit):
        asyncio.run(create_operator.insert_operator(Conn(None), "owner@example.com", "점주", "hash"))


def test_normalize_email_rejects_non_email():
    with pytest.raises(SystemExit):
        create_operator.normalize_email("ops@localhost")


def test_normalize_email_lowercases_and_strips():
    assert create_operator.normalize_email("  Ops@Example.com ") == "ops@example.com"
