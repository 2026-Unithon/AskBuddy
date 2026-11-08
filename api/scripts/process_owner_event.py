"""지정한 매장·질문의 점주 답변 이벤트 하나만 실행한다. python -m scripts.process_owner_event --help"""
import argparse
import asyncio
import json

from app.cards.owner_answer_worker import process_next_owner_event
from app.deps import init_pool, get_pool, close_pool


async def run(store_id, question_id, event_id):
    await init_pool()
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            valid = await conn.fetchval("""
                select exists(select 1 from outbox_events e join r_owner_answer_revisions r
                    on r.store_id=e.store_id and r.owner_answer_id=e.owner_answer_id
                    where e.store_id=$1 and r.question_id=$2 and e.event_id=$3
                    and e.event_type='OWNER_ANSWER_SUBMITTED')
            """, store_id, question_id, event_id)
        if not valid:
            raise SystemExit("매장·질문·이벤트가 일치하지 않습니다.")
        status = await process_next_owner_event(pool,store_id=store_id,event_id=event_id)
        print(json.dumps(dict(store=store_id, question=question_id, event=event_id,
                              result=status or 'NOT_CLAIMABLE')),flush=True)
        return 0 if status in ('PUBLISHED','LINKED','REVIEW') else 1
    finally:
        await close_pool()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ('store-id','question-id','event-id'):
        parser.add_argument('--'+arg,type=int,required=True)
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run(args.store_id,args.question_id,args.event_id)))
