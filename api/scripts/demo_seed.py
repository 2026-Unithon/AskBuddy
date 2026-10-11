"""발표용 로컬 데모 매장을 카드 없이 심는다.

매장·계정·초대코드·카테고리·로드맵 틀(단계)·카드 없는 대기 질문만 만든다.
자료·지식카드·카드 인용 대화·공개 색인은 심지 않는다. 데모 카드는 자료를 업로드해
fact-only 경로(사실→카드)로 만든다. 카드 0장에서 시작하므로 첫 직원 질문은 이관된다.

    cd api && python scripts/demo_seed.py --yes

기본은 로컬 DB 만 건드린다. 배포 DB 로 심으려면 주소를 직접 주고
--remote 까지 붙여야 한다. 실수로 배포판을 갈아엎지 않기 위해서다.

    DEMO_SEED_DB_URL='postgresql://...pooler.supabase.com:5432/postgres' \
      python scripts/demo_seed.py --yes --remote
"""
import argparse
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import asyncpg  # noqa: E402
import bcrypt  # noqa: E402

from app.config import get_settings  # noqa: E402

KST = timezone(timedelta(hours=9))
SLUG = "demo-cafe"
PW = "demo1234"

OWNER = ("박사장", "owner@demo.cafe", "010-1000-0001")
STAFF = [
    ("김지현", "jihyun@demo.cafe", "010-2000-0001", 7),   # 일차
    ("이준호", "junho@demo.cafe", "010-2000-0002", 2),
]

CATEGORIES = [("오픈업무", True, 1), ("재고정리", True, 2), ("음료제작", True, 3),
              ("마감업무", True, 4), ("베이킹", False, 5)]

STAGE_ORDER = ["가게 투어", "식자재 위치", "레시피 숙지", "오픈 업무", "마감 업무"]

# 카드 없는 대기 질문 — (질문자, 질문, 미스 이유)
PENDING = [
    ("김지현", "아몬드브리즈 새 거 어디 있어요?", "no_match"),
    ("이준호", "포스기 영수증 용지 어디서 갈아요?", "no_match"),
]


async def archive_demo_store(c, slug: str, emails: list[str]) -> int | None:
    """옛 데모 매장을 보관 처리해 같은 slug·이메일·초대코드로 새로 만들 수 있게 한다.

    매장을 지우지 않는다. 비용 원장(ai_usage_attempts)은 매장 삭제를 막는 영구 기록이고
    (D21), 공개 색인을 만들면 임베딩 비용이 기록된다. 그래서 slug·이메일을 바꿔 비켜 두고
    초대코드만 지운다. 보관된 매장은 로그인·초대로 닿지 않는다.
    """
    old = await c.fetchval("select store_id from stores where store_slug = $1", slug)
    if old is not None:
        await c.execute(
            "update stores set store_slug = left($2 || '-archived-' || store_id, 50) "
            "where store_id = $1", old, slug)
        await c.execute("delete from invite_codes where store_id = $1", old)
    # 옛 계정도 지우지 않는다(매장·기록이 참조한다). 이메일만 비켜 둔다
    await c.execute(
        "update users set email = left(email || '.archived-' || user_id, 255) "
        "where email = any($1::text[])", emails)
    return old


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--yes", action="store_true", help="확인 없이 진행")
    ap.add_argument("--remote", action="store_true",
                    help="배포 DB 에 심는다. DEMO_SEED_DB_URL 이 있어야 한다")
    args = ap.parse_args()

    s = get_settings()
    url = os.environ.get("DEMO_SEED_DB_URL") or s.supabase_db_url
    host = url.split("@")[-1].split("/")[0] if "@" in url else url
    is_local = host.startswith(("127.0.0.1", "localhost"))

    if not is_local and not args.remote:
        print(f"거부: 로컬 DB 가 아니다 ({host}).\n"
              "배포 DB 에 심으려면 --remote 를 붙여라.", file=sys.stderr)
        return 2
    if args.remote and is_local:
        print(f"거부: --remote 인데 주소가 로컬이다 ({host}).\n"
              "DEMO_SEED_DB_URL 로 배포 DB 주소를 줘라.", file=sys.stderr)
        return 2
    where = "배포 DB" if args.remote else "로컬 DB"
    if not args.yes:
        print(f"{where}({host})의 '{SLUG}' 매장 데이터를 지우고 다시 만든다. 계속하려면 --yes")
        return 1
    print(f"  대상: {where} {host}")

    now = datetime.now(KST)
    c = await asyncpg.connect(url)
    try:
        async with c.transaction():
            # ── 초기화: 옛 데모 매장은 지우지 않고 보관한다 ─────────────────
            await archive_demo_store(c, SLUG, [OWNER[1]] + [x[1] for x in STAFF])

            # ── 사람 ──────────────────────────────────────────────────
            pw = bcrypt.hashpw(PW.encode(), bcrypt.gensalt(rounds=12)).decode()  # auth/router 와 같은 방식
            owner_id = await c.fetchval(
                "insert into users (name, phone, email, password_hash, role) "
                "values ($1,$2,$3,$4,'OWNER') returning user_id", OWNER[0], OWNER[2], OWNER[1], pw)
            store_id = await c.fetchval(
                "insert into stores (owner_id, store_slug, store_name, business_type, deploy_threshold) "
                "values ($1,$2,'카페 아무개','CAFE',80) returning store_id", owner_id, SLUG)
            await c.execute(
                "insert into store_members (store_id,user_id,member_role) values ($1,$2,'OWNER')",
                store_id, owner_id)
            await c.execute(
                "insert into invite_codes (store_id, code, expires_at) values ($1,'CAFE-DEMO',now()+interval '365 days')",
                store_id)

            members = {}
            for name, email, phone, day in STAFF:
                uid = await c.fetchval(
                    "insert into users (name, phone, email, password_hash, role) "
                    "values ($1,$2,$3,$4,'STAFF') returning user_id", name, phone, email, pw)
                mid = await c.fetchval(
                    "insert into store_members (store_id,user_id,member_role,day_count) "
                    "values ($1,$2,'STAFF',$3) returning member_id", store_id, uid, day)
                members[name] = (uid, mid)

            # ── 카테고리 ──────────────────────────────────────────────
            cat = {}
            for nm, en, order in CATEGORIES:
                cat[nm] = await c.fetchval(
                    "insert into task_categories (store_id,category_name,is_enabled,sort_order) "
                    "values ($1,$2,$3,$4) returning category_id", store_id, nm, en, order)

            # ── 로드맵 틀 (카드 없이 단계만) ───────────────────────────
            for order, sname in enumerate(STAGE_ORDER, 1):
                await c.execute(
                    "insert into roadmap_stages (store_id,stage_name,stage_order) values ($1,$2,$3)",
                    store_id, sname, order)

            # ── 카드 없는 대기 질문 ───────────────────────────────────
            sess = await c.fetchval(
                "insert into chat_sessions (store_id,member_id,started_at) values ($1,$2,$3) "
                "returning session_id", store_id, members["김지현"][1], now - timedelta(days=1))
            for name, q, reason in PENDING:
                mid = members[name][1]
                umsg = await c.fetchval(
                    "insert into chat_messages (session_id,sender_type,content,created_at) "
                    "values ($1,'USER',$2,$3) returning message_id", sess, q, now - timedelta(days=1))
                await c.fetchval(
                    "insert into chat_messages (session_id,sender_type,content,answer_type,"
                    "answer_source,grounding_status,created_at) "
                    "values ($1,'BUDDY','아직 확인된 내용이 없어요. 사장님께 확인 중이에요 🙏',"
                    "'NO_ANSWER','MISS','NOT_APPLICABLE',$2) returning message_id",
                    sess, now - timedelta(days=1) + timedelta(seconds=3))
                await c.execute(
                    "insert into pending_questions (store_id,member_id,message_id,question_text,"
                    "  miss_reason,status,created_at) values ($1,$2,$3,$4,$5,'WAITING',$6)",
                    store_id, mid, umsg, q, reason, now - timedelta(days=1))

        print(f"""
  ── 데모 준비 완료 (store_id={store_id}) ──
   사장님   {OWNER[1]} / {PW}
   알바생   {STAFF[0][1]} / {PW}
            {STAFF[1][1]} / {PW}
   초대코드 CAFE-DEMO

   카드 0장 · 대기질문 {len(PENDING)}건. 지식카드는 자료 업로드로 만든다.
""")
    finally:
        await c.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
