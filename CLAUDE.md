# CLAUDE.md

> 이 파일은 Claude Code가 세션 시작 시 자동으로 읽는다.
> **작업 전 반드시 `docs/ASKBUDDY_MVP_CURRENT.md`를 읽을 것.** 제품·데이터·API·운영 계약의 단일 정본이다.
> 남은 작업과 실행 순서는 `docs/DEV_TODO_CURRENT.md`를 따른다.
> 2026-09-14 동기화: 두 담당자 W/R 경계와 새 AI 계약은 MVP 30~31절, 평가 분모·승격은 실험설계가 정본이다. 아래 과거 요약은 현재 코드의 구현 완료나 새 작업의 운영 실행 권한을 대신하지 않는다.

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
| `api/eval/progress/PROGRESS.md` | 품질 추이. 처음 대비 현재 수치. `scripts/track_progress.py` 로 갱신 |
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

## 디자인 기준

현재 토큰·모바일 규격·Figma 미확정 항목은 MVP 24·28·29절을 따른다. 과거 Yellow/게임화 시안이 현재 제품 정본을 덮어쓰지 않는다.

---

## 제품 규칙

현재 MVP의 닫힌 순환·승인·카테고리·동적 로드맵·업로드·알림·상태 UX는 MVP 2~20절을 따른다. 하트·스트릭·강제 게임화·커버리지 퍼센트는 필수 요구가 아니다. 지원 입력과 제한은 서버 capabilities가 정본이며 과거 특정 영상 성공 기록을 일반 추출 성능 보장으로 쓰지 않는다.

---

## 두 파이프라인 소유권

- W: 원본→추출 JSON→원장/revision→카드 조립·렌더·검수·공개, OWNER_ANSWER 지식 반영.
- R: 질문·문맥→검색·충분성→AnswerPlan·답변·명확화·이관, 점주 원문 전달·pending·알림.
- 공통 인계: PublishedKnowledgeSnapshot v1. C0의 승인 합성 fixture로 병렬 개발하고 실제 W 산출물로 종단 검증한다.
- 파일 주 편집자·공통 renderer·공개 서비스·migration 경계는 MVP 30~31절과 TODO를 따른다. 개인 이름을 추정하지 않는다.
- schema/API 변경은 계약과 검증 기준을 함께 갱신하고 공통 파일을 동시에 편집하지 않는다.

---

## 아키텍처 불변식 (위반 금지)

1. **브라우저는 DB를 직접 치지 않는다.** 모든 데이터 접근은 FastAPI 경유. `web/`에 Supabase 클라이언트를 설치하지 않는다.
2. **LLM 호출은 FastAPI 안에서만.** `web/`에 `OPENAI_API_KEY`·`GEMINI_API_KEY`를 두지 않는다.
3. **지식 조회는 공유 검색 서비스로 통일한다.** 제품 API는 JWT 매장·권한을 확인한다. 레거시 `/reg/*` 공개 store ID 계약은 보안 정리 대상이지 신규 호출 규약이 아니다.
4. **RLS를 쓰지 않는다.** 매장 격리는 API 코드가 전부 책임진다.
   - 모든 DB 함수는 `store_id`를 **필수 인자**로 받는다. 기본값·`Optional` 금지
   - `WHERE store_id = ?` 없는 조회 쿼리를 작성하지 않는다
   - `store_id`는 요청 본문이 아니라 **JWT에서 꺼낸 값**을 쓴다
5. **근거 부족 시 답변 생성 모델을 호출하지 않는다.** ESCALATE 저장 성공 뒤만 WAITING을 표시한다. CLARIFY·정책 안내는 pending/알림이 아니며 ERROR는 별도 오류다. v1/v2 상태 전환은 MVP 31절을 따른다.
6. **AI 사실 답변은 승인 카드/버전·불변 블록/사실 인용이 필요하다.** 점주 원문 전달은 OWNER_ANSWER로 구분한다. 기존 숫자·낱말 검사는 의미 정확성을 보장하지 않는다. 목표 경로는 참조 선택·서버 렌더링이며 원문 폴백도 질문 적합성을 검사한다.
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
| D10 | `INGEST_MODE` 코드 기본값은 `mock`. 실측 시 실제 모드·모델·설정을 명시하고 mock 실행을 모델 성능으로 집계하지 않는다 |
| D11 | 현행 검색은 0.35 하한+앵커 검사이며 0.62 strong_score 설정은 실행 경로에서 사용되지 않는다. 목표는 채널별 후보 융합 후 충분성 검사이고 lexical-only 후보에 vector 하한을 공통 적용하지 않는다 |
| D12 | 목표 답변은 승인 snapshot의 block/fact revision 선택→서버 검증·렌더링. 기존 자유 생성+숫자/단어 포함 검사는 비교 기준선이며 정답 보장이나 자동 안전 롤백이 아니다. MVP 31절의 v2·원문 호환·플래그 조합을 따른다 |
| D13 | 초안/공개 포인터 분리를 유지하고 새 구조는 카드 버전과 불변 fact revision을 고정한다. 임베딩 준비 후 CAS로 공개 포인터·색인·사실 참조·knowledge_revision을 원자 전환한다. effective_facts 최신 view는 서빙 정본이 아니다 |
| D14 | 로드맵은 고정 게임판이 아니라 카테고리 + 승인 카드로 동적 구성한다. 승인 카드가 없으면 `stages=[]`, 샘플 카드를 넣지 않는다 |
| D15 | 알림은 앱 내부 알림(`notification_events`)이 정본, Web Push 는 추가 전달. `REQUESTED` 는 전달 요청 성공일 뿐 수신·읽음이 아니다 |
| D16 | 기존 gemini-3.6-flash·추출 온도 0.0을 이번 구조 실험의 비교 기준으로 고정한다. 과거 온도 실험의 문서 수치를 재현된 일반 성능 근거로 쓰지 않는다 |
| D17 | 전체 사실/질문 고정 분모, 사실·질문 단위 짝비교, A/B 각 최소 3회와 A/A 대조, 불안정·실패 사례 포함. 3회는 통계 보장이 아니며 holdout은 사전등록 반복 캠페인으로 평가한다. 대조군 변동·사전 예산·비열등 기준을 통과해야 승격한다 |

확정 결정의 변경은 `docs/ASKBUDDY_MVP_CURRENT.md`와 `docs/DEV_TODO_CURRENT.md`에 먼저 반영하고, 평가 결과와 migration 호환성을 함께 검토한다.

---

## 하지 말 것

- 별도 벡터 DB 도입 (pgvector로 충분)
- YOLO·SAM 등 CV 파이프라인 추가
- Supabase Realtime 구독
- `is_sensitive` 관련 로직 구현
- **사용자 화면에 근거 없는 '신뢰도 %'나 지식 완성도 퍼센트 표기**
- **서비스명 혼용** (AskBuddy 하나. Relay·유니쉐프 금지)
- 요청하지 않은 기능 확장. 범위를 벗어나면 먼저 물어본다
- `pip freeze > requirements.txt` (공용 파일을 통째로 덮어쓴다. 한 줄씩 append)
- 인증을 우회하는 엔드포인트 추가. 로컬 토큰은 `api/scripts/dev_token.py` 로 만든다
- `web/` 에 Supabase 클라이언트·LLM 키·DB 자격증명 배치
- **평가용 실제 자료의 브랜드명·상호·메뉴 고유명을 어디에도 쓰지 않기.**
  데모·지원서·발표자료는 물론 `.md` 문서·커밋 메시지·코드 주석·테스트 픽스처에도 금지다.
  "어느 브랜드 자료로 테스트했다" 는 서술 자체를 남기지 않는다.
  문서에는 `평가용 카페 자료 A` 같은 익명 식별자만 쓴다. 원본은 Git 제외 경로에만 둔다

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
  정적 검사(`pnpm check`)와 브라우저 확인을 구분해서 보고한다. 자동 E2E 는 `통합 검증` 단계 범위다.
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

동작 확인은 인증된 개발 매장 fixture와 현재 API 계약을 사용한다. 공개 store_id만 넣는 과거 curl 예제를 신규 제품 호출로 복제하지 않는다.

---

## 현재 마일스톤

2026-09-14 코드 대조 기준 `0b8e1c4`. 카드 수명주기·동적 로드맵·질문/점주 답변·알림·team 평가·사실 원장 migration 기반이 존재한다. 파일 존재·과거 테스트 기록·운영 검증을 구분한다.

현재 목표는 TODO의 C0 → W0~W5 / R0~R5 병렬 → J0~J3이다. 원장 선저장·불변 승인 snapshot·참조 renderer·chat v2는 계획이며 이 문서 동기화로 구현된 것이 아니다. 상세 현황은 MVP 22절, 완료 조건은 TODO를 따른다.
