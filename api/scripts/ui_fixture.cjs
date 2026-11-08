// 화면 검사용 합성 API. 가상 매장 '골목커피 연남점' 데이터만 쓴다(실제 매장 자료 금지).
// syntheticApi(role, overrides) → { handler, misses, calls, state }
// 모르는 경로는 misses 에 "METHOD /path" 로 남기고 404 를 준다. 검사 스크립트는 misses 가 비어 있어야 통과로 본다.

const NOW = '2026-10-31T05:00:00Z';
const STORE = { store_id: 1, store_name: '골목커피 연남점', guide_completed: true, category_version: 1 };
const USERS = { OWNER: { user_id: 1, name: '김사장' }, STAFF: { user_id: 2, name: '박지호' } };
const CATEGORIES = [
  { category_id: 10, name: '음료 레시피', is_system: false, sort_order: 1 },
  { category_id: 11, name: '오픈 마감', is_system: false, sort_order: 2 },
  { category_id: 12, name: '재고 위치', is_system: false, sort_order: 3 },
  { category_id: 13, name: '기타', is_system: true, sort_order: 4 },
];
// 사실 카드(카드 1) 보기. verify_w3b_card_facts_ui.cjs 의 factCardView 구조를 옮겼다.
const origin = (o) => ({ kind: 'SOURCE', source_id: null, source_title: null, source_type: null, source_availability: null,
  locator_type: null, locator: {}, owner_answer_id: null, created_at: null, ...o });
const factRow = (o) => ({ subject: '바닐라 라떼', predicate: null, variant: { temperature: null, size: null }, value: null, unit: null,
  polarity: 'AFFIRM', step_order: null, conditions: [], exceptions: [], requires: [], change_kind: 'EXTRACTION',
  previous_sentence: null, origins: [], edit_block: null, assertion: o.sentence, ...o });
const memo = (page) => origin({ source_id: 5, source_title: '레시피 메모.jpg', source_type: 'SCAN', source_availability: 'AVAILABLE', locator_type: 'PAGE', locator: { page } });
function factCardView(version, status) {
  return { card_id: 1, version_id: version, title: '바닐라 라떼', entity_id: 9, entity_name: '바닐라 라떼', review_status: status,
    published_version_id: 10, editable: true, entity_problem: null,
    blocks: [
      { block_id: 'b1', kind: 'QUANTITIES', order: 1, variant: { temperature: 'ICE', size: null }, facts: [
        factRow({ fact_revision_id: 101, fact_id: 1, position: 1, sentence: '바닐라 라떼 ICE 우유는 225ml 넣는다.', value: '225', unit: 'ml', variant: { temperature: 'ICE', size: null }, origins: [memo(1)] }),
        factRow({ fact_revision_id: 103, fact_id: 8, position: 3, sentence: 'ICE 얼음은 컵 가득 담는다.', variant: { temperature: 'ICE', size: null }, origins: [memo(1)] }),
        factRow({ fact_revision_id: 102, fact_id: 2, position: 2, sentence: '바닐라 라떼 ICE 시럽은 10g 넣는다.', value: '10', unit: 'g', variant: { temperature: 'ICE', size: null },
          origins: [origin({ source_id: 6, source_title: '지난 메모.jpg', source_type: 'SCAN', source_availability: 'DELETED', locator_type: 'WHOLE_SOURCE' })] }),
      ] },
      { block_id: 'b2', kind: 'STEPS', order: 2, variant: { temperature: null, size: null }, facts: [
        factRow({ fact_revision_id: 201, fact_id: 3, position: 1, sentence: '컵에 얼음을 담는다.', step_order: 1, origins: [memo(2)] }),
        factRow({ fact_revision_id: 202, fact_id: 4, position: 2, sentence: '샷을 붓는다.', step_order: 2, requires: [{ fact_id: 3, label: '1번' }], origins: [memo(2)] }),
        factRow({ fact_revision_id: 203, fact_id: 5, position: 3, sentence: '물을 붓는다.', step_order: 3, origins: [origin({ kind: 'OWNER_ANSWER', owner_answer_id: 3 })] }),
        factRow({ fact_revision_id: 204, fact_id: 7, position: 4, sentence: '뚜껑을 닫는다.', step_order: 4, requires: [{ fact_id: 4, label: '2번' }], origins: [memo(3)] }),
      ] },
      { block_id: 'b3', kind: 'NOTES', order: 3, variant: { temperature: null, size: null }, facts: [
        factRow({ fact_revision_id: 301, fact_id: 6, position: 1, sentence: '바닐라 라떼에는 휘핑을 올리지 않는다.', polarity: 'NEGATE', exceptions: ['손님이 따로 요청하면'], origins: [memo(3)] }),
      ] },
    ] };
}

// 표에서 뽑힌 레시피 모양(칸마다 '이름=값', 제조순서는 화살표 한 줄). 합성 메뉴
function tableRecipeView(version, status) {
  const v = (temperature) => ({ temperature, size: null });
  let id = 500;
  const row = (sentence, temperature, extra = {}) => factRow({ fact_revision_id: ++id, fact_id: id, position: id, sentence, variant: v(temperature), origins: [memo(1)], ...extra });
  const steps = (temperature, sentence, names) => names.map((value, i) => row(sentence, temperature, { value, step_order: i + 1 }));
  return { card_id: 1, version_id: version, title: '바닐라 라떼', entity_id: 9, entity_name: '바닐라 라떼', review_status: status, published_version_id: 10, editable: true, entity_problem: null,
    blocks: [
      { block_id: 't1', kind: 'QUANTITIES', order: 1, variant: v('HOT'), facts: ['구분=바닐라', '금액=4,500원', '컵=16', '액상(텀블러)=스팀우유250ml(70°C)', '재료(시럽 / 파우더 / 베이스)=바닐라시럽 30ml'].map((s) => row(s, 'HOT')) },
      { block_id: 't2', kind: 'QUANTITIES', order: 2, variant: v('ICE'), facts: ['구분=바닐라', '금액=4,500원', '컵=20', '얼음=가득', '액상(텀블러)=우유가득(200ml)', '재료(시럽 / 파우더 / 베이스)=바닐라시럽 20ml (컵 밑선)'].map((s) => row(s, 'ICE')) },
      { block_id: 't3', kind: 'STEPS', order: 3, variant: v('HOT'), facts: steps('HOT', '제조순서=컵 → 재료 → 액상', ['컵', '재료', '액상']) },
      { block_id: 't4', kind: 'STEPS', order: 4, variant: v('ICE'), facts: steps('ICE', '제조순서=컵 → 재료 → 얼음 → 액상 → 섞음', ['컵', '재료', '얼음', '액상', '섞음']) },
      { block_id: 't5', kind: 'NOTES', order: 5, variant: v('HOT'), facts: [row('블렌더=x', 'HOT')] },
    ] };
}

const category = (id) => { const c = CATEGORIES.find((x) => x.category_id === id); return { category_id: c.category_id, name: c.name }; };

function initialState(overrides) {
  return {
    unreadCount: 3,
    cards: [
      { card_id: 1, review_status: 'APPROVED', title: '바닐라 라떼', content: 'HOT 샷 2, 바닐라 시럽 2펌프, 우유 220ml\nICE 샷 2, 시럽 2펌프, 우유 180ml, 얼음 가득', category_id: 10 },
      { card_id: 2, review_status: 'APPROVED', title: '아메리카노', content: 'HOT 물 275ml 샷 2\nICE 물 225ml 샷 2 얼음 가득', category_id: 10 },
      { card_id: 3, review_status: 'NEEDS_REVIEW', title: '마감 머신 청소', content: '그룹헤드 역세척 5회\n스팀봉 물 빼고 닦기', category_id: 11, needs_review_reason: '역세척 횟수가 두 가지(3회, 5회)로 적혀 있어요' },
      { card_id: 4, review_status: 'PENDING', title: '오픈 준비', content: '포스 켜기 → 머신 예열 15분 → 쇼케이스 채우기', category_id: 11 },
      { card_id: 5, review_status: 'PENDING', title: '원두 보관 위치', content: '창고 왼쪽 선반 2칸, 개봉한 원두는 밀폐통', category_id: 12 },
      { card_id: 6, review_status: 'APPROVED', title: '우유 발주', content: '화, 금 오전 10시 전 발주, 재고 6개 이하일 때', category_id: 12 },
    ],
    pending: [
      { pending_id: '101', question: '디카페인 원두는 어디 있어요?', status: 'WAITING', answers: [] },
      { pending_id: '102', question: '오트밀크 라떼도 시럽 2펌프인가요?', status: 'WAITING', answers: [] },
      { pending_id: '103', question: '포스 영수증 용지 교체는 어떻게 해요?', status: 'ANSWERED', answers: [
        { owner_answer_id: '7', answer: '포스 오른쪽 서랍 안에 예비 용지 있어요.', revision: 1, knowledge_status: 'PUBLISHED', knowledge_availability: 'CURRENT', proposal_status: null, event_id: null, attempts: 0, retry_available: false }] },
    ],
    answerConflict: false,
    answerDelayMs: 0,
    answerRequests: {},
    notifications: [
      { notification_id: 3, event_type: 'PENDING_QUESTION', aggregate_type: 'PENDING_QUESTION', aggregate_id: 101, title: '직원 질문이 왔어요', body: '디카페인 원두는 어디 있어요?', destination: '/owner/questions/101', delivery_status: 'REQUESTED', read_at: null, action_completed: false, created_at: NOW },
      { notification_id: 2, event_type: 'INGEST_COMPLETED', aggregate_type: 'INGEST_JOB', aggregate_id: 7, title: '카드 정리가 끝났어요', body: '레시피 메모.jpg 에서 카드 4장을 만들었어요.', destination: '/owner/cards?status=all&job_id=7', delivery_status: 'REQUESTED', read_at: null, action_completed: false, created_at: NOW },
      { notification_id: 1, event_type: 'JOIN_REQUESTED', aggregate_type: 'PENDING_QUESTION', aggregate_id: 9, title: '합류 요청', body: '이서연 님이 매장 합류를 요청했어요.', destination: '/owner/members', delivery_status: 'REQUESTED', read_at: null, action_completed: true, created_at: '2026-10-30T03:00:00Z' },
    ],
    shifts: [['오픈', '08:00', '12:00'], ['미들', '12:00', '17:00'], ['마감', '17:00', '22:00']].map(([name, starts_at, ends_at], i) => ({ shift_id: i + 1, name, starts_at, ends_at, sort_order: i, card_ids: [4] })),
    sessions: [],
    messages: [],
    job: { status: 'SUCCEEDED' },
    jobSequence: null,
    uploadDelayMs: 0,
    failUpload: false,
    failRestore: false,
    factVersion: 10,
    cardLinks: {},
    proposals: [{ proposal_id: 9, relation_type: 'CONFLICT', status: 'PENDING_REVIEW', question_text: '바닐라 라떼 ICE 시럽 몇 펌프?', answer_text: '3펌프',
      target_card_id: 1, target_version_id: 10, current_title: '바닐라 라떼', current_content: 'ICE 시럽 2펌프', proposed_title: '바닐라 라떼', proposed_content: 'ICE 시럽 3펌프',
      reason: null, can_approve: true, approval_block_reason: null, affected_cards: [{ card_id: 1, title: '바닐라 라떼' }], category_id: 10, created_at: NOW }],
    // 관리 화면(계획 4b): 직원·카테고리·근무조 설정·알림 쓰기
    joinRequests: [{ request_id: 9, name: '이서연', requested_at: NOW }],
    members: [{ user_id: 2, name: '박지호', role: 'STAFF', joined_at: NOW }, { user_id: 3, name: '김민준', role: 'STAFF', joined_at: NOW }],
    categories: CATEGORIES.map((c) => ({ ...c })),
    checklistMembers: [{ member_id: 2, user_id: 2, role: 'STAFF', name: '박지호', shift_ids: [1] }, { member_id: 3, user_id: 3, role: 'STAFF', name: '김민준', shift_ids: [3] }],
    settings: { business_day_starts_at: '04:00', staff_records_visible: true, timezone: 'Asia/Seoul' },
    pushConfigured: false,
    failMemberShifts: false,
    memberShiftDelayMs: 0,
    failRead: false,
    // 검토 고침: 요청마다 다른 지연(앞 요청이 늦게 끝나는 경우), 지우기·재분류 재시도 실패
    memberShiftDelays: null,
    failCategoryDelete: false,
    reclassification: null,
    failRetry: false,
    // 직원 화면(계획 5)
    rNotifications: [{ notification_id: '51', title: '사장님 답이 왔어요', body: '디카페인 원두는 창고 위 칸에 있어요.', destination: '/staff/chat/v2?session_id=1', read: false }],
    failRRead: false,
    submitted: null,
    signedOut: false,
    faqs: null,
    failItem: false,
    chatDelayMs: 0,
    chatEscalate: false,
    sessionsDelayMs: 0,
    itemContent: {},
    ...overrides,
  };
}

function syntheticApi(role, overrides = {}) {
  const state = initialState(overrides);
  const misses = [];
  const calls = [];
  const user = USERS[role];

  const listItem = (c) => ({ card_id: c.card_id, review_status: c.review_status, title: c.title, content: c.content, category: category(c.category_id),
    assignment_type: 'AUTOMATIC', job_id: 7, source: { source_id: 1, title: '레시피 메모.jpg', source_type: 'SCAN', read_url: null },
    has_evidence: true, needs_review_reason: c.needs_review_reason ?? null, updated_at: NOW });
  const version = (c) => ({ version_id: c.card_id * 10, version_no: 1, title: c.title, content: c.content, change_source: 'EXTRACT', created_at: NOW });
  const detail = (c) => ({ ...listItem(c), fact_card: c.card_id === 1 || (state.singleFactCard && c.card_id === 5), draft: version(c), published: c.review_status === 'APPROVED' ? version(c) : null, events: [],
    evidence: [{ evidence_id: 1, locator_type: 'PAGE', locator: {}, excerpt: c.content.split('\n')[0], source: { source_id: 1, title: '레시피 메모.jpg', source_type: 'SCAN', read_url: null, source_availability: 'AVAILABLE' } }] });
  const roadmapItems = state.cards.filter((c) => c.review_status === 'APPROVED').map((c) => ({ item_id: c.card_id + 10, card_id: c.card_id, published_version_id: c.card_id * 10, title: c.title, status: 'NOT_STARTED', category_id: c.category_id }));
  const checklistToday = () => ({
    business_date: '2026-10-31', previous_business_date: '2026-10-30', previous_submitted: true,
    scope: { all: role === 'OWNER', shift_ids: [1] }, current_shift_id: 1, upcoming: false,
    shifts: state.shifts.map((s) => ({ ...s, total: s.shift_id === 1 ? 4 : s.shift_id === 2 ? 2 : 3, done: s.shift_id === 1 ? 2 : 0, submitted: false })),
    scope_counts: { total: 4, done: 2 }, view: { total: 4, done: 2 },
    groups: [{ shift_id: 1, name: '오픈', cards: [[4, 40, '오픈 준비', null, true], [6, 60, '우유 발주', 16, false]].map(([card_id, card_version_id, title, item_id, checked]) => ({ card_id, card_version_id, title, item_id, lines: [{ line_no: 1, text: title, checked }] })) }],
    my_submission: state.submitted,
  });

  const ACTIVE = new Set(['QUEUED', 'EXTRACTING', 'CLASSIFYING']);
  // jobSequence 가 있으면 첫 요청부터 1초마다 다음 상태로 넘어간다(마지막 값은 유지).
  // 요청 수가 아니라 시간으로 넘겨야 작업 목록·작업 상세가 같은 순간에 같은 상태를 본다
  let sequenceStart = null;
  const jobStatus = () => {
    if (state.jobSequence && state.jobSequence.length) {
      sequenceStart ??= Date.now();
      const index = Math.min(Math.floor((Date.now() - sequenceStart) / 1000), state.jobSequence.length - 1);
      state.job = { ...state.job, status: state.jobSequence[index] };
    }
    return state.job.status;
  };
  const jobSources = (status) => state.job.sources ?? [{ source_id: 31, filename: '레시피 메모.jpg', status: ACTIVE.has(status) ? status : 'SUCCEEDED', card_count: ACTIVE.has(status) ? 0 : 4, error: null, source_availability: 'AVAILABLE' }];

  async function handler(route) {
    const req = route.request(), url = new URL(req.url()), p = url.pathname, m = req.method();
    if (m === 'OPTIONS') return route.fulfill({ status: 204, headers: { 'access-control-allow-origin': req.headers().origin ?? '*', 'access-control-allow-credentials': 'true', 'access-control-allow-headers': '*', 'access-control-allow-methods': '*' } });
    const body = ['POST', 'PATCH', 'PUT'].includes(m) && req.postData() && (req.headers()['content-type'] ?? '').includes('json') ? req.postDataJSON() : null;
    calls.push({ method: m, path: p + url.search, body, headers: req.headers() });
    const reply = (payload, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(payload),
      headers: { 'access-control-allow-origin': req.headers().origin ?? '*', 'access-control-allow-credentials': 'true' } });
    let payload;

    if (p === '/auth/refresh' && state.signedOut) return reply({ error: { message: '세션 없음' } }, 401);
    if (p === '/auth/login' && m === 'POST') {
      if (body.password !== 'right-pass') return reply({ error: { message: '이메일 또는 비밀번호가 맞지 않습니다' } }, 401);
      state.signedOut = false;
      return reply({ token: 'synthetic-ui-only', user: { user_id: user.user_id, role, store_id: 1 } });
    }
    if (p === '/auth/refresh') payload = { token: 'synthetic-ui-only', user: { user_id: user.user_id, role, store_id: 1 } };
    else if (p === '/auth/providers') payload = { kakao: true };
    else if (p === '/app/bootstrap') payload = { user: { ...user, role }, store: STORE, badges: { waiting_questions: state.pending.length, pending_cards: 2 },
      default_destination: role === 'OWNER' ? '/owner' : '/staff' };
    // 알림: 사장(/notifications 목록)과 직원(R 읽음 표시)이 같은 경로를 쓴다
    else if (p === '/notifications' && m === 'GET' && state.slowNotificationRefetchMs && (state.notificationGets = (state.notificationGets ?? 0) + 1) > 1 && await new Promise((r) => setTimeout(r, state.slowNotificationRefetchMs))) payload = null;
    else if (p === '/notifications' && m === 'GET') payload = { items: state.notifications, unread_count: state.unreadCount, next_cursor: null,
      notifications: state.notifications.map((n) => ({ notification_id: String(n.notification_id), title: n.title, body: n.body, destination: n.destination, read: Boolean(n.read_at) })), next_after: null };
    else if (/^\/notifications\/\w+\/read$/.test(p)) {
      if (state.failRead) return reply({ error: { message: '읽음 저장 실패' } }, 503);
      const n = state.notifications.find((x) => String(x.notification_id) === p.split('/')[2]);
      if (n && !n.read_at) { n.read_at = NOW; state.unreadCount = Math.max(0, state.unreadCount - 1); }
      payload = { notification_id: p.split('/')[2], read_at: NOW, read: true };
    }
    else if (p === '/notifications/support') payload = { push_configured: state.pushConfigured, vapid_public_key: state.pushConfigured ? 'BAAA' : null, guide_version: '1', guide_seen: true };
    else if (p === '/auth/logout' && m === 'POST') payload = {};
    else if (p === '/notifications/my-subscriptions') payload = { subscription_id: 0, enabled: false };
    // 사장 질문
    else if (p === '/learn/v2/pending') {
      const status = url.searchParams.get('status');
      payload = { questions: state.pending.filter((q) => !status || q.status === status).map(({ pending_id, question, status: s }) => ({ pending_id, question, status: s })), next_after: null };
    } else if (/^\/learn\/v2\/pending\/\d+\/answers$/.test(p) && m === 'POST') {
      const q = state.pending.find((x) => x.pending_id === p.split('/')[4]);
      if (state.answerDelayMs) await new Promise((r) => setTimeout(r, state.answerDelayMs));
      if (state.answerConflict) return reply({ error: { code: 'ANSWER_REVISION_CONFLICT', message: '답이 바뀌었습니다.' } }, 409);
      // 같은 request_id 는 같은 응답(멱등)
      if (state.answerRequests[body.request_id]) payload = state.answerRequests[body.request_id];
      else {
        const answer = { owner_answer_id: String(100 + q.answers.length), answer: body.answer, revision: q.answers.length + 1, knowledge_status: 'PENDING', knowledge_availability: 'NOT_APPLICABLE', proposal_status: null, event_id: null, attempts: 0, retry_available: false };
        q.answers.push(answer); q.status = 'ANSWERED';
        payload = state.answerRequests[body.request_id] = { owner_answer_id: answer.owner_answer_id, knowledge_status: 'PENDING' };
      }
    }
    else if (/^\/learn\/v2\/pending\/\d+$/.test(p)) {
      const q = state.pending.find((x) => x.pending_id === p.split('/').at(-1));
      if (!q) return reply({ error: { message: '없는 질문' } }, 404);
      payload = { pending_id: q.pending_id, status: q.status, question: q.question, question_contract: 'v2', legacy_answers: [], answers: q.answers ?? [],
        occurrences: [{ receipt_id: '1', original_question: q.question, resolved_query: { confirmed_slots: {} }, context_snapshot: null }, { receipt_id: '2', original_question: q.question, resolved_query: { confirmed_slots: {} }, context_snapshot: null }] };
    }
    // 카드
    else if (p === '/cards' && m === 'GET') {
      const status = url.searchParams.get('review_status'), q = url.searchParams.get('query');
      const jobId = url.searchParams.get('job_id');
      let items = state.cards;
      if (jobId) items = items.filter((c) => (c.job_id ?? 7) === Number(jobId));
      if (status && status !== 'all') items = items.filter((c) => c.review_status === status.toUpperCase());
      if (q) items = items.filter((c) => c.title.includes(q));
      payload = { items: items.map(listItem), next_cursor: null, total: items.length };
    } else if (/^\/cards\/\d+$/.test(p)) {
      const c = state.cards.find((x) => x.card_id === Number(p.split('/')[2]));
      if (!c) return reply({ error: { message: '없는 카드' } }, 404);
      payload = detail(c);
    } else if (/^\/cards\/\d+\/(approve|exclude|restore)$/.test(p) && m === 'POST') {
      const [, , id, action] = p.split('/');
      const c = state.cards.find((x) => x.card_id === Number(id));
      if (!c) return reply({ error: { message: '없는 카드' } }, 404);
      if (action === 'restore' && state.failRestore) return reply({ error: { message: '되돌리기 저장 실패' } }, 503);
      if (action === 'approve' && state.approveDelayMs) await new Promise((r) => setTimeout(r, state.approveDelayMs));
      if (action === 'approve' && state.failApprove?.includes(c.card_id)) return reply({ error: { message: '공개 실패' } }, 409);
      // 서버(api/app/cards/router.py)처럼 restore 는 공개 전 카드를 빼기 전 상태(검수 필요면 검수 필요)로 되돌린다
      if (action === 'exclude') c.beforeExclude = c.review_status;
      c.review_status = { approve: 'APPROVED', exclude: 'EXCLUDED', restore: c.beforeExclude === 'NEEDS_REVIEW' ? 'NEEDS_REVIEW' : 'PENDING' }[action];
      payload = { card_id: c.card_id, review_status: c.review_status, draft_version_id: c.card_id * 10, published_version_id: c.review_status === 'APPROVED' ? c.card_id * 10 : null, updated_at: NOW, undo_until: null };
    } else if (/^\/cards\/\d+\/category$/.test(p) && m === 'PATCH') {
      const c = state.cards.find((x) => x.card_id === Number(p.split('/')[2]));
      c.category_id = body.category_id;
      payload = { card_id: c.card_id, review_status: c.review_status, draft_version_id: c.card_id * 10, published_version_id: null, updated_at: NOW, undo_until: null };
    } else if (p === '/cards/1/facts' && m === 'GET') payload = (state.tableRecipe ? tableRecipeView : factCardView)(state.factVersion, state.cards[0].review_status);
    else if (p === '/cards/1/facts' && m === 'PUT') {
      state.factVersion += 1;
      payload = { card_id: 1, review_status: state.cards[0].review_status, draft_version_id: state.factVersion, published_version_id: 10, updated_at: NOW, undo_until: null, changed: true, edit_id: state.factVersion, revisions: [] };
    } else if (p === '/cards/5/facts' && m === 'GET' && state.singleFactCard) {
      // 사실이 하나뿐인 카드: 그 줄을 빼면 카드 지우기로 간다
      payload = { ...factCardView(50, state.cards[4].review_status), card_id: 5, title: '원두 보관 위치', published_version_id: null,
        blocks: [{ block_id: 's1', kind: 'NOTES', order: 1, variant: { temperature: null, size: null }, facts: [
          factRow({ fact_revision_id: 501, fact_id: 51, position: 1, sentence: '원두는 창고 왼쪽 선반에 둔다.', origins: [memo(1)] })] }] };
    } else if (/^\/cards\/\d+\/facts$/.test(p)) payload = { card_id: Number(p.split('/')[2]), blocks: [], facts: [] };
    else if (p === '/categories' && m === 'GET') payload = { version: 1, reclassification: state.reclassification, items: state.categories };
    else if (p === '/categories' && m === 'POST') {
      const category = { category_id: 20 + state.categories.length, name: body.name, is_system: false, sort_order: body.sort_order };
      state.categories.push(category);
      payload = { category, version: 2, reclass_job_id: null };
    } else if (/^\/reclassification-jobs\/\d+\/retry$/.test(p) && m === 'POST') {
      if (state.failRetry) return reply({ error: { message: '재분류 재시도 실패' } }, 409);
      state.reclassification = { ...state.reclassification, status: 'QUEUED' }; payload = state.reclassification;
    } else if (/^\/categories\/\d+$/.test(p) && m === 'DELETE') {
      if (state.failCategoryDelete) return reply({ error: { message: '카테고리 삭제 실패' } }, 409);
      const id = Number(p.split('/')[2]);
      state.categories = state.categories.filter((c) => c.category_id !== id);
      payload = { category_id: id, version: 2, reclass_job_id: null };
    }
    else if (p === '/learn/knowledge-proposals') payload = { store_id: 1, status: 'PENDING_REVIEW', items: state.proposals };
    else if (/^\/learn\/knowledge-proposals\/\d+\/(approve|dismiss)$/.test(p) && m === 'POST') {
      const [, , , id, action] = p.split('/');
      state.proposals = state.proposals.filter((x) => x.proposal_id !== Number(id));
      payload = { proposal_id: Number(id), status: action === 'approve' ? 'PUBLISHED' : 'DISMISSED' };
    }
    // 직원 학습·레시피
    else if (p === '/learn/roadmap') payload = { store: { store_id: 1, name: STORE.store_name }, counts: { total: roadmapItems.length, done: 0, reconfirm_required: 0 }, continue_item_id: roadmapItems[0].item_id,
      stages: CATEGORIES.filter((c) => roadmapItems.some((i) => i.category_id === c.category_id)).map((c, i) => ({ category_id: c.category_id, name: c.name, order: i + 1, items: roadmapItems.filter((x) => x.category_id === c.category_id) })) };
    else if (/^\/learn\/items\/\d+$/.test(p)) {
      if (state.failItem) return reply({ error: { message: '없는 항목' } }, 404);
      const item = roadmapItems.find((x) => x.item_id === Number(p.split('/').at(-1)));
      if (!item) return reply({ error: { message: '없는 항목' } }, 404);
      const c = state.cards.find((x) => x.card_id === item.card_id);
      payload = { ...item, content: state.itemContent[item.item_id] ?? c.content, category: category(c.category_id), evidence: [], return_to: { path: '/staff/recipes', item_id: item.item_id } };
    }
    else if (p === '/learn/v2/notifications' && m === 'GET') payload = { notifications: state.rNotifications, next_after: null };
    else if (/^\/learn\/v2\/notifications\/\w+\/read$/.test(p) && m === 'POST') {
      if (state.failRRead) return reply({ error: { message: '읽음 저장 실패' } }, 409);
      const n = state.rNotifications.find((x) => x.notification_id === p.split('/')[4]);
      if (n && !n.read) { n.read = true; state.unreadCount = Math.max(0, state.unreadCount - 1); }
      payload = { notification_id: p.split('/')[4], read: true };
    }
    else if (p === '/checklist/submissions' && m === 'POST' && state.failSubmit) return reply({ error: { message: '제출 실패' } }, 503);
    else if (p === '/checklist/submissions' && m === 'POST') { state.submitted = { done_lines: 1, total_lines: 2, submitted_at: NOW }; payload = { submission: state.submitted }; }
    else if (p === '/learn/v2/sessions' && m === 'GET') {
      if (state.sessionsDelayMs) await new Promise((r) => setTimeout(r, state.sessionsDelayMs));
      if (state.failSessions > 0) { state.failSessions -= 1; return reply({ error: { message: '대화 목록 실패' } }, 503); }
      payload = { sessions: state.sessions };
    }
    else if (p === '/learn/v2/sessions' && m === 'POST') { state.sessions = [{ session_id: '1' }]; payload = { session_id: '1' }; }
    else if (/^\/learn\/v2\/sessions\/\w+\/history$/.test(p)) {
      // olderMessages 가 있으면 첫 쪽은 '이전 대화 보기'를 남기고, before 로 부르면 그 앞 쪽을 준다
      if (url.searchParams.get('before')) payload = { messages: state.olderMessages ?? [], next_before: null, has_pending_updates: false };
      else payload = { messages: state.messages, next_before: state.olderMessages ? 'b1' : null, has_pending_updates: false };
    }
    else if (p === '/learn/v2/chat' && m === 'POST') {
      if (state.chatDelayMs) await new Promise((r) => setTimeout(r, state.chatDelayMs));
      payload = state.chatEscalate
        ? { action: 'ESCALATE', message: '사장님께 물어볼게요.', context_id: null, allowed_options: [], pending_id: '104', citations: [] }
        : { action: 'ANSWER', message: 'ICE 바닐라 라떼는 바닐라 시럽 2펌프예요.', context_id: null, allowed_options: [], pending_id: null,
          citations: [{ card_id: '1', card_version_id: '10', block_id: 'b1', source_availability: 'AVAILABLE' }] };
      // 대화 기록에도 남긴다(다시 불러오면 같은 대화가 보이게)
      const n = state.messages.length;
      const base = { receipt_id: null, original_question: null, response: null, context_revision: null, owner_answer_id: null, revision: null, knowledge_status: null };
      state.messages.push({ ...base, message_id: String(n + 1), sender: 'USER', content: body.question },
        { ...base, message_id: String(n + 2), sender: 'BUDDY', content: payload.message, receipt_id: 'r1', original_question: body.question, response: payload, context_revision: 1 });
    }
    else if (p === '/learn/chat' && m === 'GET') payload = { messages: [], session_id: null };
    else if (p === '/learn/faqs' && state.faqs) payload = { store_id: 1, items: state.faqs };
    else if (p === '/learn/faqs') payload = { store_id: 1, items: [
      { question: '바닐라 라떼 시럽 몇 펌프예요?', question_count: 7, distinct_questioners: 3, last_asked_at: NOW, card_id: 1, published_version_id: 10, card_title: '바닐라 라떼', card_content: state.cards[0].content, category_id: 10, category_name: '음료 레시피' },
      { question: '우유 발주 언제 해요?', question_count: 4, distinct_questioners: 2, last_asked_at: NOW, card_id: 6, published_version_id: 60, card_title: '우유 발주', card_content: state.cards[5].content, category_id: 12, category_name: '재고 위치' }] };
    // 근무조·기록
    else if (p === '/checklist/today') payload = checklistToday();
    else if (p === '/checklist/status') payload = { ...checklistToday(), last_submission: { submitted_at: '2026-10-30T13:00:00Z', total_lines: 9, done_lines: 9, business_date: '2026-10-30', shift_names: ['마감'] } };
    else if (p === '/checklist/me') payload = { personal_records_enabled: true };
    else if (p === '/checklist/settings') { if (m === 'PATCH') Object.assign(state.settings, body); payload = state.settings; }
    else if (p === '/checklist/records') {
      const month = url.searchParams.get('month'), other = url.searchParams.has('user_id');
      payload = { user_id: Number(url.searchParams.get('user_id') ?? user.user_id), month, visible: !other || state.settings.staff_records_visible, recording: true,
        days: [['10', 100], ['11', 78], ['12', 50]].map(([d, percent]) => ({ date: `${month}-${d}`, percent, total: 9, done: Math.round(9 * percent / 100), checked_lines: 4, submitted: true })) };
    } else if (/^\/checklist\/records\/[\d-]+$/.test(p)) payload = { date: p.split('/').at(-1), visible: true, submission: { done_lines: 7, total_lines: 9, late: false },
      lines: [{ text: '우유 재고 확인', title: '우유 재고 확인', checked_at: NOW }] };
    else if (p === '/checklist/shifts' && m === 'GET') payload = { items: state.shifts };
    else if (p === '/checklist/shifts' && m === 'POST') {
      const shift = { shift_id: Math.max(0, ...state.shifts.map((s) => s.shift_id)) + 1, name: body.name, starts_at: body.starts_at ?? null, ends_at: body.ends_at ?? null, sort_order: state.shifts.length, card_ids: [] };
      state.shifts.push(shift); payload = shift;
    } else if (p === '/checklist/shifts/order' && m === 'PUT') {
      state.shifts = body.shift_ids.map((id, i) => ({ ...state.shifts.find((s) => s.shift_id === id), sort_order: i })); payload = {};
    } else if (/^\/checklist\/shifts\/\d+\/cards$/.test(p) && m === 'PUT') {
      state.shifts.find((s) => s.shift_id === Number(p.split('/')[3])).card_ids = body.ids; payload = {};
    } else if (/^\/checklist\/shifts\/\d+$/.test(p) && m === 'PATCH') {
      const shift = state.shifts.find((s) => s.shift_id === Number(p.split('/')[3]));
      const { clear_time, ...rest } = body; Object.assign(shift, rest);
      if (clear_time) { shift.starts_at = null; shift.ends_at = null; }
      payload = shift;
    } else if (/^\/checklist\/shifts\/\d+$/.test(p) && m === 'DELETE') {
      state.shifts = state.shifts.filter((s) => s.shift_id !== Number(p.split('/')[3])); payload = {};
    }
    else if (p === '/checklist/members') payload = { items: state.checklistMembers };
    else if (/^\/checklist\/members\/\d+\/shifts$/.test(p) && m === 'PUT') {
      const wait = state.memberShiftDelays?.length ? state.memberShiftDelays.shift() : state.memberShiftDelayMs;
      if (wait) await new Promise((r) => setTimeout(r, wait));
      if (state.failMemberShifts) return reply({ error: { message: '저장 실패' } }, 503);
      state.checklistMembers.find((x) => x.member_id === Number(p.split('/')[3])).shift_ids = body.ids; payload = {};
    }
    else if (/^\/checklist\/cards\/\d+$/.test(p)) {
      const id = Number(p.split('/').at(-1));
      if (body) state.cardLinks[id] = body;
      payload = state.cardLinks[id] ?? { checklist: false, shift_ids: [] };
    }
    // 사장이 보내는 오늘만 할 일(main cecca61 의 오늘 매장 섹션)
    else if (p === '/today-tasks' && m === 'GET') payload = { business_date: '2026-10-31', items: [] };
    else if (p === '/today-tasks/mine' && m === 'GET') payload = { business_date: '2026-10-31', items: [] };
    // 직원 관리
    else if (p === '/members') payload = { pending: state.joinRequests, active: state.members };
    else if (/^\/members\/requests\/\d+\/(approve|reject)$/.test(p) && m === 'POST') {
      const [, , , id, action] = p.split('/');
      const request = state.joinRequests.find((r) => r.request_id === Number(id));
      state.joinRequests = state.joinRequests.filter((r) => r !== request);
      if (action === 'approve' && request) state.members.push({ user_id: 10 + request.request_id, name: request.name, role: 'STAFF', joined_at: NOW });
      payload = {};
    } else if (/^\/members\/\d+\/remove$/.test(p) && m === 'POST') {
      state.members = state.members.filter((x) => x.user_id !== Number(p.split('/')[2])); payload = {};
    }
    else if (p === '/members/invite-link/rotate' && m === 'POST') payload = { url: 'http://127.0.0.1:3011/join/synthetic-invite-2' };
    else if (p === '/members/invite-link') payload = { url: 'http://127.0.0.1:3011/join/synthetic-invite' };
    // 넣기
    else if (p === '/ingest/capabilities') payload = { TEXT: { extensions: ['txt'], max_bytes: null }, SCAN: { extensions: ['pdf', 'jpg', 'jpeg', 'png', 'docx'], max_bytes: null, max_pages: null }, KAKAO: { extensions: ['txt', 'jpg', 'jpeg', 'png'], max_bytes: null } };
    else if (p === '/ingest/upload-url') payload = { upload_url: 'http://localhost:8000/storage/put', file_url: '1/scan/synthetic.txt' };
    else if (p === '/storage/put') {
      if (state.uploadDelayMs) await new Promise((r) => setTimeout(r, state.uploadDelayMs));
      if (state.failUpload) return reply({ error: { message: 'synthetic upload failure' } }, 500);
      // 앞에서부터 N 개만 실패(일부 파일만 실패한 경우)
      if (state.failUploadCount > 0) { state.failUploadCount -= 1; return reply({ error: { message: 'synthetic upload failure' } }, 500); }
      // 멈춘 업로드: 응답하지 않는다(화면의 시간 제한 검사용)
      if (state.stallUpload) return new Promise(() => {});
      payload = {};
    }
    else if (p === '/ingest/sources' && m === 'POST') payload = { source_id: 31, status: 'QUEUED', duplicate: Boolean(state.duplicateSource) };
    else if (/^\/ingest\/owner-answers\/\d+\/attachments$/.test(p) && m === 'POST') payload = { job_id: 7 };
    else if (p === '/ingest/jobs' && m === 'POST') {
      if (state.failJobCreate > 0) { state.failJobCreate -= 1; return reply({ error: { message: '작업 만들기 실패' } }, 503); }
      payload = { job_id: 7, status: 'QUEUED' };
    }
    else if (p === '/ingest/jobs' && m === 'GET') {
      const status = jobStatus();
      payload = { items: [{ job_id: 7, title: null, status, category_version: 1, source_count: jobSources(status).length, card_count: 4, created_at: NOW, completed_at: ACTIVE.has(status) ? null : (state.jobCompletedAt ?? new Date().toISOString()) }], next_cursor: null, total: 1 };
    } else if (p === '/ingest/jobs/7' && m === 'GET') {
      const status = jobStatus(), sources = jobSources(status);
      payload = { job_id: 7, title: null, status, category_version: 1,
        counts: { sources: sources.length, succeeded: sources.filter((x) => x.status === 'SUCCEEDED').length, failed: sources.filter((x) => x.status === 'FAILED').length, partial: 0, cards: ACTIVE.has(status) ? 0 : 4 },
        sources, review_destination: '/owner/cards?status=all&job_id=7' };
    } else if (p === '/ingest/jobs/7/retry' && m === 'POST') { state.jobSequence = null; state.job = { ...state.job, status: 'QUEUED' }; payload = { job_id: 7, status: 'QUEUED' }; }
    else {
      misses.push(`${m} ${p}`);
      return reply({ error: { message: 'synthetic: unknown endpoint' } }, 404);
    }
    return reply(payload);
  }

  return { handler, misses, calls, state };
}

module.exports = { syntheticApi };
