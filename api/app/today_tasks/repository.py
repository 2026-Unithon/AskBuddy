"""오늘만 할 일 SQL. 모든 함수는 store_id 를 필수로 받고 모든 쿼리를 store_id 로 좁힌다 (D1)."""
from __future__ import annotations

from datetime import date
from typing import Any


async def active_staff(db, store_id: int, member_ids: list[int]) -> dict[int, int]:
    """대상이 될 수 있는 사람(이 매장의 현재 알바생)만 member_id → user_id 로 돌려준다."""
    rows = await db.fetch(
        """select member_id, user_id from store_members
           where store_id = $1 and member_id = any($2::bigint[])
             and removed_at is null and member_role = 'STAFF'""",
        store_id, member_ids,
    )
    return {int(r["member_id"]): int(r["user_id"]) for r in rows}


async def create_task(db, store_id: int, business_date: date, body: str, original_text: str,
                      created_by: int, member_ids: list[int]) -> int:
    task_id = await db.fetchval(
        """insert into today_tasks (store_id, business_date, body, original_text, created_by)
           values ($1, $2, $3, $4, $5) returning task_id""",
        store_id, business_date, body, original_text, created_by,
    )
    await db.executemany(
        "insert into today_task_targets (store_id, task_id, member_id) values ($1, $2, $3)",
        [(store_id, task_id, m) for m in member_ids],
    )
    return int(task_id)


def _iso(value) -> str | None:
    return value.isoformat() if value is not None else None


async def list_for_owner(db, store_id: int, business_date: date) -> list[dict[str, Any]]:
    """그 영업일의 취소 안 된 지시. 대상별 확인·완료를 함께 준다(사장이 직접 고른 사람이라 이름을 보인다)."""
    rows = await db.fetch(
        """select t.task_id, t.body, t.original_text, t.created_at,
                  tt.member_id, u.name, tt.seen_at, tt.done_at
           from today_tasks t
           join today_task_targets tt on tt.store_id = t.store_id and tt.task_id = t.task_id
           join store_members m on m.store_id = tt.store_id and m.member_id = tt.member_id
           join users u on u.user_id = m.user_id
           where t.store_id = $1 and t.business_date = $2 and t.canceled_at is null
           order by t.created_at desc, t.task_id desc, tt.member_id""",
        store_id, business_date,
    )
    tasks: dict[int, dict[str, Any]] = {}
    for r in rows:
        task = tasks.setdefault(int(r["task_id"]), {
            "task_id": int(r["task_id"]), "body": r["body"], "original_text": r["original_text"],
            "created_at": _iso(r["created_at"]), "targets": [],
        })
        task["targets"].append({"member_id": int(r["member_id"]), "name": r["name"],
                                "seen_at": _iso(r["seen_at"]), "done_at": _iso(r["done_at"])})
    return list(tasks.values())


async def list_for_member(db, store_id: int, business_date: date, member_id: int) -> list[dict[str, Any]]:
    rows = await db.fetch(
        """select t.task_id, t.body, t.created_at, tt.seen_at, tt.done_at
           from today_tasks t
           join today_task_targets tt on tt.store_id = t.store_id and tt.task_id = t.task_id
           where t.store_id = $1 and t.business_date = $2 and t.canceled_at is null and tt.member_id = $3
           order by t.created_at, t.task_id""",
        store_id, business_date, member_id,
    )
    return [{"task_id": int(r["task_id"]), "body": r["body"], "created_at": _iso(r["created_at"]),
             "seen": r["seen_at"] is not None, "done": r["done_at"] is not None} for r in rows]


async def cancel_task(db, store_id: int, task_id: int, business_date: date) -> bool:
    """오늘 지시만 거둘 수 있다. 지난 지시는 기록으로 남는다."""
    status = await db.execute(
        """update today_tasks set canceled_at = now()
           where store_id = $1 and task_id = $2 and business_date = $3 and canceled_at is null""",
        store_id, task_id, business_date,
    )
    return status.endswith(" 1")


async def set_done(db, store_id: int, task_id: int, member_id: int, business_date: date, done: bool) -> bool:
    """내가 대상인 오늘 지시만 바꾼다. 완료로 표시하면 확인도 한 것으로 본다."""
    status = await db.execute(
        """update today_task_targets tt
           set done_at = case when $5 then coalesce(tt.done_at, now()) else null end,
               seen_at = coalesce(tt.seen_at, now())
           from today_tasks t
           where tt.store_id = $1 and tt.task_id = $2 and tt.member_id = $3
             and t.store_id = tt.store_id and t.task_id = tt.task_id
             and t.business_date = $4 and t.canceled_at is null""",
        store_id, task_id, member_id, business_date, done,
    )
    return status.endswith(" 1")


async def mark_seen(db, store_id: int, member_id: int, task_ids: list[int], business_date: date) -> int:
    status = await db.execute(
        """update today_task_targets tt set seen_at = now()
           from today_tasks t
           where tt.store_id = $1 and tt.member_id = $2 and tt.task_id = any($3::bigint[])
             and tt.seen_at is null
             and t.store_id = tt.store_id and t.task_id = tt.task_id
             and t.business_date = $4 and t.canceled_at is null""",
        store_id, member_id, task_ids, business_date,
    )
    return int(status.rsplit(" ", 1)[-1])
