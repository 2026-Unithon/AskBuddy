"""사장님 수정 지표 보고 (2026-11-07) — 자료별로 뽑은 사실·사장님이 고친 사실·카드에 더한 사실 수를 센다.

원본 내용·사실 값은 읽지 않고 수만 낸다. 매장 하나씩 본다(D1 — store_id 필수).

    cd api && python scripts/owner_correction_report.py --store 7
"""
import argparse
import asyncio

import asyncpg

from app.config import get_settings
from app.usage.owner_correction_report import render, summarize

ROWS_SQL = """
with occ as (
  select o.source_id, r.fact_id, o.card_id
  from fact_occurrences o
  join fact_revisions r on r.store_id = o.store_id and r.fact_revision_id = o.fact_revision_id
  join sources s on s.store_id = o.store_id and s.source_id = o.source_id
  where o.store_id = $1 and s.source_type <> 'OWNER_TEXT'
),
corrected as (
  select distinct fact_id from fact_revision_meta
  where store_id = $1 and change_kind = 'OWNER_CORRECTION'
),
added as (
  select distinct cv.card_id, m.fact_id
  from fact_revision_meta m
  join card_block_facts b on b.store_id = m.store_id and b.fact_revision_id = m.fact_revision_id
  join card_versions cv on cv.store_id = b.store_id and cv.version_id = b.card_version_id
  where m.store_id = $1 and m.change_kind = 'OWNER_ADD'
),
logic as (
  select distinct on (source_id) source_id, source_logic
  from intake_route_decisions where store_id = $1
  order by source_id, decision_id desc
)
select s.source_id, s.source_type,
       lower(regexp_replace(coalesce(s.file_url, ''), '^.*\\.', '')) as ext,
       l.source_logic as logic,
       (select count(distinct fact_id) from occ where occ.source_id = s.source_id) as extracted,
       (select count(distinct occ.fact_id) from occ join corrected c on c.fact_id = occ.fact_id
         where occ.source_id = s.source_id) as corrected,
       (select count(distinct a.fact_id) from added a
         where a.card_id in (select card_id from occ where occ.source_id = s.source_id
                             and occ.card_id is not null)) as added
from sources s
left join logic l on l.source_id = s.source_id
where s.store_id = $1 and s.source_type <> 'OWNER_TEXT'
  and exists (select 1 from occ where occ.source_id = s.source_id)
order by s.source_id
"""


async def fetch_rows(conn, store_id: int) -> list[dict]:
    return [dict(r) for r in await conn.fetch(ROWS_SQL, store_id)]


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", type=int, required=True)
    args = ap.parse_args()
    conn = await asyncpg.connect(get_settings().supabase_db_url)
    try:
        print(render(summarize(await fetch_rows(conn, args.store))))
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
