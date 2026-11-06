// 넣기 → 정리 중 → 검수 회귀(화면 개선 계획 2). 합성 API(ui_fixture.cjs)만 쓴다.
// 실행: next start -p 3011 을 띄운 뒤 NODE_PATH=<playwright> node api/scripts/verify_ui_intake.cjs [이름 앞부분]
const assert = require('node:assert/strict');
const { createSuite, open, back, to, here, BASE } = require('./ui_harness.cjs');
const { test, run } = createSuite('ui-intake');

test('fixture 작업 상태 순서대로 넘어간다', async (b) => {
  const { page, ctx, api } = await open(b, 'OWNER', '/owner/jobs/7', { overrides: { jobSequence: ['EXTRACTING', 'SUCCEEDED'] } });
  await page.getByText('카드가 준비됐어요! 검수 부탁드려요!').waitFor({ timeout: 8000 });
  assert.ok(api.calls.filter((c) => c.path.startsWith('/ingest/jobs/7')).length >= 2);
  await ctx.close();
});

test('키트 차례 등장은 자식마다 지연이 늘어난다', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/dev/kit?s=gestures');
  const delays = await page.locator('[data-stagger] > *').evaluateAll((els) => els.map((e) => getComputedStyle(e).animationDelay));
  assert.deepEqual(delays.slice(0, 3), ['0s', '0.05s', '0.1s']);
  await ctx.close();
});
test('키트 왼쪽으로 밀면 동작, 조금만 밀면 제자리', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/dev/kit?s=gestures');
  const row = page.getByText('밀어 보세요');
  const box = await row.boundingBox();
  const swipe = async (dx) => {
    await page.mouse.move(box.x + box.width - 10, box.y + box.height / 2); await page.mouse.down();
    await page.mouse.move(box.x + box.width - 10 - dx, box.y + box.height / 2, { steps: 8 }); await page.mouse.up();
  };
  await swipe(30); await page.waitForTimeout(300);
  assert.equal(await page.getByText('뺐어요').count(), 0);
  await swipe(120);
  await page.getByText('뺐어요').waitFor();
  await ctx.close();
});
test('키트 밀기 동작은 키보드로도 된다', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/dev/kit?s=gestures');
  await page.getByRole('button', { name: '빼기' }).focus(); await page.keyboard.press('Enter');
  await page.getByText('뺐어요').waitFor();
  await ctx.close();
});
test('키트 길게 누르면 열리고 짧게 누르면 안 열린다', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/dev/kit?s=gestures');
  const btn = page.getByRole('button', { name: '꾹 눌러 보세요' });
  const box = await btn.boundingBox();
  await page.mouse.move(box.x + 10, box.y + 10); await page.mouse.down(); await page.waitForTimeout(150); await page.mouse.up();
  assert.equal(await page.getByText('길게 눌렀어요').count(), 0);
  await page.mouse.down(); await page.waitForTimeout(650); await page.mouse.up();
  await page.getByText('길게 눌렀어요').waitFor();
  await ctx.close();
});
test('키트 길게 누르기는 움직이면 열리지 않는다', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/dev/kit?s=gestures');
  const box = await page.getByRole('button', { name: '꾹 눌러 보세요' }).boundingBox();
  await page.mouse.move(box.x + 10, box.y + 10); await page.mouse.down();
  await page.mouse.move(box.x + 10, box.y + 40, { steps: 5 }); await page.waitForTimeout(650); await page.mouse.up();
  assert.equal(await page.getByText('길게 눌렀어요').count(), 0);
  await ctx.close();
});
test('키트 keepOnNavigate 토스트는 이동해도 남는다', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/dev/kit?s=gestures');
  await page.getByRole('button', { name: '이동해도 남는 토스트' }).click();
  await page.waitForURL(/s=o6/);
  await page.getByRole('status').getByText('남아 있어요').waitFor();
  await ctx.close();
});

test('o02a 예시 칩을 누르면 입력창이 그 문장으로 채워진다', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/add');
  await page.getByRole('group', { name: '예시' }).getByRole('button', { name: '마감 순서' }).click();
  const box = page.getByLabel('새로 알려줄 것');
  assert.equal(await box.inputValue(), '마감 때는 머신 청소, 원두 소분, 쓰레기 정리 순서로 해요');
  assert.ok(await box.evaluate((el) => el === document.activeElement));
  await ctx.close();
});
test('o02b 파일을 올리는 동안 진행 막대, 끝나면 작업 화면', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/add', { overrides: { uploadDelayMs: 1500 } });
  await page.locator('input[type=file][multiple]').setInputFiles({ name: '마감표.png', mimeType: 'image/png', buffer: Buffer.from('png') });
  await page.getByRole('button', { name: '넣기', exact: true }).click();
  const bar = page.getByRole('progressbar', { name: '마감표.png 올리는 중' });
  await bar.waitFor();
  assert.ok(!(await page.locator('main, footer').first().innerText()).includes('%'));
  await to(page, '/owner/jobs/7');
  await ctx.close();
});
test('o02b 올리기 실패한 파일은 빨간 줄과 다시', async (b) => {
  const { page, ctx, api } = await open(b, 'OWNER', '/owner/add', { overrides: { failUpload: true } });
  await page.locator('input[type=file][multiple]').setInputFiles({ name: '흐린 사진.jpg', mimeType: 'image/jpeg', buffer: Buffer.from('jpg') });
  await page.getByRole('button', { name: '넣기', exact: true }).click();
  const row = page.getByRole('listitem').filter({ hasText: '흐린 사진.jpg' });
  await row.getByText('전송이 완료되지 않았어요', { exact: false }).waitFor();
  assert.equal(here(page), '/owner/add');
  api.state.failUpload = false;
  await row.getByRole('button', { name: '다시' }).click();
  await to(page, '/owner/jobs/7');
  await ctx.close();
});
test('o02c 종류 칩은 한 줄이고 선택하면 진한 배경만', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/add');
  const group = page.getByRole('group', { name: '자료 종류' });
  const tops = await group.getByRole('button').evaluateAll((els) => [...new Set(els.map((e) => Math.round(e.getBoundingClientRect().top)))]);
  assert.equal(tops.length, 1, '한 줄');
  const chip = group.getByRole('button', { name: '공지' });
  await chip.click();
  const style = await chip.evaluate((e) => { const s = getComputedStyle(e); return { radius: s.borderTopLeftRadius, height: e.getBoundingClientRect().height, border: s.borderTopWidth }; });
  assert.equal(style.radius, '8px'); assert.equal(style.height, 32); assert.equal(style.border, '0px');
  assert.equal(await chip.getAttribute('aria-pressed'), 'true');
  await ctx.close();
});

test('o03a 정리 단계는 서버 상태대로 체크된다', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/jobs/7', { overrides: { job: { status: 'CLASSIFYING' } } });
  const steps = page.getByRole('list', { name: '정리 단계' });
  await steps.waitFor();
  assert.equal((await steps.locator('[aria-current="step"]').innerText()).trim(), '나누는 중');
  assert.equal(await page.getByText('%').count(), 0);
  await ctx.close();
});
test('o03c 작업 화면에 있으면 토스트, 다른 화면이면 보기 스낵바', async (b) => {
  const first = await open(b, 'OWNER', '/owner/jobs/7', { overrides: { jobSequence: ['EXTRACTING', 'EXTRACTING', 'SUCCEEDED'] } });
  await first.page.getByRole('status').getByText('정리 끝!').waitFor({ timeout: 10000 });
  assert.equal(await first.page.getByRole('button', { name: '보기' }).count(), 0);
  await first.ctx.close();
  const second = await open(b, 'OWNER', '/owner/cards', { overrides: { jobSequence: ['EXTRACTING', 'EXTRACTING', 'SUCCEEDED'] } });
  await second.page.getByRole('status').getByText('정리 끝!').waitFor({ timeout: 10000 });
  await second.page.getByRole('button', { name: '보기' }).click();
  await to(second.page, '/owner/jobs/7');
  await second.ctx.close();
});
test('o03c 오늘 매장에 검수할 작업이 있으면 정리 끝 배너', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner');
  const banner = page.getByRole('status').filter({ hasText: '정리 끝!' });
  await banner.getByRole('button', { name: '검수하기' }).click();
  await to(page, '/owner/jobs/7');
  await ctx.close();
});

const REVIEW = { job: { status: 'PARTIAL', sources: [
  { source_id: 31, filename: '레시피 메모.jpg', status: 'SUCCEEDED', card_count: 4, error: null, source_availability: 'AVAILABLE' },
  { source_id: 32, filename: '흐린 사진.jpg', status: 'FAILED', card_count: 0, error: { code: 'EXTRACTION_FAILED', message: '글자를 읽을 수 없어요' }, source_availability: 'AVAILABLE' }] } };

test('o04a 제목은 부탁 말투, 실패 배너는 자료마다 이유', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/jobs/7', { overrides: REVIEW });
  await page.getByRole('heading', { name: '카드가 준비됐어요! 검수 부탁드려요!' }).waitFor();
  const banner = page.getByRole('alert').filter({ hasText: '처리하지 못한 자료가 있어요.' });
  await banner.getByText('흐린 사진.jpg: 글자를 읽을 수 없어요').waitFor();
  for (const gone of ['이렇게 나눴어요', '하나씩 봐 주세요', '맞아요', '더 넣기']) assert.equal(await page.getByText(gone, { exact: true }).count(), 0, gone);
  assert.equal(await page.getByText(/^출처/).count(), 0);
  await ctx.close();
});
test('o04b 이상한 카드는 이유와 함께 위에, 잘된 카드는 아래에', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/jobs/7', { overrides: REVIEW });
  const check = page.getByRole('region', { name: '맞는지 확인해 주세요!' });
  await check.getByText('마감 머신 청소').waitFor();
  await check.getByText('역세척 횟수가 두 가지(3회, 5회)로 적혀 있어요').waitFor();
  const good = page.getByRole('region', { name: '잘 정리됐어요' });
  await good.getByText('그대로 두셔도 돼요').waitFor();
  await good.getByText('오픈 준비').waitFor();
  assert.equal(await good.getByText('마감 머신 청소').count(), 0);
  await ctx.close();
});
test('o04b 빼기는 바로 저장되고 되돌리기로 살린다', async (b) => {
  const { page, ctx, api } = await open(b, 'OWNER', '/owner/jobs/7', { overrides: REVIEW });
  const check = page.getByRole('region', { name: '맞는지 확인해 주세요!' });
  await check.getByRole('button', { name: '빼기' }).first().click();
  await page.getByRole('status').getByText('뺐어요').waitFor();
  assert.ok(api.calls.some((c) => c.method === 'POST' && c.path === '/cards/3/exclude'));
  await check.getByText('마감 머신 청소').waitFor({ state: 'hidden' });
  await page.getByRole('button', { name: '되돌리기' }).click();
  // 서버 restore 는 카드를 PENDING 으로 되돌리므로 '잘 정리됐어요' 쪽으로 돌아온다
  await page.locator('main').getByText('마감 머신 청소').first().waitFor();
  assert.ok(api.calls.some((c) => c.method === 'POST' && c.path === '/cards/3/restore'));
  await ctx.close();
});
test('o04b 연달아 빼면 앞의 것은 그대로 빠져 있다', async (b) => {
  const { page, ctx, api } = await open(b, 'OWNER', '/owner/jobs/7', { overrides: REVIEW });
  const good = page.getByRole('region', { name: '잘 정리됐어요' });
  // 잘된 카드에는 보이는 버튼이 없다(밀기 동작만). 밀기 버튼을 키보드로 누른다
  await good.getByRole('button', { name: '빼기' }).nth(0).press('Enter');
  await good.getByRole('button', { name: '빼기' }).nth(0).press('Enter');
  await page.waitForTimeout(300);
  assert.equal(api.calls.filter((c) => c.path.endsWith('/exclude')).length, 2);
  assert.equal(api.state.cards.filter((c) => c.review_status === 'EXCLUDED').length, 2);
  await ctx.close();
});
test('o04b 길게 누르면 카테고리 옮기기 시트', async (b) => {
  const { page, ctx, api } = await open(b, 'OWNER', '/owner/jobs/7', { overrides: REVIEW });
  const card = page.getByRole('region', { name: '잘 정리됐어요' }).getByText('원두 보관 위치');
  await card.scrollIntoViewIfNeeded(); await page.waitForTimeout(300);
  const box = await card.boundingBox();
  await page.mouse.move(box.x + 5, box.y + 5); await page.mouse.down(); await page.waitForTimeout(650); await page.mouse.up();
  const sheet = page.getByRole('dialog', { name: '원두 보관 위치' });
  await sheet.getByRole('button', { name: '카테고리 옮기기' }).click();
  await sheet.getByRole('button', { name: '오픈 마감' }).click();
  await page.waitForTimeout(300);
  assert.ok(api.calls.some((c) => c.method === 'PATCH' && c.path === '/cards/5/category' && c.body.category_id === 11));
  await ctx.close();
});
test('o04c 검수 완료는 잘된 카드만 공개하고 토스트 뒤 오늘 매장', async (b) => {
  const { page, ctx, api } = await open(b, 'OWNER', '/owner/jobs/7', { overrides: REVIEW });
  await page.getByRole('button', { name: '검수 완료', exact: true }).click();
  await to(page, '/owner');
  await page.getByRole('status').getByText('지식이 추가됐어요').waitFor();
  const approved = api.calls.filter((c) => c.path.endsWith('/approve')).map((c) => c.path);
  assert.deepEqual(approved.sort(), ['/cards/4/approve', '/cards/5/approve']);
  await ctx.close();
});
test('o04c 나중에 하기는 작은 글자 버튼이고 오늘 매장으로', async (b) => {
  const { page, ctx, api } = await open(b, 'OWNER', '/owner/jobs/7', { overrides: REVIEW });
  const later = page.getByRole('button', { name: '나중에 하기', exact: true });
  const size = await later.evaluate((e) => parseFloat(getComputedStyle(e).fontSize));
  assert.ok(size <= 14, `font ${size}`);
  await later.click(); await to(page, '/owner');
  assert.equal(api.calls.filter((c) => c.path.endsWith('/approve')).length, 0);
  await ctx.close();
});

test('검토 C1 길게 누르기 시트는 화면 전체를 덮고 버튼을 누를 수 있다(작은 화면, 스크롤 뒤)', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/jobs/7', { overrides: REVIEW, viewport: { width: 390, height: 500 } });
  const card = page.getByRole('region', { name: '잘 정리됐어요' }).getByText('원두 보관 위치');
  await card.scrollIntoViewIfNeeded(); await page.waitForTimeout(300);
  const box = await card.boundingBox();
  await page.mouse.move(box.x + 5, box.y + 5); await page.mouse.down(); await page.waitForTimeout(650); await page.mouse.up();
  const sheet = page.getByRole('dialog', { name: '원두 보관 위치' });
  await sheet.waitFor();
  const move = sheet.getByRole('button', { name: '카테고리 옮기기' });
  const hit = await move.evaluate((el) => { const r = el.getBoundingClientRect(); const top = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2); return { inView: r.top >= 0 && r.bottom <= innerHeight, hits: el === top || el.contains(top) }; });
  assert.deepEqual(hit, { inView: true, hits: true });
  const overlay = await page.getByRole('button', { name: '닫기' }).last().boundingBox();
  assert.ok(overlay.height >= 480, `덮개 높이 ${overlay.height}`);
  await ctx.close();
});
test('검토 C2 빼기 → 되돌리기 한 검수 필요 카드는 검수 완료로 공개되지 않고 위 섹션에 남는다', async (b) => {
  const { page, ctx, api } = await open(b, 'OWNER', '/owner/jobs/7', { overrides: REVIEW });
  const check = page.getByRole('region', { name: '맞는지 확인해 주세요!' });
  await check.getByRole('button', { name: '빼기' }).first().click();
  await page.getByRole('button', { name: '되돌리기' }).click();
  await check.getByText('마감 머신 청소').waitFor();
  await page.getByRole('button', { name: '검수 완료', exact: true }).click();
  await to(page, '/owner');
  assert.equal(api.calls.filter((c) => c.path === '/cards/3/approve').length, 0);
  await ctx.close();
});
test('검토 I3 되돌리기에 실패하면 화면에 알린다', async (b) => {
  const { page, ctx, api } = await open(b, 'OWNER', '/owner/jobs/7', { overrides: REVIEW });
  api.state.failRestore = true;
  await page.getByRole('region', { name: '맞는지 확인해 주세요!' }).getByRole('button', { name: '빼기' }).first().click();
  await page.getByRole('button', { name: '되돌리기' }).click();
  await page.getByRole('status').getByText('되돌리지 못했어요', { exact: false }).waitFor();
  await ctx.close();
});
test('검토 I4 길게 누르는 카드는 글자 선택과 iOS 링크 메뉴를 막는다', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/jobs/7', { overrides: REVIEW });
  const target = page.locator('[data-long-press]').first();
  const style = await target.evaluate((e) => ({ select: getComputedStyle(e).userSelect, className: e.className }));
  assert.equal(style.select, 'none');
  // -webkit-touch-callout 은 iOS 사파리만 알아서 크로미움에서는 계산값을 읽을 수 없다. 규칙이 붙었는지만 본다
  assert.ok(style.className.includes('[-webkit-touch-callout:none]'));
  await ctx.close();
});
test('검토 I5 공개할 카드가 없으면 검수 완료에 지식 추가 토스트가 없다', async (b) => {
  const { page, ctx, api } = await open(b, 'OWNER', '/owner/jobs/7', { overrides: REVIEW });
  for (const c of api.state.cards) if (c.review_status === 'PENDING') c.review_status = 'APPROVED';
  await page.reload({ waitUntil: 'networkidle' });
  await page.getByRole('button', { name: '검수 완료', exact: true }).click();
  await to(page, '/owner');
  await page.waitForTimeout(300);
  assert.equal(await page.getByText('지식이 추가됐어요').count(), 0);
  await ctx.close();
});
test('검토 I6 밀다가 브라우저가 가져가면(pointercancel) 동작하지 않는다', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/dev/kit?s=gestures');
  await page.getByText('밀어 보세요').evaluate((el) => {
    const target = el.closest('.touch-pan-y');
    const at = (type, x) => target.dispatchEvent(new PointerEvent(type, { bubbles: true, pointerId: 7, clientX: x, clientY: 100 }));
    at('pointerdown', 300); for (let x = 290; x >= 150; x -= 10) at('pointermove', x); at('pointercancel', 150);
  });
  await page.waitForTimeout(300);
  assert.equal(await page.getByText('뺐어요').count(), 0);
  await ctx.close();
});

run();
