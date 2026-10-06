# AskBuddy 리브랜딩 모바일 화면 구현 — 총괄 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

2026-10-06 · 상태: **총괄 계획 승인됨(U6~U8 반영). 실행: 직접 실행, P5 백엔드만 subagent-driven + 별도 검토.** 브랜치 `ui/rebrand-mobile` (worktree `../2026unithon-web`, `origin/main` `4bb145c` 기준)

**Goal:** Figma `AskBuddy — 리브랜딩 · MVP 화면` 의 `4-1 확정 · 모바일 (390)` 페이지를 `web/` 에 구현한다. Figma에 없는 MVP 계약 상태(검수·인용·CLARIFY/ESCALATE·오류·합류 승인 등)는 같은 시각 언어로 추가 화면을 만들어 채운다. 근무조 체크리스트는 백엔드까지 이 브랜치에서 만든다.

**Architecture:** 디자인 토큰과 공통 컴포넌트를 먼저 바꾸고, 그 위에 흐름 단위로 화면을 교체한다. 서버 상태는 기존 TanStack Query 계층(`web/lib/query.ts`, `web/lib/api.ts`)을 그대로 쓴다. 신규 백엔드는 체크리스트 하나뿐이다. 합류(카카오·초대 링크·승인)는 이미 합의된 `KAKAO_AUTH_PLAN.md` 의 API를 소비한다.

**Tech Stack:** Next.js 16 App Router · TypeScript · Tailwind v4 · TanStack Query v5 · Pretendard / FastAPI · PostgreSQL(Supabase migration)

**Spec:** 이 문서의 §1~§4 + Figma 파일 `OAS1MCVCQpgDVeSoddKnCP` 페이지 `0:1` + `docs/dev/ASKBUDDY_MVP_CURRENT.md` (§8·§9·§10·§12·§13·§16·§17·§28·§29) + `docs/dev/plan/KAKAO_AUTH_DESIGN.md`

## Global Constraints

- 모바일 프레임 390×844 기준, 보조 확인 360×800. 콘텐츠 최대 폭 480px (MVP §24-1)
- Figma 반응형 규칙: 가로 여백 20(최소 16) · 카드·버튼 폭 FILL, 높이 HUG · 수동 줄바꿈 금지 · 본문 15 / 라벨 13 · 터치 44 · 하단 safe-area 34
- 이번 브랜치는 **모바일 360~599 구간만** 구현한다. 태블릿 600~1279·데스크톱 1280~ 레이아웃은 범위 밖이며, 그 폭에서는 480px 중앙 프레임으로 둔다
- 브라우저는 DB·Storage·LLM 키에 직접 접근하지 않는다. 모든 데이터는 FastAPI 경유 (CLAUDE.md 불변식 1·2·7)
- 승인 카드(`published_version_id` 있음)만 직원 화면에 보인다 (불변식 11)
- 모든 목록 화면은 `초기 로딩 / 성공 / 빈 상태 / 오류 / 재시도 / 백그라운드 갱신` 을 갖는다 (MVP §8, §17-5)
- 사용자 문구는 MVP §28 사전을 우선한다. Figma 문구와 다르면 §28을 따르고, §28에 없는 상황만 Figma 문구를 쓴다
- 근거 없는 신뢰도·완성도 퍼센트를 표시하지 않는다. 진행 막대는 실제 count(예: 체크 4/7)에만 쓴다
- 서비스명은 AskBuddy 하나. 평가용 실제 자료의 상호·메뉴 고유명을 코드·픽스처·문서에 쓰지 않는다. Figma 예시 문구(`더카페 논현점` 등)는 데모 시드 값으로만 쓴다
- `web/` 에는 단위 테스트 러너가 없다. 검증은 `pnpm check` + 브라우저 확인으로 구분해 보고한다
- 커밋·푸시·PR은 사용자가 요청할 때만 한다

---

## 1. 사용자 결정 (2026-10-06)

| # | 결정 |
|---|---|
| U1 | 이번 작업만 worktree(`../2026unithon-web`)에서 백엔드 작업과 병렬로 진행한다 |
| U2 | 알바 "오늘 할 일" 체크리스트는 이번 범위에 **백엔드까지 포함**한다. 근무조는 오픈·미들·마감으로 고정하지 않고 **점주가 이름·시간·개수를 자유롭게 정한다.** 근무조가 0개면 체크리스트 전체를 한 묶음으로 보여준다 |
| U3 | 알바 합류는 원래 정한 대로다: 카카오(기본)·이메일 로그인 → 초대 링크 → 합류 요청 → **점주 승인** → 직원. Figma의 "가입 없이 바로 보기"는 따르지 않는다. 필요한 화면은 Figma에서 착안해 새로 만든다 |
| U4 | 점주 알림은 **즉시** 보낸다(앱 내 알림 + Push). Figma의 "하루 한 번 모아서 와요" 문구는 쓰지 않는다 |
| U5 | Figma에 없는 우리 흐름·기능은 Figma 시각 언어로 화면을 추가해 채운다 |
| U6 | 말하기·찍기·파일 버튼을 **자료 넣기(O3·O6)와 점주 답하기(O7) 모두** 구현한다. 멀티모달 입력 백엔드는 메인 폴더에서 병렬 개발 중이다. 이 브랜치는 기존 ingest API에 연결하고, 점주 답변 첨부 계약은 병렬 작업 결과에 맞춘다 |
| U7 | **카카오 로그인·초대 링크·합류 승인은 다른 작업으로 진행 중이다. 이 브랜치는 백엔드·화면 모두 하지 않는다.** 기존 P6을 범위에서 뺀다. 그 작업이 P0 공통 컴포넌트를 쓸 수 있게만 둔다 |
| U6-1 | (2026-10-06 추가) 붙여 넣은 글은 **병렬 작업이 새 자료 유형(TEXT)으로 만든다.** 프론트는 `/ingest/capabilities` 에 `TEXT` 가 있을 때만 글 전송을 켠다 |
| U6-2 | 브라우저 녹음 형식 문제는 **이번에 다루지 않는다.** 말하기 버튼은 숨기고 §8 후속 작업에 남긴다 |
| U6-3 | 점주 답변 첨부(말하기·찍기·파일)는 **이 브랜치에서 하지 않는다.** 계약·백엔드가 아직 계획에 없어 §8 후속 작업으로 남긴다. O7은 텍스트 답변만 연결한다 |
| U8 | 실행은 직접 실행. P5 체크리스트 백엔드만 subagent-driven-development로 작업별 구현·검토를 분리한다 |

## 2. Figma ↔ 현재 계약 대조

### 2-1. Figma 화면 목록 (페이지 `0:1`)

| Figma | node | 대응 MVP 화면 | 현재 라우트 | 새 라우트 |
|---|---|---|---|---|
| O1 시작·로그인 | 18:2 | A01 | `/owner/auth`, `/staff/auth`, `/role` | `/login` |
| O2 매장 이름 | 18:13 | A02 | `/owner/intent`, `/owner/category` | `/owner/setup` |
| O3 아무거나 넣기 | 18:21 | O01 | `/owner/upload` | `/owner/add` |
| O4 알아서 정리됐어요 | 18:39 | O04 | `/owner/preview`, `/owner/cards/review` | `/owner/jobs/[jobId]` |
| O5 알바 초대 | 18:55 | O08 일부 | `/owner/complete` | `/owner/invite` |
| O6 오늘 매장·영업 중 / O6-2 마감 후 | 18:66 / 41:2 | O03 + 체크 현황 | `/owner/questions/v2`, `/owner/dashboard` | `/owner` |
| O7 답하기 | 18:93 | O03 답변 | `/owner/questions/v2` 안 | `/owner/questions/[pendingId]` |
| O8 카드로 남았어요 | 18:110 | 답변 반영 결과 | 없음 | 같은 라우트의 결과 상태 |
| O9 카드 | 25:2 | O05 | `/owner/cards` | `/owner/cards` |
| O10 카드 보기 | 25:41 | O06 | `/owner/cards/[cardId]` | 유지 |
| S1 설정 | 25:101 | O08 | `/owner/notifications` | `/owner/settings` (+ 직원용 `/staff/settings`) |
| A1 초대 링크 열림 | 19:2 | A03 | 없음 (K 계획 Task 13) | `/join/[token]` |
| A2 오늘 할 일 | 19:10 | 신규(체크리스트) | 없음 | `/staff` |
| A3 처음 체크·가입 | 19:40 | A03 가입 | `/staff/auth` | **U3에 따라 재해석**: `/join/[token]` 의 가입 시트 |
| A4 다 했어요 | 19:50 | 신규(체크리스트) | 없음 | `/staff` 완료 상태 |
| A5 물어보기 / A6 답 도착 | 19:58 / 19:82 | S03 | `/staff/chat/v2` | `/staff/chat` |
| A7 레시피 / A8 레시피 보기 | 25:53 / 25:90 | S01 / S02 | `/staff/roadmap`, `/staff/items/[itemId]` | `/staff/recipes`, `/staff/recipes/[itemId]` |

옛 라우트는 지우지 않고 새 라우트로 `redirect` 한다. 이미 저장된 `notification_events.destination` 과 Push 딥링크가 옛 경로를 가리키기 때문이다.

### 2-2. 계약을 바꾸는 지점 — MVP 문서 갱신 필요

| 항목 | 현재 정본 | Figma / 이번 결정 | 처리 |
|---|---|---|---|
| 점주 탭 | 3탭(업로드·답변 대기·카드) §8 | 2탭(오늘 매장·카드). 업로드는 오늘 매장의 입력창, 답변 대기는 "확인해 주세요" 목록 | §24-2가 Figma 후 재결정 항목으로 열어 둔 사항. Figma를 따르고 §8 갱신 |
| 직원 탭 | 로드맵·채팅·FAQ | 2탭(오늘 할 일·레시피) + 하단 질문 입력 | 로드맵 = "레시피" 탭(카테고리별 승인 카드). FAQ는 채팅 첫 화면의 추천 질문으로 이동 |
| 매장 초기 설정 | 매장명·업종·초기 카테고리 §8 A02 | 매장 이름만 | 업종·카테고리는 기본 카테고리 세트로 시작하고 카드 탭에서 관리. §8 갱신 |
| 주 색 | brand-500 `#5BBF6A` 주 버튼 §29-1 | Figma 변수 `color/primary` `#2E6B3C` | Figma 변수로 토큰 교체, §29-1 갱신 |
| 포인트 색 | 핑크/옐로 미정 §24-2 | 핑크(새 카드 배지·장식), 카카오 버튼만 옐로 | 핑크 확정, §24-2 닫음 |
| 근무조 체크리스트 | 없음 | U2 | 신규 계약 §5 설계 후 MVP에 추가 |
| 점주 답변 입력 | 텍스트 | 말하기·찍기·파일 버튼 | U6-3. 이번엔 텍스트 답변만. 첨부는 §8 F3 후속 작업 |

### 2-3. Figma에 없어서 새로 만들 화면·상태 (U5)

| 흐름 | 추가 화면·상태 | 근거 |
|---|---|---|
| 등록 | 처리 중(작업 상태)·`PARTIAL`·`NO_RESULT`·`FAILED`+재시도, 미지원 형식·중복 자료 | §10-1, §28 |
| 검수 | O4에 `NEEDS_REVIEW` 카드 분리 표시, 카드별 저장 실패 자리 오류 | §10-3 |
| 카드 | 사실 추가·수정·삭제·순서 변경 편집 화면, 제외·복원, 근거 보기, `인용 끊김`, 초안/공개본 구분 | 10-05 결정, D20 |
| 카테고리 | 카테고리 관리(추가·삭제·재분류 진행 상태) | §11 |
| 지식 제안 | `SUPPLEMENT`/`CONFLICT` 제안 검토 | §13-2 |
| 점주 답변 결과 | O8은 `NEW` 반영일 때만. `IDENTICAL`·검토 대기·반영 실패는 "답이 전달됐어요" 결과 화면 | §13-2 |
| 질문 | `CLARIFY` 선택지, 정책 안내, 인프라 `ERROR` 재시도, 질문 전송 실패 | §13-1, §28 |
| 알림 | 알림 목록, Push 권한 요청·거절·미지원 | §16 |
| 체크리스트 | 점주 근무조 설정, 체크리스트 카드 근무조 지정 | U2 |

새 화면은 Figma 파일에 먼저 그리지 않고 코드로 만든다. 끝나면 스크린샷 목록을 남겨 디자이너 확인을 받는다(Phase 7).

## 3. 흐름 분할과 순서

순서는 CLAUDE.md의 "순환을 닫는 쪽 우선"을 따른다. 각 Phase는 혼자 돌아가는 화면 묶음으로 끝나고, Phase마다 상세 계획 파일을 따로 쓴 뒤 실행한다.

```text
P0 디자인 기반 ─┬─ P1 질문 순환(핵심) ─ P2 점주 등록 ─ P3 카드 관리 ─ P4 직원 레시피
               │                                                     │
               └──────────── P5 체크리스트(백엔드+화면) ──────────────┤
                                                                     └─ P7 검증·문서
(P6 합류는 U7에 따라 범위 밖)
```

| Phase | 묶음 | Figma | 백엔드 변경 | 상세 계획 파일 |
|---|---|---|---|---|
| P0 | 토큰·폰트·배경·공통 컴포넌트·앱 셸·탭바 | 전 화면 공통, 반응형 규칙 26:4 | 없음 | `UI_REBRAND_P0_FOUNDATION.md` |
| P1 | 질문 순환: 직원 질문 → ESCALATE → 점주 확인 목록 → 답하기 → 결과 → 직원 답 도착 | A5, A6, O6(질문 부분), O7, O8 | 없음 | `UI_REBRAND_P1_QUESTION_LOOP.md` |
| P2 | 점주 등록: 로그인(이메일)·매장 이름·아무거나 넣기·처리 중·정리 결과 검수·초대 진입 | O1, O2, O3, O4, O5 | 없음 | `UI_REBRAND_P2_OWNER_REGISTER.md` |
| P3 | 카드 관리: 목록·상세·사실 편집·제외/복원·근거·카테고리·지식 제안·설정 | O9, O10, S1 | 없음(사실 편집 API는 W3 진행 상황 확인 후) | `UI_REBRAND_P3_CARDS.md` |
| P4 | 직원 레시피: 카테고리별 승인 카드·상세·완료/재확인("바뀌었어요")·FAQ | A7, A8 | 없음 | `UI_REBRAND_P4_STAFF_RECIPES.md` |
| P5 | 체크리스트: 근무조 설정·체크·근무조 완료·점주 현황 | A2, A4, O6 상단, O6-2, 근무조 규칙 41:284 | **신규 migration + API** | `UI_REBRAND_P5_CHECKLIST.md` (설계 포함) |
| ~~P6~~ | 합류 — **범위 밖(U7)** | O1 카카오, O5, A1, A3 | — | 다른 작업 |
| P7 | 통합 검증·문서 갱신·디자이너 확인용 스크린샷 | — | — | 이 문서 §7 |

P1~P4는 기존 API만 쓰므로 서로 독립이다. P5는 백엔드가 있어 P0 직후 병렬로 시작할 수 있다. O1 카카오 버튼·O5 초대·A1·A3는 U7에 따라 만들지 않는다. O5 자리에는 기존 초대 수단으로 가는 안내만 둔다.

## 4. Phase별 범위와 완료 기준

### P0 디자인 기반

- 토큰: Figma 변수 `color/primary #2e6b3c`, `primary-weak #a8d4b4`, `ink #1e2a22`, `ink-muted #66756b`, `surface #ffffff`, `bg #f5f9f6`, `empty #e0eee3` 를 `web/app/globals.css` 에 추가하고, 기존 `brand-*` 를 쓰는 화면이 깨지지 않게 별칭으로 둔다. 상태색(warn·danger)과 핑크 accent는 유지한다
- 수치는 화면마다 `get_design_context` 로 뽑아 확정한다. 눈대중으로 정하지 않는다
- 공통 컴포넌트(`web/components/ui/` 로 분리): `Screen`(배경 오로라·여백 20·safe-area), `BackButton`, `PageTitle`, `Button`(primary·secondary·kakao, 52/44), `Composer`(입력창 + 첨부 버튼 슬롯 + 넣기), `TabBar`(2탭, 역할별), `ListGroup`(라벨 칩 + 행), `StatusChip`, `SourceChip`, `Sheet`, `Empty`, `ErrorInline`, `Skeleton`, `BuddyImage`
- Buddy 캐릭터·아이콘 자산은 Figma에서 내려받아 `web/public/` 에 둔다
- 완료 기준: `pnpm check` 통과, 기존 화면이 새 토큰에서 깨지지 않음(브라우저 확인), 컴포넌트 상태 변주를 한 화면에서 확인

### P1 질문 순환 (핵심)

- 직원 `/staff/chat`: `/learn/chat/v2` 사용. ANSWER(+`SourceChip` 카드 인용), CLARIFY(선택지 칩 → 재질문), ESCALATE(저장 성공 후에만 "확인 중·답 오면 알려드려요"), POLICY 고정 안내, ERROR(입력 보존·재시도). A6 답 도착 = 점주 원문 버블 + "새 카드·방금 추가했어요"는 실제 카드 반영 완료일 때만
- 점주 `/owner`: "확인해 주세요 · N" 목록(WAITING pending), 0건이면 §28 "지금은 기다리는 질문이 없어요"
- 점주 `/owner/questions/[pendingId]`: 질문 원문·질문 횟수, 텍스트 답변 입력창(U6-3, 첨부는 §8 F3). 저장 실패 시 입력 보존
- 결과: 지식 반영이 `NEW` 로 공개되면 O8, 그 외(동일·보완·충돌·반영 대기·실패)는 "답이 전달됐어요" + 해당 상태 안내. 반영 상태는 폴링으로 갱신하되 화면이 작업 수명을 소유하지 않는다
- 완료 기준: 로컬 데모 매장에서 질문 → ESCALATE → 점주 답변 → 직원 화면 도착까지 브라우저로 한 바퀴, `web-async-state-check`·`ui-state-walkthrough` 통과

### P2 점주 등록

- `/login`: 이메일 로그인/가입(카카오는 U7 다른 작업). 로그인 후 §9-1 진입 우선순위
- `/owner/setup`: 매장 이름 하나 → `createStore`. 기본 카테고리는 서버 기본값 사용(없으면 백엔드 확인 후 P2 상세 계획에서 결정)
- `/owner/add`: 텍스트 붙여넣기 + 말하기(녹음, `MediaRecorder`)·찍기(카메라 `capture`)·파일. 찍기·파일은 기존 `upload-url → Storage PUT → sources → jobs` 경로를 쓴다. 글 전송은 capabilities 에 TEXT 가 생기면 켜지고(U6-1), 말하기는 숨긴다(U6-2). `/ingest/capabilities` 로 허용 형식 결정. 전송 → `202 job_id` 받으면 처리 중 화면으로
- `/owner/jobs/[jobId]`: 처리 중(§28 문구, 다른 화면 가도 계속) → 결과 "이렇게 나눴어요". 카테고리별 그룹, `NEEDS_REVIEW` 는 상단 분리. "맞아요" = 보이는 확인 대상 카드 승인(카드별 성공·실패 표시), "더 넣기" = `/owner/add`. `PARTIAL/NO_RESULT/FAILED` 분기
- `/owner/invite`: 초대 링크는 다른 작업(U7) 범위다. 지금 있는 초대 수단(`createInvite`)이 남아 있으면 그것을 보여주고, 없어졌으면 "나중에"로 넘어가는 화면만 둔다
- 완료 기준: 신규 점주가 가입 → 매장 이름 → 자료 넣기 → 처리 → 승인까지 브라우저로 통과, 실패 분기 3종 확인

### P3 카드 관리

- `/owner/cards`: 검색, 카테고리 그룹, 상태 칩(확인 필요·바뀌었어요·제외됨), 커서 더 보기
- `/owner/cards/[cardId]`: 사실 목록(절차 순서 번호), 출처 줄(`출처 · 자료 · 날짜 · 알바 질문 N번 받음` 은 실제 count만), `인용 끊김`, 고치기(사실 추가·수정·삭제·순서 변경 → 초안 → 재승인), 지우기 = **제외**(복원 가능, 확인 시트)
- 사실 단위 편집 API는 10-05 결정의 W3 범위다. P3 시작 시 `main` 에 들어온 API를 확인하고, 없으면 기존 draft 편집으로 연결하고 사실 편집 UI는 P3 상세 계획에서 분리한다
- 카테고리 관리, 지식 제안(`SUPPLEMENT/CONFLICT`) 검토, `/owner/settings`(내 계정·매장·알림·직원 관리·근무조·도움·로그아웃). Figma의 "언어" 항목은 기능이 없어 넣지 않는다
- 완료 기준: 목록 0·1·30개, 긴 한글, 편집 저장 실패 시 입력 보존 확인

### P4 직원 레시피

- `/staff/recipes`: `/learn/roadmap` 의 단계(카테고리)·항목(승인 카드)을 그룹 목록으로. 검색은 클라이언트 필터. `RECONFIRM_REQUIRED` = "바뀌었어요" 칩. 승인 카드 0건이면 §28 로드맵 빈 상태
- `/staff/recipes/[itemId]`: 공개 카드 본문, 변경 안내, "확인했어요" 완료 저장(성공 후에만 확정), 하단 "이 레시피에 대해 물어보기" → 카드 문맥으로 `/staff/chat`
- FAQ: 채팅 첫 화면 추천 질문으로
- 완료 기준: 카드 공개 버전 변경 → 직원 화면에 "바뀌었어요" → 확인 후 해제까지 확인

### P5 근무조 체크리스트 (백엔드 포함)

상세 계획 첫 Task가 설계 확정이다. 아래는 초안이며 P5 상세 계획에서 검토 후 MVP·TODO에 반영한다.

- 근무조 `store_shifts(store_id, shift_id, name, starts_at_local time, ends_at_local time, sort_order, archived_at)` — 점주가 자유롭게 추가·이름 변경·시간 변경·삭제(보관)·순서 변경. 0개 허용
- 체크리스트 원천 = **승인 카드**. 카테고리에 `kind`(`GENERAL`/`CHECKLIST`)를 두고 `CHECKLIST` 카테고리의 공개 카드의 사실(절차 순서)을 체크 항목으로 쓴다. 카드↔근무조 지정 `checklist_card_shifts(store_id, card_id, shift_id)`. 지정 없는 체크리스트 카드는 "전체"에 표시
- 일일 체크 `checklist_checks(store_id, business_date, card_id, card_version_id, fact_key, checked_by, checked_at, unchecked_at)` — **매장 단위**(누가 했는지는 점주 화면에 노출하지 않음, Figma 규칙). 공개 버전이 바뀌면 그날 체크를 새 버전 기준으로 다시 계산
- 근무조 완료 `shift_completions(store_id, business_date, shift_id, completed_by, completed_at)` — 직원 "다 했어요"
- `business_date` 는 매장 시간대로 계산한다. `stores.timezone` (기본 `Asia/Seoul`) 추가. 자정을 넘는 근무조(예: 18:00~02:00)는 시작일에 귀속
- API(직원·점주 JWT, `store_id` 는 JWT에서): `GET/POST/PATCH/DELETE /checklist/shifts`, `PUT /checklist/cards/{card_id}/shifts`, `GET /checklist/today`, `POST /checklist/checks`(멱등), `DELETE /checklist/checks/{...}`, `POST /checklist/shifts/{shift_id}/complete`, 점주 `GET /checklist/status`
- 화면: 직원 `/staff`(현재 근무조 칩·남은 개수·실제 count 진행 막대·체크·"다 했어요" → 완료 화면), 점주 `/owner` 상단 영업 현황 카드(근무조별 진행, 마감 후 "마감 끝났어요·체크리스트 N개·끝난 시각"), 설정 근무조 편집, 카드 상세 근무조 지정
- 완료 기준: `store-isolation-check` 통과, API 단위 테스트(다른 매장 404, 멱등 체크, 버전 변경, 자정 넘김 근무조, 근무조 0개), 브라우저로 직원 체크 → 점주 현황 반영
- 충돌 주의: migration 번호는 시작 시점의 `supabase/migrations/` 최신 다음으로 잡고, 머지 전 `main` 과 다시 맞춘다

### P6 합류 — 범위 밖 (U7)

다른 작업에서 진행한다. 이 브랜치는 `/login` 에 카카오 버튼 자리를 만들지 않고, 그 작업이 P0의 `Button`(kakao 변형 포함)·`Sheet`·`Screen` 을 가져다 쓸 수 있게만 둔다.

### P7 통합 검증·문서

- `pnpm check`, 모든 새 라우트 `ui-state-walkthrough`, 360×800 확인
- 옛 라우트 redirect와 알림 딥링크 확인
- `ASKBUDDY_MVP_CURRENT.md` §8·§9·§24·§28·§29 + 체크리스트 신규 절, `DEV_TODO_CURRENT.md` 갱신
- Figma에 없던 추가 화면 스크린샷 목록을 디자이너 확인용으로 정리

## 5. 파일 구조 (계획)

```text
web/app/
  login/page.tsx                    P2 (카카오는 다른 작업)
  owner/page.tsx                    P1 오늘 매장 (P5에서 현황 카드)
  owner/setup/page.tsx              P2
  owner/add/page.tsx                P2
  owner/jobs/[jobId]/page.tsx       P2 (기존 파일 교체)
  owner/invite/page.tsx             P2 (기존 초대 수단 안내만)
  owner/questions/[pendingId]/page.tsx  P1
  owner/cards/page.tsx, [cardId]/page.tsx  P3 (교체)
  owner/settings/...                P3, P5(근무조)
  staff/page.tsx                    P5 오늘 할 일 (P5 전에는 /staff/recipes 로 redirect)
  staff/recipes/page.tsx, [itemId]/page.tsx  P4
  staff/chat/page.tsx               P1 (v2 내용으로 교체)
web/components/ui/                  P0 공통 컴포넌트(파일당 하나)
web/components/owner/, staff/       화면 조각
web/lib/checklist-api.ts            P5
api/app/checklist/                  P5 (router.py, service.py, models.py)
supabase/migrations/<next>_checklist.sql  P5
api/tests/test_checklist_*.py       P5
```

## 6. 병렬 작업 규칙

- 이 worktree는 `web/`, `api/app/checklist/`, 체크리스트 migration, 이 계획 문서만 새로 만든다. 메인 폴더 브랜치(`w/extraction-diagnosis`)가 고치는 `api/scripts/`, 추출·카드 백엔드는 건드리지 않는다
- 공통 파일(`api/app/main.py` 라우터 등록, `web/lib/types.ts`, `web/lib/query.ts`)은 변경을 작게 유지하고 머지 직전에 `main` 과 다시 맞춘다
- 로컬 실행: API·DB는 하나만 띄운다. P5 전에는 메인 폴더 API(8000)를 공유하고 이 worktree의 web만 `pnpm dev --port 3001` 로 띄운다. P5부터는 이 worktree의 API를 띄우며, 메인 폴더 API와 동시에 쓰지 않는다
- 커밋은 사용자 요청 시에만

## 7. Review Focus

- **옛 라우트·알림 딥링크**: `/owner/questions`, `/owner/upload`, `/staff/roadmap`, `/staff/items/[id]` 링크를 열면 새 화면의 같은 대상으로 가야 한다 → P1·P2·P4 각 상세 계획에 redirect 확인 단계를 넣는다
- **ESCALATE 저장 실패**: 저장이 실패했는데 "확인 중이에요"가 뜨면 안 된다 → P1 상세 계획에 네트워크 차단 확인 단계를 넣는다
- **"맞아요" 일부 실패**: 여러 카드 승인 중 일부만 실패하면 성공한 카드는 승인, 실패한 카드는 그 자리에 오류·재시도 → P2
- **자정 넘는 근무조·근무조 0개·체크 중 카드 버전 변경** → P5 API 테스트
- **360px 폭·긴 한글 카드 제목·질문 30개** 에서 줄바꿈·잘림 → P7, 각 Phase 브라우저 확인

## 8. 후속 작업 — 이 브랜치 밖 (U6-1~3)

화면 쪽 자리는 이 브랜치에서 만들어 두고, 서버 계약이 생기면 연결한다.

### F1. 글 붙여넣기 입력 (TEXT 자료 유형) — 병렬 멀티모달 작업

- 현재 `source_type` 은 `VOICE·VIDEO·KAKAO·SCAN` 뿐이다. `KAKAO` txt 는 카톡 내보내기 형식(시간·이름 줄)만 파싱해서, 일반 글을 올리면 메시지 0건으로 빈 결과가 된다 (`api/app/ingest/preprocess/kakao.py` `parse`)
- 필요한 것: `TEXT` 유형(원문 그대로 추출 입력), `/ingest/capabilities` 에 `TEXT` 노출(최대 글자 수 포함), 업로드 경로(서명 URL로 `.txt` 를 올리든 본문으로 받든 계약에 명시)
- 프론트 연결 지점: `web/lib/ingest-submit.ts` 의 `submitIngest` — capabilities 에 `TEXT` 가 생기면 글 전송이 자동으로 켜진다

### F2. 브라우저 녹음 형식 — 미정

- 브라우저 `MediaRecorder` 기본 형식: Chrome·Android `audio/webm;codecs=opus`, iOS Safari `audio/mp4`(m4a)
- 서버 `VOICE` 허용 형식: `mp3·m4a·wav` (`api/app/ingest/capabilities.py`) → Chrome 녹음은 그대로 못 올린다
- 선택지: (a) 서버가 webm/ogg 를 받아 ffmpeg 로 변환 (b) 프론트가 Web Audio 로 wav 인코딩(파일이 커짐)
- 결정 전까지 O3·O6 입력창과 직원 질문창의 말하기 버튼은 숨긴다

### F3. 점주 답변 첨부 (O7 말하기·찍기·파일) — 계약·백엔드 없음

- 현재 `POST /learn/v2/pending/{id}/answers` 는 `{request_id, answer, expected_revision}` 텍스트만 받는다
- 결정 배경: 10-05 결정 "점주 답변은 텍스트 파일로 정리하여 원본자료로 사용"과 저장 방식이 맞물린다. 첨부가 원본자료(sources)가 되는지, 답변 revision 에 붙는지, 직원에게 원문 전달 시 무엇을 보여주는지 정해야 한다
- 필요한 것: (1) 답변에 첨부를 붙이는 계약(서명 URL 업로드 → 답변 요청에 source 참조), (2) 음성 첨부는 전사 텍스트를 답변 원문으로 쓸지 여부, (3) 사진·파일 첨부의 직원 전달·인용 표시, (4) 지식 반영(ApplyOwnerAnswer)이 첨부를 근거로 쓰는 범위 — W/R 경계(MVP §30: 원문·전달은 R, 반영은 W)
- 프론트 연결 지점: `web/app/owner/questions/[pendingId]/page.tsx` 의 `Composer` — `tools` 자리에 `ComposerTool` 3개를 넣고 첨부 목록을 `attachments` 로 넘긴다
