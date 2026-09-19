"""부분 실패 기록이 실제 DB 에서 성립하는지 확인한다 (W1).

구간 일부를 잃은 자료를 SUCCEEDED 로 적으면 점주는 빠진 내용을 모른다.
`PARTIAL` 상태와 구간 기록이 실제 CHECK 제약을 통과하는지, 기존 상태와
말이 안 되는 값의 거절이 그대로인지 새 DB 에 migration 을 올려 확인한다.

일회용 localhost DB 서버가 필요하다 (verify_r_answer_usage 와 같은 DSN).
"""
import asyncio
import sys
from pathlib import Path
from uuid import uuid4

import asyncpg
from verify_r_answer_usage import DSN

ROOT = Path(__file__).resolve().parents[2]
PASSED: list[str] = []
FAILED: list[str] = []


def check(name: str, ok: bool) -> None:
    (PASSED if ok else FAILED).append(name)
    print(("PASS " if ok else "FAIL ") + name)


async def _fresh_db(admin: asyncpg.Connection) -> tuple[str, asyncpg.Connection]:
    """migration 을 전부 올린 새 DB 를 만든다."""
    name = "w_partial_" + uuid4().hex
    for role in ("anon", "authenticated", "service_role"):
        if not await admin.fetchval(
                "select exists(select 1 from pg_roles where rolname=$1)", role):
            await admin.execute(f'create role "{role}" nologin')
    await admin.execute(f'create database "{name}"')
    db = await asyncpg.connect(DSN.rsplit("/", 1)[0] + "/" + name, timeout=5)
    for schema in ("auth", "storage", "extensions", "graphql"):
        await db.execute(f'create schema "{schema}"')
    for migration in sorted((ROOT / "supabase/migrations").glob("*.sql")):
        await db.execute(migration.read_text(encoding="utf-8"))
    return name, db


async def _seed(db: asyncpg.Connection) -> tuple[int, int, int]:
    """검증에 필요한 최소 매장·작업을 만든다. D1 — 모든 행이 store_id 를 갖는다."""
    user = await db.fetchval(
        "insert into users (name, phone, role) "
        "values ('검증점주','010-0000-0000','OWNER') returning user_id")
    store = await db.fetchval(
        "insert into stores (owner_id, store_name, business_type) "
        "values ($1,'격리검증점','CAFE') returning store_id", user)
    job = await db.fetchval(
        "insert into ingest_jobs (store_id, created_by, title, status, "
        "category_version, prompt_version) "
        "values ($1,$2,'부분실패 검증','EXTRACTING',1,'v1') returning job_id",
        store, user)
    return user, store, job


async def _new_source(db: asyncpg.Connection, store: int, user: int,
                      source_type: str = "VOICE") -> int:
    return await db.fetchval(
        "insert into sources (store_id, uploaded_by, source_type, status) "
        "values ($1,$2,$3,'DONE') returning source_id", store, user, source_type)


async def verify(db: asyncpg.Connection) -> None:
    user, store, job = await _seed(db)

    columns = {r["column_name"] for r in await db.fetch(
        "select column_name from information_schema.columns "
        "where table_name = 'ingest_job_sources'")}
    check("구간 기록 컬럼이 존재한다",
          {"segments_total", "segments_failed", "failed_segment_ids"} <= columns)

    # 옛 CHECK 가 남아 있으면 여기서 죽는다
    source = await _new_source(db, store, user, "VIDEO")
    try:
        await db.execute(
            "insert into ingest_job_sources (store_id, job_id, source_id, status, "
            "card_count, segments_total, segments_failed, failed_segment_ids) "
            "values ($1,$2,$3,'PARTIAL',3,10,3,$4)",
            store, job, source, ["seg2", "seg5", "seg9"])
        check("PARTIAL 상태가 저장된다", True)
    except Exception as exc:
        check(f"PARTIAL 상태가 저장된다 ({type(exc).__name__}: {exc})", False)

    row = await db.fetchrow(
        "select segments_total, segments_failed, failed_segment_ids "
        "from ingest_job_sources "
        "where store_id = $1 and job_id = $2 and source_id = $3",
        store, job, source)
    check("잃은 구간 이름이 보존된다",
          bool(row) and list(row["failed_segment_ids"]) == ["seg2", "seg5", "seg9"])
    check("10구간 중 3구간 실패로 기록된다",
          bool(row) and row["segments_total"] == 10 and row["segments_failed"] == 3)

    # 전체보다 많은 실패는 계측 오류다. 조용히 받지 않는다
    source = await _new_source(db, store, user, "VIDEO")
    try:
        await db.execute(
            "insert into ingest_job_sources (store_id, job_id, source_id, status, "
            "segments_total, segments_failed) values ($1,$2,$3,'PARTIAL',3,5)",
            store, job, source)
        check("전체보다 많은 실패 구간은 거절된다", False)
    except asyncpg.CheckViolationError:
        check("전체보다 많은 실패 구간은 거절된다", True)

    # 기존 계약이 그대로여야 한다
    for status in ("QUEUED", "EXTRACTING", "CLASSIFYING",
                   "SUCCEEDED", "NO_RESULT", "FAILED"):
        source = await _new_source(db, store, user)
        try:
            await db.execute(
                "insert into ingest_job_sources (store_id, job_id, source_id, status) "
                "values ($1,$2,$3,$4)", store, job, source, status)
            ok = True
        except Exception:
            ok = False
        check(f"기존 상태 {status} 가 그대로 허용된다", ok)

    source = await _new_source(db, store, user)
    try:
        await db.execute(
            "insert into ingest_job_sources (store_id, job_id, source_id, status) "
            "values ($1,$2,$3,'NONSENSE')", store, job, source)
        check("정의되지 않은 상태는 거절된다", False)
    except asyncpg.CheckViolationError:
        check("정의되지 않은 상태는 거절된다", True)


async def verify_checkpoint_durability(db: asyncpg.Connection) -> None:
    """구간을 뽑는 즉시 적은 사실이 뒤쪽 구간의 죽음에서 살아남는지 확인한다.

    오프라인 테스트는 checkpoint 가 불렸다는 것만 증명한다. 정말 커밋됐는지는
    실제 트랜잭션에서만 알 수 있다.
    """
    from types import SimpleNamespace as NS
    from unittest.mock import patch

    from app.ingest import extract
    from app.ingest.pipeline import _extract_facts_all, _persist_ledger
    from app.ingest.schemas import Evidence, ExtractedAssertion

    user, store, _ = await _seed(db)
    source = await _new_source(db, store, user, "VIDEO")

    async def checkpoint(assertions, segment_id):
        async with db.transaction():
            await _persist_ledger(db, store, source, "VIDEO", assertions)

    calls = {"n": 0}

    async def fake_extract_facts(**kw):
        calls["n"] += 1
        if calls["n"] > 2:
            raise KeyboardInterrupt("프로세스가 죽었다")
        return NS(assertions=[ExtractedAssertion(
            local_ref=f"f{calls['n']}", original_assertion=f"원두 {calls['n']}8g",
            subject="음료Z", attribute="원두량", value=f"{calls['n']}8", unit="g",
            confidence=.9, evidence=Evidence(timestamp_sec=1))], unresolved=[])

    segments = [(f"구간{i}", []) for i in range(1, 4)]
    crashed = False
    with patch.object(extract, "extract_facts", side_effect=fake_extract_facts):
        try:
            await _extract_facts_all(
                source_id=source, source_type="VIDEO", text="", media=[],
                glossary=[], segments=segments, checkpoint=checkpoint)
        except KeyboardInterrupt:
            crashed = True
    check("3구간째에서 프로세스가 죽었다", crashed)

    rows = await db.fetch(
        "select segment_id, value from source_facts "
        "where store_id = $1 and source_id = $2 order by segment_id",
        store, source)
    check("죽기 전 구간의 사실이 원장에 남아 있다",
          [r["segment_id"] for r in rows] == ["seg1", "seg2"])
    check("남은 사실의 값이 보존된다",
          [r["value"] for r in rows] == ["18", "28"])

    # 같은 구간을 다시 돌려도 중복 행을 만들지 않아야 재처리가 가능하다
    replay = [ExtractedAssertion(
        local_ref="f1", original_assertion="원두 18g", subject="음료Z",
        attribute="원두량", value="18", unit="g", confidence=.9,
        segment_id="seg1", evidence=Evidence(timestamp_sec=1))]
    async with db.transaction():
        await _persist_ledger(db, store, source, "VIDEO", replay)
    total = await db.fetchval(
        "select count(*) from source_facts where store_id = $1 and source_id = $2",
        store, source)
    check("같은 구간 재처리가 중복 사실을 만들지 않는다", total == 2)


async def main() -> None:
    admin = await asyncpg.connect(DSN, timeout=5)
    name, db = await _fresh_db(admin)
    try:
        await verify(db)
        await verify_checkpoint_durability(db)
    finally:
        await db.close()
        await admin.execute(f'drop database "{name}"')
        await admin.close()
    print(f"\nVerified {len(PASSED)} W partial-extraction checks")
    if FAILED:
        print(f"{len(FAILED)} FAILED: " + ", ".join(FAILED))
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
