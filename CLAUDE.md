# CLAUDE.md

> 이 파일은 Claude Code가 세션 시작 시 자동으로 읽는다.
> **작업 전 반드시 `docs/AskBuddy_개발가이드.md`를 읽을 것.** 이 파일은 요약이고, 그쪽이 정본이다.

---

## 프로젝트

AskBuddy — 카페 등 소규모 매장의 업무 인수인계를 AI가 대신하는 서비스.
점주가 음성·영상·카톡·문서를 올리면 지식카드로 정리되고, 신입은 로드맵과 채팅으로 배운다.

**승인된 매장 지식만 근거로 답하고, 근거가 없으면 추정하지 않고 점주에게 넘긴다.**

**등록이 먼저다.** 점주·퇴사자가 자료를 올려 초기 지식을 채운다.
업로드 게이지가 80% 이상이어야 미리보기로 넘어가고, 그 뒤 초대코드가 발급된다.

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
| `docs/AskBuddy_개발가이드.md` | 아키텍처·계약·결정사항·개발 순서. **정본** |
| `docs/AskBuddy_사업계획서_v5.pdf` | 제품 정의·가격·시장. 제품 판단이 필요하면 여기 **(아직 리포에 없음 — 넣을 것)** |
| `docs/AskBuddy_환경세팅.md` | 파트별 환경 구성, 실행 방법 |
| `docs/ingest-contract.md` | `/ingest/*` 상세 계약. 업로드 3단계·에러 코드·프론트 예시 |
| `UI/` | 화면 목업 24장. 프론트 작업 전 반드시 볼 것 |
| `db/001_init_schema.sql` | 스키마 원천(24 테이블). 컬럼명·타입은 이 파일이 기준. `users` 에 `email`·`password_hash` 포함 |
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
- **영상은 단독 등록 불가.** 음성·텍스트·사진 중 최소 1건 등록 후 보조자료로 활성화한다.
  영상만으로는 공간 좌표·경로 정확도를 보장할 수 없다는 판단(8차 회의)
- **업로드 전에 "찍어야 할 위치 체크리스트"를 먼저 보여준다.** 자료 커버리지가 곧 정확도다
- **신입에게 공개되기 전 점주가 사진을 검토·제외·블러 처리할 수 있어야 한다.**
  현장 인터뷰에서 나온 "지저분해서 보내기 싫다"는 저항에 대한 대응. 기술 문제가 아니라 감정 문제다
- 업로드 진전도 게이지 가중치: 음성 +20 · 영상 +30 · 텍스트 +20 · OCR +10.
  **80% 이상**에서 "미리보기" 버튼이 활성화된다

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
5. **`kind: "miss"`면 LLM을 호출하지 않는다.** "사장님께 확인 중" 배지만 띄운다.
6. **`ANSWERED` 메시지는 `message_citations`가 1건 이상이어야 한다.** 0건이면 답변을 폐기한다.
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
| D6 | 알림은 폴링(2초). Realtime 미사용 |
| D7 | STT 는 OpenAI `whisper-1` |
| D8 | Storage 버킷 `sources`(비공개). 경로 `{store_id}/{voice\|video\|kakao\|scan}/{uuid}.{ext}`. 업로드는 서명 URL |
| D9 | `content_hash` 는 프론트가 SHA-256 계산. 누락 시 서버가 backfill |
| D10 | `INGEST_MODE` 기본값 `mock`. M1 통과 전에는 Gemini 를 붙이지 않는다 |
| D11 | 검색 게이트 임계는 `RETRIEVAL_THRESHOLD`(현재 0.6). D3 와 **별개 값**이다 |

이 결정들을 "개선"하려 들지 말 것. 각각 이유가 있고 개발가이드 12장에 근거가 적혀 있다.

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

**M3 — 미답변 순환 완성.** 데모의 필수 구간이자 제품의 정의다.

```
miss → pending_questions → 점주 대시보드 답변 → 카드 갱신 → 배지 해제
```

M0(스키마)·M1(목 관통)·M2(음성)·M4(영상·카톡·스캔)는 관통 확인됨.
남은 것은 **6~9번 시나리오**다 — hit 답변 / miss 배지 / 점주 답변 / 신입 화면 반영.
시간이 부족하면 다른 걸 자르고 이 넷을 살린다.
