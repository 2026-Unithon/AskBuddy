// 이동·공통 키트 회귀(화면 개선 계획 1). 합성 API(ui_fixture.cjs)만 쓴다.
// 실행: next start -p 3011 을 띄운 뒤 NODE_PATH=<playwright> node api/scripts/verify_ui_nav.cjs [이름 앞부분]
const assert = require('node:assert/strict');
const { createSuite, open, back, to, phoneBack, here, BASE } = require('./ui_harness.cjs');
const { test, run } = createSuite('ui-nav');

test('NAV-1 질문 상세의 앱 뒤로는 왔던 오늘 매장, 폰 뒤로로 상세에 돌아가지 않는다', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner');
  await page.getByText('디카페인 원두는 어디 있어요?').first().click(); await to(page, '/owner/questions/101');
  await back(page).click(); await to(page, '/owner');
  assert.notEqual(await phoneBack(page), '/owner/questions/101');
  await ctx.close();
});
test('NAV-1 카드 상세 왕복이 없다', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/cards');
  await page.getByText('아메리카노').first().click(); await to(page, '/owner/cards/2');
  await back(page).click(); await to(page, '/owner/cards');
  assert.notEqual(await phoneBack(page), '/owner/cards/2');
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
  await page.getByText('아메리카노').first().click(); await to(page, '/owner/cards/2');
  await page.reload({ waitUntil: 'networkidle' });
  await back(page).click(); await to(page, '/owner/cards');
  assert.notEqual(await phoneBack(page), '/owner/cards/2');
  await ctx.close();
});
test('NAV-1 옛 상단 바(알림)의 뒤로: 기록이 없으면 오늘 매장(T3)', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/notifications');
  await page.getByRole('link', { name: '뒤로가기' }).click(); await to(page, '/owner');
  await ctx.close();
});
test('NAV-1 BackButton 보조 키 클릭은 가로채지 않는다', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/cards/1');
  const popup = ctx.waitForEvent('page', { timeout: 5000 });
  await back(page).click({ modifiers: [process.platform === 'darwin' ? 'Meta' : 'Control'] });
  await popup;
  // 헤드리스 크로미움은 보조 키로 연 뒷탭을 불러오지 않아(about:blank) 새 탭 주소 대신 링크 주소를 본다
  assert.equal(await back(page).getAttribute('href'), '/owner/cards');
  await page.waitForTimeout(500);
  assert.equal(here(page), '/owner/cards/1', '지금 화면은 그대로');
  await ctx.close();
});

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
  await page.locator('main').evaluate((m) => { m.scrollTop = 120; m.dispatchEvent(new Event('scroll')); });
  const tabs = page.getByRole('navigation', { name: '주요 메뉴' });
  await tabs.getByRole('link', { name: '오늘 매장' }).click(); await to(page, '/owner');
  await tabs.getByRole('link', { name: '카드' }).click(); await to(page, '/owner/cards');
  await page.waitForTimeout(300);
  const top = await page.locator('main').evaluate((m) => m.scrollTop);
  assert.ok(Math.abs(top - 120) <= 2, `scrollTop ${top}`);
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

test('G1 앞으로는 forward, 앱 뒤로는 back, 탭은 fade', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/cards');
  // 진입 방향은 새 화면이 그려질 때 정해지므로 기대값이 될 때까지 기다린다
  const expectEnter = async (value) => {
    await page.waitForFunction((v) => document.querySelector('[data-enter]')?.getAttribute('data-enter') === v, value, { timeout: 3000 });
  };
  await expectEnter('initial');
  await page.getByText('아메리카노').first().click(); await to(page, '/owner/cards/2');
  await expectEnter('forward');
  await back(page).click(); await to(page, '/owner/cards');
  await expectEnter('back');
  await page.getByRole('navigation', { name: '주요 메뉴' }).getByRole('link', { name: '오늘 매장' }).click(); await to(page, '/owner');
  await expectEnter('fade');
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
  // Tailwind 4 의 scale-* 는 transform 이 아니라 CSS scale 속성을 쓴다
  const scale = await btn.evaluate((el) => { const cs = getComputedStyle(el); return cs.scale && cs.scale !== 'none' ? Number(cs.scale.split(' ')[0]) : new DOMMatrix(cs.transform).a; });
  await page.mouse.up();
  assert.ok(Math.abs(scale - 0.97) < 0.005, `scale ${scale}`);
  await ctx.close();
});

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

test('NAV-9 알림의 새 주소는 리다이렉트 없이 바로 열린다', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/notifications');
  await page.getByText('직원 질문이 왔어요').click(); await to(page, '/owner/questions/101');
  await ctx.close();
});

test('NAV-1 코드가 부른 replace 도 기록을 쌓지 않는다: 바로 연 버디에서 첫 질문 뒤 뒤로는 오늘 할 일', async (b) => {
  const { page, ctx } = await open(b, 'STAFF', '/staff/ask');
  await page.getByLabel('모르는 거 물어보기').fill('바닐라 라떼 시럽 몇 펌프예요?');
  await page.getByRole('button', { name: '보내기', exact: true }).click();
  await page.waitForURL(/session_id=1/);
  await page.waitForLoadState('networkidle');
  await back(page).click();
  await page.waitForTimeout(500);
  assert.equal(page.url().startsWith('about:') ? 'about:blank' : here(page), '/staff');
  await ctx.close();
});
test('G1 같은 화면 안 필터 replace 는 진입 모션을 다시 틀지 않는다', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner');
  await page.getByRole('navigation', { name: '주요 메뉴' }).getByRole('link', { name: '카드' }).click(); await to(page, '/owner/cards');
  await page.waitForFunction(() => document.querySelector('[data-enter]')?.getAttribute('data-enter') === 'fade');
  await page.getByRole('tab', { name: /검수 필요/ }).click(); await page.waitForURL(/review_status|status=/);
  await page.waitForTimeout(300);
  assert.notEqual(await page.locator('[data-enter]').first().getAttribute('data-enter'), 'forward');
  await ctx.close();
});
test('NAV-3 닿을 수 없는 저장 위치여도 사용자가 스크롤하면 끌려가지 않는다', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner', { viewport: { width: 390, height: 480 } });
  await page.evaluate(() => sessionStorage.setItem('askbuddy:scroll:/owner/cards', '50000'));
  await page.getByRole('navigation', { name: '주요 메뉴' }).getByRole('link', { name: '카드' }).click(); await to(page, '/owner/cards');
  await page.waitForTimeout(400);
  const main = page.locator('main');
  await main.hover(); await page.mouse.wheel(0, -100000); await page.waitForTimeout(200);
  await main.evaluate((m) => { m.scrollTop = 40; m.dispatchEvent(new Event('scroll')); });
  // 화면 안 높이가 바뀌어도(오류 배너, 펼치기 등) 다시 끌려가지 않아야 한다
  await main.evaluate((m) => { for (const c of m.children) c.style.paddingBottom = '60px'; });
  await page.waitForTimeout(400);
  const top = await main.evaluate((m) => m.scrollTop);
  assert.ok(top < 100, `scrollTop ${top}`);
  await ctx.close();
});
test('NAV-3 새로고침으로 캐시가 비어도(늦게 그려져도) 탭 스크롤을 되살린다', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/cards', { viewport: { width: 390, height: 480 } });
  await page.locator('main').evaluate((m) => { m.scrollTop = 120; m.dispatchEvent(new Event('scroll')); });
  await page.waitForTimeout(200);
  await page.getByRole('navigation', { name: '주요 메뉴' }).getByRole('link', { name: '오늘 매장' }).click(); await to(page, '/owner');
  await page.reload({ waitUntil: 'networkidle' });
  await page.getByRole('navigation', { name: '주요 메뉴' }).getByRole('link', { name: '카드' }).click(); await to(page, '/owner/cards');
  await page.waitForTimeout(500);
  const top = await page.locator('main').evaluate((m) => m.scrollTop);
  assert.ok(Math.abs(top - 120) <= 2, `scrollTop ${top}`);
  await ctx.close();
});

run();
