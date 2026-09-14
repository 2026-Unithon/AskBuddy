"""원가 리포트 (CP-00C) — 관측된 단가로 시나리오를 계산하고 D21 을 판정한다.

  python scripts/cost_report.py --store store-a
  python scripts/cost_report.py --store store-a --usd-krw 1380

관측이 불완전하면 **UNDETERMINED** 다. 통과가 아니다.
못 잰 호출을 0 으로 합산하면 총액이 사실보다 싸 보이고 그 수치로 통과를 적게 된다.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import asyncpg  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=True)

from app.config import get_settings  # noqa: E402
from app.usage import report  # noqa: E402
from app.usage.rates import load_rate_card  # noqa: E402


async def fetch_attempts(conn, store_id: int, purpose: str | None) -> list[dict]:
    rows = await conn.fetch(
        """
        select stage, cost_phase, cost_purpose, usage_status, status,
               prompt_tokens, completion_tokens, thought_tokens,
               media_duration_sec, input_bytes, known_cost_usd, cost_usd
        from ai_usage_attempts
        where store_id = $1 and ($2::text is null or cost_purpose = $2)
        """,
        store_id, purpose,
    )
    return [dict(r) for r in rows]


def _fmt(value, suffix="") -> str:
    return "—" if value is None else f"{value}{suffix}"


async def main() -> int:
    ap = argparse.ArgumentParser(description="원가 리포트 (CP-00C)")
    ap.add_argument("--store", required=True, help="store-a 또는 eval-a")
    ap.add_argument("--purpose", default=None,
                    help="PRODUCT / EVALUATION / DEVELOPMENT. 기본은 전부")
    ap.add_argument("--usd-krw", type=str, default=None, help="환율. 없으면 원화 미산출")
    args = ap.parse_args()

    slug = args.store.replace("store-", "eval-")
    usd_krw = Decimal(args.usd_krw) if args.usd_krw else None
    card = load_rate_card()

    conn = await asyncpg.connect(get_settings().supabase_db_url)
    try:
        store_id = await conn.fetchval(
            "select store_id from stores where store_slug=$1", slug)
        if store_id is None:
            print(f"매장이 없다: {slug}", file=sys.stderr)
            return 1
        attempts = await fetch_attempts(conn, store_id, args.purpose)
    finally:
        await conn.close()

    print(f"{slug} · 호출 {len(attempts)}건 · 요율표 {card.version}")
    if card.version.startswith(("unset", "missing")):
        print("  요율표가 비어 있다. 토큰은 쌓이고 비용은 계산되지 않는다.\n"
              "  config/rate_card.json 을 채우면 같은 원장으로 다시 계산한다.")
    print()

    if not attempts:
        print("관측된 호출이 없다. 먼저 자료를 처리한다.")
        return 0

    # ── 단계별 단가 ──────────────────────────────────────────────
    units = report.unit_costs(attempts)
    print(f"{'단계':<10}{'호출':>6}{'관측률':>8}{'prompt/회':>11}{'completion/회':>14}{'원가/회':>12}")
    print("-" * 62)
    for stage, u in sorted(units.items()):
        rate = u["observation_rate"]
        print(f"{stage:<10}{u['attempts']:>6}"
              f"{(f'{rate:.0%}' if rate is not None else '—'):>8}"
              f"{_fmt(u['prompt_tokens_per_call']):>11}"
              f"{_fmt(u['completion_tokens_per_call']):>14}"
              f"{_fmt(u['cost_per_call_usd']):>12}")

    # ── 등록 / 운영 ──────────────────────────────────────────────
    reg = [a for a in attempts if a["cost_phase"] == "REGISTRATION"]
    ops = [a for a in attempts if a["cost_phase"] == "OPERATING"]
    reg_known = sum(Decimal(str(a["known_cost_usd"])) for a in reg
                    if a["known_cost_usd"] is not None)
    reg_complete = all(a["usage_status"] in ("COMPLETE", "NOT_BILLABLE") for a in reg)

    print()
    print(f"등록(1회성)  호출 {len(reg)}건 · "
          f"{'전부 관측' if reg_complete and reg else '관측 불완전'} · "
          f"known ${reg_known}")
    print(f"운영(월)     호출 {len(ops)}건")

    # ── 시나리오 판정 ────────────────────────────────────────────
    answer = units.get("ANSWER")
    per_question = answer["cost_per_call_usd"] if answer else None
    print()
    print(f"{'시나리오':<10}{'월':>4}{'질문':>7}{'합계(USD)':>12}{'합계(원)':>11}{'D21':>14}")
    print("-" * 60)
    for scenario in report.load_scenarios()["scenarios"]:
        for month in (1, 2):
            p = report.project_operating(scenario, per_question, None, month=month,
                                         usd_krw=usd_krw)
            verdict = report.judge_d21(p["total_krw"])
            print(f"{p['scenario']:<10}{month:>4}{p['questions']:>7}"
                  f"{_fmt(p['total_usd']):>12}{_fmt(p['total_krw']):>11}{verdict:>14}")

    print()
    print("UNDETERMINED 는 통과가 아니다. 답변 단가·저장비·환율이 모두 관측돼야 판정한다.")
    print("현재 막는 것:", ", ".join(filter(None, [
        "답변(ANSWER) 호출 미관측" if per_question is None else None,
        "저장비 미측정",
        "요율표 미설정" if card.version.startswith(("unset", "missing")) else None,
        "환율 미입력" if usd_krw is None else None,
    ])))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
