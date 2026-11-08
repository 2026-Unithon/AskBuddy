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
test('COPY-1 사실 고치기의 하지 않음은 스위치 줄', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/cards/1');
  await startEdit(page);
  // 수정 화면에서 줄을 누르면 고치는 시트(2026-11-08, 길게 누르기 메뉴 없앰)
  await page.locator('[data-testid="fact-row"]').filter({ hasText: '뚜껑을 닫는다.' }).getByRole('button', { name: /^고치기: / }).click();
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
  // 업로드(PUT)가 실제로 시작돼 시간 재기가 걸린 뒤에 시계를 돌린다
  while (!api.calls.some((c) => c.path === '/storage/put')) await page.waitForTimeout(20);
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

// ── 근무조 기본 모두 켜짐(2026-11-08 사용자) ──
test('SHIFT-1 할 일 카드는 공통 없이 근무조 스위치만, 공통이면 모두 켜짐', async (b) => {
  const { page, ctx, api } = await open(b, 'OWNER', '/owner/cards/6', { overrides: { cardLinks: { 6: { checklist: true, shift_ids: [] } } } });
  const group = page.getByRole('group', { name: '어느 근무조 할 일인가요?' });
  await group.getByRole('switch', { name: '오픈' }).waitFor();
  assert.equal(await group.getByRole('switch', { name: '공통' }).count(), 0);
  for (const name of ['오픈', '미들', '마감']) assert.equal(await group.getByRole('switch', { name }).getAttribute('aria-checked'), 'true', name);
  await group.getByRole('switch', { name: '미들' }).click();
  await page.waitForFunction(() => true);
  const puts = () => api.calls.filter((c) => c.method === 'PUT' && c.path === '/checklist/cards/6').map((c) => c.body);
  while (puts().length < 1) await page.waitForTimeout(50);
  assert.deepEqual(puts()[0], { checklist: true, shift_ids: [1, 3] });
  await group.getByRole('switch', { name: '미들' }).and(page.locator('[aria-checked=false]')).waitFor();
  await group.getByRole('switch', { name: '미들' }).click();
  while (puts().length < 2) await page.waitForTimeout(50);
  assert.deepEqual(puts()[1], { checklist: true, shift_ids: [] }, '다 켜면 공통');
  await ctx.close();
});
test('SHIFT-2 레시피 카드는 근무조를 묻지 않는다', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/cards/1', { overrides: { tableRecipe: true } });
  await page.locator('[data-recipe-view]').waitFor();
  assert.equal(await page.getByText('어느 근무조 할 일인가요?').count(), 0);
  await ctx.close();
});

// ── Task 7 카드 ──
test("CARD-1 상세에서 삭제 되돌리기가 실패하면 '다시' 스낵바", async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/cards/5', { overrides: { singleFactCard: true, failRestore: true } });
  await startEdit(page);
  await page.getByRole('button', { name: /^빼기: / }).click();
  await page.getByRole('dialog').getByRole('button', { name: '카드 지우기' }).click();
  await page.getByRole('status').getByRole('button', { name: '되돌리기' }).click();
  const bar = page.getByRole('status').filter({ hasText: '되돌리지 못했어요' });
  await bar.getByRole('button', { name: '다시' }).waitFor();
  await ctx.close();
});
test('CARD-2 타일을 누르는 순간 상세를 미리 받는다', async (b) => {
  const { page, ctx, api } = await open(b, 'OWNER', '/owner/cards');
  const tile = page.getByRole('link', { name: /^아메리카노/ });
  await tile.dispatchEvent('pointerdown');
  for (let i = 0; i < 40 && !api.calls.some((c) => c.method === 'GET' && c.path === '/cards/2'); i++) await page.waitForTimeout(50);
  assert.ok(api.calls.some((c) => c.method === 'GET' && c.path === '/cards/2'), '누르는 순간 상세 조회');
  await ctx.close();
});
test('CARD-3 손잡이 이름은 순서와 문장 전체, 카테고리 칩은 바꾸기', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/cards/1');
  await page.getByRole('button', { name: '카테고리 바꾸기, 지금 음료 레시피' }).waitFor();
  await startEdit(page);
  await page.getByRole('button', { name: '3번 물을 붓는다. 옮기기', exact: true }).waitFor();
  await page.getByRole('button', { name: '바닐라 라떼 ICE 우유는 225ml 넣는다. 옮기기', exact: true }).waitFor();
  await ctx.close();
});
test("CARD-4 다른 답이 있는 타일은 이름표에 '다른 답이 있어요'", async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/cards');
  await page.getByRole('link', { name: '바닐라 라떼, 검수 필요, 다른 답이 있어요' }).waitFor();
  await ctx.close();
});
test('CARD-5 제안 타일도 카테고리 필터를 따른다', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/cards?status=needs_review&category_id=11');
  await page.getByRole('link', { name: /^마감 머신 청소/ }).waitFor();
  assert.equal(await page.getByRole('link', { name: /^바닐라 라떼/ }).count(), 0);
  await ctx.close();
});
test('CARD-6 수정 중에는 뒤로 버튼을 숨긴다', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/cards/1');
  await startEdit(page);
  assert.equal(await page.locator('[data-back]').count(), 0);
  await page.getByRole('button', { name: '돌아가기' }).click();
  await page.locator('[data-back]').waitFor();
  await ctx.close();
});
test("CARD-7 제안을 쓰지 않으면 카드 목록으로", async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/cards/proposals?card_id=1');
  await page.getByRole('button', { name: '이 답은 쓰지 않기' }).click();
  await to(page, '/owner/cards?status=needs_review');
  await ctx.close();
});
test('CARD-8 공개 밀기를 연달아 해도 한 번만 보낸다', async (b) => {
  const { page, ctx, api } = await open(b, 'OWNER', '/owner/cards?status=pending', { overrides: { approveDelayMs: 800 } });
  const action = page.getByRole('button', { name: '오픈 준비 공개' });
  await action.evaluate((el) => { el.click(); el.click(); });
  await page.waitForTimeout(200);
  if (await action.count()) await action.evaluate((el) => el.click());
  await page.waitForTimeout(1200);
  assert.equal(api.calls.filter((c) => c.method === 'POST' && c.path === '/cards/4/approve').length, 1);
  await ctx.close();
});

// ── Task 8 오늘 매장·질문 ──
test('Q-1 다음 질문으로 가면 앞 질문이 비치지 않고 새 입력창', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/questions/101');
  await page.getByLabel('직원에게 보낼 답').fill('창고 오른쪽 맨 위 칸');
  await page.getByRole('button', { name: '넣기' }).click();
  await page.getByText('답을 보냈어요').waitFor();
  await page.evaluate(() => {
    window.__flash = false;
    new MutationObserver(() => {
      if ([...document.querySelectorAll('h1')].some((h) => h.textContent === '디카페인 원두는 어디 있어요?')) window.__flash = true;
    }).observe(document.body, { subtree: true, childList: true, characterData: true });
  });
  await page.getByRole('button', { name: '다음 질문 1개' }).click();
  await to(page, '/owner/questions/102');
  await page.getByRole('heading', { name: '오트밀크 라떼도 시럽 2펌프인가요?' }).waitFor();
  assert.equal(await page.evaluate(() => window.__flash), false, '앞 질문 화면이 비치지 않는다');
  assert.equal(await page.getByLabel('직원에게 보낼 답').inputValue(), '');
  await ctx.close();
});
test("Q-2 답 첨부 종류 칩은 '다음에 붙일 파일 종류'", async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/questions/101');
  await page.locator('input[type=file]').first().setInputFiles({ name: '창고 사진.jpg', mimeType: 'image/jpeg', buffer: Buffer.from('jpg') });
  await page.getByRole('group', { name: '다음에 붙일 파일 종류' }).waitFor();
  await page.getByText('다음에 붙일 파일 종류', { exact: true }).waitFor();
  await ctx.close();
});
test("Q-3 질문이 하나뿐이면 나중에를 눌러도 알려 주고, 버튼 이름에 질문", async (b) => {
  const one = [{ pending_id: '101', question: '디카페인 원두는 어디 있어요?', status: 'WAITING', answers: [] }];
  const { page, ctx } = await open(b, 'OWNER', '/owner', { overrides: { pending: one } });
  await page.getByRole('button', { name: '디카페인 원두는 어디 있어요? 나중에' }).press('Enter');
  await page.getByRole('status').getByText('다른 질문이 없어 그대로 둘게요').waitFor();
  await ctx.close();
});
test('Q-4 세그먼트는 누름 버튼, 숫자는 이름과 함께 읽힌다', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/questions');
  const seg = page.getByRole('group', { name: '질문 보기' });
  const waiting = seg.getByRole('button', { name: '답변 대기 2', exact: true });
  assert.equal(await waiting.getAttribute('aria-pressed'), 'true');
  assert.equal(await page.getByRole('tab').count(), 0);
  await ctx.close();
});
test("Q-5 '물어본 말 보기'는 키보드 포커스 테두리", async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/questions/101');
  const button = page.getByRole('button', { name: '물어본 말 보기' });
  await button.focus();
  await page.keyboard.press('Shift+Tab'); await page.keyboard.press('Tab');
  const ring = await button.evaluate((el) => { const s = getComputedStyle(el); return `${s.outlineStyle} ${s.boxShadow}`; });
  assert.ok(!/^none none$/.test(ring), ring);
  await ctx.close();
});
test('TAB-1 활성 탭이 없으면 알약을 숨긴다', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/dev/kit?s=o6');
  const pill = page.locator('[data-tab-pill]');
  await pill.waitFor({ state: 'attached' });
  assert.equal(await pill.evaluate((el) => getComputedStyle(el).opacity), '0');
  await ctx.close();
});
test('CARDS-SEG 카드 상태 칩도 누름 버튼', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/cards');
  const group = page.getByRole('group', { name: '카드 상태' });
  assert.equal(await group.getByRole('button', { name: '전체', exact: true }).getAttribute('aria-pressed'), 'true');
  await ctx.close();
});

// ── Task 9 설정·관리 ──
test('SET-1 근무조 시간 오류는 값을 바꾸면 사라진다', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/shifts');
  await page.getByRole('button', { name: '고치기' }).first().click();
  const sheet = page.getByRole('dialog', { name: '근무조 고치기' });
  await sheet.getByRole('listbox', { name: '끝 시' }).getByRole('option', { name: '08' }).click();
  await sheet.getByRole('listbox', { name: '끝 분' }).getByRole('option', { name: '00' }).click();
  await sheet.getByRole('button', { name: '저장', exact: true }).click();
  await sheet.getByRole('alert').getByText('시작과 끝을 다르게 골라 주세요.').waitFor();
  await sheet.getByRole('listbox', { name: '끝 시' }).getByRole('option', { name: '09' }).click();
  await sheet.getByText('시작과 끝을 다르게 골라 주세요.').waitFor({ state: 'detached' });
  await ctx.close();
});
test('SET-2 직원 알림을 읽으면 설정의 답변 알림 숫자도 준다', async (b) => {
  const { page, ctx } = await open(b, 'STAFF', '/staff/settings');
  const link = page.getByRole('link', { name: /답변 알림/ });
  await link.getByText('3').waitFor();
  await link.click();
  await page.locator('[data-notice]').first().click();
  await page.waitForURL(/\/staff\/ask/);
  await page.goBack(); await page.goBack();
  await page.waitForURL(/\/staff\/settings/);
  await page.getByRole('link', { name: /답변 알림/ }).getByText('2').waitFor({ timeout: 3000 });
  await ctx.close();
});
test('SET-3 시간 휠은 지금 값을 aria-activedescendant 로 알린다', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/shifts');
  await page.getByRole('button', { name: '고치기' }).first().click();
  const hours = page.getByRole('dialog', { name: '근무조 고치기' }).getByRole('listbox', { name: '시작 시' });
  await hours.focus();
  await page.keyboard.press('ArrowDown');
  const active = await hours.getAttribute('aria-activedescendant');
  assert.ok(active, '활성 항목 id');
  assert.equal(await page.locator(`[id="${active}"]`).textContent(), '09');
  await ctx.close();
});
test('SET-4 안 읽은 알림이 없으면 안내를 봤음으로 저장하지 않는다', async (b) => {
  const read = [{ notification_id: 3, event_type: 'PENDING_QUESTION', aggregate_type: 'PENDING_QUESTION', aggregate_id: 101, title: '직원 질문이 왔어요', body: '디카페인', destination: '/owner/questions/101', delivery_status: 'REQUESTED', read_at: '2026-10-31T05:00:00Z', created_at: '2026-10-31T05:00:00Z' }];
  const { page, ctx } = await open(b, 'OWNER', '/owner/notifications', { overrides: { coach: true, notifications: read, unreadCount: 0 } });
  await page.locator('[data-notification]').first().waitFor();
  await page.waitForTimeout(3500);
  assert.equal(await page.evaluate(() => localStorage.getItem('askbuddy:coach:owner-notifications')), null);
  await ctx.close();
});
test('SET-5 카테고리 같은 이름은 대소문자를 가리지 않는다', async (b) => {
  const categories = [{ category_id: 10, name: 'Coffee', is_system: false, sort_order: 1 }, { category_id: 13, name: '기타', is_system: true, sort_order: 2 }];
  const { page, ctx } = await open(b, 'OWNER', '/owner/categories', { overrides: { categories } });
  await page.getByLabel('새 카테고리 이름').fill('coffee');
  await page.getByRole('alert').getByText('이미 있는 카테고리예요').waitFor();
  await ctx.close();
});

test("SET-6 밀어서 읽음이 실패하면 다시 받기 전에도 '읽지 않음' 점이 돌아온다", async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/owner/notifications', { overrides: { failRead: true, slowNotificationRefetchMs: 4000 } });
  const row = page.locator('[data-notification]').filter({ hasText: '카드 정리가 끝났어요' });
  await row.getByLabel('읽지 않음').waitFor();
  await page.getByRole('button', { name: '카드 정리가 끝났어요 읽음으로' }).focus();
  await page.keyboard.press('Enter');
  await page.getByText('읽음으로 바꾸지 못했어요.').waitFor();
  await row.getByLabel('읽지 않음').waitFor({ timeout: 500 });
  await ctx.close();
});

// ── Task 10 직원 화면 ──
const msg = (id, sender, content) => ({ message_id: String(id), sender, content, receipt_id: sender === 'BUDDY' ? `r${id}` : null, original_question: null, response: null, context_revision: null, owner_answer_id: null, revision: null, knowledge_status: null });
const chat = { sessions: [{ session_id: '1' }], messages: [msg(3, 'USER', '샷은 몇 개예요?'), msg(4, 'BUDDY', '샷은 2개예요.')], olderMessages: [msg(1, 'USER', '시럽은요?'), msg(2, 'BUDDY', '시럽은 2펌프예요.')] };
test('STAFF-1 이전 대화를 불러와도 옛 답은 타이핑하지 않는다', async (b) => {
  const { page, ctx } = await open(b, 'STAFF', '/staff/ask', { overrides: chat });
  await page.getByText('샷은 2개예요.').waitFor();
  await page.getByRole('button', { name: '이전 대화 보기' }).click();
  await page.getByText('시럽은 2펌프예요.').waitFor();
  assert.equal(await page.locator('[data-typing]').count(), 0);
  await ctx.close();
});
test('STAFF-1b 대화 목록이 실패한 뒤 다시 불러와도 옛 답은 타이핑하지 않는다', async (b) => {
  const { page, ctx, api } = await open(b, 'STAFF', '/staff/ask', { overrides: { ...chat, olderMessages: null, failSessions: 99 } });
  const retry = page.getByRole('button', { name: /다시/ }).first();
  await retry.waitFor({ timeout: 20000 });
  api.state.failSessions = 0;
  await retry.click();
  await page.getByText('샷은 2개예요.').waitFor();
  assert.equal(await page.locator('[data-typing]').count(), 0);
  await ctx.close();
});
test('STAFF-2 타이핑 중 글은 화면낭독기에 한 번에 읽힌다', async (b) => {
  const { page, ctx } = await open(b, 'STAFF', '/staff/ask', { overrides: { chatDelayMs: 0 } });
  await page.getByLabel('모르는 거 물어보기').fill('바닐라 라떼 시럽 몇 펌프예요?');
  await page.getByLabel('모르는 거 물어보기').press('Enter');
  const typing = page.locator('[data-typing]');
  await typing.waitFor();
  assert.equal(await typing.locator('[aria-hidden="true"]').count(), 1, '보이는 글은 숨김');
  assert.equal(await typing.locator('.sr-only').textContent(), 'ICE 바닐라 라떼는 바닐라 시럽 2펌프예요.');
  await ctx.close();
});
test('STAFF-3 밀기를 놓으면 판이 이동이 끝날 때까지 남는다', async (b) => {
  const { page, ctx } = await open(b, 'OWNER', '/dev/kit?s=gestures');
  const row = page.getByText('밀어 보세요');
  const box = await row.boundingBox();
  const y = box.y + box.height / 2;
  await page.mouse.move(box.x + box.width - 20, y); await page.mouse.down();
  for (let i = 1; i <= 3; i++) await page.mouse.move(box.x + box.width - 20 - i * 15, y);
  await page.mouse.up();
  const opacity = await page.getByRole('button', { name: '빼기', exact: true }).evaluate((el) => Number(getComputedStyle(el).opacity));
  assert.ok(opacity > 0, `놓은 순간 판이 바로 사라지지 않는다(${opacity})`);
  await ctx.close();
});
test('STAFF-4 레시피 시트는 닫히는 동안 제목을 지킨다', async (b) => {
  const { page, ctx } = await open(b, 'STAFF', '/staff');
  await page.getByRole('button', { name: '우유 발주', exact: true }).click();
  const sheet = page.getByRole('dialog', { name: '우유 발주' });
  await sheet.getByText(/오전 10시 전 발주/).waitFor();
  await page.keyboard.press('Escape');
  await page.waitForTimeout(60);
  if (await page.locator('dialog[open]').count()) assert.ok((await page.locator('dialog[open]').innerText()).includes('우유 발주'), '닫히는 동안 제목이 남는다');
  await ctx.close();
});
test('STAFF-5 제출 실패 뒤 다시 열면 옛 오류가 없다', async (b) => {
  const { page, ctx, api } = await open(b, 'STAFF', '/staff', { overrides: { failSubmit: true } });
  await page.getByTestId('checklist-submit').click();
  const dialog = page.getByRole('dialog', { name: /남았어요. 그래도 끝낼까요\?/ });
  await dialog.getByRole('button', { name: '그래도 끝내기' }).click();
  await dialog.getByRole('alert').waitFor();
  await dialog.getByRole('button', { name: '더 체크하기' }).click();
  await page.getByTestId('checklist-submit').click();
  await dialog.waitFor();
  assert.equal(await dialog.getByRole('alert').count(), 0);
  await ctx.close();
});
test('STAFF-6 세션 없는 옛 알림은 묻기 화면으로', async (b) => {
  const { page, ctx } = await open(b, 'STAFF', '/staff/notifications/v2', { overrides: { rNotifications: [{ notification_id: '52', title: '사장님 답이 왔어요', body: '창고 위 칸', destination: '/staff/ask', read: false }] } });
  await page.locator('[data-notice]').first().click();
  await to(page, '/staff/ask');
  await ctx.close();
});
test('STAFF-7 읽은 알림은 흐리게 하지 않는다', async (b) => {
  const { page, ctx } = await open(b, 'STAFF', '/staff/notifications/v2', { overrides: { rNotifications: [{ notification_id: '53', title: '사장님 답이 왔어요', body: '창고 위 칸', destination: '/staff/ask', read: true }] } });
  const notice = page.locator('[data-notice]').first();
  await notice.waitFor();
  assert.equal(await notice.evaluate((el) => getComputedStyle(el).opacity), '1');
  await ctx.close();
});
test('STAFF-8 추천 칩은 같은 질문을 한 번만', async (b) => {
  const faq = (card_id) => ({ question: '바닐라 라떼 시럽 몇 펌프예요?', question_count: 7, distinct_questioners: 3, last_asked_at: '2026-10-31T05:00:00Z', card_id, published_version_id: 10, card_title: '바닐라 라떼', card_content: 'x', category_id: 10, category_name: '음료 레시피' });
  const { page, ctx } = await open(b, 'STAFF', '/staff', { overrides: { faqs: [faq(1), faq(2)] } });
  await page.locator('[data-suggested]').first().waitFor();
  assert.equal(await page.locator('[data-suggested]').count(), 1);
  await ctx.close();
});

run();
