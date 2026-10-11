"""P7 실제 HTTP·DB 브라우저 검증 실행기.

전용 localhost:55439의 pgvector PostgreSQL 17에 새 UUID DB를 만들고 종료 시 지운다.
.env를 읽지 않는 임시 cwd에서 FastAPI를 띄운다. 공유 개발 DB·외부 모델은 사용하지 않는다.
사전: pgvector/pgvector:pg17, 포트 55439, postgres/synthetic-local-test, DB usage_verify.
실행: api/에서 python scripts/verify_p7_integration.py (Playwright는 NODE_PATH로 찾을 수 있다).
"""
from __future__ import annotations

import asyncio
import json
import os
import socket
from pathlib import Path
import subprocess
import sys
import tempfile
from uuid import uuid4

import asyncpg
import bcrypt
import httpx

ROOT = Path(__file__).resolve().parents[2]
ADMIN_DSN = "postgresql://postgres:synthetic-local-test@127.0.0.1:55439/usage_verify"
ARTIFACTS = ROOT / "docs/dev/review/p7_20261008"


async def seed(db):
    password = "synthetic-p7-password"
    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=4)).decode()
    owner = await db.fetchval("insert into users(name,role,email,password_hash) values('합성 점주','OWNER','p7-owner@example.com',$1) returning user_id", hashed)
    staff = await db.fetchval("insert into users(name,role,email,password_hash) values('합성 알바','STAFF','p7-staff@example.com',$1) returning user_id", hashed)
    store = await db.fetchval("insert into stores(owner_id,store_name,business_type,guide_completed_at) values($1,'합성 P7 검증 매장','CAFE',now()) returning store_id", owner)
    await db.execute("insert into store_members(store_id,user_id,member_role) values($1,$2,'OWNER')", store, owner)
    member = await db.fetchval("insert into store_members(store_id,user_id,member_role) values($1,$2,'STAFF') returning member_id", store, staff)
    category = await db.fetchval("insert into task_categories(store_id,category_name,sort_order) values($1,'매장 관리',1) returning category_id", store)
    job = await db.fetchval("insert into ingest_jobs(store_id,created_by,title,status,category_version,prompt_version,card_count) values($1,$2,'합성 등록 결과','SUCCEEDED',1,'P7_FIXTURE',2) returning job_id", store, owner)
    cards = []
    for title, content in (("합성 청소 안내", "머신 청소\n바닥 닦기"), ("합성 공통 안내 · 직원이 읽기 쉽게 적은 길고 상세한 매장 정리 안내", "작업대 닦기")):
        card = await db.fetchval("insert into knowledge_cards(store_id,category_id,origin_job_id,title,content,review_status) values($1,$2,$3,$4,$5,'APPROVED') returning card_id", store, category, job, title, content)
        # 레거시 판 트리거가 없어졌다(Phase A) — 판 1 을 명시적으로 만들고 초안·공개 포인터를 둔다
        version = await db.fetchval("insert into card_versions(store_id,card_id,version_no,title,content,change_source) values($1,$2,1,$3,$4,'EXTRACTION') returning version_id", store, card, title, content)
        await db.execute("update knowledge_cards set draft_version_id=$3, published_version_id=$3 where store_id=$1 and card_id=$2", store, card, version)
        cards.append(card)
    item = await db.fetchval("select item_id from roadmap_items where card_id=$1 and is_active limit 1", cards[0])
    session = await db.fetchval("insert into chat_sessions(store_id,member_id,contract_version) values($1,$2,'v2') returning session_id", store, member)
    pending = await db.fetchval("insert into pending_questions(store_id,member_id,question_text,contract_version,semantic_key) values($1,$2,'합성 직원 질문','v2','p7-ui-question') returning question_id", store, member)
    for recipient, event, aggregate, aid, title, destination in (
        (owner, 'PENDING_QUESTION', 'PENDING_QUESTION', pending, '합성 질문 알림', f'/owner/questions/v2?question_id={pending}'),
        (staff, 'OWNER_ANSWER', 'OWNER_ANSWER', 1, '합성 답변 알림', f'/staff/chat/v2?session_id={session}'),
    ):
        await db.execute("""insert into notification_events(store_id,recipient_user_id,event_type,aggregate_type,aggregate_id,dedupe_key,title,body,destination)
                         values($1,$2,$3,$4,$5,$6,$7,'합성 알림 내용',$8)""", store, recipient, event, aggregate, aid, f'p7:{recipient}:{event}', title, destination)
    return dict(password=password, owner=owner, staff=staff, member=member, store=store, category=category,
                cards=cards, item=item, job=job, session=session, pending=pending)


async def ready(url, process):
    async with httpx.AsyncClient() as client:
        for _ in range(100):
            if process.poll() is not None:
                raise RuntimeError(f"server stopped before ready: {url}")
            try:
                if (await client.get(url)).status_code == 200:
                    return
            except httpx.TransportError:
                pass
            await asyncio.sleep(0.2)
    raise RuntimeError(f"server readiness timeout: {url}")


async def main():
    for port in (8000, 3011):
        with socket.socket() as probe:
            if probe.connect_ex(("127.0.0.1", port)) == 0:
                raise RuntimeError(f"test port {port} is already in use")
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    admin = await asyncpg.connect(ADMIN_DSN, timeout=5)
    name = 'p7_ui_' + uuid4().hex
    db = None
    api = web = None
    created = False
    try:
        for role in ("anon", "authenticated", "service_role"):
            if not await admin.fetchval("select exists(select 1 from pg_roles where rolname=$1)", role):
                await admin.execute(f'create role "{role}" nologin')
        await admin.execute(f'create database "{name}"')
        created = True
        dsn = ADMIN_DSN.rsplit('/', 1)[0] + '/' + name
        db = await asyncpg.connect(dsn)
        for schema in ('auth', 'storage', 'extensions', 'graphql'):
            await db.execute(f'create schema "{schema}"')
        migrations = sorted((ROOT / 'supabase/migrations').glob('*.sql'))
        for migration in migrations:
            await db.execute(migration.read_text())
        print(f"PASS P7 rebuilt {len(migrations)} migrations", flush=True)
        fixture = await seed(db)
        with tempfile.TemporaryDirectory(prefix='askbuddy-p7-http-') as temporary:
            fixture_file = Path(temporary) / 'fixture.json'
            fixture_file.write_text(json.dumps(fixture))
            fixture_file.chmod(0o600)
            env = {**os.environ, 'SUPABASE_DB_URL': dsn, 'JWT_SECRET': 'synthetic-p7-only-secret-32bytes',
                   'ALLOWED_ORIGINS': 'http://127.0.0.1:3011,http://localhost:3011',
                   'R_V2_ENABLED': 'true', 'W_OWNER_ANSWER_WORKER_ENABLED': 'false',
                   'OPENAI_API_KEY': '', 'GEMINI_API_KEY': '', 'ANTHROPIC_API_KEY': '',
                   'INGEST_MODE': 'mock', 'ENV': 'local', 'PYTHONPATH': str(ROOT / 'api'),
                   'P7_FIXTURE_FILE': str(fixture_file), 'P7_ARTIFACT_DIR': str(ARTIFACTS / 'screenshots')}
            with (ARTIFACTS / 'api.log').open('w') as api_log, (ARTIFACTS / 'web.log').open('w') as web_log:
                api = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8000'], cwd=temporary, env=env, stdout=api_log, stderr=subprocess.STDOUT)
                await ready('http://127.0.0.1:8000/openapi.json', api)
                web = subprocess.Popen(['pnpm', 'start', '--port', '3011'], cwd=ROOT / 'web', env=env, stdout=web_log, stderr=subprocess.STDOUT)
                await ready('http://127.0.0.1:3011', web)
                result = await asyncio.to_thread(subprocess.run, ['node', str(ROOT / 'api/scripts/verify_p7_ui.cjs')], cwd=ROOT, env=env, check=False)
                if result.returncode:
                    raise RuntimeError('P7 browser verification failed; see browser output and server logs')
        assert await db.fetchval('select count(*) from checklist_check_events where store_id=$1', fixture['store']) > 0
        assert await db.fetchval('select count(*) from checklist_submissions where store_id=$1 and late', fixture['store']) > 0
        assert await db.fetchval('select count(*) from notification_events where store_id=$1 and read_at is not null', fixture['store']) == 2
        print('PASS P7 DB persisted check events, late submission, notification reads', flush=True)
    finally:
        for process in (web, api):
            if process is not None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
        if db is not None:
            await db.close()
        if created:
            await admin.execute(f'drop database "{name}" with (force)')
        await admin.close()
        print('P7 isolated database and test servers cleaned up', flush=True)


if __name__ == '__main__':
    asyncio.run(main())
