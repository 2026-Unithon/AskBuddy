"""매장 리포트 집계 SQL. 모든 함수는 store_id 를 필수로 받고 모든 쿼리를 store_id 로 좁힌다 (D1).

질문 수는 알바생(STAFF) 대화만 센다. 사장의 미리보기 대화가 효과 수치를 부풀리지 않게 한다.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any


async def question_counts(db, store_id: int, start: datetime, end: datetime) -> dict[str, Any]:
    row = await db.fetchrow(
        """
        with staff_msgs as (
          select m.sender_type, m.answer_type, m.answer_source
          from chat_messages m
          join chat_sessions s on s.session_id = m.session_id
          join store_members sm on sm.store_id = s.store_id and sm.member_id = s.member_id
          where s.store_id = $1 and sm.member_role = 'STAFF'
            and m.created_at >= $2 and m.created_at < $3
        )
        select
          (select count(*) from staff_msgs where sender_type = 'USER') as questions,
          (select count(*) from staff_msgs where sender_type = 'BUDDY' and answer_type = 'ANSWERED'
             and coalesce(answer_source, '') <> 'OWNER_ANSWER') as ai_answered,
          (select count(*) from pending_question_occurrences o
             join pending_questions q on q.question_id = o.question_id
             where q.store_id = $1 and o.asked_at >= $2 and o.asked_at < $3) as escalated,
          (select count(*) from owner_answers a
             join pending_questions q on q.question_id = a.question_id
             where q.store_id = $1 and a.answered_at >= $2 and a.answered_at < $3) as owner_answered,
          (select percentile_cont(0.5) within group (
                    order by extract(epoch from (a.answered_at - q.created_at)) / 60.0)
             from owner_answers a
             join pending_questions q on q.question_id = a.question_id
             where q.store_id = $1 and a.answered_at >= $2 and a.answered_at < $3) as answer_minutes_median,
          (select count(*) from pending_questions q
             where q.store_id = $1 and q.status = 'WAITING') as waiting_now
        """,
        store_id, start, end,
    )
    median = row["answer_minutes_median"]
    return {
        "questions": int(row["questions"]),
        "ai_answered": int(row["ai_answered"]),
        "escalated": int(row["escalated"]),
        "owner_answered": int(row["owner_answered"]),
        "answer_minutes_median": None if median is None else round(float(median)),
        "waiting_now": int(row["waiting_now"]),
    }


async def top_escalations(db, store_id: int, start: datetime, end: datetime, limit: int = 5) -> list[dict[str, Any]]:
    """같은 질문이 몇 번 넘어왔는지. 매뉴얼에 먼저 넣을 것을 고르는 근거다."""
    rows = await db.fetch(
        """select q.question_id, q.question_text, q.status, count(*) as asked
           from pending_question_occurrences o
           join pending_questions q on q.question_id = o.question_id
           where q.store_id = $1 and o.asked_at >= $2 and o.asked_at < $3
           group by q.question_id, q.question_text, q.status
           order by count(*) desc, max(o.asked_at) desc
           limit $4""",
        store_id, start, end, limit,
    )
    return [{"question_id": int(r["question_id"]), "question_text": r["question_text"],
             "status": r["status"], "asked": int(r["asked"])} for r in rows]


async def per_staff(db, store_id: int, start: datetime, end: datetime) -> list[dict[str, Any]]:
    rows = await db.fetch(
        """select sm.member_id, u.name,
                  (select count(*) from chat_messages m
                     join chat_sessions s on s.session_id = m.session_id
                     where s.store_id = sm.store_id and s.member_id = sm.member_id
                       and m.sender_type = 'USER' and m.created_at >= $2 and m.created_at < $3) as questions,
                  (select count(*) from pending_question_occurrences o
                     join pending_questions q on q.question_id = o.question_id
                     where q.store_id = sm.store_id and o.member_id = sm.member_id
                       and o.asked_at >= $2 and o.asked_at < $3) as escalated
           from store_members sm
           join users u on u.user_id = sm.user_id
           where sm.store_id = $1 and sm.member_role = 'STAFF' and sm.removed_at is null
           order by sm.member_id""",
        store_id, start, end,
    )
    return [{"member_id": int(r["member_id"]), "name": r["name"],
             "questions": int(r["questions"]), "escalated": int(r["escalated"])} for r in rows]


async def checklist_counts(db, store_id: int, first: date, last: date) -> dict[str, int]:
    row = await db.fetchrow(
        """select count(*) as submissions,
                  count(*) filter (where done_lines = total_lines) as complete
           from checklist_submissions
           where store_id = $1 and business_date between $2 and $3""",
        store_id, first, last,
    )
    return {"submissions": int(row["submissions"]), "complete": int(row["complete"])}


async def today_task_counts(db, store_id: int, first: date, last: date) -> dict[str, int]:
    row = await db.fetchrow(
        """select count(distinct t.task_id) as tasks,
                  count(tt.member_id) as assigned,
                  count(tt.done_at) as done
           from today_tasks t
           join today_task_targets tt on tt.store_id = t.store_id and tt.task_id = t.task_id
           where t.store_id = $1 and t.canceled_at is null and t.business_date between $2 and $3""",
        store_id, first, last,
    )
    return {"tasks": int(row["tasks"]), "assigned": int(row["assigned"]), "done": int(row["done"])}
