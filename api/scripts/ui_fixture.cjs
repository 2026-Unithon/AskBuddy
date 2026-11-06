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
      { pending_id: '101', question: '디카페인 원두는 어디 있어요?', status: 'WAITING' },
      { pending_id: '102', question: '오트밀크 라떼도 시럽 2펌프인가요?', status: 'WAITING' },
    ],
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
  const detail = (c) => ({ ...listItem(c), draft: version(c), published: c.review_status === 'APPROVED' ? version(c) : null, events: [],
    evidence: [{ evidence_id: 1, locator_type: 'PAGE', locator: {}, excerpt: c.content.split('\n')[0], source: { source_id: 1, title: '레시피 메모.jpg', source_type: 'SCAN', read_url: null, source_availability: 'AVAILABLE' } }] });
  const roadmapItems = state.cards.filter((c) => c.review_status === 'APPROVED').map((c) => ({ item_id: c.card_id + 10, card_id: c.card_id, published_version_id: c.card_id * 10, title: c.title, status: 'NOT_STARTED', category_id: c.category_id }));
  const checklistToday = () => ({
    business_date: '2026-10-31', previous_business_date: '2026-10-30', previous_submitted: true,
    scope: { all: role === 'OWNER', shift_ids: [1] }, current_shift_id: 1, upcoming: false,
    shifts: state.shifts.map((s) => ({ ...s, total: s.shift_id === 1 ? 4 : s.shift_id === 2 ? 2 : 3, done: s.shift_id === 1 ? 2 : 0, submitted: false })),
    scope_counts: { total: 4, done: 2 }, view: { total: 4, done: 2 },
    groups: [{ shift_id: 1, name: '오픈', cards: [[4, 40, '오픈 준비', 1, true], [6, 60, '우유 재고 확인', 2, false]].map(([card_id, card_version_id, title, item_id, checked]) => ({ card_id, card_version_id, title, item_id, lines: [{ line_no: 1, text: title, checked }] })) }],
    my_submission: null,
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
    calls.push({ method: m, path: p + url.search, body });
    const reply = (payload, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(payload),
      headers: { 'access-control-allow-origin': req.headers().origin ?? '*', 'access-control-allow-credentials': 'true' } });
    let payload;

    if (p === '/auth/refresh') payload = { token: 'synthetic-ui-only', user: { user_id: user.user_id, role, store_id: 1 } };
    else if (p === '/auth/providers') payload = { kakao: true };
    else if (p === '/app/bootstrap') payload = { user: { ...user, role }, store: STORE, badges: { waiting_questions: state.pending.length, pending_cards: 2 },
      default_destination: role === 'OWNER' ? '/owner' : '/staff' };
    // 알림: 사장(/notifications 목록)과 직원(R 읽음 표시)이 같은 경로를 쓴다
    else if (p === '/notifications' && m === 'GET') payload = { items: state.notifications, unread_count: state.unreadCount, next_cursor: null,
      notifications: state.notifications.map((n) => ({ notification_id: String(n.notification_id), title: n.title, body: n.body, destination: n.destination, read: Boolean(n.read_at) })), next_after: null };
    else if (/^\/notifications\/\w+\/read$/.test(p)) payload = { notification_id: p.split('/')[2], read_at: NOW, read: true };
    else if (p === '/notifications/support') payload = { push_configured: false, vapid_public_key: null, guide_version: '1', guide_seen: true };
    else if (p === '/notifications/my-subscriptions') payload = { subscription_id: 0, enabled: false };
    // 사장 질문
    else if (p === '/learn/v2/pending') payload = { questions: state.pending, next_after: null };
    else if (/^\/learn\/v2\/pending\/\d+$/.test(p)) {
      const q = state.pending.find((x) => x.pending_id === p.split('/').at(-1));
      if (!q) return reply({ error: { message: '없는 질문' } }, 404);
      payload = { pending_id: q.pending_id, status: q.status, question: q.question, question_contract: 'v2', legacy_answers: [], answers: [],
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
      // 서버(api/app/cards/router.py)처럼 restore 는 공개 전 카드를 PENDING 으로 되돌린다
      c.review_status = { approve: 'APPROVED', exclude: 'EXCLUDED', restore: 'PENDING' }[action];
      payload = { card_id: c.card_id, review_status: c.review_status, draft_version_id: c.card_id * 10, published_version_id: c.review_status === 'APPROVED' ? c.card_id * 10 : null, updated_at: NOW, undo_until: null };
    } else if (/^\/cards\/\d+\/category$/.test(p) && m === 'PATCH') {
      const c = state.cards.find((x) => x.card_id === Number(p.split('/')[2]));
      c.category_id = body.category_id;
      payload = { card_id: c.card_id, review_status: c.review_status, draft_version_id: c.card_id * 10, published_version_id: null, updated_at: NOW, undo_until: null };
    } else if (/^\/cards\/\d+\/facts$/.test(p)) payload = { card_id: Number(p.split('/')[2]), blocks: [], facts: [] };
    else if (p === '/categories') payload = { version: 1, reclassification: null, items: CATEGORIES };
    else if (p === '/learn/knowledge-proposals') payload = { store_id: 1, status: 'PENDING_REVIEW', items: [] };
    // 직원 학습·레시피
    else if (p === '/learn/roadmap') payload = { store: { store_id: 1, name: STORE.store_name }, counts: { total: roadmapItems.length, done: 0, reconfirm_required: 0 }, continue_item_id: roadmapItems[0].item_id,
      stages: CATEGORIES.filter((c) => roadmapItems.some((i) => i.category_id === c.category_id)).map((c, i) => ({ category_id: c.category_id, name: c.name, order: i + 1, items: roadmapItems.filter((x) => x.category_id === c.category_id) })) };
    else if (/^\/learn\/items\/\d+$/.test(p)) {
      const item = roadmapItems.find((x) => x.item_id === Number(p.split('/').at(-1)));
      if (!item) return reply({ error: { message: '없는 항목' } }, 404);
      const c = state.cards.find((x) => x.card_id === item.card_id);
      payload = { ...item, content: c.content, category: category(c.category_id), evidence: [], return_to: { path: '/staff/recipes', item_id: item.item_id } };
    }
    else if (p === '/learn/v2/sessions' && m === 'GET') payload = { sessions: state.sessions };
    else if (p === '/learn/v2/sessions' && m === 'POST') { state.sessions = [{ session_id: '1' }]; payload = { session_id: '1' }; }
    else if (/^\/learn\/v2\/sessions\/\w+\/history$/.test(p)) payload = { messages: state.messages, next_before: null, has_pending_updates: false };
    else if (p === '/learn/v2/chat' && m === 'POST') {
      payload = { action: 'ANSWER', message: 'ICE 바닐라 라떼는 바닐라 시럽 2펌프예요.', context_id: null, allowed_options: [], pending_id: null,
        citations: [{ card_id: '1', card_version_id: '10', block_id: 'b1', source_availability: 'AVAILABLE' }] };
    }
    else if (p === '/learn/chat' && m === 'GET') payload = { messages: [], session_id: null };
    else if (p === '/learn/faqs') payload = { store_id: 1, items: [
      { question: '바닐라 라떼 시럽 몇 펌프예요?', question_count: 7, distinct_questioners: 3, last_asked_at: NOW, card_id: 1, published_version_id: 10, card_title: '바닐라 라떼', card_content: state.cards[0].content, category_id: 10, category_name: '음료 레시피' },
      { question: '우유 발주 언제 해요?', question_count: 4, distinct_questioners: 2, last_asked_at: NOW, card_id: 6, published_version_id: 60, card_title: '우유 발주', card_content: state.cards[5].content, category_id: 12, category_name: '재고 위치' }] };
    // 근무조·기록
    else if (p === '/checklist/today') payload = checklistToday();
    else if (p === '/checklist/status') payload = { ...checklistToday(), last_submission: { submitted_at: '2026-10-30T13:00:00Z', total_lines: 9, done_lines: 9, business_date: '2026-10-30', shift_names: ['마감'] } };
    else if (p === '/checklist/me') payload = { personal_records_enabled: true };
    else if (p === '/checklist/settings') payload = { business_day_starts_at: '04:00', staff_records_visible: true, timezone: 'Asia/Seoul' };
    else if (p === '/checklist/records') payload = { user_id: user.user_id, month: '2026-10', visible: true, recording: true,
      days: [['2026-10-29', 100], ['2026-10-30', 78], ['2026-10-31', 50]].map(([date, percent]) => ({ date, percent, total: 9, done: Math.round(9 * percent / 100), checked_lines: 4, submitted: true })) };
    else if (p === '/checklist/shifts' && m === 'GET') payload = { items: state.shifts };
    else if (p === '/checklist/members') payload = { items: [{ member_id: 2, user_id: 2, role: 'STAFF', name: '박지호', shift_ids: [1] }, { member_id: 3, user_id: 3, role: 'STAFF', name: '김민준', shift_ids: [3] }] };
    else if (/^\/checklist\/cards\/\d+$/.test(p)) payload = { checklist: false, shift_ids: [] };
    // 직원 관리
    else if (p === '/members') payload = { pending: [{ request_id: 9, name: '이서연', requested_at: NOW }],
      active: [{ user_id: 2, name: '박지호', role: 'STAFF', joined_at: NOW }, { user_id: 3, name: '김민준', role: 'STAFF', joined_at: NOW }] };
    else if (p === '/members/invite-link') payload = { url: 'http://127.0.0.1:3011/join/synthetic-invite' };
    // 넣기
    else if (p === '/ingest/capabilities') payload = { TEXT: { extensions: ['txt'], max_bytes: null }, SCAN: { extensions: ['pdf', 'jpg', 'jpeg', 'png', 'docx'], max_bytes: null, max_pages: null }, KAKAO: { extensions: ['txt', 'jpg', 'jpeg', 'png'], max_bytes: null } };
    else if (p === '/ingest/upload-url') payload = { upload_url: 'http://localhost:8000/storage/put', file_url: '1/scan/synthetic.txt' };
    else if (p === '/storage/put') {
      if (state.uploadDelayMs) await new Promise((r) => setTimeout(r, state.uploadDelayMs));
      if (state.failUpload) return reply({ error: { message: 'synthetic upload failure' } }, 500);
      payload = {};
    }
    else if (p === '/ingest/sources' && m === 'POST') payload = { source_id: 31, status: 'QUEUED', duplicate: false };
    else if (p === '/ingest/jobs' && m === 'POST') payload = { job_id: 7, status: 'QUEUED' };
    else if (p === '/ingest/jobs' && m === 'GET') {
      const status = jobStatus();
      payload = { items: [{ job_id: 7, title: null, status, category_version: 1, source_count: jobSources(status).length, card_count: 4, created_at: NOW, completed_at: ACTIVE.has(status) ? null : NOW }], next_cursor: null, total: 1 };
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
