// 오늘 매장·직원 질문 회귀(화면 개선 계획 4a). 합성 API(ui_fixture.cjs)만 쓴다.
// 실행: next start -p 3011 을 띄운 뒤 NODE_PATH=<playwright> node api/scripts/verify_ui_today.cjs [이름 앞부분]
const assert = require('node:assert/strict');
const { createSuite, open, back, to, here, BASE } = require('./ui_harness.cjs');
const { test, run } = createSuite('ui-today');

test('키트 코치마크는 차례로 보이고 끝나면 다시 안 뜬다', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/dev/kit?s=guide', { overrides: { coach: true } });
  const bubble = page.getByRole('dialog', { name: '안내' });
  await bubble.getByText('첫 번째').waitFor();
  await bubble.getByRole('button', { name: '다음' }).click();
  await bubble.getByText('두 번째').waitFor();
  await bubble.getByRole('button', { name: '알겠어요' }).click();
  await bubble.waitFor({ state: 'hidden' });
  await page.reload({ waitUntil: 'networkidle' }); await page.waitForTimeout(500);
  assert.equal(await bubble.count(), 0);
  await ctx.close();
});
test('키트 코치마크 대상이 없으면 건너뛴다', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/dev/kit?s=guide', { overrides: { coach: true } });
  const bubble = page.getByRole('dialog', { name: '안내' });
  await bubble.getByRole('button', { name: '다음' }).click();
  await bubble.getByText('두 번째').waitFor();
  assert.equal(await page.getByText('없는 대상').count(), 0);
  await ctx.close();
});
test('키트 세그먼트는 하나만 선택된다', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/dev/kit?s=guide');
  const seg = page.getByRole('tablist', { name: '예시 세그먼트' });
  await seg.getByRole('tab', { name: '나' }).click();
  assert.equal(await seg.getByRole('tab', { name: '나' }).getAttribute('aria-selected'), 'true');
  assert.equal(await seg.getByRole('tab', { name: '가' }).getAttribute('aria-selected'), 'false');
  await ctx.close();
});

test('o01a 처음 들어오면 설정 알림 넣기 순서로 안내', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner', { overrides: { coach: true } });
  const bubble = page.getByRole('dialog', { name: '안내' });
  await bubble.getByText('매장 설정은 여기서 바꿔요').waitFor();
  await bubble.getByRole('button', { name: '다음' }).click();
  await bubble.getByText('질문이 오면 여기에 알려 드려요').waitFor();
  await bubble.getByRole('button', { name: '건너뛰기' }).click();
  await page.reload({ waitUntil: 'networkidle' }); await page.waitForTimeout(500);
  assert.equal(await bubble.count(), 0);
  await ctx.close();
});
test('o01b 현황 제목은 남은 수 하나, 기록 보기는 카드 안 링크', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner');
  await page.getByText('오픈 2개 남았어요').waitFor();
  assert.equal(await page.getByText(/^체크 \d+\/\d+개$/).count(), 0);
  assert.equal(await page.getByRole('link', { name: '내 기록과 알바생 기록 보기' }).count(), 0);
  await page.getByRole('link', { name: /기록 보기/ }).click(); await to(page, '/owner/me');
  await ctx.close();
});
test('o01e 스크롤 내리면 입력창이 숨고 올리면 나온다', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner', { viewport: { width: 390, height: 600 } });
  const box = page.getByLabel('새로 알려줄 것');
  const visibleBottom = async () => box.evaluate((el) => el.getBoundingClientRect().top < innerHeight);
  assert.equal(await visibleBottom(), true);
  await page.locator('main').evaluate((m) => { m.scrollTop = 200; m.dispatchEvent(new Event('scroll')); });
  await page.waitForTimeout(400);
  assert.equal(await visibleBottom(), false);
  await page.locator('main').evaluate((m) => { m.scrollTop = 0; m.dispatchEvent(new Event('scroll')); });
  await page.waitForTimeout(400);
  assert.equal(await visibleBottom(), true);
  await ctx.close();
});
test('o01f 카드 탭에 검수 필요 빨간 뱃지, 탭 알약은 하나', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner');
  const tab = page.getByRole('navigation', { name: '주요 메뉴' }).getByRole('link', { name: /카드/ });
  assert.equal((await tab.innerText()).replace(/\D/g, ''), '2');
  assert.equal(await page.locator('[data-tab-pill]').count(), 1);
  await ctx.close();
});

test('o01d 질문을 누르면 시트로 바로 답하고, 보내면 목록에서 빠진다', async (b) => {
  const { page, ctx, api } = await open(b, 'OWNER', '/owner');
  await page.getByRole('button', { name: /디카페인 원두는 어디 있어요\?/ }).click();
  const sheet = page.getByRole('dialog', { name: '디카페인 원두는 어디 있어요?' });
  await sheet.getByText('한 번 답하면 다음 알바는 이걸 안 물어봐요').waitFor();
  await sheet.getByLabel('직원에게 보낼 답').fill('창고 오른쪽 맨 위 칸에 있어요');
  await sheet.getByRole('button', { name: '넣기' }).click();
  await page.getByRole('status').getByText('답을 보냈어요').waitFor();
  await sheet.waitFor({ state: 'hidden' });
  assert.equal(here(page), '/owner');
  assert.ok(api.calls.some((c) => c.method === 'POST' && c.path === '/learn/v2/pending/101/answers'));
  await page.getByRole('button', { name: /디카페인 원두는 어디 있어요\?/ }).waitFor({ state: 'hidden' });
  await ctx.close();
});
test('o01d 보내기를 연타해도 한 번만', async (b) => {
  const { page, ctx, api } = await open(b, 'OWNER', '/owner');
  await page.getByRole('button', { name: /디카페인/ }).click();
  const sheet = page.getByRole('dialog');
  await sheet.getByLabel('직원에게 보낼 답').fill('창고 오른쪽');
  await sheet.getByRole('button', { name: '넣기' }).dblclick();
  await page.waitForTimeout(500);
  const ids = new Set(api.calls.filter((c) => c.path === '/learn/v2/pending/101/answers').map((c) => c.body.request_id));
  assert.equal(ids.size, 1);
  await ctx.close();
});
test('o01d 시트 답하기 충돌이면 입력이 남는다', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner', { overrides: { answerConflict: true } });
  await page.getByRole('button', { name: /디카페인/ }).click();
  const sheet = page.getByRole('dialog');
  await sheet.getByLabel('직원에게 보낼 답').fill('창고 오른쪽');
  await sheet.getByRole('button', { name: '넣기' }).click();
  await sheet.getByText(/그사이 답이 바뀌었어요/).waitFor();
  assert.equal(await sheet.getByLabel('직원에게 보낼 답').inputValue(), '창고 오른쪽');
  await ctx.close();
});
test('o01d 밀어서 나중에는 목록 끝으로', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner');
  const order = async () => page.locator('main').getByRole('button', { name: /어디 있어요\?|2펌프인가요\?/ }).allInnerTexts();
  assert.ok((await order())[0].includes('디카페인'));
  await page.getByRole('button', { name: '나중에' }).first().press('Enter');
  await page.waitForTimeout(300);
  const after = await order();
  assert.ok(after.at(-1).includes('디카페인') && after.length === 2);
  await ctx.close();
});
test('o09 답변 대기 전체는 세그먼트, 카드를 누르면 시트', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/questions');
  const seg = page.getByRole('tablist', { name: '질문 보기' });
  assert.equal((await seg.getByRole('tab', { name: /답변 대기/ }).innerText()).replace(/\D/g, ''), '2');
  assert.equal(await page.getByRole('link', { name: '답변하기' }).count(), 0);
  await page.getByRole('button', { name: /오트밀크 라떼도 시럽 2펌프인가요\?/ }).click();
  await page.getByRole('dialog', { name: '오트밀크 라떼도 시럽 2펌프인가요?' }).waitFor();
  await ctx.close();
});

test('o10a 여러 번 물어봤으면 물어본 말을 펼쳐 본다', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/questions/101');
  await page.getByText('직원이 2번 물어봤어요').waitFor();
  await page.getByRole('button', { name: '물어본 말 보기' }).click();
  assert.equal(await page.getByRole('listitem').filter({ hasText: '디카페인 원두는 어디 있어요?' }).count(), 2);
  await ctx.close();
});
test('o10b 첨부는 입력창의 파일 도구, 종류 칩은 붙인 뒤에만', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/questions/101');
  assert.equal(await page.getByTestId('attach-area').count(), 0);
  assert.equal(await page.getByRole('group', { name: '자료 종류' }).count(), 0);
  await page.getByTestId('attach-input').setInputFiles({ name: '창고.jpg', mimeType: 'image/jpeg', buffer: Buffer.from('jpg') });
  await page.getByRole('group', { name: '자료 종류' }).waitFor();
  await page.getByRole('listitem').filter({ hasText: '창고.jpg' }).waitFor();
  await ctx.close();
});
test('o10c 보내면 체크와 다음 질문 버튼', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/questions/101');
  const box = page.getByLabel('직원에게 보낼 답');
  await box.focus();
  await page.getByText('답을 적으면 보낼 수 있어요').waitFor();
  assert.equal(await page.getByRole('button', { name: '넣기' }).isDisabled(), true);
  await box.fill('창고 오른쪽 맨 위 칸');
  await page.getByRole('button', { name: '넣기' }).click();
  await page.getByText('답을 보냈어요').waitFor();
  await page.getByRole('button', { name: '다음 질문 1개' }).click();
  await to(page, '/owner/questions/102');
  await ctx.close();
});
test('o11 공개된 화면은 초록, 답 고치기 없음', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/questions/103');
  await page.getByText('카드로 남았어요').waitFor();
  assert.equal(await page.getByText('공개됨', { exact: true }).getAttribute('data-tone'), 'success');
  assert.equal(await page.getByRole('button', { name: '답 고치기' }).count(), 0);
  await ctx.close();
});

test('검토 1 입력창이 숨으면 그 자리에 내용이 보이고, 입력 중엔 숨지 않는다', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner', { viewport: { width: 390, height: 600 } });
  const box = page.getByLabel('새로 알려줄 것');
  const footerTop = await box.evaluate((el) => el.getBoundingClientRect().top);
  await page.locator('main').evaluate((m) => { m.scrollTop = 200; m.dispatchEvent(new Event('scroll')); });
  await page.waitForTimeout(400);
  const hit = await page.evaluate((y) => Boolean(document.elementFromPoint(195, y + 20)?.closest('main')), footerTop);
  assert.equal(hit, true, '숨은 입력창 자리에 본문이 보여야 한다');
  await page.locator('main').evaluate((m) => { m.scrollTop = 0; m.dispatchEvent(new Event('scroll')); });
  await page.waitForTimeout(400);
  await box.focus();
  await page.locator('main').evaluate((m) => { m.scrollTop = 200; m.dispatchEvent(new Event('scroll')); });
  await page.waitForTimeout(400);
  assert.ok(await box.evaluate((el) => el.getBoundingClientRect().top < innerHeight), '입력 중에는 숨지 않는다');
  await ctx.close();
});
test('검토 2 앞 질문의 늦은 저장이 다음 질문 시트를 닫지 않는다', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner', { overrides: { answerDelayMs: 1200 } });
  await page.getByRole('button', { name: /디카페인/ }).click();
  await page.getByRole('dialog').getByLabel('직원에게 보낼 답').fill('창고 오른쪽');
  await page.getByRole('dialog').getByRole('button', { name: '넣기' }).click();
  await page.keyboard.press('Escape');
  await page.getByRole('button', { name: /오트밀크/ }).click();
  const second = page.getByRole('dialog', { name: '오트밀크 라떼도 시럽 2펌프인가요?' });
  await second.getByLabel('직원에게 보낼 답').fill('네 2펌프');
  await page.waitForTimeout(1800);
  assert.equal(await second.isVisible(), true);
  assert.equal(await second.getByLabel('직원에게 보낼 답').inputValue(), '네 2펌프');
  await ctx.close();
});
test('검토 3 코치마크는 화면 크기가 바뀌면 다시 맞추고, 버튼에 포커스가 간다', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/dev/kit?s=guide', { overrides: { coach: true } });
  const bubble = page.getByRole('dialog', { name: '안내' });
  await bubble.getByText('첫 번째').waitFor();
  assert.equal(await page.evaluate(() => document.activeElement?.textContent), '다음');
  assert.equal(await bubble.getAttribute('aria-modal'), 'true');
  await page.setViewportSize({ width: 600, height: 500 }); await page.waitForTimeout(300);
  const [ring, target] = await page.evaluate(() => {
    const r = document.querySelector('[data-coach-ring]').getBoundingClientRect(), t = document.querySelector('#coach-a').getBoundingClientRect();
    return [Math.round(r.top + 6), Math.round(t.top)];
  });
  assert.ok(Math.abs(ring - target) <= 2, `ring ${ring} target ${target}`);
  await ctx.close();
});
test('검토 4 답한 뒤에도 사진·파일을 더 붙일 수 있다', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/questions/103');
  await page.getByText('카드로 남았어요').waitFor();
  await page.getByRole('button', { name: '사진, 파일 더 붙이기' }).waitFor();
  await page.getByTestId('attach-input').setInputFiles({ name: '서랍.jpg', mimeType: 'image/jpeg', buffer: Buffer.from('jpg') });
  await page.getByTestId('attach-item').filter({ hasText: '서랍.jpg' }).waitFor();
  await ctx.close();
});

run();
