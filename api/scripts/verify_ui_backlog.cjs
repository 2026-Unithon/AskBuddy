// 밀린 일 일괄 처리 회귀(UI_REDESIGN_BACKLOG_PASS_20261108). 합성 API(ui_fixture.cjs)만 쓴다.
// 실행: next start -p 3011 을 띄운 뒤 NODE_PATH=<playwright> node api/scripts/verify_ui_backlog.cjs [이름 앞부분]
const assert = require('node:assert/strict');
const { createSuite, open, to, here } = require('./ui_harness.cjs');
const { test, run } = createSuite('ui-backlog');

// ── Task 2 공통 키트 ──
test('KIT-1 스낵바에 손을 올리면 닫히지 않는다', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/dev/kit?s=feedback');
  await page.getByRole('button', { name: '스낵바 보기' }).click();
  const bar = page.getByRole('status').filter({ hasText: '지웠어요' });
  await bar.waitFor();
  await bar.getByText('지웠어요').hover();
  await page.waitForTimeout(5600);
  assert.ok(await bar.getByText('지웠어요').isVisible(), '손을 올린 동안 남는다');
  await page.mouse.move(5, 5);
  await bar.getByText('지웠어요').waitFor({ state: 'detached', timeout: 6000 });
  await ctx.close();
});
test('KIT-2 확인 창은 제목과 설명을 읽는다', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/dev/kit?s=feedback');
  await page.getByRole('button', { name: '확인 창 보기' }).click();
  const dialog = page.getByRole('dialog', { name: '로그아웃할까요?' });
  await dialog.waitFor();
  const described = await dialog.evaluate((el) => document.getElementById(el.getAttribute('aria-describedby') ?? '')?.textContent);
  assert.equal(described, '다시 들어오려면 로그인해야 해요.');
  await page.keyboard.press('Escape');
  await dialog.waitFor({ state: 'hidden' });
  // 닫힌 뒤 다시 열 수 있다(open 값과 화면이 어긋나지 않는다)
  await page.getByRole('button', { name: '확인 창 보기' }).click();
  await dialog.waitFor();
  await ctx.close();
});
test('KIT-3 차례 등장은 자식 key 를 쓴다', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/dev/kit?s=gestures');
  const second = page.locator('[data-stagger] > *').filter({ hasText: '둘' });
  await second.evaluate((el) => { el.dataset.mark = 'kept'; });
  await page.getByRole('button', { name: '첫 줄 빼기' }).click();
  await page.locator('[data-stagger] > *').filter({ hasText: '하나' }).waitFor({ state: 'detached' });
  assert.equal(await page.locator('[data-stagger] > [data-mark="kept"]').textContent(), '둘', '남은 줄은 같은 노드');
  await ctx.close();
});

// ── Task 4 문구 ──
async function startEdit(page) { await page.getByRole('button', { name: '수정하기' }).click(); await page.getByRole('button', { name: '수정 완료' }).waitFor(); }
async function longPress(page, locator) {
  await locator.scrollIntoViewIfNeeded();
  const box = await locator.boundingBox();
  await page.mouse.move(box.x + 30, box.y + 12); await page.mouse.down(); await page.waitForTimeout(650); await page.mouse.up();
}
test('COPY-1 사실 고치기의 하지 않음은 스위치 줄', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/cards/1');
  await startEdit(page);
  await longPress(page, page.locator('[data-testid="fact-row"]').filter({ hasText: '뚜껑을 닫는다.' }));
  await page.getByRole('dialog', { name: /뚜껑을 닫는다/ }).getByRole('button', { name: '고치기' }).click();
  const sheet = page.getByRole('dialog', { name: '이 사실 고치기' });
  const toggle = sheet.getByRole('switch', { name: '하지 않는 일이에요' });
  assert.equal(await toggle.getAttribute('aria-checked'), 'false');
  await toggle.click();
  assert.equal(await toggle.getAttribute('aria-checked'), 'true');
  assert.equal(await sheet.getByText(/켜짐|꺼짐/).count(), 0);
  await ctx.close();
});

// ── Task 5 넣기 ──
const jobKeys = (api) => api.calls.filter((c) => c.method === 'POST' && c.path === '/ingest/jobs').map((c) => c.headers['idempotency-key']);
test('INTAKE-1 예시 칩으로 글이 바뀌면 다른 키로 보낸다', async (b) => {
  const { page, ctx, api } = await open(b, 'OWNER', '/owner/add', { overrides: { failJobCreate: 2 } });
  await page.getByRole('group', { name: '예시' }).getByRole('button', { name: '레시피' }).click();
  const send = page.getByRole('button', { name: '넣기', exact: true });
  const settled = async (n) => { while (jobKeys(api).length < n) await page.waitForTimeout(50); await send.and(page.locator(':enabled')).waitFor(); };
  await send.click();
  await settled(1);
  // 같은 글로 다시 보내면 같은 키
  await send.click();
  await settled(2);
  await page.getByRole('group', { name: '예시' }).getByRole('button', { name: '공지' }).click();
  await send.click();
  await to(page, '/owner/jobs/7');
  const keys = jobKeys(api);
  assert.equal(keys.length, 3);
  assert.equal(keys[0], keys[1], '같은 입력은 같은 키');
  assert.notEqual(keys[1], keys[2], '예시로 글이 바뀌면 새 키');
  await ctx.close();
});
test("INTAKE-2 이미 올린 자료면 '다시' 대신 빼기만", async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/add', { overrides: { duplicateSource: true } });
  await page.locator('input[type=file][multiple]').setInputFiles({ name: '마감표.png', mimeType: 'image/png', buffer: Buffer.from('png') });
  await page.getByRole('button', { name: '넣기', exact: true }).click();
  const row = page.getByRole('listitem').filter({ hasText: '마감표.png' });
  await row.getByText('이미 올린 자료예요', { exact: false }).waitFor();
  assert.equal(await row.getByRole('button', { name: '다시' }).count(), 0);
  await row.getByRole('button', { name: '마감표.png 빼기' }).click();
  await row.waitFor({ state: 'detached' });
  await ctx.close();
});
test('INTAKE-3 일부 실패 안내는 다음 화면에서 오래 남는다', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/add', { overrides: { failUploadCount: 1 } });
  await page.locator('input[type=file][multiple]').setInputFiles([
    { name: '흐린 사진.jpg', mimeType: 'image/jpeg', buffer: Buffer.from('jpg') },
    { name: '마감표.png', mimeType: 'image/png', buffer: Buffer.from('png') },
  ]);
  await page.getByRole('button', { name: '넣기', exact: true }).click();
  await to(page, '/owner/jobs/7');
  const notice = page.getByRole('status').getByText('흐린 사진.jpg은(는) 올리지 못했어요');
  await notice.waitFor();
  await page.waitForTimeout(3500);
  assert.ok(await notice.isVisible(), '3.5초 뒤에도 보인다');
  await ctx.close();
});
test('INTAKE-4 업로드가 멈추면 시간 제한 뒤 실패와 다시', async (b) => {
  const { page, ctx, api } = await open(b, 'OWNER', '/owner/add', { overrides: { stallUpload: true } });
  await page.clock.install();
  await page.locator('input[type=file][multiple]').setInputFiles({ name: '마감표.png', mimeType: 'image/png', buffer: Buffer.from('png') });
  await page.getByRole('button', { name: '넣기', exact: true }).click();
  await page.getByRole('progressbar', { name: '마감표.png 올리는 중' }).waitFor();
  await page.clock.runFor(61_000);
  const row = page.getByRole('listitem').filter({ hasText: '마감표.png' });
  await row.getByText('올리는 데 너무 오래 걸려요', { exact: false }).waitFor();
  api.state.stallUpload = false;
  await row.getByRole('button', { name: '다시' }).click();
  await to(page, '/owner/jobs/7');
  await ctx.close();
});

// ── Task 6 정리 중·검수 ──
const onlyNeedsReview = (cards) => cards.filter((c) => c.review_status !== 'PENDING');
test("JOB-1 검수 필요만 남은 작업도 '정리 끝' 배너", async (b) => {
  const base = require('./ui_fixture.cjs').syntheticApi('OWNER').state.cards;
  const { page, ctx } = await open(b, 'OWNER', '/owner', { overrides: { cards: onlyNeedsReview(base) } });
  await page.getByRole('status').filter({ hasText: '정리 끝!' }).waitFor();
  await ctx.close();
});
test("JOB-2 오래된 작업이면 '검수할 카드가 있어요'", async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner', { overrides: { jobCompletedAt: '2026-10-01T00:00:00Z' } });
  await page.getByRole('status').filter({ hasText: '검수할 카드가 있어요' }).waitFor();
  assert.equal(await page.getByText('정리 끝!').count(), 0);
  await ctx.close();
});
test('JOB-3 검수 완료 일부 실패 안내가 버튼 바로 위에', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/jobs/7', { overrides: { failApprove: [5] } });
  await page.getByRole('button', { name: '검수 완료' }).click();
  const near = page.getByRole('button', { name: '검수 완료' }).locator('xpath=preceding-sibling::*[@role="alert"][1]');
  await near.getByText('1장은 공개하지 못했어요', { exact: false }).waitFor();
  await ctx.close();
});
test("JOB-4 확인 필요 카드의 '빼기'는 한 번만 읽힌다", async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/jobs/7');
  const section = page.getByRole('region', { name: /맞는지 확인해 주세요/ });
  await section.getByText('마감 머신 청소').waitFor();
  assert.equal(await section.getByRole('button', { name: '빼기' }).count(), 1);
  await ctx.close();
});
test("JOB-5 작업 중이면 '정리 끝' 배너는 숨긴다", async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner', { overrides: { job: { status: 'EXTRACTING' } } });
  await page.locator('[data-active-job]').waitFor();
  await page.waitForTimeout(500);
  assert.equal(await page.getByText('정리 끝!').count(), 0);
  await ctx.close();
});

async function dragLeft(page, locator) {
  await locator.scrollIntoViewIfNeeded();
  const box = await locator.boundingBox();
  const y = box.y + box.height / 2;
  await page.mouse.move(box.x + box.width - 20, y); await page.mouse.down();
  for (let i = 1; i <= 8; i++) await page.mouse.move(box.x + box.width - 20 - i * 25, y);
  await page.mouse.up();
}
test('JOB-6 실제 카드를 밀어 빼고, 연달아 빼면 앞 카드도 사라진 채', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/jobs/7');
  const tile = (title) => page.locator('[data-long-press]').filter({ hasText: title });
  await dragLeft(page, tile('오픈 준비'));
  await tile('오픈 준비').waitFor({ state: 'detached' });
  await page.getByRole('status').getByText('뺐어요').waitFor();
  await dragLeft(page, tile('원두 보관 위치'));
  await tile('원두 보관 위치').waitFor({ state: 'detached' });
  assert.equal(await tile('오픈 준비').count(), 0, '앞 카드도 계속 빠져 있다');
  await ctx.close();
});

run();
