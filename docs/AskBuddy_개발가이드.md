# AskBuddy 개발 가이드 (통합)

> **이 문서의 용도**
> 입력(준혁)·DB(관호)·출력(도영) 세 파트의 공통 계약서이자, AI 코딩 에이전트에 통째로 던지는 컨텍스트 문서다.
> **수정 규칙: 기존 내용을 지우지 말고 아래로 append 한다.** 결정이 바뀌면 원문은 두고 11장 변경 로그에 사유를 남긴다.
>
> 최종 수정: 2026-08-25 · **문서 버전 v0.4**
> v0.2: 미확정 6건 전부 결정 · 관호님 기존 FastAPI 구현을 정본으로 반영 · 도영님 ver2 프로토타입 화면 흐름 반영
> v0.3: **RLS 제거.** 매장 격리는 API 코드 레이어 단독. `users.auth_uid` 삭제, `002_rls.sql` 폐기, 시드는 `002_seed_demo.sql`로 변경
> v0.4: 리포 껍데기 확정 · 입력 파트 M1 관통 · 업로드 경로를 서명 URL 방식으로 확정(D8) · STT 확정(D7) · 테이블 수 21→24 정정

---

## 1. 제품 한 줄 정의

점주가 음성·영상·카톡·문서를 올리면 AI가 매장 지식으로 정리하고, 신입은 로드맵과 채팅으로 배운다. **승인된 매장 지식만 근거로 답하고, 근거가 없으면 추정하지 않고 점주에게 넘긴 뒤, 점주 답변이 지식으로 되돌아온다.**

구현 우선순위가 충돌하면 이 순환을 닫는 쪽을 택한다.

---

## 2. 확정 아키텍처

```
[Next.js 16]                    [FastAPI (Python 3.12)]
화면 · 라우팅 · 세션              /reg/*    지식 등록 · 검색 게이트   (관호, 구현됨)
로드맵 · 채팅 UI                  /auth/*   가입 · 로그인 · join      (관호, 구현됨)
대시보드 · 업로드 UI               /ingest/* 멀티모달 전처리 · 추출    (준혁, 신규)
        │                                │
        │  HTTP (NEXT_PUBLIC_API_URL)    │ DB 자격증명
        └───────────────►────────────────┤
                                         ▼
                          Supabase Postgres + pgvector + Storage
```

**세 가지 불변식**

1. **브라우저는 Supabase를 직접 치지 않는다.** 모든 데이터 접근은 FastAPI를 경유한다. DB 자격증명은 API만 갖는다. **RLS가 없으므로 이 규칙이 유일한 격리 수단이다.**
2. **LLM 호출은 FastAPI 안에서만 일어난다** (D2). Next.js는 `OPENAI_API_KEY`·`GEMINI_API_KEY`를 갖지 않는다.
3. **지식 진입점은 `POST /reg/retrieve` 하나다.** 채팅·검색 어디서 들어오든 이 엔드포인트를 통과한다.

**파트별 소유 범위**

| 파트 | 소유 | 상태 |
|---|---|---|
| 관호 (DB·검색) | 스키마, `/reg/*`, `/auth/*`, 검색 게이트, 골든셋·회귀 | 구현됨 (회귀 36건 통과) |
| 준혁 (입력) | `/ingest/*`, ffmpeg·pypdf·카톡 파서, Gemini 추출, 임베딩 적재 | 신규 |
| 도영 (출력) | Next.js 전 화면, 폴링, citation UI, 대시보드 | ver2(Vite) → Next 이식 |

---

## 3. 확정된 결정 6건

| # | 항목 | 결정 | 파급 |
|---|---|---|---|
| D1 | 인증·격리 | **RLS 미도입.** 매장 격리는 API 코드에서만 한다. 모든 쿼리에 `store_id`를 직접 넣는다. Supabase Auth를 쓰지 않으므로 `users.auth_uid`도 없다 | 8장 격리 규칙 |
| D2 | LLM 호출 위치 | **전부 FastAPI.** 임베딩·추출·답변 생성 모두 파이썬. Next는 LLM 키 없음 | 프롬프트가 한 곳에만 존재 |
| D3 | 신뢰도 임계 | **0.6** (스키마상 60.00). 미만이면 점주 검수 화면 상단 우선 노출 | `knowledge_cards.confidence` |
| D4 | 임베딩 | **OpenAI `text-embedding-3-small`, 1536차원 고정.** ERD 값과 일치하며 기존 임계값·회귀가 이 모델 기준 실측 | 모델 교체 = 전면 재측정 |
| D5 | 민감 카드 | **컬럼만 유지, 이번 릴리스 미사용.** `is_sensitive`, `dek_encrypted`는 예약 필드. 코드에서 읽지도 쓰지도 않는다 | 보안 설계 근거로만 사용 |
| D6 | 알림 | **폴링.** `sources.status`, `pending_questions.status`를 2초 간격 조회. Realtime 미사용 | 프론트 단순화 |

> **D4 주의:** 앞선 논의의 "모델 하나만 쓴다" 원칙과 달리 임베딩(OpenAI)과 멀티모달 추출(Gemini)이 갈린다. 임계값이 OpenAI 기준으로 이미 실측·회귀 검증됐기 때문에 여기를 건드리는 비용이 더 크다. 두 모델이 하는 일이 겹치지 않아 실패 지점이 늘어나지는 않는다.
> **D5 주의:** 심사에서 보안을 물으면 "설계는 되어 있고 이번 범위에서 활성화하지 않았다"고 답한다. 구현했다고 말하지 않는다.

---

## 4. 데이터 모델 (ERD 21테이블 + 결정 반영)

| 그룹 | 테이블 | 소유 |
|---|---|---|
| 사용자·매장 | `users`, `stores`, `store_members`, `invite_codes` | 관호 |
| 업무 분류 | `task_categories` | 도영(설정) / 준혁(추출 참조) |
| 원본 자료 | `sources` + `source_voice`/`source_video`/`source_frames`/`source_kakao`/`source_scan` | 준혁 |
| 용어 사전 | `store_glossary` | 준혁 |
| 지식 | `knowledge_cards`, `facts`, `card_embeddings` | 준혁(쓰기) / 관호(검색) |
| 로드맵 | `roadmap_stages`, `roadmap_items`, `learning_progress` | 도영 |
| 채팅 | `chat_sessions`, `chat_messages`, `message_citations` | 도영 |
| 미답변 순환 | `pending_questions`, `owner_answers` | 도영 |
| 감사 | `access_logs` | 도영 |

**ERD 대비 추가·변경된 것**

| 항목 | 이유 |
|---|---|
| `stores.store_slug` 추가 | 기존 API의 문자열 `store_id`(`demo-cafe`)를 BIGINT로 해석하는 다리 |
| `sources.content_hash` 추가 | 같은 파일 재업로드 시 카드 중복 방지 |
| `pending_questions.miss_reason` 추가 | 검색 게이트 miss 사유 보존 → 빈 지식 알림 분류 |
| `lexical_tsv` 타입 `TEXT` → `tsvector` | 그대로 두면 인덱싱 불가 |
| `TINYINT(1)` → `boolean`, `DATETIME` → `timestamptz`, `VARBINARY` → `bytea` | MySQL 표기 → Postgres |
| `match_cards()` RPC 추가 | approved 카드만 검색. `p_store_id` 필수 인자 |

**용어 정합:** 검색 게이트의 `approved` = `knowledge_cards.is_verified = true`. 별도 컬럼을 만들지 않는다.

**모든 쿼리는 `store_id`가 선행 조건이다.** RLS를 두지 않기로 했으므로(D1) 코드에서 빠뜨리면 그대로 전 매장 데이터가 노출된다. DB가 막아주지 않는다.

> 인증 컬럼(email·password_hash 등)은 관호님 기존 `identity.sql` 정의를 따르고, 통합 시 `users` 테이블에 병합한다.

---

## 5. 화면 흐름 (ver2 프로토타입 기준)

```
welcome → role-select
  ├─ owner → owner-intent
  │            ├─ 인수인계 → category → upload → preview → complete
  │            └─ 대시보드 → dashboard
  └─ staff → staff-id(초대코드) → roadmap → chat
```

| 화면 | 읽기 | 쓰기 |
|---|---|---|
| staff-id | 초대코드로 매장 조회 | `store_members` 합류 |
| category | 업종·카테고리 | `stores.business_type`, `task_categories.is_enabled` |
| upload | — | `sources` + 유형별 하위 테이블 |
| preview | 카테고리별 신뢰도, 카드 목록 | (재업로드 시 `sources`) |
| complete | 초대코드 | 학습 완료 상태 |
| roadmap | 단계·항목·진행도 | `learning_progress.status` |
| chat | 대화 이력 | `chat_messages`, miss 시 `pending_questions` |
| dashboard | 직원별 진행도, 대기 질문, 빈 지식 | `owner_answers` |

**Enum 매핑 (프로토타입 → DB)**

| 프로토타입 | DB |
|---|---|
| `owner` / `staff` | `OWNER` / `STAFF` |
| `cafe`·`restaurant`·`bakery`·`bar`·`convenience`·`salon` | `CAFE`·`RESTAURANT`·`BAKERY`·`BAR`·`CVS`·`SALON` |
| `voice`/`video`/`kakao`/`scan` | `VOICE`/`VIDEO`/`KAKAO`/`SCAN` |
| `complete`/`current`/`pending`/`locked` | `DONE`/`IN_PROGRESS`/`LOCKED` (pending은 LOCKED로 흡수) |
| `great`/`good`/`warn` | 계산값. `progress_rate` ≥80 / 50~79 / <50 |
| `buddy`/`user` | `BUDDY`/`USER` |

> `StaffLevel`은 DB 컬럼이 아니라 프론트 계산값이다. `stores.deploy_threshold`(기본 80)가 "투입 가능" 기준선이다.
> **진행도 계산식 확정:** `progress_rate = DONE 항목 수 / 전체 체크리스트 항목 수 × 100`. 노드 단위도, 별도 퀴즈도 아니다. (ver2 스펙 7번 미결 해소)

---

## 6. 인터페이스 계약

> **`/ingest/*` 의 상세 계약은 `docs/ingest-contract.md` 에 있다.** 요청·응답 예시, 에러 코드, 프론트 코드까지 그쪽에 있고, 이 절은 원칙만 남긴다.

### 6-1. 자료 처리 상태 머신 (D6 폴링)

```
UPLOADED → PROCESSING → DONE
                     ↘ FAILED (error_message 필수)
```

- 업로드는 3단계다 (D8). `POST /ingest/upload-url` 로 서명 URL 을 받고 → 브라우저가 그 URL 로 파일을 PUT 하고 → `POST /ingest/sources` 로 행을 만든다(`UPLOADED`). 그 뒤 `POST /ingest/process`
- **브라우저는 Supabase 키를 갖지 않는다.** 서명 URL 발급은 API 만 한다
- 프론트는 `GET /ingest/status?source_id=` 를 **2초 간격 폴링**
- **`FAILED`를 화면에 표시하지 않으면 스피너가 영원히 돈다.** 필수 구현
- 파일 바이너리를 API로 POST하지 않는다. 경로 문자열만 넘긴다

### 6-2. 추출 결과 스키마 (Gemini `response_schema` 강제)

```json
{
  "cards": [
    {
      "category_name": "재고정리",
      "title": "우유 보관 위치",
      "content": "냉장고 2단 왼쪽 칸. 오픈 전 유통기한 확인.",
      "confidence": 0.87,
      "facts": [
        { "object_name": "우유", "attribute": "보관위치", "value": "냉장고 2단 왼쪽 칸", "confidence": 0.87 }
      ],
      "evidence": { "source_id": 12, "timestamp_sec": 41 }
    }
  ],
  "unresolved": ["빨대·냅킨 위치 — 자료에서 확인 불가"]
}
```

- 카테고리 자유 생성 금지. 점주가 켜둔 `task_categories`만 프롬프트에 선투입하고 그중에서 고르게 한다
- 확인되지 않으면 채우지 말고 `unresolved`로 반환
- 위치는 랜드마크 기준만. 좋은 예 "제빙기 아래 세 번째 선반", 나쁜 예 "왼쪽에서 2미터"
- `confidence`는 0~1로 받아 DB에는 ×100으로 저장 (`numeric(5,2)`)
- **추출 직후 카드는 `is_verified=false`.** 점주 검수를 거쳐야 검색에 노출된다

### 6-3. 검색 → 답변 (기존 `/reg/retrieve` 계약 유지)

```
POST /reg/retrieve  { store_id, question, top_k }

hit  → { kind: "hit",  candidates: [{ id, content, category, score }] }
miss → { kind: "miss", reason: "no_match"|"intent_mismatch"|"no_anchor", message }
```

**규칙 (변경 금지)**

1. `kind: "miss"` → **LLM 호출 금지.** UX는 "사장님께 확인 중"
2. `kind: "hit"` → 후보 `content`만 LLM 컨텍스트로 넣고, 답변에 없는 id·문장 인용 금지 (`validate_citations`)
3. `ANSWERED` 메시지인데 `message_citations`가 0건이면 계약 위반 → 답변 폐기
4. miss는 `pending_questions`에 `miss_reason`과 함께 기록

### 6-4. 지식 갱신 순환

```
pending_questions(WAITING)
 → 점주 대시보드 답변 입력 → owner_answers
 → knowledge_cards 생성/갱신 (is_verified=true, owner_answers.card_id 연결)
 → 해당 card_embeddings.is_stale = true
 → 워커 재임베딩 후 is_stale = false
 → pending_questions.status = 'ANSWERED'
 → 신입 화면 배지 해제
```

점주 답변은 검수를 거치지 않고 바로 approved로 들어간다. 작성 주체와 검수 주체가 같기 때문이다.

---

## 7. 개발 순서

### M0 — 스키마 정합 (관호, 반나절)
`001` → `002` 적용. 기존 `knowledge.sql`을 이 스키마로 흡수하고, `identity.sql`의 인증 컬럼은 `users`에 병합하고, `/reg/*`가 `store_slug`로 `store_id`를 해석하도록 수정.

**이게 끝나야 나머지 둘이 시작한다.**
완료 판정: `POST /reg/retrieve {store_id:"demo-cafe", question:"우유 어디 보관해요?"}` → hit.

### M1 — 목 데이터로 경계 뚫기 (전원, 최우선)
- 준혁: `/ingest/process`가 하드코딩 카드 3개를 INSERT (Gemini 미호출)
- 도영: 초대코드 진입 → 로드맵 렌더 → 카드 열람 → 채팅 hit/miss 표시
- 관호: 시드 카드 임베딩 생성 스크립트

**M1 전에 Gemini를 붙이지 않는다.** 통합 실패는 항상 여기서 난다.

### M2 — 음성 채널 관통 (준혁)
업로드 → 전사 → 추출 → 카드 적재(`is_verified=false`) → 검수 화면 → 승인 → 임베딩 → 검색 hit.

### M3 — 미답변 순환 완성 (도영)
miss → `pending_questions` → 대시보드 답변 → 카드 갱신 → 배지 해제. **데모의 필수 구간.**

### M4 — 채널 확장·마감
영상(ffmpeg) → 카톡 txt → 파일 스캔. 신뢰도 표시, 진도율 게이지, 접근 로그.

**원칙: 3개 기능이 완결된 데모 > 10개 기능의 미완성 데모.**

### 현재 상태 (2026-08-25 기준)

| 마일스톤 | 상태 | 비고 |
|---|---|---|
| M0 스키마 정합 | 진행중 | `db/001`·`002` 는 로컬 적용·검증 완료. `/reg/*` 의 `store_slug` 해석은 관호 |
| M1 목 데이터 관통 | **입력 완료** | `/ingest/*` 전 구간 통과(업로드→처리→폴링→카드 3건). 출력·DB 는 진행중 |
| M2 음성 관통 | **관통 확인** | 전사(whisper-1) → Gemini 추출 → 카드 적재 → 승인 → 임베딩 → `/reg/retrieve` hit 까지 실측 통과 |
| M3 미답변 순환 | 미착수 | 도영 |
| M4 채널 확장 | **VIDEO·KAKAO·SCAN 관통** | 준혁. 실측 25/26 통과 |

### 다음 할 일

**준혁 (입력)** — M2·M4 관통 확인됨. 남은 것은 아래
1. **실제 자료로 재검증.** 지금까지는 전부 합성 자료다 — 사람이 쓴 전사문, 직접 만든 카톡 txt, PIL 로 그린 영상. 실제 녹음은 잡음·말끊김·사투리가, 실제 카톡은 예상 못 한 형식이 섞인다
2. N9 — 추출 카드의 검색 점수를 관호님과 맞춘다
3. `store_glossary` (N7) — 매장 용어가 전사에서 깨지면 그때 채운다
4. 영상 처리가 느리다. 12초 영상에 Gemini 18.6초. 실제 매장 영상(수 분)은 폴링이 오래 돈다 — 진행률 표시를 도영님과 상의할 것

**프롬프트 튜닝 루프 (준혁)**

```bash
# 1) 전사문만 있으면 STT 없이 추출을 돌려볼 수 있다
INGEST_MODE=real python scripts/extract_preview.py --file data/sample_transcript.ko.txt

# 2) api/prompts/extract_cards.ko.txt 만 고친다. 코드는 안 건드린다
# 3) DB 까지 넣어보려면
python scripts/set_transcript.py --file data/sample_transcript.ko.txt
curl -X POST localhost:8000/ingest/process -H "Authorization: Bearer $ASKBUDDY_TOKEN" \
     -H 'Content-Type: application/json' -d '{"source_id":<위 출력>}'
```

**관호 (DB)**
1. `/reg/*`·`/auth/*` 를 `api/app/reg/`·`api/app/auth/` 로 이식. 라우터는 `main.py` 에 이미 등록돼 있다
2. `/auth` 가 붙으면 `scripts/dev_token.py` 는 폐기한다
3. **점주 승인 직후 `POST /ingest/embed?card_id=` 를 호출한다.** 이걸 안 부르면 승인해도 검색에 안 걸린다
4. 기존 임베딩 함수를 `ingest/embed/service.py` 의 `_embed()` 와 통합 (N6)

**도영 (출력)**
1. `docs/ingest-contract.md` 대로 업로드 3단계 연동
2. 폴링에서 `FAILED` 분기 필수. 빠지면 데모에서 스피너가 영원히 돈다
3. 검수 화면은 `confidence < 60` 을 상단 우선 노출 (D3). 목 카드에 `42.0` 짜리를 하나 넣어뒀다
4. 로그인 전까지 토큰은 `python api/scripts/dev_token.py`

**공통**
- 하루 한 번 이상 `main` 을 자기 브랜치로 rebase
- 머지 순서는 `feat/db` → `feat/input` → `feat/output`

---

## 8. 코딩 규칙

**공통 — 매장 격리 (RLS가 없으므로 이게 전부다)**
- 모든 DB 접근 함수는 `store_id`를 **필수 인자**로 받는다. 기본값·`Optional` 금지
- `WHERE store_id = ?` 없는 조회 쿼리를 작성하지 않는다. 코드 리뷰 시 이것부터 본다
- `store_id`는 요청 본문이 아니라 **JWT에서 꺼낸 값**을 신뢰한다. 클라이언트가 보낸 `store_id`를 그대로 쓰면 다른 매장을 조회할 수 있다
- 통합 전 점검: 매장 2개를 만들고 A 계정으로 B의 카드가 안 보이는지 확인한다

**공통 — 그 외**
- 상태 문자열은 대문자 상수: `UPLOADED`, `PROCESSING`, `DONE`, `FAILED`, `WAITING`, `ANSWERED`, `LOCKED`, `IN_PROGRESS`
- 시간은 `TIMESTAMPTZ`. KST 변환은 프론트에서만
- 커밋 접두사: `[input]`, `[db]`, `[output]`, `[docs]`

**Python**
- 프롬프트는 `prompts/` 파일로 분리. 코드 하드코딩 금지
- LLM 호출마다 소요 시간·토큰 로깅
- 실패하면 다음 단계로 넘어가지 말고 명확히 멈춘다
- 중간 산출물을 파일로 남겨 재실행 가능하게 (`--skip-stt` 등)

**TypeScript**
- LLM API 키를 두지 않는다
- DB 자격증명(`SUPABASE_SERVICE_KEY` 등)을 두지 않는다
- Next 16은 `params`·`cookies()`·`headers()`가 async

**하지 말 것**
- 별도 벡터 DB (pgvector로 충분)
- YOLO·SAM 등 별도 CV 파이프라인
- `is_sensitive` 관련 로직 구현 (D5, 예약 필드)
- Realtime 구독 (D6, 폴링 확정)
- 게임화 요소 추가 (제거하려던 노동을 다시 만든다)

---

## 9. 데모 시나리오

1. 점주 진입 → 업종 카페 → 카테고리 4개 토글(베이킹 OFF)
2. 음성 업로드 → 처리 중 폴링 → 학습 미리보기에 카테고리별 신뢰도
3. 검수에서 카드 1개 수정 후 승인
4. 초대코드 `CAFE-DEMO` → 신입 진입
5. 로드맵 1단계 체크 → 진도율 상승
6. "우유 어디 보관해요?" → **hit**, 근거 카드와 함께 답변
7. "시럽 재고 부족하면?" → **miss**, "사장님께 확인 중" 배지, LLM 호출 없음
8. 점주 대시보드에 질문 도착 → 답변 입력
9. 신입 화면에서 답변 확인, 카드로 반영

**6~9번이 차별점이다.** 시간이 부족하면 다른 걸 자르고 이 넷을 살린다.
시연 질문은 시드·골든셋에 있는 표현을 쓴다. 띄어쓰기·활용형 변형은 미검증이다.

---

## 10. 에이전트 사용법

이 문서를 코딩 에이전트에 던질 때 함께 넣을 것:

1. 이 문서 전문
2. `001_init_schema.sql` (스키마 원천)
3. `http://localhost:8000/docs` OpenAPI 또는 `reg-contract.md`
4. **작업 범위 명시** — "M2의 음성 채널만. 영상·카톡은 건드리지 말 것"

범위를 안 주면 에이전트는 반드시 기능을 부풀린다. 8장의 "하지 말 것"을 프롬프트에 함께 붙인다.

---

## 11. 변경 로그 (append 영역)

> 형식: `YYYY-MM-DD | 파트 | 무엇을 | 왜`

| 날짜 | 파트 | 변경 | 사유 |
|---|---|---|---|
| 2026-08-25 | 공통 | v0.1 생성. B안, Next 16 채택 | 로드맵은 CRUD라 파이썬 불필요 |
| 2026-08-25 | 공통 | v0.2. 미확정 6건 전부 결정(D1~D6) | 12장 참조 |
| 2026-08-25 | DB | 기존 FastAPI 구현을 정본으로 인정. Next는 화면·BFF로 축소 | `/reg/retrieve` 게이트와 회귀 36건이 이미 존재 |
| 2026-08-25 | DB | `store_slug`·`content_hash`·`miss_reason` 추가 | API 호환 + 멱등 + miss 분석 |
| 2026-08-25 | 공통 | v0.3. **RLS 제거**, `users.auth_uid` 삭제, `002_rls.sql` 폐기 | 해커톤 범위에서 정책 디버깅 비용 대비 이득 없음. 브라우저가 DB를 직접 치지 않으므로 노출면이 없음 |
| 2026-08-25 | 출력 | 진행도 계산식을 체크리스트 완료 비율로 확정 | ver2 스펙 7번 미결 해소 |
| 2026-08-25 | 공통 | v0.4. 리포 껍데기를 main 에 올리고 `db/`·`docs/`·`api/`·`web/` 구조 확정 | 브랜치 3개가 각자 구조를 만들면 머지 때 세 벌로 갈라진다 |
| 2026-08-25 | 공통 | 스키마 테이블 수 **21 → 24** 로 정정 | 실제 `001_init_schema.sql` 이 24개. 문서 숫자가 틀렸다 |
| 2026-08-25 | 입력 | `/ingest/*` M1 관통 구현 (목 추출 → 카드 적재 → 폴링) | 가이드 7장 M1. Gemini 는 붙이지 않음 |
| 2026-08-25 | 입력 | `POST /ingest/sources` 신설 | `sources` 행 생성 주체가 문서에 없었다. 브라우저는 DB 를 못 치므로 API 가 만든다 |
| 2026-08-25 | 입력 | `POST /ingest/upload-url` 신설, 서명 URL 방식으로 확정 | "프론트 직접 업로드"와 불변식 1·2 가 충돌. 브라우저에 키를 주지 않으면서 파일이 API 를 거치지 않게 하는 유일한 방법 |
| 2026-08-25 | 입력 | `POST /ingest/embed` 신설 | 승인 → 임베딩을 잇는 지점. 관호님 승인 플로우에서 호출한다 |
| 2026-08-25 | 입력 | `INGEST_MODE` 도입, 기본값 `mock` | "M1 전에 Gemini 를 붙이지 않는다"를 코드로 강제 |
| 2026-08-25 | 공통 | `scripts/dev_token.py` 추가 | `/auth` 가 붙기 전까지의 임시 토큰. 인증 우회 엔드포인트를 만들지 않기 위함 |
| 2026-08-25 | DB | `users` 에 `email`·`password_hash` 병합. 시드에 bcrypt 해시(`demo1234`) | M0. `identity.sql` 인증 컬럼 흡수 |
| 2026-08-25 | DB | `app/reg/embeddings.py` 신설 — `embed_texts` 단일 진입점 | D4. 임베딩 함수가 두 벌이 되는 것을 막는다 |
| 2026-08-25 | 입력 | `ingest/embed/service.py` 가 `reg.embeddings.embed_texts` 를 호출하도록 교체 (N6 해소) | 동기 함수라 `asyncio.to_thread` 로 감쌈 |
| 2026-08-25 | 공통 | `supabase/config.toml` 의 `project_id` 를 **`AskBuddy`** 로 통일 | 폴더명이 달라 각자 다른 값이 생성됐다. 컨테이너 이름(`supabase_db_AskBuddy`)이 갈라진다 |
| 2026-08-25 | 공통 | `.env.example` 인라인 주석 제거 | dotenv 가 값에 주석을 붙여 읽을 수 있다 |
| 2026-08-25 | 입력 | **`GEMINI_MODEL` 을 `gemini-3.6-flash` 로 변경** | `gemini-2.5-flash` 가 신규 사용자에게 막혔다. 404 응답이 대체 모델을 지정한다 |
| 2026-08-25 | 입력 | 전사문이 있으면 STT 를 건너뛴다 | 가이드 8장 `--skip-stt`. 추출 프롬프트는 수십 번 돌려야 하는데 STT 는 느리고 비싸다 |
| 2026-08-25 | 입력 | `scripts/set_transcript.py`·`scripts/extract_preview.py` 추가 | STT 없이 추출부터 개발·튜닝하기 위한 반복 루프 |
| 2026-08-25 | 입력 | 추출 프롬프트 튜닝 — 한 카드 한 대상, confidence 구간 기준 명시 | 우유·원두·시럽이 한 카드로 합쳐져 "우유 어디 있어요?" 에 대응이 안 됐다. 4건 → 8건으로 분리됨 |
| 2026-08-25 | 공통 | 검색 게이트 임계를 `RETRIEVAL_THRESHOLD` 로 분리, 값 0 | D3 와 한 값을 공유하고 있었다. `app/reg/router.py` 한 줄 변경 (관호님 파일) |
| 2026-08-25 | 입력 | M4 — VIDEO·KAKAO·SCAN 전처리 구현 | 영상은 프레임+오디오, 카톡은 정규식 파서, 문서는 pypdf→깨지면 Gemini 판독 |
| 2026-08-25 | 입력 | 추출기가 이미지·PDF 를 함께 받도록 확장 | 영상 프레임과 스캔본은 텍스트로 담을 수 없다 |
| 2026-08-25 | 공통 | `main.py` 에 로깅 설정 추가 | uvicorn 기본 설정이 `app.*` 로거를 막아 LLM 호출 로그가 안 보였다 (가이드 8장) |

---

## 12. 결정 기록 (append 영역)

| # | 결정 | 날짜 | 근거 |
|---|---|---|---|
| D1 | RLS 미도입. 격리는 API 코드 단독 | 2026-08-25 | 브라우저가 DB에 직접 접근하지 않아 노출면이 없음. 정책 디버깅에 시간을 쓰지 않는다 |
| D2 | LLM 호출은 FastAPI 단독 | 2026-08-25 | citation 검증이 파이썬에 있음. 분산되면 규칙이 두 언어로 갈라짐 |
| D3 | 신뢰도 임계 0.6 | 2026-08-25 | 실측 전 잠정값. 파일럿에서 점주 수용률 보고 조정 |
| D4 | OpenAI text-embedding-3-small 1536 | 2026-08-25 | ERD 값과 일치, 임계값·회귀가 이 기준 실측 |
| D5 | `is_sensitive`·`dek_encrypted` 예약 필드로만 유지 | 2026-08-25 | 이번 범위 밖. 구현했다고 말하지 않는다 |
| D6 | 폴링 (2초) | 2026-08-25 | Realtime은 구현·디버깅 비용 대비 이득 없음 |
| D7 | STT 는 OpenAI `whisper-1` | 2026-08-25 | 한국어 지원·비용·안정성. 검색은 임베딩 기준이라 교체해도 임계값에 영향 없음 |
| D8 | Storage 버킷 `sources`(비공개). 오브젝트 경로 `{store_id}/{voice\|video\|kakao\|scan}/{uuid}.{ext}`. 업로드는 API 가 발급한 **서명 URL** 로만 | 2026-08-25 | 브라우저에 Supabase 키를 주지 않으면서 파일 바이너리가 API 를 거치지 않게 하는 유일한 방법. 원본 파일명을 경로에 쓰지 않는 것은 한글·공백 인코딩 사고와 덮어쓰기 방지 |
| D9 | `content_hash` 는 프론트가 SHA-256 계산해 전달. 누락 시 서버가 처리 중 backfill | 2026-08-25 | `crypto.subtle` 은 https·localhost 에서만 동작한다. 프론트가 실패해도 중복 방지가 죽지 않게 |
| D10 | `INGEST_MODE` 기본값 `mock` | 2026-08-25 | 통합 실패는 항상 M1 구간에서 난다. 목 경로를 기본값으로 두어 키 없이도 전 구간이 돌게 |
| D11 | 검색 게이트 임계를 `CONFIDENCE_THRESHOLD`(D3) 에서 분리해 `RETRIEVAL_THRESHOLD` 로 둔다. **값은 0.6** | 2026-08-26 | 한 값이 카드 검수 기준과 검색 하한을 동시에 제어하고 있었다. 분리 후 0 으로 내렸다가 0.6 으로 확정 |

---

## 13. 남은 미결 (신규)

| # | 항목 | 결정자 | 기한 |
|---|---|---|---|
| N1 | 초대코드 입장과 Supabase 로그인의 관계 — 초대코드로 계정 자동 생성인가, 로그인 후 join인가 | 관호·도영 | M0 |
| N2 | 배포 공유 여부 (로컬 시연 vs Vercel+Railway 확정) | PM | M3 |
| N3 | miss UX 문구 통일 ("사장님께 확인 중" 제안) | PM | M1 |
| N4 | 답변 생성 모델 — OpenAI vs Claude vs Gemini (호출 위치는 FastAPI로 확정) | 관호 | M3 |
| N5 | ver2(Vite) → Next 16 이식 범위 — 전면 재작성 vs 컴포넌트 이식 | 도영 | M1 |
| ~~N6~~ | ~~관호님 기존 임베딩 함수 통합~~ → **해소.** `app.reg.embeddings.embed_texts` 를 ingest 가 호출한다 | 관호·준혁 | 완료 |
| N10 | **임계 0.6 에서는 추출 카드가 miss 로 빠진다.** 실측 0.591 < 0.6. 점주가 승인한 카드로 답하는 장면을 데모에 넣으려면 0.4~0.5 가 필요하다 (N9 와 같은 뿌리) | 관호·PM | M3 |
| N7 | `store_glossary` 를 채우는 경로가 없다. 현재 추출 프롬프트에 "(등록된 용어 없음)" 이 들어간다 | 준혁·도영 | M4 |
| N8 | 배포 시 `JWT_SECRET` 교체 절차 — 로컬 기본값이 리포에 있다 | PM | M3 |
| N9 | **추출 카드가 시드 카드보다 검색 점수가 낮다.** 같은 질문에 시드 0.640 / 추출 0.591. 게이트 임계(≈0.6)가 시드 기준으로 잡혀 있어, 점주가 승인한 카드가 miss 로 빠질 수 있다 | 관호·준혁 | M3 |

> **해소됨:** 도영님이 물은 Storage 경로 규약과 `content_hash` 계산 주체는 D8·D9 로 확정했다. 상세는 `docs/ingest-contract.md`.
