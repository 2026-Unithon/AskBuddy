"""골든셋 회귀 실행. 같은 명령을 반복해서 돌리고 이전 결과와 비교한다.

  # 골든셋 등록 (JSON 파일)
  python scripts/run_eval.py cases --file eval/golden_ko.json

  # 실행 + 리포트
  python scripts/run_eval.py run --label baseline
  python scripts/run_eval.py run --label anchor-soft --compare-to 3

  # 과거 실행 조회
  python scripts/run_eval.py list
  python scripts/run_eval.py show 3

결과는 DB(evaluation_runs·evaluation_results)가 정본이고, 리포트 파일은 사본이다.
이전 실행을 덮어쓰지 않는다 — 실행마다 새 run_id 가 생긴다.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import asyncpg  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.team import repository as repo  # noqa: E402
from app.team.metrics import aggregate  # noqa: E402
from app.team.runner import run_case  # noqa: E402
from app.team.snapshot import code_version, prompt_version, settings_snapshot  # noqa: E402

REPORT_DIR = Path(__file__).resolve().parents[1] / "eval" / "reports"


async def _connect() -> asyncpg.Connection:
    return await asyncpg.connect(get_settings().supabase_db_url)


async def _resolve_store(conn: asyncpg.Connection, slug: str) -> int:
    row = await conn.fetchrow("select store_id from stores where store_slug = $1", slug)
    if row is None:
        raise SystemExit(f"매장을 찾을 수 없다: {slug}")
    return int(row["store_id"])


# ── 골든셋 등록 ────────────────────────────────────────────────────────────

async def cmd_cases(args: argparse.Namespace) -> int:
    payload = json.loads(Path(args.file).read_text(encoding="utf-8"))
    cases = payload["cases"] if isinstance(payload, dict) else payload
    conn = await _connect()
    try:
        store_id = await _resolve_store(conn, args.slug)
        async with conn.transaction():
            for case in cases:
                await repo.upsert_case(conn, store_id, case)
        rows = await repo.list_cases(conn, store_id, active_only=False)
    finally:
        await conn.close()
    active = sum(1 for r in rows if r["is_active"])
    print(f"등록 {len(cases)}건 · 매장 전체 {len(rows)}건 (활성 {active}건)")
    return 0


# ── 실행 ──────────────────────────────────────────────────────────────────

async def cmd_run(args: argparse.Namespace) -> int:
    cost = None
    if args.cost_input or args.cost_output:
        cost = {"input": args.cost_input or 0.0, "output": args.cost_output or 0.0}

    conn = await _connect()
    try:
        store_id = await _resolve_store(conn, args.slug)
        cases = await repo.list_cases(conn, store_id, active_only=True)
        if not cases:
            raise SystemExit(
                "활성 골든셋 문항이 없다. 먼저 `run_eval.py cases --file ...` 을 실행하라"
            )

        snapshot = settings_snapshot()
        run = await repo.create_run(
            conn,
            store_id,
            {
                "label": args.label,
                "code_version": code_version(),
                "prompt_version": prompt_version(),
                "answer_model": snapshot["answer_model"],
                "embedding_model": snapshot["embedding_model"],
                "answer_mode": snapshot["answer_mode"],
                "retrieval_threshold": snapshot["retrieval_threshold"],
                "retrieval_strong_score": snapshot["retrieval_strong_score"],
                "settings": snapshot,
                "case_count": len(cases),
                "notes": args.notes,
            },
        )
        run_id = int(run["run_id"])
        print(
            f"run_id={run_id} label={args.label} cases={len(cases)} "
            f"code={run['code_version']} prompt={run['prompt_version']}"
        )

        rows: list[dict[str, Any]] = []
        for index, case in enumerate(cases, start=1):
            row = await run_case(
                conn, store_id, dict(case), top_k=args.top_k, cost_per_1k=cost
            )
            rows.append(row)
            mark = "PASS" if row["passed"] else f"FAIL({row['failure_kind']})"
            print(f"  [{index:>3}/{len(cases)}] {row['case_key']:<28} {mark}")

        metrics = aggregate(rows)
        status = "FAILED" if metrics.get("error_count", 0) == len(rows) else "SUCCEEDED"
        async with conn.transaction():
            await repo.insert_results(conn, run_id, store_id, rows)
            finished = await repo.finish_run(
                conn, run_id, store_id, status=status, metrics=metrics, case_count=len(rows)
            )

        previous = None
        if args.compare_to:
            previous = await repo.get_run(conn, store_id, args.compare_to)
            if previous is None:
                print(f"경고: 비교 대상 run_id={args.compare_to} 를 찾을 수 없다")
    finally:
        await conn.close()

    report = _write_reports(finished, rows, metrics, previous)
    print(f"\n{_summary_text(metrics)}")
    print(f"리포트: {report}")
    # 근거 없는 답변은 목표 0 이다 (MVP 정본 20-4). 있으면 실패 코드로 끝낸다
    return 1 if metrics.get("ungrounded_count", 0) > 0 or status == "FAILED" else 0


# ── 조회 ──────────────────────────────────────────────────────────────────

async def cmd_list(args: argparse.Namespace) -> int:
    conn = await _connect()
    try:
        store_id = await _resolve_store(conn, args.slug)
        runs = await repo.list_runs(conn, store_id, label=args.label, limit=args.limit, before_id=None)
    finally:
        await conn.close()
    if not runs:
        print("실행 이력이 없다")
        return 0
    print(f"{'run':>5}  {'label':<20} {'status':<10} {'pass':>6} {'ungrd':>6}  started")
    for r in runs:
        metrics = r["metrics"] if isinstance(r["metrics"], dict) else json.loads(r["metrics"])
        rate = metrics.get("pass_rate")
        print(
            f"{r['run_id']:>5}  {r['label'][:20]:<20} {r['status']:<10} "
            f"{(f'{rate:.0%}' if rate is not None else '-'):>6} "
            f"{metrics.get('ungrounded_count', '-'):>6}  {r['started_at']:%Y-%m-%d %H:%M}"
        )
    return 0


async def cmd_show(args: argparse.Namespace) -> int:
    conn = await _connect()
    try:
        store_id = await _resolve_store(conn, args.slug)
        run = await repo.get_run(conn, store_id, args.run_id)
        if run is None:
            raise SystemExit(f"run_id={args.run_id} 를 찾을 수 없다")
        results = await repo.list_results(conn, store_id, args.run_id, failed_only=args.failed_only)
    finally:
        await conn.close()
    metrics = run["metrics"] if isinstance(run["metrics"], dict) else json.loads(run["metrics"])
    print(f"run {run['run_id']} · {run['label']} · {run['status']}")
    print(f"code={run['code_version']} prompt={run['prompt_version']} model={run['answer_model']}")
    print(_summary_text(metrics))
    for r in results:
        mark = "PASS" if r["passed"] else f"FAIL({r['failure_kind']})"
        print(f"  {r['case_key']:<28} {r['expected_kind']:<10} → {r['actual_kind']:<6} {mark}")
    return 0


# ── 리포트 ────────────────────────────────────────────────────────────────

def _summary_text(metrics: dict[str, Any]) -> str:
    def pct(key: str) -> str:
        value = metrics.get(key)
        return f"{value:.1%}" if isinstance(value, (int, float)) else "-"

    return (
        f"통과 {metrics.get('passed_count', 0)}/{metrics.get('case_count', 0)} ({pct('pass_rate')}) · "
        f"판정정확도 {pct('kind_accuracy')} · 기대카드 {pct('expected_card_hit_rate')} · "
        f"MRR {metrics.get('mrr', '-')} · nDCG@10 {metrics.get('ndcg_at_10', '-')} · "
        f"근거없는답변 {metrics.get('ungrounded_count', 0)}건 · "
        f"p50 {metrics.get('latency_p50_ms', '-')}ms / p95 {metrics.get('latency_p95_ms', '-')}ms · "
        f"비용범위 {metrics.get('cost_scope', 'LEGACY_UNSPECIFIED')} · "
        f"관측 {metrics.get('cost_observation_status', 'UNKNOWN')} · "
        f"알려진 비용 {metrics.get('cost_usd_known_total', 'UNKNOWN')} USD · "
        f"비용 합 {metrics.get('cost_usd_total') if metrics.get('cost_usd_total') is not None else 'UNKNOWN'} USD · "
        f"누락 {metrics.get('cost_missing_count', 'UNKNOWN')}건"
    )


def _write_reports(run, rows: list[dict[str, Any]], metrics: dict[str, Any], previous) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base = REPORT_DIR / f"run{int(run['run_id']):05d}_{stamp}"

    raw = {
        "run": {
            "run_id": int(run["run_id"]),
            "label": run["label"],
            "status": run["status"],
            "started_at": run["started_at"].isoformat(),
            "code_version": run["code_version"],
            "prompt_version": run["prompt_version"],
            "answer_model": run["answer_model"],
            "embedding_model": run["embedding_model"],
            "answer_mode": run["answer_mode"],
            "retrieval_threshold": float(run["retrieval_threshold"]),
            "retrieval_strong_score": float(run["retrieval_strong_score"]),
        },
        "metrics": metrics,
        "results": rows,
    }
    base.with_suffix(".json").write_text(
        json.dumps(raw, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    base.with_suffix(".md").write_text(
        _markdown(run, rows, metrics, previous), encoding="utf-8"
    )
    return base.with_suffix(".md")


def _markdown(run, rows: list[dict[str, Any]], metrics: dict[str, Any], previous) -> str:
    lines = [
        f"# 평가 실행 {int(run['run_id'])} — {run['label']}",
        "",
        f"- 상태: `{run['status']}`",
        f"- 시각: {run['started_at']:%Y-%m-%d %H:%M:%S %Z}",
        f"- 코드: `{run['code_version']}`",
        f"- 프롬프트: `{run['prompt_version']}`",
        f"- 모델: `{run['answer_model']}` / 임베딩 `{run['embedding_model']}`",
        f"- 모드: `{run['answer_mode']}` · 임계값 {float(run['retrieval_threshold'])}"
        f" / strong {float(run['retrieval_strong_score'])}",
        "",
        "## 지표",
        "",
        "| 지표 | 값 |",
        "|---|---:|",
    ]
    labels = {
        "case_count": "문항 수",
        "passed_count": "통과",
        "pass_rate": "통과율",
        "kind_accuracy": "hit/miss 판정 정확도",
        "expected_card_hit_rate": "기대 카드 hit율",
        "expected_card_top1_rate": "기대 카드 1위율",
        "expected_card_mean_rank": "기대 카드 평균 순위",
        "mrr": "MRR (역순위 평균)",
        "ndcg_at_10": "nDCG@10",
        "ndcg_k": "nDCG 기준 k",
        "wrong_card_rate": "잘못된 카드 선택률",
        "ungrounded_count": "근거 없는 답변 (목표 0)",
        "should_not_answer_count": "답하면 안 되는데 답한 수",
        "citation_precision_mean": "citation 정확도",
        "fact_coverage_mean": "핵심 사실 포함률",
        "latency_p50_ms": "지연 p50 (ms)",
        "latency_p95_ms": "지연 p95 (ms)",
        "hit_latency_p95_ms": "hit 지연 p95 (ms)",
        "miss_latency_p95_ms": "miss 지연 p95 (ms)",
        "prompt_tokens_total": "prompt 토큰 합",
        "completion_tokens_total": "completion 토큰 합",
        "cost_usd_total": "비용 합 (USD)",
        "cost_usd_per_question": "질문당 비용 (USD)",
        "cost_scope": "비용 범위",
        "cost_basis": "비용 산정 방식",
        "cost_usd_known_total": "알려진 비용 부분합 (USD)",
        "cost_observation_status": "비용 관측 상태",
        "cost_observed_count": "비용 확인 문항 수",
        "cost_missing_count": "비용 누락 문항 수",
        "answer_not_called_count": "답변 모델 미호출 수",
        "question_total_cost_status": "임베딩·Storage 포함 전체 질문 원가",
        "error_count": "실행 오류",
    }
    for key, label in labels.items():
        if metrics.get(key) is not None:
            lines.append(f"| {label} | {metrics[key]} |")
        elif key in ("prompt_tokens_total", "completion_tokens_total", "cost_usd_total", "cost_usd_per_question"):
            lines.append(f"| {label} | UNKNOWN |")

    if metrics.get("cost_scope") == "ANSWER_MODEL_ONLY":
        lines += ["", "비용은 관측된 답변 모델의 ESTIMATED 비용입니다. "
                  "임베딩·Storage·미관측 재시도는 포함하지 않아 전체 질문 원가는 UNKNOWN입니다.",
                  "누락 금액은 사용량·단가 또는 호출 결과가 미확정인 경우이며 0으로 대체하지 않습니다."]

    if previous is not None:
        prev_metrics = (
            previous["metrics"]
            if isinstance(previous["metrics"], dict)
            else json.loads(previous["metrics"])
        )
        lines += [
            "",
            f"## 이전 실행 대비 (run {int(previous['run_id'])} — {previous['label']})",
            "",
            "| 지표 | 이전 | 이번 | 변화 |",
            "|---|---:|---:|---:|",
        ]
        for key in (
            "pass_rate", "kind_accuracy", "expected_card_hit_rate",
            "expected_card_top1_rate", "mrr", "ndcg_at_10", "wrong_card_rate",
            "ungrounded_count", "citation_precision_mean", "latency_p95_ms",
            "cost_usd_per_question",
        ):
            before, after = prev_metrics.get(key), metrics.get(key)
            if before is None and after is None:
                continue
            delta = (
                f"{after - before:+.4g}"
                if isinstance(before, (int, float)) and isinstance(after, (int, float))
                else "-"
            )
            lines.append(f"| {labels.get(key, key)} | {before} | {after} | {delta} |")

    if metrics.get("miss_reason_distribution"):
        lines += ["", "## miss_reason 분포", ""]
        for reason, count in sorted(metrics["miss_reason_distribution"].items()):
            lines.append(f"- `{reason}` — {count}건")

    failed = [r for r in rows if not r["passed"]]
    lines += ["", f"## 실패 {len(failed)}건", ""]
    if not failed:
        lines.append("없음")
    else:
        lines += ["| 문항 | 기대 | 실제 | 실패 사유 | 질문 |", "|---|---|---|---|---|"]
        for r in failed:
            lines.append(
                f"| `{r['case_key']}` | {r['expected_kind']} | {r['actual_kind']} "
                f"| {r['failure_kind']} | {r['question']} |"
            )

    lines += [
        "", "## 전체 문항", "",
        "| 문항 | 기대 | 실제 | 순위 | nDCG | 인용 | 지연(ms) | 결과 |",
        "|---|---|---|---:|---:|---:|---:|---|",
    ]
    for r in rows:
        gain = "-" if r["ndcg"] is None else format(r["ndcg"], ".3f")
        lines.append(
            f"| `{r['case_key']}` | {r['expected_kind']} | {r['actual_kind']} "
            f"| {r['expected_hit_rank'] or '-'} | {gain} | {r['citation_count']} "
            f"| {r['total_latency_ms'] or '-'} | {'PASS' if r['passed'] else 'FAIL'} |"
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description="AskBuddy 골든셋 회귀 실행")
    ap.add_argument("--slug", default="demo-cafe", help="평가 대상 매장 slug")
    sub = ap.add_subparsers(dest="command", required=True)

    p_cases = sub.add_parser("cases", help="골든셋 문항 등록·갱신")
    p_cases.add_argument("--file", required=True, help="문항 JSON 파일")
    p_cases.set_defaults(func=cmd_cases)

    p_run = sub.add_parser("run", help="골든셋 실행")
    p_run.add_argument("--label", required=True, help="실행 이름 (예: baseline)")
    p_run.add_argument("--top-k", type=int, default=5)
    p_run.add_argument("--compare-to", type=int, default=None, help="비교할 run_id")
    p_run.add_argument("--notes", default=None)
    p_run.add_argument("--cost-input", type=float, default=None, help="1k input 토큰 단가 USD")
    p_run.add_argument("--cost-output", type=float, default=None, help="1k output 토큰 단가 USD")
    p_run.set_defaults(func=cmd_run)

    p_list = sub.add_parser("list", help="실행 이력")
    p_list.add_argument("--label", default=None)
    p_list.add_argument("--limit", type=int, default=20)
    p_list.set_defaults(func=cmd_list)

    p_show = sub.add_parser("show", help="실행 상세")
    p_show.add_argument("run_id", type=int)
    p_show.add_argument("--failed-only", action="store_true")
    p_show.set_defaults(func=cmd_show)

    args = ap.parse_args()
    return asyncio.run(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
