# 화면 개선 밀린 일 모음

계획 1~5를 하는 동안 검토에서 나왔지만 바로 고치지 않은 것들을 여기 모은다. **계획 5까지 끝낸 뒤 한 번에 처리한다**(2026-11-06 사용자 결정).
계획마다 끝날 때 이 문서에 이어 적는다. 고친 항목은 지우지 말고 `[x]` 로 표시하고 어디서 고쳤는지 적는다.

## 확인이 필요한 것 (결정 또는 다른 담당과 맞출 것)

- [ ] **카드 되돌리기가 '검수 필요'를 지운다** (계획 2) — 서버 `POST /cards/{id}/restore` 는 공개 전 카드를 늘 `PENDING` 으로 되돌린다(`api/app/cards/router.py`). 검수 화면은 빼기 전 상태를 기억해 그 화면 안에서는 공개를 막지만, 화면을 나갔다 오면 되돌린 카드는 '공개 전'으로 보이고 이유도 사라진다. 서버가 빼기 전 상태(`NEEDS_REVIEW`)와 이유로 되돌려야 완전히 막힌다. W 담당 서버 수정.
- [ ] **질문 알림 함수의 안 쓰는 인자** (계획 1) — `api/app/notifications/service.py` 의 `create_pending_question_notification(..., contract_version=...)` 는 이제 목적지를 만들 때 이 값을 쓰지 않는다. 호출하는 쪽이 아직 넘기고 있어 남겨 뒀다. R 담당과 맞춰 지운다.
- [ ] **이번 계획과 상관없이 실패하는 브라우저 스크립트 3개** (계획 1에서 확인, CI 밖)
  - `api/scripts/verify_wb_answer_attach_ui.cjs` — 옛 v1 질문 API(`/learn/pending`)를 흉내 내는데 사장님 질문 화면은 v2 를 쓴다. 고치거나 지운다.
  - `api/scripts/verify_wb_extract_anyway_ui.cjs` — 3014 포트 서버가 따로 필요하다. 공용 실행기(`ui_harness.cjs`)로 옮길지 정한다.
  - `api/scripts/verify_p7_ui.cjs` — `P7_FIXTURE_FILE` 이 있어야 돈다.
- [ ] **개발용 키트의 예시 매장 이름 "더카페 논현점"** (계획 1) — `web/app/dev/kit/page.tsx`. 실제 평가용 매장 이름이면 CLAUDE.md 규칙 위반이다. 확인 뒤 가상 이름으로 바꾼다.

## 미룬 작은 지적

### 공통 키트 (계획 1·2)
- [ ] **확인 창이 Esc 두 번에 어긋날 수 있다** — `web/components/kit/feedback.tsx` `ConfirmDialog`. 크롬이 사용자 동작 없는 두 번째 Esc 를 그냥 닫으면 `open` 값과 화면이 어긋난다. `onClose={() => { if (open) onCancel(); }}` 추가, `aria-label` 대신 `aria-labelledby`·`aria-describedby` 로 설명도 읽히게.
- [ ] **스낵바 5초가 손대도 멈추지 않는다** — `feedback.tsx`. 마우스를 올리거나 포커스하면 시간을 멈춘다(WCAG 2.2.1).
- [ ] **중간점 검사가 `·`·`&middot;` 표기는 못 잡는다** — `web/scripts/check-copy.mjs`. 노드의 실제 값(`node.text`)과 JSX 엔티티도 본다.
- [ ] **차례 등장이 순서 번호를 키로 쓴다** — `web/components/kit/stagger.tsx`. 카드가 빠지면 다음 카드가 그 자리를 이어받아 새로 들어온 것도 등장 효과가 없다. 자식의 `key` 를 쓴다.

### 옛 주소 (계획 1)
- [ ] `web/components/owner/background-job-status.tsx` 가 아직 `/owner/cards/review?job_id=` 로 보낸다(리다이렉트 한 번 더). 새 주소로.
- [ ] `web/app/join/[token]/join-client.tsx` 가 이미 합류한 직원을 `/staff/roadmap` 으로 보낸다. 합류 승인 알림은 `/staff` 로 가므로 맞춘다.
- [ ] `web/app/staff/roadmap/page.tsx` 주석이 옛 설명이다(`return_to` 는 이제 `/staff/recipes`).

### 문구 (계획 1)
- [ ] "근거 보기 N" → "근거 N개 보기" 같이 자연스럽게.
- [ ] "하지 않음 켜짐 / 꺼짐"(사실 고치기 시트)이 기계적으로 읽힌다.

### 넣기 (계획 2)
- [ ] **예시 칩으로 글을 바꿔도 중복 전송 방지 키가 안 바뀐다** — `owner-add-screen.tsx` 가 부모 `setText` 를 불러 입력창 쪽 `idempotencyKey` 가 그대로다. 작업 만들기가 실패한 뒤 예시를 골라 다시 보내면 옛 키로 다른 자료를 보낸다. 제어형 글이 바뀔 때도 키를 새로.
- [ ] **"이미 올린 자료" 실패에도 '다시'가 뜬다** — `owner-add-composer.tsx` `FileRow`. 성공할 수 없는데 누를 때마다 같은 파일을 Storage 에 다시 올린다(버려진 파일, 저장 비용). 중복이면 '빼기'만.
- [ ] **일부 파일만 실패했을 때 안내가 2초뿐이다** — 작업 화면으로 넘어가며 띄우는 토스트. 더 길게 또는 스낵바로.
- [ ] **업로드에 시간 제한·취소가 없다** — `web/lib/api.ts` `putToStorage`. 멈춘 업로드면 입력창이 계속 막힌다. `ontimeout`·`onabort`, 화면을 떠나면 중단.

### 정리 중·검수 (계획 2)
- [ ] **오늘 매장 "정리 끝!" 배너** — `finished-job-banner.tsx`
  - 작업 하나를 고르려고 카드를 최대 100장 받는다. 가벼운 조회(작업 목록 기반 등)로.
  - 검수 필요 카드만 남은 작업은 배너가 안 뜬다.
  - 오래된 작업에도 "정리 끝!"이 계속 뜬다. 오래된 건 "검수할 카드가 있어요" 같은 문구로.
- [ ] **검수 완료 일부 실패 안내가 버튼 근처에 없다** — 실패 글은 카드 위에만 있어 스크롤 밖이면 안 보인다. 하단에 짧은 안내.
- [ ] **스크린리더에 '빼기'가 두 번 읽힌다** — 확인 필요 카드의 밀기 버튼과 보이는 버튼.
- [ ] **안 쓰는 속성** — `ResultReview` 의 `retrying`.
- [ ] **테스트 빈 곳** — 실제 카드를 포인터로 미는 테스트, 일부 파일만 올라간 경우, '연달아 빼기'에서 앞 카드가 화면에서 사라졌는지 단언.
