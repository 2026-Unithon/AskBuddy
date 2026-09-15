"""읽기 원장의 관측 합계. 기존 답변 추정액과 더하지 않는다."""
from decimal import Decimal


def summarize_read_usage(rows):
    rows = list(rows)
    # 조회 receipt는 PK 기준 1회만 합산한다. 서로 다른 내용의 같은 PK는 오류다.
    unique = {}
    for row in rows:
        row = dict(row)
        key = row["usage_attempt_id"]
        if key in unique and unique[key] != row:
            raise ValueError("conflicting usage receipt")
        unique[key] = row
    rows = list(unique.values())
    complete = bool(rows) and all(r["status"] != "STARTED" and
        r["usage_status"] in ("COMPLETE", "NOT_BILLABLE") and r["cost_usd"] is not None for r in rows)
    known = sum((Decimal(str(r["known_cost_usd"])) for r in rows if r["known_cost_usd"] is not None), Decimal(0))
    return dict(schema_version="r_read_receipts/v1", scope="QUERY_AND_ANSWER_ONLY",
                attempt_count=len(rows), unknown_attempt_count=sum(
                    r["status"] == "STARTED" or r["usage_status"] == "UNKNOWN" for r in rows),
                known_cost_usd=str(known), total_cost_usd=str(sum(
                    (Decimal(str(r["cost_usd"])) for r in rows), Decimal(0))) if complete else None,
                observation_status="COMPLETE" if complete else "PARTIAL" if rows else "UNKNOWN",
                stage_counts={stage: sum(r["stage"] == stage for r in rows) for stage in ("QUERY", "ANSWER")})


async def read_run_usage(db, store_id: int, run_id: int):
    rows = await db.fetch("""
        select usage_attempt_id, stage, status, usage_status, known_cost_usd, cost_usd
        from ai_usage_attempts
        where store_id=$1 and evaluation_run_id=$2 and cost_purpose='EVALUATION'
          and cost_phase='OPERATING' and stage in ('QUERY','ANSWER')
        order by usage_attempt_id
    """, store_id, run_id)
    return summarize_read_usage(rows)
