// 직원 화면·로그인 회귀(화면 개선 계획 5). 합성 API(ui_fixture.cjs)만 쓴다.
// 실행: next start -p 3011 을 띄운 뒤 NODE_PATH=<playwright> node api/scripts/verify_ui_staff.cjs [이름 앞부분]
const assert = require('node:assert/strict');
const { createSuite, open, to, here, BASE } = require('./ui_harness.cjs');
const { test, run } = createSuite('ui-staff');

// ── Task 1 오늘 할 일 ──
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

// ── Task 2 레시피 ──
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

// ── Task 3 버디 ──
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

// ── Task 4 답변 알림 ──
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

// ── Task 5 로그인 ──
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

// ── 최종 검토 고침 ──
test('검토 1 대화 목록을 불러오는 동안 추천 칩을 눌러 새 대화를 만들지 않는다', async (b) => {
  const { page, ctx, api } = await open(b, 'STAFF', '/staff', { overrides: { sessions: [{ session_id: '1' }], sessionsDelayMs: 2500 } });
  await page.goto(BASE + '/staff/ask', { waitUntil: 'commit' });
  await page.waitForTimeout(800);
  const chip = page.locator('[data-suggested]').first();
  if (await chip.count()) await chip.click({ timeout: 500 }).catch(() => {});
  await page.waitForTimeout(2500);
  assert.equal(api.calls.filter((c) => c.method === 'POST' && c.path === '/learn/v2/sessions').length, 0);
  await ctx.close();
});
test('검토 2 가입할 때 이름이 비면 보내지 않고 칸 아래 빨간 글', async (b) => {
  const { page, ctx, api } = await open(b, 'STAFF', '/auth/email', { overrides: { signedOut: true } });
  await page.getByRole('button', { name: '처음이신가요? 가입하기' }).click();
  await page.getByLabel('이름').fill('   ');
  await page.getByLabel('이메일').fill('new@synthetic.test');
  await page.getByLabel('비밀번호').fill('right-pass');
  await page.getByRole('button', { name: '가입하기', exact: true }).click();
  await page.getByText('이름을 적어 주세요').waitFor();
  assert.equal(api.calls.filter((c) => c.path === '/auth/signup').length, 0);
  await ctx.close();
});
test('검토 3 서버 본문 형식([재료 · HOT])도 규격 제목으로 나눈다', async (b) => {
  const content = '[재료 · HOT]\n- 물 275ml\n- 샷 2\n\n[재료 · ICE]\n- 물 225ml\n- 얼음 가득\n\n[순서]\n1. 컵에 얼음을 담는다\n2. 샷을 붓는다\n\n근거 자료: 레시피 메모.jpg';
  const { page, ctx } = await open(b, 'STAFF', '/staff/recipes/12', { overrides: { itemContent: { 12: content } } });
  await page.getByRole('heading', { name: 'HOT 재료', exact: true }).waitFor();
  await page.getByRole('heading', { name: 'ICE 재료', exact: true }).waitFor();
  await page.getByRole('heading', { name: '순서', exact: true }).waitFor();
  await page.getByText('물 225ml', { exact: true }).waitFor();
  for (const gone of ['[재료 · HOT]', '근거 자료', '- 물 275ml']) assert.equal(await page.getByText(gone, { exact: false }).count(), 0, gone);
  await ctx.close();
});

run();
