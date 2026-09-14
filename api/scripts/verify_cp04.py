"""M0·M1 migration 과 트랜잭션 서비스를 실제 DB 에서 검증한다 (CP-04).

  python scripts/verify_cp04.py

임시 매장을 만들어 돌리고 끝나면 지운다. 기존 매장 자료를 건드리지 않는다.

여기서 보는 것은 스키마가 '있다' 가 아니라 **틀린 것을 막느냐** 다:
  1. 자료를 지워도 사실·근거가 남는가 (D20 / RV-11)
  2. 같은 멱등 키 재시도가 판 번호를 올리지 않는가 (§4.3)
  3. 동시에 두 발행이 들어오면 하나만 이기는가 (§4.2)
  4. 다른 매장의 사실을 블록에 담을 수 없는가 (D1 / composite FK)
  5. 승인된 판을 나중에 고칠 수 없는가 (§3.4)
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import asyncpg  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=True)

from app.config import get_settings  # noqa: E402
from app.publish import service  # noqa: E402

HASH = "sha256:" + "c" * 64
RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, ok, detail))
    print(f"  {'OK  ' if ok else 'FAIL'} {name}{'  — ' + detail if detail else ''}")


async def seed(conn) -> dict:
    """앞선 실행이 남긴 것을 먼저 치운다. 검증이 잔여물 때문에 실패하면 안 된다."""
    stale = [r["store_id"] for r in await conn.fetch(
        "select store_id from stores where store_slug like 'cp04-%'")]
    if stale:
        await cleanup(conn, {"cp04-a": stale[0],
                             "cp04-b": stale[-1] if len(stale) > 1 else stale[0]})
    owner = await conn.fetchval("select user_id from users limit 1")
    ids = {}
    for slug in ("cp04-a", "cp04-b"):
        ids[slug] = await conn.fetchval(
            """
            insert into stores (owner_id, store_slug, store_name, business_type)
            values ($1, $2, 'CP-04 검증용', 'CAFE') returning store_id
            """, owner, slug)
    ids["source"] = await conn.fetchval(
        """
        insert into sources (store_id, uploaded_by, source_type, title)
        values ($1, $2, 'SCAN', '검증용 합성 자료') returning source_id
        """, ids["cp04-a"], owner)
    ids["card"] = await conn.fetchval(
        """
        insert into knowledge_cards (store_id, title, content)
        values ($1, '검증용 카드', '내용') returning card_id
        """, ids["cp04-a"])
    ids["owner"] = owner
    return ids


async def cleanup(conn, ids: dict) -> None:
    # 불변 트리거가 막는 표는 먼저 비활성화하고 지운다. 검증용 데이터만 지운다
    for store_id in (ids["cp04-a"], ids["cp04-b"]):
        await conn.execute(
            "alter table fact_revisions disable trigger trg_fact_revision_immutable")
        await conn.execute(
            "alter table knowledge_snapshots disable trigger trg_snapshot_immutable")
        await conn.execute("delete from card_block_facts where store_id = $1", store_id)
        await conn.execute("delete from card_version_blocks where store_id = $1", store_id)
        await conn.execute("delete from fact_occurrences where store_id = $1", store_id)
        await conn.execute("delete from fact_revision_requires where store_id = $1", store_id)
        await conn.execute("delete from source_facts where store_id = $1", store_id)
        await conn.execute("update knowledge_publications set current_snapshot_id = null where store_id = $1", store_id)
        await conn.execute("delete from knowledge_snapshots where store_id = $1", store_id)
        await conn.execute("delete from raw_spans where store_id = $1", store_id)
        await conn.execute(
            "delete from ingest_job_sources where store_id = $1", store_id)
        await conn.execute("delete from ingest_jobs where store_id = $1", store_id)
        await conn.execute("delete from sources where store_id = $1", store_id)
        # 매장을 지우면 기본 카테고리까지 cascade 되는데, 시스템 카테고리는
        # 보호 트리거가 막는다. 검증용 매장을 치우는 동안만 내려 둔다
        await conn.execute("alter table task_categories "
                           "disable trigger trg_task_categories_protect_system")
        await conn.execute("delete from stores where store_id = $1", store_id)
        await conn.execute("alter table task_categories "
                           "enable trigger trg_task_categories_protect_system")
        await conn.execute(
            "alter table fact_revisions enable trigger trg_fact_revision_immutable")
        await conn.execute(
            "alter table knowledge_snapshots enable trigger trg_snapshot_immutable")


async def _fact(conn, store_id: int, assertion: str) -> int:
    return await conn.fetchval(
        """
        insert into fact_revisions (store_id, fact_id, entity_id,
                                    original_assertion, assertion)
        values ($1, 1, 1, $2, $2) returning fact_revision_id
        """, store_id, assertion)


async def scenario_deletion(conn, ids: dict) -> None:
    """1. 자료를 지워도 사실과 근거는 남는다 (D20 / RV-11)."""
    store_id, source_id = ids["cp04-a"], ids["source"]
    fact_id = await conn.fetchval(
        """
        insert into source_facts (store_id, source_id, subject, attribute,
                                  value, content_hash)
        values ($1, $2, '대상', '속성', '값', 'h-cp04') returning fact_id
        """, store_id, source_id)
    revision = await _fact(conn, store_id, "  들여쓴 원문\n")
    await conn.execute(
        """
        insert into fact_occurrences (store_id, source_id, fact_revision_id,
                                      disposition, card_id, block_id)
        values ($1, $2, $3, 'LINKED', $4, 'b1')
        """, store_id, source_id, revision, ids["card"])

    state = await service.delete_source(conn, store_id=store_id, source_id=source_id)
    remaining = await conn.fetchval(
        "select count(*) from source_facts where fact_id = $1", fact_id)
    occurrence = await conn.fetchval(
        "select count(*) from fact_occurrences where store_id = $1", store_id)
    availability = await conn.fetchval(
        "select source_availability from sources where source_id = $1", source_id)
    check("자료 삭제는 tombstone 이고 사실이 남는다",
          state == "DELETED" and remaining == 1 and occurrence == 1
          and availability == "DELETED",
          f"사실 {remaining}건 · 근거 {occurrence}건 · 상태 {availability}")

    try:
        await service.purge_source(conn, store_id=store_id, source_id=source_id)
        check("근거로 쓰이는 자료의 물리 삭제를 막는다", False, "지워졌다")
    except service.SourceInUse:
        check("근거로 쓰이는 자료의 물리 삭제를 막는다", True)

    kept = await conn.fetchval(
        "select original_assertion from fact_revisions where fact_revision_id = $1",
        revision)
    check("원문의 공백이 DB 왕복에서 보존된다", kept == "  들여쓴 원문\n",
          repr(kept))


async def scenario_idempotency(conn, ids: dict) -> None:
    """2. 같은 멱등 키 재시도는 판을 올리지 않는다 (§4.3)."""
    store_id = ids["cp04-a"]
    kw = dict(store_id=store_id, member_id=None, idempotency_key="cp04-pub-1",
              body_hash=HASH, snapshot_hash=HASH, glossary_version="g1",
              renderer_version="r1")
    first = await service.publish_knowledge(
        conn, expected_publication_revision=0, **kw)
    again = await service.publish_knowledge(
        conn, expected_publication_revision=0, **kw)
    revision = await conn.fetchval(
        "select knowledge_revision from knowledge_publications where store_id = $1",
        store_id)
    check("같은 키 재시도가 판을 올리지 않는다",
          first.status == "PUBLISHED" and again.status == "ALREADY_APPLIED"
          and again.knowledge_revision == first.knowledge_revision
          and revision == first.knowledge_revision,
          f"{first.status} → {again.status}, 판 {revision}")

    try:
        await service.publish_knowledge(
            conn, expected_publication_revision=1,
            **{**kw, "body_hash": "sha256:" + "d" * 64})
        check("같은 키·다른 본문은 충돌이다", False, "통과했다")
    except service.IdempotencyConflict:
        check("같은 키·다른 본문은 충돌이다", True)

    stale = await service.publish_knowledge(
        conn, expected_publication_revision=0,
        **{**kw, "idempotency_key": "cp04-pub-2"})
    check("옛 판 번호로는 덮어쓰지 못한다", stale.status == "STALE", stale.status)

    events = await conn.fetchval(
        "select count(*) from outbox_events where store_id = $1", store_id)
    check("재시도가 사건을 늘리지 않는다", events == 1, f"사건 {events}건")


async def scenario_race(pool, ids: dict) -> None:
    """3. 동시에 두 발행이 들어오면 하나만 이긴다 (§4.2)."""
    store_id = ids["cp04-b"]
    async with pool.acquire() as conn:
        await conn.execute(
            "insert into knowledge_publications (store_id) values ($1) "
            "on conflict do nothing", store_id)

    async def attempt(key: str):
        async with pool.acquire() as conn, conn.transaction():
            return await service.publish_knowledge(
                conn, store_id=store_id, member_id=None, idempotency_key=key,
                body_hash=HASH, expected_publication_revision=0,
                snapshot_hash=HASH, glossary_version="g1", renderer_version="r1")

    left, right = await asyncio.gather(attempt("race-a"), attempt("race-b"))
    statuses = sorted([left.status, right.status])
    async with pool.acquire() as conn:
        revision = await conn.fetchval(
            "select knowledge_revision from knowledge_publications "
            "where store_id = $1", store_id)
        snapshots = await conn.fetchval(
            "select count(*) from knowledge_snapshots where store_id = $1", store_id)
    check("동시 발행에서 하나만 이긴다",
          statuses == ["PUBLISHED", "STALE"] and revision == 1 and snapshots == 1,
          f"{statuses} · 판 {revision} · snapshot {snapshots}건")


async def scenario_isolation(conn, ids: dict) -> None:
    """4. 다른 매장의 사실을 블록에 담을 수 없다 (D1 / composite FK)."""
    a, b = ids["cp04-a"], ids["cp04-b"]
    foreign_fact = await _fact(conn, b, "다른 매장의 사실")
    await conn.execute(
        """
        insert into card_version_blocks (store_id, card_version_id, block_id,
                                         kind, block_order)
        values ($1, 1, 'b1', 'NOTES', 1)
        """, a)
    try:
        async with conn.transaction():
            await conn.execute(
                """
                insert into card_block_facts (store_id, card_version_id,
                                              block_id, fact_revision_id, position)
                values ($1, 1, 'b1', $2, 1)
                """, a, foreign_fact)
        check("다른 매장의 사실을 블록에 담지 못한다", False, "들어갔다")
    except asyncpg.ForeignKeyViolationError:
        check("다른 매장의 사실을 블록에 담지 못한다", True)

    own = await _fact(conn, a, "이 매장의 사실")
    await conn.execute(
        """
        insert into card_block_facts (store_id, card_version_id, block_id,
                                      fact_revision_id, position)
        values ($1, 1, 'b1', $2, 1)
        """, a, own)
    check("같은 매장의 사실은 담긴다", True)


async def scenario_immutability(conn, ids: dict) -> None:
    """5. 승인된 판은 나중에 고칠 수 없다 (§3.4)."""
    store_id = ids["cp04-a"]
    revision = await conn.fetchval(
        "select fact_revision_id from fact_revisions where store_id = $1 limit 1",
        store_id)
    try:
        async with conn.transaction():
            await conn.execute(
                "update fact_revisions set assertion = '몰래 고침' "
                "where fact_revision_id = $1", revision)
        check("사실 판을 나중에 고치지 못한다", False, "고쳐졌다")
    except asyncpg.RaiseError:
        check("사실 판을 나중에 고치지 못한다", True)

    snapshot_id = await conn.fetchval(
        "select snapshot_id from knowledge_snapshots where store_id = $1 limit 1",
        store_id)
    try:
        async with conn.transaction():
            await conn.execute(
                "update knowledge_snapshots set snapshot_hash = $2 "
                "where snapshot_id = $1", snapshot_id, "sha256:" + "e" * 64)
        check("발행된 snapshot 을 고치지 못한다", False, "고쳐졌다")
    except asyncpg.RaiseError:
        check("발행된 snapshot 을 고치지 못한다", True)


MIGRATIONS = Path(__file__).resolve().parents[2] / "supabase" / "migrations"


async def rebuild() -> int:
    """빈 DB 에 migration 을 처음부터 쌓아 본다 (§7 인수 기준).

    돌아가는 DB 에서 통과하는 것과 처음부터 세워지는 것은 다른 문제다.
    이미 있는 표에 기대는 migration 은 여기서만 드러난다.
    """
    url = get_settings().supabase_db_url
    admin = await asyncpg.connect(url)
    await admin.execute("drop database if exists cp04_rebuild")
    await admin.execute("create database cp04_rebuild")
    await admin.close()

    fresh = await asyncpg.connect(url.rsplit("/", 1)[0] + "/cp04_rebuild")
    failed = None
    try:
        # Supabase 가 미리 만들어 두는 schema 들
        for schema in ("auth", "storage", "extensions", "graphql"):
            await fresh.execute(f"create schema if not exists {schema}")
        for path in sorted(MIGRATIONS.glob("*.sql")):
            try:
                await fresh.execute(path.read_text(encoding="utf-8"))
                print(f"  OK   {path.name}")
            except Exception as exc:
                failed = f"{path.name}: {exc}"
                print(f"  FAIL {path.name} — {exc}")
                break
    finally:
        await fresh.close()
        admin = await asyncpg.connect(url)
        await admin.execute("drop database if exists cp04_rebuild")
        await admin.close()

    print("\n재구축", "성공" if failed is None else "실패")
    return 1 if failed else 0


async def main() -> int:
    ap = argparse.ArgumentParser(description="CP-04 검증")
    ap.add_argument("--rebuild", action="store_true",
                    help="빈 DB 에 migration 을 처음부터 쌓는 검사만 한다")
    args = ap.parse_args()
    if args.rebuild:
        print("빈 DB 재구축 (§7)")
        return await rebuild()

    url = get_settings().supabase_db_url
    pool = await asyncpg.create_pool(url, min_size=2, max_size=4)
    conn = await asyncpg.connect(url)
    ids = None
    try:
        ids = await seed(conn)
        print("1. 자료 삭제 보존 (D20 / RV-11)")
        await scenario_deletion(conn, ids)
        print("2. 멱등성 (§4.3)")
        await scenario_idempotency(conn, ids)
        print("3. 동시성 (§4.2)")
        await scenario_race(pool, ids)
        print("4. 매장 격리 (D1)")
        await scenario_isolation(conn, ids)
        print("5. 불변성 (§3.4)")
        await scenario_immutability(conn, ids)
    finally:
        if ids:
            await cleanup(conn, ids)
        await conn.close()
        await pool.close()

    failed = [name for name, ok, _ in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} 통과")
    if failed:
        print("실패:", ", ".join(failed))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
