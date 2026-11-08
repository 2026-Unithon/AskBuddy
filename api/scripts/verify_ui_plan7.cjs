// 계획 7(UI_REDESIGN_PLAN7_BULK_REVIEW_20261108) 화면 회귀. 합성 API(ui_fixture.cjs)만 쓴다.
// 실행: next start -p 3011 을 띄운 뒤 NODE_PATH=<playwright> node api/scripts/verify_ui_plan7.cjs [이름 앞부분]
const assert = require('node:assert/strict');
const { createSuite, open, to, here } = require('./ui_harness.cjs');
const { test, run } = createSuite('ui-plan7');

// ── 사용자 실화면(2026-11-08): 제출한 뒤 체크를 풀면 축하 카드 대신 남은 개수 ──
test('UNCHECK-1 제출 뒤 체크를 풀면 남은 개수로 돌아간다', async (b) => {
  const submitted = { done_lines: 4, total_lines: 4, submitted_at: '2026-10-31T05:00:00Z' };
  const { page, ctx } = await open(b, 'STAFF', '/staff', { overrides: { submitted } });
  await page.getByText('2개 남았어요').waitFor();
  assert.equal(await page.getByTestId('checklist-complete').count(), 0);
  await ctx.close();
});

// ── Task 2 카테고리 종류 ──
test('KIND-1 카테고리 줄에 종류가 보이고, 누르면 바꿀 수 있다', async (b) => {
  const { page, ctx, api } = await open(b, 'OWNER', '/owner/categories');
  const row = page.locator('[data-category]').filter({ hasText: '음료 레시피' });
  await row.getByRole('button', { name: '음료 레시피 종류 바꾸기, 지금 레시피' }).click();
  const sheet = page.getByRole('dialog', { name: "'음료 레시피'는 어떤 카드인가요?" });
  await sheet.getByRole('button', { name: '할 일', exact: true }).click();
  for (let i = 0; i < 40 && !api.calls.some((c) => c.method === 'PATCH'); i++) await page.waitForTimeout(50);
  assert.deepEqual(api.calls.find((c) => c.method === 'PATCH' && c.path === '/categories/10').body, { kind: 'TASK' });
  await row.getByRole('button', { name: '음료 레시피 종류 바꾸기, 지금 할 일' }).waitFor();
  await ctx.close();
});
test('KIND-2 종류가 할 일이면 이름이 레시피여도 근무조를 묻는다', async (b) => {
  const categories = [{ category_id: 10, name: '음료 레시피', is_system: false, sort_order: 1, kind: 'TASK' }, { category_id: 13, name: '기타', is_system: true, sort_order: 2, kind: null }];
  const { page, ctx } = await open(b, 'OWNER', '/owner/cards/2', { overrides: { categories } });
  await page.getByRole('group', { name: '어느 근무조 할 일인가요?' }).waitFor();
  await ctx.close();
});
test('KIND-3 종류가 정보면 근무조를 묻지 않는다', async (b) => {
  const categories = [{ category_id: 12, name: '재고 위치', is_system: false, sort_order: 1, kind: 'INFO' }, { category_id: 13, name: '기타', is_system: true, sort_order: 2, kind: null }];
  const { page, ctx } = await open(b, 'OWNER', '/owner/cards/6', { overrides: { categories } });
  await page.getByRole('heading', { name: '우유 발주' }).waitFor();
  await page.waitForTimeout(300);
  assert.equal(await page.getByText('어느 근무조 할 일인가요?').count(), 0);
  await ctx.close();
});

// ── Task 3 미공개 ──
test('UNPUB-1 공개 카드를 왼쪽으로 밀면 미공개, 되돌리기로 다시 공개', async (b) => {
  const { page, ctx, api } = await open(b, 'OWNER', '/owner/cards?status=approved');
  await page.getByRole('button', { name: '아메리카노 미공개' }).press('Enter');
  const bar = page.getByRole('status').filter({ hasText: '미공개로 바꿨어요' });
  await bar.waitFor();
  assert.ok(api.calls.some((c) => c.method === 'POST' && c.path === '/cards/2/unpublish'));
  await page.getByRole('link', { name: /^아메리카노/ }).waitFor({ state: 'detached' });
  await bar.getByRole('button', { name: '되돌리기' }).click();
  await page.getByRole('link', { name: /^아메리카노/ }).waitFor();
  assert.ok(api.calls.some((c) => c.method === 'POST' && c.path === '/cards/2/approve'));
  await ctx.close();
});
test('UNPUB-2 검수 필요 상세 아래는 공개와 미공개가 나란히', async (b) => {
  const { page, ctx, api } = await open(b, 'OWNER', '/owner/cards/3');
  const publish = page.getByRole('button', { name: '공개', exact: true });
  const unpublish = page.getByRole('button', { name: '미공개', exact: true });
  await unpublish.waitFor();
  const [a, c] = [await publish.boundingBox(), await unpublish.boundingBox()];
  assert.ok(Math.abs(a.y - c.y) < 4 && a.x < c.x, '같은 줄, 공개가 왼쪽');
  await unpublish.click();
  for (let i = 0; i < 40 && !api.calls.some((x) => x.path === '/cards/3/unpublish'); i++) await page.waitForTimeout(50);
  assert.ok(api.calls.some((x) => x.method === 'POST' && x.path === '/cards/3/unpublish'));
  await page.getByText('아직 공개 전이에요').waitFor();
  await ctx.close();
});

// ── Task 5 선택 모드 ──
const tile = (page, title) => page.locator('[data-card-tile]').filter({ hasText: title });
async function startSelect(page) {
  await page.getByRole('button', { name: '선택', exact: true }).click();
  await page.getByRole('toolbar', { name: '고른 카드 처리' }).waitFor();
}
test('SEL-1 선택을 누르면 밀기가 꺼지고 아래 동작 줄', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/cards');
  await startSelect(page);
  const bar = page.getByRole('toolbar', { name: '고른 카드 처리' });
  for (const name of ['이동', '공개', '미공개', '삭제']) assert.ok(await bar.getByRole('button', { name, exact: true }).isDisabled(), `${name} 은 고르기 전 꺼짐`);
  assert.equal(await page.getByRole('button', { name: /[^,] (공개|미공개|삭제)$/ }).count(), 0, '밀기 버튼 없음');
  assert.equal(await page.getByRole('navigation', { name: '주요 메뉴' }).count(), 0, '탭바 대신 동작 줄');
  await ctx.close();
});
test('SEL-2 하나씩 누르면 체크가 바뀌고 머리에 장 수', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/cards');
  await startSelect(page);
  await tile(page, '아메리카노').click();
  assert.equal(await tile(page, '아메리카노').getAttribute('aria-pressed'), 'true');
  await page.getByRole('heading', { name: '1장 선택' }).waitFor();
  await tile(page, '아메리카노').click();
  await page.getByRole('heading', { name: '카드 선택' }).waitFor();
  assert.equal(here(page), '/owner/cards', '상세로 가지 않는다');
  await ctx.close();
});
test('SEL-3 가로로 끌기 시작하면 지나간 카드가 골라진다', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/cards');
  await startSelect(page);
  await tile(page, '원두 보관 위치').evaluate((el) => el.scrollIntoView({ block: 'center' }));
  const from = await tile(page, '마감 머신 청소').boundingBox();
  const to = await tile(page, '원두 보관 위치').boundingBox();
  await page.mouse.move(from.x + 20, from.y + from.height / 2); await page.mouse.down();
  await page.mouse.move(from.x + 50, from.y + from.height / 2, { steps: 4 });
  await page.mouse.move(to.x + 50, to.y + to.height / 2, { steps: 12 });
  await page.mouse.up();
  for (const title of ['오픈 준비', '마감 머신 청소', '원두 보관 위치']) assert.equal(await tile(page, title).getAttribute('aria-pressed'), 'true', title);
  assert.equal(await tile(page, '바닐라 라떼').getAttribute('aria-pressed'), 'false');
  await ctx.close();
});
test('SEL-4 전체 선택은 보이는 카드 모두, 한 번 더 누르면 해제', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/cards?status=pending');
  await startSelect(page);
  await page.getByRole('button', { name: '전체 선택' }).click();
  await page.getByRole('heading', { name: '2장 선택' }).waitFor();
  await page.getByRole('button', { name: '전체 해제' }).click();
  await page.getByRole('heading', { name: '카드 선택' }).waitFor();
  await ctx.close();
});
test('SEL-5 일괄 공개가 일부 실패하면 실패한 카드만 남는다', async (b) => {
  const { page, ctx, api } = await open(b, 'OWNER', '/owner/cards?status=pending', { overrides: { failBulkIds: [5] } });
  await startSelect(page);
  await page.getByRole('button', { name: '전체 선택' }).click();
  await page.getByRole('toolbar', { name: '고른 카드 처리' }).getByRole('button', { name: '공개', exact: true }).click();
  await page.getByRole('alert').getByText('1장은 공개하지 못했어요', { exact: false }).waitFor();
  assert.deepEqual(api.calls.find((c) => c.path === '/cards/bulk').body, { action: 'approve', card_ids: [4, 5] });
  await page.getByRole('heading', { name: '1장 선택' }).waitFor();
  assert.equal(await tile(page, '원두 보관 위치').getAttribute('aria-pressed'), 'true');
  await ctx.close();
});
test('SEL-6 일괄 삭제 뒤 되돌리기로 모두 돌아온다', async (b) => {
  const { page, ctx, api } = await open(b, 'OWNER', '/owner/cards?status=pending');
  await startSelect(page);
  await page.getByRole('button', { name: '전체 선택' }).click();
  await page.getByRole('toolbar', { name: '고른 카드 처리' }).getByRole('button', { name: '삭제', exact: true }).click();
  const bar = page.getByRole('status').filter({ hasText: '2장 삭제했어요' });
  await bar.waitFor();
  await tile(page, '오픈 준비').waitFor({ state: 'detached' });
  await bar.getByRole('button', { name: '되돌리기' }).click();
  await tile(page, '오픈 준비').waitFor();
  assert.deepEqual(api.calls.filter((c) => c.path === '/cards/bulk').map((c) => c.body.action), ['exclude', 'restore']);
  await ctx.close();
});
test('SEL-7 이동은 카테고리 시트에서 고르고 선택 모드를 닫는다', async (b) => {
  const { page, ctx, api } = await open(b, 'OWNER', '/owner/cards');
  await startSelect(page);
  await tile(page, '오픈 준비').click();
  await page.getByRole('toolbar', { name: '고른 카드 처리' }).getByRole('button', { name: '이동', exact: true }).click();
  await page.getByRole('dialog', { name: '어디로 옮길까요?' }).getByRole('button', { name: '재고 위치' }).click();
  await page.getByRole('button', { name: '선택', exact: true }).waitFor();
  assert.deepEqual(api.calls.find((c) => c.path === '/cards/bulk').body, { action: 'move', card_ids: [4], category_id: 12 });
  await ctx.close();
});

// ── Task 6 들어가자마자 고르는 검수 ──
test("PICK-1 검수 필요 카드를 열면 '맞는 것을 골라 주세요!'와 두 값 버튼", async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/cards/3', { overrides: { pickCard: true } });
  const box = page.getByRole('group', { name: '맞는 것을 골라 주세요!' });
  await box.waitFor();
  await box.getByRole('button', { name: '일반휘핑(30g)' }).waitFor();
  await box.getByRole('button', { name: '일반휘핑(90g)' }).waitFor();
  assert.equal(await page.getByRole('button', { name: '수정 완료' }).count(), 0, '수정하기 없이');
  // 고르는 상자가 카드 내용보다 위
  const [boxTop, contentTop] = [(await box.boundingBox()).y, (await page.locator('[data-recipe-view]').boundingBox()).y];
  assert.ok(boxTop < contentTop);
  // 고르기 전에는 내용에 어느 한 값을 보이지 않고, 공개도 막는다
  await page.locator('[data-recipe-view]').getByText('골라 주세요').waitFor();
  assert.equal(await page.locator('[data-recipe-view]').getByText('30g').count(), 0);
  assert.ok(await page.getByRole('button', { name: '공개', exact: true }).isDisabled());
  await ctx.close();
});
test('PICK-2 하나를 누르면 그 값만 남고 상자가 사라진다', async (b) => {
  const { page, ctx, api } = await open(b, 'OWNER', '/owner/cards/3', { overrides: { pickCard: true } });
  await page.getByRole('group', { name: '맞는 것을 골라 주세요!' }).getByRole('button', { name: '일반휘핑(30g)' }).click();
  await page.getByRole('group', { name: '맞는 것을 골라 주세요!' }).waitFor({ state: 'detached' });
  const call = api.calls.find((c) => c.path === '/cards/3/conflicts/7/choose');
  assert.equal(call.body.keep_fact_id, 32);
  assert.equal(call.body.expected_version_id, 30);
  assert.equal(await page.locator('[data-recipe-view]').getByText('90g').count(), 0);
  await page.getByText('아직 공개 전이에요').waitFor();
  await ctx.close();
});
test('PICK-4 저장이 실패하면 버튼이 다시 눌리고 이유가 상자 안에', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/cards/3', { overrides: { pickCard: true, failPick: true } });
  const box = page.getByRole('group', { name: '맞는 것을 골라 주세요!' });
  await box.getByRole('button', { name: '일반휘핑(30g)' }).click();
  await box.getByRole('alert').getByText('그사이 카드가 바뀌었어요', { exact: false }).waitFor();
  assert.equal(await box.getByRole('button', { name: '일반휘핑(90g)' }).isDisabled(), false);
  await ctx.close();
});

run();
