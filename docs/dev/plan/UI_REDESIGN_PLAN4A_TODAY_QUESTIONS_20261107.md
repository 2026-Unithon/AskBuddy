# 화면 개선 계획 4a: 오늘 매장·직원 질문 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 사장님 오늘 매장(o01)과 직원 질문 목록·답하기·답한 뒤(o09~o11)를 사용자 결정대로 바꾼다. 질문은 화면 이동 없이 아래에서 올라오는 시트로 바로 답한다.

**Architecture:** 답하기 로직(멱등 request_id, 409 충돌, 무효화)을 질문 상세 화면에서 `useOwnerAnswer` 훅과 `QuestionAnswerForm` 으로 떼어 오늘 매장·질문 목록의 시트와 상세가 같이 쓴다. 키트에 코치마크·세그먼트·스크롤에 숨는 footer·탭 뱃지와 스프링 알약을 더한다. **서버 API·DB 는 바꾸지 않는다.** 계획 4는 둘로 나눴다(4a 오늘 매장·질문, 4b 설정·관리·옛 화면).

**Tech Stack:** Next.js 16 App Router, React 19, Tailwind 4, TanStack Query 5, Playwright 1.62(합성 API), Node 24 `node --test`.

**Spec:** `docs/dev/plan/UI_REDESIGN_SPEC_20261106.md` (o01a~f, o09a~c, o10a~c, o11a~b)

## Global Constraints

- 계획 1~3 제약 전부(중간점 금지, 모션 토큰, 피드백 기준, 합성 API, 서버 무변경, 진행률 % 금지).
- 오늘 매장에는 main(cecca61)에서 들어온 '매장 리포트' 링크, 오늘만 할 일(`TodayTasksSection`), '응대 매뉴얼 만들기' 링크가 있다. 지우지 않고 자리만 정리한다.
- 코치마크·'나중에' 순서는 그 기기 사용자 편의라 브라우저 저장소에 둔다(서버 데이터 아님). 저장소를 못 써도 화면은 동작해야 한다.
- 서버가 필요한 것은 만들지 않고 백로그에 적는다: 질문 목록의 '몇 번 물어봤어요'(목록 응답에 횟수 없음), 근무조 줄을 누르면 그 근무조 현황으로 커지는 전환(근무조별 현황 화면 없음).

## Review Focus

1. **시트로 답하는 중 같은 질문에 다른 사람이 먼저 답함(409)**: 입력은 그대로 두고 "그사이 답이 바뀌었어요"로 알린다 → Task 3 `o01d 시트 답하기 충돌이면 입력이 남는다`.
2. **시트에서 보내기를 연타**: 같은 request_id 로 한 번만 저장된다 → Task 3 `o01d 보내기를 연타해도 한 번만`.
3. **코치마크가 떠 있는데 대상(설정 버튼 등)이 아직 안 그려짐**: 대상이 생길 때까지 기다리고, 끝내 없으면 그 단계를 건너뛴다 → Task 1 `키트 코치마크 대상이 없으면 건너뛴다`.
4. **입력창을 스크롤로 숨긴 채 질문 시트를 엶**: 시트는 화면 전체를 덮어 숨은 footer 와 상관없이 보인다 → Task 2 `o01e 스크롤 내리면 입력창이 숨고 올리면 나온다`(시트 열기 포함).
5. **'나중에'로 미룬 질문이 하나뿐**: 목록 끝으로 가도 자리는 그대로 하나라 사라진 것처럼 보이면 안 된다 → Task 3 `o01d 밀어서 나중에는 목록 끝으로`.

---

## 파일 구조

| 파일 | 책임 |
|---|---|
| `web/components/kit/coachmark.tsx` (새) | 처음 한 번 안내(대상 강조 + 말풍선, 다음·건너뛰기) |
| `web/components/kit/segmented.tsx` (새) | 얇은 세그먼트(`role="tablist"`) |
| `web/components/kit/screen.tsx` | `hideFooterOnScroll` |
| `web/components/kit/tab-bar.tsx` | 탭 뱃지, 스프링으로 움직이는 활성 알약 |
| `web/lib/card-review-count.ts` (새) | 카드 '검수 필요' 수 훅(목록 뱃지와 탭 뱃지 공용) |
| `web/components/owner/use-owner-answer.ts` (새) | 답 보내기 mutation(상세에서 옮김) |
| `web/components/owner/question-answer-form.tsx` (새) | 답 입력·첨부(📎)·보내기 폼 |
| `web/components/owner/question-sheet.tsx` (새) | 질문을 누르면 올라오는 답하기 시트 |
| `web/components/owner/use-answer-attachments.ts` (새) | 첨부 상태·올리기(지금 `owner-answer-attachments.tsx` 에서 옮김) |
| `web/components/checklist/owner-status.tsx` | 오늘 매장 현황 카드(o01b·o01c) |
| `web/app/owner/page.tsx` | 오늘 매장(o01) |
| `web/app/owner/questions/questions-list.tsx` | 질문 목록(o09) |
| `web/app/owner/questions/[pendingId]/page.tsx` | 질문 상세·답한 뒤(o10·o11) |
| `api/scripts/ui_fixture.cjs` | 답 저장·충돌·첨부 |
| `api/scripts/verify_ui_today.cjs` (새) | 이 계획 회귀 |

---

### Task 1: 키트 — 코치마크, 세그먼트, 숨는 footer, 탭 뱃지·스프링 알약

**Files:** Create `web/components/kit/coachmark.tsx`, `web/components/kit/segmented.tsx`, `web/lib/card-review-count.ts`, `api/scripts/verify_ui_today.cjs` / Modify `web/components/kit/screen.tsx`, `web/components/kit/tab-bar.tsx`, `web/components/kit/index.ts`, `web/app/dev/kit/page.tsx`, `web/app/owner/cards/page.tsx`(뱃지 계산을 훅으로), CI·`run-ui.sh`

**Interfaces:**
- `Coachmark({ id, steps }: { id: string; steps: { target: string; text: string }[] })` — `localStorage["askbuddy:coach:" + id] === "done"` 이면 그리지 않는다(읽기 실패면 보여 준다). 각 단계: `document.querySelector(target)` 를 최대 2초 기다려 찾고, 없으면 그 단계를 건너뛴다. 찾으면 화면을 `bg-ink/50` 으로 덮고 대상 둘레를 비운 강조 테두리(`rounded-[16px] ring-4 ring-white`) + 아래(공간 없으면 위) 말풍선. 말풍선 `role="dialog" aria-label="안내"`, 글, 버튼 '다음'(마지막은 '알겠어요'), 작은 글자 '건너뛰기'. 끝나거나 건너뛰면 `done` 저장. Esc 는 건너뛰기.
- `Segmented({ label, value, options, onChange }: { label: string; value: string; options: { value: string; label: string; badge?: number }[]; onChange: (value: string) => void })` — 한 덩어리 알약 안 버튼들(`role="tab" aria-selected`), 선택은 흰 바탕 그림자, 높이 40, 뱃지는 `CountBadge`.
- `Screen({ ..., hideFooterOnScroll })` — 참이면 `main` 을 아래로 24px 넘게 스크롤하면 footer 를 `translateY(110%)`, 위로 스크롤하면 원위치(`--dur-base`, `--ease-out`). 맨 아래에 닿으면 보인다.
- `TabBar({ tabs, badges })` — `badges?: Record<string, number>`(키는 탭 href). 0 보다 크면 아이콘 오른쪽 위 빨간 `CountBadge tone="danger"`. 활성 배경은 탭마다 따로 그리지 않고 하나의 알약이 활성 탭 위치로 `transform` 이동(`--ease-spring`, `--dur-base`), `data-tab-pill`.
- `useCardReviewCount(): number` — 계획 3 카드 목록의 뱃지 계산(검수 필요 카드 id 와 제안 대상 id 의 합집합 크기)을 그대로 옮긴다. 카드 목록과 오늘 매장 탭바가 같이 쓴다.
- 개발 키트 `?s=guide`: `Coachmark id="dev"` 두 단계(`#coach-a` "첫 번째", `#coach-b` "두 번째", `#coach-missing` "없는 대상"은 셋째로 넣어 건너뛰기 확인), `Segmented` 하나(가·나), `hideFooterOnScroll` 화면.

- [ ] **Step 1: 테스트 작성** — `verify_ui_today.cjs`(머리는 다른 묶음과 같은 모양, 이름 `ui-today`)

```js
test('키트 코치마크는 차례로 보이고 끝나면 다시 안 뜬다', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/dev/kit?s=guide', { overrides: { coach: true } });
  const bubble = page.getByRole('dialog', { name: '안내' });
  await bubble.getByText('첫 번째').waitFor();
  await bubble.getByRole('button', { name: '다음' }).click();
  await bubble.getByText('두 번째').waitFor();
  await bubble.getByRole('button', { name: '알겠어요' }).click();
  await bubble.waitFor({ state: 'hidden' });
  await page.reload({ waitUntil: 'networkidle' }); await page.waitForTimeout(500);
  assert.equal(await bubble.count(), 0);
  await ctx.close();
});
test('키트 코치마크 대상이 없으면 건너뛴다', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/dev/kit?s=guide', { overrides: { coach: true } });
  const bubble = page.getByRole('dialog', { name: '안내' });
  await bubble.getByRole('button', { name: '다음' }).click();
  await bubble.getByText('두 번째').waitFor();
  assert.equal(await page.getByText('없는 대상').count(), 0);
  await ctx.close();
});
test('키트 세그먼트는 하나만 선택된다', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/dev/kit?s=guide');
  const seg = page.getByRole('tablist', { name: '예시 세그먼트' });
  await seg.getByRole('tab', { name: '나' }).click();
  assert.equal(await seg.getByRole('tab', { name: '나' }).getAttribute('aria-selected'), 'true');
  assert.equal(await seg.getByRole('tab', { name: '가' }).getAttribute('aria-selected'), 'false');
  await ctx.close();
});
```

- [ ] **Step 2: 실패 확인** — Expected: 3 FAIL(`?s=guide` 없음)
- [ ] **Step 3: 구현** — Interfaces 대로. 카드 목록 뱃지는 `useCardReviewCount` 로 바꾼 뒤 `ui-cards` 가 그대로 통과해야 한다.
- [ ] **Step 4: 통과 확인** — Expected: 3 PASS, `ui-nav 30`·`ui-intake 27`·`ui-cards 35` 유지

---

### Task 2: 오늘 매장 머리·현황·입력창·탭 (o01a·o01b·o01c·o01e·o01f)

**Files:** Modify `web/app/owner/page.tsx`, `web/components/checklist/owner-status.tsx`, `web/components/kit/hero.tsx`(진행 막대 등장)
**Interfaces:**
- 코치마크(o01a): 오늘 매장 처음 들어올 때 `Coachmark id="owner-home"` — 1 `[aria-label="설정"]` "매장 설정은 여기서 바꿔요", 2 `[aria-label^="알림"]` "질문이 오면 여기에 알려 드려요", 3 `textarea[aria-label="새로 알려줄 것"]` "사진, 파일, 글 아무거나 넣으면 정리해 드려요".
- 현황 카드(o01b·o01c): 제목은 남은 수 하나 — 지금 근무조가 있고 남은 게 있으면 "<근무조> <N>개 남았어요", 근무조 없이 남은 게 있으면 "<N>개 남았어요", 다 했으면 "오늘 할 일 끝!". 진행 막대는 처음 그릴 때 0에서 현재 값으로 `--dur-base`·`--ease-out`(`HeroProgress` 가 첫 프레임 0 뒤 값). 근무조 줄은 지금처럼(누르기 없음, 확대 전환은 백로그). 카드 아래 큰 버튼 '내 기록과 알바생 기록 보기'를 없애고 카드 안 오른쪽 아래 링크 **"기록 보기 ›"**(`/owner/me`). 할 일이 없을 때 안내 줄에도 "기록 보기 ›".
- 입력창(o01e): `Screen hideFooterOnScroll`.
- 탭(o01f): `TabBar badges={{ "/owner/cards": useCardReviewCount() }}`.

- [ ] **Step 1: 테스트 작성**

```js
test('o01a 처음 들어오면 설정 알림 넣기 순서로 안내', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner', { overrides: { coach: true } });
  const bubble = page.getByRole('dialog', { name: '안내' });
  await bubble.getByText('매장 설정은 여기서 바꿔요').waitFor();
  await bubble.getByRole('button', { name: '다음' }).click();
  await bubble.getByText('질문이 오면 여기에 알려 드려요').waitFor();
  await bubble.getByRole('button', { name: '건너뛰기' }).click();
  await page.reload({ waitUntil: 'networkidle' }); await page.waitForTimeout(500);
  assert.equal(await bubble.count(), 0);
  await ctx.close();
});
test('o01b 현황 제목은 남은 수 하나, 기록 보기는 카드 안 링크', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner');
  await page.getByText('오픈 2개 남았어요').waitFor();
  assert.equal(await page.getByText(/^체크 \d+\/\d+개$/).count(), 0);
  assert.equal(await page.getByRole('link', { name: '내 기록과 알바생 기록 보기' }).count(), 0);
  await page.getByRole('link', { name: /기록 보기/ }).click(); await to(page, '/owner/me');
  await ctx.close();
});
test('o01e 스크롤 내리면 입력창이 숨고 올리면 나온다', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner', { viewport: { width: 390, height: 600 } });
  const box = page.getByLabel('새로 알려줄 것');
  const visibleBottom = async () => box.evaluate((el) => el.getBoundingClientRect().top < innerHeight);
  assert.equal(await visibleBottom(), true);
  await page.locator('main').evaluate((m) => { m.scrollTop = 200; m.dispatchEvent(new Event('scroll')); });
  await page.waitForTimeout(400);
  assert.equal(await visibleBottom(), false);
  await page.locator('main').evaluate((m) => { m.scrollTop = 0; m.dispatchEvent(new Event('scroll')); });
  await page.waitForTimeout(400);
  assert.equal(await visibleBottom(), true);
  await ctx.close();
});
test('o01f 카드 탭에 검수 필요 빨간 뱃지, 탭 알약은 하나', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner');
  const tab = page.getByRole('navigation', { name: '주요 메뉴' }).getByRole('link', { name: /카드/ });
  assert.equal((await tab.innerText()).replace(/\D/g, ''), '2');
  assert.equal(await page.locator('[data-tab-pill]').count(), 1);
  await ctx.close();
});
```


- [ ] **Step 2: 실패 확인** — Expected: 4 FAIL
- [ ] **Step 3: 구현** — Interfaces 대로. 다른 묶음의 오늘 매장 테스트가 코치마크에 가리지 않게 `ui_harness.cjs` 의 `open` 은 `overrides.coach !== true` 면 `addInitScript` 로 코치마크를 모두 done 으로 둔다(`localStorage` 키 `askbuddy:coach:*`). 이 묶음의 o01a 테스트만 `{ overrides: { coach: true } }` 로 연다.
- [ ] **Step 4: 통과 확인** — Expected: 7 PASS, 다른 묶음 유지

---

### Task 3: 질문을 시트로 바로 답하기 (o01d·o09)

**Files:** Create `web/components/owner/use-owner-answer.ts`, `web/components/owner/question-answer-form.tsx`, `web/components/owner/question-sheet.tsx` / Modify `web/app/owner/page.tsx`, `web/app/owner/questions/questions-list.tsx`, `web/app/owner/questions/[pendingId]/page.tsx`(답 보내기를 훅으로), `api/scripts/ui_fixture.cjs`

**Interfaces:**
- `useOwnerAnswer(pendingId: string, { onSent }: { onSent?: () => void } = {}) → { answer, setAnswer, send, submit, latest }` — 지금 상세의 `submit` mutation·request_id·`submittedBody`·무효화를 그대로 옮긴다(동작 같음). `send()` 는 진행 중이거나 빈 글이면 아무것도 안 한다.
- `QuestionAnswerForm({ pendingId, onSent, autoFocus })` — 충돌(409)·오류 안내 + `Composer`(label "직원에게 보낼 답", 빈 글이면 '넣기' 비활성, 그 아래 12px 회색 "답을 적으면 보낼 수 있어요"는 포커스됐는데 비었을 때만).
- `QuestionSheet({ question, onClose })` — `Sheet` 제목 = 질문 문장, 설명 "한 번 답하면 다음 알바는 이걸 안 물어봐요", 안에 `QuestionAnswerForm`(autoFocus), 아래 작은 글자 링크 "자세히 보기"(`/owner/questions/<id>`). 보내면 시트를 닫고 `toast("답을 보냈어요")`.
- 오늘 매장 질문 목록(o01d): 각 질문은 `SwipeRow left={{ label: "나중에", tone: "neutral" }}` 안의 버튼 카드(누르면 시트), meta "한 번 답하면 다음 알바는 이걸 안 물어봐요", `Stagger`. '나중에'는 `sessionStorage["askbuddy:snoozed-questions"]` 에 id 를 넣고 목록 끝으로 보낸다(저장소를 못 쓰면 이번 화면에서만).
- 질문 목록(o09): '답변 대기 / 전체 이력' 큰 버튼 둘 → `Segmented label="질문 보기"`(답변 대기 옆 뱃지 = 대기 수). 대기 질문 카드는 '답변하기' 버튼 없이 카드 전체가 시트를 연다. 답한 질문은 상세로 간다. `Stagger`. 하단 탭 없음(계획 1 그대로).
- fixture: `POST /learn/v2/pending/:id/answers` — 본문을 `calls` 에 남기고 `request_id` 가 이미 있으면 같은 응답(멱등), `state.answerConflict` 가 참이면 409 `{ error: { code: "ANSWER_REVISION_CONFLICT", message: "답이 바뀌었습니다." } }`. 성공하면 그 질문 `status` 를 `ANSWERED`, `answers` 에 `{ owner_answer_id, answer, revision: 1, knowledge_status: "PENDING", event_id: null, attempts: 0, retry_available: false }`.

- [ ] **Step 1: 테스트 작성**

```js
test('o01d 질문을 누르면 시트로 바로 답하고, 보내면 목록에서 빠진다', async (b) => {
  const { page, ctx, api } = await open(b, 'OWNER', '/owner');
  await page.getByRole('button', { name: /디카페인 원두는 어디 있어요\?/ }).click();
  const sheet = page.getByRole('dialog', { name: '디카페인 원두는 어디 있어요?' });
  await sheet.getByText('한 번 답하면 다음 알바는 이걸 안 물어봐요').waitFor();
  await sheet.getByLabel('직원에게 보낼 답').fill('창고 오른쪽 맨 위 칸에 있어요');
  await sheet.getByRole('button', { name: '넣기' }).click();
  await page.getByRole('status').getByText('답을 보냈어요').waitFor();
  await sheet.waitFor({ state: 'hidden' });
  assert.equal(here(page), '/owner');
  assert.ok(api.calls.some((c) => c.method === 'POST' && c.path === '/learn/v2/pending/101/answers'));
  await page.getByRole('button', { name: /디카페인 원두는 어디 있어요\?/ }).waitFor({ state: 'hidden' });
  await ctx.close();
});
test('o01d 보내기를 연타해도 한 번만', async (b) => {
  const { page, ctx, api } = await open(b, 'OWNER', '/owner');
  await page.getByRole('button', { name: /디카페인/ }).click();
  const sheet = page.getByRole('dialog');
  await sheet.getByLabel('직원에게 보낼 답').fill('창고 오른쪽');
  await sheet.getByRole('button', { name: '넣기' }).dblclick();
  await page.waitForTimeout(500);
  const ids = new Set(api.calls.filter((c) => c.path === '/learn/v2/pending/101/answers').map((c) => c.body.request_id));
  assert.equal(ids.size, 1);
  await ctx.close();
});
test('o01d 시트 답하기 충돌이면 입력이 남는다', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner', { overrides: { answerConflict: true } });
  await page.getByRole('button', { name: /디카페인/ }).click();
  const sheet = page.getByRole('dialog');
  await sheet.getByLabel('직원에게 보낼 답').fill('창고 오른쪽');
  await sheet.getByRole('button', { name: '넣기' }).click();
  await sheet.getByText(/그사이 답이 바뀌었어요/).waitFor();
  assert.equal(await sheet.getByLabel('직원에게 보낼 답').inputValue(), '창고 오른쪽');
  await ctx.close();
});
test('o01d 밀어서 나중에는 목록 끝으로', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner');
  const order = async () => page.locator('main').getByRole('button', { name: /어디 있어요\?|2펌프인가요\?/ }).allInnerTexts();
  assert.ok((await order())[0].includes('디카페인'));
  await page.getByRole('button', { name: '나중에' }).first().press('Enter');
  await page.waitForTimeout(300);
  const after = await order();
  assert.ok(after.at(-1).includes('디카페인') && after.length === 2);
  await ctx.close();
});
test('o09 답변 대기 전체는 세그먼트, 카드를 누르면 시트', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/questions');
  const seg = page.getByRole('tablist', { name: '질문 보기' });
  assert.equal((await seg.getByRole('tab', { name: /답변 대기/ }).innerText()).replace(/\D/g, ''), '2');
  assert.equal(await page.getByRole('link', { name: '답변하기' }).count(), 0);
  await page.getByRole('button', { name: /오트밀크 라떼도 시럽 2펌프인가요\?/ }).click();
  await page.getByRole('dialog', { name: '오트밀크 라떼도 시럽 2펌프인가요?' }).waitFor();
  await ctx.close();
});
```

- [ ] **Step 2: 실패 확인** — Expected: 5 FAIL
- [ ] **Step 3: 구현** — Interfaces 대로. `verify_r_ui.cjs` 의 오늘 매장 → 질문 링크 단언(`link` 로 찾던 것)은 시트 버튼으로 고친다.
- [ ] **Step 4: 통과 확인** — Expected: 12 PASS, 다른 묶음·기존 스크립트 PASS

---

### Task 4: 질문 상세·답한 뒤 (o10a·o10b·o10c·o11a·o11b)

**Files:** Create `web/components/owner/use-answer-attachments.ts` / Modify `web/app/owner/questions/[pendingId]/page.tsx`, `web/components/owner/owner-answer-attachments.tsx`(목록 UI 만 남김), `web/components/owner/intake-hint-chips.tsx`(그대로 재사용)

**Interfaces:**
- o10a: 제목 아래 "직원이 <N>번 물어봤어요"(1번이면 "직원이 물어본 질문"), 2번 이상이면 그 옆 작은 버튼 "물어본 말 보기"(`aria-expanded`) → 펼치면 `occurrences[].original_question` 목록. 조건 칩(대상·온도 등)은 그대로.
- o10b: 본문의 첨부 상자(`attach-area`, '파일 첨부' 큰 버튼, 종류 칩)를 없앤다. `Composer` 도구에 `ComposerTool icon="clip" label="파일"` → 숨은 파일 입력. 붙인 파일은 입력창 첨부 자리에 줄로(계획 2 `FileRow` 와 같은 모양: 올리는 중 막대·끝 체크·실패 빨간 줄과 다시·빼기). 종류 칩(`IntakeHintChips`)은 파일이 하나 이상 붙었을 때만 입력창 아래에. 첨부 올리기 로직은 `useAnswerAttachments(questionId)` 로 옮기고 동작은 그대로(답과 별개로 바로 붙인다).
- o10c: 빈 글이면 '넣기' 비활성 + 포커스 시 "답을 적으면 보낼 수 있어요". 보내기 성공하면 화면 가운데 스프링 체크(`check-pop`)와 "답을 보냈어요", 아래 버튼 — 기다리는 다른 질문이 있으면 **"다음 질문 <N>개"**(가장 앞 질문 상세로 replace), 없으면 "오늘 매장으로".
- o11a: 답이 카드로 공개된 화면 — 분홍(accent) 테두리·'공개됨' 뱃지를 초록(`border-primary`, `bg-primary`)으로, '카드로 남았어요' 위에 스프링 체크 아이콘.
- o11b: '답 고치기'를 없앤다(공개된 화면과 답 상태 상자 모두). 고치기는 카드에서.

- [ ] **Step 1: 테스트 작성**

```js
test('o10a 여러 번 물어봤으면 물어본 말을 펼쳐 본다', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/questions/101');
  await page.getByText('직원이 2번 물어봤어요').waitFor();
  await page.getByRole('button', { name: '물어본 말 보기' }).click();
  assert.equal(await page.getByRole('listitem').filter({ hasText: '디카페인 원두는 어디 있어요?' }).count(), 2);
  await ctx.close();
});
test('o10b 첨부는 입력창의 파일 도구, 종류 칩은 붙인 뒤에만', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/questions/101');
  assert.equal(await page.getByTestId('attach-area').count(), 0);
  assert.equal(await page.getByRole('group', { name: '자료 종류' }).count(), 0);
  await page.locator('footer input[type=file], [data-composer] input[type=file]').first().setInputFiles({ name: '창고.jpg', mimeType: 'image/jpeg', buffer: Buffer.from('jpg') });
  await page.getByRole('group', { name: '자료 종류' }).waitFor();
  await page.getByRole('listitem').filter({ hasText: '창고.jpg' }).waitFor();
  await ctx.close();
});
test('o10c 보내면 체크와 다음 질문 버튼', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/questions/101');
  const box = page.getByLabel('직원에게 보낼 답');
  await box.focus();
  await page.getByText('답을 적으면 보낼 수 있어요').waitFor();
  assert.equal(await page.getByRole('button', { name: '넣기' }).isDisabled(), true);
  await box.fill('창고 오른쪽 맨 위 칸');
  await page.getByRole('button', { name: '넣기' }).click();
  await page.getByText('답을 보냈어요').waitFor();
  await page.getByRole('button', { name: '다음 질문 1개' }).click();
  await to(page, '/owner/questions/102');
  await ctx.close();
});
test('o11 공개된 화면은 초록, 답 고치기 없음', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/questions/103');
  await page.getByText('카드로 남았어요').waitFor();
  assert.equal(await page.getByText('공개됨', { exact: true }).getAttribute('data-tone'), 'success');
  assert.equal(await page.getByRole('button', { name: '답 고치기' }).count(), 0);
  await ctx.close();
});
```

  fixture: 질문 103 '포스 영수증 용지 교체는 어떻게 해요?' — `status: ANSWERED`, `answers: [{ owner_answer_id: '7', answer: '포스 오른쪽 서랍 안에 예비 용지 있어요.', revision: 1, knowledge_status: 'PUBLISHED', knowledge_availability: 'CURRENT', … }]`. 대기 목록(`status=WAITING`)에는 나오지 않는다.

  '공개됨' 뱃지는 `data-tone="success"` 를 붙인다.
- [ ] **Step 2: 실패 확인** — Expected: 4 FAIL
- [ ] **Step 3: 구현** — Interfaces 대로. `verify_r_ui.cjs`·`verify_wb_answer_attach_ui.cjs`(백로그로 이미 실패 중) 중 CI 스크립트인 `verify_r_ui.cjs` 의 첨부·답 고치기 단언은 이 결정대로 고친다.
- [ ] **Step 4: 통과 확인** — Expected: `ui-today` 16개, `ui-nav 30`·`ui-intake 27`·`ui-cards 35`, 기존 CI 스크립트·`verify_ui_owner_ops.cjs`(OPS_UI_BASE=3011) PASS, `pnpm check` 통과

## 실행 순서와 확인

Task 1 → 2 → 3 → 4. 미룬 지적은 `UI_REDESIGN_BACKLOG_20261106.md` 에 이어 적는다.
