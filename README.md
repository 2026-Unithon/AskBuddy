# AskBuddy

카페 등 소규모 매장의 업무 인수인계를 AI가 대신하는 서비스.
점주가 음성·영상·카톡·문서를 올리면 지식카드로 정리되고, 신입은 로드맵과 채팅으로 배운다.

**승인된 매장 지식만 근거로 답한다. 근거가 없으면 추정하지 않고 점주에게 넘긴다.**

---

## 문서

| 파일 | 용도 |
|---|---|
| [`CLAUDE.md`](./CLAUDE.md) | Claude Code 세션 컨텍스트. 자동으로 읽힘 |
| [`docs/AskBuddy_개발가이드.md`](./docs/AskBuddy_개발가이드.md) | **정본.** 아키텍처·계약·결정사항·개발 순서 |
| [`docs/AskBuddy_환경세팅.md`](./docs/AskBuddy_환경세팅.md) | 파트별 환경 구성 |
| [`db/001_init_schema.sql`](./db/001_init_schema.sql) | 스키마 원천 |

---

## 구조

```
askbuddy/
├─ CLAUDE.md                    # 공용 — Claude Code 세션 컨텍스트. 자동으로 읽힘
├─ README.md                    # 공용
├─ .gitignore                   # 공용 — .env, .venv, node_modules, api/tmp, db/data
├─ db/                          # 관호
│  ├─ 001_init_schema.sql       # 21 테이블 + pgvector. 스키마 원천
│  └─ 002_seed_demo.sql         # demo-cafe 시드
├─ api/                         # FastAPI (Python 3.12)
│  ├─ app/
│  │  ├─ main.py                # 공용 — 라우터 등록만. 세 줄 이미 등록됨
│  │  ├─ deps.py                # 공용 — DB 풀, JWT, CurrentStoreId, resolve_store_id
│  │  ├─ config.py              # 공용 — 환경변수. D3·D4 고정값은 여기 참조
│  │  ├─ auth/router.py         # 관호 — 가입 · 로그인 · 초대코드 합류
│  │  ├─ reg/router.py          # 관호 — 등록 · 검색 게이트 (/reg/retrieve)
│  │  └─ ingest/                # 준혁
│  │     ├─ router.py           #   /ingest/process · /ingest/status
│  │     ├─ preprocess/         #   ffmpeg · pypdf · 카톡 파서
│  │     ├─ extract/            #   Gemini 호출
│  │     └─ embed/              #   임베딩 적재 (생성은 관호님 코드 호출)
│  ├─ prompts/                  # 준혁 — 프롬프트 파일. 코드 하드코딩 금지
│  ├─ scripts/                  # 관호 — 회귀 · 골든셋 (check_grounding.py)
│  ├─ data/                     # 시드 · 골든셋 데이터
│  ├─ tmp/                      # 처리 중 임시파일. git 제외
│  ├─ requirements.txt          # 공용 — 추가는 append 만
│  ├─ Dockerfile                # Railway 배포 전용 (ffmpeg 포함)
│  └─ .env.example
├─ web/                         # 도영 — Next.js 16 (아직 스캐폴딩 전)
│  ├─ README.md                 #   create-next-app 실행법 · 금지사항
│  └─ .env.example              #   NEXT_PUBLIC_API_URL 하나뿐
└─ docs/
   ├─ AskBuddy_개발가이드.md      # 정본
   └─ AskBuddy_환경세팅.md
```

---

## 브랜치 전략

```
main
 ├─ feat/db      (관호)  db/, api/app/reg/, api/app/auth/
 ├─ feat/input   (준혁)  api/app/ingest/, api/prompts/
 └─ feat/output  (도영)  web/
```

**규칙 네 가지**

1. **껍데기를 main에 먼저 올린 뒤 브랜치를 판다.** 빈 폴더에 `.gitkeep`, `main.py`에 라우터 등록 스켈레톤, `.env.example` 두 개까지 main에 있어야 한다. 이게 없으면 셋이 각자 구조를 만들어서 머지 때 세 벌로 갈라진다.
2. **자기 폴더 밖을 수정하지 않는다.** 공용 파일(`api/app/main.py`, `api/app/deps.py`, `docs/`, `CLAUDE.md`, `requirements.txt`)을 고쳐야 하면 슬랙에 먼저 올린다.
3. **하루 한 번 이상 main을 자기 브랜치로 rebase한다.** 마지막 날 한 번에 머지하면 반드시 터진다.
4. **머지 순서는 `feat/db` → `feat/input` → `feat/output`.** 스키마가 바뀌면 나머지 둘이 영향을 받으므로 DB가 먼저다.

**충돌이 잦을 파일과 대응**

| 파일 | 왜 | 대응 |
|---|---|---|
| `api/app/main.py` | 셋 다 라우터를 등록 | 스켈레톤에 세 줄을 미리 넣어두고 각자 안 건드림 |
| `api/requirements.txt` | 준혁·관호가 각각 추가 | 추가 시 슬랙 공지, 한 줄씩만 append |
| `db/001_init_schema.sql` | 스키마 변경 | 관호 단독 소유. 다른 사람은 PR로 요청만 |

---

## 기동

### 1. DB

```bash
supabase start
psql "$SUPABASE_DB_URL" -f db/001_init_schema.sql
psql "$SUPABASE_DB_URL" -f db/002_seed_demo.sql
```

### 2. API

```bash
cd api
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # 키 채우기
uvicorn app.main:app --reload --port 8000
```

→ http://localhost:8000/docs

### 3. WEB

```bash
cd web
pnpm install
cp .env.example .env.local
pnpm dev
```

→ http://localhost:3000

---

## 동작 확인

```bash
# hit
curl -X POST localhost:8000/reg/retrieve -H 'Content-Type: application/json' \
  -d '{"store_id":"demo-cafe","question":"우유 어디 보관해요?","top_k":5}'

# miss
curl -X POST localhost:8000/reg/retrieve -H 'Content-Type: application/json' \
  -d '{"store_id":"demo-cafe","question":"환불은 어떻게 해요?","top_k":5}'
```

`hit`이면 `candidates` 배열, `miss`면 `reason`이 온다. **miss일 때 LLM을 호출하면 계약 위반이다.**

---

## 현재 마일스톤

**M1 — 목 데이터로 경계 뚫기.** Gemini는 아직 붙이지 않는다.
하드코딩 카드 3개 → 프론트가 로드맵·채팅 렌더링까지.

| 파트 | M1 완료 조건 |
|---|---|
| 관호 | `001`·`002` 적용, `/reg/retrieve`가 `demo-cafe`로 hit |
| 준혁 | `/ingest/process`가 하드코딩 카드 3개 INSERT (LLM 미호출) |
| 도영 | 초대코드 `CAFE-DEMO` 진입 → 로드맵 렌더 → 채팅 hit/miss 표시 |
