"""평가 매장 초기화 STEPS 가 Phase B 표(입구 판정·답변 첨부)를 자료보다 먼저 지운다.

Phase B 표는 sources 를 FK 로 가리킨다. 빠지면 `delete from sources` 가 FK 오류로 멈춘다
(Task 17 실제 DB 검증 verify_w_entity_revision R9 에서 드러남).
"""
from __future__ import annotations

import importlib
import pathlib
import sys
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))


def _steps():
    # 모듈이 import 때 .env 를 덮어 읽는다 — 테스트 환경을 건드리지 않게 막는다
    with patch("dotenv.load_dotenv", lambda *a, **kw: None):
        return importlib.import_module("reset_eval_store").STEPS


def test_intake_tables_deleted_before_sources():
    names = [n for n, _ in _steps()]
    for table in ("intake_route_decisions", "owner_answer_attachments"):
        assert table in names
        assert names.index(table) < names.index("sources")


def test_intake_steps_are_store_scoped():
    sql = dict(_steps())
    for table in ("intake_route_decisions", "owner_answer_attachments"):
        assert sql[table] == f"delete from {table} where store_id=$1"
