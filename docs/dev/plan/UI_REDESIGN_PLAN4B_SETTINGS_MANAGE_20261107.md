# 화면 개선 계획 4b: 설정·관리 화면, 옛 디자인 통일 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 사장님 설정(o12), 알바생 기록(o13), 근무조(o14), 직원 관리·초대·직원 담당(o15·o16), 카테고리(o17), 알림(o18), 첫 준비 끝(o19)을 사용자 결정대로 바꾸고, 아직 옛 `components/ui` 로 그리던 직원 관리·카테고리·알림을 새 키트로 옮긴다(G5).

**Architecture:** 화면마다 지금 쓰는 서버 API 를 그대로 쓰고 모양·피드백·몸짓만 바꾼다. 키트에 시간 휠(`TimeWheel`)을 더하고, 카드 수정에서 쓰던 끌어서 순서 바꾸기(`SortableList`)를 키트로 옮겨 근무조가 같이 쓴다. `SwipeAction` 에 스크린리더용 이름(`ariaLabel`)을, `Button` 에 모양 표시(`data-variant`)를 더한다. **서버 API·DB 는 바꾸지 않는다.**

**Tech Stack:** Next.js 16 App Router, React 19, Tailwind 4, TanStack Query 5, Playwright 1.62(합성 API).

**Spec:** `docs/dev/plan/UI_REDESIGN_SPEC_20261106.md` (o12a~o19a, G5)

## Global Constraints

- 계획 1~4a 제약 전부(중간점 금지, 모션 토큰, 피드백 기준 G4, 합성 API, 서버 무변경, 진행률 % 금지, `eslint-disable` 금지).
- 설명용 회색 문구는 지운다: 설정 줄 부제, "여러 근무조를 고를 수 있어요…", "공통 + 담당 근무조 할 일을 봐요", "카테고리를 바꾸면 자동 분류 카드만…", "필수 시스템 카테고리/사용자 카테고리", "허용하지 않아도 아래 앱 알림은…", "점주가 알바생 달력을 볼지…", 근무조 고치기 시트 설명.
- `SettingsScreen` 은 직원도 쓴다(s07a = o12a). 직원 줄은 '내 기록'·'답변 알림' 그대로, 직원 '내 기록 남기기' 스위치는 그대로 둔다(o13c 는 사장님 화면만).
- 서버가 있어야 하는 것은 만들지 않고 백로그에 적는다:
  - o12a 연필로 이름·매장 이름 고치기(수정 API 없음). 연필은 그리지 않는다(누를 수 없는 버튼 금지).
  - o15b 승인 스낵바의 '되돌리기'(승인 응답에 user_id 가 없고 승인 취소 API 없음). 승인은 토스트.
  - o17 카테고리 끌어서 순서(순서·이름 수정 API 없음).
- 브라우저 저장소는 사용자 편의에만: 알림 켜기 배너 '나중에'(`askbuddy:push-banner` = `"later"`), 코치마크(`askbuddy:coach:owner-notifications`).

## Review Focus

1. **직원 담당 체크를 빠르게 두 번 누름(두 근무조 연달아)**: 두 번째가 첫 번째 저장 결과를 덮어쓰지 않아야 한다(낙관 반영은 최신 화면 값 기준) → Task 2 `o16a 연달아 두 개 고르면 둘 다 저장된다`.
2. **근무조 시간 휠에서 시작=끝**: 저장하지 않고 칸 아래 빨간 글 → Task 3 `o14c 시작과 끝이 같으면 저장하지 않는다`.
3. **알바생이 한 명도 없는 매장의 알바생 기록**: 빈 상태 안내, 사장님 자기 기록으로 몰래 바꿔 보여 주지 않는다 → Task 4 `o13a 알바생이 없으면 빈 상태`.
4. **알림 밀어서 읽음 실패**: 읽음 표시를 되돌리고 오류를 보인다 → Task 6 `o18b 밀어서 읽음 실패하면 그대로`.
5. **카테고리 이름 앞뒤 공백·같은 이름**: `' 재고 위치 '` 도 같은 이름으로 본다 → Task 5 `o17 추가 칸 상태`.

---

## 파일 구조

| 파일 | 책임 |
|---|---|
| `web/components/kit/time-wheel.tsx` (새) | 시·분 두 줄 휠(스크롤 스냅 + 누르기 + 위아래 키) |
| `web/components/kit/sortable-list.tsx` (옮김) | `components/owner/fact-card/sortable-list.tsx` 를 키트로. 손잡이 이름 규칙 그대로 |
| `web/components/kit/buttons.tsx` | `Button`·`ButtonLink` 에 `data-variant` |
| `web/components/kit/swipe-row.tsx` | `SwipeAction.ariaLabel?` |
| `web/components/settings-screen.tsx` | o12a·o12b(두 역할) |
| `web/components/invite-link-card.tsx` | o15a(키트로) |
| `web/app/owner/members/page.tsx` | o15b·o15c(키트로) |
| `web/components/checklist/member-settings.tsx` | o16a |
| `web/app/owner/invite/page.tsx` | o19a |
| `web/components/checklist/settings-screen.tsx` | o14a~c |
| `web/components/checklist/records-screen.tsx` | o13a~c |
| `web/app/owner/categories/page.tsx` | o17(키트로) |
| `web/app/owner/notifications/page.tsx` | o18a·o18b(키트로) |
| `api/scripts/ui_fixture.cjs` | 관리 화면 쓰기 API(상태 있는 직원·카테고리·근무조·알림) |
| `api/scripts/ui_harness.cjs` | 코치마크 끄기 목록에 `owner-notifications` |
| `api/scripts/verify_ui_manage.cjs` (새) | 이 계획 회귀(`ui-manage`) |
| `api/scripts/verify_ui_checklist.cjs`, `verify_ui_rebrand.cjs`, `verify_ui_nav.cjs` | 바뀐 이름·몸짓에 맞춤 |

### fixture 추가(Task 1 에서 한 번에, 이후 Task 는 쓰기만)

`initialState` 에 더한다: `joinRequests: [{ request_id: 9, name: '이서연', requested_at: NOW }]`, `members: [{ user_id: 2, name: '박지호', role: 'STAFF', joined_at: NOW }, { user_id: 3, name: '김민준', role: 'STAFF', joined_at: NOW }]`, `categories: CATEGORIES.map((c) => ({ ...c }))`, `checklistMembers: [{ member_id: 2, user_id: 2, role: 'STAFF', name: '박지호', shift_ids: [1] }, { member_id: 3, user_id: 3, role: 'STAFF', name: '김민준', shift_ids: [3] }]`, `settings: { business_day_starts_at: '04:00', staff_records_visible: true, timezone: 'Asia/Seoul' }`, `pushConfigured: false`, `failMemberShifts: false`, `memberShiftDelayMs: 0`, `failRead: false`.

경로(기존 것을 상태로 바꾸거나 새로):

| 경로 | 동작 |
|---|---|
| `GET /members` | `{ pending: state.joinRequests, active: state.members }` |
| `POST /members/requests/:id/approve` | 요청 빼고 `members` 에 `{ user_id: 10 + id, name, role: 'STAFF', joined_at: NOW }` 더함, `{}` |
| `POST /members/requests/:id/reject` | 요청 빼기, `{}` |
| `POST /members/:userId/remove` | `members` 에서 빼기, `{}` |
| `POST /members/invite-link/rotate` | `{ url: 'http://127.0.0.1:3011/join/synthetic-invite-2' }` |
| `GET /categories` | `{ version: 1, reclassification: null, items: state.categories }` |
| `POST /categories` | `{ category_id: 20 + n, name: body.name, is_system: false, sort_order: body.sort_order }` 더함, `{ category, version: 2, reclass_job_id: null }` |
| `DELETE /categories/:id` | 빼기, `{ category_id, version: 2, reclass_job_id: null }` |
| `POST /notifications/:id/read` | `failRead` 면 503, 아니면 그 알림 `read_at = NOW`, `unreadCount -= 1`(이미 읽음이면 그대로) |
| `GET /notifications/support` | `push_configured: state.pushConfigured, vapid_public_key: state.pushConfigured ? 'BAAA' : null` |
| `POST /auth/logout` | `{}` |
| `GET /checklist/members` | `{ items: state.checklistMembers }` |
| `PUT /checklist/members/:id/shifts` | `memberShiftDelayMs` 기다림 → `failMemberShifts` 면 503 → 아니면 `shift_ids = body.ids`, `{}` |
| `GET/PATCH /checklist/settings` | `state.settings`(PATCH 는 body 를 합침) |
| `POST /checklist/shifts` | `{ shift_id: max+1, ...body, sort_order: n, card_ids: [] }` 더함 |
| `PATCH /checklist/shifts/:id` | body 합침(`clear_time` 이면 `starts_at`·`ends_at` null) |
| `DELETE /checklist/shifts/:id` | 빼기, 204 대신 `{}` |
| `PUT /checklist/shifts/order` | `body.shift_ids` 순서로 `state.shifts` 재배열, `{}` |
| `PUT /checklist/shifts/:id/cards` | `card_ids = body.ids`, `{}` |
| `GET /checklist/records` | `month` 쿼리 그대로, `user_id` 가 있고 `!state.settings.staff_records_visible` 면 `visible: false`. 날짜는 `${month}-10/11/12`(100/78/50) |
| `GET /checklist/records/:date` | `{ date, visible: true, submission: { done_lines: 7, total_lines: 9, late: false }, lines: [{ text: '우유 재고 확인', title: '우유 재고 확인', checked_at: NOW }] }` |

---

### Task 1: 설정(o12a·o12b), fixture, 새 묶음

**Files:** Create `api/scripts/verify_ui_manage.cjs` / Modify `api/scripts/ui_fixture.cjs`(위 표 전부), `api/scripts/ui_harness.cjs`, `web/components/settings-screen.tsx`, `web/components/kit/buttons.tsx`, `api/scripts/verify_ui_rebrand.cjs`(로그아웃 확인 창), CI `.github/workflows/r-validation.yml`, `run-ui.sh`

**Interfaces:**
- Produces: `Button`/`ButtonLink` 에 `data-variant={variant}`(뒤 Task 들이 모양 단언에 쓴다).
- `SettingsScreen({ role })`:
  - 위: `<section data-profile>` 프로필. 이름 첫 글자 원(56px, `bg-empty text-primary`), 이름(20 Bold), 매장 이름(14 `text-ink-muted`), 역할 칩(`사장님`/`알바생`).
  - 아래 `ListGroup` 줄(부제 없음). 사장님: `근무조`(/owner/shifts), `직원 관리`(/owner/members, 뱃지 = `membersQuery` 의 `pending.length`), `알바생 기록`(/owner/me), `카테고리`(/owner/categories), `알림`(/owner/notifications, 뱃지 = `notificationsQuery` 의 `unread_count`). 직원: `내 기록`(/staff/me), `답변 알림`(/staff/notifications/v2, 뱃지 = 읽지 않은 수).
  - 뱃지는 `ListRow badge={n > 0 ? <CountBadge n={n} tone="danger" /> : undefined}`.
  - 로그아웃: `TextButton` → `ConfirmDialog`(제목 `로그아웃할까요?`, 확인 `로그아웃`, 취소 `취소`, `tone="danger"`, `loading={logout.isPending}`). 실패는 지금처럼 `ErrorInline`.

- [ ] **Step 1: 테스트 작성** — `verify_ui_manage.cjs`(머리는 `verify_ui_today.cjs` 와 같은 모양, `createSuite('ui-manage')`)

```js
test('o12a 설정 위는 프로필, 아래는 관리 항목과 뱃지', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/settings');
  const profile = page.locator('[data-profile]');
  await profile.getByText('김사장', { exact: true }).waitFor();
  assert.ok(await profile.getByText('골목커피 연남점', { exact: true }).isVisible());
  for (const name of ['근무조', '직원 관리', '알바생 기록', '카테고리', '알림']) await page.getByRole('link', { name: new RegExp(`^${name}`) }).waitFor();
  assert.equal(await page.getByRole('link', { name: /^직원 관리/ }).getByText('1', { exact: true }).count(), 1);
  assert.equal(await page.getByRole('link', { name: /^알림/ }).getByText('3', { exact: true }).count(), 1);
  for (const gone of ['카드를 나누는 묶음', '내 계정', '할 일 담기, 영업일 시각']) assert.equal(await page.getByText(gone).count(), 0, gone);
  await ctx.close();
});
test('o12a 직원 설정도 같은 모양, 사장님 항목은 없다', async (b) => {
  const { page, ctx } = await open(b, 'STAFF', '/staff/settings');
  await page.locator('[data-profile]').getByText('박지호', { exact: true }).waitFor();
  await page.getByRole('link', { name: /^내 기록/ }).waitFor();
  await page.getByRole('link', { name: /^답변 알림/ }).waitFor();
  assert.equal(await page.getByRole('link', { name: /^직원 관리/ }).count(), 0);
  await ctx.close();
});
test('o12b 로그아웃은 확인 창을 거친다', async (b) => {
  const { page, ctx, api } = await open(b, 'OWNER', '/owner/settings');
  await page.getByRole('button', { name: '로그아웃' }).click();
  const dialog = page.getByRole('dialog', { name: '로그아웃할까요?' });
  await dialog.waitFor();
  await dialog.getByRole('button', { name: '취소' }).click();
  await dialog.waitFor({ state: 'hidden' });
  assert.equal(api.calls.filter((c) => c.path === '/auth/logout').length, 0);
  await page.getByRole('button', { name: '로그아웃' }).click();
  await dialog.getByRole('button', { name: '로그아웃' }).click();
  await page.waitForURL((u) => u.pathname !== '/owner/settings');
  assert.equal(api.calls.filter((c) => c.path === '/auth/logout').length, 1);
  await ctx.close();
});
```

- [ ] **Step 2: 실패 확인** — `run-ui.sh` → Expected: 3 FAIL(`[data-profile]` 없음)
- [ ] **Step 3: 구현** — Interfaces 대로. fixture 표 전부를 이 Task 에서 넣는다(뒤 Task 테스트가 쓴다). `ui_harness.cjs` 코치마크 끄기 목록에 `'owner-notifications'`. `verify_ui_rebrand.cjs` 로그아웃 단언은 확인 창 '로그아웃'을 한 번 더 누르게 고친다. CI 에 `verify_ui_manage.cjs` 추가.
- [ ] **Step 4: 통과 확인** — Expected: 3 PASS, `ui-nav 30`·`ui-intake 27`·`ui-cards 36`·`ui-today 20`, `verify_ui_rebrand` PASS

---

### Task 2: 직원 관리·초대·직원 담당·첫 준비 끝 (o15a·o15b·o15c·o16a·o19a, G5)

**Files:** Modify `web/components/invite-link-card.tsx`, `web/app/owner/members/page.tsx`, `web/components/checklist/member-settings.tsx`, `web/app/owner/invite/page.tsx`, `web/components/kit/swipe-row.tsx`, `api/scripts/verify_ui_checklist.cjs`(직원 담당 단언), `verify_ui_manage.cjs`

**Interfaces:**
- `SwipeAction = { label; tone; onAction; ariaLabel?: string }` — 드러나는 버튼의 `aria-label` 은 `ariaLabel ?? label`.
- `InviteLinkCard` — 키트 `Surface`. 제목 `초대 링크`(설명 문구 없음). 두 버튼 세로:
  - `Button variant="kakao"` 글 `카톡으로 보내기`, 왼쪽에 카카오 말풍선 마크 `<svg data-kakao-mark aria-hidden>`(검은 말풍선 하나, 18px).
  - `Button variant="secondary"` 글 `링크 복사`, 왼쪽 링크 아이콘.
  - 복사 성공 토스트 `링크를 복사했어요`, 실패 토스트 `복사하지 못했어요. 카톡으로 보내 주세요.`
  - `링크 새로 만들기` 작은 글자 → `ConfirmDialog`(제목 `새 링크를 만들까요?`, 설명 `지금 링크로는 더 이상 가입할 수 없어요.`, 확인 `새로 만들기`) → 성공 토스트 `새 링크를 만들었어요`.
- 직원 관리(`members/page.tsx`) — `Screen` + `BackButton parent="/owner/settings"` + `PageHeader title="직원 관리"`. 순서: 초대 카드, `ButtonLink variant="secondary" href="/owner/member-shifts"` 글 `직원 담당 근무조`, 합류 요청 섹션, 함께 일하는 직원 섹션.
  - 합류 요청 줄 `<li data-join-request>`: 이름, 요청 시각(KST), `Button`(primary, 작게 `w-auto px-4 min-h-10`) `승인` + `TextButton` `거절`. 승인 성공 토스트 `${name}님이 합류했어요`. 거절은 `ConfirmDialog`(제목 `${name}님 합류를 거절할까요?`, 확인 `거절`, `tone="danger"`) → 성공 토스트 `거절했어요`.
  - 직원 줄 `<li data-member>`: `SwipeRow left={{ label: '내보내기', ariaLabel: `${name} 내보내기`, tone: 'danger', onAction }}`. → `ConfirmDialog`(제목 `${name}님을 내보낼까요?`, 설명 `질문과 기록은 남아요.`, 확인 `내보내기`, danger) → 토스트 `${name}님을 내보냈어요`.
  - 빈 요청이면 합류 요청 섹션을 그리지 않는다. 직원 0명이면 `Empty title="아직 합류한 직원이 없어요"`.
- 직원 담당(`member-settings.tsx`) — `PageHeader title="직원 담당"`(설명 없음). 직원마다 `Surface data-member-shifts` 제목 이름, 그 아래 근무조마다 `CheckRow`(체크박스).
  - 낙관 반영: 누르면 `queryClient.setQueryData(checklistKeys...members)` 로 바로 바꾸고 저장. 다음 선택은 **캐시의 최신 shift_ids** 에서 계산한다(Review Focus 1). 실패하면 `onError` 로 이전 값 복원 + 그 직원 카드 아래 `ErrorInline` `이 변경은 저장되지 않았어요.`. 성공 토스트 `저장했어요`. 성공·실패 뒤 `invalidateQueries(checklistKeys.root)`.
- 첫 준비 끝(`invite/page.tsx`) — 위에 축하 원 `<div data-celebrate>`(초록 원 안 체크, `animate-[check-pop_…_var(--ease-spring)]`), 제목 `첫 준비 끝났어요`(설명 없음), `InviteLinkCard`, `ButtonLink` `직원 관리`. footer `ButtonLink variant="secondary"` `매장으로 돌아가기` 유지.

- [ ] **Step 1: 테스트 작성**

```js
test('o15a 초대: 복사는 토스트, 카톡 버튼은 카카오 모양', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/members');
  await ctx.grantPermissions(['clipboard-read', 'clipboard-write']);
  const kakao = page.getByRole('button', { name: '카톡으로 보내기' });
  await kakao.waitFor();
  assert.equal(await kakao.getAttribute('data-variant'), 'kakao');
  assert.equal(await kakao.locator('svg[data-kakao-mark]').count(), 1);
  assert.equal(await page.getByRole('button', { name: '링크 복사' }).getAttribute('data-variant'), 'secondary');
  await page.getByRole('button', { name: '링크 복사' }).click();
  await page.getByRole('status').getByText('링크를 복사했어요').waitFor();
  await page.getByRole('button', { name: '링크 새로 만들기' }).click();
  await page.getByRole('dialog', { name: '새 링크를 만들까요?' }).getByRole('button', { name: '새로 만들기' }).click();
  await page.getByRole('status').getByText('새 링크를 만들었어요').waitFor();
  assert.equal(await page.getByText('알바생에게 보내 주세요').count(), 0);
  await ctx.close();
});
test('o15b 합류 승인은 바로, 거절은 확인 창, 버튼 모양이 다르다', async (b) => {
  const { page, ctx, api } = await open(b, 'OWNER', '/owner/members');
  const row = page.locator('[data-join-request]').filter({ hasText: '이서연' });
  await row.waitFor();
  assert.equal(await row.getByRole('button', { name: '승인' }).getAttribute('data-variant'), 'primary');
  assert.equal(await row.getByRole('button', { name: '거절' }).getAttribute('data-variant'), null);
  await row.getByRole('button', { name: '거절' }).click();
  const dialog = page.getByRole('dialog', { name: '이서연님 합류를 거절할까요?' });
  await dialog.getByRole('button', { name: '취소' }).click();
  assert.equal(api.calls.filter((c) => c.path.endsWith('/reject')).length, 0);
  await row.getByRole('button', { name: '승인' }).click();
  await page.getByRole('status').getByText('이서연님이 합류했어요').waitFor();
  await row.waitFor({ state: 'detached' });
  await page.locator('[data-member]').filter({ hasText: '이서연' }).waitFor();
  await ctx.close();
});
test('o15c 밀어서 내보내기는 확인 창 뒤', async (b) => {
  const { page, ctx, api } = await open(b, 'OWNER', '/owner/members');
  const row = page.locator('[data-member]').filter({ hasText: '박지호' });
  const box = await row.boundingBox();
  await page.mouse.move(box.x + box.width - 20, box.y + box.height / 2); await page.mouse.down();
  await page.mouse.move(box.x + box.width - 140, box.y + box.height / 2, { steps: 10 }); await page.mouse.up();
  const dialog = page.getByRole('dialog', { name: '박지호님을 내보낼까요?' });
  await dialog.getByRole('button', { name: '내보내기' }).click();
  await page.getByRole('status').getByText('박지호님을 내보냈어요').waitFor();
  assert.ok(!api.state.members.some((m) => m.user_id === 2));
  await page.locator('[data-member]').filter({ hasText: '김민준' }).getByRole('button', { name: '김민준 내보내기' }).waitFor({ state: 'attached' });
  await ctx.close();
});
test('o16a 직원 담당은 체크박스, 누르면 바로 바뀌고 실패하면 되돌린다', async (b) => {
  const { page, ctx, api } = await open(b, 'OWNER', '/owner/member-shifts', { overrides: { memberShiftDelayMs: 800 } });
  const card = page.locator('[data-member-shifts]').filter({ hasText: '박지호' });
  const middle = card.getByRole('checkbox', { name: '미들' });
  await middle.click();
  assert.equal(await middle.getAttribute('aria-checked'), 'true');
  await page.getByRole('status').getByText('저장했어요').waitFor();
  assert.deepEqual(api.state.checklistMembers.find((m) => m.member_id === 2).shift_ids, [1, 2]);
  api.state.failMemberShifts = true; api.state.memberShiftDelayMs = 0;
  const open1 = card.getByRole('checkbox', { name: '오픈' });
  await open1.click();
  await card.getByText('이 변경은 저장되지 않았어요').waitFor();
  assert.equal(await open1.getAttribute('aria-checked'), 'true');
  assert.equal(await page.getByText('여러 근무조를 고를 수 있어요').count(), 0);
  await ctx.close();
});
test('o16a 연달아 두 개 고르면 둘 다 저장된다', async (b) => {
  const { page, ctx, api } = await open(b, 'OWNER', '/owner/member-shifts', { overrides: { memberShiftDelayMs: 400 } });
  const card = page.locator('[data-member-shifts]').filter({ hasText: '김민준' });
  await card.getByRole('checkbox', { name: '오픈' }).click();
  await card.getByRole('checkbox', { name: '미들' }).click();
  await page.waitForTimeout(1200);
  assert.deepEqual([...api.state.checklistMembers.find((m) => m.member_id === 3).shift_ids].sort(), [1, 2, 3]);
  await ctx.close();
});
test('o19a 첫 준비 끝: 축하 체크와 직원 관리', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/invite');
  await page.getByRole('heading', { name: '첫 준비 끝났어요' }).waitFor();
  assert.ok(await page.locator('[data-celebrate]').isVisible());
  await page.getByRole('link', { name: '직원 관리', exact: true }).waitFor();
  assert.equal(await page.getByText('합류 요청을 승인해 주세요').count(), 0);
  await ctx.close();
});
```

  연달아 누르기에서 첫 저장이 끝나기 전 두 번째를 누르면 두 번째 요청 body 가 `[3, 1, 2]` 여야 한다(캐시 최신 값 기준). 두 요청이 겹쳐 나중 것이 먼저 끝나도 마지막 요청이 전체 목록을 담으므로 서버 값은 맞다.

- [ ] **Step 2: 실패 확인** — Expected: 6 FAIL
- [ ] **Step 3: 구현** — Interfaces 대로. `verify_ui_checklist.cjs` 의 직원 담당 단언(`getByRole("button", { name: "아침", exact: true })` + `aria-pressed`)은 `getByRole("checkbox", { name: "아침" })` + `aria-checked=true` 로 고친다. 그 스크립트 자체 fixture 의 `PUT /checklist/members/:id/shifts` 는 그대로 쓴다.
- [ ] **Step 4: 통과 확인** — Expected: `ui-manage` 9 PASS, 다른 묶음·`verify_ui_checklist`·`verify_ui_rebrand` PASS

---

### Task 3: 근무조 (o14a·o14b·o14c)

**Files:** Create `web/components/kit/time-wheel.tsx` / Move `web/components/owner/fact-card/sortable-list.tsx` → `web/components/kit/sortable-list.tsx`(가져오는 곳 `fact-card-panel.tsx` 고침) / Modify `web/components/kit/index.ts`, `web/components/checklist/settings-screen.tsx`, `web/app/dev/kit/page.tsx`(`?s=forms` 에 시간 휠 하나), `api/scripts/verify_ui_checklist.cjs`(근무조 단언), `verify_ui_manage.cjs`

**Interfaces:**
- `TimeWheel({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void })` — `value` 는 `"HH:MM"`. 두 열 `role="listbox"`, 이름 `${label} 시`·`${label} 분`. 시 `00`~`23`, 분 `00`~`55` 5분 간격(지금 값의 분이 5의 배수가 아니면 그 분도 목록에 넣는다). 열 높이 132px, 칸 44px, `snap-y snap-mandatory`, 가운데 칸에 연한 띠. 칸은 `role="option" aria-selected`. 누르면 그 값으로 `onChange` + 가운데로 부드럽게 스크롤. 손으로 굴리고 멈추면(스크롤 끝 120ms) 가운데 칸으로 `onChange`. 열에 포커스하고 위·아래 키로 한 칸씩.
- `SortableList` — 위치만 옮긴다. 손잡이 이름 `${label.slice(0, 12)} 옮기기` 그대로.
- 근무조 화면(`ShiftSettingsScreen`):
  - `PageHeader title="근무조" action={<Button className="w-auto! px-4 min-h-10" onClick={…}>추가</Button>}`(설명 없음). 화면에 `근무조 추가` 글은 없다(시트 제목만 `근무조 추가`).
  - 근무조 카드들은 `SortableList`(label = 이름) 안. 카드: 이름(20 Bold), 시간 줄(`08:00 ~ 12:00`, 다음 날 끝이면 `, 다음 날 끝`, 시간 없으면 `시간 없음`), 버튼 줄 `Button variant="primary"` `할 일 담기` + `Button variant="secondary"` `고치기` + 작은 `TextButton` `지우기`(danger 색). ↑↓ 버튼은 없앤다. 순서 바뀌면 `order.mutate(ids)`, 실패 `ErrorInline` 그대로.
  - 근무조 0개: 지금 빈 상태·프리셋 버튼 그대로.
  - `직원 담당 근무조` ButtonLink(NAV-11), `카드에서 공통 할 일 담기` ButtonLink 유지.
  - 매장 설정 `Surface`: 줄 버튼 `영업일 시작` + 값(`04:00`) + › → 시트 `영업일 시작 시각`(TimeWheel label `영업일 시작` + `저장`) → 성공 토스트 `저장했어요`, 시트 닫힘. 그 아래 `Switch label="알바생 기록"`. 설명 Caption 둘 다 지운다(시간대 안내 포함).
  - 근무조 시트(`ShiftEditor`): 설명 없음. 제어형 상태 `name`, `timed`, `start`, `end`. `Switch label="시간 정하기"`(기존 근무조에 시간이 있으면 켜짐, 새 근무조는 꺼짐). 켜면 `TimeWheel label="시작"`·`TimeWheel label="끝"`(기본 `09:00`/`18:00`, 기존 값 있으면 그 값). 시작=끝이면 저장하지 않고 휠 아래 `role="alert"` `시작과 끝을 다르게 골라 주세요.`. 저장 body 는 지금 규칙(`starts_at`/`ends_at`, 기존 근무조에서 끄면 `clear_time: true`). 성공 토스트 `저장했어요`, 실패는 시트 안 `ErrorInline`(입력 유지, `verify_ui_checklist` 의 `같은 이름의 근무조가 있어요.` 그대로).
  - 지우기 시트: 설명 `과거 기록은 남아요.` 만. 성공 토스트 `지웠어요`.

- [ ] **Step 1: 테스트 작성**

```js
test('o14b 근무조 추가는 "추가" 버튼 하나, 시간 없이도 저장', async (b) => {
  const { page, ctx, api } = await open(b, 'OWNER', '/owner/shifts');
  await page.getByRole('heading', { name: '오픈', exact: true }).waitFor();
  assert.equal(await page.getByRole('button', { name: '근무조 추가' }).count(), 0);
  await page.getByRole('button', { name: '추가', exact: true }).click();
  const sheet = page.getByRole('dialog', { name: '근무조 추가' });
  await sheet.getByLabel('이름', { exact: true }).fill('야간');
  assert.equal(await sheet.getByRole('switch', { name: '시간 정하기' }).getAttribute('aria-checked'), 'false');
  await sheet.getByRole('button', { name: '저장', exact: true }).click();
  await page.getByRole('status').getByText('저장했어요').waitFor();
  const made = api.state.shifts.find((s) => s.name === '야간');
  assert.ok(made && made.starts_at == null);
  await ctx.close();
});
test('o14c 시간 휠로 고른다', async (b) => {
  const { page, ctx, api } = await open(b, 'OWNER', '/owner/shifts');
  await page.getByRole('button', { name: '고치기' }).first().click();
  const sheet = page.getByRole('dialog', { name: '근무조 고치기' });
  assert.equal(await sheet.getByRole('switch', { name: '시간 정하기' }).getAttribute('aria-checked'), 'true');
  assert.equal(await sheet.getByRole('listbox', { name: '시작 시' }).getByRole('option', { name: '08' }).getAttribute('aria-selected'), 'true');
  await sheet.getByRole('listbox', { name: '시작 시' }).getByRole('option', { name: '09' }).click();
  await sheet.getByRole('listbox', { name: '시작 분' }).getByRole('option', { name: '30' }).click();
  await sheet.getByRole('button', { name: '저장', exact: true }).click();
  await page.getByRole('status').getByText('저장했어요').waitFor();
  assert.equal(api.state.shifts.find((s) => s.shift_id === 1).starts_at, '09:30');
  await ctx.close();
});
test('o14c 시작과 끝이 같으면 저장하지 않는다', async (b) => {
  const { page, ctx, api } = await open(b, 'OWNER', '/owner/shifts');
  await page.getByRole('button', { name: '고치기' }).first().click();
  const sheet = page.getByRole('dialog', { name: '근무조 고치기' });
  await sheet.getByRole('listbox', { name: '끝 시' }).getByRole('option', { name: '08' }).click();
  await sheet.getByRole('listbox', { name: '끝 분' }).getByRole('option', { name: '00' }).click();
  await sheet.getByRole('button', { name: '저장', exact: true }).click();
  await sheet.getByRole('alert').getByText('시작과 끝을 다르게 골라 주세요.').waitFor();
  assert.equal(api.calls.filter((c) => c.method === 'PATCH' && c.path === '/checklist/shifts/1').length, 0);
  await ctx.close();
});
test('o14a 끌어서 순서, 할 일 담기는 초록 버튼', async (b) => {
  const { page, ctx, api } = await open(b, 'OWNER', '/owner/shifts');
  assert.equal(await page.getByRole('button', { name: '할 일 담기' }).first().getAttribute('data-variant'), 'primary');
  const handle = page.getByRole('button', { name: '오픈 옮기기' });
  const box = await handle.boundingBox();
  const rowHeight = await handle.evaluate((el) => el.closest('li').getBoundingClientRect().height);
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2); await page.mouse.down();
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2 + rowHeight * 0.8, { steps: 10 }); await page.mouse.up();
  await page.waitForFunction(() => document.querySelector('main h2')?.textContent === '미들');
  assert.deepEqual(api.state.shifts.map((s) => s.name), ['미들', '오픈', '마감']);
  await page.getByRole('button', { name: '마감 옮기기' }).focus();
  await page.keyboard.press('ArrowUp');
  await page.waitForFunction(() => [...document.querySelectorAll('main h2')].map((h) => h.textContent).join() === '미들,마감,오픈');
  await ctx.close();
});
test('o14 영업일 시작은 시트의 휠, 알바생 기록은 스위치', async (b) => {
  const { page, ctx, api } = await open(b, 'OWNER', '/owner/shifts');
  await page.getByRole('button', { name: /영업일 시작/ }).click();
  const sheet = page.getByRole('dialog', { name: '영업일 시작 시각' });
  await sheet.getByRole('listbox', { name: '영업일 시작 시' }).getByRole('option', { name: '05' }).click();
  await sheet.getByRole('button', { name: '저장', exact: true }).click();
  await page.getByRole('status').getByText('저장했어요').waitFor();
  assert.equal(api.state.settings.business_day_starts_at, '05:00');
  await page.getByRole('switch', { name: '알바생 기록' }).click();
  await page.waitForFunction(() => document.querySelector('[role=switch]')?.getAttribute('aria-checked') === 'false');
  assert.equal(api.state.settings.staff_records_visible, false);
  for (const gone of ['점주가 알바생 달력을 볼지', '매장 시간대', '매장에 맞게 이름과 시간을']) assert.equal(await page.getByText(gone).count(), 0, gone);
  await ctx.close();
});
```

  `main h2` 는 근무조 카드 제목만 h2 로 둔다(매장 설정 묶음에는 h2 를 쓰지 않는다).

- [ ] **Step 2: 실패 확인** — Expected: 5 FAIL
- [ ] **Step 3: 구현** — Interfaces 대로. `verify_ui_checklist.cjs` 근무조 단언을 고친다: `근무조 추가` 버튼 → `getByRole("button", { name: "추가", exact: true })`, `저녁 위로` 클릭 → `getByRole("button", { name: "저녁 옮기기" }).focus()` 후 `ArrowUp`. `ui-cards` 의 손잡이 테스트(`검토 3`)는 옮긴 `SortableList` 로 그대로 통과해야 한다.
- [ ] **Step 4: 통과 확인** — Expected: `ui-manage` 14 PASS, 다른 묶음·`verify_ui_checklist` PASS

---

### Task 4: 알바생 기록 (o13a·o13b·o13c)

**Files:** Modify `web/components/checklist/records-screen.tsx`, `api/scripts/verify_ui_checklist.cjs`(기록 단언), `verify_ui_manage.cjs`

**Interfaces:**
- 사장님(`role === "OWNER"`):
  - `PageHeader title="알바생 기록"`(설명 없음). `내 기록 남기기` 스위치·설명 없음.
  - 볼 사람은 `checklistMembersQuery` 의 `role === "STAFF"` 만. 기본은 첫 알바생. 고르는 버튼 `<button aria-label="기록 볼 알바생, 지금 ${name}">${name} ▾</button>` → `Sheet title="누구 기록을 볼까요?"` 안에 알바생마다 `<button data-member-option>`(이름, 고른 사람은 체크 표시 `aria-pressed`). 고르면 시트 닫고 그 달 기록 조회(`user_id`).
  - 알바생 0명: `Empty title="아직 알바생이 없어요"`, 달력 없음, 기록 조회 안 함(Review Focus 3).
  - `staff_records_visible` 가 꺼짐: `Empty title="알바생 기록을 꺼 두었어요"` + `ButtonLink variant="secondary" href="/owner/shifts"` `근무조에서 켜기`, 고르는 버튼·달력 없음.
- 직원(`role === "STAFF"`): 제목 `내 기록` 유지, 설명 없음, `내 기록 남기기` 스위치를 키트 `Switch` 로(설명 Caption 삭제).
- 달력(두 역할):
  - 달 머리 `‹ 2026년 11월 ›` 그대로. 달력 `Surface data-calendar` 에서 가로로 60px 넘게 밀고 놓으면 달 이동(왼쪽 밀기 = 다음 달, 오른쪽 = 지난달). 세로 스크롤은 막지 않는다(`touch-pan-y`, 가로가 더 클 때만). 밀다 놓은 것은 날짜 누르기로 치지 않는다.
  - 날짜를 누르면 `Sheet title="${M}월 ${D}일"` 로 그날 한 일(지금 상세 내용 그대로: 제출 줄 + `✓ 한 일` 목록). 화면 아래 상세 카드는 없앤다.

- [ ] **Step 1: 테스트 작성**

```js
const monthOf = (text) => { const [, y, m] = text.match(/(\d+)년 (\d+)월/); return `${y}-${m.padStart(2, '0')}`; };
test('o13a 알바생 기록: 알바생만 시트로 고른다', async (b) => {
  const { page, ctx, api } = await open(b, 'OWNER', '/owner/me');
  await page.getByRole('heading', { name: '알바생 기록' }).waitFor();
  await page.getByRole('button', { name: '기록 볼 알바생, 지금 박지호' }).click();
  const sheet = page.getByRole('dialog', { name: '누구 기록을 볼까요?' });
  assert.deepEqual((await sheet.locator('[data-member-option]').allInnerTexts()).map((x) => x.trim()), ['박지호', '김민준']);
  await sheet.getByRole('button', { name: '김민준' }).click();
  await page.getByRole('button', { name: '기록 볼 알바생, 지금 김민준' }).waitFor();
  assert.ok(api.calls.some((c) => c.path.startsWith('/checklist/records?') && c.path.includes('user_id=3')));
  assert.ok(!api.calls.some((c) => c.path.startsWith('/checklist/records?') && !c.path.includes('user_id=')));
  for (const gone of ['내 기록 남기기', '내가 체크한 일과 제출 기록']) assert.equal(await page.getByText(gone).count(), 0, gone);
  await ctx.close();
});
test('o13b 날짜를 누르면 시트, 밀면 달이 바뀐다', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/me');
  const head = page.getByRole('heading', { name: /\d+년 \d+월/ });
  const month = monthOf(await head.innerText());
  await page.getByRole('button', { name: `${month}-11 78%` }).click();
  const sheet = page.getByRole('dialog', { name: `${Number(month.slice(5))}월 11일` });
  await sheet.getByText('✓ 우유 재고 확인').waitFor();
  await sheet.getByRole('button', { name: '닫기' }).click();
  const cal = await page.locator('[data-calendar]').boundingBox();
  await page.mouse.move(cal.x + cal.width - 30, cal.y + 120); await page.mouse.down();
  await page.mouse.move(cal.x + 30, cal.y + 130, { steps: 12 }); await page.mouse.up();
  const [y, m] = month.split('-').map(Number);
  const next = m === 12 ? `${y + 1}년 1월` : `${y}년 ${m + 1}월`;
  await page.getByRole('heading', { name: next }).waitFor();
  assert.equal(await page.getByRole('dialog').count(), 0, '밀기는 날짜 누르기가 아니다');
  await ctx.close();
});
test('o13a 알바생이 없으면 빈 상태', async (b) => {
  const { page, ctx, api } = await open(b, 'OWNER', '/owner/me', { overrides: { checklistMembers: [{ member_id: 1, user_id: 1, role: 'OWNER', name: '김사장', shift_ids: [] }] } });
  await page.getByText('아직 알바생이 없어요').waitFor();
  assert.equal(await page.locator('[data-calendar]').count(), 0);
  assert.ok(!api.calls.some((c) => c.path.startsWith('/checklist/records')));
  await ctx.close();
});
test('o13a 알바생 기록을 꺼 두면 켜는 곳으로', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/me', { overrides: { settings: { business_day_starts_at: '04:00', staff_records_visible: false, timezone: 'Asia/Seoul' } } });
  await page.getByText('알바생 기록을 꺼 두었어요').waitFor();
  await page.getByRole('link', { name: '근무조에서 켜기' }).click(); await to(page, '/owner/shifts');
  await ctx.close();
});
test('o13c 직원 내 기록은 남기기 스위치를 그대로 둔다', async (b) => {
  const { page, ctx } = await open(b, 'STAFF', '/staff/me');
  await page.getByRole('heading', { name: '내 기록' }).waitFor();
  await page.getByRole('switch', { name: '내 기록 남기기' }).waitFor();
  assert.equal(await page.getByText('꺼도 매장 체크 상태는 바뀌어요').count(), 0);
  await ctx.close();
});
```

  `Sheet` 의 닫기 버튼 이름이 `닫기` 가 아니면 키트 이름에 맞춘다(시트 구현을 바꾸지 않는다).

- [ ] **Step 2: 실패 확인** — Expected: 5 FAIL
- [ ] **Step 3: 구현** — Interfaces 대로. `verify_ui_checklist.cjs` 점주 기록 단언을 고친다: `getByLabel("기록 구성원").selectOption("2")` → 기본이 첫 알바생(그 스크립트 fixture 의 첫 STAFF)이므로 고르기 없이 날짜 버튼을 누르고 시트 안에서 `✓ 합성 청소` 를 찾는다. `내 기록 남기기 끄기` 단언은 `/staff/me` 로 옮긴다. `조회 꺼짐 구성원 선택 숨김` 은 `getByRole("button", { name: /기록 볼 알바생/ })` count 0.
- [ ] **Step 4: 통과 확인** — Expected: `ui-manage` 19 PASS, 다른 묶음·`verify_ui_checklist` PASS

---

### Task 5: 카테고리 (o17a·o17b, G5)

**Files:** Modify `web/app/owner/categories/page.tsx`, `verify_ui_manage.cjs`

**Interfaces:**
- `Screen` + `BackButton parent="/owner/settings"` + `PageHeader title="카테고리"`(설명 없음).
- 추가 칸: 키트 모양 입력(`min-h-12 rounded-[14px] bg-surface px-4`, 포커스 테두리 `ring-2 ring-primary`, 오류면 `ring-2 ring-danger-500` + `aria-invalid`), 오른쪽 `Button className="w-auto! shrink-0 whitespace-nowrap px-5"` `추가`. 이름을 다듬은 값(`trim`)이 비면 `추가` 꺼짐. 다듬은 값이 기존 이름과 같으면 칸 아래 `role="alert"` `이미 있는 카테고리예요` + `추가` 꺼짐. 서버 오류도 칸 아래 같은 자리. 성공 토스트 `카테고리를 추가했어요`, 칸 비움.
- 목록: 줄 `<li data-category>` 이름만(16 Bold). 시스템 카테고리(`is_system`)는 밀 수 없는 줄. 나머지는 `SwipeRow left={{ label: '지우기', ariaLabel: `${name} 지우기`, tone: 'danger' }}` → `ConfirmDialog`(제목 `'${name}' 카테고리를 지울까요?`, 설명 `직접 옮긴 카드는 기타로 가요.`, 확인 `지우기`, danger) → 성공 토스트 `카테고리를 지웠어요`. `window.confirm` 없앰.
- 재분류 상태(진행 중 `Banner tone="info"` `카드를 다시 나누는 중이에요`, 실패 `Banner tone="danger"` `카드를 다시 나누지 못했어요` + 동작 `다시`)는 유지.
- 로딩 `Skeleton`, 조회 오류 `ErrorInline`(다시).

- [ ] **Step 1: 테스트 작성**

```js
test('o17 추가 칸 상태: 비면 꺼짐, 같은 이름은 칸 아래 빨간 글', async (b) => {
  const { page, ctx, api } = await open(b, 'OWNER', '/owner/categories');
  await page.getByRole('heading', { name: '카테고리' }).waitFor();
  const input = page.getByLabel('새 카테고리 이름');
  const add = page.getByRole('button', { name: '추가', exact: true });
  assert.ok(await add.isDisabled());
  await input.fill(' 재고 위치 ');
  await page.getByRole('alert').getByText('이미 있는 카테고리예요').waitFor();
  assert.equal(await input.getAttribute('aria-invalid'), 'true');
  assert.ok(await add.isDisabled());
  await input.fill('디저트');
  assert.equal(await page.getByText('이미 있는 카테고리예요').count(), 0);
  assert.equal(await add.evaluate((el) => getComputedStyle(el).whiteSpace), 'nowrap');
  assert.equal(await add.evaluate((el) => el.getBoundingClientRect().height < 60), true);
  await add.click();
  await page.getByRole('status').getByText('카테고리를 추가했어요').waitFor();
  assert.ok(api.state.categories.some((c) => c.name === '디저트'));
  assert.equal(await input.inputValue(), '');
  for (const gone of ['카테고리를 바꾸면', '사용자 카테고리', '필수 시스템 카테고리']) assert.equal(await page.getByText(gone).count(), 0, gone);
  await ctx.close();
});
test('o17 밀어서 지우기는 확인 창, 기타는 못 지운다', async (b) => {
  const { page, ctx, api } = await open(b, 'OWNER', '/owner/categories');
  const row = page.locator('[data-category]').filter({ hasText: '오픈 마감' });
  const box = await row.boundingBox();
  await page.mouse.move(box.x + box.width - 20, box.y + box.height / 2); await page.mouse.down();
  await page.mouse.move(box.x + box.width - 140, box.y + box.height / 2, { steps: 10 }); await page.mouse.up();
  const dialog = page.getByRole('dialog', { name: "'오픈 마감' 카테고리를 지울까요?" });
  await dialog.getByRole('button', { name: '지우기' }).click();
  await page.getByRole('status').getByText('카테고리를 지웠어요').waitFor();
  assert.ok(!api.state.categories.some((c) => c.category_id === 11));
  assert.equal(await page.getByRole('button', { name: '기타 지우기' }).count(), 0);
  await ctx.close();
});
```

- [ ] **Step 2: 실패 확인** — Expected: 2 FAIL
- [ ] **Step 3: 구현** — Interfaces 대로.
- [ ] **Step 4: 통과 확인** — Expected: `ui-manage` 21 PASS, 다른 묶음 PASS

---

### Task 6: 알림 (o18a·o18b, G5)

**Files:** Modify `web/app/owner/notifications/page.tsx`, `api/scripts/verify_ui_nav.cjs`(뒤로 링크 이름), `verify_ui_manage.cjs`

**Interfaces:**
- `Screen onRefresh={() => notifications.refetch()}` + `BackButton parent="/owner"` + `PageHeader title={<>알림 {unread > 0 && <CountBadge n={unread} tone="danger" />}</>} action={<TextButton>새로고침</TextButton>}`(새로고침 중엔 꺼짐).
- 휴대폰 알림:
  - 켜기 권유는 `Banner tone="info"` `질문이 오면 휴대폰으로 바로 알려드릴까요?` + 동작 `알림 받기`(지금 `enablePush`) + `onDismiss` 이름 `나중에` → `localStorage["askbuddy:push-banner"] = "later"`, 다시 띄우지 않는다(G6). 보이는 조건: 브라우저 지원 && `push_configured` && 구독 없음 && `later` 아님. 저장소 읽기 실패면 보인다.
  - 이미 켜져 있으면 목록 아래 작은 `TextButton` `휴대폰 알림 끄기`.
  - iPhone 홈 화면 안내·지원 안 함 안내는 지금 글 그대로 `Banner tone="info"`(누를 것 없음). 서버 Push 키 없음은 아무것도 그리지 않는다.
  - `허용하지 않아도…` 문구 없음.
- 목록: 알림마다 `SwipeRow`(안 읽은 것만 `left={{ label: '읽음', ariaLabel: `${title} 읽음으로`, tone: 'primary' }}`), 안의 줄은 지금처럼 누르면 읽음 처리 뒤 이동(`<button data-notification>`). 안 읽은 줄은 흰 바탕 + 왼쪽 초록 점, 읽은 줄은 `opacity-60`. `처리 완료` 는 `Chip tone="brand" size="sm"`. 이모지 아이콘 유지.
  - 밀어서 읽음은 `useMutation(markNotificationRead)`: `onMutate` 로 캐시의 그 알림 `read_at` 과 첫 페이지 `unread_count` 를 바로 바꾸고, `onError` 로 되돌리고 `ErrorInline` `읽음으로 바꾸지 못했어요.`. 성공 뒤 `invalidateQueries(queryKeys.notificationsRoot(storeId))`(종 숫자도 같이).
  - 빈 목록 `Empty title="아직 도착한 알림이 없어요"`. 처음 로딩 `Skeleton` 3개. 이전 알림 더 보기 그대로.
- 코치마크 `Coachmark id="owner-notifications" steps={[{ target: '[data-notification-unread]', text: '밀면 읽음으로 바뀌어요' }]}`(첫 안 읽은 줄의 SwipeRow 겉에 `data-notification-unread`).

- [ ] **Step 1: 테스트 작성**

```js
test('o18b 알림: 밀어서 읽음, 머리 뱃지가 줄어든다', async (b) => {
  const { page, ctx, api } = await open(b, 'OWNER', '/owner/notifications');
  const head = page.getByRole('heading', { name: /알림/ });
  await head.getByText('3', { exact: true }).waitFor();
  const row = page.locator('[data-notification]').filter({ hasText: '카드 정리가 끝났어요' });
  const box = await row.boundingBox();
  await page.mouse.move(box.x + box.width - 20, box.y + box.height / 2); await page.mouse.down();
  await page.mouse.move(box.x + box.width - 140, box.y + box.height / 2, { steps: 10 }); await page.mouse.up();
  await head.getByText('2', { exact: true }).waitFor();
  assert.ok(api.state.notifications.find((n) => n.notification_id === 2).read_at);
  assert.equal(here(page), '/owner/notifications');
  await ctx.close();
});
test('o18b 밀어서 읽음 실패하면 그대로', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/notifications', { overrides: { failRead: true } });
  await page.getByRole('button', { name: '카드 정리가 끝났어요 읽음으로' }).click();
  await page.getByText('읽음으로 바꾸지 못했어요.').waitFor();
  await page.getByRole('heading', { name: /알림/ }).getByText('3', { exact: true }).waitFor();
  await ctx.close();
});
test('o18b 새로고침 버튼과 당겨서 새로고침', async (b) => {
  const { page, ctx, api } = await open(b, 'OWNER', '/owner/notifications', { touch: true });
  const count = () => api.calls.filter((c) => c.method === 'GET' && (c.path === '/notifications' || c.path.startsWith('/notifications?'))).length;
  const before = count();
  await page.getByRole('button', { name: '새로고침' }).click();
  await page.waitForTimeout(300);
  assert.ok(count() > before);
  const mid = count();
  const cdp = await ctx.newCDPSession(page);
  const box = await page.locator('main').boundingBox();
  const at = (type, y) => cdp.send('Input.dispatchTouchEvent', { type, touchPoints: type === 'touchEnd' ? [] : [{ x: box.x + 100, y }] });
  await at('touchStart', box.y + 60);
  for (let y = box.y + 60; y <= box.y + 360; y += 20) await at('touchMove', y);
  await at('touchEnd', box.y + 360);
  await page.waitForTimeout(800);
  assert.ok(count() > mid);
  await ctx.close();
});
test('o18a 휴대폰 알림 배너: 나중에 누르면 다시 안 뜬다', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/notifications', { overrides: { pushConfigured: true } });
  const banner = page.getByText('질문이 오면 휴대폰으로 바로 알려드릴까요?');
  await banner.waitFor();
  await page.getByRole('button', { name: '알림 받기' }).waitFor();
  assert.equal(await page.getByText('허용하지 않아도').count(), 0);
  await page.getByRole('button', { name: '나중에' }).click();
  await banner.waitFor({ state: 'detached' });
  await page.reload({ waitUntil: 'networkidle' });
  await page.locator('[data-notification]').first().waitFor();
  assert.equal(await banner.count(), 0);
  await ctx.close();
});
test('o18a 처음 오면 밀어서 읽음을 알려 준다', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/notifications', { overrides: { coach: true } });
  const bubble = page.getByRole('dialog', { name: '안내' });
  await bubble.getByText('밀면 읽음으로 바뀌어요').waitFor();
  await bubble.getByRole('button', { name: '알겠어요' }).click();
  await page.reload({ waitUntil: 'networkidle' });
  await page.locator('[data-notification]').first().waitFor();
  await page.waitForTimeout(500);
  assert.equal(await bubble.count(), 0);
  await ctx.close();
});
```

- [ ] **Step 2: 실패 확인** — Expected: 5 FAIL
- [ ] **Step 3: 구현** — Interfaces 대로. `verify_ui_nav.cjs` 의 `NAV-1 옛 상단 바(알림)의 뒤로` 는 `getByRole('link', { name: '뒤로가기' })` → `back(page)` 로 고치고 이름을 `NAV-1 알림의 뒤로: 기록이 없으면 오늘 매장(T3)` 으로. `NAV-9` 는 `getByText('직원 질문이 왔어요').click()` 그대로 통과해야 한다.
- [ ] **Step 4: 통과 확인** — Expected: `ui-manage` 26 PASS, `ui-nav 30`·`ui-intake 27`·`ui-cards 36`·`ui-today 20`, 기존 CI 스크립트(`verify_r_ui`, `verify_r_history_ui`, `verify_ui_rebrand`, `verify_w3b_card_facts_ui`, `verify_ui_checklist`)·`verify_ui_owner_ops`(OPS_UI_BASE=3011) PASS, `pnpm check` 통과

---

## 이 계획에서 하지 않는 것(백로그로)

- o12a 연필로 이름·매장 이름 고치기 — 수정 API(서버).
- o15b 승인 '되돌리기' 스낵바 — 승인 응답 user_id·승인 취소(서버).
- o17 카테고리 끌어서 순서·이름 고치기 — 순서·이름 수정 API(서버).
- o13a 출퇴근 기록과 합치기, o14b 직급 — 별도 기획(스펙 '별도').
- 쓰지 않는 옛 화면·컴포넌트(`/owner/category`, `components/owner/{answer-question-sheet,pending-question-card,knowledge-card-list-item,upload-queue-item,task-card-detail,…}`) 정리 — 계획 5 뒤 백로그에서 한 번에.
