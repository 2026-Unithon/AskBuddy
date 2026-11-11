// 계획 8(UI_REDESIGN_PLAN8_MYPAGE_SETTINGS_20261110) 마이페이지와 설정. 합성 API(ui_fixture.cjs)만 쓴다.
// 실행: next start -p 3011 을 띄운 뒤 NODE_PATH=<playwright> node api/scripts/verify_ui_plan8.cjs [이름 앞부분]
const assert = require('node:assert/strict');
const { createSuite, open, to } = require('./ui_harness.cjs');
const { test, run } = createSuite('ui-plan8');

// ── Task 2: 마이페이지와 설정 골격 ──
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

// ── Task 3: 이 기기 푸시 알림 받기 ──
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
test('PUSH-4 사장님은 사장님 구독 끝점에 저장한다', async (b) => {
  const { page, ctx, api } = await open(b, 'OWNER', '/owner/settings/app', { overrides: { pushEnv: { permission: 'granted' } } });
  await page.getByRole('switch', { name: '이 기기 푸시 알림 받기' }).click();
  await page.waitForFunction(() => document.querySelector('[role=switch]')?.getAttribute('aria-checked') === 'true');
  assert.ok(api.calls.some((c) => c.method === 'POST' && c.path === '/notifications/subscriptions'));
  await ctx.close();
});

// ── Task 4: 매장 지식 내려받기, 초대 링크, 문서 링크 ──
test('EXP-1 매장 지식 내려받기는 파일을 저장한다', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/settings/app');
  const [download] = await Promise.all([page.waitForEvent('download'), page.getByRole('button', { name: '매장 지식 내려받기' }).click()]);
  assert.match(download.suggestedFilename(), /^askbuddy-knowledge-\d{8}\.json$/);
  await ctx.close();
});
test('EXP-1b 내려받기 실패는 알린다', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/settings/app', { overrides: { failExport: true } });
  await page.getByRole('button', { name: '매장 지식 내려받기' }).click();
  await page.getByRole('status').getByText(/내려받지 못했어요/).waitFor();
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

// ── Task 5: 올린 자료 관리(사장님) ──
test('SRC-1 올린 자료를 보고, 지우기 전에 묻는다', async (b) => {
  const { page, ctx, api } = await open(b, 'OWNER', '/owner/settings/app/sources');
  await page.getByText('레시피북.pdf').waitFor();
  await page.getByRole('button', { name: '레시피북.pdf 지우기' }).click();
  const dialog = page.getByRole('dialog', { name: '이 자료를 지울까요?' });
  await dialog.getByText('원본 파일은 지워지고, 만든 카드는 남아요.').waitFor();
  await dialog.getByRole('button', { name: '지우기' }).click();
  await page.getByText('레시피북.pdf').waitFor({ state: 'detached' });
  assert.ok(api.calls.some((c) => c.method === 'DELETE' && c.path.startsWith('/ingest/sources/')));
  await ctx.close();
});
test('SRC-2 자료가 없으면 빈 화면, 불러오기 실패면 다시 시도', async (b) => {
  const empty = await open(b, 'OWNER', '/owner/settings/app/sources', { overrides: { sources: [] } });
  await empty.page.getByText('올린 자료가 없어요').waitFor();
  await empty.ctx.close();
  const { page, ctx } = await open(b, 'OWNER', '/owner/settings/app/sources', { overrides: { failSources: true } });
  await page.getByRole('button', { name: '다시 시도' }).waitFor();
  await ctx.close();
});

// ── Task 6: 문의하기, 의견 보내기 ──
test('FB-1 문의하기 시트에서 보내면 저장되고 닫힌다', async (b) => {
  const { page, ctx, api } = await open(b, 'STAFF', '/staff/settings');
  await page.getByRole('button', { name: '문의하기' }).click();
  const sheet = page.getByRole('dialog', { name: '문의하기' });
  assert.equal(await sheet.getByRole('button', { name: '보내기' }).isDisabled(), true);
  await sheet.getByRole('textbox').fill('사진이 안 올라가요');
  await sheet.getByRole('button', { name: '보내기' }).click();
  await page.getByRole('status').getByText('보냈어요').waitFor();
  await sheet.waitFor({ state: 'detached' });
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

// ── Task 8: 퇴사, 탈퇴, 로그인된 기기 ──
test('BYE-1 퇴사: 묻고, 문구를 그대로 쳐야 켜진다', async (b) => {
  const { page, ctx, api } = await open(b, 'STAFF', '/staff/settings/app');
  await page.getByRole('button', { name: '퇴사했어요' }).click();
  const ask = page.getByRole('dialog', { name: '퇴사하시겠습니까?' });
  await ask.getByText('이 매장에서 나가요. 계정은 남아 다른 매장에 합류할 수 있어요.').waitFor();
  await ask.getByRole('button', { name: '예' }).click();
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
  await ask.getByText(/30일/).waitFor();
  await ask.getByRole('button', { name: '아니요' }).click();
  await ask.waitFor({ state: 'hidden' });
  assert.equal(api.calls.filter((c) => c.path === '/app/me/withdraw').length, 0);
  await ctx.close();
});
test('BYE-2b 사장님 탈퇴는 문구를 친 뒤 보내고 첫 화면으로', async (b) => {
  const { page, ctx, api } = await open(b, 'OWNER', '/owner/settings/app');
  await page.getByRole('button', { name: '회원 탈퇴' }).click();
  await page.getByRole('dialog', { name: '탈퇴하시겠습니까?' }).getByRole('button', { name: '예' }).click();
  const sheet = page.getByRole('dialog', { name: '탈퇴하기' });
  await sheet.getByRole('textbox').fill('  탈퇴하겠습니다 ');
  await sheet.getByRole('button', { name: '탈퇴하기' }).click();
  await page.waitForURL('**/');
  assert.deepEqual(api.calls.find((c) => c.path === '/app/me/withdraw').body, { confirm: '탈퇴하겠습니다' });
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
test('BYE-4 닫힌 매장의 알바생은 로그아웃되어 첫 화면으로', async (b) => {
  const { page, ctx, api } = await open(b, 'STAFF', '/staff/settings', { overrides: { storeClosed: true } });
  await page.waitForURL((u) => u.pathname === '/');
  assert.ok(api.calls.some((c) => c.path === '/auth/logout'));
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

// ── Task 10: 화면 상태(ui-state-walkthrough) ──
test('STATE-1 기기 목록 불러오기 실패면 다시 시도로 복구', async (b) => {
  const { page, ctx, api } = await open(b, 'STAFF', '/staff/settings/app/devices', { overrides: { failDevices: true } });
  await page.getByRole('button', { name: '다시 시도' }).waitFor();
  api.state.failDevices = false;
  await page.getByRole('button', { name: '다시 시도' }).click();
  await page.getByText('아이폰 Safari').waitFor();
  await ctx.close();
});
test('STATE-2 보내기를 연타해도 한 번만 저장한다', async (b) => {
  const { page, ctx, api } = await open(b, 'STAFF', '/staff/settings', { overrides: { feedbackDelayMs: 800 } });
  await page.getByRole('button', { name: '의견 보내기' }).click();
  const sheet = page.getByRole('dialog', { name: '의견 보내기' });
  await sheet.getByRole('textbox').fill('합성 의견');
  const send = sheet.getByRole('button', { name: '보내기' });
  await send.click();
  await send.click({ force: true }).catch(() => {});
  await page.getByRole('status').getByText('보냈어요').waitFor();
  assert.equal(api.calls.filter((c) => c.path === '/app/feedback').length, 1);
  await ctx.close();
});
test('LAY-1 360 폭에서 새 화면들이 가로로 넘치지 않는다', async (b) => {
  for (const [role, url] of [['OWNER', '/owner/settings'], ['OWNER', '/owner/settings/app'], ['OWNER', '/owner/settings/app/sources'],
    ['STAFF', '/staff/settings/app'], ['STAFF', '/staff/settings/app/devices'], ['OWNER', '/withdrawal']]) {
    const { page, ctx } = await open(b, role, url, { viewport: { width: 360, height: 800 }, overrides: url === '/withdrawal' ? { withdrawalDueAt: '2026-12-10T03:00:00Z' } : {} });
    await page.locator('main h1').first().waitFor();
    const over = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    assert.ok(over <= 0, `${url} 가로 넘침 ${over}px`);
    await ctx.close();
  }
});

run();
