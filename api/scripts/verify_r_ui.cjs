// 실제 브라우저 UI 상태 검사. API는 명시적 합성 fixture이며 DB E2E와 구분한다.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

(async () => {
  const channel = process.env.R_UI_BROWSER_CHANNEL || (process.platform === 'win32' ? 'msedge' : undefined);
  const browser = await chromium.launch({ ...(channel ? { channel } : {}), headless: true });
  const passed = [];
  const check = (name, value) => { assert.ok(value, name); passed.push(name); console.log('PASS UI', name); };
  const state = { sessions: [], messages: [], answers: [], notices: [], failNotices: false, failRead: false, calls: 0, failNext: false, pending: false, next: 1 };
  function message(content, sender, response = null, extra = {}) {
    return { message_id: String(state.next++), sender, content, response, receipt_id: response ? '1' : null,
      context_revision: response?.action === 'CLARIFY' ? 1 : null, owner_answer_id: null, knowledge_status: null, ...extra };
  }
  const response = (action, text) => ({ action, message: text, context_id: action === 'CLARIFY' ? '11111111-1111-4111-8111-111111111111' : null,
    allowed_options: action === 'CLARIFY' ? ['HOT', 'ICE'] : [], pending_id: action === 'ESCALATE' ? '1' : null,
    citations: action === 'ANSWER' ? [{ card_id: '1', card_version_id: '2', block_id: 'b1', source_availability: 'AVAILABLE' }] : [] });
  async function context(role) {
    const ctx = await browser.newContext({ viewport: { width: 390, height: 844 } });
    await ctx.addInitScript((role) => localStorage.setItem('askbuddy_state', JSON.stringify({ v: 8,
      data: { token: 'synthetic-ui-only', role, storeId: 1, userId: role === 'OWNER' ? 1 : 2, storeName: '합성 UI 매장' } })), role);
    await ctx.route('http://localhost:8000/**', async (route) => {
      const req = route.request(), url = new URL(req.url()), p = url.pathname;
      const body = req.method() === 'POST' ? req.postDataJSON() : null;
      let payload;
      if (p === '/app/bootstrap') {
        payload = { user: { user_id: role === 'OWNER' ? 1 : 2, role, name: '합성 사용자' },
          store: { store_id: 1, store_name: '합성 UI 매장', guide_completed: true, category_version: 1 },
          badges: { waiting_questions: 0, pending_cards: 0 },
          default_destination: role === 'OWNER' ? '/owner/upload' : '/staff/roadmap' };
      } else if (p.endsWith('/read') && p.includes('/notifications/')) {
        if (state.failRead) { state.failRead = false; await route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ error: { message: '알림 읽음 저장 실패' } }) }); return; }
        const id = p.split('/').at(-2);
        state.notices.find((n) => n.notification_id === id).read = true;
        payload = { notification_id: id, read: true };
      } else if (p === '/learn/v2/notifications') {
        if (state.failNotices) { await route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ error: { message: '알림 조회 실패' } }) }); return; }
        const remaining = state.notices.filter((n) => Number(n.notification_id) > Number(url.searchParams.get('after') ?? 0));
        payload = { notifications: remaining.slice(0, 1), next_after: remaining.length > 1 ? remaining[0].notification_id : null };
      } else if (p === '/learn/v2/sessions') {
        if (body) { state.sessions = [{ session_id: '1' }]; payload = { session_id: '1' }; }
        else payload = { sessions: state.sessions };
      } else if (p.includes('/history')) payload = { messages: state.messages, next_after: null };
      else if (p.includes('/citations/')) payload = { title: '합성 라테', text: 'HOT 합성 라테 물 225ml', source_availability: 'AVAILABLE', card_version_id: '2' };
      else if (p === '/learn/v2/chat') {
        state.calls++;
        if (state.failNext) { state.failNext = false; await route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ error: { message: '합성 장애: 다시 시도해 주세요.' } }) }); return; }
        await new Promise((resolve) => setTimeout(resolve, body.policy_receipt_id ? 700 : 200));
        if (body.policy_receipt_id) { assert.equal(body.policy_receipt_id, '1'); assert.equal(body.question, '알레르기 확인'); payload = response('ESCALATE', '안전 질문의 확인을 요청했어요.'); }
        else if (body.question === '알레르기 확인') payload = response('SAFE_ROUTE', '안전 여부를 추측하지 않습니다.');
        else if (body.question === '개인정보 질문') payload = response('REFUSE', '개인정보를 제공할 수 없습니다.');
        else if (body.question === '미확인 업무') { state.pending = true; payload = response('ESCALATE', '사장님께 확인을 요청했어요.'); }
        else if (body.option) { assert.equal(body.context_revision, 1); payload = response('ANSWER', 'HOT 합성 라테 물 225ml'); }
        else payload = response('CLARIFY', '어느 경우인지 선택해 주세요.');
        state.messages.push(message(body.question, 'USER'), message(payload.message, 'BUDDY', payload, { original_question: body.question }));
      } else if (p === '/learn/v2/pending') payload = { questions: state.pending ? [{ pending_id: '1', question: '미확인 업무', status: state.answers.length ? 'ANSWERED' : 'WAITING' }] : [], next_after: null };
      else if (p.endsWith('/answers')) {
        state.answers.push({ owner_answer_id: '1', answer: body.answer, revision: 1, knowledge_status: 'PENDING' });
        state.notices.push({ notification_id: '1', title: '사장님 답변 도착', body: '요청한 질문에 답변이 도착했어요.', destination: '/staff/chat/v2?session_id=1', read: false });
        state.messages.push(message(body.answer, 'BUDDY', null, { owner_answer_id: '1', revision: 1, knowledge_status: 'PENDING' }));
        payload = { owner_answer_id: '1', knowledge_status: 'PENDING' };
      } else if (p === '/learn/v2/pending/1') payload = { pending_id: '1', status: 'WAITING',
        occurrences: [{ receipt_id: '1', original_question: '미확인 업무', resolved_query: { confirmed_slots: { entity: '합성 라테' } }, context_snapshot: null }], answers: state.answers };
      else if (p.includes('/ingest/')) payload = { items: [] };
      else { await route.fulfill({ status: 404, body: '{}' }); return; }
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(payload) });
    });
    return ctx;
  }
  try {
    const staff = await context('STAFF'), page = await staff.newPage();
    const errors = [];
    page.on('pageerror', (e) => errors.push(e.message));
    await page.goto('http://127.0.0.1:3011/staff/chat/v2');
    await page.getByText('새 대화를 시작해 업무를 질문해 보세요.').waitFor();
    check('empty state distinct', true);
    await page.getByRole('link', { name: '답변 알림', exact: true }).click();
    await page.getByText('아직 도착한 답변 알림이 없습니다.', { exact: false }).waitFor();
    check('notification empty state distinct', true);
    await page.getByRole('link', { name: '대화로 돌아가기' }).click();
    await page.getByRole('button', { name: '새 대화', exact: true }).click();
    await page.waitForURL('**session_id=1');
    await page.getByLabel('업무 질문').fill('합성 라테 물 얼마나?');
    await page.getByRole('button', { name: '질문하기', exact: true }).click();
    await page.getByRole('button', { name: 'HOT', exact: true }).waitFor();
    await page.reload();
    await page.getByRole('button', { name: 'HOT', exact: true }).click();
    await page.getByText('HOT 합성 라테 물 225ml', { exact: true }).waitFor();
    check('clarification survives reload', state.calls === 2);
    await page.getByRole('button', { name: '근거 1 확인' }).click();
    await page.getByText('합성 라테', { exact: true }).waitFor();
    check('approved citation expands', true);
    state.failNext = true;
    await page.getByLabel('업무 질문').fill('미확인 업무');
    await page.getByRole('button', { name: '질문하기', exact: true }).click();
    await page.getByRole('alert').waitFor();
    check('failed submit retains input', await page.getByLabel('업무 질문').inputValue() === '미확인 업무');
    await page.getByRole('button', { name: '다시 확인', exact: true }).click();
    await page.getByText('사장님께 확인을 요청했어요.', { exact: true }).waitFor();
    check('retry reaches stored escalation', true);
    const owner = await context('OWNER'), ownerPage = await owner.newPage();
    ownerPage.on('pageerror', (e) => errors.push(e.message));
    await ownerPage.goto('http://127.0.0.1:3011/owner/questions/v2?question_id=1');
    await ownerPage.getByLabel('직원에게 보낼 답변').fill('  점주 원문\n그대로  ');
    await ownerPage.getByRole('button', { name: '답변 저장', exact: true }).click();
    await ownerPage.getByText('답변이 저장됐습니다.', { exact: true }).waitFor();
    check('owner raw submission preserved', state.answers[0].answer === '  점주 원문\n그대로  ');
    await page.reload();
    await page.getByText('사장님 답변', { exact: true }).waitFor();
    check('staff original delivery survives reload', (await page.locator('ol').innerText()).includes('점주 원문'));
    await page.getByLabel('업무 질문').fill('개인정보 질문');
    await page.getByRole('button', { name: '질문하기', exact: true }).click();
    await page.getByText('개인정보를 제공할 수 없습니다.', { exact: true }).waitFor();
    check('REFUSE offers no policy confirmation', await page.getByTestId('r-policy-confirm').count() === 0);
    await page.getByLabel('업무 질문').fill('알레르기 확인');
    await page.getByRole('button', { name: '질문하기', exact: true }).click();
    await page.getByTestId('r-policy-confirm').waitFor();
    await page.reload();
    await page.getByTestId('r-policy-confirm').waitFor();
    check('SAFE_ROUTE confirmation survives reload', true);
    const policyOut = path.resolve(__dirname, '../tmp/r-ui'); fs.mkdirSync(policyOut, { recursive: true });
    await page.screenshot({ path: path.join(policyOut, 'policy.png'), fullPage: true });
    await page.getByLabel('업무 질문').fill('작성 중인 다른 질문');
    state.failNext = true;
    await page.getByTestId('r-policy-confirm').click();
    await page.getByRole('alert').waitFor();
    check('confirmation failure keeps draft and offers retry', await page.getByLabel('업무 질문').inputValue() === '작성 중인 다른 질문');
    await page.getByRole('button', { name: '다시 확인', exact: true }).click();
    await page.locator('[data-testid="r-policy-confirm"][disabled]').waitFor();
    check('confirmation button disabled while request pending', await page.getByTestId('r-policy-confirm').isDisabled());
    await page.getByText('안전 질문의 확인을 요청했어요.', { exact: true }).waitFor();
    check('successful confirmation preserves unrelated draft', await page.getByLabel('업무 질문').inputValue() === '작성 중인 다른 질문');
    await page.reload();
    await page.getByText('안전 질문의 확인을 요청했어요.', { exact: true }).waitFor();
    check('completed confirmation no longer offers duplicate button', await page.getByTestId('r-policy-confirm').count() === 0);
    state.notices.push({ notification_id: '2', title: '합성 경로 검사', body: '외부 주소를 열지 않습니다.', destination: 'https://example.invalid/', read: false });
    state.failNotices = true;
    await page.goto('http://127.0.0.1:3011/staff/notifications/v2');
    await page.getByText('알림 조회 실패', { exact: true }).waitFor();
    check('notification fetch failure shown as error', await page.getByText('아직 도착한 답변 알림이 없습니다.', { exact: false }).count() === 0);
    state.failNotices = false;
    await page.getByRole('button', { name: '다시 확인', exact: true }).click();
    await page.getByText('사장님 답변 도착 · 읽지 않음', { exact: true }).waitFor();
    state.failRead = true;
    await page.getByRole('button', { name: '답변 확인', exact: true }).click();
    await page.getByText('알림 읽음 저장 실패', { exact: true }).waitFor();
    check('read failure does not navigate or mark success', page.url().endsWith('/staff/notifications/v2') && state.notices[0].read === false);
    await page.getByRole('button', { name: '다시 확인', exact: true }).click();
    await page.waitForURL('**/staff/chat/v2?session_id=1');
    check('notification read opens exact conversation', state.notices[0].read === true);
    await page.getByRole('link', { name: '답변 알림', exact: true }).click();
    await page.waitForURL('**/staff/notifications/v2');
    await page.reload();
    await page.getByText('사장님 답변 도착 · 읽음', { exact: true }).waitFor();
    check('notification read survives reload', true);
    await page.getByRole('button', { name: '다음 알림 보기' }).click();
    await page.getByText('합성 경로 검사 · 읽지 않음', { exact: true }).waitFor();
    check('notification cursor loads next page', true);
    await page.getByRole('button', { name: '읽음으로 표시' }).click();
    await page.getByText('합성 경로 검사 · 읽음', { exact: true }).waitFor();
    check('notification cannot navigate to arbitrary destination', page.url().endsWith('/staff/notifications/v2'));
    for (const width of [390, 360]) {
      await page.setViewportSize({ width, height: 844 });
      check(`notifications width ${width} no overflow`, await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    }
    await page.screenshot({ path: path.join(policyOut, 'notifications.png'), fullPage: true });
    await page.getByRole('button', { name: '답변 확인', exact: true }).click();
    await page.waitForURL('**/staff/chat/v2?session_id=1');
    for (const width of [390, 360]) {
      await page.setViewportSize({ width, height: 844 });
      await ownerPage.setViewportSize({ width, height: 844 });
      check(`staff width ${width} no overflow`, await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
      check(`owner width ${width} no overflow`, await ownerPage.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    }
    const out = path.resolve(__dirname, '../tmp/r-ui'); fs.mkdirSync(out, { recursive: true });
    await page.screenshot({ path: path.join(out, 'staff.png'), fullPage: true });
    await ownerPage.screenshot({ path: path.join(out, 'owner.png'), fullPage: true });
    check('no browser runtime exceptions', errors.length === 0);
    fs.writeFileSync(path.join(out, 'result.json'), JSON.stringify({ fixture: 'synthetic API browser walkthrough', passed }, null, 2));
    console.log(`Verified ${passed.length} browser checks`);
  } finally { await browser.close(); }
})().catch((err) => { console.error(err); process.exitCode = 1; });
