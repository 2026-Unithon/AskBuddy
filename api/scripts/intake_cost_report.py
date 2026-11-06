"""입구 호출 보고 (Phase B 추가 S5) — 단계별 호출·비용과 작은 자료·묶음·한 호출 수.

  python scripts/intake_cost_report.py --store 12
  python scripts/intake_cost_report.py --store 12 --since 2026-10-14 --out /tmp/intake.md

두 조회 모두 `store_id` 로 좁힌다. 묶음 분류 영수증은 묶음의 첫 자료·별도 run_tag 로 붙으므로
run_tag 가 아니라 매장·기간으로 모은다. 집계·서식은 `app.usage.intake_report` 가 한다.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import asyncpg  # noqa: E402

from app.usage import intake_report  # noqa: E402

# 기간을 주지 않으면 전체 기록
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


async def fetch_stage_rows(conn, store_id: int, since: datetime) -> list[dict]:
    """단계별(운영 제품 호출만). 재시도는 logical_call_id 로 한 호출로 센다.

    cost_usd 가 null 인 시도(미관측·요율 없음)는 unknown_cost_calls 로 따로 센다.
    """
    rows = await conn.fetch(
        """
        select stage, count(distinct logical_call_id) as calls,
               coalesce(sum(cost_usd), 0) as cost_usd,
               coalesce(sum(known_cost_usd), 0) as known_cost_usd,
               coalesce(sum(prompt_tokens), 0) as prompt_tokens,
               coalesce(sum(completion_tokens), 0) as completion_tokens,
               -- 비용 미관측(null)은 0 이 아니다(원장 규칙 1·D21). 따로 세어 합계를 '부분' 으로 적는다
               count(*) filter (where cost_usd is null) as unknown_cost_calls
        from ai_usage_attempts
        where store_id = $1 and cost_purpose = 'PRODUCT' and started_at >= $2
        group by stage order by stage
        """,
        store_id, since,
    )
    return [dict(r) for r in rows]


async def fetch_source_rows(conn, store_id: int, since: datetime) -> list[dict]:
    """자료별 최신 판정. 한 호출은 model_sections.single_call, 묶음은 logical_call_id 의 :bundle."""
    rows = await conn.fetch(
        """
        select distinct on (d.source_id) d.source_id, d.normalizer,
               coalesce((d.sample_summary->>'chars')::int, 0) as chars,
               coalesce((d.sample_summary->>'images')::int, 0) as images,
               coalesce((d.sample_summary->>'complete')::boolean, false) as complete,
               coalesce((d.model_sections->>'single_call')::boolean, false) as single_call,
               coalesce(d.logical_call_id like '%:bundle%', false) as bundled
        from intake_route_decisions d
        where d.store_id = $1 and d.created_at >= $2
        order by d.source_id, d.decision_id desc
        """,
        store_id, since,
    )
    return [dict(r) for r in rows]


async def summarize_store(conn, store_id: int, since: datetime = EPOCH) -> dict:
    return intake_report.summarize(await fetch_stage_rows(conn, store_id, since),
                                   await fetch_source_rows(conn, store_id, since))


def _since(value: str | None) -> datetime:
    if not value:
        return EPOCH
    d = date.fromisoformat(value)
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


async def main() -> int:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=True)
    from app.config import get_settings

    ap = argparse.ArgumentParser(description="입구 호출 보고 (작은 자료 호출 줄이기)")
    ap.add_argument("--store", required=True, type=int, help="store_id")
    ap.add_argument("--since", default=None, help="YYYY-MM-DD (UTC 0시부터). 없으면 전체")
    ap.add_argument("--out", default=None, help="마크다운을 쓸 경로. 없으면 표준 출력")
    args = ap.parse_args()

    conn = await asyncpg.connect(get_settings().supabase_db_url)
    try:
        summary = await summarize_store(conn, args.store, _since(args.since))
    finally:
        await conn.close()

    text = intake_report.render(summary)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"보고를 썼다: {args.out}")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
