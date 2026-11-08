// 계획 7(UI_REDESIGN_PLAN7_BULK_REVIEW_20261108) 화면 회귀. 합성 API(ui_fixture.cjs)만 쓴다.
// 실행: next start -p 3011 을 띄운 뒤 NODE_PATH=<playwright> node api/scripts/verify_ui_plan7.cjs [이름 앞부분]
const assert = require('node:assert/strict');
const { createSuite, open, to, here } = require('./ui_harness.cjs');
const { test, run } = createSuite('ui-plan7');

// ── 사용자 실화면(2026-11-08): 제출한 뒤 체크를 풀면 축하 카드 대신 남은 개수 ──
test('UNCHECK-1 제출 뒤 체크를 풀면 끝 카드의 숫자도 지금 체크 수', async (b) => {
  // 제출 기록은 4/4 였지만 지금 체크는 2/4. 끝 카드는 지금 수를 보인다(서버도 제출 기록 수를 맞춘다)
  const submitted = { done_lines: 4, total_lines: 4, submitted_at: '2026-10-31T05:00:00Z' };
  const { page, ctx } = await open(b, 'STAFF', '/staff', { overrides: { submitted } });
  await page.getByTestId('checklist-complete').waitFor();
  await page.getByText('체크 2/4개 제출했어요').waitFor();
  assert.equal(await page.getByText('체크 4/4개 제출했어요').count(), 0);
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

// ── Task 7 수정 되돌리기 ──
async function editAndSave(page) {
  await page.getByRole('button', { name: '수정하기' }).click();
  await page.getByRole('button', { name: '3번 물을 붓는다. 옮기기', exact: true }).press('ArrowUp');
  await page.getByRole('button', { name: '수정 완료' }).click();
}
test("UNDO-1 수정 완료 알림의 '되돌리기'를 누르면 되돌린다", async (b) => {
  const { page, ctx, api } = await open(b, 'OWNER', '/owner/cards/1');
  await editAndSave(page);
  const bar = page.getByRole('status').filter({ hasText: '수정했어요' });
  await bar.getByRole('button', { name: '되돌리기' }).click();
  for (let i = 0; i < 40 && !api.calls.some((c) => /\/revert$/.test(c.path)); i++) await page.waitForTimeout(50);
  const call = api.calls.find((c) => /\/revert$/.test(c.path));
  assert.equal(call.path, '/cards/1/facts/edits/11/revert');
  await page.getByRole('status').getByText('되돌렸어요').waitFor();
  await ctx.close();
});
test('UNDO-2 되돌리기가 실패하면 이유를 알린다', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/cards/1', { overrides: { failRevert: true } });
  await editAndSave(page);
  await page.getByRole('status').filter({ hasText: '수정했어요' }).getByRole('button', { name: '되돌리기' }).click();
  await page.getByRole('status').getByText('그사이 카드가 바뀌어 되돌릴 수 없어요', { exact: false }).waitFor();
  await ctx.close();
});

// ── Task 8 지난 대화 ──
const pastChats = { sessions: [{ session_id: '2', title: '우유 발주 언제 해요?', last_at: '2026-10-31T05:00:00Z' }, { session_id: '1', title: '바닐라 시럽 몇 펌프예요?', last_at: '2026-10-30T05:00:00Z' }], messages: [] };
test("CHAT-1 머리의 '지난 대화'를 누르면 목록, 검색으로 걸러진다", async (b) => {
  const { page, ctx } = await open(b, 'STAFF', '/staff/ask', { overrides: pastChats });
  await page.getByRole('button', { name: '지난 대화' }).click();
  const sheet = page.getByRole('dialog', { name: '지난 대화' });
  await sheet.getByRole('link', { name: /우유 발주 언제 해요\?/ }).waitFor();
  await sheet.getByRole('searchbox', { name: '지난 대화 찾기' }).fill('바닐라');
  await sheet.getByRole('link', { name: /우유 발주/ }).waitFor({ state: 'detached' });
  await sheet.getByRole('link', { name: /바닐라 시럽/ }).waitFor();
  await ctx.close();
});
test('CHAT-2 목록에서 고르면 그 대화가 열린다', async (b) => {
  const { page, ctx } = await open(b, 'STAFF', '/staff/ask', { overrides: pastChats });
  await page.getByRole('button', { name: '지난 대화' }).click();
  await page.getByRole('dialog', { name: '지난 대화' }).getByRole('link', { name: /바닐라 시럽/ }).click();
  await to(page, '/staff/ask?session_id=1');
  await ctx.close();
});
test("CHAT-3 '새 대화'는 목록 안 작은 글자, 누르면 빈 대화", async (b) => {
  const { page, ctx } = await open(b, 'STAFF', '/staff/ask?session_id=2', { overrides: pastChats });
  assert.equal(await page.getByRole('button', { name: '새 대화' }).count(), 0, '목록 밖에는 없다');
  await page.getByRole('button', { name: '지난 대화' }).click();
  const fresh = page.getByRole('dialog', { name: '지난 대화' }).getByRole('link', { name: '새 대화' });
  assert.ok(parseFloat(await fresh.evaluate((el) => getComputedStyle(el).fontSize)) <= 14);
  await fresh.click();
  await to(page, '/staff/ask?new=1');
  await ctx.close();
});
test('CHAT-4 옛 대화 주소는 버디로', async (b) => {
  const { page, ctx } = await open(b, 'STAFF', '/staff/chat');
  await to(page, '/staff/ask');
  await ctx.close();
});

// ── Task 9 작은 기능 ──
test('NAME-1 설정 연필로 이름과 매장 이름을 고친다', async (b) => {
  const { page, ctx, api } = await open(b, 'OWNER', '/owner/settings');
  await page.getByRole('button', { name: '내 이름 고치기' }).click();
  const sheet = page.getByRole('dialog', { name: '내 이름 고치기' });
  await sheet.getByRole('textbox', { name: '이름' }).fill('김사장님');
  await sheet.getByRole('button', { name: '저장' }).click();
  await sheet.waitFor({ state: 'detached' });
  assert.deepEqual(api.calls.find((c) => c.method === 'PATCH' && c.path === '/app/me').body, { name: '김사장님' });
  await page.getByText('김사장님').first().waitFor();
  await page.getByRole('button', { name: '매장 이름 고치기' }).click();
  await page.getByRole('dialog', { name: '매장 이름 고치기' }).getByRole('textbox', { name: '이름' }).fill('버디 카페 2호점');
  await page.getByRole('dialog', { name: '매장 이름 고치기' }).getByRole('button', { name: '저장' }).click();
  await page.getByText('버디 카페 2호점').first().waitFor();
  await ctx.close();
});
test('NAME-2 알바생은 매장 이름 연필이 없다', async (b) => {
  const { page, ctx } = await open(b, 'STAFF', '/staff/settings');
  await page.getByRole('button', { name: '내 이름 고치기' }).waitFor();
  assert.equal(await page.getByRole('button', { name: '매장 이름 고치기' }).count(), 0);
  await ctx.close();
});
test("JOIN-1 합류 승인 뒤 스낵바 '되돌리기'", async (b) => {
  const { page, ctx, api } = await open(b, 'OWNER', '/owner/members');
  await page.getByRole('button', { name: '승인' }).click();
  const bar = page.getByRole('status').filter({ hasText: '이서연님이 합류했어요' });
  await bar.getByRole('button', { name: '되돌리기' }).click();
  for (let i = 0; i < 40 && !api.calls.some((c) => c.path === '/members/requests/9/undo-approve'); i++) await page.waitForTimeout(50);
  assert.ok(api.calls.some((c) => c.method === 'POST' && c.path === '/members/requests/9/undo-approve'));
  await page.getByRole('button', { name: '승인' }).waitFor();
  await ctx.close();
});
test('CAT-1 카테고리를 끌어서(키보드) 순서를 바꾼다', async (b) => {
  const { page, ctx, api } = await open(b, 'OWNER', '/owner/categories');
  await page.getByRole('button', { name: '음료 레시피 옮기기' }).press('ArrowDown');
  for (let i = 0; i < 40 && !api.calls.some((c) => c.path === '/categories/order'); i++) await page.waitForTimeout(50);
  assert.deepEqual(api.calls.find((c) => c.method === 'PUT' && c.path === '/categories/order').body, { ids: [11, 10, 12, 13] });
  await ctx.close();
});
test('CAT-2 카테고리 이름을 누르면 고치는 시트', async (b) => {
  const { page, ctx, api } = await open(b, 'OWNER', '/owner/categories');
  await page.getByRole('button', { name: '오픈 마감 이름 고치기' }).click();
  const sheet = page.getByRole('dialog', { name: '카테고리 이름 고치기' });
  await sheet.getByRole('textbox', { name: '이름' }).fill('마감 청소');
  await sheet.getByRole('button', { name: '저장' }).click();
  await sheet.waitFor({ state: 'detached' });
  assert.deepEqual(api.calls.find((c) => c.method === 'PATCH' && c.path === '/categories/11').body, { name: '마감 청소' });
  await page.locator('[data-category]').filter({ hasText: '마감 청소' }).waitFor();
  assert.equal(await page.getByRole('button', { name: '기타 이름 고치기' }).count(), 0, '기타는 못 고친다');
  await ctx.close();
});

// ── Task 10 직원 화면 ──
test("OTHER-1 '다른 근무조 할 일 보기'를 펼치면 다른 근무조 할 일", async (b) => {
  const otherGroups = [{ shift_id: 3, name: '마감', cards: [{ card_id: 9, title: '마감 정산', item_id: null }] }];
  const { page, ctx } = await open(b, 'STAFF', '/staff', { overrides: { otherGroups } });
  const toggle = page.getByRole('button', { name: '다른 근무조 할 일 보기' });
  assert.equal(await toggle.getAttribute('aria-expanded'), 'false');
  assert.equal(await page.getByText('마감 정산').count(), 0);
  await toggle.click();
  await page.getByText('마감 정산').waitFor();
  assert.equal(await page.getByRole('checkbox', { name: /마감 정산/ }).count(), 0, '읽기만');
  await ctx.close();
});
test('CHIP-1 오늘 할 일의 추천 칩은 누르면 바로 보낸다', async (b) => {
  const { page, ctx, api } = await open(b, 'STAFF', '/staff');
  await page.locator('[data-suggested]', { hasText: '바닐라 라떼 시럽 몇 펌프예요?' }).click();
  await page.waitForURL(/\/staff\/ask/);
  for (let i = 0; i < 60 && !api.calls.some((c) => c.path === '/learn/v2/chat'); i++) await page.waitForTimeout(50);
  assert.equal(api.calls.find((c) => c.path === '/learn/v2/chat')?.body.question, '바닐라 라떼 시럽 몇 펌프예요?');
  await page.getByText('ICE 바닐라 라떼는 바닐라 시럽 2펌프예요.').waitFor();
  await ctx.close();
});
test("DOT-1 새 답이 온 대화를 열면 '새 답' 알림을 읽음으로", async (b) => {
  const { page, ctx, api } = await open(b, 'STAFF', '/staff/ask?session_id=1', { overrides: { sessions: [{ session_id: '1' }] } });
  for (let i = 0; i < 60 && !api.calls.some((c) => c.path === '/learn/v2/notifications/51/read'); i++) await page.waitForTimeout(50);
  assert.ok(api.calls.some((c) => c.method === 'POST' && c.path === '/learn/v2/notifications/51/read'));
  await ctx.close();
});

test('OLD-1 합류 대기 화면은 새 부품(버튼·제목 크기)', async (b) => {
  const { page, ctx } = await open(b, 'STAFF', '/staff/pending', { overrides: { noStore: true } });
  const title = page.getByRole('heading', { name: '사장님 승인을 기다리고 있어요' });
  await title.waitFor();
  assert.equal(await title.evaluate((el) => getComputedStyle(el).fontSize), '26px');
  assert.equal(await page.getByRole('button', { name: '승인되면 알림 받기' }).getAttribute('data-variant'), 'primary');
  await ctx.close();
});
test('OLD-2 합류 대기 상태를 못 불러오면 오류 줄과 다시 시도', async (b) => {
  const { page, ctx } = await open(b, 'STAFF', '/staff/pending', { overrides: { noStore: true, failJoinStatus: 9 } });
  // 503 은 공용 문구로 바뀐다. 오류 줄과 다시 시도 버튼이 보이면 된다
  await page.getByText('서비스가 잠시 지연되고 있습니다', { exact: false }).waitFor({ timeout: 15000 });
  await page.getByRole('button', { name: '다시 시도' }).waitFor();
  await ctx.close();
});

// ── Task 11 작은 결정 ──
test('EDIT-1 수정 모드에서 같은 문장에서 나온 줄은 한 덩어리', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/cards/3', { overrides: { pickCard: true } });
  await page.getByRole('button', { name: '수정하기' }).click();
  await page.getByRole('button', { name: '수정 완료' }).waitFor();
  // 제조순서 한 문장에서 나온 세 줄: 두 번째·세 번째 줄이 앞 줄에 붙는다
  assert.equal(await page.locator('[data-same-sentence]').count(), 2);
  await ctx.close();
});

test('CAT-3 카테고리 줄은 밀기가 없고 오른쪽 휴지통', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/categories');
  const row = page.locator('[data-category]').filter({ hasText: '재고 위치' });
  const trash = row.getByRole('button', { name: '재고 위치 지우기' });
  await trash.waitFor();
  const [rowBox, trashBox] = [await row.boundingBox(), await trash.boundingBox()];
  assert.ok(trashBox.x > rowBox.x + rowBox.width * 0.7, '오른쪽 끝');
  assert.ok(await trash.isVisible(), '밀지 않아도 보인다');
  await ctx.close();
});

// ── Task 12 ──
test("HEAD-1 보기 모드에 '수치·순서·목록' 머리글이 없다(규격 머리글만)", async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/cards/1');
  await page.getByRole('heading', { name: 'ICE', exact: true }).waitFor();
  for (const name of ['수치', '순서', '목록']) assert.equal(await page.getByRole('heading', { name, exact: true }).count(), 0, name);
  await ctx.close();
});

test('RECIPE-1 직원 레시피도 한눈에 보기(가격은 제목 옆, HOT/ICE 따로)', async (b) => {
  const { page, ctx } = await open(b, 'STAFF', '/staff/recipes/11', { overrides: { staffTableRecipe: true } });
  const view = page.locator('[data-recipe-view]');
  await view.waitFor();
  await view.getByText('바닐라시럽 30ml', { exact: false }).waitFor();
  await page.getByText('4,500원').waitFor();
  for (const h of ['HOT', 'ICE']) await view.getByRole('heading', { name: h, exact: true }).waitFor();
  await ctx.close();
});
test('RECIPE-2 사실 묶음이 없는 레시피는 예전 본문 그대로', async (b) => {
  const { page, ctx } = await open(b, 'STAFF', '/staff/recipes/11');
  await page.getByText('바닐라 시럽 2펌프', { exact: false }).first().waitFor();
  assert.equal(await page.locator('[data-recipe-view]').count(), 0);
  await ctx.close();
});

// ── 사용자 실화면 문제(2026-11-08) ──
test('ERR-1 실패 이유가 개발자용 예외 문장이면 쉬운 말로', async (b) => {
  const job = { status: 'FAILED', sources: [{ source_id: 31, filename: 'input.txt', status: 'FAILED', card_count: 0, source_availability: 'AVAILABLE',
    error: { code: 'EXTRACTION_FAILED', message: "RuntimeError: 카카오톡 대화를 한 건도 파싱하지 못했다. '대화 내용 내보내기' 로 받은 txt 인지 확인하라" } }] };
  const { page, ctx } = await open(b, 'OWNER', '/owner/jobs/7', { overrides: { job } });
  await page.getByText('이 자료를 읽지 못했어요. 다시 시도하거나 다른 형식으로 올려 주세요.').first().waitFor();
  assert.equal(await page.getByText(/RuntimeError|확인하라/).count(), 0);
  await ctx.close();
});

test('CANCEL-1 정리 중 화면에서 취소하면 확인 창 뒤 취소, 빈 자리 상자 없음', async (b) => {
  const { page, ctx, api } = await open(b, 'OWNER', '/owner/jobs/7', { overrides: { job: { status: 'EXTRACTING' } } });
  await page.getByRole('heading', { name: '정리하고 있어요' }).waitFor();
  assert.equal(await page.locator('main [data-skeleton], main .animate-pulse').count(), 0, '끝나지 않는 빈 상자 없음');
  await page.getByRole('button', { name: '정리 취소' }).click();
  await page.getByRole('dialog', { name: '정리를 취소할까요?' }).getByRole('button', { name: '취소하기' }).click();
  await page.getByRole('heading', { name: '처리하지 못했어요' }).waitFor();
  assert.ok(api.calls.some((c) => c.method === 'POST' && c.path === '/ingest/jobs/7/cancel'));
  await page.getByText('정리를 취소했어요.').first().waitFor();
  await ctx.close();
});

test("META-1 질문 카드에 '한 번 답하면…' 문구가 없다", async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner');
  await page.getByText('디카페인 원두는 어디 있어요?').first().waitFor();
  assert.equal(await page.getByText('한 번 답하면', { exact: false }).count(), 0);
  await ctx.close();
});
test("HINT-1 '이건 어떤 자료인가요?' 칩은 글이나 파일을 넣었을 때만", async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/add');
  await page.getByLabel('새로 알려줄 것').waitFor();
  assert.equal(await page.getByRole('group', { name: '자료 종류' }).count(), 0, '처음엔 없다');
  await page.getByLabel('새로 알려줄 것').fill('우유는 월목 발주');
  await page.getByRole('group', { name: '자료 종류' }).waitFor();
  await page.getByLabel('새로 알려줄 것').fill('');
  await page.getByRole('group', { name: '자료 종류' }).waitFor({ state: 'detached' });
  await ctx.close();
});

run();
