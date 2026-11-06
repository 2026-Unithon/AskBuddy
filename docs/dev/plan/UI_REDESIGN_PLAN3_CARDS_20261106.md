# 화면 개선 계획 3: 카드 목록·상세·확인 필요·제안 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 사장님 카드 화면(o05~o08)을 사용자 결정과 스케치대로 바꾼다. 카테고리 섹션 + 2열 카드 격자, 상태는 글자 대신 모양으로, 상세는 읽기 전용, 오른쪽 위 '수정하기'로만 고친다.

**Architecture:** 계획 1·2 키트(이동 기록, 피드백, `SwipeRow`, `useLongPress`, `Stagger`, `Sheet` 포털) 위에 `Switch`, 당겨서 새로고침, `CardTile`, 단어 단위 비교(`diffWords`)를 더한다. 목록→상세 제목은 React `ViewTransition`(Next 16 App Router 기본 지원)으로 이어 붙인다. **서버 API·DB 는 바꾸지 않는다.** 서버가 먼저 필요한 기능(공개 내리기, 수정 되돌리기, 검수 필요→미공개, 충돌 값 고르기)은 `UI_REDESIGN_BACKLOG_20261106.md` '서버 먼저 필요한 기능'에 있고 이 계획에서 만들지 않는다.

**Tech Stack:** Next.js 16 App Router, React 19(App Router 내장 canary — `ViewTransition`), Tailwind 4, TanStack Query 5, Playwright 1.62(합성 API), Node 24 `node --test`.

**Spec:** `docs/dev/plan/UI_REDESIGN_SPEC_20261106.md` (o05a~c, o06a~f, o07a~b, o08a~b, 앱 전체 규칙), 사용자 스케치(2026-11-06: 카테고리 제목 + 굵은 밑줄, 아래 2열 카드, 카드엔 이름과 ›만)

## Global Constraints

- 계획 1·2 제약 전부(중간점 금지, 모션 토큰, 합성 API 로만 검증, 커밋은 사용자가, 진행률 % 금지).
- **카드 상태 정의(사용자 확정):** 공개 = `APPROVED`(살아 있는 카드), 검수 필요 = `NEEDS_REVIEW` + 다른 답 제안이 걸린 카드, 미공개 = `PENDING`(공개하지 않는 카드), 삭제 = `EXCLUDED` — **어느 화면에서도 보이지 않는다**(목록 필터에 없음, 상세로 직접 와도 "삭제한 카드예요"만). 삭제를 되돌리는 길은 삭제 직후 5초 스낵바 '되돌리기'(→ `restore`) 하나뿐.
- 목록 필터는 정확히 **전체 / 공개 / 검수 필요 / 미공개** 네 개. 빨간 뱃지는 '검수 필요'에만.
- 밀기 규칙(이 계획 범위): 미공개 카드는 전체·미공개 탭에서 **오른쪽 → 공개**, 미공개 탭에서 **왼쪽 → 삭제**(스낵바 "삭제했어요" + "되돌리기"). 공개 카드의 왼쪽 밀기(→ 미공개)는 서버 '공개 내리기'가 생긴 뒤(백로그).
- 상세는 **읽기 전용**. 고치기·빼기·순서 바꾸기·길게 누르기는 오른쪽 위 **'수정하기'** 로 들어간 수정 모드에서만. 수정 모드 하단은 **'수정 완료'(초록, 왼쪽) / '돌아가기'(흰색, 오른쪽)** 좌우. 상세 화면의 '고치기'·'지우기' 버튼은 없앤다.
- 상세 보기 모드에는 칩(블록 이름 칩, 값 칩, '하지 않음' 칩), 줄마다 '근거:', '출처', '근거 보기 N', 회색 안내 문구가 없다. 근거 자료는 페이지 맨 아래 마지막 카드 밑에 아주 작은 회색 글씨로 한 번만.
- 제안 화면 버튼은 **'수정 완료'** 하나 + 아래 작은 회색 글자 **'수정하지 않고 돌아가기'**.

## Review Focus

1. **검색어를 빨리 지우거나 고칠 때 이전 검색 결과가 늦게 도착**: 마지막 입력 기준 결과만 보여야 한다(주소의 query 가 정본, 조회 키에 query 포함) → Task 2 `o05a 검색은 칠 때마다 걸러지고 마지막 글자 기준`.
2. **미공개 카드를 삭제한 직후 다른 미공개 카드 삭제**: 스낵바는 하나라 첫 '되돌리기'는 사라진다. 첫 카드는 서버에서도 화면에서도 삭제된 채여야 한다 → Task 2 `o05c 연달아 삭제해도 앞 카드는 삭제된 채`.
3. **삭제된 카드의 상세 주소로 직접 들어옴(옛 알림·뒤로가기)**: 내용·버튼 없이 "삭제한 카드예요"만 → Task 3 `o06 삭제한 카드 주소는 내용 없이 안내만`.
4. **수정 모드에서 순서를 바꿨다가 '돌아가기'**: 저장되지 않고 원래 순서로 → Task 4 `o06f 돌아가기는 저장하지 않는다`.
5. **드래그로 옮길 수 없는 자리(선행 단계 앞)로 끌기**: 옮기지 않고 제자리 → Task 4 `o06d 선행 단계 앞으로는 끌어도 안 옮겨진다`.

---

## 파일 구조

| 파일 | 책임 |
|---|---|
| `web/types/react-canary.d.ts` (새) | `/// <reference types="react/canary" />` — `ViewTransition` 타입 |
| `web/components/kit/switch.tsx` (새) | 켜고 끄는 스위치(`role="switch"`) |
| `web/components/kit/pull-to-refresh.tsx` (새) | 당겨서 새로고침 훅 + 표시 |
| `web/components/kit/screen.tsx` | `onRefresh` 받기 |
| `web/lib/diff-words.ts` (새) | 단어 단위 비교(순수 함수) |
| `web/tests/diff-words.test.mjs` (새) | 단위 테스트 |
| `web/components/owner/card-tile.tsx` (새) | 목록 2열 카드 한 장(상태 모양·밀기) |
| `web/app/owner/cards/page.tsx` | 목록(o05) |
| `web/app/owner/cards/[cardId]/page.tsx` | 상세 머리·하단·삭제 카드(o06·o07) |
| `web/components/owner/fact-card/fact-card-panel.tsx` | 보기 모드 블록 머리·근거 모음, 수정 모드 드래그·길게 누르기·사실 추가 줄 |
| `web/components/owner/fact-card/fact-row.tsx` | 보기 모드 줄(칩·근거 없음, 값 굵게) |
| `web/components/owner/fact-card/sortable-list.tsx` (새) | 수정 모드 끌어서 순서 바꾸기 |
| `web/components/checklist/card-assignment.tsx` | 공통·근무조 스위치(o06e) |
| `web/app/owner/cards/proposals/page.tsx` | 제안(o08) |
| `api/scripts/ui_fixture.cjs` | 사실 카드 보기·저장, 제안, 근무조 연결 |
| `api/scripts/verify_ui_cards.cjs` (새) | 이 계획 회귀 |

---

### Task 1: 키트 — 스위치, 당겨서 새로고침, ViewTransition 타입, fixture

**Files:**
- Create: `web/types/react-canary.d.ts`, `web/components/kit/switch.tsx`, `web/components/kit/pull-to-refresh.tsx`, `api/scripts/verify_ui_cards.cjs`
- Modify: `web/components/kit/screen.tsx`, `web/components/kit/index.ts`, `web/app/dev/kit/page.tsx`, `api/scripts/ui_fixture.cjs`, `.github/workflows/r-validation.yml`, 로컬 `run-ui.sh`(저장소 밖)

**Interfaces:**
- Produces:
  - `Switch({ checked, onChange, label, disabled }: { checked: boolean; onChange: (next: boolean) => void; label: string; disabled?: boolean })` — 한 줄 전체가 `<button role="switch" aria-checked>`, 왼쪽 글 `label`, 오른쪽 52×32 둥근 틀과 손잡이. 켜지면 틀 `bg-primary`, 손잡이가 오른쪽으로 `--ease-spring` `--dur-base`.
  - `usePullToRefresh(onRefresh: () => Promise<unknown>, { threshold = 64 } = {}) → { bind: { onPointerDown, onPointerMove, onPointerUp, onPointerCancel }, pull: number, refreshing: boolean }` — 스크롤이 맨 위(`scrollTop === 0`)일 때만 아래로 끄는 것을 잡는다. `threshold` 넘게 끌고 놓으면 `onRefresh` 를 기다리는 동안 `refreshing`. 끄는 거리는 저항(실제 이동 × 0.5).
  - `Screen({ ..., onRefresh })` — 주면 `main` 에 위 훅을 붙이고 위쪽에 `role="status" aria-label="새로고침 중"` 스피너(끄는 동안 회전량은 `pull` 비율, 새로고침 중엔 계속 회전).
  - 개발 키트 `?s=forms`: `Switch` 하나("알림"), `Screen onRefresh` 로 누를 때마다 화면 글 `새로고침 N번` 이 1씩 느는 미리보기.
  - fixture(`ui_fixture.cjs`):
    - 카드 1 상세에 `fact_card: true`. `GET /cards/1/facts` 는 `verify_w3b_card_facts_ui.cjs` 의 `factCardView` 구조를 그대로 옮긴 뷰(제목 '바닐라 라떼', ICE 수치 2줄 225ml·10g, 순서 4줄과 선행 관계, 목록 1줄 NEGATE). `PUT /cards/1/facts` 는 본문을 `calls` 에 남기고 `version_id + 1` 로 `FactEditResult` 성공.
    - `GET /learn/knowledge-proposals` 는 `state.proposals`(기본 1건: proposal_id 9, target_card_id 1, current_content "ICE 시럽 2펌프", proposed_content "ICE 시럽 3펌프", question_text "바닐라 라떼 ICE 시럽 몇 펌프?", can_approve true). `POST .../9/(approve|dismiss)` 는 목록에서 빼고 `{ proposal_id: 9, status }`.
    - `GET /checklist/cards/:id` 는 `state.cardLinks[id] ?? { checklist: false, shift_ids: [] }`, `PUT /checklist/cards/:id` 는 본문을 저장해 돌려준다.
    - `GET /cards` 는 `review_status` 와 `query`(제목 포함) 필터를 지키고, 요청마다 `calls` 에 남는다(새로고침·검색 단언용).

- [ ] **Step 1: 테스트 작성** — `verify_ui_cards.cjs`(머리는 `verify_ui_intake.cjs` 와 같은 모양, 묶음 이름 `ui-cards`)

```js
test('키트 스위치는 눌러서 켜고 끈다', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/dev/kit?s=forms');
  const sw = page.getByRole('switch', { name: '알림' });
  assert.equal(await sw.getAttribute('aria-checked'), 'false');
  await sw.click(); assert.equal(await sw.getAttribute('aria-checked'), 'true');
  await sw.press('Space'); assert.equal(await sw.getAttribute('aria-checked'), 'false');
  await ctx.close();
});
test('키트 맨 위에서 당기면 새로고침, 조금만 당기면 안 한다', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/dev/kit?s=forms');
  const box = await page.locator('main').boundingBox();
  const pull = async (dy) => {
    await page.mouse.move(box.x + 100, box.y + 40); await page.mouse.down();
    await page.mouse.move(box.x + 100, box.y + 40 + dy, { steps: 10 }); await page.mouse.up();
  };
  await pull(40); await page.waitForTimeout(300);
  await page.getByText('새로고침 0번').waitFor();
  await pull(220);
  await page.getByText('새로고침 1번').waitFor();
  await ctx.close();
});
```

- [ ] **Step 2: 실패 확인** — Expected: 둘 다 FAIL(`?s=forms` 없음)
- [ ] **Step 3: 구현** — Interfaces 대로. CI·`run-ui.sh` 에 `verify_ui_cards.cjs` 추가.
- [ ] **Step 4: 통과 확인** — Expected: 2 PASS, `ui-nav 30`·`ui-intake 27` 유지.

---

### Task 2: 카드 목록 (o05a·o05b·o05c)

**Files:**
- Create: `web/components/owner/card-tile.tsx`
- Modify: `web/app/owner/cards/page.tsx`
- Test: `api/scripts/verify_ui_cards.cjs`

**Interfaces:**
- Consumes: `SwipeRow`, `Stagger`, `useFeedback`, `CountBadge`, `Screen onRefresh`(Task 1)
- Produces:
  - 필터 탭(`role="tablist" aria-label="카드 상태"`): 전체(`status` 없음) / 공개(`approved`) / 검수 필요(`needs_review`) / 미공개(`pending`). 주소 `?status=` 값은 그대로 쓰고, 옛 값 `excluded` 로 오면 전체로 보낸다. '검수 필요' 탭 옆에 빨간 `CountBadge tone="danger"` — 값은 `cardsQuery({ status: "needs_review", limit: 1 }).data.total` + 제안이 걸린 카드 중 `NEEDS_REVIEW` 가 아닌 카드 수. 0 이면 뱃지 없음.
  - 전체 탭은 `EXCLUDED` 를 빼고 보여 준다(서버 응답에 섞여 와도).
  - 검색: 입력이 바뀌면 250ms 뒤 `?query=` 를 replace(Enter 없이). 비우면 `query` 를 지운다. 조회 키에 query 가 들어 있어 늦게 온 옛 결과는 화면에 쓰지 않는다.
  - 다른 답 제안(o05b): 목록 위 배너를 없앤다. 제안이 걸린 카드(`target_card_id`)는 전체·검수 필요 탭에서 '검수 필요' 모양으로 보이고, 타일 아래에 톤온톤 띠 "다른 답이 있어요"(`bg-brand-100 text-brand-800`, 굵게). 그 타일을 누르면 `/owner/cards/proposals?card_id=<id>`.
  - 배치(스케치): 카테고리마다 `<section aria-labelledby>` — 제목(17px 굵게) 아래 굵은 밑줄(`border-b-2 border-ink`), 그 아래 `grid grid-cols-2 gap-3` 의 `CardTile`. 카테고리 순서는 `productCategoriesQuery` 의 `sort_order`, 카드가 없는 카테고리는 그리지 않는다.
  - `CardTile({ card, proposal, swipe })` — 타일 자체가 `<Link>` 이고 `data-status`·`aria-label`·모양 클래스가 그 링크에 붙는다. 내용은 이름(15px 굵게, 2줄까지)과 오른쪽 `›` 만. 요약·상태 글자 없음. `data-status`("approved"|"review"|"pending") 와 `aria-label="<이름>, <공개|검수 필요|미공개>"`. 모양:
    - 공개: 흰 바탕, 그림자, 왼쪽 위 초록 점(8px `bg-primary`).
    - 검수 필요: `bg-warn-50`, 테두리 `border-2 border-warn-500`, 왼쪽 위 주황 점.
    - 미공개: 투명 바탕, 점선 테두리(`border-2 border-dashed border-ink-muted/40`), 이름 글자 `text-ink-muted`.
    - 이름은 `<ViewTransition name={"card-title-" + card_id}>` 로 감싼다.
  - 밀기: 미공개 카드 — 전체·미공개 탭에서 `right: { label: "공개", tone: "primary" }` → `approve`, 성공하면 토스트 "공개했어요". 미공개 탭에서만 `left: { label: "삭제", tone: "danger" }` → 누르는 즉시 숨기고 `exclude`, 성공하면 스낵바 메시지 "삭제했어요" 동작 "되돌리기"(→ `restore`, 다시 보임), 실패하면 다시 보이고 토스트 "삭제하지 못했어요". 공개·검수 필요 카드는 밀기 없음.
  - `Screen onRefresh={() => cards.refetch()}`(당겨서 새로고침).
  - 카테고리·작업으로 좁힌 상태 칩("이번에 넣은 자료의 카드만, 모두 보기")은 지금처럼 남긴다.

- [ ] **Step 1: 테스트 작성**

```js
test('o05a 필터는 전체 공개 검수 필요 미공개, 지운 카드는 어디에도 없다', async (b) => {
  const { page, ctx, api } = await open(b, 'OWNER', '/owner/cards');
  api.state.cards.push({ card_id: 7, review_status: 'EXCLUDED', title: '지운 레시피', content: '-', category_id: 10 });
  await page.reload({ waitUntil: 'networkidle' });
  const tabs = page.getByRole('tablist', { name: '카드 상태' }).getByRole('tab');
  assert.deepEqual((await tabs.allInnerTexts()).map((t) => t.replace(/\d+/g, '').trim()), ['전체', '공개', '검수 필요', '미공개']);
  assert.equal(await page.getByText('지운 레시피').count(), 0);
  await ctx.close();
});
test('o05a 빨간 뱃지는 검수 필요에만, 제안 걸린 카드도 센다', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/cards');
  const review = page.getByRole('tab', { name: /검수 필요/ });
  assert.equal((await review.innerText()).replace(/\D/g, ''), '2'); // 마감 머신 청소 + 제안 걸린 바닐라 라떼
  for (const name of ['전체', '공개', '미공개']) assert.equal((await page.getByRole('tab', { name: new RegExp(name) }).innerText()).replace(/\D/g, ''), '', name);
  await ctx.close();
});
test('o05a 검색은 칠 때마다 걸러지고 마지막 글자 기준', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/cards');
  const box = page.getByRole('searchbox', { name: '카드 찾기' });
  await box.pressSequentially('우유', { delay: 40 });
  await page.waitForURL(/query=%EC%9A%B0%EC%9C%A0/);
  await page.getByText('우유 발주').waitFor();
  assert.equal(await page.getByText('아메리카노').count(), 0);
  await box.fill(''); await page.waitForURL((u) => !u.search.includes('query='));
  await page.getByText('아메리카노').waitFor();
  await ctx.close();
});
test('o05b 제안 배너 대신 제안 걸린 카드에 다른 답 띠', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/cards?status=needs_review');
  assert.equal(await page.getByText('기존 카드와 다른 답이 있어요').count(), 0);
  const tile = page.getByRole('link', { name: '바닐라 라떼, 검수 필요' });
  await tile.getByText('다른 답이 있어요').waitFor();
  await tile.click(); await to(page, '/owner/cards/proposals?card_id=1');
  await ctx.close();
});
test('o05c 카테고리 섹션과 밑줄, 2열, 카드엔 이름과 꺾쇠만', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/cards');
  const section = page.getByRole('region', { name: '음료 레시피' });
  const heading = section.getByRole('heading', { name: '음료 레시피' });
  assert.equal(await heading.evaluate((h) => getComputedStyle(h).borderBottomWidth), '2px');
  const tiles = section.locator('[data-status]');
  const tops = await tiles.evaluateAll((els) => els.map((e) => Math.round(e.getBoundingClientRect().top)));
  assert.equal(tops[0], tops[1], '2열');
  const americano = section.locator('[aria-label="아메리카노, 공개"]');
  assert.deepEqual((await americano.innerText()).split('\n').map((t) => t.trim()).filter(Boolean), ['아메리카노', '›']);
  await ctx.close();
});
test('o05c 상태는 글자가 아니라 모양으로', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/cards');
  const style = async (name) => page.locator(`[aria-label^="${name},"]`).evaluate((e) => ({ status: e.dataset.status, border: getComputedStyle(e).borderTopStyle }));
  assert.deepEqual(await style('아메리카노'), { status: 'approved', border: 'none' });
  assert.deepEqual(await style('오픈 준비'), { status: 'pending', border: 'dashed' });
  assert.equal((await style('마감 머신 청소')).status, 'review');
  for (const word of ['공개 전', '확인 필요', '미공개']) assert.equal(await page.locator('main [data-status]').getByText(word, { exact: true }).count(), 0, word);
  await ctx.close();
});
test('o05c 미공개 카드는 오른쪽으로 밀면 공개', async (b) => {
  const { page, ctx, api } = await open(b, 'OWNER', '/owner/cards?status=pending');
  await page.getByRole('button', { name: '공개' }).first().press('Enter');
  await page.getByRole('status').getByText('공개했어요').waitFor();
  assert.ok(api.calls.some((c) => c.method === 'POST' && c.path === '/cards/4/approve'));
  await ctx.close();
});
test('o05c 미공개 탭에서 왼쪽으로 밀면 삭제, 되돌리기로 살린다', async (b) => {
  const { page, ctx, api } = await open(b, 'OWNER', '/owner/cards?status=pending');
  await page.getByRole('button', { name: '삭제' }).first().press('Enter');
  await page.getByRole('status').getByText('삭제했어요').waitFor();
  await page.getByText('오픈 준비').waitFor({ state: 'hidden' });
  await page.getByRole('button', { name: '되돌리기' }).click();
  await page.getByText('오픈 준비').waitFor();
  assert.ok(api.calls.some((c) => c.path === '/cards/4/restore'));
  await ctx.close();
});
test('o05c 연달아 삭제해도 앞 카드는 삭제된 채', async (b) => {
  const { page, ctx, api } = await open(b, 'OWNER', '/owner/cards?status=pending');
  await page.getByRole('button', { name: '삭제' }).nth(0).press('Enter');
  await page.getByRole('button', { name: '삭제' }).nth(0).press('Enter');
  await page.waitForTimeout(300);
  assert.equal(api.state.cards.filter((c) => c.review_status === 'EXCLUDED').length, 2);
  assert.equal(await page.locator('[data-status]').count(), 0);
  await ctx.close();
});
test('o05c 전체 탭의 공개 카드는 밀 수 없다(공개 내리기는 서버 뒤)', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/cards');
  const tile = page.locator('[aria-label="아메리카노, 공개"]');
  assert.equal(await tile.locator('..').getByRole('button', { name: /삭제|미공개/ }).count(), 0);
  await ctx.close();
});
test('o05c 당겨서 새로고침', async (b) => {
  const { page, ctx, api } = await open(b, 'OWNER', '/owner/cards');
  const before = api.calls.filter((c) => c.path.startsWith('/cards?') || c.path === '/cards').length;
  const box = await page.locator('main').boundingBox();
  await page.mouse.move(box.x + 100, box.y + 40); await page.mouse.down();
  await page.mouse.move(box.x + 100, box.y + 260, { steps: 10 }); await page.mouse.up();
  await page.waitForTimeout(500);
  assert.ok(api.calls.filter((c) => c.path.startsWith('/cards?') || c.path === '/cards').length > before);
  await ctx.close();
});
test('o05c 목록 제목이 상세 제목으로 이어진다(view transition)', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/cards');
  await page.evaluate(() => { window.__vt = 0; const orig = document.startViewTransition?.bind(document); if (orig) document.startViewTransition = (...a) => { window.__vt++; return orig(...a); }; });
  await page.getByRole('link', { name: '아메리카노, 공개' }).click(); await to(page, '/owner/cards/2');
  assert.ok(await page.evaluate(() => window.__vt) > 0);
  await ctx.close();
});
```

  fixture 기본 카드: 1 바닐라 라떼(공개, 제안 걸림), 2 아메리카노(공개), 3 마감 머신 청소(검수 필요), 4 오픈 준비(미공개), 5 원두 보관 위치(미공개), 6 우유 발주(공개).
- [ ] **Step 2: 실패 확인** — Expected: 11개 FAIL
- [ ] **Step 3: 구현** — Interfaces 대로. 기존 `verify_ui_rebrand.cjs` 의 목록 단언(배너, 지운 카드 탭)은 이 결정대로 고친다.
- [ ] **Step 4: 통과 확인** — Expected: Task 1·2 13개 PASS, 다른 묶음 유지.

---

### Task 3: 카드 상세 보기 모드 (o06a·o06b·o06c·o06e·o07a·o07b)

**Files:**
- Modify: `web/app/owner/cards/[cardId]/page.tsx`, `web/components/owner/fact-card/fact-card-panel.tsx`(보기 모드 부분), `web/components/owner/fact-card/fact-row.tsx`, `web/components/checklist/card-assignment.tsx`
- Test: `api/scripts/verify_ui_cards.cjs`

**Interfaces:**
- Consumes: `Switch`(Task 1)
- Produces:
  - 머리: 왼쪽 `BackButton`, 오른쪽 **'수정하기'** 버튼(사실 카드이고 고칠 수 있을 때만, `pressable`, 작은 알약). 그 아래 카테고리 칩 버튼(이름 + `▾`, 누르면 지금의 카테고리 옮기기 시트) — 상태 칩은 없앤다(상태는 아래 상태 줄로). 제목 h1 은 `<ViewTransition name={"card-title-" + id}>`.
  - 상태 줄(제목 아래 한 줄, 작게): 공개면 초록 점 + "직원에게 보여요", 미공개면 회색 점 + "아직 공개 전이에요", 고친 내용이 공개 전이면 "고친 내용은 아직 공개 전이에요".
  - 검수 필요(o07a): 제목 아래 경고 상자 — 굵은 첫 줄 "확인해 주세요", 둘째 줄 사유(15px, `text-ink`), 왼쪽 주황 띠(`border-l-4 border-warn-500 bg-warn-50`). '근거 보기 N' 없음.
  - 사실 카드 보기 모드(o06b·o06d): 블록마다 카드 **밖** 위에 머리글(17px 굵게) — 규격이 있으면 규격 이름(예 "ICE", "HOT 톨"), 없으면 블록 이름("순서", "목록", "수치"). 블록 칩 없음. 줄은 문장만(값이 문장 안에 있으면 그 부분만 굵게, `<strong>`), 순서 블록은 번호 원 유지, 조건·예외는 13px 회색 한 줄("조건: …"). 값 칩·'하지 않음' 칩·'근거:' 줄 없음. 블록 안내 문구("위나 아래로 옮기면…") 없음.
  - 근거 모음(o06c): 페이지 맨 아래, 마지막 블록 밑에 11px 회색 `<p>` 하나 — "근거 자료 " + 모든 사실의 `originLabel` 을 중복 없이 쉼표로. 사실 카드가 아니면 `card.evidence` 의 자료 이름으로 같게. 끊긴 인용은 이름 뒤 "(원본 지워짐)". '출처 …' 캡션, '근거 보기' 버튼, 펼침 목록은 없앤다.
  - 근무조 할 일(o06e, `CardAssignment`): 제목 "어느 근무조 할 일인가요?", 아래 `Switch` 들 — 첫 줄 **"공통"**(켜짐 = `checklist: true, shift_ids: []`), 그 아래 근무조마다 `Switch`(이름). 공통을 켜면 근무조는 모두 꺼진다. 근무조 하나를 켜면 공통은 꺼지고 `checklist: true, shift_ids: [...]`. 모두 끄면 `checklist: false`. 회색 안내 문구 없음. 저장 중엔 스위치 비활성.
  - 하단(o06f·o07b): 공개 카드는 하단 버튼 없음. 미공개·검수 필요·고친 내용 공개 전이면 **'공개'** 버튼 하나(초록). 검수 필요의 '미공개'는 서버 뒤(백로그). '고치기'·'지우기'·'다시 살리기'·지우기 확인 시트는 없앤다.
  - 삭제한 카드(`EXCLUDED`): 뒤로 버튼과 `Empty title="삭제한 카드예요" description="이 카드는 이제 어디에도 보이지 않아요."` 만.

- [ ] **Step 1: 테스트 작성**

```js
test('o06a 오른쪽 위 수정하기, 카테고리 칩, 안내 문구 없음', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/cards/1');
  const edit = page.getByRole('button', { name: '수정하기' });
  const back = await page.locator('[data-back]').boundingBox(), box = await edit.boundingBox();
  assert.ok(Math.abs(back.y - box.y) < 12 && box.x > 200, '뒤로와 같은 줄 오른쪽');
  await page.getByRole('button', { name: /음료 레시피/ }).click();
  await page.getByRole('dialog', { name: '어디로 옮길까요?' }).waitFor();
  assert.equal(await page.getByText(/제목은 메뉴/).count(), 0);
  await ctx.close();
});
test('o06b 블록 머리글은 카드 밖 굵은 글, 칩과 근거 줄 없음, 값은 문장 안에서 굵게', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/cards/1');
  const head = page.getByRole('heading', { name: 'ICE', exact: true });
  assert.ok(parseFloat(await head.evaluate((h) => getComputedStyle(h).fontSize)) >= 17);
  for (const gone of [/^수치/, /^근거:/, /^출처/, /근거 보기/, '하지 않음', '위나 아래로 옮기면 일하는 순서가 바뀌어요.']) assert.equal(await page.locator('main').getByText(gone).count(), 0, String(gone));
  assert.equal(await page.locator('main strong', { hasText: '225ml' }).count() + await page.locator('main strong', { hasText: '225' }).count() > 0, true);
  await ctx.close();
});
test('o06c 근거 자료는 맨 아래 작은 회색 한 줄', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/cards/1');
  const line = page.getByText(/^근거 자료 /);
  await line.waitFor();
  const info = await line.evaluate((e) => ({ size: parseFloat(getComputedStyle(e).fontSize), last: e === e.closest('main').lastElementChild || !e.nextElementSibling }));
  assert.ok(info.size <= 12); assert.ok(info.last);
  assert.ok((await line.innerText()).includes('지난 메모.jpg (원본 지워짐)'));
  await ctx.close();
});
test('o06e 공통과 근무조는 스위치, 공통을 켜면 근무조가 꺼진다', async (b) => {
  const { page, ctx, api } = await open(b, 'OWNER', '/owner/cards/2', { overrides: { cardLinks: { 2: { checklist: true, shift_ids: [1] } } } });
  const common = page.getByRole('switch', { name: '공통' });
  const open1 = page.getByRole('switch', { name: '오픈' });
  assert.equal(await open1.getAttribute('aria-checked'), 'true');
  assert.equal(await common.getAttribute('aria-checked'), 'false');
  await common.click(); await page.waitForTimeout(300);
  assert.deepEqual(api.calls.filter((c) => c.path === '/checklist/cards/2' && c.method === 'PUT').at(-1).body, { checklist: true, shift_ids: [] });
  assert.equal(await page.getByText(/공통은 모두에게 보여요/).count(), 0);
  assert.equal(await page.getByText(/켜짐|꺼짐/).count(), 0);
  await ctx.close();
});
test('o07a 검수 필요 사유는 확인해 주세요 상자, 근거 보기 없음', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/cards/3');
  await page.getByText('확인해 주세요', { exact: true }).waitFor();
  await page.getByText('역세척 횟수가 두 가지(3회, 5회)로 적혀 있어요').waitFor();
  assert.equal(await page.getByText(/근거 보기/).count(), 0);
  await ctx.close();
});
test('o07b 하단은 공개 하나, 고치기 지우기 없음', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/cards/3');
  await page.getByRole('button', { name: '공개', exact: true }).waitFor();
  for (const gone of ['고치기', '지우기', '공개하기']) assert.equal(await page.getByRole('button', { name: gone, exact: true }).count(), 0, gone);
  await ctx.close();
  const live = await open(b, 'OWNER', '/owner/cards/2');
  assert.equal(await live.page.getByRole('button', { name: '공개', exact: true }).count(), 0);
  await live.ctx.close();
});
test('o06 삭제한 카드 주소는 내용 없이 안내만', async (b) => {
  const { page, ctx, api } = await open(b, 'OWNER', '/owner/cards/2');
  api.state.cards[1].review_status = 'EXCLUDED';
  await page.reload({ waitUntil: 'networkidle' });
  await page.getByText('삭제한 카드예요').waitFor();
  assert.equal(await page.getByText('아메리카노').count(), 0);
  assert.equal(await page.getByRole('button', { name: /살리기|되돌리기|공개/ }).count(), 0);
  await ctx.close();
});
```

- [ ] **Step 2: 실패 확인** — Expected: 7개 FAIL
- [ ] **Step 3: 구현** — Interfaces 대로. `verify_w3b_card_facts_ui.cjs` 의 보기 모드 단언(블록 칩 이름, '근거:' 줄, '고치기' 버튼으로 수정 시작)은 이 결정대로 고친다(수정 시작은 '수정하기').
- [ ] **Step 4: 통과 확인** — Expected: 지금까지 20개 PASS, `verify_w3b_card_facts_ui.cjs` PASS.

---

### Task 4: 카드 상세 수정 모드 (o06d·o06f)

**Files:**
- Create: `web/components/owner/fact-card/sortable-list.tsx`
- Modify: `web/components/owner/fact-card/fact-card-panel.tsx`(수정 모드·`FactCardEditFooter`), `web/components/owner/fact-card/fact-row.tsx`(수정 모드 버튼), `web/app/owner/cards/[cardId]/page.tsx`
- Test: `api/scripts/verify_ui_cards.cjs`

**Interfaces:**
- Consumes: `useLongPress`, `Sheet`, `useFeedback`, 지금의 `useFactCardEditor`(`start`, `cancel`, `submit`, `actions.moveStep`, `actions.moveDisplay`, `remove`, `setEditKey`, `setAdding`, `dirty`, `save`)
- Produces:
  - '수정하기' → `editor.start()`. 수정 중엔 머리의 '수정하기' 를 숨긴다.
  - 하단(수정 중): 한 줄에 두 버튼, 왼쪽 **'수정 완료'**(primary, `disabled={!dirty}`, `loading`), 오른쪽 **'돌아가기'**(secondary) — `flex gap-2`, 각 `flex-1`. 저장 오류 안내(지금 `FactCardEditFooter` 의 충돌·재시도 블록)는 버튼 위에 그대로. '사실 추가'·'그만두기' 버튼은 없앤다.
  - 수정 완료 성공 → 수정 모드를 닫고 토스트 **"수정 완료"**(되돌리기 스낵바는 서버 뒤, 백로그).
  - 돌아가기 → 저장 없이 `editor.cancel()`. 고친 게 있으면 확인 창(`ConfirmDialog` 제목 "고친 내용을 버릴까요?", 확인 "버리기", tone danger).
  - 수정 중 블록 맨 아래에 "+ 사실 추가" 줄 버튼(`editor.setAdding(true)`).
  - `SortableList({ items, canMove, onMove, renderItem })` — `items: { key: string }[]`, `canMove(from: number, to: number): boolean`, `onMove(key: string, dir: -1 | 1): void`. 각 줄 오른쪽 손잡이(`aria-label="<문장 앞 12자> 옮기기"`, `≡`)를 포인터로 끌면 줄 높이 절반을 넘을 때마다 `canMove` 가 참일 때만 `onMove(key, ±1)` 한 칸씩. 손잡이에 포커스하고 위·아래 화살표도 같은 동작. 지금 행의 '위로'·'아래로' 버튼은 없앤다(손잡이가 대신).
  - 줄을 길게 누르면(`useLongPress`) 시트(제목 = 문장 앞 20자) '고치기'(`setEditKey`)·'빼기'(`remove`). 줄 안의 '고치기'·'빼기' 작은 버튼은 남긴다.
  - 보기 모드에서는 손잡이·길게 누르기가 없다(읽기 전용).

- [ ] **Step 1: 테스트 작성**

```js
async function startEdit(page) { await page.getByRole('button', { name: '수정하기' }).click(); await page.getByRole('button', { name: '수정 완료' }).waitFor(); }

test('o06f 수정 모드 하단은 수정 완료 왼쪽 초록, 돌아가기 오른쪽 흰색', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/cards/1');
  await startEdit(page);
  const done = page.getByRole('button', { name: '수정 완료' }), cancel = page.getByRole('button', { name: '돌아가기' });
  const [d, c] = [await done.boundingBox(), await cancel.boundingBox()];
  assert.ok(Math.abs(d.y - c.y) < 4 && d.x < c.x, '좌우');
  assert.equal(await page.getByRole('button', { name: '수정하기' }).count(), 0);
  for (const gone of ['고친 내용 저장', '그만두기']) assert.equal(await page.getByRole('button', { name: gone }).count(), 0, gone);
  await ctx.close();
});
test('o06d 보기 모드에는 손잡이가 없고 수정 모드에만 있다', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/cards/1');
  assert.equal(await page.getByRole('button', { name: /옮기기$/ }).count(), 0);
  await startEdit(page);
  assert.ok(await page.getByRole('button', { name: /옮기기$/ }).count() > 0);
  assert.equal(await page.getByRole('button', { name: /^위로|^아래로/ }).count(), 0);
  await ctx.close();
});
test('o06d 손잡이를 끌어 순서를 바꾸고 수정 완료하면 저장, 수정 완료 토스트', async (b) => {
  const { page, ctx, api } = await open(b, 'OWNER', '/owner/cards/1');
  await startEdit(page);
  const handle = page.getByRole('button', { name: '물을 붓는다. 옮기기' });
  const box = await handle.boundingBox();
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2); await page.mouse.down();
  await page.mouse.move(box.x + box.width / 2, box.y - 70, { steps: 12 }); await page.mouse.up();
  const order = await page.locator('[data-testid="fact-row"]').allInnerTexts();
  assert.ok(order.findIndex((t) => t.includes('물을 붓는다.')) < order.findIndex((t) => t.includes('샷을 붓는다.')));
  await page.getByRole('button', { name: '수정 완료' }).click();
  await page.getByRole('status').getByText('수정 완료').waitFor();
  assert.ok(api.calls.some((c) => c.method === 'PUT' && c.path === '/cards/1/facts'));
  await page.getByRole('button', { name: '수정하기' }).waitFor();
  await ctx.close();
});
test('o06d 손잡이는 키보드 화살표로도 옮긴다', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/cards/1');
  await startEdit(page);
  await page.getByRole('button', { name: '물을 붓는다. 옮기기' }).press('ArrowUp');
  const order = await page.locator('[data-testid="fact-row"]').allInnerTexts();
  assert.ok(order.findIndex((t) => t.includes('물을 붓는다.')) < order.findIndex((t) => t.includes('샷을 붓는다.')));
  await ctx.close();
});
test('o06d 선행 단계 앞으로는 끌어도 안 옮겨진다', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/cards/1');
  await startEdit(page);
  await page.getByRole('button', { name: '샷을 붓는다. 옮기기' }).press('ArrowUp'); // 샷은 1번(얼음) 뒤여야 한다
  const order = await page.locator('[data-testid="fact-row"]').allInnerTexts();
  assert.ok(order.findIndex((t) => t.includes('컵에 얼음을 담는다.')) < order.findIndex((t) => t.includes('샷을 붓는다.')));
  await ctx.close();
});
test('o06d 수정 모드에서 줄을 길게 누르면 고치기 빼기 시트', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/cards/1');
  await startEdit(page);
  const row = page.locator('[data-testid="fact-row"]').filter({ hasText: '뚜껑을 닫는다.' });
  await row.scrollIntoViewIfNeeded();
  const box = await row.boundingBox();
  await page.mouse.move(box.x + 30, box.y + 12); await page.mouse.down(); await page.waitForTimeout(650); await page.mouse.up();
  const sheet = page.getByRole('dialog', { name: /뚜껑을 닫는다/ });
  await sheet.getByRole('button', { name: '빼기' }).waitFor();
  await sheet.getByRole('button', { name: '고치기' }).waitFor();
  await ctx.close();
});
test('o06f 돌아가기는 저장하지 않는다', async (b) => {
  const { page, ctx, api } = await open(b, 'OWNER', '/owner/cards/1');
  await startEdit(page);
  await page.getByRole('button', { name: '물을 붓는다. 옮기기' }).press('ArrowUp');
  await page.getByRole('button', { name: '돌아가기' }).click();
  await page.getByRole('dialog', { name: '고친 내용을 버릴까요?' }).getByRole('button', { name: '버리기' }).click();
  await page.getByRole('button', { name: '수정하기' }).waitFor();
  assert.equal(api.calls.filter((c) => c.method === 'PUT').length, 0);
  const order = await page.locator('[data-testid="fact-row"]').allInnerTexts();
  assert.ok(order.findIndex((t) => t.includes('샷을 붓는다.')) < order.findIndex((t) => t.includes('물을 붓는다.')));
  await ctx.close();
});
```

- [ ] **Step 2: 실패 확인** — Expected: 7개 FAIL
- [ ] **Step 3: 구현** — Interfaces 대로. `verify_w3b_card_facts_ui.cjs` 의 수정 모드 단언('위로 (…)', '아래로 (…)' 버튼, '고친 내용 저장', '그만두기', '사실 추가')은 손잡이·'수정 완료'·'돌아가기'·'+ 사실 추가'로 고친다.
- [ ] **Step 4: 통과 확인** — Expected: 지금까지 27개 PASS, `verify_w3b_card_facts_ui.cjs` PASS.

---

### Task 5: 제안 화면 (o08a·o08b)

**Files:**
- Create: `web/lib/diff-words.ts`, `web/tests/diff-words.test.mjs`
- Modify: `web/app/owner/cards/proposals/page.tsx`
- Test: `api/scripts/verify_ui_cards.cjs`

**Interfaces:**
- Produces:
  - `diffWords(before: string, after: string): { text: string; kind: "same" | "del" | "add" }[]` — 공백 기준 낱말 LCS. 이어진 같은 종류는 하나로 합치고 낱말 사이 공백을 보존한다. import 없음.
  - 제안 카드(o08a): 질문 한 줄("직원 질문: …"), 그 아래 카드 이름(굵게)과 **바뀐 부분만 강조한 한 덩어리 글** — `del` 은 회색 취소선(`line-through text-ink-muted`), `add` 는 굵게 초록 배경(`bg-brand-100 font-bold`), `same` 은 보통. 조각마다 `data-diff="<kind>"`. '지금 카드' / '제안 내용' 두 상자는 없앤다.
  - 버튼(o08b): **'수정 완료'**(primary, `approve`) 하나, 그 아래 `TextButton` 회색 작은 글 **'수정하지 않고 돌아가기'**(`dismiss`). 연결된 카드 확인 버튼(`affected_cards` 링크), 승인 안내 캡션은 없앤다. 성공하면 각각 토스트 "카드에 반영했어요" / "그대로 뒀어요".
  - `?card_id=<id>` 가 있으면 그 카드에 걸린 제안만 보인다.

- [ ] **Step 1: 테스트 작성**

  단위(`web/tests/diff-words.test.mjs`):

```js
import { test } from "node:test";
import assert from "node:assert/strict";
import { diffWords } from "../lib/diff-words.ts";
test("바뀐 낱말만 del/add", () => {
  assert.deepEqual(diffWords("ICE 시럽 2펌프", "ICE 시럽 3펌프"), [
    { text: "ICE 시럽 ", kind: "same" }, { text: "2펌프", kind: "del" }, { text: "3펌프", kind: "add" },
  ]);
});
test("같으면 하나, 비면 전부 add", () => {
  assert.deepEqual(diffWords("우유 200", "우유 200"), [{ text: "우유 200", kind: "same" }]);
  assert.deepEqual(diffWords("", "새 내용"), [{ text: "새 내용", kind: "add" }]);
});
```

  브라우저:

```js
test('o08a 바뀐 부분만 강조, 지금 카드 제안 내용 상자 없음', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/cards/proposals');
  assert.equal(await page.locator('main del, main s, main [data-diff="del"]').filter({ hasText: '2펌프' }).count(), 1);
  assert.equal(await page.locator('main [data-diff="add"]').filter({ hasText: '3펌프' }).count(), 1);
  for (const gone of ['지금 카드', '제안 내용']) assert.equal(await page.getByText(gone, { exact: true }).count(), 0, gone);
  await ctx.close();
});
test('o08b 수정 완료 하나와 작은 돌아가기, 카드 확인 버튼 없음', async (b) => {
  const { page, ctx, api } = await open(b, 'OWNER', '/owner/cards/proposals?card_id=1');
  assert.equal(await page.getByRole('link', { name: /확인$/ }).count(), 0);
  const back = page.getByRole('button', { name: '수정하지 않고 돌아가기' });
  assert.ok(parseFloat(await back.evaluate((e) => getComputedStyle(e).fontSize)) <= 14);
  await page.getByRole('button', { name: '수정 완료' }).click();
  await page.getByRole('status').getByText('카드에 반영했어요').waitFor();
  assert.ok(api.calls.some((c) => c.path === '/learn/knowledge-proposals/9/approve'));
  await ctx.close();
});
```

- [ ] **Step 2: 실패 확인** — Expected: 단위 2, 브라우저 2 FAIL
- [ ] **Step 3: 구현** — Interfaces 대로. `verify_ui_rebrand.cjs` 의 제안 화면 단언('확인한 카드 공개', '공개하지 않고 제안 닫기')은 새 버튼으로 고친다.
- [ ] **Step 4: 통과 확인** — Expected: `ui-cards` 29개, 단위 테스트 전부, `ui-nav 30`·`ui-intake 27`·기존 CI 스크립트 PASS, `pnpm check` 통과.

---

## 실행 순서와 확인

Task 1 → 2 → 3 → 4 → 5. 마지막 확인:
- `cd web && pnpm check` 통과(node test 에 `diff-words` 추가)
- `verify_ui_nav.cjs` 30, `verify_ui_intake.cjs` 27, `verify_ui_cards.cjs` 29, `verify_r_ui.cjs`·`verify_r_history_ui.cjs`·`verify_ui_rebrand.cjs`·`verify_w3b_card_facts_ui.cjs` PASS
- 미룬 지적은 `UI_REDESIGN_BACKLOG_20261106.md` 에 이어 적는다
