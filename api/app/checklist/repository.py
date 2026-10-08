"""체크리스트 SQL. 모든 함수는 store_id 를 필수로 받고 모든 쿼리를 store_id 로 좁힌다 (D1)."""
from __future__ import annotations

from datetime import date, time
from typing import Any

from app.checklist.calendar import split_lines
from app.checklist.scope import ChecklistCard, Shift

PRESET = (("오픈", time(7), time(11)), ("미들", time(14), time(18)), ("마감", time(18), time(23)))


def _shift(row) -> Shift:
    return Shift(int(row["shift_id"]), row["name"], int(row["sort_order"]), row["starts_at"], row["ends_at"])


async def get_member(db, store_id: int, user_id: int):
    return await db.fetchrow(
        """select m.member_id, m.member_role, m.personal_records_enabled,
                  s.timezone, s.business_day_starts_at, s.staff_records_visible
           from store_members m join stores s on s.store_id = m.store_id
           where m.store_id = $1 and m.user_id = $2 and m.removed_at is null""",
        store_id, user_id,
    )


async def list_shifts(db, store_id: int) -> list[Shift]:
    rows = await db.fetch(
        """select shift_id, name, sort_order, starts_at, ends_at from store_shifts
           where store_id = $1 and archived_at is null order by sort_order, shift_id""",
        store_id,
    )
    return [_shift(r) for r in rows]


async def shift_card_ids(db, store_id: int) -> dict[int, list[int]]:
    """근무조별 연결 카드 id (승인 여부와 무관, card_id 순). 활성 근무조만."""
    rows = await db.fetch(
        """select cs.shift_id, array_agg(cs.card_id order by cs.card_id) as card_ids
           from checklist_card_shifts cs
           join store_shifts s on s.store_id = cs.store_id and s.shift_id = cs.shift_id and s.archived_at is null
           where cs.store_id = $1 group by cs.shift_id""",
        store_id,
    )
    return {int(r["shift_id"]): [int(x) for x in r["card_ids"]] for r in rows}


async def shifts_exist(db, store_id: int, shift_ids: list[int]) -> bool:
    if not shift_ids:
        return True
    found = await db.fetchval(
        """select count(*) from store_shifts
           where store_id = $1 and shift_id = any($2::bigint[]) and archived_at is null""",
        store_id, list(set(shift_ids)),
    )
    return found == len(set(shift_ids))


async def card_exists(db, store_id: int, card_ids: list[int]) -> bool:
    if not card_ids:
        return True
    found = await db.fetchval(
        "select count(*) from knowledge_cards where store_id = $1 and card_id = any($2::bigint[])",
        store_id, list(set(card_ids)),
    )
    return found == len(set(card_ids))


async def create_shift(db, store_id: int, name: str, starts_at: time | None, ends_at: time | None) -> Shift:
    row = await db.fetchrow(
        """insert into store_shifts (store_id, name, starts_at, ends_at, sort_order)
           values ($1, $2, $3, $4,
             (select coalesce(max(sort_order), -1) + 1 from store_shifts where store_id = $1 and archived_at is null))
           returning shift_id, name, sort_order, starts_at, ends_at""",
        store_id, name, starts_at, ends_at,
    )
    return _shift(row)


async def update_shift(db, store_id: int, shift_id: int, name: str | None,
                       starts_at: time | None, ends_at: time | None, set_time: bool) -> Shift | None:
    row = await db.fetchrow(
        """update store_shifts set
             name = coalesce($3, name),
             starts_at = case when $6 then $4 else starts_at end,
             ends_at = case when $6 then $5 else ends_at end,
             updated_at = now()
           where store_id = $1 and shift_id = $2 and archived_at is null
           returning shift_id, name, sort_order, starts_at, ends_at""",
        store_id, shift_id, name, starts_at, ends_at, set_time,
    )
    return _shift(row) if row else None


async def archive_shift(db, store_id: int, shift_id: int) -> bool:
    """보관하면서 그 근무조의 카드 연결·직원 담당을 지운다. 연결이 안 남은 카드는 체크리스트에서 빠진다(공통으로 보이면 안 됨, C9)."""
    async with db.transaction():
        result = await db.execute(
            """update store_shifts set archived_at = now(), updated_at = now()
               where store_id = $1 and shift_id = $2 and archived_at is null""",
            store_id, shift_id,
        )
        if not result.endswith(" 1"):
            return False
        rows = await db.fetch(
            "delete from checklist_card_shifts where store_id = $1 and shift_id = $2 returning card_id",
            store_id, shift_id,
        )
        await db.execute("delete from member_shifts where store_id = $1 and shift_id = $2", store_id, shift_id)
        await _drop_orphans(db, store_id, [int(r["card_id"]) for r in rows])
    return True


async def reorder_shifts(db, store_id: int, shift_ids: list[int]) -> bool:
    async with db.transaction():
        active = [s.shift_id for s in await list_shifts(db, store_id)]
        if sorted(active) != sorted(shift_ids) or len(set(shift_ids)) != len(shift_ids):
            return False
        for order, shift_id in enumerate(shift_ids):
            await db.execute(
                "update store_shifts set sort_order = $3, updated_at = now() where store_id = $1 and shift_id = $2",
                store_id, shift_id, order,
            )
    return True


async def create_preset(db, store_id: int) -> list[Shift] | None:
    """활성 근무조가 0개일 때만 오픈·미들·마감을 만든다. 이름·시간은 점주가 바로 고친다."""
    async with db.transaction():
        await db.execute("select 1 from stores where store_id = $1 for update", store_id)
        if await db.fetchval(
            "select count(*) from store_shifts where store_id = $1 and archived_at is null", store_id
        ):
            return None
        return [await create_shift(db, store_id, name, start, end) for name, start, end in PRESET]


async def _drop_orphans(db, store_id: int, card_ids: list[int]) -> None:
    """근무조에서 빠져 연결이 하나도 안 남은 카드는 체크리스트에서 뺀다 — 공통으로 바뀌면 안 된다 (C9)."""
    if not card_ids:
        return
    await db.execute(
        """delete from checklist_cards c
           where c.store_id = $1 and c.card_id = any($2::bigint[])
             and not exists (select 1 from checklist_card_shifts s
                             where s.store_id = c.store_id and s.card_id = c.card_id)""",
        store_id, card_ids,
    )


async def set_shift_cards(db, store_id: int, shift_id: int, card_ids: list[int]) -> None:
    async with db.transaction():
        before = [r["card_id"] for r in await db.fetch(
            "select card_id from checklist_card_shifts where store_id = $1 and shift_id = $2", store_id, shift_id)]
        for card_id in card_ids:
            await db.execute(
                "insert into checklist_cards (store_id, card_id) values ($1, $2) on conflict do nothing",
                store_id, card_id,
            )
            await db.execute(
                """insert into checklist_card_shifts (store_id, card_id, shift_id) values ($1, $2, $3)
                   on conflict do nothing""",
                store_id, card_id, shift_id,
            )
        await db.execute(
            """delete from checklist_card_shifts
               where store_id = $1 and shift_id = $2 and not (card_id = any($3::bigint[]))""",
            store_id, shift_id, card_ids,
        )
        await _drop_orphans(db, store_id, [c for c in before if c not in card_ids])


async def get_card_links(db, store_id: int, card_id: int) -> dict[str, Any] | None:
    if not await card_exists(db, store_id, [card_id]):
        return None
    linked = await db.fetchval(
        "select exists(select 1 from checklist_cards where store_id = $1 and card_id = $2)", store_id, card_id)
    rows = await db.fetch(
        """select cs.shift_id from checklist_card_shifts cs
           join store_shifts s on s.store_id = cs.store_id and s.shift_id = cs.shift_id and s.archived_at is null
           where cs.store_id = $1 and cs.card_id = $2 order by s.sort_order, s.shift_id""",
        store_id, card_id,
    )
    return {"card_id": card_id, "checklist": bool(linked), "shift_ids": [int(r["shift_id"]) for r in rows]}


async def set_card_links(db, store_id: int, card_id: int, checklist: bool, shift_ids: list[int]) -> None:
    async with db.transaction():
        if not checklist:
            await db.execute("delete from checklist_cards where store_id = $1 and card_id = $2", store_id, card_id)
            return
        await db.execute(
            "insert into checklist_cards (store_id, card_id) values ($1, $2) on conflict do nothing", store_id, card_id)
        await db.execute(
            """delete from checklist_card_shifts
               where store_id = $1 and card_id = $2 and not (shift_id = any($3::bigint[]))""",
            store_id, card_id, shift_ids,
        )
        for shift_id in shift_ids:
            await db.execute(
                """insert into checklist_card_shifts (store_id, card_id, shift_id) values ($1, $2, $3)
                   on conflict do nothing""",
                store_id, card_id, shift_id,
            )


async def list_members(db, store_id: int) -> list[dict[str, Any]]:
    rows = await db.fetch(
        """select m.member_id, m.user_id, u.name, m.member_role,
                  coalesce(array_agg(ms.shift_id order by s.sort_order)
                           filter (where s.shift_id is not null), '{}') as shift_ids
           from store_members m
           join users u on u.user_id = m.user_id
           left join member_shifts ms on ms.store_id = m.store_id and ms.member_id = m.member_id
           left join store_shifts s on s.store_id = ms.store_id and s.shift_id = ms.shift_id and s.archived_at is null
           where m.store_id = $1 and m.removed_at is null
           group by m.member_id, m.user_id, u.name, m.member_role
           order by m.member_role desc, m.member_id""",
        store_id,
    )
    return [{"member_id": int(r["member_id"]), "user_id": int(r["user_id"]), "name": r["name"],
             "role": r["member_role"], "shift_ids": [int(x) for x in r["shift_ids"]]} for r in rows]


async def set_member_shifts(db, store_id: int, member_id: int, shift_ids: list[int]) -> bool:
    async with db.transaction():
        exists = await db.fetchval(
            "select exists(select 1 from store_members where store_id = $1 and member_id = $2 and removed_at is null)", store_id, member_id)
        if not exists:
            return False
        await db.execute("delete from member_shifts where store_id = $1 and member_id = $2", store_id, member_id)
        for shift_id in set(shift_ids):
            await db.execute(
                "insert into member_shifts (store_id, member_id, shift_id) values ($1, $2, $3)",
                store_id, member_id, shift_id,
            )
    return True


async def update_settings(db, store_id: int, business_day_starts_at: time | None,
                          staff_records_visible: bool | None) -> None:
    await db.execute(
        """update stores set
             business_day_starts_at = coalesce($2, business_day_starts_at),
             staff_records_visible = coalesce($3, staff_records_visible)
           where store_id = $1""",
        store_id, business_day_starts_at, staff_records_visible,
    )


async def set_personal_records(db, store_id: int, member_id: int, enabled: bool) -> None:
    await db.execute(
        "update store_members set personal_records_enabled = $3 where store_id = $1 and member_id = $2",
        store_id, member_id, enabled,
    )


async def load_cards(db, store_id: int) -> list[ChecklistCard]:
    """승인·공개 버전이 있는 체크리스트 카드. 보관 근무조 연결은 빼고, 연결 행이 아예 없으면 공통 (C9)."""
    rows = await db.fetch(
        """select c.card_id, k.published_version_id as card_version_id, v.title, v.content,
                  bool_and(cs.shift_id is null) as common,
                  coalesce(array_agg(s.shift_id) filter (where s.shift_id is not null), '{}') as shift_ids
           from checklist_cards c
           join knowledge_cards k on k.store_id = c.store_id and k.card_id = c.card_id
           join card_versions v on v.store_id = k.store_id and v.version_id = k.published_version_id
           left join checklist_card_shifts cs on cs.store_id = c.store_id and cs.card_id = c.card_id
           left join store_shifts s on s.store_id = cs.store_id and s.shift_id = cs.shift_id and s.archived_at is null
           where c.store_id = $1 and k.review_status = 'APPROVED' and k.published_version_id is not null
           group by c.card_id, k.published_version_id, v.title, v.content, c.created_at
           order by c.created_at, c.card_id""",
        store_id,
    )
    cards = []
    for r in rows:
        lines = tuple(split_lines(r["content"]))
        if lines:
            cards.append(ChecklistCard(int(r["card_id"]), int(r["card_version_id"]), r["title"], lines,
                                       bool(r["common"]), frozenset(int(x) for x in r["shift_ids"])))
    return cards


async def member_shift_ids(db, store_id: int, member_id: int) -> set[int]:
    rows = await db.fetch("select shift_id from member_shifts where store_id = $1 and member_id = $2",
                          store_id, member_id)
    return {int(r["shift_id"]) for r in rows}


async def checked_keys(db, store_id: int, business_date: date, version_ids: list[int]) -> set[tuple[int, int]]:
    if not version_ids:
        return set()
    rows = await db.fetch(
        """select card_version_id, line_no from checklist_checks
           where store_id = $1 and business_date = $2 and checked and card_version_id = any($3::bigint[])""",
        store_id, business_date, version_ids,
    )
    return {(int(r["card_version_id"]), int(r["line_no"])) for r in rows}


async def apply_checks(db, store_id: int, business_date: date, user_id: int,
                       items: list[tuple[int, int, bool]], *, late: bool, personal: bool) -> None:
    """매장 체크 상태를 바꾼다. 내 기록 남기기가 꺼져 있으면 사람 흔적(updated_by·이벤트)을 남기지 않는다 (C7-1).

    줄마다 문장 하나로 원자적으로 바꾸고, 실제로 바뀐 줄(returning 1)만 이벤트를 남긴다.
    같은 값 재전송·어제 창 전체 저장이 남의 체크를 내 기록으로 만들지 않는다. 행이 없는데 해제하는 요청은 아무것도 안 한다.
    """
    actor = user_id if personal else None
    for version_id, line_no, checked in items:
        if checked:
            changed = await db.fetchval(
                """insert into checklist_checks (store_id, business_date, card_version_id, line_no, checked, updated_by)
                   values ($1, $2, $3, $4, $5, $6)
                   on conflict (store_id, business_date, card_version_id, line_no)
                   do update set checked = excluded.checked, updated_by = excluded.updated_by, updated_at = now()
                   where checklist_checks.checked is distinct from excluded.checked
                   returning 1""",
                store_id, business_date, version_id, line_no, checked, actor,
            )
        else:
            # 행이 있고 체크된 줄만 해제한다 (없으면 새로 만들지 않음)
            changed = await db.fetchval(
                """update checklist_checks set checked = false, updated_by = $6, updated_at = now()
                   where store_id = $1 and business_date = $2 and card_version_id = $3 and line_no = $4
                     and checked is distinct from $5
                   returning 1""",
                store_id, business_date, version_id, line_no, checked, actor,
            )
        if changed and personal:
            await db.execute(
                """insert into checklist_check_events
                     (store_id, business_date, card_version_id, line_no, checked, user_id, late)
                   values ($1, $2, $3, $4, $5, $6, $7)""",
                store_id, business_date, version_id, line_no, checked, user_id, late,
            )


def _submission(row) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "user_id": int(row["user_id"]),
        "scope_shift_ids": None if row["scope_shift_ids"] is None else [int(x) for x in row["scope_shift_ids"]],
        "total_lines": int(row["total_lines"]), "done_lines": int(row["done_lines"]),
        "late": bool(row["late"]), "submitted_at": row["submitted_at"].isoformat(),
    }


async def get_submission(db, store_id: int, business_date: date, user_id: int) -> dict[str, Any] | None:
    return _submission(await db.fetchrow(
        """select user_id, scope_shift_ids, total_lines, done_lines, late, submitted_at from checklist_submissions
           where store_id = $1 and business_date = $2 and user_id = $3""",
        store_id, business_date, user_id,
    ))


async def insert_submission(db, store_id: int, business_date: date, user_id: int,
                            scope_shift_ids: list[int] | None, total: int, done: int,
                            *, late: bool, personal: bool) -> dict[str, Any]:
    """사람·영업일당 하나. 이미 있으면 그대로 돌려준다(멱등)."""
    await db.execute(
        """insert into checklist_submissions
             (store_id, business_date, user_id, scope_shift_ids, total_lines, done_lines, late, personal)
           values ($1, $2, $3, $4, $5, $6, $7, $8)
           on conflict (store_id, business_date, user_id) do nothing""",
        store_id, business_date, user_id, scope_shift_ids, total, done, late, personal,
    )
    return await get_submission(db, store_id, business_date, user_id)  # type: ignore[return-value]


async def submissions_on(db, store_id: int, business_date: date) -> list[dict[str, Any]]:
    rows = await db.fetch(
        """select user_id, scope_shift_ids, total_lines, done_lines, late, submitted_at from checklist_submissions
           where store_id = $1 and business_date = $2 order by submitted_at""",
        store_id, business_date,
    )
    return [_submission(r) for r in rows]  # type: ignore[misc]


async def member_by_user(db, store_id: int, user_id: int):
    return await db.fetchrow(
        """select m.member_id, m.member_role, m.personal_records_enabled, u.name from store_members m
           join users u on u.user_id = m.user_id where m.store_id = $1 and m.user_id = $2""",
        store_id, user_id,
    )


async def last_submission(db, store_id: int, dates: list[date]) -> dict[str, Any] | None:
    row = await db.fetchrow(
        """select business_date, user_id, scope_shift_ids, total_lines, done_lines, late, submitted_at
           from checklist_submissions where store_id = $1 and business_date = any($2::date[])
           order by submitted_at desc limit 1""",
        store_id, dates,
    )
    if row is None:
        return None
    out = _submission(row)
    out["business_date"] = row["business_date"].isoformat()  # type: ignore[index]
    return out


async def record_days(db, store_id: int, user_id: int, start: date, end: date) -> list[dict[str, Any]]:
    """출근한 날 = 내 체크 이벤트나 개인 제출이 있는 날. %는 제출 때 고정값, 제출이 없으면 체크한 줄 수만."""
    rows = await db.fetch(
        """with last as (
             select distinct on (business_date, card_version_id, line_no) business_date, checked
             from checklist_check_events
             where store_id = $1 and user_id = $2 and business_date between $3 and $4
             order by business_date, card_version_id, line_no, event_id desc
           ), checks as (
             select business_date, count(*) filter (where checked) as checked_lines from last group by business_date
           ), subs as (
             select business_date, total_lines, done_lines from checklist_submissions
             where store_id = $1 and user_id = $2 and personal and business_date between $3 and $4
           )
           select coalesce(c.business_date, s.business_date) as day,
                  coalesce(c.checked_lines, 0) as checked_lines, s.total_lines, s.done_lines
           from checks c full join subs s on s.business_date = c.business_date
           order by day""",
        store_id, user_id, start, end,
    )
    days = []
    for r in rows:
        total = r["total_lines"]
        days.append({
            "date": r["day"].isoformat(), "submitted": total is not None,
            "checked_lines": int(r["checked_lines"]),
            "percent": round(100 * r["done_lines"] / total) if total else None,
            "total": total, "done": r["done_lines"],
        })
    return days


async def record_day(db, store_id: int, user_id: int, day: date) -> dict[str, Any]:
    rows = await db.fetch(
        """with last as (
             select distinct on (card_version_id, line_no) card_version_id, line_no, checked, created_at
             from checklist_check_events
             where store_id = $1 and user_id = $2 and business_date = $3
             order by card_version_id, line_no, event_id desc
           )
           select l.card_version_id, l.line_no, l.created_at, v.title, v.content
           from last l join card_versions v on v.store_id = $1 and v.version_id = l.card_version_id
           where l.checked order by l.created_at""",
        store_id, user_id, day,
    )
    lines = []
    for r in rows:
        texts = split_lines(r["content"])
        if 1 <= r["line_no"] <= len(texts):
            lines.append({"title": r["title"], "text": texts[r["line_no"] - 1],
                          "checked_at": r["created_at"].isoformat()})
    sub = await db.fetchrow(
        """select user_id, scope_shift_ids, total_lines, done_lines, late, submitted_at from checklist_submissions
           where store_id = $1 and user_id = $2 and business_date = $3 and personal""",
        store_id, user_id, day,
    )
    return {"date": day.isoformat(), "lines": lines, "submission": _submission(sub)}
