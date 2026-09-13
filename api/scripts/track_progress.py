"""평가 실행 이력을 시계열로 누적하고 진행 리포트를 만든다.

  python scripts/track_progress.py            # DB → metrics.jsonl 갱신 → PROGRESS.md 재생성
  python scripts/track_progress.py --slug eval-a
  python scripts/track_progress.py --report-only

왜 따로 두는가:
  `run_eval.py` 의 리포트는 실행 1회짜리다. "처음보다 얼마나 좋아졌는가" 를 보려면
  실행을 가로지르는 기록이 필요하다. 그게 `eval/progress/metrics.jsonl` 이다.

커밋 정책:
  progress/ 는 커밋한다. 집계 숫자만 담고 질문문·카드 본문·매장 자료는 담지 않는다.
  숫자 이력이 Git 에 남아야 "언제 무엇을 바꿔서 얼마나 올랐는지" 를 나중에 증명할 수 있다.
  실행별 원본 리포트(eval/reports/)는 계속 Git 제외다.
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

PROGRESS_DIR = Path(__file__).resolve().parents[1] / "eval" / "progress"
METRICS_FILE = PROGRESS_DIR / "metrics.jsonl"
REPORT_FILE = PROGRESS_DIR / "PROGRESS.md"

# 추적할 지표. (키, 라벨, 높을수록 좋은가, 포맷)
READ_METRICS = [
    ("pass_rate",               "통과율",            True,  "pct"),
    ("kind_accuracy",           "hit/miss 판정",      True,  "pct"),
    ("expected_card_hit_rate",  "기대카드 적중",       True,  "pct"),
    ("expected_card_top1_rate", "기대카드 1위",        True,  "pct"),
    ("mrr",                     "MRR",               True,  "num"),
    ("ndcg_at_10",              "nDCG@10",           True,  "num"),
    ("citation_precision_mean", "citation 정확도",    True,  "num"),
    ("wrong_card_rate",         "잘못된 카드 선택",     False, "pct"),
    ("ungrounded_count",        "근거없는 답변",        False, "int"),
    ("latency_p95_ms",          "지연 p95(ms)",       False, "int"),
    ("cost_usd_per_question",   "질문당 비용(USD)",    False, "cost"),
]


def _fmt(value: Any, kind: str) -> str:
    if value is None:
        return "-"
    if kind == "pct":
        return f"{value * 100:.1f}%"
    if kind == "int":
        return f"{value:,.0f}"
    if kind == "cost":
        return f"{value:.6f}"
    return f"{value:.4f}"


async def collect(slug: str | None) -> list[dict[str, Any]]:
    """종료된 실행만 가져온다. RUNNING 은 아직 수치가 확정되지 않았다."""
    conn = await asyncpg.connect(get_settings().supabase_db_url)
    try:
        rows = await conn.fetch(
            """
            select r.run_id, r.label, r.status, r.started_at, r.finished_at,
                   r.code_version, r.prompt_version, r.answer_model,
                   r.embedding_model, r.answer_mode, r.retrieval_threshold,
                   r.retrieval_strong_score, r.feature_flags, r.metrics,
                   r.case_count, s.store_slug
            from evaluation_runs r
            join stores s on s.store_id = r.store_id
            where r.status = 'SUCCEEDED'
              and ($1::text is null or s.store_slug = $1)
            order by r.run_id
            """,
            slug,
        )
    finally:
        await conn.close()

    out = []
    for r in rows:
        metrics = r["metrics"] if isinstance(r["metrics"], dict) else json.loads(r["metrics"])
        flags = r["feature_flags"] if isinstance(r["feature_flags"], dict) else json.loads(r["feature_flags"])
        out.append({
            "run_id": int(r["run_id"]),
            "path": "read",          # 추출 하네스가 붙으면 "write" 가 생긴다
            "store": r["store_slug"],
            "label": r["label"],
            "at": r["started_at"].astimezone(timezone.utc).isoformat(),
            "code_version": r["code_version"],
            "prompt_version": r["prompt_version"],
            "model": r["answer_model"],
            "embedding_model": r["embedding_model"],
            "answer_mode": r["answer_mode"],
            "retrieval_threshold": float(r["retrieval_threshold"]),
            "retrieval_strong_score": float(r["retrieval_strong_score"]),
            "feature_flags": flags,
            "case_count": int(r["case_count"]),
            "metrics": {k: metrics.get(k) for k, *_ in READ_METRICS},
        })
    return out


def merge(new_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """기존 기록을 덮어쓰지 않는다. run_id 로 중복만 거른다."""
    existing: dict[int, dict[str, Any]] = {}
    if METRICS_FILE.exists():
        for line in METRICS_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                row = json.loads(line)
                existing[row["run_id"]] = row
    added = 0
    for row in new_rows:
        if row["run_id"] not in existing:
            existing[row["run_id"]] = row
            added += 1
    merged = [existing[k] for k in sorted(existing)]
    PROGRESS_DIR.mkdir(parents=True, exist_ok=True)
    METRICS_FILE.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in merged) + "\n",
        encoding="utf-8",
    )
    return merged, added


def render(rows: list[dict[str, Any]]) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    read = [r for r in rows if r["path"] == "read"]
    write = [r for r in rows if r["path"] == "write"]

    lines = [
        "# AskBuddy 품질 추이",
        "",
        f"> 자동 생성 — `python scripts/track_progress.py` · 갱신 {now}",
        "> 원본은 DB(`evaluation_runs`)이고 이 파일은 사본이다. 직접 고치지 않는다.",
        "",
        "이 파일은 **처음보다 얼마나 좋아졌는가**를 보는 곳이다.",
        "실행 1회짜리 상세 리포트는 `eval/reports/`(Git 제외)에 있다.",
        "",
    ]

    if not rows:
        lines += ["아직 기록이 없다. `python scripts/run_eval.py run --label ...` 을 먼저 돌린다.", ""]
        return "\n".join(lines)

    # ── 처음 대비 현재 ──────────────────────────────────────────────
    if read:
        first, last = read[0], read[-1]
        lines += [
            "## 읽기 경로 — 처음 대비 현재",
            "",
            f"기준 `{first['label']}` (run {first['run_id']}, {first['at'][:10]}) → "
            f"현재 `{last['label']}` (run {last['run_id']}, {last['at'][:10]})",
            "",
            "| 지표 | 처음 | 현재 | 변화 |",
            "|---|---:|---:|---:|",
        ]
        for key, label, higher_better, kind in READ_METRICS:
            a, b = first["metrics"].get(key), last["metrics"].get(key)
            if a is None and b is None:
                continue
            if isinstance(a, (int, float)) and isinstance(b, (int, float)):
                delta = b - a
                if abs(delta) < 1e-9:
                    mark = "="
                else:
                    improved = (delta > 0) == higher_better
                    arrow = "▲" if delta > 0 else "▼"
                    mark = f"{arrow} {abs(delta):.4g} {'개선' if improved else '악화'}"
            else:
                mark = "-"
            lines.append(f"| {label} | {_fmt(a, kind)} | {_fmt(b, kind)} | {mark} |")
        lines.append("")

    # ── 전체 추이 ──────────────────────────────────────────────────
    if read:
        lines += [
            "## 읽기 경로 — 전체 추이",
            "",
            "| run | 날짜 | 매장 | 실험 | 문항 | 통과율 | 판정 | 적중 | MRR | nDCG | 근거없음 | p95 |",
            "|---:|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
        for r in read:
            m = r["metrics"]
            lines.append(
                f"| {r['run_id']} | {r['at'][:10]} | `{r['store']}` | {r['label']} "
                f"| {r['case_count']} | {_fmt(m.get('pass_rate'), 'pct')} "
                f"| {_fmt(m.get('kind_accuracy'), 'pct')} "
                f"| {_fmt(m.get('expected_card_hit_rate'), 'pct')} "
                f"| {_fmt(m.get('mrr'), 'num')} | {_fmt(m.get('ndcg_at_10'), 'num')} "
                f"| {_fmt(m.get('ungrounded_count'), 'int')} "
                f"| {_fmt(m.get('latency_p95_ms'), 'int')} |"
            )
        lines.append("")

    if write:
        lines += ["## 쓰기 경로 — 추출 품질", "", "(추출 하네스가 붙으면 여기에 쌓인다)", ""]
    else:
        lines += [
            "## 쓰기 경로 — 추출 품질",
            "",
            "아직 없다. 13.2 추출 평가 하네스가 붙으면 `E-O0` 추출 손실이 여기 쌓인다.",
            "",
        ]

    # ── 설정 이력 ──────────────────────────────────────────────────
    lines += [
        "## 설정 이력",
        "",
        "수치가 움직였을 때 무엇이 바뀌었는지 대조한다.",
        "",
        "| run | 코드 | 프롬프트 | 모델 | 모드 | 임계값 | 플래그 |",
        "|---:|---|---|---|---|---:|---|",
    ]
    for r in rows:
        flags = ", ".join(f"{k}={v}" for k, v in sorted(r["feature_flags"].items())) or "-"
        lines.append(
            f"| {r['run_id']} | `{r['code_version']}` | `{r['prompt_version']}` "
            f"| {r['model']} | {r['answer_mode']} | {r['retrieval_threshold']} | {flags} |"
        )
    lines += [
        "",
        "## 읽는 법",
        "",
        "- **통과율만 보지 않는다.** 근거 없는 답변은 목표 0이고, 하나라도 있으면 통과율이 높아도 실패다.",
        "- **MRR·nDCG 는 통과율이 못 잡는 저하를 잡는다.** 기대 카드가 1위에서 3위로 밀려도 통과는 통과다.",
        "- **문항 수가 다른 실행끼리 비교하지 않는다.** 같은 골든셋에서만 전후 비교가 성립한다.",
        "- **코드·프롬프트 버전이 같은데 수치가 움직였다면** 자료나 카드가 바뀐 것이다.",
        "",
    ]
    return "\n".join(lines)


async def main() -> int:
    ap = argparse.ArgumentParser(description="평가 실행 이력을 시계열로 누적한다")
    ap.add_argument("--slug", default=None, help="특정 매장만 (기본: 전체)")
    ap.add_argument("--report-only", action="store_true", help="DB 조회 없이 리포트만 재생성")
    args = ap.parse_args()

    if args.report_only:
        rows = []
        if METRICS_FILE.exists():
            rows = [json.loads(l) for l in METRICS_FILE.read_text(encoding="utf-8").splitlines() if l.strip()]
        added = 0
    else:
        rows, added = merge(await collect(args.slug))

    PROGRESS_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_FILE.write_text(render(rows), encoding="utf-8")
    print(f"기록 {len(rows)}건 (신규 {added}건) → {REPORT_FILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
