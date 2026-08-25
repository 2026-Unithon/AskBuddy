# CLAUDE.md

> 이 파일은 Claude Code가 세션 시작 시 자동으로 읽는다.
> **작업 전 반드시 `docs/AskBuddy_개발가이드.md`를 읽을 것.** 이 파일은 요약이고, 그쪽이 정본이다.

---

## 프로젝트

AskBuddy — 카페 등 소규모 매장의 업무 인수인계를 AI가 대신하는 서비스.
점주가 음성·영상·카톡·문서를 올리면 지식카드로 정리되고, 신입은 로드맵과 채팅으로 배운다.
**승인된 매장 지식만 근거로 답하고, 근거가 없으면 추정하지 않고 점주에게 넘긴다.**

---

## 반드시 먼저 읽을 문서

| 파일 | 내용 |
|---|---|
| `docs/AskBuddy_개발가이드.md` | 아키텍처·계약·결정사항·개발 순서. **정본** |
| `docs/AskBuddy_환경세팅.md` | 파트별 환경 구성, 실행 방법 |
| `docs/ingest-contract.md` | `/ingest/*` 상세 계약. 업로드 3단계·에러 코드·프론트 예시 |
| `db/001_init_schema.sql` | 스키마 원천(24 테이블). 컬럼명·타입은 이 파일이 기준 |
| `db/002_seed_demo.sql` | 데모 매장 시드. `demo-cafe` |

---

## 스택 (변경 금지)

| 항목 | 값 |
|---|---|
| 백엔드 | FastAPI, Python 3.12 |
| 프론트 | Next.js 16 (App Router, TypeScript) |
| DB | PostgreSQL 15 + pgvector (Supabase) |
| 임베딩 | OpenAI `text-embedding-3-small` (1536차원) — **고정** |
| STT | OpenAI `whisper-1` |
| 멀티모달 추출 | Gemini Flash |
| 파일 저장 | Supabase Storage 버킷 `sources` (비공개) |
| 로컬 포트 | api `8000`, web `3000`, DB `54322`, Studio `54323` |

---

## 폴더 소유권 (브랜치 충돌 방지)

각 브랜치는 **자기 폴더 밖을 수정하지 않는다.**

| 폴더 | 담당 | 브랜치 |
|---|---|---|
| `db/` | 관호 | `feat/db` |
| `api/app/reg/`, `api/app/auth/` | 관호 | `feat/db` |
| `api/app/ingest/`, `api/prompts/`, `api/scripts/` | 준혁 | `feat/input` |
| `web/` | 도영 | `feat/output` |
| `docs/`, `CLAUDE.md`, `api/app/main.py`, `api/app/deps.py`, `api/app/config.py`, `api/requirements.txt`, `supabase/` | **공용 — 수정 전 팀 합의** | `main` 직접 |

공용 파일을 고쳐야 하면 먼저 사람에게 물어본다. 임의로 수정하지 않는다.

---

## 아키텍처 불변식 (위반 금지)

1. **브라우저는 DB를 직접 치지 않는다.** 모든 데이터 접근은 FastAPI 경유. `web/`에 Supabase 클라이언트를 설치하지 않는다.
2. **LLM 호출은 FastAPI 안에서만.** `web/`에 `OPENAI_API_KEY`·`GEMINI_API_KEY`를 두지 않는다.
3. **지식 진입점은 `POST /reg/retrieve` 하나.** 채팅·검색 어디서 들어오든 이걸 통과한다.
4. **RLS를 쓰지 않는다.** 매장 격리는 API 코드가 전부 책임진다.
   - 모든 DB 함수는 `store_id`를 **필수 인자**로 받는다. 기본값·`Optional` 금지
   - `WHERE store_id = ?` 없는 조회 쿼리를 작성하지 않는다
   - `store_id`는 요청 본문이 아니라 **JWT에서 꺼낸 값**을 쓴다
5. **`kind: "miss"`면 LLM을 호출하지 않는다.** "사장님께 확인 중" 배지만 띄운다.
6. **`ANSWERED` 메시지는 `message_citations`가 1건 이상이어야 한다.** 0건이면 답변을 폐기한다.
7. **브라우저는 Supabase Storage 에도 키로 접근하지 않는다.** `POST /ingest/upload-url` 이 발급한 서명 URL 로만 올린다. 파일 바이너리는 API 를 거치지 않는다.
8. **모델명·차원·임계값은 `api/app/config.py` 가 단일 출처다.** 코드에 리터럴로 쓰지 않는다.

---

## 확정된 결정 (되돌리지 말 것)

| # | 결정 |
|---|---|
| D1 | RLS 미도입. 격리는 API 코드 단독 |
| D2 | LLM 호출은 FastAPI 단독. Next는 LLM 키 없음 |
| D3 | 신뢰도 임계 0.6 (DB 저장은 60.00) |
| D4 | 임베딩 OpenAI 1536 고정. 교체 시 임계값 전면 재측정 |
| D5 | `is_sensitive`·`dek_encrypted`는 예약 필드. 코드에서 읽지도 쓰지도 않는다 |
| D6 | 알림은 폴링(2초). Realtime 미사용 |
| D7 | STT 는 OpenAI `whisper-1` |
| D8 | Storage 버킷 `sources`(비공개). 경로 `{store_id}/{voice\|video\|kakao\|scan}/{uuid}.{ext}`. 업로드는 서명 URL |
| D9 | `content_hash` 는 프론트가 SHA-256 계산. 누락 시 서버가 backfill |
| D10 | `INGEST_MODE` 기본값 `mock`. M1 통과 전에는 Gemini 를 붙이지 않는다 |

이 결정들을 "개선"하려 들지 말 것. 각각 이유가 있고 개발가이드 12장에 근거가 적혀 있다.

---

## 하지 말 것

- 별도 벡터 DB 도입 (pgvector로 충분)
- YOLO·SAM 등 CV 파이프라인 추가
- Supabase Realtime 구독
- `is_sensitive` 관련 로직 구현
- 게임화 요소 추가
- 요청하지 않은 기능 확장. 범위를 벗어나면 먼저 물어본다
- `pip freeze > requirements.txt` (공용 파일을 통째로 덮어쓴다. 한 줄씩 append)
- 인증을 우회하는 엔드포인트 추가. 로컬 토큰은 `api/scripts/dev_token.py` 로 만든다
- `web/` 에 Supabase 클라이언트·LLM 키·DB 자격증명 배치

---

## 코딩 규칙

- 상태 문자열은 대문자 상수: `UPLOADED` `PROCESSING` `DONE` `FAILED` `WAITING` `ANSWERED` `LOCKED` `IN_PROGRESS`
- 시간은 `TIMESTAMPTZ`. KST 변환은 프론트에서만
- 프롬프트는 `api/prompts/` 파일로 분리. 코드 하드코딩 금지
- LLM 호출마다 소요 시간·토큰 로깅
- 실패하면 다음 단계로 넘어가지 말고 명확히 멈춘다
- 주석은 한국어
- 커밋 접두사: `[input]` `[db]` `[output]` `[docs]`

---

## 실행

```bash
# DB
supabase start
psql "$SUPABASE_DB_URL" -f db/001_init_schema.sql
psql "$SUPABASE_DB_URL" -f db/002_seed_demo.sql

# API
cd api && source .venv/bin/activate && uvicorn app.main:app --reload --port 8000

# WEB
cd web && pnpm dev
```

동작 확인:

```bash
curl -X POST localhost:8000/reg/retrieve \
  -H 'Content-Type: application/json' \
  -d '{"store_id":"demo-cafe","question":"우유 어디 보관해요?","top_k":5}'
# → kind: "hit"
```

---

## 현재 마일스톤

**M1 — 목 데이터로 경계 뚫기.** Gemini를 아직 붙이지 않는다.
하드코딩 카드 3개가 DB에 들어가고, 프론트가 그걸 읽어 로드맵·채팅을 띄우는 것까지가 목표.

이 단계에서 실제 추출·전사·OCR을 구현하지 말 것. 통합 실패는 항상 여기서 난다.
