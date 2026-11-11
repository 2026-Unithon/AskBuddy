// 설정·관리 화면 회귀(화면 개선 계획 4b). 합성 API(ui_fixture.cjs)만 쓴다.
// 실행: next start -p 3011 을 띄운 뒤 NODE_PATH=<playwright> node api/scripts/verify_ui_manage.cjs [이름 앞부분]
const assert = require('node:assert/strict');
const { createSuite, open, to, here } = require('./ui_harness.cjs');
const { test, run } = createSuite('ui-manage');

// ── Task 1 설정 ──
test('o12a 설정 위는 프로필, 아래는 관리 항목과 뱃지', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/settings');
  const profile = page.locator('[data-profile]');
  await profile.getByText('김사장', { exact: true }).waitFor();
  assert.ok(await profile.getByText('버디 카페 1호점', { exact: true }).isVisible());
  for (const name of ['근무조', '직원 관리', '알바생 기록', '카테고리', '알림']) await page.getByRole('link', { name: new RegExp(`^${name}`) }).waitFor();
  await page.getByRole('link', { name: /^직원 관리/ }).getByText('1', { exact: true }).waitFor();
  await page.getByRole('link', { name: /^알림/ }).getByText('3', { exact: true }).waitFor();
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
// 계획 8: 로그아웃은 마이페이지가 아니라 설정(/owner/settings/app)에 있다
test('o12b 로그아웃은 확인 창을 거친다', async (b) => {
  const { page, ctx, api } = await open(b, 'OWNER', '/owner/settings/app');
  await page.getByRole('button', { name: '로그아웃' }).click();
  const dialog = page.getByRole('dialog', { name: '로그아웃할까요?' });
  await dialog.waitFor();
  await dialog.getByRole('button', { name: '취소' }).click();
  await dialog.waitFor({ state: 'hidden' });
  assert.equal(api.calls.filter((c) => c.path === '/auth/logout').length, 0);
  await page.getByRole('button', { name: '로그아웃' }).click();
  await dialog.getByRole('button', { name: '로그아웃' }).click();
  await page.waitForURL((u) => u.pathname !== '/owner/settings/app');
  assert.equal(api.calls.filter((c) => c.path === '/auth/logout').length, 1);
  await ctx.close();
});

// ── Task 2 직원 관리·초대·직원 담당·첫 준비 끝 ──
async function swipeLeft(page, row) {
  const box = await row.boundingBox();
  await page.mouse.move(box.x + box.width - 20, box.y + box.height / 2); await page.mouse.down();
  await page.mouse.move(box.x + box.width - 140, box.y + box.height / 2, { steps: 10 }); await page.mouse.up();
}
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
  await row.waitFor();
  await swipeLeft(page, row);
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
  // 서버 응답(800ms)보다 먼저 보이면 낙관 반영이다. 화면 갱신은 한 박자(tick) 뒤라 300ms 안을 본다
  await card.locator('[role=checkbox][aria-checked=true]', { hasText: '미들' }).waitFor({ timeout: 300 });
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

// ── Task 3 근무조 ──
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
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2 + rowHeight * 0.8, { steps: 10 });
  const [saved] = await Promise.all([
    page.waitForResponse((res) => res.request().method() === 'PUT' && new URL(res.url()).pathname.endsWith('/checklist/shifts/order')),
    page.mouse.up(),
  ]);
  assert.ok(saved.ok());
  await page.waitForFunction(() => document.querySelector('main h2')?.textContent === '미들');
  assert.deepEqual(api.state.shifts.map((s) => s.name), ['미들', '오픈', '마감']);
  // Verify the saved drag order before testing the independent keyboard move.
  await page.reload();
  await page.waitForFunction(() => document.querySelector('main h2')?.textContent === '미들');
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

// ── Task 4 알바생 기록 ──
const monthOf = (text) => { const [, y, m] = text.match(/(\d+)년 (\d+)월/); return `${y}-${m.padStart(2, '0')}`; };
test('o13a 알바생 기록: 알바생만 시트로 고른다', async (b) => {
  const { page, ctx, api } = await open(b, 'OWNER', '/owner/me');
  await page.getByRole('heading', { name: '알바생 기록' }).waitFor();
  await page.getByRole('button', { name: '기록 볼 알바생, 지금 박지호' }).click();
  const sheet = page.getByRole('dialog', { name: '누구 기록을 볼까요?' });
  await sheet.waitFor();
  assert.deepEqual((await sheet.locator('[data-member-option]').allInnerTexts()).map((x) => x.trim()), ['박지호', '김민준']);
  await sheet.getByRole('button', { name: '김민준' }).click();
  await page.getByRole('button', { name: '기록 볼 알바생, 지금 김민준' }).waitFor();
  await page.waitForTimeout(300);
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
  await page.keyboard.press('Escape');
  await sheet.waitFor({ state: 'hidden' });
  const cal = await page.locator('[data-calendar]').boundingBox();
  await page.mouse.move(cal.x + cal.width - 30, cal.y + 120); await page.mouse.down();
  await page.mouse.move(cal.x + 30, cal.y + 130, { steps: 12 }); await page.mouse.up();
  const [y, m] = month.split('-').map(Number);
  const next = m === 12 ? `${y + 1}년 1월` : `${y}년 ${m + 1}월`;
  await page.getByRole('heading', { name: next }).waitFor();
  await page.waitForTimeout(300);
  assert.equal(await page.getByRole('dialog', { name: /월 \d+일/ }).count(), 0, '밀기는 날짜 누르기가 아니다');
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

// ── Task 5 카테고리 ──
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
test('o17 휴지통을 누르면 확인 창, 기타는 못 지운다(2026-11-08 밀기 대신 휴지통)', async (b) => {
  const { page, ctx, api } = await open(b, 'OWNER', '/owner/categories');
  const row = page.locator('[data-category]').filter({ hasText: '오픈 마감' });
  await row.waitFor();
  await row.getByRole('button', { name: '오픈 마감 지우기' }).click();
  const dialog = page.getByRole('dialog', { name: "'오픈 마감' 카테고리를 지울까요?" });
  await dialog.getByRole('button', { name: '지우기' }).click();
  await page.getByRole('status').getByText('카테고리를 지웠어요').waitFor();
  assert.ok(!api.state.categories.some((c) => c.category_id === 11));
  assert.equal(await page.getByRole('button', { name: '기타 지우기' }).count(), 0);
  await ctx.close();
});

// ── Task 6 알림 ──
test('o18b 알림: 밀어서 읽음, 머리 뱃지가 줄어든다', async (b) => {
  const { page, ctx, api } = await open(b, 'OWNER', '/owner/notifications');
  const head = page.getByRole('heading', { name: /알림/ });
  await head.getByText('3', { exact: true }).waitFor();
  const row = page.locator('[data-notification]').filter({ hasText: '카드 정리가 끝났어요' });
  await swipeLeft(page, row);
  await head.getByText('2', { exact: true }).waitFor();
  assert.ok(api.state.notifications.find((n) => n.notification_id === 2).read_at);
  assert.equal(here(page), '/owner/notifications');
  await ctx.close();
});
test('o18b 밀어서 읽음 실패하면 그대로', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/notifications', { overrides: { failRead: true } });
  // 밀기 버튼은 내용 뒤에 있다. 키보드로 포커스하면 드러나고 Enter 로 누른다
  await page.getByRole('button', { name: '카드 정리가 끝났어요 읽음으로' }).focus();
  await page.keyboard.press('Enter');
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

// ── 최종 검토 고침(중요 7건) ──
test('검토 1 앞 저장이 늦게 끝나도 연달아 고른 담당이 다 남는다', async (b) => {
  const { page, ctx, api } = await open(b, 'OWNER', '/owner/member-shifts', { overrides: { memberShiftDelays: [700, 0] } });
  const card = page.locator('[data-member-shifts]').filter({ hasText: '김민준' });
  await card.getByRole('checkbox', { name: '오픈' }).click();
  await card.getByRole('checkbox', { name: '미들' }).click();
  await page.waitForTimeout(1800);
  assert.deepEqual([...api.state.checklistMembers.find((m) => m.member_id === 3).shift_ids].sort(), [1, 2, 3]);
  await ctx.close();
});
test('검토 2 손가락으로 달을 넘긴 뒤 처음 누른 날짜가 열린다', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/me', { touch: true });
  const month = monthOf(await page.getByRole('heading', { name: /\d+년 \d+월/ }).innerText());
  const cal = await page.locator('[data-calendar]').boundingBox();
  const cdp = await ctx.newCDPSession(page);
  const at = (type, x) => cdp.send('Input.dispatchTouchEvent', { type, touchPoints: type === 'touchEnd' ? [] : [{ x, y: cal.y + 120 }] });
  await at('touchStart', cal.x + cal.width - 30);
  for (let x = cal.x + cal.width - 30; x >= cal.x + 30; x -= 20) await at('touchMove', x);
  await at('touchEnd', cal.x + 30);
  const [y, m] = month.split('-').map(Number);
  const nextMonth = m === 12 ? `${y + 1}-01` : `${y}-${String(m + 1).padStart(2, '0')}`;
  await page.getByRole('heading', { name: m === 12 ? `${y + 1}년 1월` : `${y}년 ${m + 1}월` }).waitFor();
  await page.getByRole('button', { name: `${nextMonth}-11 78%` }).tap();
  await page.getByRole('dialog', { name: `${Number(nextMonth.slice(5))}월 11일` }).waitFor({ timeout: 3000 });
  await ctx.close();
});
test('검토 2 날짜 터치는 끌기·취소와 구분하고 키보드로도 열린다', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/me', { touch: true });
  const month = monthOf(await page.getByRole('heading', { name: /\d+년 \d+월/ }).innerText());
  const date = page.getByRole('button', { name: `${month}-11 78%` });
  const box = await date.boundingBox();
  const x = box.x + box.width / 2, y = box.y + box.height / 2;
  const cdp = await ctx.newCDPSession(page);
  const touch = (type, atX = x) => cdp.send('Input.dispatchTouchEvent', { type, touchPoints: ['touchEnd', 'touchCancel'].includes(type) ? [] : [{ x: atX, y }] });
  // 조금 끌었다 제자리로 돌아와도 날짜를 고르는 탭은 아니다.
  await touch('touchStart');
  await touch('touchMove', x + 25);
  await touch('touchMove');
  await touch('touchEnd');
  assert.equal(await page.getByRole('dialog').count(), 0, '끌었다 돌아와도 날짜를 열지 않는다');
  await touch('touchStart');
  await touch('touchCancel');
  assert.equal(await page.getByRole('dialog').count(), 0, '취소한 터치로 날짜를 열지 않는다');
  await date.tap();
  const sheet = page.getByRole('dialog', { name: `${Number(month.slice(5))}월 11일` });
  await sheet.waitFor({ timeout: 3000 });
  await page.getByRole('button', { name: '닫기', exact: true }).click();
  await sheet.waitFor({ state: 'detached' });
  await date.focus();
  await date.press('Enter');
  await sheet.waitFor();
  await ctx.close();
});
test('검토 3 시트를 열자마자 이름을 고쳐도 휠을 굴린 값이 저장된다', async (b) => {
  const shifts = [['오픈', '08:07', '12:00'], ['미들', '12:00', '17:00']].map(([name, starts_at, ends_at], i) => ({ shift_id: i + 1, name, starts_at, ends_at, sort_order: i, card_ids: [] }));
  const { page, ctx, api } = await open(b, 'OWNER', '/owner/shifts', { overrides: { shifts } });
  await page.getByRole('button', { name: '고치기' }).first().click();
  const sheet = page.getByRole('dialog', { name: '근무조 고치기' });
  await sheet.getByLabel('이름', { exact: true }).pressSequentially(' 조', { delay: 60 });
  await page.waitForTimeout(1000);
  const hours = sheet.getByRole('listbox', { name: '시작 시' });
  await hours.evaluate((el) => el.scrollTo({ top: 10 * 44 }));
  await hours.getByRole('option', { name: '10' }).and(page.locator('[aria-selected=true]')).waitFor({ timeout: 2000 });
  await sheet.getByRole('button', { name: '저장', exact: true }).click();
  await page.getByRole('status').getByText('저장했어요').waitFor();
  assert.equal(api.state.shifts.find((s) => s.shift_id === 1).starts_at, '10:07');
  await ctx.close();
});
test('검토 4 근무조를 한 번에 두 칸 끌면 두 칸 옮겨지고 한 번만 저장한다', async (b) => {
  const { page, ctx, api } = await open(b, 'OWNER', '/owner/shifts');
  const handle = page.getByRole('button', { name: '마감 옮기기' });
  await handle.scrollIntoViewIfNeeded();
  const box = await handle.boundingBox();
  const rowHeight = await handle.evaluate((el) => el.closest('li').getBoundingClientRect().height);
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2); await page.mouse.down();
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2 - rowHeight * 1.8, { steps: 24 }); await page.mouse.up();
  await page.waitForTimeout(800);
  assert.deepEqual(api.state.shifts.map((s) => s.name), ['마감', '오픈', '미들']);
  assert.equal(api.calls.filter((c) => c.path === '/checklist/shifts/order').length, 1);
  await ctx.close();
});
test('검토 5 확인 창에서 실패하면 창 안에 이유가 보인다', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/categories', { overrides: { failCategoryDelete: true } });
  const row = page.locator('[data-category]').filter({ hasText: '오픈 마감' });
  await row.waitFor();
  await row.getByRole('button', { name: '오픈 마감 지우기' }).click();
  const dialog = page.getByRole('dialog', { name: "'오픈 마감' 카테고리를 지울까요?" });
  await dialog.getByRole('button', { name: '지우기' }).click();
  await dialog.getByRole('alert').getByText('카테고리 삭제 실패').waitFor({ timeout: 3000 });
  await ctx.close();
});
test('검토 6 나중에를 눌러도 휴대폰 알림을 켤 곳이 남는다', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/notifications', { overrides: { pushConfigured: true } });
  await page.getByRole('button', { name: '나중에' }).click();
  await page.reload({ waitUntil: 'networkidle' });
  await page.getByRole('button', { name: '휴대폰 알림 켜기' }).waitFor({ timeout: 3000 });
  await ctx.close();
});
test('검토 7 재분류 다시가 실패하면 보이고, 누르는 동안 막힌다', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/categories', { overrides: { reclassification: { job_id: 5, status: 'FAILED' }, failRetry: true } });
  await page.getByRole('button', { name: '다시', exact: true }).click();
  await page.getByText('재분류 재시도 실패').waitFor({ timeout: 3000 });
  await ctx.close();
});

run();
