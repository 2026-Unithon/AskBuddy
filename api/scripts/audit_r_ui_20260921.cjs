// R-only audit: real Next UI, synthetic API; no real store/provider access.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const answer = (action, message) => ({ action, message, context_id: action === 'CLARIFY' ? '11111111-1111-4111-8111-111111111111' : null,
  allowed_options: action === 'CLARIFY' ? ['HOT', 'ICE'] : [], pending_id: action === 'ESCALATE' ? '1' : null, citations: [] });
const message = (id, action, content) => ({ message_id: String(id), sender: 'BUDDY', content,
  receipt_id: String(id), original_question: '합성 질문', response: answer(action, content),
  context_revision: action === 'CLARIFY' ? 1 : null, owner_answer_id: null, revision: null, knowledge_status: null });

(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  try {
    for (const scenario of ['pagination', 'earlier_pending']) {
      const state = { calls: 0, asks: 0, messages: scenario === 'pagination'
        ? Array.from({ length: 100 }, (_, i) => message(i+1, i===99 ? 'CLARIFY' : 'ANSWER', `합성 기록 ${i+1}`))
        : [message(1, 'ESCALATE', '먼저 한 질문은 점주 확인 대기'), message(2, 'ANSWER', '나중 질문은 답변 완료')] };
      const ctx = await browser.newContext({ viewport: { width: 390, height: 844 } });
      await ctx.addInitScript(() => localStorage.setItem('askbuddy_state', JSON.stringify({ v: 8,
        data: { token: 'synthetic-ui-only', role: 'STAFF', storeId: 1, userId: 2, storeName: '합성 UI 매장' } })));
      await ctx.route('**/*', async route => {
        const req = route.request(), url = new URL(req.url()), p = url.pathname;
        if (url.origin === 'http://127.0.0.1:3011') return route.continue();
        let payload;
        if (p === '/app/bootstrap') payload = { user: { user_id: 2, role: 'STAFF', name: '합성 직원' },
          store: { store_id: 1, store_name: '합성 UI 매장', guide_completed: true, category_version: 1 },
          badges: { waiting_questions: 0, pending_cards: 0 }, default_destination: '/staff/roadmap' };
        else if (p === '/learn/v2/sessions') payload = { sessions: [{ session_id: '1' }] };
        else if (p.endsWith('/history')) {
          state.calls++;
          const rows = state.messages.filter(m => Number(m.message_id) > Number(url.searchParams.get('after') || 0)).slice(0, 100);
          payload = { messages: rows, next_after: rows.length === 100 ? rows.at(-1).message_id : null };
        } else if (p === '/learn/v2/chat') {
          state.asks++;
          state.messages.push(message(101, 'ANSWER', '새 질문 서버 저장'), message(102, 'ANSWER', '새 답변 서버 저장'));
          payload = answer('ANSWER', '새 답변 서버 저장');
        } else return route.fulfill({ status: 404, body: '{}' });
        return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(payload) });
      });
      const page = await ctx.newPage();
      const errors = [];
      page.on('pageerror', e => errors.push(e.message));
      await page.goto('http://127.0.0.1:3011/staff/chat/v2?session_id=1');
      await page.locator('ol li').first().waitFor();
      if (scenario === 'pagination') {
        await page.getByText('합성 기록 100', { exact: true }).waitFor();
        const initialChoices = await page.getByRole('button', { name: 'HOT', exact: true }).count();
        await page.getByLabel('업무 질문').fill('새 합성 질문');
        await page.getByRole('button', { name: '질문하기', exact: true }).click();
        await page.waitForFunction(() => document.querySelector('#r-question').value === '');
        const visibleAfterSuccess = await page.getByText('새 답변 서버 저장', { exact: true }).count();
        assert.equal(state.asks, 1);
        console.log(JSON.stringify({ scenario, initialChoices, storedMessages: state.messages.length, visibleAfterSuccess }));
        await page.getByRole('button', { name: '다음 대화 기록 보기' }).click();
        await page.getByText('새 답변 서버 저장', { exact: true }).waitFor();
        console.log(JSON.stringify({ scenario, manualNextPageRevealsAnswer: true }));
      } else {
        await page.getByText('나중 질문은 답변 완료', { exact: true }).waitFor();
        const before = state.calls;
        state.messages.push({ ...message(3, 'ANSWER', '기다리던 점주 답변'), response: null,
          owner_answer_id: '1', revision: 1, knowledge_status: 'PENDING' });
        await page.waitForTimeout(6200);
        const visible = await page.getByText('기다리던 점주 답변', { exact: true }).count();
        console.log(JSON.stringify({ scenario, historyRequestsAfterArrival: state.calls-before, ownerReplyVisible: visible }));
        await page.getByRole('button', { name: '새 답변 확인', exact: true }).click();
        await page.getByText('기다리던 점주 답변', { exact: true }).waitFor();
        console.log(JSON.stringify({ scenario, manualRefreshRevealsReply: true }));
      }
      assert.deepEqual(errors, []);
      await ctx.close();
    }
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
