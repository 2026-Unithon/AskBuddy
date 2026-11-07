# 화면 개선 계획 5: 직원 화면·로그인 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 직원 오늘 할 일(s01), 레시피 목록·보기(s02·s03), 버디(s04), 자주 묻는 질문 화면을 버디 칩으로 옮기기(s05a, NAV-6), 답변 알림(s09a), 대화 '새 답' 점(NAV-8), 로그인·이메일(a01a·a02a)을 사용자 결정대로 바꾼다.

**Architecture:** 서버 API 는 그대로 쓴다. 자주 묻는 질문(`/learn/faqs`)을 추천 질문 칩 하나(`SuggestedQuestions`)로 만들어 오늘 할 일·레시피 보기·버디가 같이 쓴다. `CheckRow` 에 제목을 누르면 시트를 여는 `onOpen` 을, `AskBar` 에 '새 답' 점(`newAnswer`)을 더한다. 옛 `components/ui` 로 그리던 답변 알림·로그인·이메일을 키트로 옮긴다. **서버 API·DB 는 바꾸지 않는다.**

**Tech Stack:** Next.js 16 App Router, React 19, Tailwind 4, TanStack Query 5, Playwright 1.62(합성 API).

**Spec:** `docs/dev/plan/UI_REDESIGN_SPEC_20261106.md` (s01a~s09a, a01a·a02a, NAV-6·NAV-8)

## Global Constraints

- 계획 1~4b 제약 전부(중간점 금지, 모션 토큰, 피드백 G4, 합성 API, 서버 무변경, 진행률 % 금지, `eslint-disable` 금지, 설명용 회색 문구 금지).
- 직원 설정(s07a)은 계획 4b 에서 사장님 설정과 같게 끝냈다.
- 추천 질문 칩은 누르면 질문을 **채워서** 버디로 간다(오늘 할 일·레시피 보기). 버디 화면 안의 칩은 누르면 바로 보낸다(사용자 동작이라 화면 진입 자동 전송이 아니다).
- 답은 한 번에 오므로 '타이핑'은 다 받은 답을 약 0.3초에 걸쳐 보여 주는 연출이다(s04c). 이미 있던 대화(새로고침·다시 들어옴)는 연출하지 않는다. `prefers-reduced-motion` 이면 바로 보인다.
- 직원 대기 화면(`/staff/pending`), 합류 화면(`/join`), 역할 고르기(`/auth/role`)의 옛 디자인은 이번 범위 밖(백로그).

## Review Focus

1. **오늘 할 일 시트에서 레시피를 못 불러옴(삭제·비공개 카드)**: 시트 안에 "이 레시피를 볼 수 없어요", 체크는 그대로 된다 → Task 1 `s01d 볼 수 없는 레시피면 시트에 안내`.
2. **추천 질문이 없거나(새 매장) 불러오기 실패**: 칩 자리를 비우고 입력창은 그대로 쓴다 → Task 3 `s05a 자주 묻는 질문이 없으면 칩 없이 입력창만`.
3. **타이핑 연출 중 다음 질문을 보냄**: 앞 답은 바로 다 보이고 새 질문이 이어진다(글자가 잘린 채 남지 않는다) → Task 3 `s04c 새 답만 타이핑, 끝나면 전부 보인다`.
4. **답변 알림을 눌렀는데 읽음 저장 실패**: 이동하지 않고 오류를 보인다(지금 동작 유지) → Task 4 `s09a 읽음 실패면 머문다`.
5. **이메일 칸 형식 오류 상태에서 로그인 누름**: 서버로 보내지 않고 칸 아래 빨간 글 → Task 5 `a02a 형식이 틀리면 보내지 않는다`.

---

## 파일 구조

| 파일 | 책임 |
|---|---|
| `web/components/staff/suggested-questions.tsx` (새) | 추천 질문 칩(자주 묻는 질문 상위 N개, 카드로 거르기) |
| `web/components/kit/checkbox.tsx` | `CheckRow.onOpen?` |
| `web/components/kit/composer.tsx` | `AskBar.newAnswer?` |
| `web/components/checklist/today-screen.tsx` | s01b~f, NAV-8 |
| `web/app/staff/recipes/page.tsx`, `web/app/staff/recipes/[itemId]/page.tsx` | s02·s03 |
| `web/components/staff/ask-screen.tsx` | s04·NAV-6 |
| `web/app/staff/faqs/page.tsx` | 버디로 넘기기(s05a) |
| `web/components/r-v2-notifications.tsx` | s09a(키트로) |
| `web/app/page.tsx`, `web/app/auth/email/page.tsx` | a01a·a02a(키트로) |
| `api/scripts/ui_fixture.cjs` | 직원 쪽 경로(R 알림, 제출, 로그인) |
| `api/scripts/verify_ui_staff.cjs` (새) | 이 계획 회귀(`ui-staff`) |
| `api/scripts/verify_r_ui.cjs`, `verify_ui_rebrand.cjs`, `verify_ui_nav.cjs`, `verify_ui_checklist.cjs` | 바뀐 이름·동작에 맞춤 |

### fixture 추가(Task 1 에서 한 번에)

- `initialState`: `rNotifications: [{ notification_id: '51', title: '사장님 답이 왔어요', body: '디카페인 원두는 창고 위 칸에 있어요.', destination: '/staff/chat/v2?session_id=1', read: false }]`, `failRRead: false`, `submitted: null`, `signedOut: false`, `faqs: null`(null 이면 지금 두 개, 배열이면 그것), `failItem: false`.
- 오늘 할 일 묶음 카드의 `item_id`: `오픈 준비` → `null`, 둘째 줄 → `[6, 60, '우유 발주', 16, false]`(공개 카드 6의 학습 항목 16).
- `GET /checklist/today`·`/checklist/status` 의 `my_submission` 은 `state.submitted`. `POST /checklist/submissions` → `state.submitted = { done_lines: 1, total_lines: 2, submitted_at: NOW }`, `{ submission: state.submitted }`.
- `GET /learn/v2/notifications` → `{ notifications: state.rNotifications, next_after: null }`. `POST /learn/v2/notifications/:id/read` → `failRRead` 면 409 `{ error: { message: '읽음 저장 실패' } }`, 아니면 그 알림 `read = true`.
- `/auth/refresh`: `state.signedOut` 이면 401. `POST /auth/login`: 비밀번호가 `right-pass` 면 `signedOut = false` + 세션, 아니면 401.
- `/learn/faqs`: `state.faqs ?? 지금 두 개`.
- `/learn/items/:id`: `failItem` 이면 404.

---

### Task 1: 오늘 할 일 (s01a~f, NAV-8), fixture, 새 묶음

**Files:** Create `web/components/staff/suggested-questions.tsx`, `api/scripts/verify_ui_staff.cjs` / Modify `web/components/kit/checkbox.tsx`, `web/components/kit/composer.tsx`, `web/components/checklist/today-screen.tsx`, `api/scripts/ui_fixture.cjs`, `api/scripts/verify_ui_checklist.cjs`(근무조 칩·제출 시트), CI, `run-ui.sh`

**Interfaces:**
- `SuggestedQuestions({ cardId, limit = 3, onPick }: { cardId?: number; limit?: number; onPick: (question: string) => void })` — `faqsQuery` 의 `items` 를 `question_count` 내림차순, `cardId` 가 있으면 그 카드 것만, 상위 `limit` 개. 칩은 `<button data-suggested>` 글자는 질문 그대로, 가로 스크롤 한 줄(`overflow-x-auto`, 칩 `whitespace-nowrap rounded-full bg-surface px-3.5 min-h-10 text-[14px] shadow-card`). 로딩·오류·0개면 아무것도 그리지 않는다. `aria-label="추천 질문"` 인 `div`.
- `CheckRow({ ..., onOpen })` — `onOpen` 이 있으면 제목은 링크 대신 `<button>`(이름 = 제목)이고 누르면 `onOpen()`. `href` 와 함께 주지 않는다.
- `AskBar({ ..., newAnswer })` — 참이면 입력창 왼쪽에 초록 점 `<span data-new-answer role="img" aria-label="새 답이 왔어요">`.
- 오늘 할 일(`TodayScreen`):
  - s01b: 남은 수 제목 `text-[22px]`(지금 28), 히어로 아래 `done/total개` 글은 그대로.
  - s01c: 근무조 칩(`aria-label="근무조 선택"`) 없앤다. 서버가 준 묶음 그대로 보인다.
  - s01d: 줄 제목을 누르면 `Sheet title={카드 제목}` 이 열리고 `learnItemQuery(item_id)` 의 내용(`NumberedContent`)과 `ButtonLink` `레시피 전체 보기`(→ `/staff/recipes/{item_id}`). 못 불러오면(403·404) `이 레시피를 볼 수 없어요`. `item_id` 가 없는 줄은 누를 수 없는 글.
  - s01e: 남은 게 있으면 `ConfirmDialog`(제목 `${남은}개가 남았어요. 그래도 끝낼까요?`, 확인 `그래도 끝내기`, 취소 `더 체크하기`, 실패는 `error`). 다 한 뒤 히어로는 축하 체크 원 `data-celebrate`(스프링) + `오늘 할 일 끝났어요`.
  - s01f: footer 에 `SuggestedQuestions` → 고르면 `/staff/ask?q=…` 로 이동. 그 아래 `AskBar`.
  - NAV-8: `rNotificationsQuery` 첫 페이지에 `read === false` 가 있으면 `AskBar newAnswer`.

- [ ] **Step 1: 테스트 작성** — `verify_ui_staff.cjs`(머리는 `verify_ui_manage.cjs` 와 같은 모양, `createSuite('ui-staff')`)

```js
test('s01b·c 진행 카드는 작게, 근무조 칩은 없다', async (b) => {
  const { page, ctx } = await open(b, 'STAFF', '/staff');
  const title = page.getByText(/^\d+개 남았어요$/);
  await title.waitFor();
  assert.ok(parseFloat(await title.evaluate((el) => getComputedStyle(el).fontSize)) <= 22);
  assert.equal(await page.getByLabel('근무조 선택').count(), 0);
  await ctx.close();
});
test('s01d 할 일 이름을 누르면 레시피 시트', async (b) => {
  const { page, ctx } = await open(b, 'STAFF', '/staff');
  await page.getByRole('button', { name: '우유 발주', exact: true }).click();
  const sheet = page.getByRole('dialog', { name: '우유 발주' });
  await sheet.getByText(/오전 10시 전 발주/).waitFor();
  await sheet.getByRole('link', { name: '레시피 전체 보기' }).click(); await to(page, '/staff/recipes/16');
  await ctx.close();
});
test('s01d 볼 수 없는 레시피면 시트에 안내', async (b) => {
  const { page, ctx } = await open(b, 'STAFF', '/staff', { overrides: { failItem: true } });
  await page.getByRole('button', { name: '우유 발주', exact: true }).click();
  await page.getByRole('dialog', { name: '우유 발주' }).getByText('이 레시피를 볼 수 없어요').waitFor();
  await ctx.close();
});
test('s01e 남았는데 끝내면 확인 창, 끝나면 축하', async (b) => {
  const { page, ctx, api } = await open(b, 'STAFF', '/staff');
  await page.getByTestId('checklist-submit').click();
  const dialog = page.getByRole('dialog', { name: /남았어요. 그래도 끝낼까요\?/ });
  await dialog.getByRole('button', { name: '더 체크하기' }).click();
  assert.equal(api.calls.filter((c) => c.path === '/checklist/submissions').length, 0);
  await page.getByTestId('checklist-submit').click();
  await dialog.getByRole('button', { name: '그래도 끝내기' }).click();
  await page.getByText('오늘 할 일 끝났어요').waitFor();
  assert.ok(await page.locator('[data-celebrate]').isVisible());
  await ctx.close();
});
test('s01f 추천 질문 칩을 누르면 버디에 채워진다', async (b) => {
  const { page, ctx } = await open(b, 'STAFF', '/staff');
  await page.locator('[data-suggested]', { hasText: '바닐라 라떼 시럽 몇 펌프예요?' }).click();
  await page.waitForURL(/\/staff\/ask\?q=/);
  assert.equal(await page.getByLabel('모르는 거 물어보기').inputValue(), '바닐라 라떼 시럽 몇 펌프예요?');
  await ctx.close();
});
test('NAV-8 새 답이 있으면 입력창에 점, 없으면 없다', async (b) => {
  const one = await open(b, 'STAFF', '/staff');
  await one.page.locator('[data-new-answer]').waitFor();
  await one.ctx.close();
  const none = await open(b, 'STAFF', '/staff', { overrides: { rNotifications: [] } });
  await none.page.getByText(/^\d+개 남았어요$/).waitFor();
  assert.equal(await none.page.locator('[data-new-answer]').count(), 0);
  await none.ctx.close();
});
```

- [ ] **Step 2: 실패 확인** — `run-ui.sh` → Expected: 6 FAIL
- [ ] **Step 3: 구현** — Interfaces 대로, fixture 전부. `verify_ui_checklist.cjs` 의 직원 근무조 칩 단언(칩을 눌러 근무조를 바꾸는 부분)은 칩이 없다는 단언으로, 제출 확인 시트(`Sheet`)는 `ConfirmDialog` 에 맞춘다(버튼 이름 `그래도 끝내기`·`더 체크하기` 는 같다). CI 에 `verify_ui_staff.cjs`.
- [ ] **Step 4: 통과 확인** — Expected: `ui-staff` 6 PASS, 다른 묶음·기존 스크립트 PASS

---

### Task 2: 레시피 목록·보기 (s02a·s02b·s03a·s03b·s03c)

**Files:** Modify `web/app/staff/recipes/page.tsx`, `web/app/staff/recipes/[itemId]/page.tsx`, `api/scripts/verify_ui_rebrand.cjs`, `verify_ui_staff.cjs`

**Interfaces:**
- 목록: 검색 칸은 사장님 카드 찾기와 같은 모양(`role="searchbox"`, 이름 `레시피 찾기`), 글자를 칠 때마다 거른다(지금 그대로). 줄 부제(`확인했어요` 등) 없앤다. 대신 `DONE` 은 줄 오른쪽 초록 체크 `<span role="img" aria-label="확인함">`, `RECONFIRM_REQUIRED` 는 주황 점 `<span role="img" aria-label="내용이 바뀜">`. 묶음들은 `Stagger` 로 차례 등장.
- 보기(s03a): 제목 아래, 내용 줄 중 `HOT`·`ICE` 로 시작하는 줄은 규격별로 나눠 `<h2>` 굵게 18px `HOT`/`ICE` + 그 아래 카드(`Surface`)에 앞말을 뺀 나머지. 그 밖의 줄은 한 카드에 `NumberedContent`. 규격 줄이 없으면 지금처럼 한 카드.
- 보기(s03b): `확인했어요. 내용이 바뀌면 다시 알려드려요.`·`출처 …`·`인용 끊김` 글 없앤다. 재확인 안내(`내용이 바뀌었어요. 다시 한 번 확인해주세요`)는 남긴다.
- 보기(s03c): footer 의 `이 레시피에 대해 물어보기` 링크 자리에 `SuggestedQuestions cardId={card_id} limit={2}` + 맨 앞 고정 칩 `이 레시피에 대해 물어보기`(링크, `/staff/ask?q={제목} `). 칩을 누르면 질문을 채워 버디로.

- [ ] **Step 1: 테스트 작성**

```js
test('s02b 레시피 목록은 글 대신 표시, 차례 등장', async (b) => {
  const { page, ctx } = await open(b, 'STAFF', '/staff/recipes');
  await page.getByRole('link', { name: /바닐라 라떼/ }).waitFor();
  for (const gone of ['확인했어요', '아직 안 봤어요', '내용이 바뀌었어요']) assert.equal(await page.getByText(gone, { exact: true }).count(), 0, gone);
  await page.getByRole('searchbox', { name: '레시피 찾기' }).fill('아메');
  assert.equal(await page.getByRole('link', { name: /바닐라 라떼/ }).count(), 0);
  await page.getByRole('link', { name: /아메리카노/ }).waitFor();
  await ctx.close();
});
test('s03a 레시피 보기는 HOT·ICE 를 카드 밖 제목으로', async (b) => {
  const { page, ctx } = await open(b, 'STAFF', '/staff/recipes/12');
  await page.getByRole('heading', { name: 'HOT', exact: true }).waitFor();
  await page.getByRole('heading', { name: 'ICE', exact: true }).waitFor();
  await page.getByText('물 275ml 샷 2', { exact: true }).waitFor();
  for (const gone of [/^출처/, '확인했어요. 내용이 바뀌면 다시 알려드려요.']) assert.equal(await page.getByText(gone).count(), 0, String(gone));
  await ctx.close();
});
test('s03c 레시피 보기 아래 추천 질문 칩', async (b) => {
  const { page, ctx } = await open(b, 'STAFF', '/staff/recipes/11');
  await page.locator('[data-suggested]', { hasText: '바닐라 라떼 시럽 몇 펌프예요?' }).click();
  await page.waitForURL(/\/staff\/ask\?q=/);
  assert.equal(await page.getByLabel('모르는 거 물어보기').inputValue(), '바닐라 라떼 시럽 몇 펌프예요?');
  await ctx.close();
});
```

- [ ] **Step 2: 실패 확인** — Expected: 3 FAIL
- [ ] **Step 3: 구현** — Interfaces 대로. `verify_ui_rebrand.cjs` 의 `바뀌었어요` 글 단언은 `getByRole('img', { name: '내용이 바뀜' })` 로.
- [ ] **Step 4: 통과 확인** — Expected: `ui-staff` 9 PASS, 다른 묶음·기존 스크립트 PASS

---

### Task 3: 버디 (s04a·s04b·s04c, s05a, NAV-6)

**Files:** Modify `web/components/staff/ask-screen.tsx`, `web/app/staff/faqs/page.tsx`, `api/scripts/verify_r_ui.cjs`, `api/scripts/verify_ui_nav.cjs`, `verify_ui_staff.cjs`

**Interfaces:**
- NAV-6·s04a: footer 입력창 위 `SuggestedQuestions limit={3}`. 보내는 중이 아니고 입력이 비었을 때만 보인다. 누르면 바로 그 질문을 보낸다(`ask.mutate`).
- s04a 근거: `CitationChip` 은 작은 회색 글자 버튼 `근거 카드`(숫자 없음, `text-[12px] text-ink-muted underline-offset-2`), 불러오면 `근거 {제목}`. 펼침은 그대로.
- s04b 사장님께 넘긴 답: `Chip` `확인 중이에요. 답 오면 알려드려요` 대신 단계 표시 `<ol aria-label="사장님께 확인 중">` 세 줄: `질문을 받았어요`(체크), `사장님께 보냈어요`(체크), `답 오면 알려드려요`(깜빡이는 점). 
- s04c: 보내는 중엔 `Caption 매장 카드를 확인하고 있어요` 대신 생각 중 점 세 개 `<div role="status" aria-label="버디가 생각 중이에요" data-thinking>`. 새로 도착한 버디 답(이 화면에 들어온 뒤 생긴 `message_id`)만 `Typewriter` 로 0.3초에 걸쳐 보인다: 연출 중 `data-typing` 이 붙고, 끝나면 빠지고 전문이 보인다. 첫 불러오기 때 이미 있던 메시지는 연출하지 않는다.
- s05a: `/staff/faqs` 는 `redirect('/staff/ask')`(서버 컴포넌트). 옛 FAQ 화면 코드는 지운다.

- [ ] **Step 1: 테스트 작성**

```js
test('NAV-6 버디 입력창 위 추천 질문 칩은 누르면 바로 보낸다', async (b) => {
  const { page, ctx, api } = await open(b, 'STAFF', '/staff/ask');
  await page.locator('[data-suggested]', { hasText: '우유 발주 언제 해요?' }).click();
  await page.getByText('ICE 바닐라 라떼는 바닐라 시럽 2펌프예요.').waitFor();
  assert.equal(api.calls.find((c) => c.path === '/learn/v2/chat').body.question, '우유 발주 언제 해요?');
  await ctx.close();
});
test('s05a 자주 묻는 질문이 없으면 칩 없이 입력창만', async (b) => {
  const { page, ctx } = await open(b, 'STAFF', '/staff/ask', { overrides: { faqs: [] } });
  await page.getByLabel('모르는 거 물어보기').waitFor();
  assert.equal(await page.locator('[data-suggested]').count(), 0);
  await ctx.close();
});
test('s05a 옛 자주 묻는 질문 주소는 버디로', async (b) => {
  const { page, ctx } = await open(b, 'STAFF', '/staff/faqs');
  await to(page, '/staff/ask');
  await ctx.close();
});
test('s04c 생각 중 표시, 새 답만 타이핑, 끝나면 전부 보인다', async (b) => {
  const { page, ctx } = await open(b, 'STAFF', '/staff/ask', { overrides: { chatDelayMs: 600 } });
  await page.getByLabel('모르는 거 물어보기').fill('바닐라 라떼 시럽 몇 펌프예요?');
  await page.getByRole('button', { name: '보내기', exact: true }).click();
  await page.locator('[data-thinking]').waitFor();
  await page.locator('[data-typing]').waitFor({ timeout: 3000 });
  await page.locator('[data-typing]').waitFor({ state: 'detached', timeout: 2000 });
  await page.getByText('ICE 바닐라 라떼는 바닐라 시럽 2펌프예요.', { exact: true }).waitFor();
  await page.reload({ waitUntil: 'networkidle' });
  await page.getByText('ICE 바닐라 라떼는 바닐라 시럽 2펌프예요.', { exact: true }).waitFor();
  assert.equal(await page.locator('[data-typing]').count(), 0, '다시 들어오면 연출하지 않는다');
  await ctx.close();
});
test('s04a 근거는 작은 회색 글자, 숫자 없음', async (b) => {
  const { page, ctx } = await open(b, 'STAFF', '/staff/ask');
  await page.getByLabel('모르는 거 물어보기').fill('바닐라 라떼 시럽 몇 펌프예요?');
  await page.getByRole('button', { name: '보내기', exact: true }).click();
  const cite = page.getByRole('button', { name: '근거 카드', exact: true });
  await cite.waitFor();
  assert.ok(parseFloat(await cite.evaluate((el) => getComputedStyle(el).fontSize)) <= 12);
  assert.equal(await page.getByText(/근거 카드 \d/).count(), 0);
  await ctx.close();
});
test('s04b 사장님께 넘긴 답은 단계로 보인다', async (b) => {
  const { page, ctx } = await open(b, 'STAFF', '/staff/ask', { overrides: { chatEscalate: true } });
  await page.getByLabel('모르는 거 물어보기').fill('디카페인 원두는 어디 있어요?');
  await page.getByRole('button', { name: '보내기', exact: true }).click();
  const steps = page.getByRole('list', { name: '사장님께 확인 중' });
  await steps.getByText('사장님께 보냈어요').waitFor();
  await steps.getByText('답 오면 알려드려요').waitFor();
  await ctx.close();
});
```

  fixture 에 더한다: `chatDelayMs`(채팅 응답 지연), `chatEscalate`(참이면 `{ action: 'ESCALATE', message: '사장님께 물어볼게요.', pending_id: '104', citations: [] }`). `POST /learn/v2/chat` 은 사용자·버디 메시지를 `state.messages` 에 쌓아 history 가 돌려주게 한다(버디 메시지 `response` 에 위 응답, `receipt_id: 'r1'`).

- [ ] **Step 2: 실패 확인** — Expected: 6 FAIL
- [ ] **Step 3: 구현** — Interfaces 대로. `verify_r_ui.cjs`: `근거 카드 1` → `근거 카드`(첫째), `확인 중이에요. 답 오면 알려드려요` → 단계 목록의 `답 오면 알려드려요`. `verify_ui_nav.cjs` 의 `/staff/faqs` 옛 탭 검사는 주소가 `/staff/ask` 로 넘어가는지로 바꾼다.
- [ ] **Step 4: 통과 확인** — Expected: `ui-staff` 15 PASS, 다른 묶음·기존 스크립트 PASS

---

### Task 4: 답변 알림 (s09a)

**Files:** Modify `web/components/r-v2-notifications.tsx`, `api/scripts/verify_r_ui.cjs`, `verify_ui_staff.cjs`

**Interfaces:**
- `Screen onRefresh` + `BackButton parent="/staff"` + `PageHeader title={<>답변 알림 {안읽음 > 0 && <CountBadge tone="danger" />}</>} action={<TextButton>새로고침</TextButton>}`.
- 줄마다 `<button data-notice>`: 안 읽은 것은 초록 점 + 굵은 제목, 읽은 것은 `opacity-60`. 본문 두 줄 자르기. 누르면 읽음 저장 → 성공하면 대화 주소면 그 대화로(`router.push`), 아니면 그 자리. 누르는 순간 줄이 살짝 커지는 확대(`scale-[1.02]` 전환, `data-opening`).
- 실패는 `ErrorInline`(지금처럼 머문다). 빈 목록 `Empty title="아직 도착한 답이 없어요"`. 이전 알림 더 보기 그대로.

- [ ] **Step 1: 테스트 작성**

```js
test('s09a 답변 알림: 뱃지, 누르면 대화로', async (b) => {
  const { page, ctx, api } = await open(b, 'STAFF', '/staff/notifications/v2');
  await page.getByRole('heading', { name: /답변 알림/ }).getByText('1', { exact: true }).waitFor();
  await page.locator('[data-notice]', { hasText: '사장님 답이 왔어요' }).click();
  await page.waitForURL(/\/staff\/ask\?session_id=1/);
  assert.equal(api.state.rNotifications[0].read, true);
  await ctx.close();
});
test('s09a 읽음 실패면 머문다', async (b) => {
  const { page, ctx } = await open(b, 'STAFF', '/staff/notifications/v2', { overrides: { failRRead: true } });
  await page.locator('[data-notice]').first().click();
  await page.getByText('읽음 저장 실패').waitFor();
  assert.equal(here(page), '/staff/notifications/v2');
  await ctx.close();
});
test('s09a 당겨서 새로고침', async (b) => {
  const { page, ctx, api } = await open(b, 'STAFF', '/staff/notifications/v2', { touch: true });
  const count = () => api.calls.filter((c) => c.path.startsWith('/learn/v2/notifications') && c.method === 'GET').length;
  const before = count();
  const cdp = await ctx.newCDPSession(page);
  const box = await page.locator('main').boundingBox();
  const at = (type, y) => cdp.send('Input.dispatchTouchEvent', { type, touchPoints: type === 'touchEnd' ? [] : [{ x: box.x + 100, y }] });
  await at('touchStart', box.y + 60);
  for (let y = box.y + 60; y <= box.y + 360; y += 20) await at('touchMove', y);
  await at('touchEnd', box.y + 360);
  await page.waitForTimeout(800);
  assert.ok(count() > before);
  await ctx.close();
});
```

- [ ] **Step 2: 실패 확인** — Expected: 3 FAIL
- [ ] **Step 3: 구현** — Interfaces 대로. `verify_r_ui.cjs`: `아직 도착한 답변 알림이 없습니다.` → `아직 도착한 답이 없어요`, `답변 확인` 버튼 → `[data-notice]` 줄.
- [ ] **Step 4: 통과 확인** — Expected: `ui-staff` 18 PASS, 다른 묶음·기존 스크립트 PASS

---

### Task 5: 로그인·이메일 (a01a·a02a)

**Files:** Modify `web/app/page.tsx`, `web/app/auth/email/page.tsx`, `verify_ui_staff.cjs`

**Interfaces:**
- 로그인(`/`): 키트 화면. 버디 그림은 한 번 통통 튄다(`data-bounce`, `animate-[buddy-bounce_600ms_var(--ease-spring)]`, `globals.css` 에 `@keyframes buddy-bounce` 0%→`translateY(0)` 40%→`translateY(-16px)` 70%→`translateY(0) scaleY(.96)` 100%→`translateY(0)`; reduced-motion 이면 없음). 제목·문구·버튼 셋은 `Stagger` 차례 등장. 카카오·`이메일로 시작하기`(링크)·안내 글은 그대로.
- 이메일(`/auth/email`): `BackButton parent="/"`. 제목 로그인 `이메일로 시작해요`, 가입 `처음 오셨군요, 반가워요`. 칸마다 보이는 이름(`label`)과 칸 아래 빨간 글: 이메일은 칸을 떠날 때 형식이 틀리면 `이메일 형식을 확인해 주세요`, 비밀번호는 6자 미만이면 `비밀번호는 6자 이상이에요`. 오류 칸은 `aria-invalid` + 빨간 테두리. 형식 오류가 있으면 보내지 않는다. 서버 401 은 비밀번호 칸 아래 `이메일 또는 비밀번호를 확인해 주세요.`, 409 는 이메일 칸 아래 `이미 가입된 이메일입니다. 로그인해 주세요.`. 버튼은 키트 `Button loading`. 모드 바꾸기는 `TextButton`.

- [ ] **Step 1: 테스트 작성**

```js
test('a01a 로그인 첫 화면: 버디가 튀고 차례로 나온다', async (b) => {
  const { page, ctx } = await open(b, 'STAFF', '/', { overrides: { signedOut: true } });
  await page.getByRole('link', { name: '이메일로 시작하기' }).waitFor();
  assert.equal(await page.locator('[data-bounce]').count(), 1);
  assert.ok(await page.locator('[data-stagger]').count() >= 1);
  await ctx.close();
});
test('a02a 형식이 틀리면 보내지 않고 칸 아래 빨간 글', async (b) => {
  const { page, ctx, api } = await open(b, 'STAFF', '/auth/email', { overrides: { signedOut: true } });
  await page.getByRole('heading', { name: '이메일로 시작해요' }).waitFor();
  assert.equal(await page.getByText('다시 만나 반가워요').count(), 0);
  const email = page.getByLabel('이메일');
  await email.fill('owner-at-test');
  await page.getByLabel('비밀번호').fill('123');
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  await page.getByText('이메일 형식을 확인해 주세요').waitFor();
  await page.getByText('비밀번호는 6자 이상이에요').waitFor();
  assert.equal(await email.getAttribute('aria-invalid'), 'true');
  assert.equal(api.calls.filter((c) => c.path === '/auth/login').length, 0);
  await ctx.close();
});
test('a02a 서버가 거절하면 비밀번호 칸 아래, 맞으면 들어간다', async (b) => {
  const { page, ctx } = await open(b, 'STAFF', '/auth/email', { overrides: { signedOut: true } });
  await page.getByLabel('이메일').fill('staff@synthetic.test');
  await page.getByLabel('비밀번호').fill('wrong-pass');
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  await page.getByText('이메일 또는 비밀번호를 확인해 주세요.', { exact: true }).waitFor();
  assert.equal(await page.getByLabel('비밀번호').getAttribute('aria-invalid'), 'true');
  await page.getByLabel('비밀번호').fill('right-pass');
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  await page.waitForURL((u) => u.pathname === '/staff');
  await ctx.close();
});
```

- [ ] **Step 2: 실패 확인** — Expected: 3 FAIL
- [ ] **Step 3: 구현** — Interfaces 대로. `verify_ui_rebrand.cjs` 의 로그인 흐름(이름·이메일·비밀번호 칸, `로그인`·`가입하기`, 401 문구)은 그대로 통과해야 한다.
- [ ] **Step 4: 통과 확인** — Expected: `ui-staff` 21 PASS, `ui-nav`·`ui-intake`·`ui-cards`·`ui-today`·`ui-manage` 유지, 기존 스크립트(`verify_r_ui`, `verify_r_history_ui`, `verify_ui_rebrand`, `verify_w3b_card_facts_ui`, `verify_ui_checklist`)·`verify_ui_owner_ops` PASS, `pnpm check` 통과

---

## 이 계획에서 하지 않는 것(백로그로)

- 직원 대기(`/staff/pending`)·합류(`/join`)·역할 고르기(`/auth/role`)·옛 직원 대화(`/staff/chat`) 화면의 키트 옮기기.
- 오늘 할 일 칩으로 고른 질문을 버디가 바로 보내기(지금은 채우기만. 화면 진입 자동 전송은 새로고침 때 다시 보낼 위험).
