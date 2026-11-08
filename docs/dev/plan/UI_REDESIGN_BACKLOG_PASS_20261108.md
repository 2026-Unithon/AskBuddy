# 화면 개선 밀린 일 일괄 처리 (묶음 A)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** `UI_REDESIGN_BACKLOG_20261106.md` 미처리 항목 가운데 화면만으로(또는 작은 서버 버그 수정으로) 닫히는 것을 한 번에 고친다.

**Architecture:** 고칠 때마다 먼저 실패하는 검사를 쓴다. 화면은 합성 API 브라우저 검사 묶음 `api/scripts/verify_ui_backlog.cjs`(새로 만듦, `ui_harness.cjs` 사용), 순수 함수는 `web/tests/*.test.mjs`(node --test), 서버는 pytest.

**Spec:** `docs/dev/plan/UI_REDESIGN_BACKLOG_20261106.md`, `docs/dev/plan/UI_REDESIGN_SPEC_20261106.md`

## Global Constraints

- 화면 글에 중간점(·) 금지, 회색 설명 글 추가 금지, 근거 없는 % 금지. `eslint-disable` 금지.
- 서버 데이터는 Query 로만. mutation 성공 뒤 invalidate.
- 실데이터·운영 DB 금지. 합성 fixture(`api/scripts/ui_fixture.cjs`)만.
- 평가용 실자료 상호·메뉴 이름 금지.
- 커밋하지 않는다(사용자가 한다).

## 묶음 나누기

| 묶음 | 내용 | 이번에 |
|---|---|---|
| A | 화면만, 또는 작은 서버 버그(되돌리기 상태) | **이 계획** |
| B | 새 서버 API 가 먼저인 기능(W 담당): 공개 내리기, 수정 되돌리기, 검수 필요→미공개, 충돌 값 고르기, 질문 목록 물어본 횟수, 제안 대상 카드 상태, 카테고리 종류·순서·이름, 설정 이름 고치기, 합류 승인 취소 | 다음 계획 |
| C | 사용자 결정 필요 | 보고에서 묻는다 |
| 보류 | 새 화면(o01b 근무조별 현황), 탭바 레이아웃 이동(알약 미끄러짐), 옛 화면 키트화(`/staff/pending`·`/join`·`/auth/role`·`/staff/chat`), R 담당과 맞출 안 쓰는 인자 | 범위 밖, 문서에 남김 |

## Review Focus

1. 예시 칩으로 글을 바꾼 뒤 재전송: 다른 Idempotency-Key 여야 한다(같은 글이면 같은 키).
2. 업로드가 멈추면 시간 제한 뒤 실패 줄과 '다시'가 떠야 하고 입력창이 풀려야 한다.
3. 공개 전 '검수 필요' 카드를 빼고 되돌리면 서버가 `NEEDS_REVIEW` 로 돌려야 한다(이유 칸은 지우지 않는다).
4. 스낵바에 손을 올리면 닫히지 않는다.
5. 차례 등장: 목록에서 하나가 빠져도 남은 줄은 다시 등장 효과를 받지 않는다.

---

### Task 1: 서버 되돌리기가 빼기 전 상태로 (`api/app/cards/router.py`, `repository.py`)

- 테스트 `api/tests/test_w_approve_route.py`
  - `test_restore_of_unpublished_needs_review_card_returns_to_needs_review`: `repo.last_exclude_from_status` 가 `"NEEDS_REVIEW"` 를 주면 update 인자 `target == "NEEDS_REVIEW"`, 재발행 없음.
  - `test_restore_of_unpublished_pending_card_returns_to_pending`: 이전 상태가 `"PENDING"`·`None` 이면 `"PENDING"`.
  - 공개 포인터가 있으면 기존대로 `APPROVED`.
- 구현: `repository.last_exclude_from_status(conn, store_id, card_id) -> str | None`(`card_review_events` 에서 `action='EXCLUDE'` 마지막 `from_status`, `store_id` 조건 필수).

### Task 2: 공통 키트 (`web/components/kit/feedback.tsx`, `stagger.tsx`, `web/scripts/check-copy.mjs`)

- `web/tests/check-copy.test.mjs` `엔티티와 이스케이프 중간점도 찾는다`: `<p>근거 &middot; 1</p>`, `"근거 · 1"`, `<p>a &#183; b</p>` → 줄 1·2·3.
- 브라우저(`/dev/kit`, `NEXT_PUBLIC_DEV_KIT=1`):
  - `KIT-1 스낵바에 손을 올리면 닫히지 않는다`: 스낵바 띄움 → hover → 6초 뒤에도 보임 → 손 뗀 뒤 5초 안에 닫힘.
  - `KIT-2 확인 창은 제목과 설명을 읽는다`: dialog `aria-labelledby` 가 h2, `aria-describedby` 가 설명.
  - `KIT-3 차례 등장은 자식 key 를 쓴다`: 키트 페이지 목록에서 첫 줄을 빼면 남은 줄의 `animationName` 요소가 그대로(같은 DOM 노드) 남는다.
- 구현: 스낵바 `onPointerEnter/onFocus` 에서 타이머 멈춤, `onPointerLeave/onBlur` 에서 남은 시간 다시. dialog `onClose` 에서 `open` 이면 `onCancel`. `Stagger` 는 `isValidElement(child) && child.key` 를 키로.

### Task 3: 옛 주소·안 쓰는 파일·이름

- 지움: `components/r-v2-owner-questions.tsx`, `components/owner/{task-card-detail,upload-file-picker,upload-queue-item,background-refresh-indicator,knowledge-card-list-item,empty-state,background-job-status,skeleton-list,answer-question-sheet,pending-question-card,inline-error,status-badge}.tsx`, `app/owner/category/`. 지우기 전 이름으로 아무 데서도 안 부르는지 grep 으로 확인(완료).
- `join-client.tsx` 이미 합류 → `/staff`. 로드맵 주석 고침. 키트 예시 매장 이름 → "버디 카페 1호점".
- 확인: `pnpm check`(빌드·타입·lint).

### Task 4: 문구

- "근거 보기 N" 은 코드에 더 없다(이미 사라짐) → 문서 표시만.
- 사실 고치기 시트 하지 않음 버튼 → 스위치 줄 "하지 않는 일이에요"(`role="switch"`, `aria-checked`). 검사 `COPY-1`: 시트에서 스위치를 누르면 `aria-checked=true`, "켜짐"·"꺼짐" 글 없음.

### Task 5: 넣기

- `INTAKE-1 예시 칩으로 글이 바뀌면 다른 키로 보낸다`: 작업 만들기 1회 실패(`failJobCreate`) → 예시 '공지' → 보내기 → 두 POST `/ingest/jobs` 의 `Idempotency-Key` 가 다르다. 같은 글로 바로 다시 보내면 같다.
- `INTAKE-2 이미 올린 자료면 '다시' 대신 빼기만`: fixture `duplicateSource` → 실패 줄에 '다시' 없음, `빼기` 있음.
- `INTAKE-3 일부 실패 안내는 다음 화면에서 5초 남는다`: 한 파일 실패 → 작업 화면에서 3초 뒤에도 안내 보임.
- `INTAKE-4 업로드가 멈추면 시간 제한 뒤 실패`: fixture `stallUpload` → `UPLOAD_TIMEOUT_MS`(테스트용 짧은 값은 `window.__uploadTimeoutMs`) 뒤 실패 줄과 '다시'.
- 구현: 키는 보낼 때 입력 서명(글, 파일 id, 칩)으로 정한다(같은 서명 → 같은 키). `putToStorage(url, file, onProgress, { timeoutMs, signal })`, 화면을 떠나면 abort. toast `durationMs` 옵션.

### Task 6: 정리 중·검수

- `JOB-1 검수 필요만 남은 작업도 '정리 끝' 배너`: pending 0, needs_review 1 → 배너 보임.
- `JOB-2 오래된 작업이면 '검수할 카드가 있어요'`: completed_at 이 하루 넘음 → 문구 바뀜.
- 배너 조회: `cardsQuery(..., { status: "needs_review"/"pending", limit: 1 })` 두 개(각 1장)로 가볍게, 작업 id 는 그 카드의 `job_id`.
- `JOB-3 검수 완료 일부 실패 안내가 버튼 위에`: 하단 버튼 바로 위 `role=alert`.
- `JOB-4 '빼기'는 한 번만 읽힌다`: 확인 필요 카드의 밀기 판 버튼은 `aria-hidden`/`tabIndex=-1`(보이는 버튼이 있을 때).
- `ResultReview.retrying` 제거(타입 검사).

### Task 7: 카드

- `CARD-1 상세 삭제 되돌리기 실패면 스낵바 '다시'`.
- `CARD-2 타일을 누르면 상세를 미리 받는다`: 누르는 순간(pointerdown) `/cards/{id}` 요청.
- `CARD-3 손잡이 이름은 순서와 문장 전체`: `aria-label` = `"{n}번 {문장} 순서 바꾸기"`, 카테고리 칩 "카테고리 바꾸기".
- `CARD-4 다른 답 있음은 이름표에 들어간다`.
- `CARD-5 만든 제안 타일은 필터를 따른다`(공개 전 필터에서 '공개' 제안 타일 없음).
- `fact-values.test.mjs`: "2번째 컵에 시럽 2펌프", value 2 unit 펌프 → 굵게는 두 번째 2. 단위 없는 값 2 와 "12시" → 굵게 없음.
- `CARD-6 수정 중 뒤로 버튼은 버릴지 묻는다`.
- `diff-words.test.mjs`: 공백은 바뀐 것으로 치지 않는다.
- `CARD-7 제안을 닫으면 목록으로`, 버튼 이름 "이 답은 쓰지 않기".
- `CARD-8 근무조 스위치 묶음 이름`.
- `CARD-9 공개 밀기 연타는 한 번만 보낸다`.

### Task 8: 오늘 매장·질문

- `Q-1 다음 질문으로 가면 새 입력창`(답 보낸 뒤 '다음 질문' → 앞 질문 글이 안 비침, 입력창 빈 칸).
- `Q-2 첨부 칩 이름은 '다음에 붙일 파일'`.
- `Q-3 하나뿐인 질문을 미루면 토스트`, '나중에' 버튼 이름에 질문 글.
- `Q-4 세그먼트는 aria-pressed 버튼`, 뱃지는 "검수 필요 2" 로 읽힘.
- `Q-5 '물어본 말 보기' 포커스 테두리`.
- 탭 알약: 활성 탭이 없으면 숨김(`TAB-1`).

### Task 9: 설정·관리

- `SET-1 근무조 시간 오류는 값을 바꾸면 사라진다`.
- `SET-2 직원 알림을 읽으면 설정 뱃지도 준다`(R 알림 읽음 뒤 `notifications` 키도 무효화).
- `SET-3 시간 휠은 aria-activedescendant`.
- `SET-4 안 읽은 알림이 없으면 코치마크를 '봤음'으로 저장하지 않는다`.
- `SET-5 카테고리 같은 이름은 대소문자 무시`.
- `SET-6 알림 밀어서 읽음 실패는 '읽지 않음' 점이 바로 돌아온다`.

### Task 10: 직원 화면

- `STAFF-1 이전 대화 불러오기는 타이핑하지 않는다`.
- `STAFF-2 타이핑 글은 aria-hidden, 전체는 sr-only 하나`.
- `STAFF-3 밀기 판은 놓은 뒤 이동이 끝날 때까지 남는다`(transitionend 전 opacity 1).
- `STAFF-4 레시피 시트 닫히는 동안 제목 유지`.
- `STAFF-5 제출 실패 뒤 다시 열면 옛 오류 없음`.
- `STAFF-6 세션 없는 v1 알림은 /staff/ask 로`.
- `STAFF-7 읽은 알림은 흐리게 하지 않고 점만 뺀다`(본문 대비 유지).
- `STAFF-8 추천 칩은 같은 질문 한 번`.
- `STAFF-9 작업 중 배너가 있으면 '정리 끝' 배너는 숨긴다`.
- ui-nav 보조 키 클릭 대기 10초로.

### Task 11: 옛 브라우저 스크립트 3개

- `verify_wb_answer_attach_ui.cjs`: v1 질문 API 흉내라 사장님 질문 화면(v2)과 안 맞는다. 같은 범위를 `verify_ui_today.cjs` 가 덮는지 확인 뒤 지운다.
- `verify_wb_extract_anyway_ui.cjs`, `verify_p7_ui.cjs`: 전용 서버·파일이 필요해 남기고 머리 주석에 실행 조건을 적는다.

## 검증

- `cd api && .venv/bin/pytest -q` 전부.
- `cd web && node --test tests/` 전부, `pnpm check`.
- 브라우저 묶음 전부(nav·intake·cards·today·manage·staff·backlog) + 옛 스크립트(`OLD=1`).
- 매장 격리 정적 검사(`check_store_id.py api/app/cards`) 변경 전과 비교.
