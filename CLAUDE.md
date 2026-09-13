# CLAUDE.md

> 이 파일은 Claude Code가 세션 시작 시 자동으로 읽는다.
> **작업 전 반드시 `docs/ASKBUDDY_MVP_CURRENT.md`를 읽을 것.** 제품·데이터·API·운영 계약의 단일 정본이다.
> 남은 작업과 실행 순서는 `docs/DEV_TODO_CURRENT.md`를 따른다.

---

## 프로젝트

AskBuddy — 카페 등 소규모 매장의 업무 인수인계를 AI가 대신하는 서비스.
점주가 음성·영상·카톡·문서를 올리면 지식카드로 정리되고, 신입은 로드맵과 채팅으로 배운다.

**승인된 매장 지식만 근거로 답하고, 근거가 없으면 추정하지 않고 점주에게 넘긴다.**

**등록이 먼저다.** 점주·퇴사자가 자료를 올려 초기 지식을 채운다.
올린 자료는 작업(job) 단위로 접수되고, 결과가 나오면 검수 화면으로 알림이 간다. (게이지 80% 게이트는 계약 v1에서 폐기)

등록으로 끝이 아니라, 쓰면서 계속 자란다.

```
신입이 묻는다 → 지식에 없으면 AI가 "모른다"고 답한다 → 점주 폰에 알림
→ 점주가 30초 답한다 → 그 답이 매장의 영구 지식
→ 다음 알바는 같은 질문을 하지 않는다
```

"모른다고 말할 줄 아는 AI"는 한계가 아니라 설계 철학이다. 그 '넘김'이 지식이 자라는 경로다.

> 구현 우선순위가 충돌하면 **이 순환을 닫는 쪽**을 택한다.
> 서비스명은 **AskBuddy** 하나다. Relay·유니쉐프를 쓰지 않는다.

---

## 반드시 먼저 읽을 문서

| 파일 | 내용 |
|---|---|
| `docs/ASKBUDDY_MVP_CURRENT.md` | 제품·데이터·API·화면·배포 계약. **현재 단일 정본** |
| `docs/DEV_TODO_CURRENT.md` | 남은 12.5~15단계의 실행 순서와 완료 기준 |
| `docs/이관경계_실험설계.md` | 무엇을 모델에 넘기고 무엇을 우리가 쥐는가. 플래그·실험 순서·게이트 지표 |
| `UI/` | 화면 목업 24장. 프론트 작업 전 반드시 볼 것 |
| `db/001_init_schema.sql` | 초기 스키마(24 테이블). `users` 에 `email`·`password_hash` 포함 |
| `supabase/migrations/` | 적용 가능한 스키마 변경 이력. 신규 컬럼·테이블의 실행 기준 |
| `db/002_seed_demo.sql` | 데모 매장 시드. `demo-cafe`, 초대코드 `CAFE-DEMO` |

---

## 스택 (변경 금지)

| 항목 | 값 |
|---|---|
| 백엔드 | FastAPI, Python 3.12 |
| 프론트 | Next.js 16 (App Router, TypeScript) |
| DB | PostgreSQL 15 + pgvector (Supabase) |
| 임베딩 | OpenAI `text-embedding-3-small` (1536차원) — **고정** |
| STT | OpenAI `whisper-1` |
| 멀티모달 추출 | Gemini `gemini-3.6-flash` |
| 파일 저장 | Supabase Storage 버킷 `sources` (비공개) |
| 로컬 포트 | api `8000`, web `3000`, DB `54322`, Studio `54323` |

---

## 디자인 시스템 (그대로 적용)

| 토큰 | 값 | 용도 |
|---|---|---|
| Primary — Buddy Green | `#5DBB8A` | 완료 상태, 주요 CTA, 진행 상태 |
| Dark — Deep Green | `#245B48` | 헤더, 강조 텍스트, 아이콘 |
| Background — Warm Green White | `#F4FAF6` | 전체 배경, 카드 배경 |
| Point — Buddy Yellow | `#FFD166` | 보상, 뱃지, 진행 중인 미션 |
| Text — Dark Charcoal | `#26332E` | 본문 |
| Disabled — Soft Gray | `#DDE4E0` | 미완료·잠긴 단계 |
| Error — Soft Red | `#E57373` | 오류 |

- 톤: Friendly · Growth · Guidance · Gamification. **딱딱한 매뉴얼 느낌 금지**
- Buddy 캐릭터가 화면 곳곳에 말풍선으로 등장한다. 마스코트는 Green 메인 + Yellow 포인트 + Deep Green 아웃라인
- 모바일 웹 우선. 사장님 대시보드만 데스크탑 반응형

---

## 제품 규칙 (기획서 v5)

- **게임화는 필수다.** 듀오링고형 스킬트리, 스트릭·젬·하트, 뱃지, 미션 완료 연출.
  신입이 "눈치 보며 다시 묻는 일"을 없애는 장치이지 장식이 아니다
- **'신뢰도 %'를 사용자에게 노출하지 않는다.** 산출 근거를 설명할 수 없는 지표는 폐기됐다.
  대신 **'매장 지식 완성도'** = 등록된 카테고리 중 필수 항목이 채워진 비율.
  `knowledge_cards.confidence` 는 **점주 검수 정렬용 내부 값**이다. 화면에 %로 찍지 않는다
- **영상도 처음부터 올릴 수 있다.** 기획서 v5 의 "영상 단독 등록 불가"는 철회했다 —
  M4 에서 영상만으로 화면을 읽어 카드를 만드는 것이 실측으로 확인됐다 (오디오 없는 영상에서 5건)
- **업로드 전에 "찍어야 할 위치 체크리스트"를 먼저 보여준다.** 자료 커버리지가 곧 정확도다
- **신입에게 공개되기 전 점주가 사진을 검토·제외·블러 처리할 수 있어야 한다.**
  현장 인터뷰에서 나온 "지저분해서 보내기 싫다"는 저항에 대한 대응. 기술 문제가 아니라 감정 문제다
- ~~업로드 진전도 게이지 80% 게이트~~ — **계약 v1 에서 폐기.** 커버리지를 퍼센트로 약속하지 않는다.
  대신 작업(job) 접수 → 추출 완료 알림 → 검수 화면 딥링크로 흐른다

---

## 폴더 소유권 (브랜치 충돌 방지)

각 브랜치는 **자기 폴더 밖을 수정하지 않는다.**

| 폴더 | 담당 | 브랜치 |
|---|---|---|
| `db/` | 관호 | `feat/db` |
| `api/app/reg/`, `api/app/auth/` | 관호 | `feat/db` |
| `api/app/ingest/`, `api/prompts/`, `api/scripts/` | 준혁 | `feat/input` |
| `web/`, `UI/` | 도영 | `feat/output` |
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
5. **`kind: "miss"`면 답변 LLM을 호출하지 않는다.** "사장님께 확인 중" 배지만 띄운다. 질문 저장에 실패하면 `WAITING` 으로 표시하지 않는다.
6. **`ANSWERED` 메시지는 `message_citations`가 1건 이상이어야 한다.** 0건이면 답변을 폐기한다.
    생성 답변은 `validate_grounded_payload` 3종 검증을 통과해야만 저장한다. 검증 실패는 API 실패가 아니라 `CARD_ORIGINAL`·`FALLBACK` 으로 저장·반환한다.
11. **검색과 직원 학습은 `published_version_id` 가 있는 승인 카드만 본다.** 초안·제외 카드·과거 버전은 섞이지 않는다.
12. **자동 재분류는 `assignment_type='MANUAL'` 카드를 덮지 않는다.** 사람이 옮긴 것이 우선이다.
7. **브라우저는 Supabase Storage 에도 키로 접근하지 않는다.** `POST /ingest/upload-url` 이 발급한 서명 URL 로만 올린다. 파일 바이너리는 API 를 거치지 않는다.
8. **모델명·차원·임계값은 `api/app/config.py` 가 단일 출처다.** 코드에 리터럴로 쓰지 않는다.
9. **임베딩 생성은 `app.reg.embeddings.embed_texts` 하나만 쓴다.** 새 임베딩 함수를 만들지 않는다 (D4). 동기 함수이므로 async 문맥에서는 `asyncio.to_thread` 로 감싼다.
10. **`.env` 에 인라인 주석을 쓰지 않는다.** dotenv 가 값에 주석을 붙여 읽을 수 있다.

---

## 확정된 결정 (되돌리지 말 것)

| # | 결정 |
|---|---|
| D1 | RLS 미도입. 격리는 API 코드 단독 |
| D2 | LLM 호출은 FastAPI 단독. Next는 LLM 키 없음 |
| D3 | 카드 검수 기준 `CONFIDENCE_THRESHOLD` 0.6 (DB 저장은 60.00). 미만이면 검수 화면 상단 우선 노출 |
| D4 | 임베딩 OpenAI 1536 고정. 교체 시 임계값 전면 재측정 |
| D5 | `is_sensitive`·`dek_encrypted`는 예약 필드. 코드에서 읽지도 쓰지도 않는다 |
| D6 | Supabase Realtime 미사용. 앱 내 상태 갱신은 폴링, 매장 밖 전달은 Web Push |
| D7 | STT 는 OpenAI `whisper-1` |
| D8 | Storage 버킷 `sources`(비공개). 경로 `{store_id}/{voice\|video\|kakao\|scan}/{uuid}.{ext}`. 업로드는 서명 URL |
| D9 | `content_hash` 는 프론트가 SHA-256 계산. 누락 시 서버가 backfill |
| D10 | `INGEST_MODE` 기본값 `mock`. M1 통과 전에는 Gemini 를 붙이지 않는다 |
| D11 | 현재 검색 게이트는 `RETRIEVAL_THRESHOLD` **0.35** 하한 + `RETRIEVAL_STRONG_SCORE` **0.62** + 낱말 앵커 검사다. 14단계에서 앵커를 기능 플래그 기반 소프트 감점으로 바꾸고 평가 하네스로 임계값을 재결정한다. D3와는 별개 값이다. |
| D12 | 답변 생성은 하되 **서버가 검증한다.** 승인 카드 상위 3장만 입력, `response_schema` 강제, temperature 0.0. 인용 화이트리스트·숫자 부분집합·낱말 부분집합 3종 중 하나라도 실패하면 생성문을 버리고 카드 원문(`CARD_ORIGINAL`)으로 폴백. `ANSWER_MODE=extractive` 로 생성을 끌 수 있다 |
| D13 | 카드 본문은 `card_versions` 가 갖는다. `draft_version_id`(초안) 와 `published_version_id`(공개) 를 분리하고, 승인 = 임베딩 생성 + 공개 포인터 이동을 한 성공 단위로 처리한다 |
| D14 | 로드맵은 고정 게임판이 아니라 카테고리 + 승인 카드로 동적 구성한다. 승인 카드가 없으면 `stages=[]`, 샘플 카드를 넣지 않는다 |
| D15 | 알림은 앱 내부 알림(`notification_events`)이 정본, Web Push 는 추가 전달. `REQUESTED` 는 전달 요청 성공일 뿐 수신·읽음이 아니다 |

확정 결정의 변경은 `docs/ASKBUDDY_MVP_CURRENT.md`와 `docs/DEV_TODO_CURRENT.md`에 먼저 반영하고, 평가 결과와 migration 호환성을 함께 검토한다.

---

## 하지 말 것

- 별도 벡터 DB 도입 (pgvector로 충분)
- YOLO·SAM 등 CV 파이프라인 추가
- Supabase Realtime 구독
- `is_sensitive` 관련 로직 구현
- **사용자 화면에 '신뢰도 %' 표기** (기획서에서 폐기한 지표. '매장 지식 완성도'를 쓴다)
- **서비스명 혼용** (AskBuddy 하나. Relay·유니쉐프 금지)
- 요청하지 않은 기능 확장. 범위를 벗어나면 먼저 물어본다
- `pip freeze > requirements.txt` (공용 파일을 통째로 덮어쓴다. 한 줄씩 append)
- 인증을 우회하는 엔드포인트 추가. 로컬 토큰은 `api/scripts/dev_token.py` 로 만든다
- `web/` 에 Supabase 클라이언트·LLM 키·DB 자격증명 배치

---

## 개발 스킬

작업 종류에 따라 아래 스킬을 **작업을 마쳤다고 보고하기 전에** 쓴다.
스킬은 규칙을 다시 적어둔 문서가 아니라, 규칙이 지켜졌는지 확인하는 절차다.

| 스킬 | 언제 | 위치 |
|---|---|---|
| `store-isolation-check` | `api/app/`·`supabase/migrations/`·`db/` 를 건드렸을 때 | 저장소 전용 |
| `web-async-state-check` | `web/` 의 query·mutation·lifecycle 을 건드렸을 때 | 저장소 전용 |
| `ui-state-walkthrough` | 화면을 추가·수정하고 실제 동작을 확인할 때 | 저장소 전용 |
| superpowers 의 TDD·체계적 디버깅 | 기능 구현과 버그 추적 전반 | 플러그인 |

저장소 전용 스킬은 `.claude/skills/<이름>/SKILL.md` 에 있다.

- 매장 격리 정적 검사는 grep 이 아니라
  `python3 .claude/skills/store-isolation-check/check_store_id.py api/app/<폴더>` 로 돈다.
  검토를 마친 예외만 `# store-isolation-ok: <사유>` 로 못 박는다. 사유 없는 면제는 무시된다.
- `web/` 에는 단위 테스트 러너가 없다. "테스트 통과" 라고 쓰지 않는다.
  정적 검사(`pnpm check`)와 브라우저 확인을 구분해서 보고한다. 자동 E2E 는 13.6 범위다.
- 확인하지 않은 항목을 완료로 적지 않는다. 브라우저를 못 띄웠으면 그렇게 쓴다.

---

## 코딩 규칙

- 상태 문자열은 대문자 상수. 현재 계약 기준:
  - 카드 `PENDING` `NEEDS_REVIEW` `APPROVED` `EXCLUDED`
  - 작업 `QUEUED` `EXTRACTING` `CLASSIFYING` `SUCCEEDED` `PARTIAL` `NO_RESULT` `FAILED`
  - 학습 `NOT_STARTED` `DONE` `RECONFIRM_REQUIRED` (`LOCKED`·`IN_PROGRESS` 는 호환 잔재)
  - 질문 `WAITING` `ANSWERED` · 알림 `PENDING` `REQUESTED` `FAILED`
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

**MVP 계약 v1 백엔드 구현 완료 (main @ `d62c08e`).** 들어온 것:

- `a44c69b` `/app/bootstrap` · 카테고리 CRUD·재분류 · `ingest_jobs` 작업 단위
- `a3ffb26` 카드 수명주기(`card_versions`·검수상태·근거·검수이력) · 동적 로드맵
- `ba7201e` 근거 기반 생성 답변 · 점주 답변 학습 루프 · FAQ
- `d62c08e` 앱 내부 알림 · Web Push

남은 것:

1. **`/team/evaluations` 평가 하네스** — `quality_evaluations` 테이블만 있고 라우터가 없다. 정확도 수치를 다시 재려면 이게 먼저다
2. `/ingest/capabilities` 제한값이 전부 `null` — 실자료 측정 후 확정
3. VAPID 실키·운영 HTTPS 주소, production `INGEST_MODE`
4. 계약 21절 검증 10항목을 충분한 질문 세트로 반복 측정
5. 프론트를 신규 API 로 이전 (작업트리에 진행 중)
