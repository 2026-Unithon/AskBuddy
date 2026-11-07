// 사장 운영(오늘만 할 일·리포트·응대 매뉴얼) 브라우저 검증. 모든 API 응답은 합성 fixture 이며
// 실제 매장·DB 를 쓰지 않는다.
// 실행: next start -p 3012 후 NODE_PATH=<playwright 설치 경로> node api/scripts/verify_ui_owner_ops.cjs
const { chromium } = require("playwright");
const assert = require("node:assert/strict");

const BASE = process.env.OPS_UI_BASE || "http://127.0.0.1:3012";

function state(overrides = {}) {
  return {
    tasks: [],
    mine: [],
    calls: [],
    misses: [],
    failPolish: false,
    failDone: false,
    failReport: false,
    perStaffVisible: true,
    categories: ["오픈업무", "손님응대", "배달대응", "돌발상황", "기타"],
    ...overrides,
  };
}

function report(s, days) {
  return {
    first_date: days === 7 ? "2026-10-31" : "2026-10-08",
    last_date: "2026-11-06",
    days,
    questions: {
      questions: days === 7 ? 24 : 80, ai_answered: days === 7 ? 19 : 61, escalated: 5,
      owner_answered: 4, answer_minutes_median: 90, waiting_now: 1,
    },
    top_escalations: [{ question_id: 101, question_text: "디카페인 원두는 어디 있어요?", status: "WAITING", asked: 3 }],
    per_staff: s.perStaffVisible ? [{ member_id: 2, name: "박지호", questions: 14, escalated: 3 }] : null,
    checklist: { submissions: 12, complete: 10 },
    today_tasks: { tasks: 3, assigned: 5, done: 4 },
  };
}

async function open(browser, role, url, s, width = 390) {
  const ctx = await browser.newContext({ viewport: { width, height: 844 }, locale: "ko-KR" });
  // 화면 개선 계획 4a: 처음 한 번 뜨는 안내(코치마크)는 이 검사에서 본 것으로 둔다
  await ctx.addInitScript(() => { try { for (const k of ['owner-home', 'staff-home', 'dev']) localStorage.setItem(`askbuddy:coach:${k}`, 'done'); } catch {} });
  await ctx.addInitScript((role) => localStorage.setItem("askbuddy_state", JSON.stringify({
    v: 9, data: { token: "synthetic-ops-only", role, userId: role === "OWNER" ? 1 : 2, storeId: 1 },
  })), role);
  await ctx.route("http://localhost:8000/**", async (route) => {
    const req = route.request();
    const u = new URL(req.url());
    const p = u.pathname;
    const m = req.method();
    const cors = { "access-control-allow-origin": req.headers().origin ?? BASE, "access-control-allow-credentials": "true" };
    if (m === "OPTIONS") {
      return route.fulfill({ status: 204, headers: { ...cors, "access-control-allow-headers": "*", "access-control-allow-methods": "*" } });
    }
    const body = req.postData() ? req.postDataJSON() : null;
    const respond = (payload, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(payload), headers: cors });
    const fail = (status, code, message) => respond({ error: { message, code, retryable: false, details: {} } }, status);
    s.calls.push({ m, p: p + u.search, body });

    if (p === "/auth/refresh") return respond({ token: "synthetic-ops-only", user: { user_id: role === "OWNER" ? 1 : 2, role, store_id: 1 } });
    if (p === "/app/bootstrap") return respond({
      user: { user_id: role === "OWNER" ? 1 : 2, role, name: role === "OWNER" ? "김사장" : "박지호" },
      store: { store_id: 1, store_name: "합성 매장", guide_completed: true }, badges: {},
      default_destination: role === "OWNER" ? "/owner" : "/staff",
    });
    if (p === "/learn/v2/pending") return respond({ questions: [], next_after: null });
    if (p === "/checklist/status") return respond({ business_date: "2026-11-06", current_shift_id: null, shifts: [], scope_counts: { total: 0, done: 0 }, last_submission: null });
    if (p === "/checklist/today") return respond({
      business_date: "2026-11-06", previous_business_date: "2026-11-05", previous_submitted: true,
      scope: { all: true, shift_ids: [] }, current_shift_id: null, upcoming: false, shifts: [],
      scope_counts: { total: 0, done: 0 }, view: { total: 0, done: 0 }, groups: [], my_submission: null,
    });
    if (p === "/checklist/members") return respond({ items: [
      { member_id: 1, user_id: 1, role: "OWNER", name: "김사장", shift_ids: [] },
      { member_id: 2, user_id: 2, role: "STAFF", name: "박지호", shift_ids: [] },
      { member_id: 3, user_id: 3, role: "STAFF", name: "김민준", shift_ids: [] },
    ] });
    if (p === "/ingest/capabilities") return respond({ text: { enabled: true }, source_types: {} });
    if (p === "/categories") return respond({ version: 1, items: s.categories.map((name, i) => ({ category_id: i + 1, name, is_system: name === "기타", sort_order: i })), reclassification: null });

    if (p === "/today-tasks" && m === "GET") return respond({ business_date: "2026-11-06", items: s.tasks });
    if (p === "/today-tasks" && m === "POST") {
      const names = { 2: "박지호", 3: "김민준" };
      const task = { task_id: 11 + s.tasks.length, body: body.body ?? body.text, original_text: body.text, created_at: "2026-11-06T03:00:00Z",
        targets: body.member_ids.map((id) => ({ member_id: id, name: names[id], seen_at: null, done_at: null })) };
      s.tasks.unshift(task);
      return respond({ business_date: "2026-11-06", task }, 201);
    }
    if (p === "/today-tasks/polish") {
      if (s.failPolish) return fail(503, "POLISH_UNAVAILABLE", "문장을 다듬지 못했어요. 적은 그대로 보낼 수 있어요.");
      return respond({ body: "오늘 마감 후 쓰레기통을 가게 밖으로 내놓아 주세요." });
    }
    if (/^\/today-tasks\/\d+$/.test(p) && m === "DELETE") {
      s.tasks = s.tasks.filter((t) => t.task_id !== Number(p.split("/")[2]));
      return route.fulfill({ status: 204, headers: cors });
    }
    if (p === "/today-tasks/mine") return respond({ business_date: "2026-11-06", items: s.mine });
    if (p === "/today-tasks/seen") {
      s.mine = s.mine.map((t) => (body.task_ids.includes(t.task_id) ? { ...t, seen: true } : t));
      return respond({ updated: body.task_ids.length });
    }
    if (/^\/today-tasks\/\d+\/done$/.test(p)) {
      if (s.failDone) return fail(500, "SYNTHETIC_ERROR", "합성 저장 실패");
      const id = Number(p.split("/")[2]);
      s.mine = s.mine.map((t) => (t.task_id === id ? { ...t, done: body.done, seen: true } : t));
      return respond({ task_id: id, done: body.done });
    }
    if (p === "/report/summary") {
      if (s.failReport) { s.failReport = false; return fail(500, "SYNTHETIC_ERROR", "합성 리포트 실패"); }
      return respond(report(s, Number(u.searchParams.get("days"))));
    }
    s.misses.push(`${m} ${p}`);
    return fail(404, "NOT_FOUND", "합성 fixture 에 없는 경로");
  });
  const page = await ctx.newPage();
  await page.goto(BASE + url);
  await page.waitForLoadState("networkidle");
  return { ctx, page };
}

// 버튼 가운데 점을 실제로 누가 받는지 본다. 입력창·탭이 위에 덮이면 다른 요소가 나온다
const notCovered = (locator) => locator.evaluate((el) => {
  el.scrollIntoView({ block: "center" });
  const r = el.getBoundingClientRect();
  const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
  return Boolean(hit && (hit === el || el.contains(hit)));
});
const noHorizontalScroll = (page) => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth);
const calls = (s, m, p) => s.calls.filter((c) => c.m === m && c.p.startsWith(p));
async function until(fn, ms = 5000) {
  const end = Date.now() + ms;
  while (!fn()) {
    if (Date.now() > end) throw new Error("기다린 요청이 오지 않았다");
    await new Promise((r) => setTimeout(r, 50));
  }
}

const cases = [];
const test = (name, fn) => cases.push([name, fn]);

test("사장: 비어 있으면 안내, 다듬어서 박지호에게 보내면 목록에 '아직 안 봄'으로 뜬다", async (b) => {
  const s = state();
  const { page, ctx } = await open(b, "OWNER", "/owner", s);
  await page.getByText("오늘 따로 시킬 일이 있나요?").waitFor();
  await page.getByTestId("today-task-open").click();
  await page.getByTestId("today-task-text").fill("마감하고 쓰레기통 밖으로 내놔");
  // 대상을 안 고르면 보낼 수 없다
  assert.equal(await page.getByTestId("today-task-send").isDisabled(), true);
  await page.getByTestId("today-task-member").filter({ hasText: "박지호" }).click();
  await page.getByTestId("today-task-polish").click();
  await page.getByTestId("today-task-polished").waitFor();
  assert.equal(await page.getByTestId("today-task-polished").inputValue(), "오늘 마감 후 쓰레기통을 가게 밖으로 내놓아 주세요.");
  assert.equal(await notCovered(page.getByTestId("today-task-send")), true, "보내기 버튼이 입력창·탭에 가려진다");
  await page.getByTestId("today-task-send").click();
  await page.getByTestId("owner-today-task").first().waitFor();
  const sent = calls(s, "POST", "/today-tasks").find((c) => c.p === "/today-tasks").body;
  assert.deepEqual(sent, { text: "마감하고 쓰레기통 밖으로 내놔", body: "오늘 마감 후 쓰레기통을 가게 밖으로 내놓아 주세요.", member_ids: [2] });
  assert.ok(await page.getByText("박지호 아직 안 봄").isVisible());
  assert.ok(await page.getByText("1명 중 0명 완료").isVisible());
  await ctx.close();
});

test("사장: 다듬기가 실패해도 적은 그대로 '모두'에게 보낼 수 있다", async (b) => {
  const s = state({ failPolish: true });
  const { page, ctx } = await open(b, "OWNER", "/owner", s);
  await page.getByTestId("today-task-open").click();
  await page.getByTestId("today-task-text").fill("닭은 냉동실에 넣어 둬");
  await page.getByRole("button", { name: "모두" }).click();
  await page.getByTestId("today-task-polish").click();
  await page.getByText("문장을 다듬지 못했어요").waitFor();
  await page.getByTestId("today-task-send").click();
  await page.getByTestId("owner-today-task").first().waitFor();
  const sent = calls(s, "POST", "/today-tasks").find((c) => c.p === "/today-tasks").body;
  assert.deepEqual(sent, { text: "닭은 냉동실에 넣어 둬", member_ids: [2, 3] });
  assert.ok(await page.getByText("2명 중 0명 완료").isVisible());
  await ctx.close();
});

test("사장: 거두기는 한 번 더 확인한 뒤 지운다, 상태 칩은 완료/확인함으로 갈린다", async (b) => {
  const s = state({ tasks: [{ task_id: 11, body: "얼음 채워 주세요", original_text: "얼음", created_at: "2026-11-06T03:00:00Z",
    targets: [{ member_id: 2, name: "박지호", seen_at: "x", done_at: "y" }, { member_id: 3, name: "김민준", seen_at: "x", done_at: null }] }] });
  const { page, ctx } = await open(b, "OWNER", "/owner", s);
  assert.ok(await page.getByText("박지호 완료").isVisible());
  assert.ok(await page.getByText("김민준 확인함").isVisible());
  await page.getByRole("button", { name: "거두기" }).click();
  assert.equal(calls(s, "DELETE", "/today-tasks/").length, 0);
  await page.getByRole("button", { name: "거두기" }).click();
  await page.getByText("오늘 따로 시킬 일이 있나요?").waitFor();
  assert.equal(calls(s, "DELETE", "/today-tasks/11").length, 1);
  assert.equal(await noHorizontalScroll(page), true);
  await ctx.close();
});

test("알바: 맨 위에 보이고, 보이면 확인을 보내고, 눌러서 완료한다", async (b) => {
  const s = state({ mine: [{ task_id: 11, body: "오늘 마감 후 쓰레기통을 밖으로 내놓아 주세요.", created_at: "2026-11-06T03:00:00Z", seen: false, done: false }] });
  const { page, ctx } = await open(b, "STAFF", "/staff?task_id=11", s, 360);
  await page.getByTestId("today-only-tasks").waitFor();
  assert.ok(await page.getByText("사장님이 보낸 오늘만 할 일").isVisible());
  // 매일 체크리스트가 비어 있어도 사장 지시가 있으면 '할 일 없음'을 띄우지 않는다
  assert.equal(await page.getByText("아직 오늘 할 일이 없어요").count(), 0);
  await until(() => calls(s, "POST", "/today-tasks/seen").length > 0);
  assert.deepEqual(calls(s, "POST", "/today-tasks/seen")[0].body, { task_ids: [11] });
  await page.getByText("오늘 마감 후 쓰레기통을 밖으로 내놓아 주세요.").click();
  await until(() => s.mine[0].done === true);
  assert.deepEqual(calls(s, "PUT", "/today-tasks/11/done")[0].body, { done: true });
  assert.equal(s.mine[0].done, true);
  // 폴링으로 다시 불러와도 확인 요청을 또 보내지 않는다
  assert.equal(calls(s, "POST", "/today-tasks/seen").length, 1);
  assert.equal(await noHorizontalScroll(page), true);
  await ctx.close();
});

test("알바: 완료 저장이 실패하면 체크가 되돌아가고 오류가 남는다", async (b) => {
  const s = state({ failDone: true, mine: [{ task_id: 11, body: "얼음 채우기", created_at: "2026-11-06T03:00:00Z", seen: true, done: false }] });
  const { page, ctx } = await open(b, "STAFF", "/staff", s);
  await page.getByText("얼음 채우기").click();
  await page.getByText("합성 저장 실패").waitFor();
  await page.waitForLoadState("networkidle");
  assert.equal(calls(s, "PUT", "/today-tasks/11/done").length, 1);
  assert.equal(await page.locator('[aria-checked="true"], input:checked').count(), 0);
  assert.equal(calls(s, "POST", "/today-tasks/seen").length, 0);
  await ctx.close();
});

test("알바: 받은 지시가 없으면 구역을 그리지 않는다", async (b) => {
  const s = state();
  const { page, ctx } = await open(b, "STAFF", "/staff", s);
  assert.equal(await page.getByTestId("today-only-tasks").count(), 0);
  await page.getByText("아직 오늘 할 일이 없어요").waitFor();
  await ctx.close();
});

test("리포트: 건수와 걸린 시간, 30일 전환, 실패 뒤 다시 시도", async (b) => {
  const s = state({ failReport: true });
  const { page, ctx } = await open(b, "OWNER", "/owner/report", s, 360);
  await page.getByRole("button", { name: "다시 시도" }).click();
  await page.getByTestId("report-headline").waitFor();
  assert.equal(await page.getByTestId("report-headline").innerText(), "알바생 질문 24건 중 19건은 AI가 바로 답했어요");
  assert.ok(await page.getByText("1.5시간").isVisible());
  assert.ok(await page.getByText("3번 물어봄, 아직 답 안 함").isVisible());
  assert.ok(await page.getByText("질문 14건, 사장님께 넘어감 3건").isVisible());
  assert.ok(await page.getByText("3건 보냄, 5명 중 4명 완료").isVisible());
  await page.getByRole("button", { name: "최근 30일" }).click();
  await page.getByText("알바생 질문 80건 중 61건은 AI가 바로 답했어요").waitFor();
  assert.ok(calls(s, "GET", "/report/summary?days=30").length >= 1);
  const text = await page.locator("main, body").first().innerText();
  assert.equal(/\d+%/.test(text), false, "퍼센트 표기 금지");
  assert.equal(await noHorizontalScroll(page), true);
  await ctx.close();
});

test("리포트: 알바생 기록 보기를 끈 매장은 사람별 숫자를 안 보인다", async (b) => {
  const s = state({ perStaffVisible: false });
  const { page, ctx } = await open(b, "OWNER", "/owner/report", s);
  await page.getByText("알바생 기록 보기를 꺼 두셔서").waitFor();
  assert.equal(await page.getByText("박지호").count(), 0);
  await ctx.close();
});

test("응대 매뉴얼: 상황을 고르면 입력창에 상황이 들어가고, 카테고리가 없으면 알려준다", async (b) => {
  const s = state({ categories: ["오픈업무", "기타"] });
  const { page, ctx } = await open(b, "OWNER", "/owner/guide/service", s);
  await page.getByText("손님응대, 배달대응, 돌발상황이(가) 없어서").waitFor();
  await page.getByRole("button", { name: /환불을 해 달라고 하면/ }).click();
  const box = page.getByRole("textbox", { name: "새로 알려줄 것" });
  await box.waitFor();
  assert.equal(await box.inputValue(), "[손님응대] 환불을 해 달라고 하면: ");
  await page.getByRole("button", { name: /배달 기사님이 늦거나 안 오면/ }).click();
  assert.equal(await box.inputValue(), "[배달대응] 배달 기사님이 늦거나 안 오면: ");
  assert.equal(await noHorizontalScroll(page), true);
  await ctx.close();
});

test("사장 첫 화면: 리포트와 응대 매뉴얼로 가는 길이 있다", async (b) => {
  const s = state();
  const { page, ctx } = await open(b, "OWNER", "/owner", s, 360);
  await page.getByRole("link", { name: /매장 리포트/ }).click();
  await page.waitForURL((u) => u.pathname === "/owner/report");
  await page.goto(BASE + "/owner");
  await page.getByRole("link", { name: /응대 매뉴얼 만들기/ }).click();
  await page.waitForURL((u) => u.pathname === "/owner/guide/service");
  await ctx.close();
});

(async () => {
  const browser = await chromium.launch({ headless: true });
  let failed = 0;
  for (const [name, fn] of cases) {
    try {
      await fn(browser);
      console.log("PASS", name);
    } catch (error) {
      failed++;
      console.log("FAIL", name, "\n  ", error.message.split("\n")[0]);
    }
  }
  await browser.close();
  console.log(`${cases.length - failed}/${cases.length} passed`);
  process.exit(failed ? 1 : 0);
})();
