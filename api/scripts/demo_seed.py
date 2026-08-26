"""발표용 로컬 데모 각본을 통째로 심는다.

시연 중에는 업로드→전사→추출을 돌릴 시간이 없다. 그래서 이미 다 끝난 상태로 시작한다.
자료가 올라가 있고, 지식이 구축돼 있고, 질문이 오갔고, 못 답한 것과 점주가 답해준 것이
섞여 있다. 내용은 전부 testdata/ 의 실제 자료에 근거한다.

    cd api && python scripts/demo_seed.py --yes

기본은 로컬 DB 만 건드린다. 배포 DB 로 심으려면 주소를 직접 주고
--remote 까지 붙여야 한다. 실수로 배포판을 갈아엎지 않기 위해서다.

    DEMO_SEED_DB_URL='postgresql://...pooler.supabase.com:5432/postgres' \
      python scripts/demo_seed.py --yes --remote
"""
import argparse
import asyncio
import hashlib
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import asyncpg  # noqa: E402
import bcrypt  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.reg.embeddings import content_hash, embed_texts, vector_literal  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
TESTDATA = ROOT / "testdata"
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

# (source_key, source_type, 파일, 제목, 며칠 전)
SOURCES = [
    ("video",  "VIDEO", "video/store_walkthrough.mp4",      "매장 한 바퀴 투어",        8),
    ("narr",   "VOICE", "video/store_walkthrough_narration.txt", "매장 투어 음성 설명", 8),
    ("kakao",  "KAKAO", "chat/kakao_staff_group.txt",       "알바방 대화 내보내기",     3),
    ("cap",    "KAKAO", "chat/chat_capture_notice.png",     "원두 변경 공지 캡처",      2),
    ("recipe", "SCAN",  "docs/beverage_recipes.pdf",        "음료 레시피북",           6),
    ("close",  "SCAN",  "docs/closing_checklist.pdf",       "마감 체크리스트",         6),
    ("memo",   "SCAN",  "photos/02_hotwater_memo.jpg",      "온수기 옆 손글씨 메모",    1),
    ("jars",   "SCAN",  "photos/10_portioned_jars.jpg",     "소분 용기 라벨",          1),
]

# (카테고리, 제목, 본문, 신뢰도, 출처키, 승인여부)
CARDS = [
    ("오픈업무", "온수기 전원과 예열 시간",
     "출근하면 온수기 전원을 가장 먼저 켭니다. 90도까지 올라오는 데 15분 걸리니 그동안 다른 준비를 하세요.",
     92, "kakao", True),
    ("오픈업무", "오픈 시 첫 샷 버리기",
     "머신이 예열되면 첫 샷은 뽑아서 버립니다. 밤새 그룹헤드에 남아 있던 물이 빠져야 하기 때문입니다.",
     90, "kakao", True),
    ("오픈업무", "그라인더 호퍼 원두 채우기",
     "온수기가 데워지는 동안 그라인더 호퍼에 원두를 채워둡니다. 원두는 제빙기 아래 세 번째 선반에 있습니다.",
     88, "kakao", True),
    ("재고정리", "우유 보관 위치",
     "우유는 머신 아래 작업대 하부의 언더카운터 냉장고에 있습니다. 오픈 때 유통기한을 확인하고 이틀 남은 것은 앞으로 빼둡니다.",
     94, "narr", True),
    ("재고정리", "컵 보관 위치",
     "일회용 컵은 바 하부장 왼쪽 칸에 있습니다. 예전에는 냉장고 위 선반에 뒀지만 자리를 옮겼습니다.",
     91, "kakao", True),
    ("재고정리", "시럽·소스류 위치",
     "시럽과 소스류는 에스프레소 머신 오른쪽 선반에 있습니다. 왼쪽부터 바닐라, 헤이즐넛, 카라멜 순서입니다.",
     89, "narr", True),
    ("재고정리", "원두 종류 변경 안내",
     "드립용 원두가 에티오피아 예가체프로 바뀌었습니다. 기존 브라질 산토스는 라벨을 붙여 그라인더 옆 밀폐용기에 따로 보관합니다.",
     86, "cap", True),
    ("재고정리", "세제·살균제 위치",
     "싱크대 수전 뒤쪽 벽에 흰색 펌프통 세 개가 걸려 있습니다. 용도가 다르니 라벨을 확인하고 쓰세요.",
     72, "narr", True),
    ("음료제작", "아이스 아메리카노 기준",
     "아이스 아메리카노는 샷 2개가 기본입니다. 얼음은 컵의 8부까지 채우고 물을 부은 뒤 샷을 올립니다.",
     93, "recipe", True),
    ("음료제작", "라떼 스팀 온도",
     "라떼용 우유 스팀 온도는 65도로 맞춥니다. 더 뜨거우면 우유 맛이 죽습니다.",
     90, "recipe", True),
    ("음료제작", "밀크티 베이스 배합",
     "밀크티는 베이스 130g에 우유 190g을 넣습니다. 온수기 옆 메모에 적힌 기준입니다.",
     87, "memo", True),
    ("음료제작", "콜드브루 원액 기준",
     "콜드브루는 원액 120g을 기준으로 씁니다. 얼음이 녹는 것을 감안해 물은 따로 넣지 않습니다.",
     85, "memo", True),
    ("음료제작", "에스프레소 머신 사용 순서",
     "란실리오 머신은 나무 탬핑매트 바로 뒤에 있습니다. 포터필터는 그룹헤드에 꽂아두고, 장착 전에 물을 살짝 뽑아 열수를 빼줍니다.",
     88, "narr", True),
    ("마감업무", "마감 시 그라인더 정리",
     "호퍼에 남은 원두는 원두통에 다시 붓고, 넉박스는 비워서 물로 헹굽니다. 분쇄도 다이얼은 절대 건드리지 않습니다.",
     95, "close", True),
    ("마감업무", "마감 시 기기 세척",
     "머신 그룹헤드를 물을 틀어가며 닦고, 포터필터도 헹궈 다시 장착해 둡니다.",
     89, "close", True),
    ("재고정리", "소분 용기 라벨 규칙",
     "소분한 재료는 용기에 내용물과 소분한 날짜를 함께 적습니다. 라벨이 없는 용기는 쓰지 않습니다.",
     83, "jars", True),
    # ↓ 검수 화면 시연용 — 아직 승인 전
    ("음료제작", "시럽 펌프 횟수",
     "헤이즐넛 시럽은 HOT 기준 2펌프입니다. 다만 벽에 붙은 손글씨 메모에는 1.5+1로 적혀 있어 확인이 필요합니다.",
     48, "recipe", False),
    ("마감업무", "아이스머신 배수",
     "마감 때 아이스머신 배수 밸브를 열어 물을 뺍니다. 밸브 위치는 자료에서 확인되지 않았습니다.",
     42, "video", False),
    ("오픈업무", "전자레인지·토스터 사용",
     "주방 벽 안내문에 전자레인지와 토스터 사용법이 붙어 있습니다. 세부 시간은 판독이 어렵습니다.",
     55, "memo", False),
]

# 신입이 실제로 물어본 것들 — (며칠 전, 질문, 결과)
#   hit    : 답변 성공 (근거 카드 제목)
#   miss   : 못 답함 → 대기질문 (아직 WAITING)
#   solved : 못 답했다가 점주가 답해줌 → 지식으로 반영됨
CHAT = [
    (3, "우유 어디 보관해요?", "hit", "우유 보관 위치"),
    (3, "아아 샷 몇 개 넣어요?", "hit", "아이스 아메리카노 기준"),
    (2, "마감할 때 그라인더는 어떻게 해요?", "hit", "마감 시 그라인더 정리"),
    (2, "아몬드브리즈 새 거 어디 있어요?", "miss", "no_match"),
    (1, "컵이 선반에 안 보이는데 어디 있나요?", "solved",
     "컵은 바 하부장 왼쪽 칸으로 옮겼어요. 예전 자리(냉장고 위 선반)에는 이제 없습니다."),
    (1, "포스기 영수증 용지 어디서 갈아요?", "miss", "no_match"),
]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else \
        hashlib.sha256(str(path).encode()).hexdigest()


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
    if not s.openai_api_key:
        print("OPENAI_API_KEY 가 없다. 임베딩을 못 만들어 검색이 동작하지 않는다.", file=sys.stderr)
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
            # ── 초기화: 데모 매장만 지운다 ──────────────────────────────
            old = await c.fetchval("select store_id from stores where store_slug = $1", SLUG)
            if old:
                await c.execute("delete from stores where store_id = $1", old)
            await c.execute(
                "delete from users where email = any($1::text[])",
                [OWNER[1]] + [x[1] for x in STAFF])

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

            # ── 올려둔 자료 ────────────────────────────────────────────
            src = {}
            for key, kind, rel, title, days in SOURCES:
                path = TESTDATA / rel
                sid = await c.fetchval(
                    "insert into sources (store_id, uploaded_by, source_type, title, file_url, "
                    "  file_size, content_hash, status, processed_at, created_at) "
                    "values ($1,$2,$3,$4,$5,$6,$7,'DONE',$8,$8) returning source_id",
                    store_id, owner_id, kind, title,
                    f"sources/{store_id}/{kind.lower()}/{key}{path.suffix}",
                    path.stat().st_size if path.exists() else 0,
                    sha(path), now - timedelta(days=days))
                src[key] = sid
                if kind == "VOICE":
                    await c.execute(
                        "insert into source_voice (source_id,audio_format,duration_sec,record_method,"
                        "  transcript,stt_model) values ($1,'m4a',196,'UPLOAD',$2,'whisper-1')",
                        sid, (path.read_text(encoding="utf-8")[:1500] if path.exists() else ""))
                elif kind == "VIDEO":
                    vid = await c.fetchval(
                        "insert into source_video (source_id,video_format,duration_sec,resolution,fps,frame_count) "
                        "values ($1,'mp4',32,'1280x720',24,11) returning video_id", sid)
                    await c.executemany(
                        "insert into source_frames (video_id,frame_index,timestamp_sec,image_url) "
                        "values ($1,$2,$3,$4)",
                        [(vid, i, i * 3, f"sources/{store_id}/frames/{sid}/{i:04d}.jpg") for i in range(11)])
                elif kind == "KAKAO":
                    shot = path.suffix.lower() in (".png", ".jpg", ".jpeg")
                    await c.execute(
                        "insert into source_kakao (source_id,import_type,room_name,message_count,participant_cnt) "
                        "values ($1,$2,'테스트 카페 알바방',$3,$4)",
                        sid, "SCREENSHOT" if shot else "TXT_EXPORT", 0 if shot else 23, 0 if shot else 3)
                else:
                    await c.execute(
                        "insert into source_scan (source_id,doc_type,doc_category,page_count,ocr_engine) "
                        "values ($1,$2,'MANUAL',$3,'gemini')",
                        sid, "PDF" if path.suffix.lower() == ".pdf" else "JPG",
                        2 if "recipe" in rel else 1)

            # ── 지식카드 ──────────────────────────────────────────────
            cards = {}
            for cname, title, body, conf, skey, verified in CARDS:
                cid = await c.fetchval(
                    "insert into knowledge_cards (store_id,category_id,source_id,title,content,"
                    "  confidence,is_verified,created_at,updated_at) "
                    "values ($1,$2,$3,$4,$5,$6,$7,$8,$9) returning card_id",
                    store_id, cat[cname], src.get(skey), title, body, conf, verified,
                    now - timedelta(days=2), now - timedelta(days=1) if verified else None)
                cards[title] = cid

            # ── 로드맵 ────────────────────────────────────────────────
            stages = [("가게 투어", ["매장 전체 둘러보기", "주요 장비 위치 파악", "비상구·소화기 위치"]),
                      ("식자재 위치", ["냉장고 위치", "냉동고 위치", "식자재 보관 위치", "소모품 위치"]),
                      ("레시피 숙지", ["아이스 아메리카노", "카페라떼", "밀크티·콜드브루"]),
                      ("오픈 업무", ["온수기 예열", "그라인더 원두 채우기", "첫 샷 버리기"]),
                      ("마감 업무", ["기기 세척", "그라인더 정리", "정산 및 시건"])]
            items = []
            for order, (sname, its) in enumerate(stages, 1):
                stg = await c.fetchval(
                    "insert into roadmap_stages (store_id,stage_name,stage_order) values ($1,$2,$3) "
                    "returning stage_id", store_id, sname, order)
                for io_, iname in enumerate(its, 1):
                    items.append(await c.fetchval(
                        "insert into roadmap_items (stage_id,item_name,item_order) values ($1,$2,$3) "
                        "returning item_id", stg, iname, io_))

            # 김지현: 3단계까지(10/18) · 이준호: 1단계(3/18)
            for name, upto in (("김지현", 10), ("이준호", 3)):
                mid = members[name][1]
                for i, item_id in enumerate(items):
                    st = "DONE" if i < upto else ("IN_PROGRESS" if i == upto else "LOCKED")
                    await c.execute(
                        "insert into learning_progress (member_id,item_id,status,completed_at) "
                        "values ($1,$2,$3,$4)",
                        mid, item_id, st,
                        now - timedelta(days=max(1, 5 - i // 3)) if st == "DONE" else None)
                rate = round(upto / len(items) * 100, 2)
                await c.execute(
                    "update store_members set progress_rate=$2, is_deployable=$3, last_active_at=now() "
                    "where member_id=$1", mid, rate, rate >= 80)

            # ── 오간 대화 ─────────────────────────────────────────────
            uid, mid = members["김지현"]
            sess = await c.fetchval(
                "insert into chat_sessions (store_id,member_id,started_at) values ($1,$2,$3) "
                "returning session_id", store_id, mid, now - timedelta(days=3))
            for days, q, kind, extra in CHAT:
                at = now - timedelta(days=days)
                umsg = await c.fetchval(
                    "insert into chat_messages (session_id,sender_type,content,created_at) "
                    "values ($1,'USER',$2,$3) returning message_id", sess, q, at)
                if kind == "hit":
                    card_id = cards[extra]
                    body = await c.fetchval("select content from knowledge_cards where card_id=$1", card_id)
                    bmsg = await c.fetchval(
                        "insert into chat_messages (session_id,sender_type,content,answer_type,confidence,created_at) "
                        "values ($1,'BUDDY',$2,'ANSWERED',$3,$4) returning message_id",
                        sess, body, 90, at + timedelta(seconds=3))
                    await c.execute(
                        "insert into message_citations (message_id,card_id,relevance) values ($1,$2,$3)",
                        bmsg, card_id, 88)
                else:
                    bmsg = await c.fetchval(
                        "insert into chat_messages (session_id,sender_type,content,answer_type,created_at) "
                        "values ($1,'BUDDY','아직 확인된 내용이 없어요. 사장님께 확인 중이에요 🙏','NO_ANSWER',$2) "
                        "returning message_id", sess, at + timedelta(seconds=3))
                    if kind == "miss":
                        await c.execute(
                            "insert into pending_questions (store_id,member_id,message_id,question_text,"
                            "  miss_reason,status,created_at) values ($1,$2,$3,$4,$5,'WAITING',$6)",
                            store_id, mid, umsg, q, extra, at)
                    else:  # solved — 점주가 답해줘서 지식이 된 것
                        qid = await c.fetchval(
                            "insert into pending_questions (store_id,member_id,message_id,question_text,"
                            "  miss_reason,status,created_at) values ($1,$2,$3,$4,'no_match','ANSWERED',$5) "
                            "returning question_id", store_id, mid, umsg, q, at)
                        await c.execute(
                            "insert into owner_answers (question_id,answered_by,answer_text,card_id,answered_at) "
                            "values ($1,$2,$3,$4,$5)",
                            qid, owner_id, extra, cards["컵 보관 위치"], at + timedelta(hours=2))
                        await c.execute(
                            "insert into chat_messages (session_id,sender_type,content,answer_type,confidence,created_at) "
                            "values ($1,'BUDDY',$2,'ANSWERED',95,$3)",
                            sess, extra, at + timedelta(hours=2, seconds=5))

        # ── 임베딩 (트랜잭션 밖 — 외부 호출) ──────────────────────────
        rows = await c.fetch(
            "select card_id, title, content from knowledge_cards "
            "where store_id=$1 and is_verified order by card_id", store_id)
        texts = [f"{r['title']}\n{r['content']}" for r in rows]
        print(f"  임베딩 {len(texts)}건 생성 중…")
        vecs = embed_texts(texts)
        for r, t, v in zip(rows, texts, vecs):
            await c.execute(
                "insert into card_embeddings (card_id,store_id,chunk_index,chunk_text,embedding,"
                "  dimension,model_name,content_hash,lexical_tsv) "
                "values ($1,$2,0,$3,$4::vector,$5,$6,$7,to_tsvector('simple',$3))",
                r["card_id"], store_id, t, vector_literal(v), s.embedding_dim,
                s.embedding_model, content_hash(t))

        print(f"""
  ── 데모 준비 완료 (store_id={store_id}) ──
   사장님   {OWNER[1]} / {PW}
   알바생   {STAFF[0][1]} / {PW}   진도 55.56%
            {STAFF[1][1]} / {PW}   진도 16.67%
   초대코드 CAFE-DEMO

   자료 {len(SOURCES)}건 · 카드 {len(CARDS)}건(승인 {len(texts)} · 검수대기 {len(CARDS)-len(texts)})
   대화 {len(CHAT)}건 · 대기질문 2건 · 점주가 답해준 것 1건
""")
    finally:
        await c.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
