# 화면 개선 계획 1: 이동·공통 키트 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 뒤로가기·하단 탭·알림 주소를 고쳐 길을 잃지 않게 하고, 이후 화면 계획들이 쓸 공통 키트(모션·누름 반응·토스트·스낵바·확인 창·배너)와 '중간점 금지' 검사를 만든다.

**Architecture:** 앱 안 이동 기록을 sessionStorage 스택(`lib/nav-stack.ts` 순수 함수 + `lib/nav-history.tsx` provider)으로 추적하고, 뒤로 버튼은 기록이 있으면 `router.back()`, 없으면 부모로 `router.replace()` 한다. 화면 진입 모션은 그 스택의 방향(앞·뒤·탭)을 `Screen` 의 `data-enter` 로 받아 CSS 로 그린다. 서버 알림 주소는 `app/notifications/destinations.py` 한 곳에서 만든다.

**Tech Stack:** Next.js 16 App Router, React 19, Tailwind 4, TanStack Query 5, Playwright 1.62(합성 API), Node 24 내장 `node --test`(타입 제거 실행), FastAPI·pytest.

**Spec:** `docs/dev/plan/UI_REDESIGN_SPEC_20261106.md` (이동 NAV-1~5·8~12, G1·G2·G4)

## Global Constraints

- 중간점 `·` 은 화면에 보이는 글(문자열 리터럴·JSX 글)에 쓰지 않는다. 주석·서버가 준 데이터(카테고리 이름 등)는 대상이 아니다.
- 모션: 이즈 아웃 `cubic-bezier(0.22, 1, 0.36, 1)`, 기본 220ms, 짧은 것 150ms. 스프링 `cubic-bezier(0.34, 1.56, 0.64, 1)`. 누르면 `scale(0.97)`. `prefers-reduced-motion` 은 `globals.css` 의 기존 규칙이 끈다.
- 스낵바는 5초, 토스트는 2초. 한 번에 하나만 보이고 새 것이 옛 것을 바꾼다.
- `web/` 에 Supabase 클라이언트·LLM 키 금지. 화면 검증은 합성 API 로만 한다(실데이터·운영 금지).
- 옛 알림 주소 리다이렉트(`/owner/questions/v2`, `/owner/cards/review`, `/staff/chat/v2`, `/staff/roadmap`, `/staff/items/:id`, `/owner/upload`, `/owner/dashboard`)는 이미 저장된 알림 때문에 지우지 않는다.
- `api/app/learn/*` 는 R 담당 파일이다. Task 8 은 R 쪽 동시 편집이 없을 때 한다(CLAUDE.md 두 파이프라인 소유권).
- 커밋 접두사: 웹은 `[output]`, 서버 알림 주소는 `[output]`, 문서는 `[docs]`.

## Review Focus

1. **알림·카톡 링크로 앱을 처음 연 경우**(앱 안 기록 0): 앱 뒤로는 부모로 가야 하고, 그 뒤 폰 뒤로가 같은 화면으로 돌아오면 안 된다 → Task 1 `NAV-1 주소로 바로 연 카드 상세` 테스트.
2. **새로고침 뒤 뒤로**: sessionStorage 스택이 남아 있으니 앱 뒤로가 브라우저 뒤로와 같은 곳으로 가야 한다 → Task 1 `NAV-1 새로고침 뒤`.
3. **sessionStorage 를 못 쓰는 브라우저**(사파리 개인 모드 일부): 예외 없이 '기록 없음'으로 동작해 부모로 가야 한다 → Task 1 `nav-stack` 단위 테스트 `readStack 이 던지면 빈 스택`.
4. **Cmd/Ctrl·가운데 클릭으로 뒤로 버튼을 새 탭에서 열기**: 가로채지 말고 부모 주소를 새 탭에 연다 → Task 1 `BackButton 보조 키 클릭은 가로채지 않는다`.
5. **스낵바가 떠 있는 중 다른 화면으로 이동**: 되돌리기 콜백이 언마운트된 화면 상태를 건드리면 안 된다. 스낵바는 이동하면 닫힌다 → Task 6 `스낵바는 화면을 옮기면 닫힌다`.

---

## 파일 구조

| 파일 | 책임 |
|---|---|
| `web/lib/nav-stack.ts` (새) | 순수 함수: 이동 기록 스택 갱신·방향 계산·저장 읽기 |
| `web/lib/nav-history.tsx` (새) | provider: 주소 변화·popstate 를 듣고 스택 유지, `useNavHistory`, `useBack` |
| `web/tests/nav-stack.test.mjs` (새) | `node --test` 단위 테스트 |
| `web/scripts/check-copy.mjs` (새) | 화면 글 중간점 검사(TypeScript 컴파일러 API) |
| `web/tests/check-copy.test.mjs` (새) | 검사기 단위 테스트 |
| `web/components/kit/buttons.tsx` | `BackButton` 을 `parent` 기반으로, `pressable` 상수, `ProfileButton`·`BellButton` |
| `web/components/kit/feedback.tsx` (새) | `FeedbackProvider`·`useFeedback`·`ConfirmDialog`·`Banner`·`CountBadge` |
| `web/components/kit/screen.tsx` | `Screen` 에 `data-enter`·탭 스크롤 기억 |
| `web/components/kit/tab-bar.tsx` | 탭 전환 replace |
| `web/components/kit/header-actions.tsx` (새) | 사람 아이콘 + 종(읽지 않은 수) |
| `web/public/figma/icon-user.svg`, `icon-bell.svg` (새) | 아이콘 |
| `web/app/globals.css` | 모션 토큰·키프레임 |
| `web/app/providers.tsx` | `NavHistoryProvider`·`FeedbackProvider` 장착 |
| `api/scripts/ui_fixture.cjs` (새) | 합성 API 공용 fixture |
| `api/scripts/verify_ui_nav.cjs` (새) | 이동·키트 브라우저 회귀 |
| `api/app/notifications/destinations.py` (새) | 서버 알림·이동 주소 단일 출처 |
| `api/tests/test_notification_destinations.py` (새) | 주소 함수·옛 주소 정적 검사 |
| `.github/workflows/r-validation.yml` | 새 브라우저 검사 실행 |

---

### Task 1: 앱 안 이동 기록과 뒤로 버튼 (NAV-1)

**Files:**
- Create: `web/lib/nav-stack.ts`, `web/lib/nav-history.tsx`, `web/tests/nav-stack.test.mjs`, `api/scripts/ui_fixture.cjs`, `api/scripts/verify_ui_nav.cjs`
- Modify: `web/components/kit/buttons.tsx` (`BackButton`), `web/components/ui.tsx` (`TopBar`), `web/app/providers.tsx`, `web/package.json`, `.github/workflows/r-validation.yml`, 그리고 `BackButton`·`TopBar backHref` 를 쓰는 모든 화면(아래 부모 표)

**Interfaces:**
- Produces:
  - `type NavMode = "push" | "replace" | "pop"`
  - `type NavEnter = "forward" | "back" | "fade" | "initial"`
  - `nextStack(stack: string[], url: string, mode: NavMode): string[]`
  - `enterOf(mode: NavMode | "initial"): NavEnter` — push→forward, pop→back, replace→fade
  - `readStack(storage: Pick<Storage, "getItem"> | null, url: string): string[]` — 저장된 스택 맨 위가 `url` 이면 그 스택, 아니면 `[url]`. 읽기가 던지거나 JSON 이 깨지면 `[url]`
  - `NAV_STACK_KEY = "askbuddy:nav-stack"`, 스택 최대 길이 `NAV_STACK_LIMIT = 50`(넘으면 앞에서 자른다)
  - `NavHistoryProvider({ children })`, `useNavHistory(): { canGoBack(): boolean; enter: NavEnter; markReplace(): void }`
  - `useBack(parent: string): () => void`
  - `BackButton({ parent, label = "뒤로" }: { parent: string; label?: string })`
  - `api/scripts/ui_fixture.cjs`: `syntheticApi(role: "OWNER" | "STAFF", overrides?: object) → { handler(route), misses: string[], calls: {method, path, body}[], state }`

- [ ] **Step 1: 단위 테스트 작성** — `web/tests/nav-stack.test.mjs`

```js
import { test } from "node:test";
import assert from "node:assert/strict";
import { nextStack, enterOf, readStack, NAV_STACK_LIMIT } from "../lib/nav-stack.ts";

test("push 는 쌓고 같은 주소 반복은 무시한다", () => {
  assert.deepEqual(nextStack(["/owner"], "/owner/cards/1", "push"), ["/owner", "/owner/cards/1"]);
  assert.deepEqual(nextStack(["/owner", "/owner/cards/1"], "/owner/cards/1", "push"), ["/owner", "/owner/cards/1"]);
});
test("replace 는 맨 위만 바꾼다", () => {
  assert.deepEqual(nextStack(["/owner", "/owner/add"], "/owner/jobs/7", "replace"), ["/owner", "/owner/jobs/7"]);
});
test("pop 은 바로 아래와 같으면 꺼내고, 다르면(앞으로 가기) 쌓는다", () => {
  assert.deepEqual(nextStack(["/owner", "/owner/cards/1"], "/owner", "pop"), ["/owner"]);
  assert.deepEqual(nextStack(["/owner"], "/owner/cards/1", "pop"), ["/owner", "/owner/cards/1"]);
});
test("스택은 최대 길이를 넘지 않는다", () => {
  let stack = ["/0"];
  for (let i = 1; i <= NAV_STACK_LIMIT + 5; i++) stack = nextStack(stack, `/${i}`, "push");
  assert.equal(stack.length, NAV_STACK_LIMIT);
  assert.equal(stack.at(-1), `/${NAV_STACK_LIMIT + 5}`);
});
test("방향", () => {
  assert.equal(enterOf("push"), "forward");
  assert.equal(enterOf("pop"), "back");
  assert.equal(enterOf("replace"), "fade");
  assert.equal(enterOf("initial"), "initial");
});
test("readStack: 저장 맨 위가 지금 주소면 이어 쓴다(새로고침)", () => {
  const storage = { getItem: () => JSON.stringify(["/owner", "/owner/cards/1"]) };
  assert.deepEqual(readStack(storage, "/owner/cards/1"), ["/owner", "/owner/cards/1"]);
  assert.deepEqual(readStack(storage, "/staff"), ["/staff"]);
});
test("readStack 이 던지거나 깨진 값이면 빈 스택(지금 주소 하나)", () => {
  assert.deepEqual(readStack({ getItem: () => { throw new Error("blocked"); } }, "/owner"), ["/owner"]);
  assert.deepEqual(readStack({ getItem: () => "{oops" }, "/owner"), ["/owner"]);
  assert.deepEqual(readStack(null, "/owner"), ["/owner"]);
});
```

- [ ] **Step 2: 실패 확인**

`web/package.json` scripts 에 `"test": "node --test tests/"` 를 넣고, `check` 를 `"next typegen && pnpm lint && pnpm typecheck && pnpm test && pnpm build"` 로 바꾼다.
Run: `cd web && pnpm test`
Expected: FAIL — `Cannot find module '../lib/nav-stack.ts'`

- [ ] **Step 3: `web/lib/nav-stack.ts` 구현** — 위 Interfaces 의 시그니처 그대로. 이 파일은 import 가 없어야 한다(`node --test` 가 바로 읽는다).

- [ ] **Step 4: 통과 확인** — Run: `cd web && pnpm test` / Expected: 7 tests pass

- [ ] **Step 5: provider 와 뒤로 버튼 구현**
  - `web/lib/nav-history.tsx`: `usePathname()`+`useSearchParams()` 로 만든 주소가 바뀔 때마다 `nextStack(stack, url, pendingMode ?? "push")` 를 적용하고 sessionStorage 에 쓴다(try/catch). `popstate` 리스너가 `pendingMode = "pop"`, `markReplace()` 가 `pendingMode = "replace"` 를 넣고, 적용 뒤 비운다. 첫 마운트는 `readStack(sessionStorage, url)`, `enter = "initial"`. `useSearchParams` 때문에 provider 는 `<Suspense fallback={children}>` 안에 둔다.
  - `useBack(parent)`: `canGoBack()` 이면 `router.back()`, 아니면 `markReplace(); router.replace(parent)`.
  - `BackButton`: `<Link href={parent} data-back="">` 를 그리고, `onClick` 에서 `event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button !== 0` 이면 아무것도 안 하고, 아니면 `preventDefault()` 후 `useBack(parent)()`. 기존 모양(`min-h-11`, 왼쪽 화살표, 그림자) 유지.
  - `TopBar` 의 `backHref` 링크도 같은 방식으로 `useBack(backHref)` 를 쓴다.
  - `web/app/providers.tsx`: `AppProvider` 안쪽에 `NavHistoryProvider` 로 감싼다.

- [ ] **Step 6: 모든 호출부를 `parent` 로 바꾼다** — `href` prop 이 사라졌으니 `pnpm typecheck` 가 남은 곳을 알려준다. 부모는 아래 표대로(달라지는 곳은 굵게).

| 화면 | 파일 | 부모 |
|---|---|---|
| 카드 상세(모든 상태) | `app/owner/cards/[cardId]/page.tsx` | `/owner/cards` |
| 다른 답 확인 | `app/owner/cards/proposals/page.tsx` | `/owner/cards` |
| 넣기 | `app/owner/add/page.tsx` | `/owner` |
| 정리 중·결과 | `app/owner/jobs/[jobId]/page.tsx` | `/owner` |
| 직원 질문 목록 | `app/owner/questions/questions-list.tsx` | `/owner` |
| 질문 답하기(모든 상태) | `app/owner/questions/[pendingId]/page.tsx` | **`/owner`** (163행은 지금 `/owner/questions`) |
| 레시피 상세 | `app/staff/recipes/[itemId]/page.tsx` | `/staff/recipes` |
| 버디 대화 | `components/staff/ask-screen.tsx` | `/staff` |
| 설정 | `components/settings-screen.tsx` | `/owner` 또는 `/staff` |
| 직원 담당 근무조 | `components/checklist/member-settings.tsx` | **`/owner/members`** (NAV-11) |
| 기록 | `components/checklist/records-screen.tsx` | `/{role}/settings` |
| 근무조 설정 | `components/checklist/settings-screen.tsx` | `/owner/settings` |
| 직원 관리 (TopBar) | `app/owner/members/page.tsx` | `/owner/settings` |
| 카테고리 (TopBar) | `app/owner/categories/page.tsx` | **`/owner/settings`** (지금 `/owner/cards`) |
| 알림 (TopBar) | `app/owner/notifications/page.tsx` | **`/owner`** (지금 `/owner/upload`, T3) |
| 업종 선택·이메일 로그인·개발 키트 | 그대로 | 그대로 |

- [ ] **Step 7: 합성 fixture 작성** — `api/scripts/ui_fixture.cjs`

  `syntheticApi(role, overrides)` 는 `http://localhost:8000/**` 요청을 받아 아래 고정 데이터로 답한다. 모르는 경로는 `misses` 에 `"METHOD /path"` 로 넣고 404 를 준다. 응답 모양은 `web/lib/api.ts`·`web/lib/r-v2-api.ts` 의 타입을 따른다(`verify_ui_rebrand.cjs` 의 `listItem`·`detail`·`/checklist/today` 모양을 그대로 옮겨 쓴다).
  - 매장 `{ store_id: 1, store_name: "골목커피 연남점", guide_completed: true }`, 사장 user_id 1 '김사장', 직원 user_id 2 '박지호'.
  - 알림 `GET /notifications` → `unread_count: 3`, 항목 3개(질문 101, 작업 7 완료, 합류 요청).
  - 사장 질문 대기 101 '디카페인 원두는 어디 있어요?', 102 '오트밀크 라떼도 시럽 2펌프인가요?' (`/learn/v2/pending`, `/learn/v2/pending/101`).
  - 카드 1 '바닐라 라떼'(APPROVED, 음료 레시피), 2 '아메리카노'(APPROVED), 3 '마감 머신 청소'(NEEDS_REVIEW), 4 '오픈 준비'(PENDING), 5 '원두 보관 위치'(PENDING), 6 '우유 발주'(APPROVED). 카테고리 10 '음료 레시피', 11 '오픈 마감', 12 '재고 위치'.
  - 직원 로드맵 항목 11 '바닐라 라떼'(card 1) 외 4개, `/learn/items/11`.
  - 작업 7(SUCCEEDED, 카드 4), 넣기 제출 경로 `POST /ingest/upload-url`(→ `upload_url: "http://localhost:8000/storage/put"`), `PUT /storage/put`, `POST /ingest/sources`, `POST /ingest/jobs`(→ `job_id: 7`).
  - 근무조 오픈·미들·마감, 직원 박지호·김민준, 합류 대기 이서연.

- [ ] **Step 8: 브라우저 회귀 테스트 작성** — `api/scripts/verify_ui_nav.cjs`

```js
// 이동·공통 키트 회귀. 합성 API(ui_fixture.cjs)만 쓴다.
// 실행: next start -p 3011 을 띄운 뒤 NODE_PATH=<playwright> node api/scripts/verify_ui_nav.cjs
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const { syntheticApi } = require('./ui_fixture.cjs');

const BASE = process.env.UI_BASE || 'http://127.0.0.1:3011';
const here = (page) => { const u = new URL(page.url()); return u.pathname + u.search; };
const cases = [];
const test = (name, fn) => cases.push([name, fn]);
const opened = [];

async function open(browser, role, url, { viewport = { width: 390, height: 844 }, overrides } = {}) {
  const api = syntheticApi(role, overrides);
  opened.push(api);
  const ctx = await browser.newContext({ viewport, locale: 'ko-KR' });
  await ctx.route('http://localhost:8000/**', api.handler);
  const page = await ctx.newPage();
  await page.goto(BASE + url);
  await page.waitForLoadState('networkidle');
  return { ctx, page, api };
}
// 앱 뒤로 버튼. 화면마다 글자(카드·직원 질문·뒤로)가 달라 표시 속성으로 찾는다.
const back = (page) => page.locator('[data-back]').first();
async function to(page, path) { await page.waitForURL((u) => u.pathname + u.search === path, { timeout: 5000 }); }
// 폰 뒤로가기. 앱 밖(첫 화면 이전)으로 나가면 about:blank 가 된다.
async function phoneBack(page) { await page.goBack({ waitUntil: 'networkidle' }).catch(() => null); return page.url().startsWith('about:') ? 'about:blank' : here(page); }

test('NAV-1 질문 상세의 앱 뒤로는 왔던 오늘 매장, 폰 뒤로로 상세에 돌아가지 않는다', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner');
  await page.getByText('디카페인 원두는 어디 있어요?').first().click(); await to(page, '/owner/questions/101');
  await back(page).click(); await to(page, '/owner');
  assert.notEqual(await phoneBack(page), '/owner/questions/101');
  await ctx.close();
});
test('NAV-1 카드 상세 왕복이 없다', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/cards');
  await page.getByText('바닐라 라떼').first().click(); await to(page, '/owner/cards/1');
  await back(page).click(); await to(page, '/owner/cards');
  assert.notEqual(await phoneBack(page), '/owner/cards/1');
  await ctx.close();
});
test('NAV-1 주소로 바로 연 카드 상세의 뒤로는 부모로 replace', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/cards/1');
  const before = await page.evaluate(() => history.length);
  await back(page).click(); await to(page, '/owner/cards');
  assert.equal(await page.evaluate(() => history.length), before, '기록이 쌓이지 않는다');
  assert.equal(await phoneBack(page), 'about:blank');
  await ctx.close();
});
test('NAV-1 레시피에서 연 버디의 뒤로는 레시피 상세', async (b) => {
  const { page, ctx } = await open(b, 'STAFF', '/staff/recipes');
  await page.getByText('바닐라 라떼').first().click(); await to(page, '/staff/recipes/11');
  await page.getByText('이 레시피에 대해 물어보기').click(); await page.waitForURL(/\/staff\/ask/);
  await back(page).click(); await to(page, '/staff/recipes/11');
  await ctx.close();
});
test('NAV-1 새로고침 뒤에도 앱 뒤로는 왔던 곳', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/cards');
  await page.getByText('바닐라 라떼').first().click(); await to(page, '/owner/cards/1');
  await page.reload({ waitUntil: 'networkidle' });
  await back(page).click(); await to(page, '/owner/cards');
  assert.notEqual(await phoneBack(page), '/owner/cards/1');
  await ctx.close();
});
test('NAV-1 옛 상단 바(알림)의 뒤로: 기록이 없으면 오늘 매장(T3)', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/notifications');
  await page.getByRole('link', { name: '뒤로가기' }).click(); await to(page, '/owner');
  await ctx.close();
});
test('NAV-1 BackButton 보조 키 클릭은 가로채지 않는다', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/cards/1');
  const popup = ctx.waitForEvent('page');
  await back(page).click({ modifiers: [process.platform === 'darwin' ? 'Meta' : 'Control'] });
  const tab = await popup; await tab.waitForLoadState();
  assert.equal(new URL(tab.url()).pathname, '/owner/cards');
  assert.equal(here(page), '/owner/cards/1');
  await ctx.close();
});

(async () => {
  const only = process.argv[2];
  const browser = await chromium.launch({ headless: true });
  let passed = 0;
  for (const [name, fn] of cases) {
    if (only && !name.startsWith(only)) continue;
    await fn(browser);
    // fixture 가 모르는 API 를 부른 화면은 실패로 본다(합성 데이터가 화면을 다 덮는지)
    for (const api of opened.splice(0)) assert.deepEqual(api.misses, [], `${name} 모르는 API`);
    passed++; console.log('PASS ui-nav', name);
  }
  await browser.close();
  console.log(`ui-nav ${passed} passed`);
})().catch((error) => { console.error(error); process.exit(1); });
```

- [ ] **Step 9: 실패 확인 → 통과 확인**

Run: `cd web && pnpm build && (pnpm exec next start -p 3011 &) && sleep 5 && NODE_PATH=$PWD/../api/tmp/browser/node_modules node ../api/scripts/verify_ui_nav.cjs NAV-1`
Expected: Step 5·6 전에는 'NAV-1 질문 상세…' 이 `notEqual` 로 실패, 뒤에는 `ui-nav 7 passed`.

- [ ] **Step 10: CI 에 추가** — `.github/workflows/r-validation.yml` browser 잡의 마지막 줄 뒤에 `NODE_PATH="$PWD/api/tmp/browser/node_modules" node api/scripts/verify_ui_nav.cjs` 를 넣는다.

- [ ] **Step 11: 정적 검사** — Run: `cd web && pnpm check` / Expected: lint·typecheck·test·build 통과

- [ ] **Step 12: 커밋**

```bash
git add web/lib/nav-stack.ts web/lib/nav-history.tsx web/tests web/package.json web/components web/app api/scripts/ui_fixture.cjs api/scripts/verify_ui_nav.cjs .github/workflows/r-validation.yml
git commit -m "[output] 앱 뒤로 버튼을 왔던 곳으로, 기록이 없으면 부모로"
```

---

### Task 2: 완료 이동 replace, 설정 아래 계층, 막다른 화면 (NAV-2·11·12)

**Files:**
- Modify: `web/components/owner/owner-add-composer.tsx:53`, `web/app/owner/jobs/[jobId]/page.tsx:284`, `web/app/owner/intent/page.tsx`, `web/components/checklist/settings-screen.tsx:164`, `web/app/staff/chat/page.tsx`, `web/components/r-v2-notifications.tsx:36`
- Test: `api/scripts/verify_ui_nav.cjs`

**Interfaces:**
- Consumes: `useNavHistory().markReplace()` (Task 1) — `router.replace` 직전에 부른다.

- [ ] **Step 1: 테스트 추가** — `verify_ui_nav.cjs`

```js
test('NAV-2 넣기 → 작업 화면은 replace, 폰 뒤로는 넣기 전 화면', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner');
  await page.goto(BASE + '/owner/add'); await page.waitForLoadState('networkidle');
  await page.getByPlaceholder('여기에 말하거나 붙여넣기').fill('마감 때 머신 청소');
  await page.getByRole('button', { name: '넣기', exact: true }).click(); await to(page, '/owner/jobs/7');
  assert.equal(await phoneBack(page), '/owner');
  await ctx.close();
});
test('NAV-11 근무조의 직원 담당 버튼은 바로 직원 담당, 그 부모는 직원 관리', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/shifts');
  await page.getByRole('link', { name: '직원 담당 근무조' }).click(); await to(page, '/owner/member-shifts');
  await ctx.close();
  const direct = await open(b, 'OWNER', '/owner/member-shifts');
  await back(direct.page).click(); await to(direct.page, '/owner/members');
  await direct.ctx.close();
});
test('NAV-12 매장이 있는 점주가 매장 만들기 주소로 오면 기본 목적지로 넘어간다', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/intent');
  await to(page, '/owner');
  assert.equal(await page.getByText('이미 매장이 있어요').count(), 0);
  await ctx.close();
});
test('NAV-12 이전 대화 이력 주소는 버디로', async (b) => {
  const { page, ctx } = await open(b, 'STAFF', '/staff/chat');
  await page.waitForURL(/\/staff\/ask$/);
  await ctx.close();
});
```

- [ ] **Step 2: 실패 확인** — Run: `node ../api/scripts/verify_ui_nav.cjs NAV-2` (그리고 `NAV-11`, `NAV-12`) / Expected: 넷 다 FAIL

- [ ] **Step 3: 구현**
  - `owner-add-composer.tsx`: `router.push` → `markReplace(); router.replace(...)`.
  - `jobs/[jobId]/page.tsx:284`: 같은 방식으로 replace.
  - `intent/page.tsx`: `onSuccess` 는 replace. 매장이 있고 `create.isIdle` 이면 '이미 매장이 있어요' 화면 대신 `useEffect` 로 `router.replace(bootstrap.data.default_destination)` 하고 그동안 `Skeleton` 을 그린다. 서버 기본 목적지가 가이드 안 끝난 새 매장은 `/owner/add`, 끝난 매장은 `/owner` 라서, 매장 생성 직후 가드가 화면을 다시 올려도 `/owner/add` 로 간다(기존 주석이 걱정한 덮어쓰기가 생기지 않는다). 그 주석을 이 이유로 바꾼다.
  - `settings-screen.tsx:164`: `href="/owner/member-shifts"`.
  - `app/staff/chat/page.tsx`: `redirect("/staff/ask")` 만 남긴 서버 컴포넌트로 바꾼다(`chatQuery` 를 다른 곳이 안 쓰면 같이 지운다).
  - `r-v2-notifications.tsx:36`: `href="/staff/ask"`.

- [ ] **Step 4: 통과 확인** — Run: `node ../api/scripts/verify_ui_nav.cjs NAV-` / Expected: 지금까지 11개 PASS

- [ ] **Step 5: 커밋** — `git commit -m "[output] 완료 뒤 이동은 기록에서 지우고, 직원 담당·막다른 화면 정리"`

---

### Task 3: 하단 탭 하나로, 탭 전환 replace, 탭별 스크롤 기억 (NAV-3·4)

**Files:**
- Modify: `web/components/kit/tab-bar.tsx`, `web/components/kit/screen.tsx`, `web/app/owner/questions/questions-list.tsx`, `web/app/staff/layout.tsx`
- Delete: `web/components/owner/owner-bottom-nav.tsx`, `web/components/staff-nav.tsx`
- Test: `api/scripts/verify_ui_nav.cjs`

**Interfaces:**
- Consumes: `useNavHistory().markReplace` (Task 1)
- Produces: `Screen` 이 `tabBar` 가 있을 때 스크롤 위치를 `sessionStorage["askbuddy:scroll:" + pathname]` 에 저장·복원

- [ ] **Step 1: 테스트 추가**

```js
test('NAV-3 탭을 오가도 폰 뒤로는 탭을 되짚지 않는다', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner');
  const before = await page.evaluate(() => history.length);
  const tabs = page.getByRole('navigation', { name: '주요 메뉴' });
  await tabs.getByRole('link', { name: '카드' }).click(); await to(page, '/owner/cards');
  await tabs.getByRole('link', { name: '오늘 매장' }).click(); await to(page, '/owner');
  assert.equal(await page.evaluate(() => history.length), before);
  await ctx.close();
});
test('NAV-3 탭마다 스크롤 위치를 기억한다', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/cards', { viewport: { width: 390, height: 480 } });
  await page.locator('main').evaluate((m) => { m.scrollTop = 300; m.dispatchEvent(new Event('scroll')); });
  const tabs = page.getByRole('navigation', { name: '주요 메뉴' });
  await tabs.getByRole('link', { name: '오늘 매장' }).click(); await to(page, '/owner');
  await tabs.getByRole('link', { name: '카드' }).click(); await to(page, '/owner/cards');
  await page.waitForTimeout(300);
  const top = await page.locator('main').evaluate((m) => m.scrollTop);
  assert.ok(Math.abs(top - 300) <= 2, `scrollTop ${top}`);
  await ctx.close();
});
test('NAV-4 옛 하단 탭이 어디에도 없다', async (b) => {
  for (const [role, url] of [['OWNER', '/owner/questions'], ['STAFF', '/staff/faqs']]) {
    const { page, ctx } = await open(b, role, url);
    for (const label of ['업로드', '답변 대기', '카드 목록', '학습', '자주 묻는 질문']) {
      assert.equal(await page.getByRole('navigation').getByText(label, { exact: true }).count(), 0, `${url} ${label}`);
    }
    await ctx.close();
  }
});
```

- [ ] **Step 2: 실패 확인** — Run: `node ../api/scripts/verify_ui_nav.cjs NAV-3` / `NAV-4` / Expected: FAIL (history.length 증가, scrollTop 0, '업로드' 있음)

- [ ] **Step 3: 구현**
  - `TabBar`: 각 `Link` 에 `replace` 와 `onClick={() => markReplace()}`. 이미 활성 탭이면 `preventDefault()` 하고 `main` 을 맨 위로 부드럽게 스크롤.
  - `Screen`: `tabBar` 가 있으면 `main` 의 `scroll` 을 requestAnimationFrame 으로 묶어 저장하고, 마운트 때 저장값으로 `scrollTop` 을 맞춘다. 데이터가 늦게 와 높이가 모자라면 `ResizeObserver` 로 높이가 충분해질 때 한 번 더 맞추고 관찰을 끝낸다.
  - `questions-list.tsx`: `OwnerBottomNav` 를 지운다(o09c: 이 화면은 탭 없음, `Screen` 에 `tabBar` 안 넘김).
  - `staff/layout.tsx`: `StaffBottomNav`·`showBottomNav` 를 지운다.
  - 두 옛 탭 컴포넌트 파일을 지운다.

- [ ] **Step 4: 통과 확인** — Run: `node ../api/scripts/verify_ui_nav.cjs NAV-` / Expected: 14개 PASS

- [ ] **Step 5: 커밋** — `git commit -m "[output] 하단 탭 하나로, 탭 전환은 기록에 안 쌓고 스크롤 기억"`

---

### Task 4: 헤더의 사람 아이콘과 종 (NAV-5·8·10)

**Files:**
- Create: `web/components/kit/header-actions.tsx`, `web/public/figma/icon-user.svg`, `web/public/figma/icon-bell.svg`
- Modify: `web/components/kit/icon.tsx` (`"user" | "bell"`), `web/components/kit/index.ts`, `web/app/owner/page.tsx:38`, `web/components/checklist/today-screen.tsx:169`, `web/app/staff/recipes/page.tsx:37`
- Delete: `web/components/owner/owner-page-header.tsx` (쓰는 곳 없음)
- Test: `api/scripts/verify_ui_nav.cjs`

**Interfaces:**
- Produces: `HeaderActions({ role }: { role: "OWNER" | "STAFF" })` — 종 링크(`aria-label` "알림" 또는 "알림 N개 읽지 않음", 오른쪽 위 빨간 숫자, 99 넘으면 "99+") + 사람 아이콘 원 링크(`aria-label` "설정"). 종 주소는 사장 `/owner/notifications`, 직원 `/staff/notifications/v2`. 읽지 않은 수는 `notificationsQuery(state.token, state.storeId).data?.unread_count` (같은 `/notifications` 를 두 역할 모두 쓴다). `SettingsButton` 은 쓰는 곳이 없어지면 지운다.
- 아이콘 SVG 는 기존 `icon-home.svg` 와 같은 20×20 viewBox, stroke-width 2, round cap·join. user = 머리 원(cx 10 cy 6.5 r 3.5) + 어깨 호, bell = 종 몸통 + 아래 짧은 추.

- [ ] **Step 1: 테스트 추가**

```js
test('NAV-10 사장 헤더: 사람 아이콘은 설정, 종은 읽지 않은 수와 함께 알림', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner');
  const bell = page.getByRole('link', { name: '알림 3개 읽지 않음' });
  await bell.waitFor();
  assert.equal((await bell.innerText()).trim(), '3');
  await page.getByRole('link', { name: '설정' }).click(); await to(page, '/owner/settings');
  await back(page).click(); await to(page, '/owner');
  await bell.click(); await to(page, '/owner/notifications');
  await ctx.close();
});
test('NAV-8 직원 헤더에도 종이 있다', async (b) => {
  const { page, ctx } = await open(b, 'STAFF', '/staff');
  await page.getByRole('link', { name: /^알림/ }).click(); await to(page, '/staff/notifications/v2');
  await ctx.close();
});
test('NAV-10 읽지 않은 알림이 없으면 숫자 없이 "알림"', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner', { overrides: { unreadCount: 0 } });
  await page.getByRole('link', { name: '알림', exact: true }).waitFor();
  await ctx.close();
});
```

  `ui_fixture.cjs` 는 `overrides.unreadCount` 로 `unread_count` 를 바꾼다.

- [ ] **Step 2: 실패 확인** — Run: `node ../api/scripts/verify_ui_nav.cjs NAV-10` / Expected: FAIL (종 링크 없음)
- [ ] **Step 3: 구현** — 위 Interfaces 대로. 헤더 오른쪽은 `종, 사람` 순서, 둘 다 44px 원, `gap-2`.
- [ ] **Step 4: 통과 확인** — Expected: NAV 17개 PASS
- [ ] **Step 5: 커밋** — `git commit -m "[output] 헤더에 설정 사람 아이콘과 알림 종"`

---

### Task 5: 화면 진입 모션과 누름 반응 (G1·G2)

**Files:**
- Modify: `web/app/globals.css`, `web/components/kit/screen.tsx`, `web/components/kit/buttons.tsx`, `web/components/kit/surface.tsx`, `web/components/kit/tab-bar.tsx`, `web/components/kit/checkbox.tsx`, `web/components/kit/header-actions.tsx`
- Test: `api/scripts/verify_ui_nav.cjs`

**Interfaces:**
- Consumes: `useNavHistory().enter` (Task 1)
- Produces:
  - CSS 변수 `--ease-out: cubic-bezier(0.22, 1, 0.36, 1)`, `--ease-spring: cubic-bezier(0.34, 1.56, 0.64, 1)`, `--dur-fast: 150ms`, `--dur-base: 220ms`
  - 키프레임 `screen-forward`(opacity 0, translateX(24px) → 원위치), `screen-back`(translateX(-24px)), `screen-fade`(opacity만), `check-pop`(scale 0.6 → 1)
  - `Screen` 바깥 div 에 `data-enter={enter}`; `[data-enter="forward"] > main` 등에 `animation: screen-* var(--dur-base) var(--ease-out)`. `initial` 은 모션 없음.
  - `export const pressable = "transition-transform duration-150 ease-[var(--ease-out)] active:scale-[0.97]"` (buttons.tsx). `Button`·`ButtonLink` 의 `active:scale-[0.98]` 을 이것으로 바꾸고, `BackButton`·`ListRow`·`CardLink`·`TabBar` 링크·`HeaderActions` 두 링크에도 붙인다.
  - `CheckRow` 의 체크 아이콘은 `animation: check-pop var(--dur-base) var(--ease-spring)`.

- [ ] **Step 1: 테스트 추가**

```js
test('G1 앞으로는 forward, 앱 뒤로는 back, 탭은 fade', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/cards');
  const enter = () => page.locator('[data-enter]').first().getAttribute('data-enter');
  assert.equal(await enter(), 'initial');
  await page.getByText('바닐라 라떼').first().click(); await to(page, '/owner/cards/1');
  assert.equal(await enter(), 'forward');
  await back(page).click(); await to(page, '/owner/cards');
  assert.equal(await enter(), 'back');
  await page.getByRole('navigation', { name: '주요 메뉴' }).getByRole('link', { name: '오늘 매장' }).click(); await to(page, '/owner');
  assert.equal(await enter(), 'fade');
  const anim = await page.locator('[data-enter] > main').first().evaluate((m) => getComputedStyle(m).animationName);
  assert.equal(anim, 'screen-fade');
  await ctx.close();
});
test('G2 누르는 동안 0.97로 줄어든다', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/cards/1');
  const btn = back(page);
  const box = await btn.boundingBox();
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2); await page.mouse.down();
  await page.waitForTimeout(250);
  const scale = await btn.evaluate((el) => new DOMMatrix(getComputedStyle(el).transform).a);
  await page.mouse.up();
  assert.ok(Math.abs(scale - 0.97) < 0.005, `scale ${scale}`);
  await ctx.close();
});
```

- [ ] **Step 2: 실패 확인** — Run: `node ../api/scripts/verify_ui_nav.cjs G` / Expected: FAIL (`data-enter` 없음)
- [ ] **Step 3: 구현** — 위 Interfaces 대로.
- [ ] **Step 4: 통과 확인** — Expected: NAV 17 + G 2 PASS
- [ ] **Step 5: 커밋** — `git commit -m "[output] 화면 진입 방향 모션과 누름 반응"`

---

### Task 6: 알림·피드백 키트 (G4)

**Files:**
- Create: `web/components/kit/feedback.tsx`
- Modify: `web/components/kit/index.ts`, `web/app/providers.tsx`, `web/app/dev/kit/page.tsx`, `.github/workflows/r-validation.yml`
- Test: `api/scripts/verify_ui_nav.cjs`

**Interfaces:**
- Produces:
  - `FeedbackProvider({ children })` — `providers.tsx` 에서 `NavHistoryProvider` 안쪽에 둔다. 주소가 바뀌면 떠 있는 토스트·스낵바를 닫는다.
  - `useFeedback(): { toast(message: string): void; snackbar(opts: { message: string; actionLabel: string; onAction: () => void; durationMs?: number }): void; dismiss(): void }` — 토스트 2000ms, 스낵바 기본 5000ms. 한 개만, 새 것이 바꾼다. 컨테이너 `role="status" aria-live="polite"`, 화면 아래 가운데, 탭바가 있는 화면에서도 가리지 않게 `bottom: calc(100px + env(safe-area-inset-bottom))`. 등장 `screen-fade` + translateY(8px), `--dur-base`, `--ease-out`.
  - `ConfirmDialog({ open, title, description, confirmLabel, cancelLabel = "취소", tone = "primary", loading = false, onConfirm, onCancel }: { open: boolean; title: string; description?: string; confirmLabel: string; cancelLabel?: string; tone?: "primary" | "danger"; loading?: boolean; onConfirm: () => void; onCancel: () => void })` — 네이티브 `<dialog>` 의 `showModal()`(포커스 가두기·Esc 기본 제공). Esc·바깥 누름은 `onCancel`. 버튼은 좌우: 취소(흰색) 왼쪽, 확인 오른쪽(`tone` 에 따라 primary 또는 danger).
  - `Banner({ tone = "info", children, action, onDismiss }: { tone?: "info" | "warn" | "danger"; children: ReactNode; action?: { label: string; onClick: () => void }; onDismiss?: () => void })` — `role="status"`(danger 는 `role="alert"`), 닫기 버튼 `aria-label="닫기"`.
  - `CountBadge({ n, tone = "neutral" }: { n: number; tone?: "neutral" | "danger" })` — 중간점 대신 쓰는 숫자 알약(Task 7 이 쓴다). 99 넘으면 "99+".
  - 개발 키트 `?s=feedback` 화면: 버튼 '토스트 보기'(메시지 "저장했어요"), '스낵바 보기'(메시지 "지웠어요", 동작 "되돌리기" → 누르면 화면 글 "되돌렸어요" 표시), '확인 창 보기'(제목 "로그아웃할까요?", 확인 "로그아웃", 누르면 "확인함"), danger 배너 하나("처리하지 못한 자료가 있어요.", 동작 "다시 시도").
  - 개발 키트 가드: `process.env.NODE_ENV === "production" && process.env.NEXT_PUBLIC_DEV_KIT !== "1"` 일 때만 `notFound()`. CI browser 잡의 `pnpm check` 단계에 `env: NEXT_PUBLIC_DEV_KIT: "1"`.

- [ ] **Step 1: 테스트 추가**

```js
test('G4 토스트는 2초 뒤 사라진다', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/dev/kit?s=feedback');
  await page.getByRole('button', { name: '토스트 보기' }).click();
  const toast = page.getByRole('status').getByText('저장했어요');
  await toast.waitFor();
  await toast.waitFor({ state: 'hidden', timeout: 3000 });
  await ctx.close();
});
test('G4 스낵바 되돌리기는 동작을 부르고 닫힌다', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/dev/kit?s=feedback');
  await page.getByRole('button', { name: '스낵바 보기' }).click();
  await page.getByRole('status').getByText('지웠어요').waitFor();
  await page.getByRole('button', { name: '되돌리기' }).click();
  await page.getByText('되돌렸어요').waitFor();
  assert.equal(await page.getByRole('button', { name: '되돌리기' }).count(), 0);
  await ctx.close();
});
test('G4 스낵바는 5초 뒤 저절로 닫힌다', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/dev/kit?s=feedback');
  await page.getByRole('button', { name: '스낵바 보기' }).click();
  const bar = page.getByRole('status').getByText('지웠어요');
  await bar.waitFor(); await page.waitForTimeout(4500);
  assert.equal(await bar.isVisible(), true);
  await bar.waitFor({ state: 'hidden', timeout: 1500 });
  await ctx.close();
});
test('G4 스낵바는 화면을 옮기면 닫힌다', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/dev/kit?s=feedback');
  await page.getByRole('button', { name: '스낵바 보기' }).click();
  await page.getByRole('status').getByText('지웠어요').waitFor();
  await page.goto(BASE + '/dev/kit?s=o6'); await page.waitForLoadState('networkidle');
  assert.equal(await page.getByText('지웠어요').count(), 0);
  await ctx.close();
});
test('G4 확인 창: Esc 는 취소, 확인은 동작', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/dev/kit?s=feedback');
  await page.getByRole('button', { name: '확인 창 보기' }).click();
  const dialog = page.getByRole('dialog', { name: '로그아웃할까요?' });
  await dialog.waitFor(); await page.keyboard.press('Escape');
  await dialog.waitFor({ state: 'hidden' });
  assert.equal(await page.getByText('확인함').count(), 0);
  await page.getByRole('button', { name: '확인 창 보기' }).click();
  await dialog.getByRole('button', { name: '로그아웃' }).click();
  await page.getByText('확인함').waitFor();
  await ctx.close();
});
test('G4 위험 배너는 alert 로 읽힌다', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/dev/kit?s=feedback');
  await page.getByRole('alert').getByText('처리하지 못한 자료가 있어요.').waitFor();
  await ctx.close();
});
```

- [ ] **Step 2: 실패 확인** — Run: `cd web && NEXT_PUBLIC_DEV_KIT=1 pnpm build && ... verify_ui_nav.cjs G4` / Expected: FAIL (버튼 없음)
- [ ] **Step 3: 구현** — 위 Interfaces 대로.
- [ ] **Step 4: 통과 확인** — Expected: G4 6개 PASS, 전체 25개 PASS
- [ ] **Step 5: 커밋** — `git commit -m "[output] 토스트·스낵바·확인 창·배너 공통 키트"`

---

### Task 7: 화면 글에서 중간점 없애기 (G4 메모)

**Files:**
- Create: `web/scripts/check-copy.mjs`, `web/tests/check-copy.test.mjs`
- Modify: `web/package.json` (`check` 에 `node scripts/check-copy.mjs` 추가), 그리고 검사기가 짚는 모든 파일(지금 약 40개 파일, `app/dev/**` 제외)

**Interfaces:**
- Produces: `findMiddots(source: string, fileName: string): { line: number; text: string }[]` (`check-copy.mjs` 에서 export). TypeScript 컴파일러 API(`typescript` devDependency)로 파일을 읽어 `StringLiteral`, `NoSubstitutionTemplateLiteral`, `TemplateHead/Middle/Tail`, `JsxText` 노드 중 `·`(U+00B7) 이 든 것만 돌려준다. 주석은 보지 않는다. 파일을 직접 실행했을 때만(`process.argv[1] === fileURLToPath(import.meta.url)`) CLI 로 동작해 `app`, `components`, `lib` 아래 `.ts`·`.tsx` 를 훑고(`app/dev/` 제외) 하나라도 있으면 `file:line: text` 를 찍고 `exit 1`.

- [ ] **Step 1: 단위 테스트 작성**

```js
import { test } from "node:test";
import assert from "node:assert/strict";
import { findMiddots } from "../scripts/check-copy.mjs";

test("화면 글의 중간점을 찾는다", () => {
  const src = `const a = "근거 · 1쪽";\nexport const C = () => <p>확인해 주세요 · 2</p>;\nconst t = \`출처 · \${x}\`;`;
  assert.deepEqual(findMiddots(src, "a.tsx").map((f) => f.line), [1, 2, 3]);
});
test("주석과 중간점 없는 글은 무시한다", () => {
  const src = `// 오늘 매장 · 카드 탭\n/* 근거 · 1쪽 */\nconst a = "정리 끝!";`;
  assert.deepEqual(findMiddots(src, "a.tsx"), []);
});
```

- [ ] **Step 2: 실패 확인** — Run: `cd web && pnpm test` / Expected: FAIL (`check-copy.mjs` 없음)
- [ ] **Step 3: 검사기 구현** — 위 Interfaces 대로. 통과 확인: `pnpm test` PASS. 그다음 `node scripts/check-copy.mjs` 는 남은 중간점 목록과 함께 FAIL 한다(정상).
- [ ] **Step 4: 목록을 하나씩 고친다.** 규칙:
  1. 개수(`확인해 주세요 · 2`, `음료 레시피 · 2`) → 글 + `<CountBadge n={2} />`.
  2. 나열(`.join(" · ")`, `HOT 샷 2 · 바닐라 시럽 2펌프`) → `, `.
  3. 메타 묶음(`10. 31. 오후 02:00 · 합류`, `근거 · 레시피 메모.jpg · 1쪽`, `출처 · 파일명`) → 따로 `<span>` 으로 두고 부모에 `flex flex-wrap gap-x-2`. 글 사이 기호는 쓰지 않는다.
  4. 낱말 묶음(`업종·메뉴`, `메뉴·위치·할 일로 찾기`, `초대 · 합류 승인`) → 쉼표(`메뉴, 위치, 할 일로 찾기`) 또는 '와/과'(`업종과 메뉴`).
  5. 상태 라벨(`지금 · 오픈`) → 두 요소로 나눠 앞은 작은 글(`지금`), 뒤는 굵게(`오픈`).
  6. `lib/api.ts`·`lib/ingest-submit.ts` 등의 오류 문구도 같은 규칙. 서버가 준 문구·데이터는 손대지 않는다.
- [ ] **Step 5: 통과 확인** — Run: `cd web && node scripts/check-copy.mjs && pnpm check` / Expected: 출력 없이 0 종료, check 통과. 그리고 `node ../api/scripts/verify_ui_nav.cjs` 전체 PASS(문구를 찾는 테스트가 깨지지 않았는지).
- [ ] **Step 6: 커밋** — `git commit -m "[output] 화면 글에서 중간점 없애고 검사기 추가"`

---

### Task 8: 서버가 새 주소를 직접 준다 (NAV-9)

**Files:**
- Create: `api/app/notifications/destinations.py`, `api/tests/test_notification_destinations.py`
- Modify: `api/app/notifications/service.py:102,127,348,366`, `api/app/ingest/router.py:405`, `api/app/learn/owner_delivery.py:78-79`, `api/app/learn/owner_publication.py:41-42`, `api/app/learn/owner_handoff.py:44`, `api/app/learn/router.py:192,798,1224`, `docs/dev/ASKBUDDY_MVP_CURRENT.md:558`(알림 주소 표)

**Interfaces:**
- Produces (`destinations.py`, 주석 한국어):

```python
OWNER_HOME = "/owner"
OWNER_QUESTIONS = "/owner/questions"
OWNER_MEMBERS = "/owner/members"
STAFF_HOME = "/staff"
STAFF_RECIPES = "/staff/recipes"
STAFF_ASK = "/staff/ask"

def owner_question(question_id: int) -> str: ...      # "/owner/questions/{id}"
def owner_job_cards(job_id: int) -> str: ...          # "/owner/cards?status=all&job_id={id}"
def staff_session(session_id: str | None) -> str: ... # "/staff/ask?session_id={quote(id)}", 없으면 STAFF_ASK
```

- 바꾸는 곳: 새 질문 알림 → `owner_question(question_id)`(v1·v2 구분 없음), 추출 완료 알림·작업 응답 `review_destination` → `owner_job_cards(job_id)`, 합류 요청 → `OWNER_MEMBERS`, 합류 승인 → `STAFF_HOME`, 점주 답 도착(delivery·publication) → v2 는 `staff_session(session_id)`, v1 은 `STAFF_ASK`, 지식 반영 중단 알림 → `OWNER_QUESTIONS`, `V2_REQUIRED` 오류 `details.destination` → `STAFF_ASK`, 학습 상세 `return_to.path` → `STAFF_RECIPES`.

- [ ] **Step 1: 테스트 작성** — `api/tests/test_notification_destinations.py`

```python
from pathlib import Path

from app.notifications import destinations as d

APP = Path(__file__).resolve().parents[1] / "app"
OLD = ("/owner/questions/v2", "/staff/chat", "/owner/cards/review", "/staff/roadmap", "/owner/upload", "/owner/dashboard")


def test_owner_question():
    assert d.owner_question(101) == "/owner/questions/101"


def test_owner_job_cards():
    assert d.owner_job_cards(7) == "/owner/cards?status=all&job_id=7"


def test_staff_session_quotes_and_falls_back():
    assert d.staff_session("a b/c") == "/staff/ask?session_id=a%20b%2Fc"
    assert d.staff_session(None) == "/staff/ask"
    assert d.staff_session("") == "/staff/ask"


def test_no_old_destination_left_in_app():
    hits = [
        f"{path.relative_to(APP)}:{no}"
        for path in APP.rglob("*.py")
        for no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if any(f'"{old}' in line or f"'{old}" in line for old in OLD)
    ]
    assert hits == []
```

- [ ] **Step 2: 실패 확인** — Run: `cd api && source .venv/bin/activate && pytest tests/test_notification_destinations.py -v` / Expected: FAIL (`destinations` 없음)
- [ ] **Step 3: 구현** — `destinations.py` 를 만들고 위 '바꾸는 곳' 을 상수·함수로 바꾼다. `MVP_CURRENT.md:558` 표의 주소를 `/owner/cards?status=all&job_id={job_id}` 로 고치고 같은 표에 새 질문·점주 답 도착 행이 있으면 새 주소로 맞춘다.
- [ ] **Step 4: 통과 확인** — Run: `pytest tests/test_notification_destinations.py -v` PASS, 그리고 `pytest -q` 전체(옛 주소를 기대하던 테스트가 있으면 새 주소로 고친다). 매장 격리 검사: `python3 .claude/skills/store-isolation-check/check_store_id.py api/app/notifications api/app/learn api/app/ingest` 통과.
- [ ] **Step 5: 브라우저 확인** — `ui_fixture.cjs` 의 알림 `destination` 을 새 주소로 바꾸고 테스트 추가:

```js
test('NAV-9 알림의 새 주소는 리다이렉트 없이 바로 열린다', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/notifications');
  await page.getByText('직원 질문이 왔어요').click(); await to(page, '/owner/questions/101');
  await ctx.close();
});
```

  Expected: PASS (지금은 알림 목록이 옛 `/owner/questions/v2?question_id=101` 을 주고, 그 주소를 누르면 화면이 안 바뀌는 문제가 있었다 — 2026-10-31 캡처 N4).
- [ ] **Step 6: 커밋** — `git commit -m "[output] 서버 알림 주소를 새 화면 주소로"`

---

## 실행 순서와 확인

Task 1 → 2 → 3 → 4 → 5 → 6 → 7 순서(뒤 Task 가 앞 Task 의 provider·키트를 쓴다). Task 8 은 서버만 건드리므로 Task 1 뒤 언제든 되지만 R 담당 파일 동시 편집을 피한다.

마지막 확인:
- `cd web && pnpm check` 통과(lint·typecheck·`node --test`·중간점 검사·build)
- `NODE_PATH=... node api/scripts/verify_ui_nav.cjs` 전체 PASS(26개), 기존 `verify_r_ui.cjs`·`verify_r_history_ui.cjs`·`verify_ui_rebrand.cjs` PASS(옛 탭·문구를 찾던 단언은 이 계획 결정대로 고친다)
- `cd api && pytest -q` 통과, 매장 격리 검사 통과
- `ui-state-walkthrough`·`web-async-state-check` 스킬로 이동·스낵바 lifecycle 확인
