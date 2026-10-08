// 리브랜딩 화면 회귀 검사. P5 상세 검증은 verify_ui_checklist.cjs. 합성 fixture이며 실제 자료를 쓰지 않는다.
// 실행: next start -p 3011 을 띄운 뒤 NODE_PATH=<playwright> node api/scripts/verify_ui_rebrand.cjs
const { chromium } = require('playwright');
const assert = require('node:assert/strict');

const BASE = 'http://127.0.0.1:3011';

(async () => {
  const channel = process.env.R_UI_BROWSER_CHANNEL || (process.platform === 'win32' ? 'msedge' : undefined);
  const browser = await chromium.launch({ ...(channel ? { channel } : {}), headless: true });
  let passed = 0;
  const check = (name, value) => { assert.ok(value, name); passed++; console.log('PASS rebrand', name); };

  const state = {
    cards: [
      { card_id: 1, review_status: 'APPROVED', title: '합성 라테', content: '컵에 얼음 가득\n시럽 2펌프\n우유 200ml', category: { category_id: 10, name: '음료' }, job_id: 7 },
      { card_id: 2, review_status: 'PENDING', title: '합성 원두 위치', content: '창고 왼쪽 선반 2칸', category: { category_id: 11, name: '재고 · 위치' }, job_id: 7 },
      { card_id: 3, review_status: 'NEEDS_REVIEW', title: '합성 마감 청소', content: '머신 청소', category: { category_id: 11, name: '재고 · 위치' }, job_id: 7, needs_review_reason: '시간이 두 가지로 적혀 있어요' },
      { card_id: 4, review_status: 'EXCLUDED', title: '합성 지운 카드', content: '지운 내용', category: { category_id: 10, name: '음료' }, job_id: 7 },
    ],
    job: { status: 'EXTRACTING' },
    failApprove: new Set(), failDraft: 0, failRetryJob: false, approveCalls: [],
    proposals: [{ proposal_id: 9, relation_type: 'CONFLICT', status: 'PENDING_REVIEW', question_text: '합성 시럽 몇 번?', answer_text: '3펌프',
      target_card_id: 1, target_version_id: 1, current_title: '합성 라테', current_content: '시럽 2펌프', proposed_title: '합성 라테', proposed_content: '시럽 3펌프', reason: '펌프 수가 달라요', category_id: 10, created_at: '2026-10-06T00:00:00Z' }],
    failProposal: true,
    roadmapEmpty: false,
    hasStore: true, guideCompleted: true, failStore: true, signupBodies: [], storeBodies: [],
    item: { status: 'RECONFIRM_REQUIRED' }, failCompletion: true, completionBodies: [],
  };
  const version = (card, id) => ({ version_id: id, version_no: 1, title: card.title, content: card.content, change_source: 'EXTRACT', created_at: '2026-10-05T00:00:00Z' });
  const listItem = (card) => ({ ...card, assignment_type: 'AUTOMATIC', source: { source_id: 1, title: '합성 메모.png', source_type: 'SCAN', read_url: null }, has_evidence: true, needs_review_reason: card.needs_review_reason ?? null, updated_at: '2026-10-05T00:00:00Z' });
  const detail = (card) => ({ ...listItem(card), draft: version(card, card.card_id * 10), published: card.review_status === 'APPROVED' ? version(card, card.card_id * 10) : null,
    evidence: [{ evidence_id: 1, locator_type: 'PAGE', locator: {}, excerpt: '합성 근거 문장', source: { source_id: 1, title: '합성 메모.png', source_type: 'SCAN', read_url: null, source_availability: 'DELETED' } }], events: [] });
  const fail = (route, status, message) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify({ detail: message, error: { message } }) });

  async function context(role, { signedIn = true } = {}) {
    let sessionActive = signedIn, sessionRole = role;
    const ctx = await browser.newContext({ viewport: { width: 390, height: 844 } });
    await ctx.route('http://localhost:8000/**', async (route) => {
      const req = route.request(), url = new URL(req.url()), p = url.pathname, m = req.method();
      const body = ['POST', 'PATCH', 'PUT'].includes(m) && req.postData() ? req.postDataJSON() : null;
      let payload;
      if (p === '/auth/refresh') {
        if (!sessionActive) return fail(route, 401, '세션 없음');
        payload = { token: 'synthetic-ui-only', user: { user_id: role === 'OWNER' ? 1 : 2, role: sessionRole, store_id: state.hasStore ? 1 : null } };
      } else if (p === '/auth/logout') { sessionActive = false; payload = {}; }
      else if (p === '/auth/providers') payload = { kakao: true };
      else if (p === '/auth/role') { sessionRole = body.role; payload = { token: 'synthetic-ui-only', user: { user_id: 1, role: sessionRole, store_id: null } }; }
      else if (p === '/app/bootstrap') payload = { user: { user_id: role === 'OWNER' ? 1 : 2, role: sessionRole, name: '합성 사용자' },
        store: state.hasStore ? { store_id: 1, store_name: '합성 매장', guide_completed: state.guideCompleted, category_version: 1 } : null,
        badges: { waiting_questions: 0, pending_cards: 1 },
        default_destination: !sessionRole ? '/auth/role' : sessionRole === 'OWNER' ? (state.hasStore ? '/owner' : '/owner/intent') : '/staff' };
      else if (p === '/auth/login') {
        if (body.password !== 'right-pass') return fail(route, 401, '이메일 또는 비밀번호가 맞지 않습니다');
        sessionActive = true; payload = { token: 'synthetic-ui-only', user: { user_id: 1, role: 'OWNER', store_id: state.hasStore ? 1 : null } };
      } else if (p === '/auth/signup') { state.hasStore = false; sessionActive = true; sessionRole = null; state.signupBodies.push(body); payload = { token: 'synthetic-ui-only', user: { user_id: 1, role: null, store_id: null } }; }
      else if (p === '/auth/stores') {
        if (state.failStore) { state.failStore = false; return fail(route, 503, '합성 매장 생성 실패'); }
        state.hasStore = true; state.storeBodies.push(body);
        payload = { token: 'synthetic-ui-only', store: { store_id: 1, store_name: body.store_name } };
      } else if (p === '/members/invite-link') payload = { url: 'http://localhost:3011/join/synthetic-invite-token' };
      else if (p === '/ingest/capabilities') payload = { SCAN: { extensions: ['pdf', 'jpg', 'jpeg', 'png'], max_bytes: 20000000 } };
      else if (p === '/ingest/jobs') payload = { items: [], next_cursor: null, total: 0 };
      else if (p === '/ingest/jobs/7') payload = { job_id: 7, title: null, status: state.job.status, category_version: 1,
        counts: { sources: 2, succeeded: 1, failed: state.job.status === 'PARTIAL' ? 1 : 0, partial: 0, cards: state.job.status === 'EXTRACTING' ? 0 : 3 },
        sources: [{ source_id: 1, filename: '합성 메모.png', status: state.job.status === 'EXTRACTING' ? 'EXTRACTING' : 'SUCCEEDED', card_count: 3, error: null },
          { source_id: 2, filename: '합성 실패.pdf', status: state.job.status === 'PARTIAL' ? 'FAILED' : 'QUEUED', card_count: 0, error: state.job.status === 'PARTIAL' ? { code: 'X', message: '합성 처리 실패' } : null }],
        review_destination: '/owner/cards/review?job_id=7' };
      else if (p === '/ingest/jobs/7/retry') { if (state.failRetryJob) { state.failRetryJob = false; return fail(route, 503, '합성 재시도 실패'); } state.job.status = 'QUEUED'; payload = { job_id: 7, status: 'QUEUED' }; }
      else if (p === '/cards' && m === 'GET') {
        const status = url.searchParams.get('review_status'), q = url.searchParams.get('query');
        let items = state.cards;
        if (status && status !== 'all') items = items.filter((c) => c.review_status === status.toUpperCase());
        if (q) items = items.filter((c) => c.title.includes(q));
        payload = { items: items.map(listItem), next_cursor: null, total: items.length };
      } else if (/^\/cards\/\d+$/.test(p)) {
        const card = state.cards.find((c) => c.card_id === Number(p.split('/')[2]));
        if (!card) return fail(route, 404, '없는 카드');
        payload = detail(card);
      } else if (/^\/cards\/\d+\/(approve|exclude|restore)$/.test(p)) {
        const [, , id, action] = p.split('/'); const card = state.cards.find((c) => c.card_id === Number(id));
        if (action === 'approve') { state.approveCalls.push(card.card_id); if (state.failApprove.has(card.card_id)) { state.failApprove.delete(card.card_id); return fail(route, 502, '합성 공개 실패'); } }
        card.review_status = { approve: 'APPROVED', exclude: 'EXCLUDED', restore: 'PENDING' }[action];
        payload = { card_id: card.card_id, review_status: card.review_status, draft_version_id: 1, published_version_id: 1, updated_at: '2026-10-06T00:00:00Z', undo_until: null };
      } else if (/^\/cards\/\d+\/draft$/.test(p)) {
        if (state.failDraft) { state.failDraft--; return fail(route, 409, '버전 충돌'); }
        const card = state.cards.find((c) => c.card_id === Number(p.split('/')[2])); card.title = body.title; card.content = body.content;
        payload = { card_id: card.card_id, review_status: card.review_status, draft_version_id: 2, published_version_id: 1, updated_at: '2026-10-06T00:00:00Z', undo_until: null };
      } else if (/^\/cards\/\d+\/category$/.test(p)) {
        const card = state.cards.find((c) => c.card_id === Number(p.split('/')[2])); card.category = { category_id: body.category_id, name: body.category_id === 11 ? '재고 · 위치' : '음료' };
        payload = { card_id: card.card_id, review_status: card.review_status, draft_version_id: 1, published_version_id: 1, updated_at: '2026-10-06T00:00:01Z', undo_until: null };
      } else if (p === '/categories') payload = { version: 1, reclassification: null, items: [
        { category_id: 10, name: '음료', is_system: false, sort_order: 1 }, { category_id: 11, name: '재고 · 위치', is_system: false, sort_order: 2 }] };
      else if (p === '/learn/knowledge-proposals') payload = { store_id: 1, status: 'PENDING_REVIEW', items: state.proposals };
      else if (/^\/learn\/knowledge-proposals\/\d+\/(approve|dismiss)$/.test(p)) {
        if (state.failProposal) { state.failProposal = false; return fail(route, 503, '합성 제안 저장 실패'); }
        state.proposals = []; payload = { proposal_id: 9, status: 'PUBLISHED' };
      } else if (p === '/learn/roadmap') payload = state.roadmapEmpty
        ? { store: { store_id: 1, name: '합성 매장' }, counts: { total: 0, done: 0, reconfirm_required: 0 }, continue_item_id: null, stages: [] }
        : { store: { store_id: 1, name: '합성 매장' }, counts: { total: 2, done: 0, reconfirm_required: 1 }, continue_item_id: 5,
          stages: [{ category_id: 10, name: '음료', order: 1, items: [{ item_id: 5, card_id: 1, published_version_id: 10, title: '합성 라테', status: state.item.status }] },
            { category_id: 11, name: '재고 · 위치', order: 2, items: [{ item_id: 6, card_id: 2, published_version_id: 20, title: '합성 원두 위치', status: 'NOT_STARTED' }] }] };
      else if (p === '/learn/items/5') payload = { item_id: 5, card_id: 1, published_version_id: 10, title: '합성 라테', content: '컵에 얼음 가득\n시럽 2펌프', status: state.item.status,
        category: { category_id: 10, name: '음료' }, evidence: [], return_to: { path: '/staff/roadmap', item_id: 5 } };
      else if (p === '/learn/items/5/completion') {
        state.completionBodies.push(body);
        if (state.failCompletion) { state.failCompletion = false; return fail(route, 503, '합성 저장 실패'); }
        state.item.status = body.completed ? 'DONE' : 'NOT_STARTED';
        payload = { item_id: 5, card_id: 1, published_version_id: 10, status: state.item.status, counts: { total: 2, done: 1, reconfirm_required: 0 } };
      } else if (p === '/learn/v2/pending') payload = { questions: [], next_after: null };
      else if (p === '/learn/v2/sessions') payload = { sessions: [] };
      else if (p === '/checklist/today') payload = { business_date: '2026-10-08', previous_business_date: '2026-10-07', previous_submitted: true,
        scope: { all: true, shift_ids: [] }, current_shift_id: null, upcoming: false, shifts: [], groups: [],
        view: { total: 0, done: 0 }, scope_counts: { total: 0, done: 0 }, my_submission: null };
      else if (p === '/checklist/status') payload = { business_date: '2026-10-08', current_shift_id: null, shifts: [], scope_counts: { total: 0, done: 0 }, last_submission: null };
      else if (p === '/checklist/cards/1') payload = { card_id: 1, checklist: false, shift_ids: [] };
      else if (p === '/checklist/shifts') payload = { items: [] };
      else return route.fulfill({ status: 404, contentType: 'application/json', body: '{}' });
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(payload) });
    });
    return ctx;
  }

  const noOverflow = (page) => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth);
  try {
    const errors = [];
    const owner = await context('OWNER'), page = await owner.newPage();
    page.on('pageerror', (e) => errors.push(e.message));

    // P2 작업 화면: 처리 중 → PARTIAL 결과 → "맞아요" 일부 실패 → 실패한 카드만 재시도
    await page.goto(`${BASE}/owner/jobs/7`);
    await page.getByText('정리하고 있어요', { exact: true }).waitFor();
    check('job processing shows server state without fake progress', await page.getByRole('progressbar').count() === 0);
    state.job.status = 'PARTIAL';
    await page.getByText('이렇게 나눴어요', { exact: true }).waitFor({ timeout: 10000 });
    check('job polling moves to result', await page.getByText('준비된 카드와 처리하지 못한 자료가 있어요.', { exact: false }).isVisible());
    check('needs-review card separated from bulk approve', await page.getByText('하나씩 봐 주세요 · 1', { exact: true }).isVisible());
    check('excluded card hidden from result', await page.getByText('합성 지운 카드').count() === 0);
    state.failApprove.add(2);
    await page.getByRole('button', { name: '맞아요', exact: true }).click();
    await page.getByText('를 다시 누르면 이 카드만 다시 시도해요.', { exact: false }).waitFor();
    check('bulk approve failure stays on failed card', state.approveCalls.join() === '2');
    await page.getByRole('button', { name: '맞아요', exact: true }).click();
    await page.waitForURL('**/owner', { timeout: 10000 }).catch(() => {});
    check('retry approves only the failed card', state.approveCalls.join() === '2,2' && state.cards[1].review_status === 'APPROVED');
    state.job.status = 'FAILED'; state.failRetryJob = true;
    await page.goto(`${BASE}/owner/jobs/7`);
    await page.getByText('처리하지 못했어요', { exact: true }).waitFor();
    await page.getByRole('button', { name: '다시 시도', exact: true }).first().click();
    await page.getByText('다시 시도하지 못했어요.', { exact: false }).or(page.locator('[role="alert"]:not(#__next-route-announcer__)')).first().waitFor();
    check('job retry failure shown in place', state.job.status === 'FAILED');
    await page.goto(`${BASE}/owner/jobs/abc`);
    await page.getByText('잘못된 작업 주소예요', { exact: true }).waitFor();
    check('invalid job id handled', true);

    // P3 카드 목록: 묶음·필터·검색·지운 카드 분리·제안 배너·작업 딥링크
    await page.goto(`${BASE}/owner/cards`);
    await page.getByRole('link', { name: /합성 라테/ }).waitFor();
    check('card list groups by category', await page.getByText('재고 · 위치', { exact: true }).count() >= 1);
    check('all filter hides excluded cards', await page.getByText('합성 지운 카드').count() === 0);
    await page.getByRole('tab', { name: '지운 카드' }).click();
    await page.getByText('합성 지운 카드', { exact: true }).waitFor();
    check('excluded filter shows excluded cards', page.url().includes('status=excluded'));
    await page.goto(`${BASE}/owner/cards`);
    await page.getByLabel('카드 찾기').fill('원두');
    await page.getByLabel('카드 찾기').press('Enter');
    await page.waitForURL('**query=*');
    await page.getByRole('link', { name: /합성 원두 위치/ }).waitFor();
    check('search narrows list', await page.getByRole('link', { name: /합성 라테/ }).count() === 0);
    await page.goto(`${BASE}/owner/cards/review?job_id=7`);
    await page.waitForURL('**/owner/cards?status=all&job_id=7');
    await page.getByText('이번에 넣은 자료의 카드만 · 모두 보기', { exact: true }).waitFor();
    check('job review deep link keeps job filter', true);

    // 지식 제안: 저장 실패는 그 자리에, 재시도 성공 후 빈 상태
    await page.getByRole('link', { name: /기존 카드와 다른 답이 있어요/ }).click();
    await page.waitForURL('**/owner/cards/proposals');
    await page.getByRole('button', { name: '바꿀 내용으로 공개' }).click();
    await page.locator('[role="alert"]:not(#__next-route-announcer__)').waitFor();
    check('proposal failure shown in place', state.proposals.length === 1);
    await page.getByRole('button', { name: '다시 시도', exact: true }).click();
    await page.getByText('확인할 제안이 없어요', { exact: true }).waitFor();
    check('proposal resolved empties list', true);

    // 카드 상세: 고치기 충돌 시 입력 보존 → 저장, 지우기 시트, 다시 살리기, 카테고리 이동, 인용 끊김
    await page.goto(`${BASE}/owner/cards/1`);
    await page.getByRole('heading', { name: '합성 라테' }).waitFor();
    check('detail shows numbered lines', await page.locator('ol li').count() === 3);
    await page.getByRole('button', { name: /근거 보기/ }).click();
    await page.getByText('합성 근거 문장', { exact: true }).waitFor();
    check('evidence expands', true);
    check('deleted source marked as broken citation', await page.getByText('인용 끊김', { exact: false }).count() >= 1);
    await page.getByRole('button', { name: '고치기', exact: true }).click();
    await page.getByLabel('제목').fill('합성 라테 고침');
    state.failDraft = 1;
    await page.getByRole('button', { name: '고친 내용 저장' }).click();
    await page.getByText('그사이 카드가 바뀌었어요.', { exact: false }).waitFor();
    check('draft conflict keeps input', await page.getByLabel('제목').inputValue() === '합성 라테 고침');
    await page.getByRole('button', { name: '고친 내용 저장' }).click();
    await page.getByRole('heading', { name: '합성 라테 고침' }).waitFor();
    check('draft save returns to detail', state.cards[0].title === '합성 라테 고침');
    await page.getByRole('button', { name: /카테고리 음료/ }).click();
    await page.getByRole('button', { name: '재고 · 위치' }).click();
    await page.getByRole('button', { name: /카테고리 재고 · 위치/ }).waitFor();
    check('category move updates card', state.cards[0].category.category_id === 11);
    await page.getByRole('button', { name: '지우기', exact: true }).click();
    await page.getByRole('dialog').getByRole('button', { name: '지우기', exact: true }).click();
    await page.getByRole('button', { name: '다시 살리기' }).waitFor();
    check('exclude goes through confirm sheet', state.cards[0].review_status === 'EXCLUDED');
    await page.getByRole('button', { name: '다시 살리기' }).click();
    await page.getByRole('button', { name: '공개하기' }).waitFor();
    check('restore brings card back', state.cards[0].review_status === 'PENDING');
    await page.goto(`${BASE}/owner/cards/999`);
    await page.getByText('이 카드를 볼 수 없어요', { exact: true }).waitFor();
    check('missing card does not leak', true);
    for (const width of [390, 360]) {
      await page.setViewportSize({ width, height: 844 });
      await page.goto(`${BASE}/owner/cards`);
      await page.getByRole('link', { name: /합성 원두 위치/ }).waitFor();
      check(`owner cards width ${width} no overflow`, await noOverflow(page));
    }
    await page.setViewportSize({ width: 390, height: 844 });

    // 설정 → 로그아웃은 저장 상태를 지운다
    await page.goto(`${BASE}/owner/settings`);
    await page.getByText('합성 매장', { exact: true }).waitFor();
    await page.getByRole('button', { name: '로그아웃' }).click();
    // 세션 폐기 뒤 새로고침해도 로그인 화면에 머문다
    await page.waitForURL(`${BASE}/`);
    await page.getByRole('link', { name: '이메일로 시작하기' }).waitFor();
    await page.reload();
    await page.getByRole('link', { name: '이메일로 시작하기' }).waitFor();
    check('logout stays signed out after reload', !page.url().includes('next='));

    // P2 시작: 로그인 실패·성공, 가입 → 매장 이름(실패 후 재시도) → 아무거나 넣기, 초대 코드, 첫 공개 → 초대
    const fresh = await context('OWNER', { signedIn: false }), fp = await fresh.newPage();
    fp.on('pageerror', (e) => errors.push(e.message));
    await fp.goto(`${BASE}/owner/auth`);
    await fp.getByRole('link', { name: '이메일로 시작하기' }).click();
    const sheet = fp;
    await sheet.getByLabel('이메일').fill('owner@synthetic.test');
    await sheet.getByLabel('비밀번호').fill('wrong-pass');
    await sheet.getByRole('button', { name: '로그인', exact: true }).click();
    await sheet.getByText('이메일 또는 비밀번호를 확인해 주세요.', { exact: true }).waitFor();
    check('wrong password stays on login with message', fp.url().includes('/auth/email'));
    await sheet.getByLabel('비밀번호').fill('right-pass');
    await sheet.getByRole('button', { name: '로그인', exact: true }).click();
    await fp.waitForURL(`${BASE}/owner`);
    check('login lands on today store', true);
    await fresh.close();

    const joiner = await context('OWNER', { signedIn: false }), jp = await joiner.newPage();
    jp.on('pageerror', (e) => errors.push(e.message));
    await jp.goto(`${BASE}/owner/auth`);
    await jp.getByRole('link', { name: '이메일로 시작하기' }).click();
    await jp.getByRole('button', { name: /가입하기/ }).click();
    await jp.getByLabel('이름').fill('합성 사장');
    await jp.getByLabel('이메일').fill('new@synthetic.test');
    await jp.getByLabel('비밀번호').fill('right-pass');
    await jp.getByRole('button', { name: '가입하기', exact: true }).click();
    await jp.waitForURL('**/auth/role');
    check('signup defers role choice', state.signupBodies[0]?.role == null);
    await jp.getByRole('button', { name: '사장님이에요' }).click();
    await jp.waitForURL('**/owner/intent');
    await jp.getByLabel('매장 이름').fill('합성 새 매장');
    await jp.getByRole('button', { name: '다음', exact: true }).click();
    await jp.locator('[role="alert"]:not(#__next-route-announcer__)').waitFor();
    check('store create failure keeps name', await jp.getByLabel('매장 이름').inputValue() === '합성 새 매장');
    await jp.getByRole('button', { name: '다시 시도', exact: true }).click();
    await jp.waitForURL('**/owner/add');
    await jp.getByText('알려주고 싶은 걸 아무거나 넣어주세요', { exact: true }).waitFor();
    check('store created as cafe then add screen', state.storeBodies[0]?.store_name === '합성 새 매장' && state.storeBodies[0]?.business_type === 'CAFE');
    check('voice tool hidden until recording format decided', await jp.getByRole('button', { name: '말하기' }).count() === 0);
    await joiner.close();

    await page.goto(`${BASE}/auth/email`);
    await page.getByLabel('이메일').fill('owner@synthetic.test');
    await page.getByLabel('비밀번호').fill('right-pass');
    await page.getByRole('button', { name: '로그인', exact: true }).click();
    await page.waitForURL(`${BASE}/owner`);
    await page.goto(`${BASE}/owner/upload`);
    await page.waitForURL('**/owner/add');
    check('old upload address opens add screen', true);
    await page.goto(`${BASE}/owner/complete`);
    await page.waitForURL('**/owner/invite');
    await page.getByRole('button', { name: '링크 복사', exact: true }).waitFor();
    check('invite link actions available', await page.getByRole('link', { name: '직원 관리 · 합류 승인' }).isVisible());
    state.guideCompleted = false; state.job.status = 'SUCCEEDED';
    state.cards[0].review_status = 'PENDING'; state.cards[2].review_status = 'PENDING'; state.cards[2].needs_review_reason = null;
    await page.goto(`${BASE}/owner/jobs/7`);
    await page.getByRole('button', { name: '맞아요', exact: true }).click();
    await page.waitForURL('**/owner/invite');
    check('first publish continues to invite', state.cards[0].review_status === 'APPROVED' && state.cards[2].review_status === 'APPROVED');
    for (const width of [390, 360]) {
      await page.setViewportSize({ width, height: 844 });
      check(`invite width ${width} no overflow`, await noOverflow(page));
    }
    await page.setViewportSize({ width: 390, height: 844 });
    state.guideCompleted = true;

    // P4 레시피: 옛 주소 이동, 바뀌었어요, 완료 저장 실패 후 재시도, 질문 연결, 빈 상태
    const staff = await context('STAFF'), sp = await staff.newPage();
    sp.on('pageerror', (e) => errors.push(e.message));
    await sp.goto(`${BASE}/staff/roadmap`);
    await sp.waitForURL('**/staff/recipes');
    await sp.getByRole('link', { name: /합성 라테/ }).waitFor();
    check('old roadmap address opens recipes', await sp.getByText('바뀌었어요', { exact: true }).isVisible());
    await sp.goto(`${BASE}/staff/items/5`);
    await sp.waitForURL('**/staff/recipes/5');
    await sp.getByText('내용이 바뀌었어요. 다시 한 번 확인해주세요', { exact: true }).waitFor();
    check('old item address opens recipe', true);
    await sp.getByRole('button', { name: '확인했어요' }).click();
    await sp.getByText('아직 완료로 저장되지 않았어요.', { exact: false }).waitFor();
    check('completion failure is not shown as done', state.item.status === 'RECONFIRM_REQUIRED');
    await sp.getByRole('button', { name: '확인했어요' }).click();
    await sp.getByRole('button', { name: '확인 취소하기' }).waitFor();
    check('completion saves current published version', state.completionBodies.every((b) => b.published_version_id === 10 && b.completed === true));
    await sp.getByRole('link', { name: '이 레시피에 대해 물어보기' }).click();
    await sp.waitForURL('**/staff/ask?q=*');
    check('ask from recipe prefills question', (await sp.getByLabel('모르는 거 물어보기').inputValue()).startsWith('합성 라테'));
    state.roadmapEmpty = true;
    await sp.goto(`${BASE}/staff`);
    await sp.getByText('아직 오늘 할 일이 없어요', { exact: true }).waitFor();
    check('staff home opens checklist instead of redirect', new URL(sp.url()).pathname === '/staff');
    await sp.getByRole('link', { name: '레시피', exact: true }).click();
    await sp.waitForURL('**/staff/recipes');
    await sp.getByText('아직 준비된 학습 자료가 없어요', { exact: true }).waitFor();
    check('empty roadmap shows reason not samples', await sp.locator('a[href^="/staff/recipes/"]').count() === 0);
    for (const width of [390, 360]) {
      await sp.setViewportSize({ width, height: 844 });
      check(`staff recipes width ${width} no overflow`, await noOverflow(sp));
    }
    check('no browser runtime exceptions', errors.length === 0);
    console.log(`Verified ${passed} rebrand browser checks`);
  } finally { await browser.close(); }
})().catch((err) => { console.error(err); process.exitCode = 1; });
