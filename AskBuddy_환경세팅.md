# AskBuddy 개발 환경 세팅

> 최종 수정: 2026-08-25 · **v0.3**
> 대상: 준혁(입력) · 관호(DB) · 도영(출력)
> v0.2: 기존 리포(`hackathon-test`) 구조 반영 · 임베딩 OpenAI 확정 · Gemini는 워커 전용
> v0.3: **RLS 제거.** `002_rls.sql` 폐기, 시드는 `002_seed_demo.sql`. 매장 격리는 API 코드 단독

---

## 0. 확정 스택

| 항목 | 값 | 비고 |
|---|---|---|
| 프론트 | Next.js 16 (App Router, TS) | Node 20.9+ 필수, Turbopack 기본 |
| Node | 22 LTS | 팀 전체 통일 |
| 패키지 매니저 | pnpm (corepack) | |
| 백엔드 | FastAPI, Python 3.12 | `/reg/*`·`/auth/*` 기구현 + `/ingest/*` 신규 |
| DB | PostgreSQL 15 + pgvector | 로컬 Supabase CLI(도커), 배포 Supabase |
| 임베딩 | OpenAI `text-embedding-3-small` (1536) | **D4 고정.** 교체 시 임계값 전면 재측정 |
| 멀티모달 추출 | Gemini Flash | 워커 전용 |
| 파일 저장 | Supabase Storage | 프론트 직접 업로드 |
| 배포 | web → Vercel, api → Railway | Root Directory: `web` / `api` |
| 로컬 포트 | web `3000`, api `8000`, DB `54322`, Studio `54323` | |

**불변식 3개**
1. 브라우저는 Supabase를 직접 치지 않는다. 전부 FastAPI 경유
2. LLM 키(`OPENAI_API_KEY`, `GEMINI_API_KEY`)는 **api에만** 둔다
3. DB 자격증명은 api에만 둔다. **RLS를 두지 않으므로 1·3번이 유일한 격리 수단이다**

---

## 1. 도커 범위

**도커로 띄우는 것: DB와 Storage만.** `supabase start`가 Postgres·pgvector·Storage·Studio를 한 번에 올린다.

**도커에 넣지 않는 것: Next.js, FastAPI 로컬 개발 서버.** 각자 네이티브 실행한다. 핫리로드 속도 때문이며, 배포용 `api/Dockerfile`은 Railway 전용으로 유지한다.

Supabase 없이 순수 Postgres만 쓸 경우:

```yaml
# docker-compose.yml — Supabase 미사용 시
services:
  db:
    image: pgvector/pgvector:pg15
    environment:
      POSTGRES_PASSWORD: askbuddy
      POSTGRES_DB: askbuddy
    ports: ["5432:5432"]
    volumes: ["./db/data:/var/lib/postgresql/data"]
```

이 경우 Storage가 없으므로 파일 업로드는 로컬 디스크로 대체해야 한다. **권장하지 않는다.**

---

## 2. 리포 구조 (기존 `hackathon-test` 기준)

```
hackathon-test/
├─ web/                      # 도영 — Next.js 16
│  ├─ app/
│  └─ lib/api.ts             # FastAPI 호출 래퍼 (Supabase 직접 호출 금지)
├─ api/                      # 관호 + 준혁 — FastAPI
│  ├─ app/
│  │  ├─ reg/                # 관호 — 등록·검색 게이트 (기구현)
│  │  ├─ auth/               # 관호 — 인증 (기구현)
│  │  └─ ingest/             # 준혁 — 신규
│  │     ├─ preprocess/      # ffmpeg · pypdf · kakao 파서
│  │     ├─ extract/         # Gemini 호출
│  │     └─ embed/           # OpenAI 임베딩 + 적재
│  ├─ prompts/               # 프롬프트 파일 (코드 하드코딩 금지)
│  ├─ sql/
│  │  ├─ 001_init_schema.sql
│  │  └─ 002_seed_demo.sql
│  ├─ data/                  # 시드·골든셋
│  ├─ scripts/               # check_grounding 등 회귀
│  └─ requirements.txt
└─ docs/
   ├─ AskBuddy_환경세팅.md
   └─ AskBuddy_개발가이드.md
```

기존 `api/sql/identity.sql`·`knowledge.sql`은 `001~003`으로 흡수한다. 두 벌을 남겨두면 스키마가 갈라진다.

---

## 3. 공통 세팅

### 3-1. 필수 설치

| 도구 | 버전 | 확인 |
|---|---|---|
| Git | 2.4x | `git --version` |
| Docker Desktop | 최신 | `docker ps` |
| Node | 22 LTS | `node -v` |
| pnpm | corepack | `pnpm -v` |
| Python | 3.12 | `python3 --version` |
| Supabase CLI | 최신 | `supabase --version` |
| ffmpeg | 6.x | `ffmpeg -version` |

```bash
nvm install 22 && nvm use 22
corepack enable && corepack prepare pnpm@latest --activate

# macOS
brew install supabase/tap/supabase ffmpeg
# Windows
scoop bucket add supabase https://github.com/supabase/scoop-bucket.git && scoop install supabase
winget install Gyan.FFmpeg
```

**Windows는 WSL2 작업을 강력히 권장한다.** ffmpeg PATH, 경로 구분자, CRLF 세 가지가 전부 여기서 터진다.

### 3-2. DB 기동

```bash
git clone https://github.com/kim-kwanho/hackathon-test && cd hackathon-test
supabase start        # 첫 실행 5~10분

# 스키마 적용
psql "$SUPABASE_DB_URL" -f api/sql/001_init_schema.sql
psql "$SUPABASE_DB_URL" -f api/sql/002_seed_demo.sql
```

`supabase start` 출력의 URL·키를 `.env`에 채운다.

### 3-3. 환경변수

**`api/.env`** — 시크릿 값은 리포에 커밋하지 않는다. 이름만 관리한다.

```bash
APP_NAME=askbuddy
ENV=local
ALLOWED_ORIGINS=http://localhost:3000

# LLM — api 에만 존재
OPENAI_API_KEY=              # 임베딩(필수) + 답변 생성
GEMINI_API_KEY=              # 멀티모달 추출 (준혁)
ANTHROPIC_API_KEY=           # 선택. 있으면 채팅 모델 우선

EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_DIM=1536
CONFIDENCE_THRESHOLD=0.6     # D3
FRAME_INTERVAL_SEC=3

# Supabase
SUPABASE_URL=http://127.0.0.1:54321
SUPABASE_SERVICE_KEY=        # 절대 프론트로 넘기지 않음
SUPABASE_DB_URL=postgresql://postgres:postgres@127.0.0.1:54322/postgres
```

**`web/.env.local`**

```bash
NEXT_PUBLIC_API_URL=http://localhost:8000
```

> 프론트 환경변수는 **이것 하나면 된다.** `NEXT_PUBLIC_SUPABASE_*`는 두지 않는다 — 브라우저가 Supabase를 직접 치지 않기 때문이다(불변식 1).
> `.gitignore`: `.env*`, `!.env.example`, `api/tmp/`, `db/data/`

**Gemini 키 함정:** 예전에 셸에서 `export GEMINI_API_KEY=...` 한 적이 있으면 `.env`보다 우선한다. `unset GEMINI_API_KEY` 후 `load_dotenv(override=True)`.

---

## 4. 관호 — DB 파트

### 4-1. 할 일

1. `001`·`002` 적용, 기존 `knowledge.sql` 폐기. `identity.sql`의 인증 컬럼은 `users` 테이블에 병합
2. `/reg/*`·`/auth/*`가 `store_slug`로 `store_id`(BIGINT)를 해석하도록 수정
3. 검색 쿼리를 `match_cards()` RPC로 교체 (approved만 대상)
4. 시드 카드 3건 임베딩 생성 스크립트

### 4-2. 문자열 store_id 호환

기존 API는 `store_id="demo-cafe"`를 받는다. ERD는 BIGINT다. 진입점에서 한 번만 변환한다.

```python
async def resolve_store_id(raw: str | int) -> int:
    if isinstance(raw, int) or str(raw).isdigit():
        return int(raw)
    row = await db.fetchrow(
        "select store_id from stores where store_slug = $1", raw)
    if not row:
        raise HTTPException(404, f"unknown store: {raw}")
    return row["store_id"]
```

API 계약(요청 JSON)은 그대로 두고 내부만 바꾸므로, 도영님 프론트와 골든셋 스크립트는 수정이 필요 없다.

### 4-3. 매장 격리 (D1 — RLS 미도입)

**DB 차원의 방어선이 없다.** 격리는 전적으로 API 코드가 한다.

```python
# 모든 조회 함수는 store_id 를 필수 인자로. 기본값·Optional 금지
async def get_cards(store_id: int, category_id: int | None = None): ...
```

지켜야 할 것 세 가지.

1. `WHERE store_id = ?` 없는 조회 쿼리를 만들지 않는다
2. `store_id`는 요청 본문이 아니라 **JWT에서 꺼낸 값**을 신뢰한다. 클라이언트가 보낸 값을 그대로 쓰면 남의 매장을 조회할 수 있다
3. 통합 전 점검 — 매장 2개를 만들고 A 계정으로 B의 카드가 안 보이는지 확인한다

시연 중엔 드러나지 않다가 심사위원이 두 계정으로 열어보면 그대로 보인다. 이게 RLS를 뺀 대가이므로 코드 리뷰에서 이 항목부터 본다.

### 4-4. TS 타입 생성

```bash
supabase gen types typescript --local > web/types/database.ts
```

프론트가 Supabase를 직접 치지는 않지만, 응답 타입 정의에 재사용할 수 있다. 스키마 변경 시 재생성해 커밋한다.

### 4-5. 검증

```bash
psql "$SUPABASE_DB_URL" -c "select count(*) from roadmap_items"        # 16
psql "$SUPABASE_DB_URL" -c "select code from invite_codes"             # CAFE-DEMO
curl -X POST localhost:8000/reg/retrieve \
  -d '{"store_id":"demo-cafe","question":"우유 어디 보관해요?","top_k":5}'   # kind=hit
python api/scripts/check_grounding.py                                   # 통과
```

---

## 5. 준혁 — 입력 파트

### 5-1. 세팅

```bash
cd api
python3 -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -U pip
pip install -r requirements.txt
# ingest 신규 의존성
pip install google-genai pypdf pillow tenacity
pip freeze > requirements.txt
```

| 패키지 | 용도 |
|---|---|
| `google-genai` | Gemini 멀티모달 (구 `google-generativeai` 아님) |
| `pypdf` | PDF 페이지 분할 |
| `pillow` | 프레임 이미지 처리 |
| `tenacity` | LLM 호출 재시도 |
| (기존) `openai` | 임베딩 — **관호님 코드 재사용, 새로 만들지 말 것** |

ffmpeg는 시스템 설치다. 시작 시 `shutil.which("ffmpeg")`로 확인하고 없으면 명확히 죽인다.

### 5-2. 실행

```bash
uvicorn app.main:app --reload --port 8000
curl localhost:8000/health
open http://localhost:8000/docs
```

### 5-3. `/ingest/*` 규칙

- 모든 DB 함수는 `store_id` 필수 인자
- 원본 파일은 프론트가 Storage에 올린다. 워커는 경로만 받아 서명 URL로 내려받는다
- 상태 보고는 `sources.status`로만: `UPLOADED → PROCESSING → DONE | FAILED`. 실패 시 `error_message` 필수
- 같은 파일 재업로드는 `content_hash`로 무시 (멱등)
- 추출 카드는 `is_verified=false`로 저장. 점주 승인 후에만 임베딩·검색 대상
- 임베딩은 **관호님 기존 OpenAI 코드를 호출**한다. 새 임베딩 함수를 만들면 차원·모델명이 갈라진다
- 임시 파일은 `api/tmp/{source_id}/`, 처리 후 삭제

### 5-4. 프레임 추출

```bash
ffmpeg -i input.mp4 -vf "fps=1/3,scale=640:-1" tmp/frame_%04d.jpg
```

3초 간격, 가로 640. 인덱스는 0-base로 맞춰 `timestamp_sec = index * 3`이 성립하게 한다.

### 5-5. 검증

- [ ] `ffmpeg -version` 동작
- [ ] 샘플 mp4 → 프레임 N장 → `source_frames` N행
- [ ] Gemini 호출 1회 성공(JSON 파싱까지)
- [ ] 카드 INSERT 후 `select * from knowledge_cards where is_verified=false` 확인

---

## 6. 도영 — 출력 파트

### 6-1. 세팅

```bash
cd web        # 없으면 아래로 생성
pnpm create next-app@latest web --ts --app --tailwind --eslint --src-dir=false
pnpm dev      # http://localhost:3000
```

Supabase 클라이언트 라이브러리는 설치하지 않는다(불변식 1). API 호출 래퍼만 만든다.

```ts
// lib/api.ts
const BASE = process.env.NEXT_PUBLIC_API_URL!

export async function retrieve(storeId: string, question: string) {
  const res = await fetch(`${BASE}/reg/retrieve`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ store_id: storeId, question, top_k: 5 }),
  })
  if (!res.ok) throw new Error(`retrieve failed: ${res.status}`)
  return res.json()   // { kind: 'hit' | 'miss', ... }
}
```

### 6-2. Next 16에서 달라진 것

| 항목 | 변경 |
|---|---|
| `middleware.ts` | `proxy.ts`로 이름 변경 |
| `cookies()`·`headers()`·`params` | 전부 async, `await` 필수 |
| 캐싱 | 암묵적 캐싱 제거. `"use cache"`로 명시 |
| `revalidateTag()` | 두 번째 인자로 cacheLife 프로필 필요 |
| 번들러 | Turbopack 기본 (webpack 설정 불필요) |

### 6-3. ver2 이식 시 주의

- ver2는 Vite + React이고 데이터가 `App.tsx`에 하드코딩돼 있다. **컴포넌트는 재사용하되 상태 관리는 새로 짠다.**
- Enum 값이 소문자다. DB는 대문자다(개발가이드 5장 매핑표 참조)
- `pending` 노드 상태는 DB에 없다. `LOCKED`로 흡수한다
- 진행도는 `DONE 항목 / 전체 항목 × 100`

### 6-4. 폴링 (D6)

```ts
// 업로드 후 2초 간격, FAILED 반드시 화면 표시
const id = setInterval(async () => {
  const s = await getStatus(sourceId)
  if (s.status === 'DONE')   { clearInterval(id); goPreview() }
  if (s.status === 'FAILED') { clearInterval(id); showError(s.error_message) }
}, 2000)
```

`FAILED` 분기를 빼먹으면 데모에서 스피너가 영원히 돈다.

### 6-5. 절대 하지 말 것

- Supabase를 직접 호출하지 않는다
- LLM API 키를 두지 않는다
- `kind: "miss"`일 때 LLM 호출로 문장을 만들지 않는다. "사장님께 확인 중" 배지만 띄운다

---

## 7. 부팅 검증 체크리스트

**공통**
- [ ] `supabase status` 전 서비스 running
- [ ] Studio(`:54323`)에서 21개 테이블 확인
- [ ] `select store_id, store_slug from stores;` → 1행, `demo-cafe`

**관호**
- [ ] `001`·`002` 무오류 적용
- [ ] `/reg/retrieve` → `demo-cafe`로 hit
- [ ] `check_grounding.py` 통과
- [ ] `select embedding from card_embeddings limit 1;` 실행 가능

**준혁**
- [ ] `ffmpeg -version`
- [ ] `/health` 200, `/docs` 접근
- [ ] Gemini 호출 1회 성공
- [ ] 샘플 처리 후 `sources.status='DONE'`

**도영**
- [ ] `node -v` 22.x, `pnpm dev` 기동
- [ ] `CAFE-DEMO` 입력 → 매장 진입
- [ ] 시드 카드 3건이 로드맵에 렌더링
- [ ] hit 질문 / miss 질문 각 1개 화면 확인

---

## 8. 배포

| 파트 | 타깃 | Root Directory |
|---|---|---|
| `web/` | Vercel | `web` |
| `api/` | Railway (Dockerfile) | `api` |

순서: Railway URL 확보 → Vercel `NEXT_PUBLIC_API_URL`에 입력 → Railway `ALLOWED_ORIGINS`에 Vercel 도메인 추가.

- CORS `*`는 해커톤 임시로만. 시연 후 되돌린다
- 무료 티어는 무요청 시 슬립한다. **시연 5분 전 헬스체크 호출** 또는 외부 크론 5분 핑
- 배포 URL이 robots.txt로 막혀 있으면 심사위원이 못 연다. 먼저 푼다

---

## 9. 자주 터지는 문제

| 증상 | 원인 | 해결 |
|---|---|---|
| `supabase start` 실패 | 도커 미기동·포트 충돌 | Docker Desktop 실행, `supabase stop --no-backup` 후 재시도 |
| `ffmpeg: command not found` | PATH 미등록(Windows) | 재설치 후 터미널 재시작. WSL2 권장 |
| Gemini 키가 `.env`와 다름 | 셸 export 우선 | `unset` + `load_dotenv(override=True)` |
| Next에서 `params` undefined | Next 16은 async | `const { id } = await params` |
| 카톡 txt 한글 깨짐 | cp949 | utf-8 → cp949 → utf-16 → euc-kr 순 시도 |
| 검색이 계속 miss | 카드가 `is_verified=false` 또는 임베딩 미생성 | 승인 여부와 `card_embeddings` 행 수 먼저 확인 |
| 워커 데이터가 프론트에 안 보임 | `store_id` 불일치 | psql 로 직접 조회해 데이터 존재부터 확인 |
| CORS 에러 | `ALLOWED_ORIGINS` 누락 | api `.env` 확인 후 재기동 |
| 임베딩 차원 오류 | 모델 교체 | D4 위반. 1536 고정. 교체하려면 임계값 전면 재측정 |

---

## 10. 세팅 완료 후 첫 작업

**목 데이터로 경계를 먼저 뚫는다.** 워커가 하드코딩 카드 3개를 넣고 → 프론트가 그걸 읽어 로드맵·채팅을 띄우는 것까지 성공한 뒤 실제 추출을 붙인다. 반대로 하면 추출 품질을 튜닝하다가 통합 시간을 전부 잃는다.
