# 화면 개선 계획 2: 넣기 → 정리 중 → 검수 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 사장님이 자료를 넣고(o02), 정리되는 걸 보고(o03), 일 맡은 직원이 "검수 부탁드려요" 하듯 결과를 확인해 끝내는(o04) 흐름을 사용자 결정대로 바꾼다.

**Architecture:** 계획 1의 키트(이동 기록·피드백·`CountBadge`·모션 토큰) 위에 공용 조각 셋(`Stagger`, `SwipeRow`, `useLongPress`)을 더하고, 세 화면을 그것으로 다시 짠다. 진행 상태는 계속 서버 작업 상태(`ingestJobQuery`·`ingestJobsQuery`)가 정본이고, 화면은 그걸 단계로 보여 줄 뿐이다. 파일 올리기 진행률만 브라우저가 아는 값(XHR 업로드 진행)이다.

**Tech Stack:** Next.js 16 App Router, React 19, Tailwind 4, TanStack Query 5, Playwright 1.62(합성 API), Node 24 `node --test`.

**Spec:** `docs/dev/plan/UI_REDESIGN_SPEC_20261106.md` (o02a~c, o03a~c, o04a~c, 앱 전체 규칙)

## Global Constraints

- 계획 1의 제약 전부(중간점 금지, 모션 토큰, 토스트 2초·스낵바 5초, 합성 API 로만 검증, 커밋은 사용자가).
- 말투: 일 맡은 직원이 부탁하는 말. 명령조 금지(o04a). 결과 화면 제목은 정확히 **"카드가 준비됐어요! 검수 부탁드려요!"**, 실패 배너 첫 줄은 정확히 **"처리하지 못한 자료가 있어요."**, 끝났을 때 알림은 정확히 **"정리 끝!"**, 검수 완료 토스트는 정확히 **"지식이 추가됐어요"**.
- 결과 화면 버튼: 주 버튼 **"검수 완료"** 하나 + 그 아래 작은 글자 버튼 **"나중에 하기"**(o04c, 2026-11-06 확정 문구). "맞아요", "더 넣기", "하나씩 봐 주세요", 결과 화면 아래 '출처' 글씨는 없앤다.
- 진행률 숫자(%)를 화면에 쓰지 않는다(CLAUDE.md "근거 없는 완성도 퍼센트" 금지). 파일 올리기는 막대만, 정리 단계는 단계 이름만.
- 서버 API·DB 는 바꾸지 않는다(W 담당 계약 그대로). 이 계획은 `web/` 와 합성 fixture·검사 스크립트만 바꾼다.

## Review Focus

1. **자료 여러 개 중 일부만 올라가지 못한 경우**: 올라간 것으로 작업이 만들어져 넘어가면 실패한 파일 안내가 사라진다. 실패한 파일만 남아 있을 때는 넣기 화면에 남고 그 파일 줄에 이유와 '다시'가 보여야 한다 → Task 3 `o02b 올리기 실패한 파일은 빨간 줄과 다시`.
2. **검수 화면에서 '빼기' 직후 다른 카드도 빼기**: 스낵바는 하나만이므로 첫 번째 되돌리기는 사라진다. 첫 번째 빼기는 이미 저장됐어야 하고 화면에서도 빠져 있어야 한다 → Task 5 `o04b 연달아 빼면 앞의 것은 그대로 빠져 있다`.
3. **정리가 끝나는 순간 사장님이 그 작업 화면에 있을 때**: 스낵바('보기')가 아니라 토스트만 떠야 한다(이미 보고 있음) → Task 4 `o03c 작업 화면에 있으면 토스트, 다른 화면이면 보기 스낵바`.
4. **검수 필요 카드를 그대로 두고 '검수 완료'**: 공개할 카드만 공개하고 넘어가며, 검수 필요 카드는 공개되지 않고 남는다 → Task 5 `o04c 검수 완료는 잘된 카드만 공개하고 토스트 뒤 오늘 매장`.
5. **길게 누르기와 스크롤**: 목록을 손가락으로 스크롤하다 멈춰도 길게 누르기로 잘못 열리면 안 된다(움직이면 취소) → Task 2 `키트 길게 누르기는 움직이면 열리지 않는다`.

---

## 파일 구조

| 파일 | 책임 |
|---|---|
| `api/scripts/ui_harness.cjs` (새) | Playwright 공용 실행기: `open`, `back`, `to`, `phoneBack`, `test`, `run` |
| `api/scripts/verify_ui_nav.cjs` | 공용 실행기를 쓰도록 머리 부분만 교체 |
| `api/scripts/ui_fixture.cjs` | 작업 상태·카드 변경·업로드 지연/실패 덮어쓰기 추가 |
| `api/scripts/verify_ui_intake.cjs` (새) | 이 계획의 브라우저 회귀 |
| `web/components/kit/stagger.tsx` (새) | 차례 등장(자식마다 50ms) |
| `web/components/kit/swipe-row.tsx` (새) | 밀어서 동작(왼쪽·오른쪽) |
| `web/lib/use-long-press.ts` (새) | 길게 누르기(500ms, 10px 움직이면 취소) |
| `web/components/kit/feedback.tsx` | `toast(message, { keepOnNavigate })` |
| `web/app/dev/kit/page.tsx` | `?s=gestures` 미리보기 |
| `web/lib/api.ts` | `putToStorage` 진행률 콜백(XHR) |
| `web/lib/ingest-submit.ts` | `submitIngest` 항목별 진행 콜백 |
| `web/components/owner/owner-add-composer.tsx` | 파일 진행 줄·실패 줄·제어형 글 입력 |
| `web/components/owner/intake-hint-chips.tsx` | 칩 모양(o02c) |
| `web/app/owner/add/page.tsx` | 예시 칩·차례 등장(o02a) |
| `web/components/owner/job-steps.tsx` (새) | 정리 단계 표시(o03a) |
| `web/components/owner/job-steps-logic.ts` (새) | 서버 상태 → 단계 번호(순수 함수) |
| `web/tests/job-steps.test.mjs` (새) | 단계 번호 단위 테스트 |
| `web/app/owner/jobs/[jobId]/page.tsx` | 정리 중·결과 화면(o03·o04) |
| `web/components/owner/review-card.tsx` (새) | 결과 카드 모양·빼기·길게 누르기 시트 |
| `web/components/owner-job-monitor.tsx` | 끝났을 때 알림(o03c) |
| `web/components/owner/finished-job-banner.tsx` (새) | 오늘 매장 '정리 끝!' 배너 |
| `web/app/owner/page.tsx` | 배너 자리 |

---

### Task 1: 공용 브라우저 실행기와 fixture 확장

**Files:**
- Create: `api/scripts/ui_harness.cjs`, `api/scripts/verify_ui_intake.cjs`
- Modify: `api/scripts/verify_ui_nav.cjs`, `api/scripts/ui_fixture.cjs`, `.github/workflows/r-validation.yml`, `.superpowers/sdd/<plan>/run-ui.sh`(로컬 실행용, 저장소 밖)

**Interfaces:**
- Produces (`ui_harness.cjs`):
  - `createSuite(label) → { test(name, fn), run() }` — `run()` 은 `process.argv[2]` 로 이름 앞부분 필터, 각 테스트 뒤 그 테스트에서 연 fixture 의 `misses` 가 비었는지 단언, 끝에 `"${label} N passed"` 출력, 실패 시 exit 1.
  - `open(browser, role, url, { viewport?, overrides? }) → { ctx, page, api }` — 지금 `verify_ui_nav.cjs` 의 `open` 그대로(`pageerror` 도 misses 에 넣는다).
  - `back(page)`, `to(page, path)`, `phoneBack(page)`, `here(page)`, `BASE` — 지금 정의 그대로.
- Produces (`ui_fixture.cjs` overrides·state):
  - `overrides.job = { status, sources? }` — `GET /ingest/jobs/7` 이 이 값을 쓴다. `sources` 를 빼면 기본 소스 1개(레시피 메모.jpg, 상태는 작업 상태를 따름). 기본은 SUCCEEDED.
  - `state.jobSequence: string[]` — 있으면 `GET /ingest/jobs/7`·`GET /ingest/jobs` 를 부를 때마다 앞에서 하나씩 꺼내 `job.status` 로 쓴다(마지막 값은 유지). 정리 중 → 끝 전환 테스트용.
  - `GET /ingest/jobs` 는 `[{ job_id: 7, status: job.status, source_count, card_count: 4, created_at, completed_at }]` 를 돌려준다.
  - 카드 변경: `POST /cards/:id/(approve|exclude|restore)` 는 `state.cards` 의 `review_status` 를 바꾸고 `CardMutationResult` 를 돌려준다. `PATCH /cards/:id/category` 는 `category_id` 를 바꾼다. 호출은 `calls` 에 남는다.
  - 업로드: `overrides.uploadDelayMs`(기본 0) 만큼 `PUT /storage/put` 응답을 늦추고, `overrides.failUpload === true` 면 500.
  - 카드 목록 `GET /cards?job_id=7` 는 `job_id === 7` 인 카드만, `status=pending` 등 기존 필터도 그대로.

- [ ] **Step 1: 실행기 분리** — `verify_ui_nav.cjs` 의 머리(require ~ `phoneBack`, 실행 루프)를 `ui_harness.cjs` 로 옮기고, `verify_ui_nav.cjs` 는 `const { createSuite, open, back, to, phoneBack, here, BASE } = require('./ui_harness.cjs'); const { test, run } = createSuite('ui-nav'); … run();` 로 바꾼다.
- [ ] **Step 2: 회귀 확인** — Run: `run-ui.sh` (pnpm check → next start → `verify_ui_nav.cjs`) / Expected: `ui-nav 30 passed`(계획 1 결과와 같음).
- [ ] **Step 3: 새 스크립트 뼈대와 fixture 테스트** — `verify_ui_intake.cjs`:

```js
// 넣기 → 정리 중 → 검수 회귀(화면 개선 계획 2). 합성 API(ui_fixture.cjs)만 쓴다.
const assert = require('node:assert/strict');
const { createSuite, open, back, to, here, BASE } = require('./ui_harness.cjs');
const { test, run } = createSuite('ui-intake');

test('fixture 작업 상태 순서대로 넘어간다', async (b) => {
  const { page, ctx, api } = await open(b, 'OWNER', '/owner/jobs/7', { overrides: { jobSequence: ['EXTRACTING', 'SUCCEEDED'] } });
  await page.getByText('카드가 준비됐어요! 검수 부탁드려요!').waitFor({ timeout: 8000 });
  assert.ok(api.calls.filter((c) => c.path.startsWith('/ingest/jobs/7')).length >= 2);
  await ctx.close();
});

run();
```

  CI browser 잡과 `run-ui.sh` 에 `node api/scripts/verify_ui_intake.cjs` 를 `verify_ui_nav.cjs` 다음 줄로 넣는다.
- [ ] **Step 4: 실패 확인** — Expected: FAIL(제목 글이 아직 "이렇게 나눴어요"). fixture 오류(`misses`)로 실패하면 fixture 를 먼저 고친다. 이 테스트는 Task 5 에서 통과한다.
- [ ] **Step 5: fixture 구현** — 위 Interfaces 대로. `ui-nav` 30개가 그대로 통과해야 한다.

---

### Task 2: 키트에 차례 등장·밀기·길게 누르기·이동해도 남는 토스트

**Files:**
- Create: `web/components/kit/stagger.tsx`, `web/components/kit/swipe-row.tsx`, `web/lib/use-long-press.ts`
- Modify: `web/components/kit/feedback.tsx`, `web/components/kit/index.ts`, `web/app/globals.css`, `web/app/dev/kit/page.tsx`
- Test: `api/scripts/verify_ui_intake.cjs`

**Interfaces:**
- Produces:
  - `Stagger({ children, step = 50 }: { children: ReactNode; step?: number })` — 자식마다 `style={{ "--stagger-i": i }}` 를 주고 `animation: stagger-in var(--dur-base) var(--ease-out) both; animation-delay: calc(var(--stagger-i) * <step>ms)`. 키프레임 `stagger-in`: opacity 0, translateY(8px) → 원위치. `data-stagger` 속성을 둔다.
  - `SwipeRow({ children, left, right }: { children: ReactNode; left?: SwipeAction; right?: SwipeAction })`, `type SwipeAction = { label: string; tone: "danger" | "primary" | "neutral"; onAction: () => void }` — `left` 는 왼쪽으로 밀 때(오른쪽에서 드러남), `right` 는 오른쪽으로 밀 때. 포인터로 72px 넘게 밀고 놓으면 `onAction`, 덜 밀면 제자리로(`--dur-base`, `--ease-out`). 가로 이동이 세로보다 클 때만 밀기로 잡아 세로 스크롤을 막지 않는다(`touch-action: pan-y`). 키보드·스크린리더용으로 드러나는 버튼은 늘 DOM 에 있고 `aria-label` 이 `label` 이다(포커스하면 보인다).
  - `useLongPress(onLongPress: () => void, { ms = 500, moveTolerance = 10 } = {}) → { onPointerDown, onPointerMove, onPointerUp, onPointerCancel, onContextMenu }` — 누른 채 `ms` 지나면 한 번 부르고, 그 사이 `moveTolerance` px 넘게 움직이면 취소. 길게 누르기가 일어난 뒤 이어지는 click 은 막는다(`onClickCapture` 가 아니라 반환 객체에 `onClick` 도 포함해 `preventDefault`).
  - `toast(message: string, opts?: { keepOnNavigate?: boolean })` — `keepOnNavigate` 면 주소가 바뀌어도 닫지 않는다(스낵바는 지금처럼 닫는다).
  - 개발 키트 `?s=gestures`: `Stagger` 로 '하나', '둘', '셋' 세 줄, `SwipeRow`(left: '빼기' → 화면 글 "뺐어요") 한 줄 '밀어 보세요', 길게 누르면 화면 글 "길게 눌렀어요" 가 나오는 버튼 '꾹 눌러 보세요', 버튼 '이동해도 남는 토스트'(→ `toast("남아 있어요", { keepOnNavigate: true })` 후 `router.push("/dev/kit?s=o6")`).

- [ ] **Step 1: 테스트 작성** (`verify_ui_intake.cjs` 에 추가)

```js
test('키트 차례 등장은 자식마다 지연이 늘어난다', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/dev/kit?s=gestures');
  const delays = await page.locator('[data-stagger] > *').evaluateAll((els) => els.map((e) => getComputedStyle(e).animationDelay));
  assert.deepEqual(delays.slice(0, 3), ['0s', '0.05s', '0.1s']);
  await ctx.close();
});
test('키트 왼쪽으로 밀면 동작, 조금만 밀면 제자리', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/dev/kit?s=gestures');
  const row = page.getByText('밀어 보세요');
  const box = await row.boundingBox();
  const swipe = async (dx) => {
    await page.mouse.move(box.x + box.width - 10, box.y + box.height / 2); await page.mouse.down();
    await page.mouse.move(box.x + box.width - 10 - dx, box.y + box.height / 2, { steps: 8 }); await page.mouse.up();
  };
  await swipe(30); await page.waitForTimeout(300);
  assert.equal(await page.getByText('뺐어요').count(), 0);
  await swipe(120);
  await page.getByText('뺐어요').waitFor();
  await ctx.close();
});
test('키트 밀기 동작은 키보드로도 된다', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/dev/kit?s=gestures');
  await page.getByRole('button', { name: '빼기' }).focus(); await page.keyboard.press('Enter');
  await page.getByText('뺐어요').waitFor();
  await ctx.close();
});
test('키트 길게 누르면 열리고 짧게 누르면 안 열린다', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/dev/kit?s=gestures');
  const btn = page.getByRole('button', { name: '꾹 눌러 보세요' });
  const box = await btn.boundingBox();
  await page.mouse.move(box.x + 10, box.y + 10); await page.mouse.down(); await page.waitForTimeout(150); await page.mouse.up();
  assert.equal(await page.getByText('길게 눌렀어요').count(), 0);
  await page.mouse.down(); await page.waitForTimeout(650); await page.mouse.up();
  await page.getByText('길게 눌렀어요').waitFor();
  await ctx.close();
});
test('키트 길게 누르기는 움직이면 열리지 않는다', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/dev/kit?s=gestures');
  const box = await page.getByRole('button', { name: '꾹 눌러 보세요' }).boundingBox();
  await page.mouse.move(box.x + 10, box.y + 10); await page.mouse.down();
  await page.mouse.move(box.x + 10, box.y + 40, { steps: 5 }); await page.waitForTimeout(650); await page.mouse.up();
  assert.equal(await page.getByText('길게 눌렀어요').count(), 0);
  await ctx.close();
});
test('키트 keepOnNavigate 토스트는 이동해도 남는다', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/dev/kit?s=gestures');
  await page.getByRole('button', { name: '이동해도 남는 토스트' }).click();
  await page.waitForURL(/s=o6/);
  await page.getByRole('status').getByText('남아 있어요').waitFor();
  await ctx.close();
});
```

- [ ] **Step 2: 실패 확인** — Run: `run-ui.sh` 다음 `verify_ui_intake.cjs 키트` / Expected: 6개 FAIL(`?s=gestures` 없음)
- [ ] **Step 3: 구현** — 위 Interfaces 대로.
- [ ] **Step 4: 통과 확인** — Expected: 키트 6개 PASS, `ui-nav 30 passed` 유지.

---

### Task 3: 넣기 화면 (o02a·o02b·o02c)

**Files:**
- Modify: `web/app/owner/add/page.tsx`, `web/components/owner/owner-add-composer.tsx`, `web/components/owner/intake-hint-chips.tsx`, `web/lib/api.ts`(`putToStorage`), `web/lib/ingest-submit.ts`
- Test: `api/scripts/verify_ui_intake.cjs`

**Interfaces:**
- Consumes: `Stagger` (Task 2)
- Produces:
  - `putToStorage(uploadUrl: string, file: File, onProgress?: (fraction: number) => void): Promise<void>` — `XMLHttpRequest` 로 PUT, `upload.onprogress` 에서 `loaded/total`. 상태 2xx 아니면 `Error("업로드 실패: <status>")`(지금 문구 유지).
  - `submitIngest({ ..., onItem? }: { ...; onItem?: (key: string, update: { status: "UPLOADING" | "DONE" | "FAILED"; progress?: number; message?: string }) => void })` — `key` 는 파일이면 `PickedFile.id`, 붙여 넣은 글이면 `"text"`.
  - `OwnerAddComposer({ placeholder, text, onTextChange })` — `text`/`onTextChange` 를 주면 제어형, 안 주면 지금처럼 내부 상태.
  - 넣기 화면 예시 칩(`role="group" aria-label="예시"`, 버튼 셋): '레시피' → `"바닐라 라떼는 얼음 가득, 시럽 2펌프, 우유 200에 샷 2개"`, '마감 순서' → `"마감 때는 머신 청소, 원두 소분, 쓰레기 정리 순서로 해요"`, '공지' → `"이번 주부터 오트밀크 추가는 500원 받아요"`. 누르면 입력창 글이 그 문장으로 바뀌고 입력창에 포커스.
  - 파일 줄(첨부 목록): 올리는 중 `role="progressbar"`(aria-valuenow 0~100, 글자 % 없음), 끝나면 체크 아이콘, 실패하면 빨간 테두리 + 이유 + '다시' 버튼(그 파일만 다시 올려 작업을 만든다).
  - 입력창 상태(텍스트 필드 상태): 포커스되면 입력 상자 테두리 `ring-2 ring-primary/40`. 글자 수 제한은 서버 capabilities 의 `TEXT.max_chars` 가 있을 때만 남은 글자를 크게(15px) 보여 주고, 넘으면 '넣기' 비활성 + "N자까지 넣을 수 있어요"(지금은 서버가 값을 안 주므로 보이지 않는다).
  - 종류 칩(o02c): 선택은 진한 배경(`bg-primary text-white`)만, 테두리 없음. 한 줄(`flex-nowrap overflow-x-auto`), 높이 32px·글자 12px·모서리 8px. 누를 수 있는 영역은 44px 유지(`before` 가상 요소로 위아래 6px 확장).
  - 넣기 화면 머리: 제목, 설명, 예시 칩을 `Stagger` 로.

- [ ] **Step 1: 테스트 작성**

```js
test('o02a 예시 칩을 누르면 입력창이 그 문장으로 채워진다', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/add');
  await page.getByRole('group', { name: '예시' }).getByRole('button', { name: '마감 순서' }).click();
  const box = page.getByLabel('새로 알려줄 것');
  assert.equal(await box.inputValue(), '마감 때는 머신 청소, 원두 소분, 쓰레기 정리 순서로 해요');
  assert.ok(await box.evaluate((el) => el === document.activeElement));
  await ctx.close();
});
test('o02b 파일을 올리는 동안 진행 막대, 끝나면 작업 화면', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/add', { overrides: { uploadDelayMs: 1500 } });
  await page.locator('input[type=file][multiple]').setInputFiles({ name: '마감표.png', mimeType: 'image/png', buffer: Buffer.from('png') });
  await page.getByRole('button', { name: '넣기', exact: true }).click();
  const bar = page.getByRole('progressbar', { name: '마감표.png 올리는 중' });
  await bar.waitFor();
  assert.ok(!(await page.locator('main, footer').first().innerText()).includes('%'));
  await to(page, '/owner/jobs/7');
  await ctx.close();
});
test('o02b 올리기 실패한 파일은 빨간 줄과 다시', async (b) => {
  const { page, ctx, api } = await open(b, 'OWNER', '/owner/add', { overrides: { failUpload: true } });
  await page.locator('input[type=file][multiple]').setInputFiles({ name: '흐린 사진.jpg', mimeType: 'image/jpeg', buffer: Buffer.from('jpg') });
  await page.getByRole('button', { name: '넣기', exact: true }).click();
  const row = page.getByRole('listitem').filter({ hasText: '흐린 사진.jpg' });
  await row.getByText('전송이 완료되지 않았어요', { exact: false }).waitFor();
  assert.equal(here(page), '/owner/add');
  api.state.failUpload = false;
  await row.getByRole('button', { name: '다시' }).click();
  await to(page, '/owner/jobs/7');
  await ctx.close();
});
test('o02c 종류 칩은 한 줄이고 선택하면 진한 배경만', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/add');
  const group = page.getByRole('group', { name: '자료 종류' });
  const tops = await group.getByRole('button').evaluateAll((els) => [...new Set(els.map((e) => Math.round(e.getBoundingClientRect().top)))]);
  assert.equal(tops.length, 1, '한 줄');
  const chip = group.getByRole('button', { name: '공지' });
  await chip.click();
  const style = await chip.evaluate((e) => { const s = getComputedStyle(e); return { radius: s.borderTopLeftRadius, height: e.getBoundingClientRect().height, border: s.borderTopWidth }; });
  assert.equal(style.radius, '8px'); assert.equal(style.height, 32); assert.equal(style.border, '0px');
  assert.equal(await chip.getAttribute('aria-pressed'), 'true');
  await ctx.close();
});
```

  fixture: `failUpload` 은 `api.state` 에서 읽어 테스트 도중 바꿀 수 있게 한다(Task 1 구현을 이 값 기준으로).
- [ ] **Step 2: 실패 확인** — Expected: 넷 다 FAIL
- [ ] **Step 3: 구현** — Interfaces 대로. 실패 파일이 있고 작업도 만들어진 경우(일부만 실패)는 지금처럼 작업 화면으로 넘어가되, 넘어가기 전 스낵바 대신 `toast("<파일명> 은(는) 올리지 못했어요", { keepOnNavigate: true })`.
- [ ] **Step 4: 통과 확인** — Expected: 4개 PASS, `ui-nav` 의 `NAV-2 넣기 → 작업 화면` 포함 전부 PASS.

---

### Task 4: 정리 중 화면과 끝났을 때 알림 (o03a·o03b·o03c)

**Files:**
- Create: `web/components/owner/job-steps.tsx`, `web/components/owner/finished-job-banner.tsx`
- Modify: `web/app/owner/jobs/[jobId]/page.tsx`(`Processing`, `SourceList`), `web/components/owner-job-monitor.tsx`, `web/app/owner/page.tsx`
- Test: `api/scripts/verify_ui_intake.cjs`

**Interfaces:**
- Consumes: `useFeedback` (계획 1), `Banner` (계획 1), `Skeleton`
- Produces:
  - `jobStepIndex(status: string): 0 | 1 | 2 | 3` (`web/components/owner/job-steps-logic.ts`, import 없는 순수 함수) — QUEUED→1, EXTRACTING→1, CLASSIFYING→2, 그 밖(끝난 상태)→3. 단계 이름 `["올렸어요", "읽는 중", "나누는 중"]`. 인덱스보다 앞 단계는 체크, 같은 단계는 스피너, 뒤는 흐린 원.
  - `JobSteps({ status })` — `role="list" aria-label="정리 단계"`, 지금 단계 항목에 `aria-current="step"`.
  - 정리 중 화면: 제목 "정리하고 있어요", 설명 "다른 화면으로 가도 계속 정리해요", `JobSteps`, 파일 줄(진행 중이면 작은 스피너, 끝나면 체크, 상태 글이 바뀔 때 `screen-fade`), 그 아래 만들어질 카드 자리 `Skeleton` 두 개. 마스코트 깜빡임과 "다 되면 알림으로 알려드려요" 문구는 없앤다.
  - `OwnerJobMonitor`: 작업이 진행 → 끝으로 바뀌면, 지금 주소가 `/owner/jobs/<그 작업>` 이면 `toast("정리 끝!")`, 아니면 `snackbar({ message: "정리 끝!", actionLabel: "보기", onAction: () => router.push("/owner/jobs/<id>") })`. 카드가 0장으로 끝난 작업(`card_count === 0`)은 알리지 않는다(실패 화면에서 따로 보여 준다).
  - `FinishedJobBanner()` — `cardsQuery(token, storeId, { status: "pending" })` 의 카드 중 `job_id` 가 있는 것의 가장 큰 `job_id` 를 골라 `Banner tone="info"` "정리 끝!" + 동작 '검수하기'(→ `/owner/jobs/<id>`). 대기 카드가 없으면 그리지 않는다. 오늘 매장 화면의 `PageHeader` 바로 아래.

- [ ] **Step 1: 테스트 작성**

```js
test('o03a 정리 단계는 서버 상태대로 체크된다', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/jobs/7', { overrides: { job: { status: 'CLASSIFYING' } } });
  const steps = page.getByRole('list', { name: '정리 단계' });
  await steps.waitFor();
  assert.equal((await steps.locator('[aria-current="step"]').innerText()).trim(), '나누는 중');
  assert.equal(await page.getByText('%').count(), 0);
  await ctx.close();
});
test('o03c 작업 화면에 있으면 토스트, 다른 화면이면 보기 스낵바', async (b) => {
  const first = await open(b, 'OWNER', '/owner/jobs/7', { overrides: { jobSequence: ['EXTRACTING', 'EXTRACTING', 'SUCCEEDED'] } });
  await first.page.getByRole('status').getByText('정리 끝!').waitFor({ timeout: 10000 });
  assert.equal(await first.page.getByRole('button', { name: '보기' }).count(), 0);
  await first.ctx.close();
  const second = await open(b, 'OWNER', '/owner/cards', { overrides: { jobSequence: ['EXTRACTING', 'EXTRACTING', 'SUCCEEDED'] } });
  await second.page.getByRole('status').getByText('정리 끝!').waitFor({ timeout: 10000 });
  await second.page.getByRole('button', { name: '보기' }).click();
  await to(second.page, '/owner/jobs/7');
  await second.ctx.close();
});
test('o03c 오늘 매장에 검수할 작업이 있으면 정리 끝 배너', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner');
  const banner = page.getByRole('status').filter({ hasText: '정리 끝!' });
  await banner.getByRole('button', { name: '검수하기' }).click();
  await to(page, '/owner/jobs/7');
  await ctx.close();
});
```

  단위 테스트 `web/tests/job-steps.test.mjs`:

```js
import { test } from "node:test";
import assert from "node:assert/strict";
import { jobStepIndex } from "../components/owner/job-steps-logic.ts";
test("서버 상태 → 단계", () => {
  assert.equal(jobStepIndex("QUEUED"), 1);
  assert.equal(jobStepIndex("EXTRACTING"), 1);
  assert.equal(jobStepIndex("CLASSIFYING"), 2);
  assert.equal(jobStepIndex("SUCCEEDED"), 3);
  assert.equal(jobStepIndex("PARTIAL"), 3);
});
```

  (`jobStepIndex` 는 import 없는 `web/components/owner/job-steps-logic.ts` 에 두고 `job-steps.tsx` 가 가져다 쓴다 — `node --test` 가 바로 읽게.)
- [ ] **Step 2: 실패 확인** — Expected: 3개 브라우저 + 1개 단위 FAIL
- [ ] **Step 3: 구현** — Interfaces 대로. 배너가 오늘 매장의 기존 요소(근무조 현황 카드)를 밀어내므로 `ui-nav` 의 오늘 매장 테스트가 영향을 받는지 확인한다.
- [ ] **Step 4: 통과 확인** — Expected: 이 Task 의 4개 PASS, `ui-nav 30 passed`

---

### Task 5: 검수 화면 (o04a·o04b·o04c)

**Files:**
- Create: `web/components/owner/review-card.tsx`
- Modify: `web/app/owner/jobs/[jobId]/page.tsx`(`ResultReview`, `ResultCard` 삭제)
- Test: `api/scripts/verify_ui_intake.cjs`

**Interfaces:**
- Consumes: `SwipeRow`, `useLongPress`, `Stagger` (Task 2), `useFeedback`·`Banner`·`CountBadge`(계획 1), `Sheet`, `mutateProductCard`, `moveProductCard`, `productCategoriesQuery`
- Produces:
  - 섹션은 `<section aria-labelledby=<제목 id>>` 로 만들어 `region` 역할이 되게 한다.
  - 화면 구성(위에서 아래):
    1. `BackButton parent="/owner"`, 제목 **"카드가 준비됐어요! 검수 부탁드려요!"**(PageHeader title, 설명 없음).
    2. 작업이 PARTIAL 이거나 실패 자료가 있으면 `Banner tone="danger"`: 첫 줄 **"처리하지 못한 자료가 있어요."**, 그 아래 실패 자료마다 `<파일명>: <error.message>` 한 줄, 동작 '다시 시도'(지금 `retryIngestJob`).
    3. 섹션 **"맞는지 확인해 주세요!"** + `CountBadge` — `NEEDS_REVIEW` 카드. 카드마다 이유(`needs_review_reason`, 없으면 "내용이 확실하지 않아요")를 카드 위 주황 띠로, 카드 안 버튼 둘: '고치기'(→ `/owner/cards/<id>`), '빼기'. 누르면 그 카드를 목록에서 **바로 숨기고**(낙관적 반영) `exclude` 를 보낸다. 실패하면 다시 보이고 카드에 빨간 글. 성공하면 스낵바 메시지 **"뺐어요"**, 동작 **"되돌리기"**(→ `restore` 후 다시 보임).
    4. 섹션 **"잘 정리됐어요"** + 작은 회색 글 "그대로 두셔도 돼요" — 나머지(PENDING·APPROVED). 카테고리 이름을 소제목으로, 그 아래 카드들.
    5. '추출하지 않은 자료' 섹션은 지금처럼 남긴다(그래도 추출하기).
    - 결과 화면의 '출처' 글씨, '하나씩 봐 주세요', '이렇게 나눴어요' 는 없앤다.
  - `ReviewCard({ card, tone, onExclude, onMove, busy })` — 완성된 카드 모양: 흰 카드, 제목 17px 굵게, 내용은 줄마다 나눠 앞에 작은 점 없이 행간 넉넉히(최대 4줄, 넘으면 "외 N줄"), 칩 없음. 카드 전체가 `SwipeRow`(left: '빼기', tone danger, 위와 같은 낙관적 빼기) 안에 있고, 길게 누르면 `Sheet`(제목 카드 이름) — '고치기', '카테고리 옮기기'(같은 시트 안에서 카테고리 버튼 목록, 고르면 `moveProductCard`), '빼기'. 카드 목록은 `Stagger`.
  - 하단: 주 버튼 **"검수 완료"**(`loading` 중 스피너) + 그 아래 `TextButton` **"나중에 하기"**(→ `/owner`, replace). 검수 완료 = '잘 정리됐어요' 안의 PENDING 카드를 모두 `approve`. 전부 성공하면 `toast("지식이 추가됐어요", { keepOnNavigate: true })` 후 첫 매장이면 `/owner/invite`, 아니면 `/owner` 로 replace. 일부 실패하면 머무르고 실패 카드에 빨간 글 "공개하지 못했어요. 검수 완료를 다시 누르면 이 카드만 다시 해요."
  - 검수 필요 카드는 검수 완료로 공개하지 않는다(그대로 남아 카드 탭에서 다시 본다).

- [ ] **Step 1: 테스트 작성**

```js
const REVIEW = { job: { status: 'PARTIAL', sources: [
  { source_id: 31, filename: '레시피 메모.jpg', status: 'SUCCEEDED', card_count: 4, error: null, source_availability: 'AVAILABLE' },
  { source_id: 32, filename: '흐린 사진.jpg', status: 'FAILED', card_count: 0, error: { code: 'EXTRACTION_FAILED', message: '글자를 읽을 수 없어요' }, source_availability: 'AVAILABLE' }] } };

test('o04a 제목은 부탁 말투, 실패 배너는 자료마다 이유', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/jobs/7', { overrides: REVIEW });
  await page.getByRole('heading', { name: '카드가 준비됐어요! 검수 부탁드려요!' }).waitFor();
  const banner = page.getByRole('alert').filter({ hasText: '처리하지 못한 자료가 있어요.' });
  await banner.getByText('흐린 사진.jpg: 글자를 읽을 수 없어요').waitFor();
  for (const gone of ['이렇게 나눴어요', '하나씩 봐 주세요', '맞아요', '더 넣기']) assert.equal(await page.getByText(gone, { exact: true }).count(), 0, gone);
  assert.equal(await page.getByText(/^출처/).count(), 0);
  await ctx.close();
});
test('o04b 이상한 카드는 이유와 함께 위에, 잘된 카드는 아래에', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/jobs/7', { overrides: REVIEW });
  const check = page.getByRole('region', { name: '맞는지 확인해 주세요!' });
  await check.getByText('마감 머신 청소').waitFor();
  await check.getByText('역세척 횟수가 두 가지(3회, 5회)로 적혀 있어요').waitFor();
  const good = page.getByRole('region', { name: '잘 정리됐어요' });
  await good.getByText('그대로 두셔도 돼요').waitFor();
  await good.getByText('오픈 준비').waitFor();
  assert.equal(await good.getByText('마감 머신 청소').count(), 0);
  await ctx.close();
});
test('o04b 빼기는 바로 저장되고 되돌리기로 살린다', async (b) => {
  const { page, ctx, api } = await open(b, 'OWNER', '/owner/jobs/7', { overrides: REVIEW });
  const check = page.getByRole('region', { name: '맞는지 확인해 주세요!' });
  await check.getByRole('button', { name: '빼기' }).first().click();
  await page.getByRole('status').getByText('뺐어요').waitFor();
  assert.ok(api.calls.some((c) => c.method === 'POST' && c.path === '/cards/3/exclude'));
  await check.getByText('마감 머신 청소').waitFor({ state: 'hidden' });
  await page.getByRole('button', { name: '되돌리기' }).click();
  await check.getByText('마감 머신 청소').waitFor();
  assert.ok(api.calls.some((c) => c.method === 'POST' && c.path === '/cards/3/restore'));
  await ctx.close();
});
test('o04b 연달아 빼면 앞의 것은 그대로 빠져 있다', async (b) => {
  const { page, ctx, api } = await open(b, 'OWNER', '/owner/jobs/7', { overrides: REVIEW });
  const good = page.getByRole('region', { name: '잘 정리됐어요' });
  await good.getByRole('button', { name: '빼기' }).nth(0).click();
  await good.getByRole('button', { name: '빼기' }).nth(0).click();
  await page.waitForTimeout(300);
  assert.equal(api.calls.filter((c) => c.path.endsWith('/exclude')).length, 2);
  assert.equal(api.state.cards.filter((c) => c.review_status === 'EXCLUDED').length, 2);
  await ctx.close();
});
test('o04b 길게 누르면 카테고리 옮기기 시트', async (b) => {
  const { page, ctx, api } = await open(b, 'OWNER', '/owner/jobs/7', { overrides: REVIEW });
  const card = page.getByRole('region', { name: '잘 정리됐어요' }).getByText('원두 보관 위치');
  const box = await card.boundingBox();
  await page.mouse.move(box.x + 5, box.y + 5); await page.mouse.down(); await page.waitForTimeout(650); await page.mouse.up();
  const sheet = page.getByRole('dialog', { name: '원두 보관 위치' });
  await sheet.getByRole('button', { name: '카테고리 옮기기' }).click();
  await sheet.getByRole('button', { name: '오픈 마감' }).click();
  await page.waitForTimeout(300);
  assert.ok(api.calls.some((c) => c.method === 'PATCH' && c.path === '/cards/5/category' && c.body.category_id === 11));
  await ctx.close();
});
test('o04c 검수 완료는 잘된 카드만 공개하고 토스트 뒤 오늘 매장', async (b) => {
  const { page, ctx, api } = await open(b, 'OWNER', '/owner/jobs/7', { overrides: REVIEW });
  await page.getByRole('button', { name: '검수 완료', exact: true }).click();
  await to(page, '/owner');
  await page.getByRole('status').getByText('지식이 추가됐어요').waitFor();
  const approved = api.calls.filter((c) => c.path.endsWith('/approve')).map((c) => c.path);
  assert.deepEqual(approved.sort(), ['/cards/4/approve', '/cards/5/approve']);
  await ctx.close();
});
test('o04c 나중에 하기는 작은 글자 버튼이고 오늘 매장으로', async (b) => {
  const { page, ctx, api } = await open(b, 'OWNER', '/owner/jobs/7', { overrides: REVIEW });
  const later = page.getByRole('button', { name: '나중에 하기', exact: true });
  const size = await later.evaluate((e) => parseFloat(getComputedStyle(e).fontSize));
  assert.ok(size <= 14, `font ${size}`);
  await later.click(); await to(page, '/owner');
  assert.equal(api.calls.filter((c) => c.path.endsWith('/approve')).length, 0);
  await ctx.close();
});
```

  fixture 의 카드 `job_id` 는 모두 7, 대기(PENDING) 카드는 4 '오픈 준비'와 5 '원두 보관 위치', 검수 필요는 3 '마감 머신 청소'(계획 1 fixture 그대로).
- [ ] **Step 2: 실패 확인** — Expected: 7개 FAIL(+ Task 1 의 'fixture 작업 상태' 테스트도 아직 FAIL)
- [ ] **Step 3: 구현** — Interfaces 대로. `ui-nav` 의 `NAV-2` 는 넣기 → 작업 화면만 보므로 그대로 통과해야 한다. 기존 `verify_ui_rebrand.cjs` 가 '맞아요'·'하나씩 봐 주세요'·'이렇게 나눴어요' 를 찾는 단언은 이 결정대로 고친다.
- [ ] **Step 4: 통과 확인** — Expected: `ui-intake` 전부 PASS(1 + 6 + 4 + 4 + 7 = 22), `ui-nav 30 passed`, 기존 CI 스크립트 3개 PASS, `pnpm check` 통과.

---

## 실행 순서와 확인

Task 1 → 2 → 3 → 4 → 5. 마지막 확인:
- `cd web && pnpm check` 통과(node test 에 `job-steps` 추가)
- `verify_ui_nav.cjs` 30개, `verify_ui_intake.cjs` 22개, `verify_r_ui.cjs`·`verify_r_history_ui.cjs`·`verify_ui_rebrand.cjs` PASS
- `ui-state-walkthrough`·`web-async-state-check` 스킬로 넣기 제출·검수 완료 mutation 의 lifecycle(연타, 실패 뒤 다시) 확인
