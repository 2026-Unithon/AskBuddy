// W3b 점주 사실 카드 화면 — 실제 브라우저 상태 검사.
// API 는 Playwright 가 가로채는 **합성 fixture** 다. 실제 FastAPI·DB·모델을 부르지 않는다(지출 0).
// 로그인은 합성 /auth/refresh 응답으로 만든다(지금 앱은 localStorage 토큰을 지우고 쿠키 갱신으로 복원한다).
//
// 실행:
//   pnpm --dir web build && pnpm --dir web exec next start -p 3011
//   NODE_PATH=<playwright 가 있는 node_modules> node api/scripts/verify_w3b_card_facts_ui.cjs
// 화면 사진은 W3B_UI_SHOTS(기본 api/tmp/w3b-ui) 에 남는다.
const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const BASE = "http://127.0.0.1:3011";
const OUT = process.env.W3B_UI_SHOTS || path.resolve(__dirname, "../tmp/w3b-ui");

const origin = (o) => ({
  kind: "SOURCE", source_id: null, source_title: null, source_type: null, source_availability: null,
  locator_type: null, locator: {}, owner_answer_id: null, created_at: null, ...o,
});
const row = (o) => ({
  subject: "음료Z", predicate: null, variant: { temperature: null, size: null }, value: null, unit: null,
  polarity: "AFFIRM", step_order: null, conditions: [], exceptions: [], requires: [], change_kind: "EXTRACTION",
  previous_sentence: null, origins: [], edit_block: null, assertion: o.sentence, ...o,
});

function factCardView(version) {
  return {
    card_id: 1, version_id: version, title: "음료Z", entity_id: 9, entity_name: "음료Z", review_status: "APPROVED",
    published_version_id: 10, editable: true, entity_problem: null,
    blocks: [
      { block_id: "b1", kind: "QUANTITIES", order: 1, variant: { temperature: "ICE", size: null }, facts: [
        row({ fact_revision_id: 101, fact_id: 1, position: 1, sentence: "음료Z ICE 물은 225ml 넣는다.", value: "225", unit: "ml",
          variant: { temperature: "ICE", size: null },
          origins: [origin({ source_id: 5, source_title: "합성 매뉴얼.pdf", source_type: "SCAN", source_availability: "AVAILABLE", locator_type: "PAGE", locator: { page: 3 } })] }),
        row({ fact_revision_id: 102, fact_id: 2, position: 2, sentence: "음료Z ICE 시럽은 10g 넣는다.", value: "10", unit: "g",
          variant: { temperature: "ICE", size: null }, change_kind: "OWNER_CORRECTION", previous_sentence: "음료Z ICE 시럽은 15g 넣는다.",
          origins: [origin({ source_id: 6, source_title: "지난 메모.jpg", source_type: "SCAN", source_availability: "DELETED", locator_type: "WHOLE_SOURCE" })] }),
      ] },
      { block_id: "b2", kind: "STEPS", order: 2, variant: { temperature: null, size: null }, facts: [
        row({ fact_revision_id: 201, fact_id: 3, position: 1, sentence: "컵에 얼음을 담는다.", step_order: 1,
          origins: [origin({ kind: "OWNER_TEXT", source_id: 7, source_title: "카드 직접 입력 · 음료Z", source_type: "OWNER_TEXT", source_availability: "AVAILABLE", locator_type: "LINE", locator: { line: 1 }, created_at: "2026-10-08T03:00:00Z" })] }),
        row({ fact_revision_id: 202, fact_id: 4, position: 2, sentence: "샷을 붓는다.", step_order: 2, conditions: ["손님이 연하게 원하면 한 번만"],
          requires: [{ fact_id: 3, label: "1번" }],
          origins: [origin({ source_id: 8, source_title: "합성 영상.mp4", source_type: "VIDEO", source_availability: "AVAILABLE", locator_type: "TIMESTAMP", locator: { timestamp_sec: 75 } })] }),
        row({ fact_revision_id: 203, fact_id: 5, position: 3, sentence: "물을 붓는다.", step_order: 3,
          origins: [origin({ kind: "OWNER_ANSWER", owner_answer_id: 3 })] }),
        // 204 는 202(샷, fact 4)가 먼저다 → 라벨은 초안의 202 번호를 따라간다
        row({ fact_revision_id: 204, fact_id: 7, position: 4, sentence: "뚜껑을 닫는다.", step_order: 4,
          requires: [{ fact_id: 4, label: "2번" }],
          origins: [origin({ source_id: 5, source_title: "합성 매뉴얼.pdf", source_type: "SCAN", source_availability: "AVAILABLE", locator_type: "PAGE", locator: { page: 5 } })] }),
      ] },
      { block_id: "b3", kind: "NOTES", order: 3, variant: { temperature: null, size: null }, facts: [
        row({ fact_revision_id: 301, fact_id: 6, position: 1, sentence: "음료Z에는 휘핑을 올리지 않는다.", polarity: "NEGATE",
          exceptions: ["손님이 따로 요청하면"], edit_block: "CHANGED_ELSEWHERE",
          origins: [origin({ source_id: 5, source_title: "합성 매뉴얼.pdf", source_type: "SCAN", source_availability: "AVAILABLE", locator_type: "PAGE", locator: { page: 4 } })] }),
      ] },
    ],
  };
}

function singleView(cardId, extra = {}) {
  return {
    card_id: cardId, version_id: 40 + cardId, title: `합성음료A ${cardId}`, entity_id: 10, entity_name: "합성음료A", review_status: "PENDING",
    published_version_id: null, editable: true, entity_problem: null,
    blocks: [{ block_id: "s1", kind: "NOTES", order: 1, variant: { temperature: null, size: null }, facts: [
      row({ fact_revision_id: 400 + cardId, fact_id: 40 + cardId, position: 1, sentence: "합성음료A는 매장에서만 판다.", subject: "합성음료A",
        origins: [origin({ source_id: 5, source_title: "합성 매뉴얼.pdf", source_availability: "AVAILABLE", locator_type: "PAGE", locator: { page: 1 } })] }),
    ] }],
    ...extra,
  };
}

// 카드 8: 번호가 같은 두 단계 / 카드 9: 사실로 나뉘지 않은 RAW 블록이 섞임
function rawMixedView() {
  const v = singleView(9);
  v.blocks.push({ block_id: "raw1", kind: "RAW", order: 2, variant: { temperature: null, size: null }, facts: [
    row({ fact_revision_id: 901, fact_id: 91, position: 1, sentence: "합성 원문 한 덩어리." }),
  ] });
  return v;
}

// 카드 12: 단계 1~4 가 있는 절차. 새 단계를 끼워 넣는 시나리오(물을 붓는다는 얼음 단계가 먼저)
function stepsInsertView() {
  const v = singleView(12);
  v.blocks = [{ block_id: "i1", kind: "STEPS", order: 1, variant: { temperature: null, size: null }, facts: [
    row({ fact_revision_id: 1201, fact_id: 121, position: 1, sentence: "합성음료A 컵을 꺼낸다.", step_order: 1 }),
    row({ fact_revision_id: 1202, fact_id: 122, position: 2, sentence: "합성음료A 얼음을 담는다.", step_order: 2 }),
    row({ fact_revision_id: 1203, fact_id: 123, position: 3, sentence: "합성음료A 물을 붓는다.", step_order: 3,
      requires: [{ fact_id: 122, label: "2번" }] }),
    row({ fact_revision_id: 1204, fact_id: 124, position: 4, sentence: "합성음료A 뚜껑을 닫는다.", step_order: 4 }),
  ] }];
  return v;
}

const state = {
  version: 10,
  saveQueue: [],
  saveBodies: [],
  parseBodies: [],
  factsCalls: {},
  excluded: new Set(),
  excludeCalls: [],
  failFactsOnce: true,
  failCard1FactsOnce: false,
  cardCalls: {},
};

function cardDetail(cardId) {
  const fact = cardId !== 2;
  const excluded = state.excluded.has(cardId);
  const title = cardId === 1 ? "음료Z" : cardId === 2 ? "합성 옛 카드" : `합성음료A ${cardId}`;
  return {
    card_id: cardId, review_status: excluded ? "EXCLUDED" : cardId === 1 ? "APPROVED" : "PENDING", assignment_type: "AUTOMATIC",
    category: { category_id: 1, name: "음료" }, source: null, job_id: null, needs_review_reason: null,
    draft: { version_id: cardId === 1 ? state.version : 40 + cardId, version_no: 1, title,
      content: cardId === 2 ? "합성 옛 카드 첫 줄\n합성 옛 카드 둘째 줄" : "렌더된 본문", change_source: "EXTRACTION", created_at: "2026-10-08T03:00:00Z" },
    // 카드 1 은 공개판(10)이 있다 → 저장 뒤 초안 판이 달라지면 "고친 내용 공개 전"
    published: cardId === 1 ? { version_id: 10, version_no: 1, title, content: "렌더된 본문", change_source: "EXTRACTION", created_at: "2026-10-08T03:00:00Z" } : null,
    evidence: [], events: [], updated_at: "2026-10-08T03:00:00Z",
    fact_card: fact,
  };
}

// 계획 10: 사실 카드 보기는 서버처럼 언제나 구역 제목·줄을 싣는다
const { withLines } = require("./ui_fixture.cjs");
const json = (route, status, payload) => route.fulfill({ status, contentType: "application/json",
  body: JSON.stringify(payload && Array.isArray(payload.blocks) && payload.blocks.every((b) => Array.isArray(b.facts)) ? withLines(payload) : payload) });
const apiError = (route, status, code, message, details, retryable = false) => json(route, status, { error: { code, message, retryable, details } });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function handle(route) {
  const req = route.request();
  const url = new URL(req.url());
  const p = url.pathname;
  const method = req.method();
  if (p === "/auth/refresh") return json(route, 200, { token: "synthetic-ui-only", user: { user_id: 1, role: "OWNER", store_id: 1 } });
  if (p === "/app/bootstrap") {
    return json(route, 200, { user: { user_id: 1, role: "OWNER", name: "합성 점주" },
      store: { store_id: 1, store_name: "합성 UI 매장", guide_completed: true, category_version: 1 },
      badges: { waiting_questions: 0, pending_cards: 0 }, default_destination: "/owner" });
  }
  if (p === "/ingest/jobs") return json(route, 200, { items: [], next_cursor: null, total: 0 });
  // 공개 카드의 근무조 연결 칸(CardAssignment)
  if (/^\/checklist\/cards\/\d+$/.test(p) && method === "GET") return json(route, 200, { checklist: false, shift_ids: [] });
  if (p === "/checklist/shifts" && method === "GET") return json(route, 200, { items: [] });
  let m = p.match(/^\/cards\/(\d+)$/);
  if (m && method === "GET") {
    const id = Number(m[1]);
    state.cardCalls[id] = (state.cardCalls[id] ?? 0) + 1;
    return json(route, 200, cardDetail(id));
  }
  m = p.match(/^\/cards\/(\d+)\/facts$/);
  if (m && method === "GET") {
    const id = Number(m[1]);
    state.factsCalls[id] = (state.factsCalls[id] ?? 0) + 1;
    if (id === 5 && state.failFactsOnce) {
      state.failFactsOnce = false;
      await sleep(1200);
      // 자동 재시도가 가리지 않게 retryable=false 인 500 으로 낸다
      return apiError(route, 500, "INTERNAL_ERROR", "합성 사실 목록 오류예요.");
    }
    if (id === 1 && state.failCard1FactsOnce) {
      state.failCard1FactsOnce = false;
      return apiError(route, 500, "INTERNAL_ERROR", "합성 다시 읽기 오류예요.");
    }
    if (id === 1) return json(route, 200, factCardView(state.version));
    if (id === 9) return json(route, 200, rawMixedView());
    if (id === 12) return json(route, 200, stepsInsertView());
    if (id === 11) return apiError(route, 404, "CARD_NOT_FOUND", "카드를 찾을 수 없습니다.");
    if (id === 3) return json(route, 200, singleView(3, { editable: false }));
    if (id === 7) return json(route, 200, singleView(7, { editable: false, entity_problem: "MIXED_ENTITY" }));
    const view = singleView(id);
    if (state.excluded.has(id)) { view.review_status = "EXCLUDED"; view.editable = false; }
    return json(route, 200, view);
  }
  m = p.match(/^\/cards\/(\d+)\/facts\/parse$/);
  if (m && method === "POST") {
    const body = req.postDataJSON();
    state.parseBodies.push(body);
    await sleep(300);
    if (Number(m[1]) === 12) {
      // 분석은 "마지막 단계" 로 읽었다(5번) → 블록 끝에 붙고, 점주가 위로 옮겨 3번 자리에 둔다
      return json(route, 200, { mode: "ADD", warnings: [], proposals: [
        { client_ref: "p1", block_kind: "STEPS", warnings: [], fact: { sentence: "합성음료A 시럽을 넣는다.", polarity: "AFFIRM", value: null, unit: null,
          conditions: [], exceptions: [], step_order: 5, variant: { temperature: null, size: null }, predicate: null } },
      ] });
    }
    if (body.mode === "MODIFY") {
      return json(route, 200, { mode: "MODIFY", warnings: ["MODIFY_SPLIT"], proposals: [
        { client_ref: "p1", block_kind: "QUANTITIES", warnings: [], fact: { sentence: "음료Z ICE 물은 250ml 넣는다.", polarity: "AFFIRM", value: "250", unit: "ml",
          conditions: [], exceptions: [], step_order: null, variant: { temperature: "ICE", size: null }, predicate: null } },
        { client_ref: "p2", block_kind: "NOTES", warnings: [], fact: { sentence: "얼음은 가득 채운다.", polarity: "AFFIRM", value: null, unit: null,
          conditions: [], exceptions: [], step_order: null, variant: { temperature: null, size: null }, predicate: null } },
      ] });
    }
    return json(route, 200, { mode: "ADD", warnings: ["MULTIPLE_FACTS"], proposals: [
      { client_ref: "p1", block_kind: "NOTES", warnings: [], fact: { sentence: "음료Z는 빨대를 꽂아 낸다.", polarity: "AFFIRM", value: null, unit: null,
        conditions: [], exceptions: [], step_order: null, variant: { temperature: null, size: null }, predicate: "제공" } },
      { client_ref: "p2", block_kind: "NOTES", warnings: ["SUBJECT_MISMATCH"], fact: { sentence: "합성음료B는 컵 뚜껑을 닫는다.", polarity: "AFFIRM", value: null, unit: null,
        conditions: [], exceptions: [], step_order: null, variant: { temperature: null, size: null }, predicate: null } },
      { client_ref: "p3", block_kind: "QUANTITIES", warnings: ["VARIANT_UNRESOLVED"], fact: { sentence: "점보 사이즈는 물 400ml.", polarity: "AFFIRM", value: "400", unit: "ml",
        conditions: [], exceptions: [], step_order: null, variant: { temperature: null, size: null }, predicate: null } },
    ] });
  }
  m = p.match(/^\/cards\/(\d+)\/facts$/);
  if (m && method === "PUT") {
    const body = req.postDataJSON();
    state.saveBodies.push(body);
    const mode = state.saveQueue.shift() ?? "ok";
    if (mode === "network") return route.abort("failed");
    if (mode === "conflict") return apiError(route, 409, "CARD_VERSION_CONFLICT", "카드가 바뀌었습니다.", { current_version_id: state.version + 1 });
    if (mode === "value") return apiError(route, 422, "FACT_VALUE_NOT_IN_SENTENCE", "숫자 칸과 문장 속 숫자가 달라요.", { ref: 101 });
    if (mode === "steps") return apiError(route, 422, "STEP_REQUIRES_ORDER", "선행 단계 순서 오류.", { ref: 203, requires_fact_id: 4 });
    if (mode === "stepOrder") return apiError(route, 422, "CARD_LAYOUT_INVALID", "카드 배치가 올바르지 않습니다.", { plan_code: "PLAN_STEP_ORDER" });
    await sleep(300);
    state.version += 1;
    return json(route, 200, { card_id: 1, review_status: "PENDING", draft_version_id: state.version, published_version_id: null,
      updated_at: "2026-10-09T03:00:00Z", undo_until: null, changed: true, edit_id: state.saveBodies.length, revisions: [] });
  }
  m = p.match(/^\/cards\/(\d+)\/exclude$/);
  if (m && method === "POST") {
    const id = Number(m[1]);
    state.excludeCalls.push(id);
    state.excluded.add(id);
    return json(route, 200, { card_id: id, review_status: "EXCLUDED", draft_version_id: 40 + id, published_version_id: null,
      updated_at: "2026-10-09T03:00:00Z", undo_until: "2026-10-09T03:00:10Z" });
  }
  return apiError(route, 404, "NOT_FOUND", `합성 fixture 에 없는 경로: ${method} ${p}`);
}

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  const passed = [];
  const errors = [];
  const unknown = [];
  const check = (name, value) => { assert.ok(value, name); passed.push(name); console.log("PASS W3b-UI", name); };
  try {
    const ctx = await browser.newContext({ viewport: { width: 390, height: 844 } });
    await ctx.route(/^http:\/\/(localhost|127\.0\.0\.1):8000\//, async (route) => {
      const before = route.request().url();
      await handle(route).catch((e) => { unknown.push(`${before}: ${e.message}`); return route.abort("failed"); });
    });
    const page = await ctx.newPage();
    page.on("pageerror", (e) => errors.push(e.message));
    page.on("response", (r) => { if (r.status() === 404 && r.url().includes(":8000/") && !r.url().endsWith("/cards/11/facts")) unknown.push(r.url()); });
    const shot = async (name) => {
      // 버튼 켜짐/꺼짐 전환(transition)이 끝난 뒤 찍는다
      await page.waitForTimeout(300);
      await page.screenshot({ path: path.join(OUT, `${name}.png`), fullPage: false });
    };
    const noOverflow = () => page.evaluate(() =>
      [...document.querySelectorAll("main")].every((main) => main.scrollWidth <= main.clientWidth) && document.documentElement.scrollWidth <= innerWidth);
    const text = (t) => page.getByText(t, { exact: true });
    const inViewport = async (loc) => {
      const box = await loc.boundingBox();
      const vp = page.viewportSize();
      return Boolean(box) && box.y >= 0 && box.y + box.height <= vp.height + 1;
    };
    const panel = () => page.getByTestId("fact-panel");

    // ── 로딩 Skeleton → 사실 목록 오류 → 다시 시도 (카드 5)
    await page.goto(`${BASE}/owner/cards/5`);
    await page.getByTestId("fact-panel-loading").waitFor();
    await shot("01-loading-390");
    check("로딩 중 사실 목록 Skeleton", await page.getByTestId("fact-panel-loading").isVisible());
    await page.getByText("합성 사실 목록 오류예요.", { exact: true }).waitFor();
    await shot("02-facts-error-390");
    await page.getByRole("button", { name: "다시 시도", exact: true }).click();
    await panel().waitFor();
    check("사실 목록 오류 뒤 다시 시도로 복구", state.factsCalls[5] >= 2);

    // 계획 10 Task 9: 수정은 보기와 같은 줄 타일. 타일 이름은 '{줄 글} 옮기기', 누르면 '이 줄 고치기' 시트
    const tile = (lineText) => page.getByRole("button", { name: `${lineText} 옮기기`, exact: true });
    const tiles = async () => page.locator("[data-tile]").allInnerTexts();
    const press = async (lineText, key) => { await tile(lineText).press(key); await page.waitForTimeout(50); };
    const editTile = async (lineText, next) => {
      await tile(lineText).click();
      const sheet = page.getByRole("dialog", { name: "이 줄 고치기" });
      await sheet.waitFor();
      await sheet.getByRole("textbox").fill(next);
      await sheet.getByRole("button", { name: "바꾸기", exact: true }).click();
      await sheet.waitFor({ state: "detached" });
    };
    const removeTile = async (lineText) => {
      await tile(lineText).click();
      await page.getByRole("dialog", { name: "이 줄 고치기" }).getByRole("button", { name: "이 줄 빼기", exact: true }).click();
    };
    const leaveEdit = async () => {
      await page.getByRole("button", { name: "돌아가기", exact: true }).click();
      const discard = page.getByRole("dialog", { name: "고친 내용을 버릴까요?" });
      if (await discard.isVisible().catch(() => false)) await discard.getByRole("button", { name: "버리기" }).click();
    };

    // ── 사실 카드 보기 (카드 1)
    await page.goto(`${BASE}/owner/cards/1`);
    await panel().waitFor();
    // 화면 개선 계획 3: 보기 모드는 블록 머리글(카드 밖), 칩·줄마다 근거 없음, 근거는 맨 아래 한 줄
    // 2026-11-08 사용자: '수치·순서·목록' 머리글은 뜻이 없어 규격(HOT/ICE) 머리글만 둔다
    check("블록 머리글은 규격만",
      await page.getByRole("heading", { name: "ICE", exact: true }).isVisible() && await page.getByRole("heading", { name: "순서", exact: true }).count() === 0 && await page.getByRole("heading", { name: "목록", exact: true }).count() === 0);
    check("보기 모드에 하지 않음 칩 없음", await page.locator("main").getByText("하지 않음", { exact: true }).count() === 0);
    // 계획 10: 원문 줄은 문장 뒤에 (조건: …)·(예외: …) 를 붙인다
    check("조건·예외 줄", await page.getByText("(조건: 손님이 연하게 원하면 한 번만)", { exact: false }).isVisible() && await page.getByText("(예외: 손님이 따로 요청하면)", { exact: false }).isVisible());
    check("보기 모드에 줄마다 근거·이전 문장 없음", await page.getByText(/^근거:|^이전:|^먼저:/).count() === 0);
    const evidenceLine = await page.getByText(/^근거 자료 /).innerText();
    check("근거 자료 한 줄", ["합성 매뉴얼.pdf", "합성 영상.mp4", "사장님 답변", "사장님 직접 입력", "지난 메모.jpg (원본 지워짐)"].every((n) => evidenceLine.includes(n)));
    check("제목 안내 문구 없음(화면 개선 o06a)", await page.getByText("제목은 메뉴").count() === 0);
    check("값은 문장 안에서 굵게", await page.locator("main strong", { hasText: "225ml" }).count() === 1);
    check("저장 전: 공개판과 같아 공개 전 안내 없음", await text("고친 내용은 아직 공개 전이에요").count() === 0);
    check("보기 화면에 신뢰도·완성도 % 없음", !(await page.locator("main").innerText()).includes("%"));
    for (const [w, h] of [[390, 844], [360, 800]]) {
      await page.setViewportSize({ width: w, height: h });
      check(`보기 ${w}px 가로 넘침 없음`, await noOverflow());
      await shot(`03-view-${w}`);
    }
    await page.setViewportSize({ width: 390, height: 844 });

    // ── 편집: 고치기 시트 + 다시 분석(MODIFY_SPLIT 안내)
    await page.getByRole("button", { name: "수정하기", exact: true }).click();
    await page.getByRole("button", { name: "수정 완료", exact: true }).waitFor();
    // 고친 게 없으면 수정 완료는 저장 없이 읽는 화면으로(2026-11-08). 다시 들어간다
    await page.getByRole("button", { name: "수정 완료", exact: true }).click();
    await page.getByRole("button", { name: "수정하기", exact: true }).click();
    await page.getByRole("button", { name: "수정 완료", exact: true }).waitFor();
    check("편집 전 수정 완료는 저장 요청 없음", state.saveBodies.length === 0);
    await tile("음료Z ICE 물은 225ml 넣는다.").click();
    const dialog = page.getByRole("dialog", { name: "이 줄 고치기" });
    await dialog.waitFor();
    check("고치기 시트가 화면 안에 뜸(스크롤과 무관)", await inViewport(dialog));
    await shot("04-edit-sheet-390");
    await dialog.getByRole("button", { name: "그만두기", exact: true }).click();
    await editTile("음료Z ICE 물은 225ml 넣는다.", "음료Z ICE 물은 250ml 넣는다.");
    check("고친 줄 글이 타일에 남음", (await tiles()).includes("음료Z ICE 물은 250ml 넣는다."));
    check("저장 전에는 다시 분석하지 않음", state.parseBodies.length === 0);

    // ── 줄 순서: 막는 규칙 없이 옮긴다(줄은 보이는 순서일 뿐, 사실의 단계 번호는 그대로)
    await press("물을 붓는다.", "ArrowUp");
    // 샷 줄은 조건이 붙어 '샷을 붓는다. (조건: …)' 이다 → 문장 앞부분으로 맞춘다
    const STEP_SENTENCES = ["컵에 얼음을 담는다.", "샷을 붓는다.", "물을 붓는다.", "뚜껑을 닫는다."];
    const stepTiles = (await tiles()).map((t) => STEP_SENTENCES.find((x) => t.startsWith(x))).filter(Boolean);
    check("키보드로 물을 샷 앞으로", JSON.stringify(stepTiles) === JSON.stringify(["컵에 얼음을 담는다.", "물을 붓는다.", "샷을 붓는다.", "뚜껑을 닫는다."]));
    for (const [w, h] of [[390, 844], [360, 800]]) {
      await page.setViewportSize({ width: w, height: h });
      check(`편집 ${w}px 가로 넘침 없음`, await noOverflow());
      await shot(`05-editing-${w}`);
    }
    await page.setViewportSize({ width: 390, height: 844 });

    // ── 저장: 네트워크 실패 → 같은 키로 다시 시도 → 422 값-문장
    state.saveQueue.push("network", "value", "conflict");
    await page.getByRole("button", { name: "수정 완료", exact: true }).click();
    await page.getByRole("button", { name: "다시 시도", exact: true }).waitFor();
    check("네트워크 실패에 입력 유지", (await tiles()).includes("음료Z ICE 물은 250ml 넣는다."));
    check("저장할 때 고친 줄만 다시 분석(MODIFY, 원래 판 101)",
      state.parseBodies.length === 1 && state.parseBodies[0].mode === "MODIFY" && state.parseBodies[0].base_fact_revision_id === 101
      && state.parseBodies[0].text === "음료Z ICE 물은 250ml 넣는다.");
    const first = state.saveBodies[0];
    const blocks = Object.fromEntries(first.blocks.map((b) => [b.kind, b]));
    const q = blocks.QUANTITIES;
    check("요청: 수치 블록 MODIFY 101(250) + KEEP 102, 나머지 제안은 그 줄에 붙는 ADD",
      q.items[0].op === "MODIFY" && q.items[0].fact_revision_id === 101 && q.items[0].fact.value === "250"
      && q.items[1].op === "KEEP" && q.items[1].fact_revision_id === 102
      && q.items[2].op === "ADD" && q.items[2].fact.sentence === "얼음은 가득 채운다."
      && q.lines[0].text === "음료Z ICE 물은 250ml 넣는다." && q.lines[0].client_refs.includes(q.items[2].client_ref));
    check("요청: 단계 사실은 모두 KEEP·원래 순서, 줄만 옮긴 순서",
      JSON.stringify(blocks.STEPS.items.map((i) => [i.op, i.fact_revision_id])) === JSON.stringify([["KEEP", 201], ["KEEP", 202], ["KEEP", 203], ["KEEP", 204]])
      && JSON.stringify(blocks.STEPS.lines.map((l) => l.fact_revision_ids[0])) === JSON.stringify([201, 203, 202, 204]));
    check("요청: 목록 KEEP 301·삭제 없음·기대 판", blocks.NOTES.items[0].op === "KEEP" && first.deleted_fact_revision_ids.length === 0 && first.expected_version_id === 10);
    await page.getByRole("button", { name: "다시 시도", exact: true }).click();
    await text("숫자 칸과 문장 속 숫자가 달라요. 문장도 같이 고쳐 주세요.").waitFor();
    check("재시도는 같은 idempotency_key", state.saveBodies[1].idempotency_key === state.saveBodies[0].idempotency_key);
    check("422 FACT_VALUE_NOT_IN_SENTENCE 문구·입력 유지", (await tiles()).includes("음료Z ICE 물은 250ml 넣는다."));
    await shot("06-validation-422-390");

    // ── 409 충돌 → 배너·그대로 두기
    await page.getByRole("button", { name: "수정 완료", exact: true }).click();
    await page.getByTestId("fact-conflict").waitFor();
    check("409 충돌 배너 문구", await text("그사이 카드가 바뀌었어요. 최신 내용을 불러온 뒤 다시 고쳐 주세요.").isVisible());
    check("충돌에 입력 유지", (await tiles()).includes("음료Z ICE 물은 250ml 넣는다."));
    await shot("07-conflict-390");
    await page.getByRole("button", { name: "그대로 두기", exact: true }).click();
    await page.getByTestId("fact-conflict").waitFor({ state: "detached" });
    check("그대로 두기 뒤 배너 닫힘·편집 유지",
      await page.getByTestId("fact-conflict").count() === 0 && (await tiles()).includes("음료Z ICE 물은 250ml 넣는다."));

    // ── 사실 추가: 분석 3제안 + 경고, 체크한 것만 ADD
    await page.getByRole("button", { name: "+ 사실 추가", exact: true }).click();
    const add = page.getByRole("dialog");
    await add.waitFor();
    check("추가 시트가 화면 안에 뜸", await inViewport(add));
    await add.getByLabel("넣을 내용").fill("음료Z는 빨대를 꽂아 낸다. 합성음료B는 컵 뚜껑을 닫는다. 점보 사이즈는 물 400ml.");
    await add.getByRole("button", { name: "분석하기", exact: true }).click();
    await add.getByTestId("parse-proposals").waitFor();
    const proposalsText = await add.getByTestId("parse-proposals").innerText();
    check("MULTIPLE_FACTS 경고", proposalsText.includes("사실 3개를 찾았어요"));
    check("SUBJECT_MISMATCH 경고", proposalsText.includes("다른 대상 같아요"));
    const boxes = add.getByRole("checkbox");
    check("VARIANT_UNRESOLVED 제안은 체크 불가", await boxes.nth(2).isDisabled() && !(await boxes.nth(2).isChecked()));
    check("SUBJECT_MISMATCH 제안은 처음에 체크 해제", !(await boxes.nth(1).isChecked()) && await boxes.nth(0).isChecked());
    await shot("08-add-proposals-390");
    await add.getByRole("button", { name: /^카드에 넣기/ }).click();
    check("새로 넣은 줄 타일", (await tiles()).includes("음료Z는 빨대를 꽂아 낸다."));

    // ── 저장 성공 → 보기 상태
    await page.getByRole("button", { name: "수정 완료", exact: true }).click();
    await page.getByRole("button", { name: "수정 완료", exact: true }).waitFor({ state: "detached" });
    const ok = state.saveBodies.at(-1);
    const adds = ok.blocks.flatMap((b) => b.items).filter((i) => i.op === "ADD");
    check("체크한 제안만 ADD(고친 줄의 나머지 제안 1건 포함)", adds.length === 2 && adds.some((a) => a.fact.sentence === "음료Z는 빨대를 꽂아 낸다." && /^[A-Za-z0-9_-]+$/.test(a.client_ref)) && /^[A-Za-z0-9_-]+$/.test(adds[0].client_ref));
    check("추가는 같은 규격 목록 블록 끝", ok.blocks.find((b) => b.kind === "NOTES").items.at(-1).op === "ADD");
    check("본문이 바뀌면 새 idempotency_key", ok.idempotency_key !== state.saveBodies[0].idempotency_key);
    await page.getByRole("button", { name: "수정하기", exact: true }).waitFor();
    check("저장 성공 뒤 보기 상태·사실 다시 읽음", state.factsCalls[1] >= 2);
    await text("고친 내용은 아직 공개 전이에요").waitFor();
    check("저장 성공 뒤 고친 내용 공개 전 안내와 공개 버튼", await page.getByRole("button", { name: "공개", exact: true }).isVisible());
    await shot("09-saved-390");

    // ── 다시 편집 → 충돌 → 최신 내용 불러오기
    await page.getByRole("button", { name: "수정하기", exact: true }).click();
    await removeTile("음료Z ICE 시럽은 10g 넣는다.");
    check("뺀 줄이 목록에서 사라짐", await page.getByText("음료Z ICE 시럽은 10g 넣는다.", { exact: true }).count() === 0);
    state.saveQueue.push("conflict");
    await page.getByRole("button", { name: "수정 완료", exact: true }).click();
    await page.getByTestId("fact-conflict").waitFor();
    check("요청: 뺀 줄은 deleted", state.saveBodies.at(-1).deleted_fact_revision_ids.includes(102));
    // 다시 읽기 실패: 초안·배너 유지, 오류 표시
    state.failCard1FactsOnce = true;
    await page.getByRole("button", { name: "최신 내용 불러오기(고친 내용은 사라져요)" }).click();
    await page.getByTestId("fact-reload-error").waitFor();
    check("최신 불러오기 실패: 배너·초안 유지",
      await page.getByTestId("fact-conflict").isVisible() && await page.getByText("음료Z ICE 시럽은 10g 넣는다.", { exact: true }).count() === 0);
    await shot("09b-reload-failed-390");
    const callsBefore = state.factsCalls[1];
    const cardBefore = state.cardCalls[1];
    await page.getByRole("button", { name: "최신 내용 불러오기(고친 내용은 사라져요)" }).click();
    await page.getByText("음료Z ICE 시럽은 10g 넣는다.", { exact: true }).waitFor();
    check("최신 내용 불러오기: 카드 상세도 다시 읽음", await (async () => { for (let k = 0; k < 20 && !(state.cardCalls[1] > cardBefore); k++) await sleep(100); return state.cardCalls[1] > cardBefore; })());
    check("최신 내용 불러오기: 다시 읽고 편집을 새로 시작", state.factsCalls[1] > callsBefore
      && await page.getByTestId("fact-conflict").count() === 0 && (await tiles()).includes("음료Z ICE 시럽은 10g 넣는다."));
    await leaveEdit();
    await page.getByRole("button", { name: "수정하기", exact: true }).waitFor();

    // ── 마지막 줄 빼기 → 지우기 시트 → /exclude (카드 4)
    await page.goto(`${BASE}/owner/cards/4`);
    await panel().waitFor();
    await page.getByRole("button", { name: "수정하기", exact: true }).click();
    await page.locator("[data-tile]").first().click();
    await page.getByRole("dialog", { name: "이 줄 고치기" }).getByRole("button", { name: "이 줄 빼기", exact: true }).click();
    const last = page.getByRole("dialog");
    await last.getByText("사실이 하나도 남지 않아요. 이 카드를 지울까요?", { exact: true }).waitFor();
    await shot("10-last-fact-390");
    await last.getByRole("button", { name: "카드 지우기" }).click();
    // 화면 개선 계획 3: 삭제한 카드는 안내만 보이고, 되돌리기는 5초 스낵바로만
    await page.getByText("삭제한 카드예요", { exact: true }).waitFor();
    await page.getByRole("status").getByText("삭제했어요", { exact: true }).waitFor();
    check("마지막 줄 빼기 → /exclude 호출(빈 카드 저장 없음)", state.excludeCalls.includes(4) && !state.saveBodies.some((b) => b.blocks.length === 0));
    await shot("11-excluded-390");

    // ── 기존 절차에 단계 넣기 (카드 12): 추가 → 블록 끝 줄 → 위로 두 번 → 셋째 줄. 사실의 단계 번호는 분석 그대로
    await page.goto(`${BASE}/owner/cards/12`);
    await panel().waitFor();
    await page.getByRole("button", { name: "수정하기", exact: true }).click();
    await page.getByRole("button", { name: "+ 사실 추가", exact: true }).click();
    const addStep = page.getByRole("dialog");
    await addStep.waitFor();
    await addStep.getByLabel("넣을 내용").fill("마지막에 합성음료A 시럽을 넣는다.");
    await addStep.getByRole("button", { name: "분석하기", exact: true }).click();
    await addStep.getByTestId("parse-proposals").waitFor();
    await addStep.getByRole("button", { name: /^카드에 넣기/ }).click();
    await addStep.waitFor({ state: "detached" });
    check("새 줄은 처음에 블록 끝", (await tiles()).at(-1) === "합성음료A 시럽을 넣는다.");
    await press("합성음료A 시럽을 넣는다.", "ArrowUp");
    await press("합성음료A 시럽을 넣는다.", "ArrowUp");
    check("위로 두 번: 셋째 줄", JSON.stringify(await tiles()) === JSON.stringify([
      "합성음료A 컵을 꺼낸다.", "합성음료A 얼음을 담는다.", "합성음료A 시럽을 넣는다.", "합성음료A 물을 붓는다.", "합성음료A 뚜껑을 닫는다.",
    ]));
    for (const [w, h] of [[390, 844], [360, 800]]) {
      await page.setViewportSize({ width: w, height: h });
      check(`단계 넣기 ${w}px 가로 넘침 없음`, await noOverflow());
      await shot(`17-step-insert-${w}`);
    }
    await page.setViewportSize({ width: 390, height: 844 });
    const before = state.saveBodies.length;
    await page.getByRole("button", { name: "수정 완료", exact: true }).click();
    await page.getByRole("button", { name: "수정 완료", exact: true }).waitFor({ state: "detached" });
    const insertBody = state.saveBodies[before];
    const steps = insertBody.blocks.find((b) => b.kind === "STEPS");
    check("요청: 기존 단계 KEEP(번호 그대로), 새 단계 ADD",
      JSON.stringify(steps.items.map((i) => [i.op, i.fact_revision_id ?? i.fact.sentence])) === JSON.stringify([
        ["KEEP", 1201], ["KEEP", 1202], ["KEEP", 1203], ["KEEP", 1204], ["ADD", "합성음료A 시럽을 넣는다."],
      ]) && insertBody.deleted_fact_revision_ids.length === 0);
    const added = steps.items.find((i) => i.op === "ADD");
    check("요청: 줄 순서는 사장님이 옮긴 대로, 새 줄은 새 사실을 인용",
      steps.lines.length === 5 && steps.lines[2].client_refs[0] === added.client_ref
      && JSON.stringify(steps.lines.map((l) => l.fact_revision_ids[0] ?? null)) === JSON.stringify([1201, 1202, null, 1203, 1204]));

    // ── RAW 블록 섞임: 고치기 없음 + 이유 안내 (카드 9)
    await page.goto(`${BASE}/owner/cards/9`);
    await panel().waitFor();
    check("RAW 섞임: 안내 문구·고치기 없음",
      await text("이 카드에는 사실로 나뉘지 않은 내용이 섞여 있어 사실 단위로 고칠 수 없어요.").isVisible()
      && await page.getByRole("button", { name: "수정하기", exact: true }).count() === 0);
    await shot("15-raw-mixed-390");

    // ── 사실 목록 404: 볼 수 없어요 (다시 시도 없음) (카드 11)
    await page.goto(`${BASE}/owner/cards/11`);
    await text("이 카드를 볼 수 없어요").waitFor();
    check("사실 목록 404 는 볼 수 없어요·다시 시도 없음", await page.getByRole("button", { name: "다시 시도", exact: true }).count() === 0);
    await shot("16-facts-404-390");

    // ── 사실 카드가 아닌 카드는 읽기 전용 (카드 2)
    await page.goto(`${BASE}/owner/cards/2`);
    await text("합성 옛 카드 첫 줄").waitFor();
    check("레거시 카드: 사실 목록 없음·사실 API 호출 없음", await page.getByTestId("fact-panel").count() === 0 && !state.factsCalls[2]);
    check("레거시 카드: 고치기 버튼·자유 글 입력칸 없음(읽기만)",
      await page.getByRole("button", { name: "수정하기", exact: true }).count() === 0
      && await page.locator("textarea").count() === 0
      && await page.getByText("내용 · 한 줄에 하나씩", { exact: true }).count() === 0);
    await shot("12-legacy-readonly-390");

    // ── 대상 정리 바뀜 읽기 전용 (카드 7)
    await page.goto(`${BASE}/owner/cards/7`);
    await panel().waitFor();
    check("entity_problem: 안내 문구·고치기 없음",
      await text("메뉴 정리가 바뀌어 이 카드에서 고칠 수 없어요.").isVisible() && await page.getByRole("button", { name: "수정하기", exact: true }).count() === 0);
    await page.setViewportSize({ width: 360, height: 800 });
    check("읽기 전용 360px 가로 넘침 없음", await noOverflow());
    await shot("14-readonly-entity-360");

    check("합성 fixture 밖 경로 호출 없음", unknown.length === 0);
    check("브라우저 런타임 예외 없음", errors.length === 0);
    fs.writeFileSync(path.join(OUT, "result.json"), JSON.stringify({ fixture: "synthetic API browser walkthrough (no real API/DB/model)", passed }, null, 2));
    console.log(`Verified ${passed.length} W3b UI checks`);
  } finally {
    if (unknown.length) console.error("unknown:", unknown);
    if (errors.length) console.error("page errors:", errors);
    await browser.close();
  }
})().catch((err) => { console.error(err); process.exitCode = 1; });
