# 팀 작업 규칙

3인이 5일 동안 한 리포를 만지면서 머지 충돌을 구조적으로 막기 위해 정한 규칙이다.
제품 설명은 [README](../README.md), 아키텍처 근거는 [개발가이드](./AskBuddy_개발가이드.md)에 있다.

---

## 폴더 소유권

각 브랜치는 **자기 폴더 밖을 수정하지 않는다.**

| 폴더 | 담당 | 브랜치 |
|---|---|---|
| `db/` | 관호 | `feat/db` |
| `api/app/reg/`, `api/app/auth/`, `api/app/learn/` | 관호 | `feat/db` |
| `api/app/ingest/`, `api/prompts/`, `api/scripts/` | 준혁 | `feat/input` |
| `web/`, `UI/` | 도영 | `feat/output` |
| `docs/`, `CLAUDE.md`, `api/app/main.py`, `api/app/deps.py`, `api/app/config.py`, `api/requirements.txt`, `supabase/` | **공용 — 수정 전 합의** | `main` 직접 |

---

## 브랜치 전략

```
main
 ├─ feat/db      (관호)  db/, api/app/reg/, api/app/auth/, api/app/learn/
 ├─ feat/input   (준혁)  api/app/ingest/, api/prompts/
 └─ feat/output  (도영)  web/
```

**규칙 네 가지**

1. **껍데기를 main에 먼저 올린 뒤 브랜치를 판다.** 빈 폴더에 `.gitkeep`, `main.py`에 라우터 등록 스켈레톤, `.env.example`까지 main에 있어야 한다. 이게 없으면 셋이 각자 구조를 만들어서 머지 때 세 벌로 갈라진다.
2. **자기 폴더 밖을 수정하지 않는다.** 공용 파일을 고쳐야 하면 먼저 팀에 올린다.
3. **하루 한 번 이상 main을 자기 브랜치로 rebase한다.** 마지막 날 한 번에 머지하면 반드시 터진다.
4. **머지 순서는 `feat/db` → `feat/input` → `feat/output`.** 스키마가 바뀌면 나머지 둘이 영향을 받으므로 DB가 먼저다.

**충돌이 잦을 파일과 대응**

| 파일 | 왜 | 대응 |
|---|---|---|
| `api/app/main.py` | 셋 다 라우터를 등록 | 스켈레톤에 라우터 등록 줄을 미리 넣어두고 각자 안 건드림 |
| `api/requirements.txt` | 준혁·관호가 각각 추가 | 추가 시 공지, 한 줄씩만 append (`pip freeze` 금지) |
| `db/001_init_schema.sql` | 스키마 변경 | 관호 단독 소유. 다른 사람은 PR로 요청만 |

---

## 커밋 규칙

접두사로 파트를 구분한다: `[db]` `[input]` `[output]` `[docs]`

---

## 폴더 구조

```
AskBuddy/
├─ CLAUDE.md                    # 공용 — AI 코딩 에이전트 세션 컨텍스트
├─ README.md                    # 공용
├─ db/                          # 관호
│  ├─ 001_init_schema.sql       #   24 테이블 + pgvector. 스키마 원천
│  └─ 002_seed_demo.sql         #   demo-cafe 시드
├─ api/                         # FastAPI (Python 3.12)
│  ├─ app/
│  │  ├─ main.py                # 공용 — 라우터 등록만
│  │  ├─ deps.py                # 공용 — DB 풀, JWT, CurrentStoreId
│  │  ├─ config.py              # 공용 — 환경변수. 모델명·차원·임계값 단일 출처
│  │  ├─ auth/router.py         # 관호 — 가입 · 로그인 · 초대코드 합류
│  │  ├─ reg/                   # 관호 — 등록 · 검색 게이트 (/reg/retrieve)
│  │  ├─ learn/router.py        # 관호 — 로드맵 · 채팅 · 미답변 순환
│  │  └─ ingest/                # 준혁
│  │     ├─ router.py           #   /ingest/process · /ingest/status
│  │     ├─ preprocess/         #   ffmpeg · pypdf · 카톡 파서
│  │     ├─ extract/            #   Gemini 호출
│  │     └─ embed/              #   임베딩 적재
│  ├─ prompts/                  # 준혁 — 프롬프트 파일. 코드 하드코딩 금지
│  ├─ scripts/                  # dev_token · init_storage · ingest_smoke · 시드
│  └─ Dockerfile                # Railway 배포 전용 (ffmpeg 포함)
├─ web/                         # 도영 — Next.js 16 App Router
└─ docs/
```

---

## 기동 상세

### DB

```bash
supabase init         # 최초 1회
supabase start        # 첫 실행 5~10분

# psql 이 있으면
psql "$SUPABASE_DB_URL" -f db/001_init_schema.sql
psql "$SUPABASE_DB_URL" -f db/002_seed_demo.sql

# 없으면 컨테이너 안의 psql 을 쓴다 (mac/linux)
docker exec -i supabase_db_AskBuddy psql -v ON_ERROR_STOP=1 -U postgres -d postgres < db/001_init_schema.sql
docker exec -i supabase_db_AskBuddy psql -v ON_ERROR_STOP=1 -U postgres -d postgres < db/002_seed_demo.sql

# Windows PowerShell
#   Get-Content db/001_init_schema.sql -Raw -Encoding UTF8 | docker exec -i supabase_db_AskBuddy psql -U postgres -d postgres -v ON_ERROR_STOP=1
#   Get-Content db/002_seed_demo.sql   -Raw -Encoding UTF8 | docker exec -i supabase_db_AskBuddy psql -U postgres -d postgres -v ON_ERROR_STOP=1
```

시드 카드 임베딩 (검색 hit 에 필요):

```bash
cd api
# .env 에 OPENAI_API_KEY 채운 뒤
python scripts/seed_embeddings.py
```

### API

```bash
cd api
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env             # 키 채우기. 인라인 주석 금지
python scripts/init_storage.py   # 버킷 sources 생성. 최초 1회
uvicorn app.main:app --reload --port 8000
```

M1 은 LLM 키 없이 전 구간이 돈다 (`INGEST_MODE=mock`).

```bash
python scripts/ingest_smoke.py   # 업로드 → 처리 → 폴링 → 카드 3건
```

### WEB

```bash
cd web
pnpm install
cp .env.example .env.local
pnpm dev
```
