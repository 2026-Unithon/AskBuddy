# 계획 8: 마이페이지와 설정(알림, 개인정보, 계정, 퇴사, 탈퇴)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** 지금의 '설정' 화면을 사장님과 알바생 모두의 **마이페이지**로 바꾸고, 그 안에 문의하기, 의견 보내기, **설정**을 둔다. 설정은 카드 목록처럼 굵은 밑줄 아래 줄을 놓는 세 구역(알림 설정, 개인정보 보호, 계정)과 빨간 칸(퇴사했어요, 회원 탈퇴)으로 만든다.

**Architecture:** 화면은 기존 `web/components/settings-screen.tsx`(마이페이지)와 새 `web/components/app-settings-screen.tsx`(설정)로 나눈다. 서버는 기존 라우터에 끝점을 더한다.
- `api/app/bootstrap`: 의견, 퇴사, 탈퇴
- `api/app/auth`: 로그인된 기기
- `api/app/ingest`: 올린 자료 목록

새 컬럼과 표는 가산 migration 하나(`20261110120000_settings_account.sql`)로 넣는다. 화면은 합성 API(`ui_fixture.cjs`)에 같은 계약을 더해 새 묶음 `verify_ui_plan8.cjs`로 확인한다.
- 순수 규칙: `web/tests/*.test.mjs`
- 서버: pytest
- SQL: 일회용 pg17

**Spec:** 아래 '사용자 결정' 표(2026-11-10 대화)와 MVP 정본.

## 사용자 결정 (2026-11-10)

| # | 결정 |
|---|---|
| 1 | '설정' 화면 이름을 **마이페이지**로(사장님, 알바생 둘 다). 아래 목록 끝에 **문의하기**, **의견 보내기**, **설정** 순서로 둔다 |
| 2 | 설정 화면은 카드 목록 구역 모양(굵은 제목 + `border-b-2 border-ink` 밑줄, 아래 줄). 토글이나 링크 |
| 3 | 알림 설정: **이 기기 푸시 알림 받기** 하나. 폰이 막고 있으면 그 이유와 켜는 법을 토글 아래 한 줄로 |
| 4 | 개인정보 보호: 매장 지식 내려받기, 올린 자료 관리, 로그인된 기기, 개인정보 처리방침, 이용약관 |
| 5 | 계정: 로그인 방식, 초대 링크 만들기, 앱 버전, 로그아웃. 영업일 시작 시각은 근무조 화면에 그대로 둔다 |
| 6 | 빨간 칸: **퇴사했어요**(알바생만), **회원 탈퇴**. 누르면 'O하시겠습니까?' → 예 → '퇴사하겠습니다'/'탈퇴하겠습니다'를 그대로 입력해야 버튼이 켜진다 |
| 7 | 알바생 탈퇴: 바로 계정 삭제. 질문 기록은 이름 없이 남는다 |
| 8 | 사장님 탈퇴: **30일 유예**. 그 순간 사장님과 알바생 모두 매장에 못 들어온다. 30일 안에 사장님이 카카오로 다시 로그인해 취소하면 다시 열린다. 30일이 지나면 파기 |
| 9 | 문의하기, 의견 보내기: 앱 안 입력창 → **서버에 저장**. 운영자가 DB에서 본다 |
| 10 | 개인정보 처리방침, 이용약관: 레퍼런스를 찾아 법률 검토 후 초안 작성, 다시 한 번 검토 |

## 아직 사용자에게 받아야 하는 것 (Task 9 가 막힌다)

- 운영 주체: 상호(또는 개인 이름), 대표자, 사업자등록번호(있으면), 주소, 연락처(이메일)
- 개인정보 보호책임자: 이름(또는 직책)과 연락처
- Supabase 프로젝트 리전, AWS EC2 리전(`vars.AWS_REGION`), Vercel 함수 리전. 처리방침 국외 이전 표에 국가를 적어야 한다
- 시행일

받기 전까지 초안의 해당 칸은 `【채워야 함: …】`으로 두고, 화면 페이지는 그 표시가 남아 있으면 빌드 검사(Task 9 Step 6)에서 실패한다.

## 파기 방식 (사용자 결정 2026-11-10: B안)

30일이 지나면 그 매장의 모든 행과 Storage 파일을 지운다. 남는 것은 원가 장부(`ai_usage_attempts`, `cost_assessments`)와 비운 `stores` 행뿐이다. 처리방침에도 이렇게 적는다.

파기 자체는 **계획 9**(`docs/dev/plan/DB_CLEANUP_PURGE_PLAN9_20261110.md`)의 Task 5~7이 만든다. 이 계획은 그것을 쓴다. **계획 9의 Task 5~7이 끝난 뒤에 Task 7을 시작한다.**

| 계획 9가 주는 것 | 이 계획이 쓰는 곳 |
|---|---|
| 칸 `stores.closing_at`, `stores.purge_due_at`, `stores.deleted_at`, `users.deleted_at` | Task 7 |
| `Settings.withdrawal_grace_days`(30) | Task 7 `withdraw_owner` |
| `purge.purge_due_stores(pool) -> list[int]` | Task 7 `withdrawal_loop` |
| `purge.PURGE_ORDER`와 분류 검사(`test_every_table_is_classified`) | Task 1: 새 표 `user_feedback`을 목록에 넣어야 검사가 통과한다 |
| `storage.delete_objects(bucket, paths)` | Task 7 알바생 탈퇴의 사진 삭제 |

탈퇴 기한은 `stores.purge_due_at` 한 곳에만 둔다. `users.withdrawal_due_at`은 만들지 않는다(계획 9 R3).

## Global Constraints

- 매장 격리: 모든 새 쿼리는 `store_id` 필수, JWT의 store_id. 사용자 단위 쿼리(기기, 탈퇴)는 `# store-isolation-ok: <사유>`. `check_store_id.py` 위반 수가 변경 전(ingest 15건)과 같아야 한다.
- migration은 가산만, `supabase/migrations/20261110120000_settings_account.sql` 하나. 계획 9의 migration 네 개 뒤에 온다. `verify_r_schema_rebuild.py` 통과.
- 30일은 `config.py`의 `withdrawal_grace_days`에서만 읽는다. 코드나 SQL에 30을 적지 않는다.
- 확인 문구는 정확히 '퇴사하겠습니다', '탈퇴하겠습니다'(앞뒤 공백만 무시). 서버도 같은 문구를 받아야 처리한다(화면 우회 방지).
- 화면 글: 중간점 금지, 회색 설명 추가 금지, % 금지, `eslint-disable` 금지. 붙잡는 문구(다크패턴) 금지.
- 브라우저는 DB, Storage에 직접 가지 않는다(불변식 1, 7). 내려받기는 API 응답을 blob으로 받아 저장한다.
- 실데이터, 운영 DB, 배포판을 건드리지 않는다. 커밋하지 않는다.

## Review Focus

1. 탈퇴 대기 중인 매장의 알바생이 이미 받아 둔 access token으로 계속 쓰면 안 된다. `get_store_id`가 매 요청마다 막아야 한다.
2. 알바생이 탈퇴한 뒤 같은 카카오로 다시 들어오면 **새 계정**이어야 한다. 옛 기록과 이어지면 안 된다.
3. 사장님이 30일 안에 다시 로그인하면 취소 화면이 먼저 나와야 한다. 매장 화면이 바로 열리면 취소 없이 쓰는 꼴이 된다.
4. 로그인된 기기에서 남의 `family_id`를 끊을 수 없어야 한다(404).
5. 아이폰 Safari 탭에서 토글을 켜면 아무 일도 안 일어나는 대신 '홈 화면에 추가' 안내가 나와야 한다.

---

## 파일 구조

| 파일 | 책임 |
|---|---|
| `supabase/migrations/20261110120000_settings_account.sql` | `auth_refresh_tokens.user_agent`, `user_feedback` (탈퇴 칸은 계획 9의 `20261110110000_store_purge.sql`) |
| `api/app/bootstrap/purge.py` | `PURGE_ORDER`에 `user_feedback` 추가 |
| `api/app/bootstrap/account.py` (새) | 퇴사, 탈퇴, 취소 순수 DB 함수. 파기는 계획 9의 `purge.py` |
| `api/app/bootstrap/account_router.py` (새) | `/app/me/leave-store`, `/app/me/withdraw`, `/app/me/withdrawal`, `/app/me/withdrawal/cancel`, `/app/feedback` |
| `api/app/bootstrap/withdrawal_loop.py` (새) | 한 시간마다 `purge.purge_due_stores`를 부른다 |
| `api/app/auth/devices.py` (새) | `device_label(ua)`, 기기 목록, 기기 끊기 |
| `api/app/auth/session.py` | `issue_refresh(..., user_agent)` |
| `api/app/deps.py` | `get_store_id`가 닫힌 매장을 막는다 |
| `api/app/ingest/router.py` | `GET /ingest/sources` |
| `web/components/settings-screen.tsx` | 마이페이지(제목, 행 추가, 로그아웃 빼기) |
| `web/components/app-settings-screen.tsx` (새) | 설정 화면 |
| `web/components/settings/*.tsx` (새) | `SettingsSection`, `PushToggleRow`, `TypedConfirm`, `FeedbackSheet` |
| `web/lib/push-state.ts` (새) | 푸시 상태 판정 순수 함수 |
| `web/app/{owner,staff}/settings/app/...` (새) | 설정, 로그인된 기기, (사장님) 올린 자료 |
| `web/app/withdrawal/page.tsx` (새) | 탈퇴 대기 안내와 취소 |
| `web/app/privacy/page.tsx`, `web/app/terms/page.tsx` (새) | 로그인 없이 읽는 문서 |
| `docs/dev/legal/PRIVACY_POLICY_DRAFT.md`, `TERMS_DRAFT.md` (새) | 초안 정본 |

---

### Task 1: migration

**Files:** Create `supabase/migrations/20261110120000_settings_account.sql`, Test `api/tests/test_plan8_account_db.py`. Modify `api/app/bootstrap/purge.py`(`PURGE_ORDER` 맨 앞에 `"user_feedback"`).

**Interfaces — Consumes:** 계획 9의 `purge.PURGE_ORDER`. 새 표를 넣지 않으면 `tests/test_plan9_purge_db.py::PurgeCatalogTest::test_every_table_is_classified`가 실패한다(매장을 파기해도 의견 글이 남는 것을 막는 검사).

- [ ] **Step 1: 실패하는 테스트**

```python
"""계획 8: 설정, 계정. 실제 스키마. PLAN7_TEST_DB_URL 이 없으면 건너뛴다."""
import unittest
from tests._plan7_db import ENABLED, SKIP_REASON, drop_db, fresh_db, seed_store


@unittest.skipUnless(ENABLED, SKIP_REASON)
class SchemaTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.conn, self.name = await fresh_db()

    async def asyncTearDown(self):
        await drop_db(self.conn, self.name)

    async def test_columns_exist(self):
        cols = {(r["table_name"], r["column_name"]) for r in await self.conn.fetch(
            "select table_name, column_name from information_schema.columns where table_schema = 'public'")}
        for pair in [("auth_refresh_tokens", "user_agent"), ("user_feedback", "body")]:
            self.assertIn(pair, cols)
        # 기한은 stores.purge_due_at 한 곳에만 둔다(계획 9 R3)
        self.assertNotIn(("users", "withdrawal_due_at"), cols)

    async def test_feedback_is_in_the_purge_list(self):
        from app.bootstrap import purge
        self.assertIn("user_feedback", purge.PURGE_ORDER)

    async def test_feedback_checks(self):
        store = await seed_store(self.conn)
        user = await self.conn.fetchval("insert into users (name, role) values ('알바', 'STAFF') returning user_id")
        with self.assertRaises(Exception):
            await self.conn.execute("insert into user_feedback (store_id, user_id, kind, body) values ($1, $2, 'BUG', 'x')", store, user)
        with self.assertRaises(Exception):
            await self.conn.execute("insert into user_feedback (store_id, user_id, kind, body) values ($1, $2, 'IDEA', '')", store, user)
```

- [ ] **Step 2:** `docker exec plan7-pg psql -U postgres -c "drop database if exists plan7_template"` 후 `PLAN7_TEST_DB_URL=… python -m pytest tests/test_plan8_account_db.py -q`. Expected: FAIL(`user_agent` 없음)
- [ ] **Step 3: migration**

```sql
-- 계획 8(2026-11-10): 로그인된 기기, 의견, 퇴사, 탈퇴
alter table auth_refresh_tokens add column if not exists user_agent varchar(300);

create table if not exists user_feedback (
  feedback_id bigint generated always as identity primary key,
  store_id    bigint references stores(store_id) on delete cascade,
  user_id     bigint references users(user_id) on delete set null,
  kind        varchar(10) not null check (kind in ('INQUIRY','IDEA')),
  body        text not null check (char_length(btrim(body)) between 1 and 2000),
  created_at  timestamptz not null default now()
);
create index if not exists user_feedback_created on user_feedback (created_at desc);
```

- [ ] **Step 4:** `purge.PURGE_ORDER` 맨 앞에 `"user_feedback"`을 넣는다(다른 표가 가리키지 않아 순서 제약이 없다).
- [ ] **Step 5:** template 지우고 `python -m pytest tests/test_plan8_account_db.py tests/test_plan9_purge_db.py -q`. Expected: 모두 통과(계획 8 쪽 3 passed). `python scripts/verify_r_schema_rebuild.py`. Expected: exit 0.

### Task 2: 마이페이지와 설정 화면 골격

**Files:** Modify `web/components/settings-screen.tsx`. Create `web/components/app-settings-screen.tsx`, `web/components/settings/settings-section.tsx`, `web/app/owner/settings/app/page.tsx`, `web/app/staff/settings/app/page.tsx`. Modify `web/next.config.ts`(`NEXT_PUBLIC_APP_VERSION` ← package.json version), `api/scripts/ui_fixture.cjs`. Create `api/scripts/verify_ui_plan8.cjs`, `.superpowers/sdd/UI_REDESIGN_PLAN8_MYPAGE_SETTINGS_20261110/run-ui.sh`(plan7 것을 복사해 마지막 묶음만 `verify_ui_plan8.cjs`로).

**Interfaces — Produces:**
- `SettingsSection({ title: string, tone?: "danger", children })` → `<section aria-labelledby>` + `<h2 class="border-b-2 border-ink pb-1.5 text-[17px] font-bold">`. `tone="danger"`이면 제목 대신 `rounded-[20px] border-2 border-danger-500` 상자.
- `SettingsLink({ title, href?, onClick?, value?, danger? })` → 한 줄(최소 높이 56, 오른쪽 `›` 또는 `value` 글자).

- [ ] **Step 1: 실패하는 브라우저 테스트** (`verify_ui_plan8.cjs`, 헤더는 plan7과 같음)

```js
test('MY-1 사장님 마이페이지 제목과 목록 끝 세 줄', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/settings');
  await page.getByRole('heading', { name: '마이페이지' }).waitFor();
  const rows = await page.locator('main li').allTextContents();
  assert.deepEqual(rows.slice(-3).map((t) => t.replace(/[›\d]/g, '').trim()), ['문의하기', '의견 보내기', '설정']);
  assert.equal(await page.getByRole('button', { name: '로그아웃' }).count(), 0);
  await ctx.close();
});
test('MY-2 알바생 마이페이지도 같은 세 줄', async (b) => {
  const { page, ctx } = await open(b, 'STAFF', '/staff/settings');
  await page.getByRole('heading', { name: '마이페이지' }).waitFor();
  await page.getByRole('link', { name: '설정' }).click(); await to(page, '/staff/settings/app');
  await ctx.close();
});
test('SET-1 사장님 설정 구역과 줄', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/settings/app');
  await page.getByRole('heading', { name: '설정', level: 1 }).waitFor();
  const h2 = await page.locator('main h2').allTextContents();
  assert.deepEqual(h2, ['알림 설정', '개인정보 보호', '계정']);
  for (const name of ['매장 지식 내려받기', '올린 자료 관리', '로그인된 기기', '개인정보 처리방침', '이용약관', '초대 링크 만들기', '로그아웃', '회원 탈퇴'])
    await page.getByRole('main').getByText(name, { exact: true }).waitFor();
  await page.getByText('카카오', { exact: true }).waitFor();
  await page.getByText(/^v\d+\.\d+\.\d+$/).waitFor();
  assert.equal(await page.getByText('퇴사했어요').count(), 0);
  await ctx.close();
});
test('SET-2 알바생 설정에는 사장님 줄이 없고 퇴사가 있다', async (b) => {
  const { page, ctx } = await open(b, 'STAFF', '/staff/settings/app');
  await page.getByText('퇴사했어요').waitFor();
  for (const name of ['매장 지식 내려받기', '올린 자료 관리', '초대 링크 만들기']) assert.equal(await page.getByText(name).count(), 0, name);
  await ctx.close();
});
test('SET-3 빨간 칸은 마지막 구역이고 테두리가 위험 색', async (b) => {
  const { page, ctx } = await open(b, 'STAFF', '/staff/settings/app');
  const box = page.locator('[data-danger-zone]');
  assert.match(await box.textContent(), /퇴사했어요.*회원 탈퇴/);
  assert.equal(await page.locator('main section').last().getAttribute('data-danger-zone'), '');
  await ctx.close();
});
test('SET-4 로그아웃은 설정에서 확인 창을 거친다', async (b) => {
  const { page, ctx, api } = await open(b, 'OWNER', '/owner/settings/app');
  await page.getByRole('button', { name: '로그아웃' }).click();
  await page.getByRole('dialog', { name: '로그아웃할까요?' }).getByRole('button', { name: '로그아웃' }).click();
  for (let i = 0; i < 40 && !api.calls.some((c) => c.path === '/auth/logout'); i++) await page.waitForTimeout(50);
  assert.ok(api.calls.some((c) => c.path === '/auth/logout'));
  await ctx.close();
});
```

- [ ] **Step 2:** `bash .superpowers/sdd/UI_REDESIGN_PLAN8_MYPAGE_SETTINGS_20261110/run-ui.sh MY`. Expected: FAIL(제목 '설정')
- [ ] **Step 3:** 구현
  - 마이페이지: `PageHeader title="마이페이지"`. 행 끝에 `{문의하기}`, `{의견 보내기}`(Task 6에서 시트 연결, 이 Task에선 `onClick` 없는 자리), `{설정 → /{role}/settings/app}`. 로그아웃 블록과 ConfirmDialog는 설정으로 옮긴다.
  - 설정 화면: 위 구역, 줄 순서는 사용자 결정 4, 5, 6. '로그인 방식' 값은 `카카오`(bootstrap에 공급자가 없으므로 고정 글자, 이메일 로그인 계정은 없음. 현행 로그인은 카카오 하나). '앱 버전' 값은 `v${process.env.NEXT_PUBLIC_APP_VERSION}`.
  - `next.config.ts`: `env: { NEXT_PUBLIC_APP_VERSION: pkg.version }`.
- [ ] **Step 4:** 같은 명령. Expected: MY-1, 2, SET-1~4 PASS. 마이페이지로 이름이 바뀐 탓에 깨지는 옛 테스트(`verify_ui_nav`, `verify_ui_manage`, `verify_ui_staff`에서 '설정' 제목, 로그아웃 위치를 보는 것)는 새 위치로 고친다. 전체 `run-ui.sh` 통과.

### Task 3: 이 기기 푸시 알림 받기

**Files:** Create `web/lib/push-state.ts`, `web/tests/push-state.test.mjs`, `web/components/settings/push-toggle-row.tsx`. Modify `web/lib/push.ts`, `web/lib/api.ts`(`deleteMyPushSubscription(id, token)` → `DELETE /notifications/my-subscriptions/{id}`).

**Interfaces — Produces:**
- `pushState(env: { hasPushApi: boolean; ios: boolean; standalone: boolean; permission: "default"|"granted"|"denied"; subscribed: boolean; configured: boolean }): "IOS_NEEDS_HOME" | "UNSUPPORTED" | "NOT_CONFIGURED" | "DENIED" | "ON" | "OFF"`
- `turnPushOn(role, token): Promise<"ON"|"DENIED"|"UNSUPPORTED"|"NOT_CONFIGURED">`. 사장님은 `/notifications/subscriptions`, 알바생은 `/notifications/my-subscriptions`로 저장한다. 지금 두 화면이 쓰는 계약 그대로.
- `turnPushOff(role, token): Promise<void>`. 현재 구독을 같은 끝점에 저장해 id를 받은 뒤(서버가 endpoint로 upsert), 그 id를 DELETE하고 브라우저 구독을 해제한다.

- [ ] **Step 1: 실패하는 단위 테스트**

```js
import assert from "node:assert/strict";
import { test } from "node:test";
import { pushState } from "../lib/push-state.ts";
const base = { hasPushApi: true, ios: false, standalone: false, permission: "default", subscribed: false, configured: true };
test("아이폰 Safari 탭은 홈 화면에 추가해야 한다", () => {
  assert.equal(pushState({ ...base, ios: true, hasPushApi: false }), "IOS_NEEDS_HOME");
  assert.equal(pushState({ ...base, ios: true, hasPushApi: true, standalone: false }), "IOS_NEEDS_HOME");
});
test("홈 화면 앱이면 아이폰도 켤 수 있다", () => assert.equal(pushState({ ...base, ios: true, standalone: true }), "OFF"));
test("푸시 API 가 없으면 안 된다", () => assert.equal(pushState({ ...base, hasPushApi: false }), "UNSUPPORTED"));
test("서버 키가 없으면 준비 안 됨", () => assert.equal(pushState({ ...base, configured: false }), "NOT_CONFIGURED"));
test("거절했으면 폰 설정", () => assert.equal(pushState({ ...base, permission: "denied" }), "DENIED"));
test("허락하고 구독 중이면 켜짐", () => assert.equal(pushState({ ...base, permission: "granted", subscribed: true }), "ON"));
test("허락만 하고 구독이 없으면 꺼짐", () => assert.equal(pushState({ ...base, permission: "granted" }), "OFF"));
```

- [ ] **Step 2:** `cd web && node --test tests/push-state.test.mjs`. Expected: FAIL(모듈 없음)
- [ ] **Step 3:** `pushState` 구현(위 순서대로 판정: ios&&!standalone → IOS_NEEDS_HOME, !hasPushApi → UNSUPPORTED, !configured → NOT_CONFIGURED, denied → DENIED, granted&&subscribed → ON, 그 외 OFF).
- [ ] **Step 4:** Expected: 7 passed
- [ ] **Step 5: 화면 테스트** (`verify_ui_plan8.cjs`). fixture에 `pushEnv` 덮어쓰기(브라우저 `Notification.permission`, `PushManager` 흉내를 `addInitScript`로) 추가.

```js
test('PUSH-1 아이폰 Safari 탭이면 홈 화면 안내', async (b) => {
  const { page, ctx } = await open(b, 'STAFF', '/staff/settings/app', { overrides: { pushEnv: { ios: true, standalone: false } } });
  await page.getByText('홈 화면에 추가해야 받을 수 있어요').waitFor();
  await page.getByRole('button', { name: '추가하는 법' }).click();
  await page.getByRole('dialog', { name: '홈 화면에 추가하기' }).waitFor();
  assert.equal(await page.getByRole('switch', { name: '이 기기 푸시 알림 받기' }).isDisabled(), true);
  await ctx.close();
});
test('PUSH-2 폰에서 막았으면 폰 설정 안내', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/settings/app', { overrides: { pushEnv: { permission: 'denied' } } });
  await page.getByText('휴대폰 설정에서 알림이 꺼져 있어요').waitFor();
  await page.getByRole('button', { name: '켜는 법' }).click();
  await page.getByRole('dialog', { name: '알림 켜는 법' }).waitFor();
  await ctx.close();
});
test('PUSH-3 켜면 구독을 저장하고 끄면 지운다', async (b) => {
  const { page, ctx, api } = await open(b, 'STAFF', '/staff/settings/app', { overrides: { pushEnv: { permission: 'granted' } } });
  const sw = page.getByRole('switch', { name: '이 기기 푸시 알림 받기' });
  await sw.click();
  await page.waitForFunction(() => document.querySelector('[role=switch]')?.getAttribute('aria-checked') === 'true');
  assert.ok(api.calls.some((c) => c.method === 'POST' && c.path === '/notifications/my-subscriptions'));
  await sw.click();
  await page.waitForFunction(() => document.querySelector('[role=switch]')?.getAttribute('aria-checked') === 'false');
  assert.ok(api.calls.some((c) => c.method === 'DELETE' && c.path.startsWith('/notifications/my-subscriptions/')));
  await ctx.close();
});
```

- [ ] **Step 6:** 화면 구현. 안내 문구는 정확히:
  - IOS_NEEDS_HOME: '홈 화면에 추가해야 받을 수 있어요' + '추가하는 법'(시트 '홈 화면에 추가하기': 1. Safari 아래 공유 버튼 2. 홈 화면에 추가 3. 홈 화면의 AskBuddy로 열고 여기서 켜기)
  - DENIED: '휴대폰 설정에서 알림이 꺼져 있어요' + '켜는 법'(시트 '알림 켜는 법': 아이폰은 설정 > 알림 > AskBuddy, 안드로이드는 Chrome 주소창 왼쪽 자물쇠 > 권한 > 알림)
  - UNSUPPORTED: '이 브라우저는 알림을 받을 수 없어요'. NOT_CONFIGURED: 토글 비활성, 글 없음.
  - 토글을 바꾸는 동안 비활성. 실패하면 ErrorInline.
- [ ] **Step 7:** `run-ui.sh PUSH`. Expected: PUSH-1~3 PASS

### Task 4: 매장 지식 내려받기, 초대 링크, 문서 링크

**Files:** Modify `web/components/app-settings-screen.tsx`, `web/lib/api.ts`(`downloadKnowledge(token): Promise<Blob>` → `GET /learn/v2/knowledge/export`).

- [ ] **Step 1: 실패하는 테스트**

```js
test('EXP-1 매장 지식 내려받기는 파일을 저장한다', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/settings/app');
  const [download] = await Promise.all([page.waitForEvent('download'), page.getByRole('button', { name: '매장 지식 내려받기' }).click()]);
  assert.match(download.suggestedFilename(), /^askbuddy-knowledge-\d{8}\.json$/);
  await ctx.close();
});
test('EXP-2 초대 링크 만들기는 초대 화면으로', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/settings/app');
  await page.getByRole('link', { name: '초대 링크 만들기' }).click(); await to(page, '/owner/invite');
  await ctx.close();
});
test('DOC-1 처리방침과 약관은 로그인 없이 열린다', async (b) => {
  const ctx = await b.newContext(); const page = await ctx.newPage();
  for (const [path, title] of [['/privacy', '개인정보 처리방침'], ['/terms', '이용약관']]) {
    await page.goto(`http://127.0.0.1:3011${path}`);
    await page.getByRole('heading', { name: title, level: 1 }).waitFor();
  }
  await ctx.close();
});
```

- [ ] **Step 2:** FAIL 확인. **Step 3:** 구현. 내려받기는 blob → `URL.createObjectURL` → `<a download>` 클릭 → revoke. 파일 이름은 KST 날짜(`askbuddy-knowledge-YYYYMMDD.json`). 실패하면 toast. `/privacy`, `/terms`는 Task 9 전까지 제목만 있는 페이지로 둔다. **Step 4:** PASS

### Task 5: 올린 자료 관리 (사장님)

**Files:** Modify `api/app/ingest/router.py`, `api/app/ingest/repository.py`(`list_sources(conn, store_id, *, cursor, limit)`). Test `api/tests/test_plan8_sources_list.py`. Create `web/app/owner/settings/app/sources/page.tsx`. Modify `web/lib/api.ts`, `web/lib/query.ts`(`queryKeys.sources(storeId)`).

**Interfaces — Produces:** `GET /ingest/sources?cursor=&limit=30` → `{ items: [{ source_id, title, source_type, file_size, created_at }], next_cursor }`. 조건은 `store_id = $1 and deleted_at is null`, 순서는 `source_id desc`. 사장님만.

- [ ] **Step 1: 실패하는 테스트**(실제 스키마)

```python
@unittest.skipUnless(ENABLED, SKIP_REASON)
class SourceListTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.conn, self.name = await fresh_db()
        self.store = await seed_store(self.conn); self.other = await seed_store(self.conn)
        self.user = await self.conn.fetchval("insert into users (name, role) values ('사장', 'OWNER') returning user_id")
        ins = "insert into sources (store_id, uploaded_by, source_type, title) values ($1, $2, 'SCAN', $3) returning source_id"
        self.a = await self.conn.fetchval(ins, self.store, self.user, "레시피북")
        self.b = await self.conn.fetchval(ins, self.store, self.user, "지운 자료")
        await self.conn.execute("update sources set deleted_at = now() where source_id = $1", self.b)
        await self.conn.fetchval(ins, self.other, self.user, "남의 자료")

    async def asyncTearDown(self):
        await drop_db(self.conn, self.name)

    async def test_lists_only_my_live_sources(self):
        from app.ingest import repository
        rows = await repository.list_sources(self.conn, self.store, cursor=None, limit=30)
        self.assertEqual([r["title"] for r in rows], ["레시피북"])
```

- [ ] **Step 2:** FAIL. **Step 3:** 구현 후 PASS. `check_store_id.py api/app/ingest` 위반 수 15 그대로.
- [ ] **Step 4: 화면 테스트**

```js
test('SRC-1 올린 자료를 보고, 지우기 전에 묻는다', async (b) => {
  const { page, ctx, api } = await open(b, 'OWNER', '/owner/settings/app/sources');
  await page.getByText('레시피북.pdf').waitFor();
  await page.getByRole('button', { name: '레시피북.pdf 지우기' }).click();
  const dialog = page.getByRole('dialog', { name: '이 자료를 지울까요?' });
  await dialog.getByRole('button', { name: '지우기' }).click();
  await page.getByText('레시피북.pdf').waitFor({ state: 'detached' });
  assert.ok(api.calls.some((c) => c.method === 'DELETE' && c.path.startsWith('/ingest/sources/')));
  await ctx.close();
});
```

확인 창 설명은 '원본 파일은 지워지고, 만든 카드는 남아요.'(D20 그대로). fixture에 `GET /ingest/sources`와 `DELETE /ingest/sources/:id`를 더한다. PASS 확인.

### Task 6: 문의하기, 의견 보내기

**Files:** Create `api/app/bootstrap/account_router.py`(이 Task에선 `/app/feedback`만), Test `api/tests/test_plan8_feedback.py`, Create `web/components/settings/feedback-sheet.tsx`. Modify `web/components/settings-screen.tsx`, `api/app/main.py`(라우터 등록).

**Interfaces — Produces:** `POST /app/feedback { kind: "INQUIRY"|"IDEA", body: str(1..2000) }` → 201 `{ feedback_id }`. store_id, user_id는 JWT에서 가져온다.

- [ ] **Step 1: 실패하는 테스트**

```python
@unittest.skipUnless(ENABLED, SKIP_REASON)
class FeedbackTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.conn, self.name = await fresh_db(); self.store = await seed_store(self.conn)
        self.user = await self.conn.fetchval("insert into users (name, role) values ('알바', 'STAFF') returning user_id")
    async def asyncTearDown(self):
        await drop_db(self.conn, self.name)
    async def test_saves_trimmed_body_with_store(self):
        from app.bootstrap import account
        fid = await account.save_feedback(self.conn, store_id=self.store, user_id=self.user, kind="IDEA", body="  다크 모드  ")
        row = await self.conn.fetchrow("select store_id, kind, body from user_feedback where feedback_id = $1", fid)
        self.assertEqual(dict(row), {"store_id": self.store, "kind": "IDEA", "body": "다크 모드"})
    async def test_rejects_blank(self):
        from app.bootstrap import account
        with self.assertRaises(ValueError):
            await account.save_feedback(self.conn, store_id=self.store, user_id=self.user, kind="INQUIRY", body="   ")
```

- [ ] **Step 2:** FAIL. **Step 3:** 구현(`ValueError` → 라우터에서 400 `FEEDBACK_EMPTY`). PASS.
- [ ] **Step 4: 화면 테스트**

```js
test('FB-1 문의하기 시트에서 보내면 저장되고 닫힌다', async (b) => {
  const { page, ctx, api } = await open(b, 'STAFF', '/staff/settings');
  await page.getByRole('button', { name: '문의하기' }).click();
  const sheet = page.getByRole('dialog', { name: '문의하기' });
  assert.equal(await sheet.getByRole('button', { name: '보내기' }).isDisabled(), true);
  await sheet.getByRole('textbox').fill('사진이 안 올라가요');
  await sheet.getByRole('button', { name: '보내기' }).click();
  await page.getByRole('status').getByText('보냈어요').waitFor();
  assert.deepEqual(api.calls.find((c) => c.path === '/app/feedback').body, { kind: 'INQUIRY', body: '사진이 안 올라가요' });
  await ctx.close();
});
test('FB-2 보내기 실패면 쓴 글이 남는다', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/settings', { overrides: { failFeedback: true } });
  await page.getByRole('button', { name: '의견 보내기' }).click();
  const sheet = page.getByRole('dialog', { name: '의견 보내기' });
  await sheet.getByRole('textbox').fill('다크 모드');
  await sheet.getByRole('button', { name: '보내기' }).click();
  await sheet.getByRole('alert').waitFor();
  assert.equal(await sheet.getByRole('textbox').inputValue(), '다크 모드');
  await ctx.close();
});
```

입력창은 `maxLength=2000`, 글자 수 표시 없음. PASS 확인.

### Task 7: 퇴사, 회원 탈퇴 (서버)

**선행:** 계획 9 Task 5~7.

**Files:** Create `api/app/bootstrap/account.py`, `api/app/bootstrap/withdrawal_loop.py`. Modify `api/app/bootstrap/account_router.py`, `api/app/deps.py`, `api/app/auth/kakao_accounts.py`, `api/app/bootstrap/router.py`(bootstrap 응답에 `withdrawal_due_at`. 값은 그 사장님 매장의 `stores.purge_due_at`), `api/app/main.py`(loop 등록). Test `api/tests/test_plan8_account_db.py`(추가), `api/tests/test_plan8_account_routes.py`.

**Interfaces — Consumes(계획 9):** `stores.closing_at/purge_due_at/deleted_at`, `users.deleted_at`, `get_settings().withdrawal_grace_days`, `purge.purge_due_stores(pool) -> list[int]`, `storage.delete_objects(bucket, paths)`, `storage.split_object_path(file_url)`.

**Interfaces — Produces:**
- `CONFIRM_LEAVE = "퇴사하겠습니다"`, `CONFIRM_WITHDRAW = "탈퇴하겠습니다"`
- `leave_store(conn, *, store_id, user_id)`: STAFF만. `store_members.removed_at = now(), removed_by = user_id`. 그다음 `revoke_user_sessions`.
- `withdraw_staff(conn, *, user_id)`: 모든 활성 membership `removed_at`, `user_identities` 행 삭제, `push_subscriptions`(user_id cascade 표) 중 그 사용자 행 삭제, 세션 폐기, `users`를 `name='탈퇴한 사용자', phone=null, email=null, password_hash=null, avatar_path=null, deleted_at=now()`로. avatar Storage 객체 삭제는 커밋 뒤 best-effort, 실패는 로그.
- `withdraw_owner(conn, *, store_id, user_id, now)`: `stores.closing_at = now, purge_due_at = now + timedelta(days=get_settings().withdrawal_grace_days)`(조건 `store_id = $1 and owner_id = $2`). 그 매장 모든 멤버의 세션 폐기. 사용자 행은 건드리지 않는다.
- `withdrawal_due(conn, *, user_id) -> datetime | None`: `select purge_due_at from stores where owner_id = $1 and closing_at is not null and deleted_at is null`. `# store-isolation-ok: 로그인한 사장님 자신의 매장을 owner_id 로 찾는다`
- `cancel_withdrawal(conn, *, user_id, now)`: `purge_due_at > now`일 때만 `closing_at = null, purge_due_at = null`. 지났으면 `WithdrawalExpired`.
- 파기는 이 파일에 두지 않는다. `withdrawal_loop(pool)`가 한 시간마다 `purge.purge_due_stores(pool)`를 부른다.
- `get_store_id`: 멤버 조회에 `join stores s using (store_id)`를 더하고 `s.closing_at is null and s.deleted_at is null`을 건다.
  - 사장님이 닫힌 매장이면 `ApiError(403, "OWNER_WITHDRAWING")`
  - 그 밖이면 `ApiError(403, "STORE_CLOSED")`
- 라우트:
  - `POST /app/me/leave-store { confirm }` → 204
  - `POST /app/me/withdraw { confirm }` → 204
  - `GET /app/me/withdrawal` → `{ due_at | null }` (CurrentUserId만)
  - `POST /app/me/withdrawal/cancel` → 204
  - confirm이 문구와 다르면 400 `CONFIRM_MISMATCH`. 사장님이 퇴사하려 하면 403 `OWNER_CANNOT_LEAVE`
- 카카오 로그인: 사용자가 `deleted_at`이면 그 identity는 이미 지워져 새 계정이 만들어진다. 사장님의 `withdrawal_due()`가 미래이면 로그인은 되고 `next=/withdrawal`로 보낸다. 파기가 끝난 뒤에는 사용자 행 자체가 없어 새 계정이 된다.

- [ ] **Step 1: 실패하는 DB 테스트**

```python
from datetime import datetime, timedelta, timezone
NOW = datetime(2026, 11, 10, 3, 0, tzinfo=timezone.utc)

@unittest.skipUnless(ENABLED, SKIP_REASON)
class AccountTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.conn, self.name = await fresh_db(); self.store = await seed_store(self.conn)
        q = "insert into users (name, role) values ($1, $2) returning user_id"
        self.owner = await self.conn.fetchval(q, "사장", "OWNER"); self.staff = await self.conn.fetchval(q, "알바", "STAFF")
        await self.conn.execute("update stores set owner_id = $2 where store_id = $1", self.store, self.owner)
        for uid, role in [(self.owner, "OWNER"), (self.staff, "STAFF")]:
            await self.conn.execute("insert into store_members (store_id, user_id, member_role) values ($1, $2, $3)", self.store, uid, role)
        await self.conn.execute("insert into user_identities (user_id, provider, provider_user_id) values ($1, 'KAKAO', 'k-staff')", self.staff)
    async def asyncTearDown(self):
        await drop_db(self.conn, self.name)

    async def test_leave_store_removes_membership_keeps_account(self):
        from app.bootstrap import account
        await account.leave_store(self.conn, store_id=self.store, user_id=self.staff)
        self.assertIsNotNone(await self.conn.fetchval("select removed_at from store_members where user_id = $1", self.staff))
        self.assertIsNone(await self.conn.fetchval("select deleted_at from users where user_id = $1", self.staff))

    async def test_owner_cannot_leave(self):
        from app.bootstrap import account
        with self.assertRaises(account.OwnerCannotLeave):
            await account.leave_store(self.conn, store_id=self.store, user_id=self.owner)

    async def test_staff_withdraw_anonymizes_and_frees_kakao(self):
        from app.bootstrap import account
        await account.withdraw_staff(self.conn, user_id=self.staff)
        row = await self.conn.fetchrow("select name, deleted_at, avatar_path from users where user_id = $1", self.staff)
        self.assertEqual(row["name"], "탈퇴한 사용자"); self.assertIsNotNone(row["deleted_at"]); self.assertIsNone(row["avatar_path"])
        self.assertEqual(await self.conn.fetchval("select count(*) from user_identities where user_id = $1", self.staff), 0)

    async def test_owner_withdraw_closes_store_then_cancel_reopens(self):
        from app.bootstrap import account
        from app.config import get_settings
        days = get_settings().withdrawal_grace_days
        await account.withdraw_owner(self.conn, store_id=self.store, user_id=self.owner, now=NOW)
        row = await self.conn.fetchrow("select closing_at, purge_due_at from stores where store_id = $1", self.store)
        self.assertEqual((row["closing_at"], row["purge_due_at"]), (NOW, NOW + timedelta(days=days)))
        self.assertEqual(await account.withdrawal_due(self.conn, user_id=self.owner), NOW + timedelta(days=days))
        await account.cancel_withdrawal(self.conn, user_id=self.owner, now=NOW + timedelta(days=days - 1))
        row = await self.conn.fetchrow("select closing_at, purge_due_at from stores where store_id = $1", self.store)
        self.assertEqual((row["closing_at"], row["purge_due_at"]), (None, None))
        self.assertIsNone(await account.withdrawal_due(self.conn, user_id=self.owner))

    async def test_withdraw_owner_refuses_someone_elses_store(self):
        from app.bootstrap import account
        with self.assertRaises(LookupError):
            await account.withdraw_owner(self.conn, store_id=self.store, user_id=self.staff, now=NOW)
        self.assertIsNone(await self.conn.fetchval("select closing_at from stores where store_id = $1", self.store))

    async def test_cancel_after_due_fails(self):
        from app.bootstrap import account
        await account.withdraw_owner(self.conn, store_id=self.store, user_id=self.owner, now=NOW)
        with self.assertRaises(account.WithdrawalExpired):
            await account.cancel_withdrawal(self.conn, user_id=self.owner, now=NOW + timedelta(days=31))

    async def test_withdrawn_store_is_purged_once_the_grace_has_passed(self):
        # 탈퇴(이 계획)와 파기(계획 9)가 이어지는지 본다. DB 시계가 기준이라 탈퇴 시각을 과거로 준다
        import asyncpg
        from datetime import datetime as dt
        from app.bootstrap import account, purge
        from app.config import get_settings
        from tests._plan7_db import _db_url
        days = get_settings().withdrawal_grace_days
        await self.conn.execute("insert into user_feedback (store_id, user_id, kind, body) values ($1, $2, 'IDEA', '의견')", self.store, self.staff)
        await self.conn.execute("set session_replication_role = origin")
        deleted = []

        async def fake(bucket, paths):
            deleted.append(bucket)
        pool = await asyncpg.create_pool(_db_url(self.name), min_size=1, max_size=2)
        try:
            await account.withdraw_owner(self.conn, store_id=self.store, user_id=self.owner, now=dt.now(timezone.utc) - timedelta(days=days - 1))
            self.assertEqual(await purge.purge_due_stores(pool, delete_objects=fake), [])
            await account.cancel_withdrawal(self.conn, user_id=self.owner, now=dt.now(timezone.utc))
            await account.withdraw_owner(self.conn, store_id=self.store, user_id=self.owner, now=dt.now(timezone.utc) - timedelta(days=days, seconds=1))
            self.assertEqual(await purge.purge_due_stores(pool, delete_objects=fake), [self.store])
        finally:
            await pool.close()
        self.assertEqual(await self.conn.fetchval("select count(*) from users where user_id = any($1::bigint[])", [self.owner, self.staff]), 0)
        self.assertEqual(await self.conn.fetchval("select count(*) from user_feedback where store_id = $1", self.store), 0)
        self.assertEqual(await self.conn.fetchval("select store_name from stores where store_id = $1", self.store), "삭제된 매장")
        with self.assertRaises(account.WithdrawalExpired):
            await account.cancel_withdrawal(self.conn, user_id=self.owner, now=dt.now(timezone.utc))

    async def test_closed_store_blocks_every_request(self):
        from app.bootstrap import account
        from app.deps import get_store_id
        from app.errors import ApiError
        await account.withdraw_owner(self.conn, store_id=self.store, user_id=self.owner, now=NOW)
        with self.assertRaises(ApiError) as staff_err:
            await get_store_id({"store_id": self.store, "user_id": self.staff, "role": "STAFF"}, self.conn)
        self.assertEqual(staff_err.exception.code, "STORE_CLOSED")
        with self.assertRaises(ApiError) as owner_err:
            await get_store_id({"store_id": self.store, "user_id": self.owner, "role": "OWNER"}, self.conn)
        self.assertEqual(owner_err.exception.code, "OWNER_WITHDRAWING")
```

(`ApiError` import 경로는 기존 라우터가 쓰는 것과 같은 모듈로 맞춘다.)

- [ ] **Step 2: 라우트 테스트**(가짜 DB 없이 문구 검사만)

```python
import pytest
from app.bootstrap.account_router import ConfirmRequest, check_confirm
from app.errors import ApiError

def test_confirm_must_match_exactly_ignoring_edges():
    check_confirm(ConfirmRequest(confirm="  퇴사하겠습니다 "), "퇴사하겠습니다")
    with pytest.raises(ApiError) as err:
        check_confirm(ConfirmRequest(confirm="퇴사 하겠습니다"), "퇴사하겠습니다")
    assert err.value.code == "CONFIRM_MISMATCH"
```

- [ ] **Step 3:** 둘 다 FAIL 확인. **Step 4:** 구현. `withdrawal_loop(pool)`는 `metadata_retention.retention_loop`과 같은 모양(한 시간마다 `purge.purge_due_stores(pool)`, 예외는 종류만 로그에 남기고 계속). **Step 5:** PASS. 전체 pytest(실 DB 포함) 통과. `check_store_id.py api/app/bootstrap api/app/auth api/app/ingest` 결과 기록.

### Task 8: 퇴사, 탈퇴, 로그인된 기기 (화면과 기기 서버)

**Files:** Create `api/app/auth/devices.py`. Modify `api/app/auth/session.py`(`issue_refresh(db, *, user_id, family_id=None, user_agent=None)`, `rotate_refresh`는 앞 행의 `user_agent`를 이어받는다), `api/app/auth/router.py`, `kakao_router.py`(로그인 때 `request.headers.get("user-agent","")[:300]`). Test `api/tests/test_plan8_devices.py`. Create `web/components/settings/typed-confirm.tsx`, `web/app/{owner,staff}/settings/app/devices/page.tsx`, `web/app/withdrawal/page.tsx`. Modify `web/lib/api.ts`(403 `OWNER_WITHDRAWING`이면 `/withdrawal`, `STORE_CLOSED`이면 로그아웃 후 `/`).

**Interfaces — Produces:**
- `device_label(ua: str | None) -> str`
- `GET /auth/sessions` → `[{ family_id, label, last_used_at, current }]`. 활성 계열만(`revoked_at is null and expires_at > now()`). 계열마다 가장 최근 행. `current`는 요청 refresh 쿠키의 계열과 같은지.
- `POST /auth/sessions/{family_id}/revoke` → 204. 내 계열이 아니면 404.

- [ ] **Step 1: 실패하는 테스트**

```python
import pytest
from app.auth.devices import device_label

@pytest.mark.parametrize("ua,label", [
    ("Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) AppleWebKit/605.1.15 Version/18.1 Mobile/15E148 Safari/604.1", "아이폰 Safari"),
    ("Mozilla/5.0 (Linux; Android 15; SM-S928N) AppleWebKit/537.36 Chrome/131.0 Mobile Safari/537.36", "안드로이드 Chrome"),
    ("Mozilla/5.0 (Linux; Android 15; SM-S928N) AppleWebKit/537.36 SamsungBrowser/27.0 Chrome/125.0 Mobile Safari/537.36", "안드로이드 삼성 인터넷"),
    ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/131.0 Safari/537.36", "Mac Chrome"),
    ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36 Edg/131.0", "Windows Edge"),
    ("Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) AppleWebKit/605.1.15 KAKAOTALK 10.9.0", "아이폰 카카오톡"),
    (None, "알 수 없는 기기"),
])
def test_device_label(ua, label):
    assert device_label(ua) == label
```

실 DB 테스트(`test_plan8_account_db.py`에 추가):

```python
    async def test_sessions_list_and_revoke_only_mine(self):
        from app.auth import devices, session
        _, _ = await session.issue_refresh(self.conn, user_id=self.staff, user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) Safari/604.1")
        _, _ = await session.issue_refresh(self.conn, user_id=self.owner, user_agent="x")
        mine = await devices.list_sessions(self.conn, user_id=self.staff, current_family=None)
        self.assertEqual([d["label"] for d in mine], ["아이폰 Safari"])
        with self.assertRaises(LookupError):
            others = await devices.list_sessions(self.conn, user_id=self.owner, current_family=None)
            await devices.revoke(self.conn, user_id=self.staff, family_id=others[0]["family_id"])
        await devices.revoke(self.conn, user_id=self.staff, family_id=mine[0]["family_id"])
        self.assertEqual(await devices.list_sessions(self.conn, user_id=self.staff, current_family=None), [])
```

- [ ] **Step 2:** FAIL. **Step 3:** 구현(판정 순서: KAKAOTALK → 카카오톡, SamsungBrowser → 삼성 인터넷, Edg/ → Edge, Chrome/ → Chrome, Safari/ → Safari. 기기는 iPhone|iPad → 아이폰/아이패드, Android → 안드로이드, Macintosh → Mac, Windows → Windows). **Step 4:** PASS
- [ ] **Step 5: 화면 테스트**

```js
test('BYE-1 퇴사: 묻고, 문구를 그대로 쳐야 켜진다', async (b) => {
  const { page, ctx, api } = await open(b, 'STAFF', '/staff/settings/app');
  await page.getByRole('button', { name: '퇴사했어요' }).click();
  await page.getByRole('dialog', { name: '퇴사하시겠습니까?' }).getByRole('button', { name: '예' }).click();
  const sheet = page.getByRole('dialog', { name: '퇴사하기' });
  const go = sheet.getByRole('button', { name: '퇴사하기' });
  await sheet.getByRole('textbox').fill('퇴사 하겠습니다');
  assert.equal(await go.isDisabled(), true);
  await sheet.getByRole('textbox').fill('퇴사하겠습니다');
  await go.click();
  await page.waitForURL('**/');
  assert.deepEqual(api.calls.find((c) => c.path === '/app/me/leave-store').body, { confirm: '퇴사하겠습니다' });
  await ctx.close();
});
test('BYE-2 아니요면 아무것도 안 한다', async (b) => {
  const { page, ctx, api } = await open(b, 'OWNER', '/owner/settings/app');
  await page.getByRole('button', { name: '회원 탈퇴' }).click();
  const ask = page.getByRole('dialog', { name: '탈퇴하시겠습니까?' });
  await ask.getByText('30일').waitFor();
  await ask.getByRole('button', { name: '아니요' }).click();
  await ask.waitFor({ state: 'hidden' });
  assert.equal(api.calls.filter((c) => c.path === '/app/me/withdraw').length, 0);
  await ctx.close();
});
test('BYE-3 사장님 탈퇴 대기 중 로그인하면 취소 화면', async (b) => {
  const { page, ctx, api } = await open(b, 'OWNER', '/owner', { overrides: { withdrawalDueAt: '2026-12-10T03:00:00Z' } });
  await to(page, '/withdrawal');
  await page.getByText('2026년 12월 10일').waitFor();
  await page.getByRole('button', { name: '탈퇴 취소하기' }).click();
  await to(page, '/owner');
  assert.ok(api.calls.some((c) => c.path === '/app/me/withdrawal/cancel'));
  await ctx.close();
});
test('DEV-1 로그인된 기기: 이 기기 표시, 다른 기기 로그아웃', async (b) => {
  const { page, ctx, api } = await open(b, 'STAFF', '/staff/settings/app/devices');
  await page.getByText('아이폰 Safari').waitFor();
  await page.getByText('이 기기').waitFor();
  await page.getByRole('button', { name: 'Mac Chrome 로그아웃' }).click();
  await page.getByRole('dialog', { name: '이 기기에서 로그아웃할까요?' }).getByRole('button', { name: '로그아웃' }).click();
  await page.getByText('Mac Chrome').waitFor({ state: 'detached' });
  assert.ok(api.calls.some((c) => c.method === 'POST' && /^\/auth\/sessions\/.+\/revoke$/.test(c.path)));
  assert.equal(await page.getByRole('button', { name: '아이폰 Safari 로그아웃' }).count(), 0);
  await ctx.close();
});
```

  - 확인 창 문구(설명은 사실만):
    - 알바생 탈퇴: '계정과 이름이 지워지고 이 매장에서 나가요. 질문 기록은 이름 없이 남아요.'
    - 사장님 탈퇴: '30일 뒤 매장과 계정이 지워져요. 그동안 알바생도 매장에 들어올 수 없어요. 30일 안에 다시 로그인하면 취소할 수 있어요.'
    - 퇴사: '이 매장에서 나가요. 계정은 남아 다른 매장에 합류할 수 있어요.'
  - '이 기기' 줄에는 로그아웃 버튼이 없다. 이 기기는 설정의 로그아웃을 쓴다.
- [ ] **Step 6:** fixture 끝점 추가 후 PASS. `pnpm check` 통과.

### Task 9: 개인정보 처리방침, 이용약관

**Files:** Create `docs/dev/legal/PRIVACY_POLICY_DRAFT.md`, `docs/dev/legal/TERMS_DRAFT.md`, `docs/dev/legal/REVIEW_20261110.md`(검토 기록). Modify `web/app/privacy/page.tsx`, `web/app/terms/page.tsx`(문서를 빌드 때 읽어 그린다. 마크다운 렌더러가 없으면 제목/문단/표만 다루는 작은 변환기를 `web/lib/legal-doc.ts`에 둔다). Create `web/tests/legal-doc.test.mjs`.

참고한 기준(초안 머리말에 출처로 남긴다):
- 개인정보보호위원회 『개인정보 처리방침 작성지침』(2025.4 개정): 필수, 권장 항목. 동의 없이 처리하는 항목과 동의 항목 구분. 설정 메뉴 공개 허용.
- 개인정보 보호법 제30조(처리방침), 제26조(위탁 공개), 제28조의8(국외 이전, 처리방침 공개로 계약 이행 이전), 제21조(파기), 제37조의2(자동화된 결정)
- 생성형 AI 개발, 활용 개인정보 처리 안내서(2025): AI 처리 과정 공개 권고
- 인공지능기본법(2026.1.22 시행) 제31조, 시행령 제23조: 생성형 AI 기반 사실의 사전 고지(약관 기재 가능)
- 약관규제법 제6조, 제7조와 공정위 시정 사례: 고의, 중과실 면책 금지. 탈퇴 방법 제한 금지. 일방 변경 시 사전 공지.
- 외부 처리자 실제 계약: OpenAI API(학습 미사용, 최대 30일 보관), Gemini API 유료(제품 개선 미사용, 남용 감시용 한정 보관), Anthropic API, Supabase, AWS, Vercel, 카카오 로그인, 브라우저 푸시 서비스

처리방침 목차(작성지침 필수 + 해당 시 필수):
1. 처리 목적
2. 처리 항목과 근거(계약 이행, 동의 없음 / 선택). 실제 수집 항목은 아래와 같다.
   - 카카오 회원번호, 닉네임
   - 이름, 프로필 사진, 매장 이름
   - 올린 자료(음성, 영상, 사진, 문서. 사람 목소리, 얼굴이 담길 수 있음)
   - 질문, 답변 기록
   - 푸시 구독 정보
   - 로그인 기기 정보(브라우저 종류), 접속 기록
   - 문의, 의견 글
3. 보유 기간과 파기
   - 탈퇴: 알바생은 즉시, 사장님은 30일 유예 뒤
   - 자료 삭제 시 원본 즉시
   - 로그인 기록은 만료 뒤
   - 파기 방법: 사장님 탈퇴 30일 뒤 그 매장의 모든 기록과 파일을 지운다. 남는 것은 매장 번호와 AI 호출 건수, 비용 기록뿐이고 여기에는 사람이나 매장을 알아볼 내용이 없다(계획 9 D22)
   - 서버 로그(CloudWatch) 30일, 백업 사본의 보존 기간(Supabase 설정값 확인 후 기재)
4. 제3자 제공: 없음
5. 처리 위탁과 국외 이전 표: 받는 자, 국가, 항목, 목적, 시기와 방법, 보유 기간, 거부 방법(거부하면 서비스 이용 불가)
6. 정보주체 권리와 행사 방법: 열람, 정정, 삭제, 처리정지, 전송요구, 동의 철회. 앱 안 경로(마이페이지, 설정, 문의하기)
7. 자동화된 결정: AI가 카드를 만들고 답을 고르지만 사람의 권리, 의무에 중대한 영향을 주는 결정은 하지 않는다. 사장님이 검수 후 공개한다
8. 생성형 AI 처리 과정: 무엇이 어느 모델에 가는지, 학습에 쓰지 않는 계약
9. 안전성 확보 조치
10. 쿠키, 행태정보: 로그인 유지용 쿠키만, 광고 추적 없음
11. 14세 미만: 가입 대상 아님
12. 보호책임자, 고충 처리, 권익 침해 구제 기관(개인정보분쟁조정위원회 1833-6972, 개인정보침해신고센터 118, 대검찰청 1301, 경찰청 182)
13. 변경 이력과 시행일

이용약관 목차:
1. 목적, 정의
2. 약관 게시와 변경(30일 전 공지, 불리한 변경은 개별 통지)
3. 회원 가입(카카오), 사장님과 알바생
4. 서비스 내용과 **생성형 AI 기반 고지**. AI가 만든 카드는 사장님 검수 전 직원에게 보이지 않고, 답이 없으면 추정하지 않고 사장님에게 넘긴다.
5. 회원 의무: 남의 개인정보, 저작물 무단 업로드 금지
6. 올린 자료와 매장 지식의 권리: 회원에게 있다. 회사는 서비스 제공에 필요한 범위에서만 이용, 학습 판매 없음.
7. 서비스 변경, 중단(사전 공지)
8. 퇴사, 탈퇴(앱 안에서 언제든. 다른 방법도 문의로 가능)
9. 이용 제한
10. 책임 제한: 고의, 중과실 면책 없음. AI 답의 한계 고지
11. 분쟁 해결, 관할(민사소송법 따름)
12. 부칙(시행일)

- [ ] **Step 1: 실패하는 단위 테스트**(빈칸이 남으면 화면에 내보내지 않는다)

```js
import assert from "node:assert/strict";
import { test } from "node:test";
import { parseLegalDoc, unfilled } from "../lib/legal-doc.ts";
test("채워야 할 칸을 찾는다", () => assert.deepEqual(unfilled("상호: 【채워야 함: 상호】"), ["상호"]));
test("제목, 문단, 표를 나눈다", () => {
  const doc = parseLegalDoc("# 개인정보 처리방침\n\n## 1. 목적\n\n본문\n\n| a | b |\n|---|---|\n| 1 | 2 |\n");
  assert.deepEqual(doc.map((b) => b.type), ["h1", "h2", "p", "table"]);
});
```

- [ ] **Step 2:** FAIL. **Step 3:** 변환기 구현. 페이지는 `unfilled()`가 비어 있지 않으면 **빌드 실패**(`throw`). 그래서 사용자 값을 받기 전엔 Task 4의 제목만 있는 페이지를 유지한다.
- [ ] **Step 4:** 초안 두 문서 작성. 실제 수집 항목은 코드에서 다시 확인한다(`users` 컬럼, `user_identities`, `auth_refresh_tokens`, `push_subscriptions` 류, `user_feedback`, `sources`, 질문 표). 위탁 표의 리전은 사용자 값.
- [ ] **Step 5: 2차 검토**(`REVIEW_20261110.md`에 표로 남긴다)
  - 작성지침 필수 항목 대조표: 항목 → 초안 절 → 있음/없음
  - 처리 항목 ↔ 실제 컬럼 대조
  - 약관 조항마다 약관규제법 제6~14조 해당 여부
  - 'AI 기반 고지' 위치
  - 남은 위험(법률 자문 필요 항목)
  - 이 검토는 변호사 검토를 대신하지 않는다고 맨 위에 적는다.
- [ ] **Step 6:** 사용자 값을 받은 뒤 빈칸을 채우면 `/privacy`, `/terms`가 문서를 그린다. DOC-1 PASS. 그리고 `pnpm build`가 빈칸 검사를 통과한다.

### Task 10: 문서와 마무리

- [ ] MVP 정본에 설정 계약, 탈퇴 상태(`stores.closing_at`, `stores.purge_due_at`, 응답의 `withdrawal_due_at`, 403 코드 두 개), 의견 표, 기기 목록을 적는다. 파기 규칙(D22)은 계획 9 Task 4가 이미 적었으므로 그 절을 가리킨다.
- [ ] `ui-state-walkthrough`, `web-async-state-check`, `store-isolation-check` 스킬을 실행한다.
- [ ] 전체 `run-ui.sh`(OLD=1), 전체 pytest(실 DB), `verify_r_schema_rebuild.py`, `node --test web/tests` 통과 기록을 ledger에 남긴다.
- [ ] 휴대폰 실기기 확인은 자동화 범위 밖이다(아이폰 홈 화면 앱 푸시). 확인하지 못했으면 그렇게 보고한다.
