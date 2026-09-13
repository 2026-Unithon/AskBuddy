#!/usr/bin/env python3
"""매장 격리 정적 검사 — AST 로 실제 시그니처와 SQL 문자열을 본다.

RLS 를 쓰지 않으므로(D1) 격리는 전부 API 코드 책임이다. 이 스크립트는 두 가지를 찾는다.

  1. DB 커넥션을 받으면서 store_id 를 인자로 받지 않는 함수
  2. 매장 데이터 테이블을 읽으면서 store_id 조건이 없는 SQL 문자열

사용:
  python .claude/skills/store-isolation-check/check_store_id.py api/app
  python .claude/skills/store-isolation-check/check_store_id.py api/app/team

위반이 있으면 종료 코드 1.
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

# store_id 컬럼을 실제로 가진 테이블만 검사한다.
# chat_messages·message_citations·push_subscriptions 처럼 컬럼이 없는 테이블은
# 부모(session_id·message_id·user_id)를 통해 격리된다 — 여기에 넣으면 거짓 양성만 낸다.
#
# 목록 갱신 (테이블을 추가했을 때):
#   docker exec -i supabase_db_AskBuddy psql -U postgres -d postgres -t -A -c \
#     "select string_agg(quote_literal(table_name), ', ' order by table_name)
#      from information_schema.columns
#      where table_schema='public' and column_name='store_id';"
TENANT_TABLES = {
    "access_logs", "card_embeddings", "card_evidence", "card_review_events",
    "card_versions", "chat_sessions", "evaluation_cases", "evaluation_results",
    "evaluation_runs", "ingest_job_sources", "ingest_jobs", "invite_codes",
    "knowledge_cards", "knowledge_change_proposals", "notification_deliveries",
    "notification_events", "owner_ui_state", "pending_questions",
    "quality_evaluations", "reclassification_jobs", "reclassification_results",
    "roadmap_stages", "sources", "store_glossary", "store_members",
    "task_categories",
}
CONN_HINTS = ("asyncpg.Connection", "Connection", "Db")
# 라우트 핸들러는 store_id 를 인자가 아니라 JWT 에서 꺼내는 것이 정답이다 (불변식 4).
# 이 타입을 받으면 핸들러로 보고, 대신 본문이 실제로 store_id 로 좁히는지 확인한다
CLAIM_HINTS = ("Claims", "CurrentStoreId", "CurrentUserId")
_FROM = re.compile(r"\b(?:from|join|into|update)\s+([a-z_][a-z0-9_]*)", re.I)
# 검토를 마친 예외는 해당 줄이나 바로 윗줄에 이유와 함께 못 박는다.
#   # store-isolation-ok: 로그인 전이라 매장이 아직 없다
_SUPPRESS = re.compile(r"#\s*store-isolation-ok\b\s*:?\s*(.*)")


def _suppressed(lines: list[str], lineno: int) -> bool:
    """해당 줄이나 앞 3줄에 사유가 달린 면제 주석이 있는가."""
    for offset in range(0, 4):
        index = lineno - 1 - offset
        if index < 0:
            break
        match = _SUPPRESS.search(lines[index])
        if match:
            return bool(match.group(1).strip())  # 사유 없는 면제는 인정하지 않는다
    return False


def _annotations(node: ast.AsyncFunctionDef | ast.FunctionDef) -> list[str]:
    args = node.args.posonlyargs + node.args.args + node.args.kwonlyargs
    return [ast.unparse(a.annotation) if a.annotation else "" for a in args]


def _takes_connection(node: ast.AsyncFunctionDef | ast.FunctionDef) -> bool:
    return any(h in ann for ann in _annotations(node) for h in CONN_HINTS)


def _is_route_handler(node: ast.AsyncFunctionDef | ast.FunctionDef) -> bool:
    return any(h in ann for ann in _annotations(node) for h in CLAIM_HINTS)


def _body_scopes_by_store(node: ast.AsyncFunctionDef | ast.FunctionDef) -> bool:
    """핸들러 본문이 store_id 를 실제로 꺼내 쓰는가."""
    return any(
        isinstance(n, ast.Name) and n.id == "store_id"
        or isinstance(n, ast.Constant) and n.value == "store_id"
        or isinstance(n, ast.Attribute) and n.attr == "store_id"
        for n in ast.walk(node)
    )


def _param_names(node: ast.AsyncFunctionDef | ast.FunctionDef) -> set[str]:
    return {a.arg for a in node.args.args + node.args.kwonlyargs + node.args.posonlyargs}


def _has_default(node: ast.AsyncFunctionDef | ast.FunctionDef, name: str) -> bool:
    """store_id 에 기본값이 있으면 그 자체가 위반이다 (기본값·Optional 금지)."""
    args = node.args
    positional = args.posonlyargs + args.args
    for arg, default in zip(reversed(positional), reversed(args.defaults)):
        if arg.arg == name:
            return default is not None
    for arg, default in zip(args.kwonlyargs, args.kw_defaults):
        if arg.arg == name and default is not None:
            return True
    return False


def check_functions(tree: ast.AST, path: Path, lines: list[str]) -> list[str]:
    problems = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
            continue
        if not _takes_connection(node):
            continue
        params = _param_names(node)
        if _suppressed(lines, node.lineno):
            continue
        if _is_route_handler(node):
            # 핸들러는 JWT 에서 꺼낸다. 다만 꺼내 쓰지 않으면 격리가 없는 것이다
            if not _body_scopes_by_store(node):
                problems.append(
                    f"{path}:{node.lineno}: {node.name}() 가 인증 정보를 받는데 "
                    f"store_id 로 좁히는 코드가 없다"
                )
            continue
        if "store_id" not in params:
            problems.append(
                f"{path}:{node.lineno}: {node.name}() 가 DB 커넥션을 받는데 "
                f"store_id 인자가 없다"
            )
        elif _has_default(node, "store_id"):
            problems.append(
                f"{path}:{node.lineno}: {node.name}() 의 store_id 에 기본값이 있다 "
                f"(기본값·Optional 금지)"
            )
    return problems


def check_sql(tree: ast.AST, path: Path, lines: list[str]) -> list[str]:
    problems = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        sql = node.value
        lowered = sql.lower()
        if not any(k in lowered for k in ("select ", "update ", "delete ", "insert into")):
            continue
        tables = {t.lower() for t in _FROM.findall(sql)} & TENANT_TABLES
        if not tables:
            continue
        if "store_id" in lowered:
            continue
        if _suppressed(lines, node.lineno):
            continue
        problems.append(
            f"{path}:{node.lineno}: SQL 이 {sorted(tables)} 를 건드리는데 "
            f"store_id 가 없다"
        )
    return problems


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    roots = [Path(a) for a in argv[1:]]
    problems: list[str] = []
    checked = 0
    for root in roots:
        files = sorted(root.rglob("*.py")) if root.is_dir() else [root]
        for path in files:
            if "__pycache__" in path.parts:
                continue
            source = path.read_text(encoding="utf-8")
            try:
                tree = ast.parse(source)
            except SyntaxError as exc:
                problems.append(f"{path}: 파싱 실패 — {exc}")
                continue
            lines = source.splitlines()
            checked += 1
            problems += check_functions(tree, path, lines)
            problems += check_sql(tree, path, lines)

    print(f"검사한 파일 {checked}개")
    if not problems:
        print("매장 격리 위반 없음")
        return 0
    print(f"\n위반 {len(problems)}건:\n")
    for p in problems:
        print(f"  {p}")
    print(
        "\n검토를 마친 정당한 예외는 해당 줄 위에 사유와 함께 못 박는다:\n"
        "  # store-isolation-ok: <왜 store_id 가 필요 없는지>\n"
        "사유 없는 면제 주석은 무시된다."
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
