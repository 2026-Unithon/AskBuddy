// 카드 목록·상세·확인 필요·제안 회귀(화면 개선 계획 3). 합성 API(ui_fixture.cjs)만 쓴다.
// 실행: next start -p 3011 을 띄운 뒤 NODE_PATH=<playwright> node api/scripts/verify_ui_cards.cjs [이름 앞부분]
const assert = require('node:assert/strict');
const { createSuite, open, back, to, here, BASE } = require('./ui_harness.cjs');
const { test, run } = createSuite('ui-cards');

test('키트 스위치는 눌러서 켜고 끈다', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/dev/kit?s=forms');
  const sw = page.getByRole('switch', { name: '알림' });
  assert.equal(await sw.getAttribute('aria-checked'), 'false');
  await sw.click(); assert.equal(await sw.getAttribute('aria-checked'), 'true');
  await sw.press('Space'); assert.equal(await sw.getAttribute('aria-checked'), 'false');
  await ctx.close();
});
test('키트 맨 위에서 당기면 새로고침, 조금만 당기면 안 한다', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/dev/kit?s=forms');
  const box = await page.locator('main').boundingBox();
  const pull = async (dy) => {
    await page.mouse.move(box.x + 100, box.y + 40); await page.mouse.down();
    await page.mouse.move(box.x + 100, box.y + 40 + dy, { steps: 10 }); await page.mouse.up();
  };
  await pull(40); await page.waitForTimeout(300);
  await page.getByText('새로고침 0번').waitFor();
  await pull(220);
  await page.getByText('새로고침 1번').waitFor();
  await ctx.close();
});

test('o05a 필터는 전체 공개 검수 필요 미공개, 지운 카드는 어디에도 없다', async (b) => {
  const { page, ctx, api } = await open(b, 'OWNER', '/owner/cards');
  api.state.cards.push({ card_id: 7, review_status: 'EXCLUDED', title: '지운 레시피', content: '-', category_id: 10 });
  await page.reload({ waitUntil: 'networkidle' });
  const tabs = page.getByRole('group', { name: '카드 상태' }).getByRole('button');
  assert.deepEqual((await tabs.allInnerTexts()).map((t) => t.replace(/\d+/g, '').trim()), ['전체', '공개', '검수 필요', '미공개']);
  assert.equal(await page.getByText('지운 레시피').count(), 0);
  await ctx.close();
});
test('o05a 빨간 뱃지는 검수 필요에만, 제안 걸린 카드도 센다', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/cards');
  const review = page.getByRole('group', { name: '카드 상태' }).getByRole('button', { name: /검수 필요/ });
  assert.equal((await review.innerText()).replace(/\D/g, ''), '2'); // 마감 머신 청소 + 제안 걸린 바닐라 라떼
  for (const name of ['전체', '공개', '미공개']) assert.equal((await page.getByRole('group', { name: '카드 상태' }).getByRole('button', { name, exact: true }).innerText()).replace(/\D/g, ''), '', name);
  await ctx.close();
});
test('o05a 검색은 칠 때마다 걸러지고 마지막 글자 기준', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/cards');
  const box = page.getByRole('searchbox', { name: '카드 찾기' });
  await box.pressSequentially('우유', { delay: 40 });
  await page.waitForURL(/query=%EC%9A%B0%EC%9C%A0/);
  await page.getByText('우유 발주').waitFor();
  assert.equal(await page.getByText('아메리카노').count(), 0);
  await box.fill(''); await page.waitForURL((u) => !u.search.includes('query='));
  await page.getByText('아메리카노').waitFor();
  await ctx.close();
});
test('o05b 제안 배너 대신 제안 걸린 카드에 다른 답 띠', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/cards?status=needs_review');
  assert.equal(await page.getByText('기존 카드와 다른 답이 있어요').count(), 0);
  const tile = page.getByRole('link', { name: '바닐라 라떼, 검수 필요' });
  await tile.getByText('다른 답이 있어요').waitFor();
  await tile.click(); await to(page, '/owner/cards/proposals?card_id=1');
  await ctx.close();
});
test('o05c 카테고리 섹션과 밑줄, 2열, 카드엔 이름과 꺾쇠만', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/cards');
  const section = page.getByRole('region', { name: '음료 레시피' });
  const heading = section.getByRole('heading', { name: '음료 레시피' });
  assert.equal(await heading.evaluate((h) => getComputedStyle(h).borderBottomWidth), '2px');
  const tiles = section.locator('[data-status]');
  const tops = await tiles.evaluateAll((els) => els.map((e) => Math.round(e.getBoundingClientRect().top)));
  assert.equal(tops[0], tops[1], '2열');
  const americano = section.locator('[aria-label="아메리카노, 공개"]');
  assert.deepEqual((await americano.innerText()).split('\n').map((t) => t.trim()).filter(Boolean), ['아메리카노', '›']);
  await ctx.close();
});
test('o05c 상태는 글자가 아니라 모양으로', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/cards');
  const style = async (name) => page.locator(`[aria-label^="${name},"]`).evaluate((e) => ({ status: e.dataset.status, border: getComputedStyle(e).borderTopWidth === '0px' ? 'none' : getComputedStyle(e).borderTopStyle }));
  assert.deepEqual(await style('아메리카노'), { status: 'approved', border: 'none' });
  assert.deepEqual(await style('오픈 준비'), { status: 'pending', border: 'dashed' });
  assert.equal((await style('마감 머신 청소')).status, 'review');
  for (const word of ['공개 전', '확인 필요', '미공개']) assert.equal(await page.locator('main [data-status]').getByText(word, { exact: true }).count(), 0, word);
  await ctx.close();
});
test('o05c 미공개 카드는 오른쪽으로 밀면 공개', async (b) => {
  const { page, ctx, api } = await open(b, 'OWNER', '/owner/cards?status=pending');
  await page.getByRole('button', { name: / 공개$/ }).first().press('Enter');
  await page.getByRole('status').getByText('공개했어요').waitFor();
  assert.ok(api.calls.some((c) => c.method === 'POST' && c.path === '/cards/4/approve'));
  await ctx.close();
});
test('o05c 미공개 탭에서 왼쪽으로 밀면 삭제, 되돌리기로 살린다', async (b) => {
  const { page, ctx, api } = await open(b, 'OWNER', '/owner/cards?status=pending');
  await page.getByRole('button', { name: '삭제' }).first().press('Enter');
  await page.getByRole('status').getByText('삭제했어요').waitFor();
  await page.getByText('오픈 준비').waitFor({ state: 'hidden' });
  await page.getByRole('button', { name: '되돌리기' }).click();
  await page.getByText('오픈 준비').waitFor();
  assert.ok(api.calls.some((c) => c.path === '/cards/4/restore'));
  await ctx.close();
});
test('o05c 연달아 삭제해도 앞 카드는 삭제된 채', async (b) => {
  const { page, ctx, api } = await open(b, 'OWNER', '/owner/cards?status=pending');
  await page.getByRole('button', { name: '삭제' }).nth(0).press('Enter');
  await page.getByRole('button', { name: '삭제' }).nth(0).press('Enter');
  await page.waitForTimeout(300);
  assert.equal(api.state.cards.filter((c) => c.review_status === 'EXCLUDED').length, 2);
  assert.equal(await page.locator('[data-status]').count(), 0);
  await ctx.close();
});
test('o05c 전체 탭의 공개 카드는 밀 수 없다(공개 내리기는 서버 뒤)', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/cards');
  const tile = page.locator('[aria-label="아메리카노, 공개"]');
  assert.equal(await tile.locator('..').getByRole('button', { name: /삭제|미공개/ }).count(), 0);
  await ctx.close();
});
test('o05c 당겨서 새로고침', async (b) => {
  const { page, ctx, api } = await open(b, 'OWNER', '/owner/cards');
  const before = api.calls.filter((c) => c.path.startsWith('/cards?') || c.path === '/cards').length;
  const box = await page.locator('main').boundingBox();
  await page.mouse.move(box.x + 100, box.y + 40); await page.mouse.down();
  await page.mouse.move(box.x + 100, box.y + 260, { steps: 10 }); await page.mouse.up();
  await page.waitForTimeout(500);
  assert.ok(api.calls.filter((c) => c.path.startsWith('/cards?') || c.path === '/cards').length > before);
  await ctx.close();
});
test('o05c 목록 제목이 상세 제목으로 이어진다(view transition)', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/cards');
  await page.evaluate(() => { window.__vt = 0; const orig = document.startViewTransition?.bind(document); if (orig) document.startViewTransition = (...a) => { window.__vt++; return orig(...a); }; });
  await page.getByRole('link', { name: '아메리카노, 공개' }).click(); await to(page, '/owner/cards/2');
  assert.ok(await page.evaluate(() => window.__vt) > 0);
  await ctx.close();
});

test('o06a 오른쪽 위 수정하기, 카테고리 칩, 안내 문구 없음', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/cards/1');
  const edit = page.getByRole('button', { name: '수정하기' });
  const back = await page.locator('[data-back]').boundingBox(), box = await edit.boundingBox();
  assert.ok(Math.abs(back.y - box.y) < 12 && box.x > 200, '뒤로와 같은 줄 오른쪽');
  await page.getByRole('button', { name: /음료 레시피/ }).click();
  await page.getByRole('dialog', { name: '어디로 옮길까요?' }).waitFor();
  assert.equal(await page.getByText(/제목은 메뉴/).count(), 0);
  await ctx.close();
});
test('o06b 블록 머리글은 카드 밖 굵은 글, 칩과 근거 줄 없음, 값은 문장 안에서 굵게', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/cards/1');
  const head = page.getByRole('heading', { name: 'ICE', exact: true });
  assert.ok(parseFloat(await head.evaluate((h) => getComputedStyle(h).fontSize)) >= 17);
  for (const gone of [/^수치/, /^근거:/, /^출처/, /근거 보기/, '하지 않음', '위나 아래로 옮기면 일하는 순서가 바뀌어요.']) assert.equal(await page.locator('main').getByText(gone).count(), 0, String(gone));
  assert.equal(await page.locator('main strong', { hasText: '225ml' }).count() + await page.locator('main strong', { hasText: '225' }).count() > 0, true);
  await ctx.close();
});
test('o06c 근거 자료는 맨 아래 작은 회색 한 줄', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/cards/1');
  const line = page.getByText(/^근거 자료 /);
  await line.waitFor();
  const info = await line.evaluate((e) => ({ size: parseFloat(getComputedStyle(e).fontSize), last: e === e.closest('main').lastElementChild || !e.nextElementSibling }));
  assert.ok(info.size <= 12); assert.ok(info.last);
  assert.ok((await line.innerText()).includes('지난 메모.jpg (원본 지워짐)'));
  await ctx.close();
});
// 2026-11-08 사용자: 레시피는 근무조와 상관없이 모두에게 보인다. 할 일 카드의 근무조 스위치는 ui-backlog SHIFT-1
test('o06e 레시피 카테고리 카드는 근무조를 묻지 않는다', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/cards/2', { overrides: { cardLinks: { 2: { checklist: true, shift_ids: [1] } } } });
  await page.getByRole('heading', { name: '아메리카노' }).waitFor();
  await page.waitForTimeout(300);
  assert.equal(await page.getByText('어느 근무조 할 일인가요?').count(), 0);
  assert.equal(await page.getByRole('switch').count(), 0);
  await ctx.close();
});
test('o07a 검수 필요 사유는 확인해 주세요 상자, 근거 보기 없음', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/cards/3');
  await page.getByText('확인해 주세요', { exact: true }).waitFor();
  await page.getByText('역세척 횟수가 두 가지(3회, 5회)로 적혀 있어요').waitFor();
  assert.equal(await page.getByText(/근거 보기/).count(), 0);
  await ctx.close();
});
test('o07b 하단은 공개 하나, 고치기 지우기 없음', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/cards/3');
  await page.getByRole('button', { name: '공개', exact: true }).waitFor();
  for (const gone of ['고치기', '지우기', '공개하기']) assert.equal(await page.getByRole('button', { name: gone, exact: true }).count(), 0, gone);
  await ctx.close();
  const live = await open(b, 'OWNER', '/owner/cards/2');
  assert.equal(await live.page.getByRole('button', { name: '공개', exact: true }).count(), 0);
  await live.ctx.close();
});
test('o06 삭제한 카드 주소는 내용 없이 안내만', async (b) => {
  const { page, ctx, api } = await open(b, 'OWNER', '/owner/cards/2');
  api.state.cards[1].review_status = 'EXCLUDED';
  await page.reload({ waitUntil: 'networkidle' });
  await page.getByText('삭제한 카드예요').waitFor();
  assert.equal(await page.getByText('아메리카노').count(), 0);
  assert.equal(await page.getByRole('button', { name: /살리기|되돌리기|공개/ }).count(), 0);
  await ctx.close();
});

async function startEdit(page) { await page.getByRole('button', { name: '수정하기' }).click(); await page.getByRole('button', { name: '수정 완료' }).waitFor(); }

test('o06f 수정 모드 하단은 수정 완료 큰 버튼, 그 아래 작은 글자 돌아가기(2026-11-08 다시 판단)', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/cards/1');
  await startEdit(page);
  const done = page.getByRole('button', { name: '수정 완료' }), cancel = page.getByRole('button', { name: '돌아가기' });
  const [d, c] = [await done.boundingBox(), await cancel.boundingBox()];
  assert.ok(c.y > d.y + d.height - 2, '돌아가기는 아래');
  assert.ok(c.width < d.width / 2, '돌아가기는 작은 글자');
  assert.ok(Math.abs((c.x + c.width / 2) - (d.x + d.width / 2)) < 8, '가운데');
  assert.equal(await page.getByRole('button', { name: '수정하기' }).count(), 0);
  for (const gone of ['고친 내용 저장', '그만두기']) assert.equal(await page.getByRole('button', { name: gone }).count(), 0, gone);
  await ctx.close();
});
test('o06d 보기 모드에는 손잡이가 없고 수정 모드에만 있다', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/cards/1');
  assert.equal(await page.getByRole('button', { name: /^(?!카테고리).*옮기기$/ }).count(), 0);
  await startEdit(page);
  assert.ok(await page.getByRole('button', { name: /^(?!카테고리).*옮기기$/ }).count() > 0);
  assert.equal(await page.getByRole('button', { name: /^위로|^아래로/ }).count(), 0);
  await ctx.close();
});
test('o06d 손잡이를 끌어 순서를 바꾸고 수정 완료하면 저장, 수정 완료 토스트', async (b) => {
  const { page, ctx, api } = await open(b, 'OWNER', '/owner/cards/1');
  await startEdit(page);
  const handle = page.getByRole('button', { name: '3번 물을 붓는다. 옮기기' });
  await handle.scrollIntoViewIfNeeded(); await page.waitForTimeout(200);
  const box = await handle.boundingBox();
  // 수정 모드 줄은 근거·버튼까지 있어 높다. 한 줄 높이의 3/4 만큼 끌면 한 칸 옮겨진다
  const rowHeight = await handle.evaluate((el) => el.closest('li').getBoundingClientRect().height);
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2); await page.mouse.down();
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2 - rowHeight * 0.75, { steps: 12 }); await page.mouse.up();
  const order = await page.locator('[data-testid="fact-row"]').allInnerTexts();
  assert.ok(order.findIndex((t) => t.includes('물을 붓는다.')) < order.findIndex((t) => t.includes('샷을 붓는다.')));
  await page.getByRole('button', { name: '수정 완료' }).click();
  await page.getByRole('status').getByText('수정했어요').waitFor();
  assert.ok(api.calls.some((c) => c.method === 'PUT' && c.path === '/cards/1/facts'));
  await page.getByRole('button', { name: '수정하기' }).waitFor();
  await ctx.close();
});
test('o06d 손잡이는 키보드 화살표로도 옮긴다', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/cards/1');
  await startEdit(page);
  await page.getByRole('button', { name: '3번 물을 붓는다. 옮기기' }).press('ArrowUp');
  const order = await page.locator('[data-testid="fact-row"]').allInnerTexts();
  assert.ok(order.findIndex((t) => t.includes('물을 붓는다.')) < order.findIndex((t) => t.includes('샷을 붓는다.')));
  await ctx.close();
});
test('o06d 선행 단계 앞으로는 끌어도 안 옮겨진다', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/cards/1');
  await startEdit(page);
  await page.getByRole('button', { name: '2번 샷을 붓는다. 옮기기' }).press('ArrowUp'); // 샷은 1번(얼음) 뒤여야 한다
  const order = await page.locator('[data-testid="fact-row"]').allInnerTexts();
  assert.ok(order.findIndex((t) => t.includes('컵에 얼음을 담는다.')) < order.findIndex((t) => t.includes('샷을 붓는다.')));
  await ctx.close();
});
test('o06d 수정 모드에서 줄을 누르면 고치기, 오른쪽 휴지통으로 빼기(2026-11-08 길게 누르기 메뉴 대신)', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/cards/1');
  await startEdit(page);
  const row = page.locator('[data-testid="fact-row"]').filter({ hasText: '뚜껑을 닫는다.' });
  await row.getByRole('button', { name: /^빼기: / }).waitFor();
  await row.getByRole('button', { name: /^고치기: / }).click();
  await page.getByRole('dialog', { name: '이 사실 고치기' }).waitFor();
  await ctx.close();
});
test('o06f 돌아가기는 저장하지 않는다', async (b) => {
  const { page, ctx, api } = await open(b, 'OWNER', '/owner/cards/1');
  await startEdit(page);
  await page.getByRole('button', { name: '3번 물을 붓는다. 옮기기' }).press('ArrowUp');
  await page.getByRole('button', { name: '돌아가기' }).click();
  await page.getByRole('dialog', { name: '고친 내용을 버릴까요?' }).getByRole('button', { name: '버리고 나가기' }).click();
  await page.getByRole('button', { name: '수정하기' }).waitFor();
  assert.equal(api.calls.filter((c) => c.method === 'PUT').length, 0);
  const order = await page.locator('[data-testid="fact-row"]').allInnerTexts();
  assert.ok(order.findIndex((t) => t.includes('샷을 붓는다.')) < order.findIndex((t) => t.includes('물을 붓는다.')));
  await ctx.close();
});

test('o08a 바뀐 부분만 강조, 지금 카드 제안 내용 상자 없음', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/cards/proposals');
  assert.equal(await page.locator('main del, main s, main [data-diff="del"]').filter({ hasText: '2펌프' }).count(), 1);
  assert.equal(await page.locator('main [data-diff="add"]').filter({ hasText: '3펌프' }).count(), 1);
  for (const gone of ['지금 카드', '제안 내용']) assert.equal(await page.getByText(gone, { exact: true }).count(), 0, gone);
  await ctx.close();
});
test('o08b 수정 완료 하나와 작은 쓰지 않기, 카드 확인 버튼 없음', async (b) => {
  const { page, ctx, api } = await open(b, 'OWNER', '/owner/cards/proposals?card_id=1');
  assert.equal(await page.getByRole('link', { name: /확인$/ }).count(), 0);
  const back = page.getByRole('button', { name: '이 답은 쓰지 않기' });
  assert.ok(parseFloat(await back.evaluate((e) => getComputedStyle(e).fontSize)) <= 14);
  await page.getByRole('button', { name: '수정 완료' }).click();
  await page.getByRole('status').getByText('카드에 반영했어요').waitFor();
  assert.ok(api.calls.some((c) => c.path === '/learn/knowledge-proposals/9/approve'));
  await ctx.close();
});

test('검토 1 검색어를 친 뒤 밖에서 주소가 바뀌면 옛 검색어가 다시 붙지 않는다', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/cards?category_id=12');
  await page.getByRole('searchbox', { name: '카드 찾기' }).pressSequentially('우유', { delay: 40 });
  await page.waitForURL(/query=/);
  await page.getByRole('button', { name: /모두 보기/ }).click();
  await page.waitForTimeout(600);
  assert.equal(new URL(page.url()).search, '');
  assert.equal(await page.getByRole('searchbox', { name: '카드 찾기' }).inputValue(), '');
  await ctx.close();
});
test('검토 2 손가락으로 맨 위에서 당기면 새로고침된다', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/dev/kit?s=forms', { touch: true });
  const cdp = await ctx.newCDPSession(page);
  const box = await page.locator('main').boundingBox();
  const at = (type, y) => cdp.send('Input.dispatchTouchEvent', { type, touchPoints: type === 'touchEnd' ? [] : [{ x: box.x + 100, y }] });
  await at('touchStart', box.y + 60);
  for (let y = box.y + 60; y <= box.y + 360; y += 20) await at('touchMove', y);
  await at('touchEnd', box.y + 360);
  await page.getByText('새로고침 1번').waitFor({ timeout: 3000 });
  await ctx.close();
});
test('검토 3 손잡이를 아래로 두 줄 끌면 두 칸 옮겨진다', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/cards/1');
  await page.getByRole('button', { name: '수정하기' }).click(); await page.getByRole('button', { name: '수정 완료' }).waitFor();
  const handle = page.getByRole('button', { name: '바닐라 라떼 ICE 우유는 225ml 넣는다. 옮기기' });
  await handle.scrollIntoViewIfNeeded(); await page.waitForTimeout(200);
  const box = await handle.boundingBox();
  const rowHeight = await handle.evaluate((el) => el.closest('li').getBoundingClientRect().height);
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2); await page.mouse.down();
  // 손잡이 줄에서 왼쪽으로 벗어나 끌고, 벗어난 자리에서 놓는다(줄이 DOM 에서 옮겨지며 포인터 붙잡기가 풀리는 경우)
  await page.mouse.move(box.x - 150, box.y + box.height / 2 + rowHeight * 1.8, { steps: 24 }); await page.mouse.up();
  const iceOrder = async () => (await page.locator('[data-testid="fact-row"]').allInnerTexts()).filter((t) => /ICE/.test(t)).map((t) => t.split('\n')[0]);
  const ice = await iceOrder();
  assert.ok(ice[2].includes('우유는 225ml'), JSON.stringify(ice));
  // 놓은 뒤 누르지 않고 손잡이 위를 지나가도 순서가 바뀌면 안 된다
  const other = await page.getByRole('button', { name: /옮기기$/ }).filter({ hasNotText: '카테고리' }).first().boundingBox();
  await page.mouse.move(other.x + 10, other.y + 10); await page.mouse.move(other.x + 10, other.y + 200, { steps: 10 });
  assert.deepEqual(await iceOrder(), ice);
  await ctx.close();
});
test('검토 4 검수 필요 카드에 걸린 제안은 뱃지를 두 번 세지 않는다', async (b) => {
  const { page, ctx, api } = await open(b, 'OWNER', '/owner/cards?status=approved');
  api.state.proposals[0].target_card_id = 3;
  await page.reload({ waitUntil: 'networkidle' });
  assert.equal((await page.getByRole('group', { name: '카드 상태' }).getByRole('button', { name: /검수 필요/ }).innerText()).replace(/\D/g, ''), '1');
  await ctx.close();
});
test('검토 5 승인하면 함께 공개되는 다른 카드를 알려 준다', async (b) => {
  const { page, ctx, api } = await open(b, 'OWNER', '/owner/cards/proposals');
  api.state.proposals[0].affected_cards = [{ card_id: 1, title: '바닐라 라떼' }, { card_id: 5, title: '원두 보관 위치' }];
  await page.reload({ waitUntil: 'networkidle' });
  await page.getByText(/함께 공개돼요/).waitFor();
  assert.ok((await page.getByText(/함께 공개돼요/).innerText()).includes('원두 보관 위치'));
  await ctx.close();
});

test('o05c 레시피 카테고리는 두 칸, 나머지는 한 칸씩(2026-11-07 스케치)', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/cards');
  const widths = async (name) => page.getByRole('region', { name }).locator('[data-status]').evaluateAll((els) => els.map((e) => Math.round(e.getBoundingClientRect().width)));
  const section = async (name) => Math.round(await page.getByRole('region', { name }).evaluate((e) => e.getBoundingClientRect().width));
  const recipe = await widths('음료 레시피'), full = await section('음료 레시피');
  assert.ok(recipe.every((w) => w < full / 2 + 4), `레시피 ${recipe} / ${full}`);
  const stock = await widths('재고 위치'), stockFull = await section('재고 위치');
  assert.ok(stock.every((w) => w > stockFull - 8), `재고 ${stock} / ${stockFull}`);
  await ctx.close();
});

// ── 사용자 실화면 지적(2026-11-07) ──
test('실화면 1 밀지 않은 카드 뒤 동작 버튼은 보이지 않는다', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/cards');
  await page.getByRole('link', { name: /원두 보관 위치/ }).waitFor();
  const hidden = await page.locator('main').evaluate((main) => [...main.querySelectorAll('button[aria-label]')]
    .filter((el) => /(^|\s)(공개|미공개|삭제|빼기)$/.test(el.getAttribute('aria-label') ?? '') && el.className.includes('absolute'))
    .map((el) => getComputedStyle(el).opacity));
  assert.ok(hidden.length > 0, '밀기 버튼이 있어야 한다');
  assert.ok(hidden.every((o) => o === '0'), JSON.stringify(hidden));
  await ctx.close();
});
test('실화면 2 상태 칩 줄이 눌리지 않고 다 보인다', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/cards');
  const bar = page.getByRole('group', { name: '카드 상태' });
  await bar.waitFor();
  assert.ok((await bar.boundingBox()).height >= 36);
  await ctx.close();
});
test('실화면 3 정리 중인 작업은 오늘 매장에 진행 줄로', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner', { overrides: { job: { status: 'EXTRACTING' } } });
  const row = page.locator('[data-active-job]');
  await row.getByText('읽는 중').waitFor();
  await row.click(); await to(page, '/owner/jobs/7');
  await ctx.close();
});

run();
