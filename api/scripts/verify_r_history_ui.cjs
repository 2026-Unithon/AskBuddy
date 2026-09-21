// 최신 이력·미해결 질문 갱신 회귀. 실제 UI + 합성 API이며 운영 자료를 사용하지 않는다.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const response = (action, message) => ({ action, message,
  context_id: action === 'CLARIFY' ? '11111111-1111-4111-8111-111111111111' : null,
  allowed_options: action === 'CLARIFY' ? ['HOT', 'ICE'] : [],
  pending_id: action === 'ESCALATE' ? '1' : null, citations: [] });
const message = (id, action, content) => ({ message_id: String(id), sender: 'BUDDY', content,
  receipt_id: String(id), original_question: '합성 질문', response: response(action, content),
  context_revision: action === 'CLARIFY' ? 1 : null, owner_answer_id: null, revision: null, knowledge_status: null });

(async () => {
  const channel = process.env.R_UI_BROWSER_CHANNEL || (process.platform === 'win32' ? 'msedge' : undefined);
  const browser = await chromium.launch({ ...(channel ? { channel } : {}), headless: true });
  let checks = 0;
  const check = (name, value) => { assert.ok(value, name); checks++; console.log('PASS history UI', name); };
  async function setup(count, pending = false) {
    const state = { calls: 0, pending, messages: Array.from({ length: count }, (_, i) =>
      message(i+1, pending ? (i === 0 ? 'ESCALATE' : 'ANSWER') : (i === count-1 ? 'CLARIFY' : 'ANSWER'), `합성 기록 ${i+1}`)) };
    const ctx = await browser.newContext({ viewport: { width: 390, height: 844 } });
    await ctx.addInitScript(() => localStorage.setItem('askbuddy_state', JSON.stringify({ v: 8,
      data: { token: 'synthetic-ui-only', role: 'STAFF', storeId: 1, userId: 2, storeName: '합성 UI 매장' } })));
    await ctx.route('**/*', async route => {
      const req = route.request(), url = new URL(req.url()), path = url.pathname;
      if (url.origin === 'http://127.0.0.1:3011') return route.continue();
      let payload;
      if (path === '/app/bootstrap') payload = { user: { user_id: 2, role: 'STAFF', name: '합성 직원' },
        store: { store_id: 1, store_name: '합성 UI 매장', guide_completed: true, category_version: 1 },
        badges: { waiting_questions: 0, pending_cards: 0 }, default_destination: '/staff/roadmap' };
      else if (path === '/learn/v2/sessions') payload = { sessions: [{ session_id: '1' }] };
      else if (path.endsWith('/history')) {
        assert.equal(url.searchParams.get('latest'), 'true');
        state.calls++;
        const available = state.messages.filter(m => Number(m.message_id) < Number(url.searchParams.get('before') || Number.MAX_SAFE_INTEGER));
        const rows = available.slice(-100);
        payload = { messages: rows, next_before: available.length > 100 ? rows[0].message_id : null, has_pending_updates: state.pending };
      } else if (path === '/learn/v2/chat') {
        const body = req.postDataJSON();
        const action = body.policy_receipt_id ? 'ESCALATE' : body.question === '합성 안전 질문' ? 'SAFE_ROUTE' : 'ANSWER';
        const content = `저장 완료 ${action}`;
        const id = Number(state.messages.at(-1).message_id)+1;
        state.messages.push({ ...message(id, null, body.question), sender: 'USER', response: null });
        state.messages.push(message(id+1, action, content));
        payload = response(action, content);
      } else return route.fulfill({ status: 404, body: '{}' });
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(payload) });
    });
    const page = await ctx.newPage(), errors = [];
    page.on('pageerror', e => errors.push(e.message));
    await page.goto('http://127.0.0.1:3011/staff/chat/v2?session_id=1');
    await page.getByText(`합성 기록 ${count}`, { exact: true }).waitFor();
    return { ctx, page, state, errors };
  }
  try {
    for (const count of [99, 100, 101, 200]) {
      const { ctx, page, state, errors } = await setup(count);
      check(`${count} newest page bounded`, await page.locator('ol li').count() === Math.min(count, 100));
      check(`${count} older cursor exact`, await page.getByRole('button', { name: '이전 대화 기록 보기' }).count() === Number(count > 100));
      check(`${count} latest clarification immediately usable`, await page.getByRole('button', { name: 'HOT', exact: true }).isVisible());
      await page.getByRole('button', { name: 'HOT', exact: true }).click();
      await page.getByText('저장 완료 ANSWER', { exact: true }).waitFor();
      check(`${count} submitted answer appears without paging`, true);
      await page.getByLabel('업무 질문').fill('합성 안전 질문');
      await page.getByRole('button', { name: '질문하기', exact: true }).click();
      await page.getByTestId('r-policy-confirm').waitFor();
      await page.reload();
      await page.getByTestId('r-policy-confirm').click();
      await page.getByText('저장 완료 ESCALATE', { exact: true }).waitFor();
      check(`${count} latest safety confirmation survives reload`, true);
      while (await page.getByRole('button', { name: '이전 대화 기록 보기' }).count()) {
        const previous = await page.locator('ol li').count();
        await page.getByRole('button', { name: '이전 대화 기록 보기' }).click();
        await page.waitForFunction(n => document.querySelectorAll('ol li').length > n, previous);
      }
      check(`${count} all older records restored without duplication`, await page.locator('ol li').count() === state.messages.length);
      const texts = await page.locator('ol li > p.whitespace-pre-wrap').allTextContents();
      assert.deepEqual(texts, state.messages.map(m => m.content));
      check(`${count} oldest to newest order preserved`, true);
      await page.getByLabel('업무 질문').fill('기록을 펼친 뒤 새 질문');
      const expectedCount = state.messages.length + 2;
      await page.getByRole('button', { name: '질문하기', exact: true }).click();
      await page.waitForFunction(n => document.querySelectorAll('ol li').length === n, expectedCount);
      check(`${count} refetch of multiple pages preserves every row`, await page.locator('ol li').count() === state.messages.length);
      assert.deepEqual(errors, []);
      await ctx.close();
    }
    const { ctx, page, state, errors } = await setup(201, true);
    check('pending question is outside visible page', await page.getByText('합성 기록 1', { exact: true }).count() === 0);
    state.messages.push({ ...message(202, null, '기다리던 점주 답변'), response: null,
      owner_answer_id: '1', revision: 1, knowledge_status: 'PENDING' });
    await page.getByText('기다리던 점주 답변', { exact: true }).waitFor({ timeout: 12000 });
    check('earlier pending reply arrives automatically after later answers', true);
    state.messages.at(-1).knowledge_status = 'PUBLISHED'; state.pending = false;
    await page.getByText('답변 1 · 지식 반영: 공개 완료', { exact: true }).waitFor({ timeout: 12000 });
    const calls = state.calls;
    await page.waitForTimeout(6200);
    check('resolved session stops polling', state.calls === calls);
    await page.reload();
    await page.getByText('기다리던 점주 답변', { exact: true }).waitFor();
    check('latest owner delivery survives reload', true);
    assert.deepEqual(errors, []);
    await ctx.close();
    console.log(`Verified ${checks} history browser checks`);
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
