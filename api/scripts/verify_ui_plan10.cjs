// 계획 10(카드 줄 보기·타일 수정·직원 같은 보기·대기 화면 로그아웃·선택 자동 스크롤). 합성 API(ui_fixture.cjs)만 쓴다.
// 실행: next start -p 3011 을 띄운 뒤 NODE_PATH=<playwright> node api/scripts/verify_ui_plan10.cjs [이름 앞부분]
const assert = require('node:assert/strict');
const { createSuite, open } = require('./ui_harness.cjs');
const { test, run } = createSuite('ui-plan10');

// ── Task 8 보기는 어디서나 하나 ──
test('VIEW-1 사장님 상세: 구역 제목과 줄, 화살표 단계', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/cards/1', { overrides: { lineCard: 'short' } });
  await page.getByRole('heading', { name: 'HOT' }).waitFor();
  assert.equal(await page.locator('[data-layout="ARROW"] [data-line]').count(), 3);
  assert.equal(await page.getByText('수치').count(), 0);
  await ctx.close();
});
test('VIEW-2 긴 단계는 번호 목록, 보관은 목록', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/cards/1', { overrides: { lineCard: 'long' } });
  await page.locator('[data-layout="NUMBERED"]').waitFor();
  await page.getByRole('heading', { name: '보관' }).waitFor();
  assert.equal(await page.locator('[data-layout="LIST"] [data-line]').count(), 1);
  await ctx.close();
});
test('VIEW-3 줄 없는 옛 카드도 같은 보기', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/cards/1', { overrides: { lineCard: 'legacy' } });
  await page.locator('[data-line]').first().waitFor();
  assert.deepEqual(await page.locator('[data-line]').allTextContents(), ['샷=2', '얼음=가득']);
  await ctx.close();
});
test('VIEW-4 직원 레시피도 같은 보기', async (b) => {
  const { page, ctx } = await open(b, 'STAFF', '/staff/recipes/11', { overrides: { lineCard: 'short' } });
  await page.locator('[data-layout="ARROW"]').waitFor();
  assert.deepEqual(await page.locator('[data-line]').allTextContents(), ['2샷', '얼음 가득', '물 붓기']);
  await ctx.close();
});

// ── 2026-11-18 금액은 제목 오른쪽(예전처럼) ──
test('PRICE-1 사장님 상세: 금액 줄은 본문에서 빠지고 제목 오른쪽에', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/cards/1', { overrides: { lineCard: 'price' } });
  const price = page.locator('[data-price]');
  await price.waitFor();
  assert.deepEqual(await price.locator('span').allTextContents(), ['HOT 1,500원', 'ICE 2,000원']);
  assert.deepEqual(await page.locator('[data-line]').allTextContents(), ['물 180ml']);
  // 같은 줄(제목 행) 오른쪽 끝
  const title = await page.getByRole('heading', { level: 1 }).boundingBox();
  const box = await price.boundingBox();
  assert.ok(box.x > title.x + title.width - 1, '제목 오른쪽');
  assert.ok(box.y < title.y + title.height, '제목과 같은 행');
  // 금액 때문에 제목이 꺾이지 않는다(한 줄 높이)
  assert.ok(title.height < 50, `제목 높이 ${title.height}`);
  // 금액만 있던 ICE 구역은 사라진다
  assert.equal(await page.getByRole('heading', { name: 'ICE' }).count(), 0);
  await ctx.close();
});
test('PRICE-2 고치는 동안은 금액이 제목 옆에서 빠지고 타일로 남는다', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/cards/1', { overrides: { lineCard: 'price' } });
  await page.locator('[data-price]').waitFor();
  await page.getByRole('button', { name: '수정하기' }).click();
  await page.locator('[data-tile]').first().waitFor();
  assert.equal(await page.locator('[data-price]').count(), 0);
  assert.equal(await page.locator('[data-tile]').filter({ hasText: '금액 1,500원' }).count(), 1);
  await ctx.close();
});
test('PRICE-3 직원 레시피도 같은 자리·같은 모양', async (b) => {
  const owner = await open(b, 'OWNER', '/owner/cards/1', { overrides: { lineCard: 'price' } });
  await owner.page.locator('[data-price]').waitFor();
  const ownerClass = await owner.page.locator('[data-price]').getAttribute('class');
  await owner.ctx.close();
  const { page, ctx } = await open(b, 'STAFF', '/staff/recipes/11', { overrides: { lineCard: 'price' } });
  const price = page.locator('[data-price]');
  await price.waitFor();
  assert.deepEqual(await price.locator('span').allTextContents(), ['HOT 1,500원', 'ICE 2,000원']);
  assert.equal(await price.getAttribute('class'), ownerClass);
  assert.deepEqual(await page.locator('[data-line]').allTextContents(), ['물 180ml']);
  await ctx.close();
});

// ── Task 8b 직원 레시피 목록·카드도 사장님과 똑같이 ──
test('STAFF-LIST-1 직원 레시피 목록은 사장님 카드 목록과 같은 구역·격자', async (b) => {
  const { page, ctx } = await open(b, 'STAFF', '/staff/recipes');
  const section = page.getByRole('region', { name: '음료 레시피' });
  await section.getByRole('heading', { name: '음료 레시피' }).waitFor();
  assert.match(await section.locator('h2').getAttribute('class'), /border-b-2 border-ink/);
  assert.match(await section.locator('> div').getAttribute('class'), /grid-cols-2/);
  assert.equal(await page.locator('main li').count(), 0, 'ListRow 목록이 아니다');
  await ctx.close();
});
test('STAFF-LIST-2 같은 부품: 사장님 구역 머리와 직원 구역 머리의 class 가 같다', async (b) => {
  const owner = await open(b, 'OWNER', '/owner/cards?status=approved');
  const ownerClass = await owner.page.getByRole('heading', { name: '음료 레시피' }).getAttribute('class');
  await owner.ctx.close();
  const staff = await open(b, 'STAFF', '/staff/recipes');
  assert.equal(await staff.page.getByRole('heading', { name: '음료 레시피' }).getAttribute('class'), ownerClass);
  await staff.ctx.close();
});
test('STAFF-LIST-3 직원 타일에는 밀기·선택이 없고 누르면 직원 레시피로', async (b) => {
  const { page, ctx } = await open(b, 'STAFF', '/staff/recipes');
  assert.equal(await page.getByRole('button', { name: /삭제$|미공개$|공개$/ }).count(), 0);
  assert.equal(await page.getByRole('button', { name: '선택' }).count(), 0);
  await page.locator('[data-card-tile]').filter({ hasText: '바닐라 라떼' }).click();
  await page.waitForURL((u) => u.pathname === '/staff/recipes/11');
  await ctx.close();
});
test('STAFF-CARD-1 직원 카드 상세는 사장님 상세와 같은 보기, 수치·순서·목록 머리와 근거 줄이 없다', async (b) => {
  const { page, ctx } = await open(b, 'STAFF', '/staff/recipes/11', { overrides: { lineCard: 'long' } });
  await page.locator('[data-layout="NUMBERED"]').waitFor();
  for (const old of ['수치', '순서', '목록']) assert.equal(await page.getByRole('heading', { name: old, exact: true }).count(), 0, old);
  assert.equal(await page.getByText(/^근거:/).count(), 0);
  await page.getByRole('button', { name: '확인했어요' }).waitFor();   // 직원 동작은 그대로
  await ctx.close();
});
test('STAFF-CARD-2 줄 없는 옛 공개 카드도 같은 보기', async (b) => {
  const { page, ctx } = await open(b, 'STAFF', '/staff/recipes/11', { overrides: { lineCard: 'legacy' } });
  await page.locator('[data-line]').first().waitFor();
  assert.equal(await page.getByRole('heading', { name: '수치', exact: true }).count(), 0);
  await ctx.close();
});

// ── Task 10 알바생 대기 화면 로그아웃, 알림 실패 이유 ──
test('WAIT-1 대기 화면에서 로그아웃', async (b) => {
  const { page, ctx, api } = await open(b, 'STAFF', '/staff/pending', { overrides: { noStore: true } });
  await page.getByRole('button', { name: '로그아웃' }).click();
  await page.getByRole('dialog', { name: '로그아웃할까요?' }).getByRole('button', { name: '로그아웃' }).click();
  await page.waitForURL((u) => u.pathname === '/');
  assert.ok(api.calls.some((c) => c.path === '/auth/logout'));
  await ctx.close();
});
test('WAIT-2 알림 실패는 이유를 보인다', async (b) => {
  const { page, ctx } = await open(b, 'STAFF', '/staff/pending', { overrides: { noStore: true, pushEnv: { permission: 'granted' }, failMySubscription: true } });
  await page.getByRole('button', { name: '승인되면 알림 받기' }).click();
  await page.getByText('알림 설정에 실패했어요.').waitFor();
  await page.getByText('구독 저장 실패').waitFor();   // fixture 가 돌려준 서버 문구
  await ctx.close();
});

// ── Task 11 선택 모드 자동 스크롤 ──
test('BL-1 선택 모드에서 아래 가장자리로 끌면 저절로 스크롤하고 계속 고른다', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/cards?status=all', { overrides: { manyCards: 40 } });
  await page.getByRole('button', { name: '선택' }).click();
  const first = await page.locator('[data-card-tile]').first().boundingBox();
  const vh = page.viewportSize().height;
  await page.mouse.move(first.x + 20, first.y + 20); await page.mouse.down();
  // 가로로 먼저 움직여 '고르기 끌기'로 정한 뒤(세로 먼저면 스크롤) 아래 가장자리로
  await page.mouse.move(first.x + 60, first.y + 22, { steps: 4 });
  await page.mouse.move(first.x + 60, vh - 4, { steps: 10 });
  await page.waitForTimeout(800);
  assert.ok(await page.evaluate(() => document.querySelector('main').scrollTop) > 0);
  await page.mouse.up();
  assert.ok(await page.locator('[data-card-tile][aria-pressed="true"]').count() > 8);
  await ctx.close();
});

// ── Task 9 수정은 타일 끌기(모션 A: 따라오고 비켜서기) ──
test('TILE-1 끌어서 단계 순서를 바꾸고 저장', async (b) => {
  const { page, ctx, api } = await open(b, 'OWNER', '/owner/cards/1', { overrides: { lineCard: 'short' } });
  await page.getByRole('button', { name: '수정하기' }).click();
  const tiles = page.locator('[data-tile]');
  const from = await tiles.nth(2).boundingBox(), to = await tiles.nth(0).boundingBox();
  await page.mouse.move(from.x + 10, from.y + 10); await page.mouse.down();
  await page.mouse.move(to.x + 5, to.y + 10, { steps: 12 }); await page.mouse.up();
  assert.deepEqual(await tiles.allTextContents(), ['물 붓기', '2샷', '얼음 가득']);
  await page.getByRole('button', { name: '수정 완료' }).click();
  await page.getByRole('button', { name: '수정하기' }).waitFor();
  const body = api.calls.find((c) => c.method === 'PUT' && c.path === '/cards/1/facts').body;
  assert.deepEqual(body.blocks[0].lines.map((l) => l.text), ['물 붓기', '2샷', '얼음 가득']);
  assert.equal(body.blocks[0].heading, 'HOT');
  await ctx.close();
});
test('TILE-2 키보드로도 옮긴다', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/cards/1', { overrides: { lineCard: 'short' } });
  await page.getByRole('button', { name: '수정하기' }).click();
  await page.getByRole('button', { name: '물 붓기 옮기기' }).focus();
  await page.keyboard.press('ArrowLeft');
  assert.equal((await page.locator('[data-tile]').allTextContents())[1], '물 붓기');
  await ctx.close();
});
test('TILE-3 화면 밖에서 놓으면 그대로', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/cards/1', { overrides: { lineCard: 'short' } });
  await page.getByRole('button', { name: '수정하기' }).click();
  const before = await page.locator('[data-tile]').allTextContents();
  const box = await page.locator('[data-tile]').nth(0).boundingBox();
  await page.mouse.move(box.x + 5, box.y + 5); await page.mouse.down();
  await page.mouse.move(-50, -50, { steps: 8 }); await page.mouse.up();
  assert.deepEqual(await page.locator('[data-tile]').allTextContents(), before);
  await ctx.close();
});
test('TILE-4 줄을 눌러 글을 고치면 다시 분석해 저장', async (b) => {
  const { page, ctx, api } = await open(b, 'OWNER', '/owner/cards/1', { overrides: { lineCard: 'short' } });
  await page.getByRole('button', { name: '수정하기' }).click();
  await page.locator('[data-tile]').nth(0).click();
  const sheet = page.getByRole('dialog', { name: '이 줄 고치기' });
  await sheet.getByRole('textbox').fill('3샷');
  await sheet.getByRole('button', { name: '바꾸기' }).click();
  await page.getByRole('button', { name: '수정 완료' }).click();
  await page.getByRole('button', { name: '수정하기' }).waitFor();
  assert.ok(api.calls.some((c) => c.path === '/cards/1/facts/parse' && c.body.text === '3샷'));
  const body = api.calls.find((c) => c.method === 'PUT' && c.path === '/cards/1/facts').body;
  assert.equal(body.blocks[0].lines[0].text, '3샷');
  assert.equal(body.blocks[0].items[0].op, 'MODIFY');
  await ctx.close();
});
test('TILE-5 모션 줄이기 설정이면 옮김 모션이 없다', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/cards/1', { overrides: { lineCard: 'short' } });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.getByRole('button', { name: '수정하기' }).click();
  const d = await page.locator('[data-tile]').first().evaluate((el) => getComputedStyle(el).transitionDuration);
  // 전역 동작 줄이기 규칙(globals.css)이 0.01ms 로 덮는다. 사실상 0
  assert.ok(parseFloat(d) <= 0.00001, d);
  await ctx.close();
});
test('TILE-6 모션이 켜져 있으면 타일이 220ms 로 미끄러진다', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/cards/1', { overrides: { lineCard: 'short' } });
  await page.getByRole('button', { name: '수정하기' }).click();
  const d = await page.locator('[data-tile]').first().evaluate((el) => getComputedStyle(el).transitionDuration);
  assert.match(d, /0\.22s/);
  await ctx.close();
});
test('LAY-10 360·390 폭에서 수정 화면이 가로로 넘치지 않는다', async (b) => {
  for (const width of [360, 390]) {
    const { page, ctx } = await open(b, 'OWNER', '/owner/cards/1', { viewport: { width, height: 800 }, overrides: { lineCard: 'long' } });
    await page.getByRole('button', { name: '수정하기' }).click();
    await page.locator('[data-tile]').first().waitFor();
    const over = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    assert.ok(over <= 0, `${width}px 에서 ${over}px 넘침`);
    await ctx.close();
  }
});

run();
