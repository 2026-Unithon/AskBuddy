// Phase B 후속 1 — 작업 상세의 자료별 "그래도 추출하기" 실제 브라우저 상태 검사.
// API 는 Playwright 가 가로채는 **합성 fixture** 다. 실제 FastAPI·DB·모델을 부르지 않는다(지출 0).
//
// 실행:
//   pnpm --dir web build && pnpm --dir web exec next start -p 3014
//   NODE_PATH=<playwright 가 있는 node_modules> node api/scripts/verify_wb_extract_anyway_ui.cjs
// 화면 사진은 WB_UI_SHOTS(기본 api/tmp/wb-extract-anyway-ui) 에 남는다.
const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const BASE = process.env.WB_UI_BASE || "http://127.0.0.1:3014";
const OUT = process.env.WB_UI_SHOTS || path.resolve(__dirname, "../tmp/wb-extract-anyway-ui");

const CORS = { "access-control-allow-origin": BASE, "access-control-allow-credentials": "true", "access-control-allow-headers": "authorization,content-type,idempotency-key", "access-control-allow-methods": "GET,POST,PUT,PATCH,DELETE,OPTIONS" };
const json = (route, status, payload) =>
  route.fulfill({ status, contentType: "application/json", headers: CORS, body: JSON.stringify(payload) });
const apiError = (route, status, code, message) =>
  json(route, status, { error: { code, message, retryable: false, details: {} } });

const NONE_MSG = "업무 자료가 아니라고 판단해 추출하지 않았어요.";
const none = (source_id, filename, extra = {}) => ({ source_id, filename, status: "NO_RESULT", card_count: 0, error: { code: "INTAKE_NONE", message: NONE_MSG }, source_availability: "AVAILABLE", ...extra });
const done = (source_id, filename) => ({ source_id, filename, status: "SUCCEEDED", card_count: 1, error: null, source_availability: "AVAILABLE" });

const job = (job_id, status, sources) => ({
  job_id, title: "합성 작업", status, category_version: 1,
  counts: { sources: sources.length, succeeded: sources.filter((s) => s.status === "SUCCEEDED").length, failed: sources.filter((s) => s.status === "FAILED").length, partial: 0, cards: sources.reduce((n, s) => n + s.card_count, 0) },
  sources, review_destination: `/owner/cards/review?job_id=${job_id}`,
});

const state = {
  posts: [],
  jobs: {
    // 섞인 작업: 카드 나온 파일 + 무관 파일 + 분류 때문이 아닌 무결과 + 지워진 무관 파일
    31: job(31, "SUCCEEDED", [done(301, "recipe.docx"), none(302, "chat.docx"),
      { source_id: 303, filename: "empty.docx", status: "NO_RESULT", card_count: 0, error: { code: "NO_RESULT", message: "추출된 업무 카드가 없습니다." }, source_availability: "AVAILABLE" },
      none(304, "gone.docx", { source_availability: "DELETED" })]),
    // 작업 전체 무결과: 무관 파일 둘
    32: job(32, "NO_RESULT", [none(321, "memo-a.docx"), none(322, "memo-b.docx")]),
    // 처리 중: 앞서 끝난 무관 파일이 있어도 버튼이 없다
    34: job(34, "EXTRACTING", [none(341, "early.docx"), { source_id: 342, filename: "later.docx", status: "EXTRACTING", card_count: 0, error: null, source_availability: "AVAILABLE" }]),
  },
  fail322: true,
};

async function handle(route) {
  const req = route.request();
  const url = new URL(req.url());
  const p = url.pathname;
  const method = req.method();
  if (method === "OPTIONS") return route.fulfill({ status: 204, headers: CORS });
  if (p === "/auth/refresh") return json(route, 200, { token: "synthetic-ui-only", user: { user_id: 1, role: "OWNER", store_id: 1 } });
  if (p === "/app/bootstrap") {
    return json(route, 200, { user: { user_id: 1, role: "OWNER", name: "합성 점주" },
      store: { store_id: 1, store_name: "합성 UI 매장", guide_completed: true, category_version: 1 },
      badges: { waiting_questions: 0, pending_cards: 0 }, default_destination: "/owner" });
  }
  if (p === "/ingest/jobs") return json(route, 200, { items: [], next_cursor: null, total: 0 });
  let m = p.match(/^\/ingest\/jobs\/(\d+)$/);
  if (m && method === "GET") {
    const j = state.jobs[m[1]];
    return j ? json(route, 200, j) : apiError(route, 404, "INGEST_JOB_NOT_FOUND", "자료 작업을 찾을 수 없습니다.");
  }
  m = p.match(/^\/ingest\/jobs\/(\d+)\/sources\/(\d+)\/extract-anyway$/);
  if (m && method === "POST") {
    const [jobId, sourceId] = [Number(m[1]), Number(m[2])];
    state.posts.push(p);
    if (sourceId === 322 && state.fail322) {
      state.fail322 = false;
      return apiError(route, 409, "INGEST_JOB_IN_PROGRESS", "자료를 처리하고 있어요. 끝난 뒤 다시 시도해 주세요.");
    }
    const j = state.jobs[jobId];
    // 서버처럼 그 자료만 QUEUED 로, 작업은 QUEUED 로 되돌린다. 다음 조회 몇 번 뒤 끝난다
    j.status = "QUEUED";
    j.sources = j.sources.map((s) => (s.source_id === sourceId ? { ...s, status: "QUEUED", error: null } : s));
    state.finishAfter = { jobId, sourceId, polls: 1 };
    return json(route, 202, { job_id: jobId, status: "QUEUED", category_version: 1, source_count: 1 });
  }
  if (p === "/cards" && method === "GET") {
    const jobId = Number(url.searchParams.get("job_id"));
    return json(route, 200, { items: [{ card_id: jobId * 10, review_status: "APPROVED", title: "합성 카드 음료Z", content: "샷 2", category: { category_id: 1, name: "레시피" }, assignment_type: "AUTOMATIC", source: null, job_id: jobId, has_evidence: true, needs_review_reason: null, updated_at: "2026-10-11T00:00:00Z" }], next_cursor: null, total: 1 });
  }
  return apiError(route, 404, "NOT_FOUND", `합성 fixture 에 없는 경로: ${method} ${p}`);
}

// 조회가 한 번 지나면 다시 처리한 자료를 끝낸다(폴링이 따라가는지 본다)
function advance() {
  const f = state.finishAfter;
  if (!f) return;
  if (f.polls-- > 0) return;
  const j = state.jobs[f.jobId];
  j.sources = j.sources.map((s) => (s.source_id === f.sourceId ? { ...s, status: "SUCCEEDED", card_count: 1, error: null } : s));
  j.status = "SUCCEEDED";
  j.counts.cards = j.sources.reduce((n, s) => n + s.card_count, 0);
  state.finishAfter = null;
}

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  const errors = [];
  const unknown = [];
  const check = (name, value) => { assert.ok(value, name); console.log("PASS WB-UI", name); };
  try {
    const ctx = await browser.newContext({ viewport: { width: 390, height: 844 } });
    await ctx.route(/^http:\/\/(localhost|127\.0\.0\.1):8000\//, async (route) => {
      const before = route.request().url();
      if (/\/ingest\/jobs\/\d+$/.test(new URL(before).pathname)) advance();
      await handle(route).catch((e) => { unknown.push(`${before}: ${e.message}`); return route.abort("failed"); });
    });
    const page = await ctx.newPage();
    page.on("pageerror", (e) => errors.push(e.message));
    const shot = async (name) => { await page.waitForTimeout(300); await page.screenshot({ path: path.join(OUT, `${name}.png`), fullPage: true }); };
    const anyway = page.getByRole("button", { name: "그래도 추출하기" });
    const row = (name) => page.locator("li", { hasText: name });

    // 1. 섞인 작업(SUCCEEDED): 무관 자료 행에만 버튼
    await page.goto(`${BASE}/owner/jobs/31`, { waitUntil: "networkidle" });
    await page.getByRole("heading", { name: "이렇게 나눴어요" }).waitFor({ timeout: 8000 });
    check("SUCCEEDED 섞인 작업에 추출하지 않은 자료 구역이 보인다", await page.getByText("추출하지 않은 자료 · 1").isVisible());
    check("버튼은 하나 — 무관 자료(chat.docx) 행에만", (await anyway.count()) === 1 && (await row("chat.docx").getByRole("button", { name: "그래도 추출하기" }).count()) === 1);
    check("카드 나온 자료·분류 아닌 무결과·지워진 무관 자료에는 버튼이 없다",
      (await row("recipe.docx").count()) === 0 && (await row("empty.docx").count()) === 0 && (await row("gone.docx").count()) === 0);
    check("무관 자료 행에 판정 메시지가 보인다", (await row("chat.docx").innerText()).includes(NONE_MSG));
    await shot("1-succeeded-mixed");

    await row("chat.docx").getByRole("button", { name: "그래도 추출하기" }).click();
    await page.getByRole("heading", { name: "정리하고 있어요" }).waitFor({ timeout: 8000 });
    check("누르면 그 자료 경로만 호출한다", JSON.stringify(state.posts) === JSON.stringify(["/ingest/jobs/31/sources/302/extract-anyway"]));
    await shot("2-processing");
    await page.getByRole("heading", { name: "이렇게 나눴어요" }).waitFor({ timeout: 10000 });
    check("처리가 끝나면 폴링이 따라와 버튼이 사라진다", (await anyway.count()) === 0);
    await shot("3-after");

    // 2. 작업 전체 무결과: 자료마다 버튼, 작업 단위 버튼은 없다
    await page.goto(`${BASE}/owner/jobs/32`, { waitUntil: "networkidle" });
    await page.getByRole("heading", { name: "찾은 내용이 없어요" }).waitFor({ timeout: 8000 });
    check("NO_RESULT 작업은 무관 자료 행마다 버튼(2개)·footer 의 작업 단위 버튼 없음",
      (await anyway.count()) === 2 && (await row("memo-a.docx").getByRole("button", { name: "그래도 추출하기" }).count()) === 1
      && (await row("memo-b.docx").getByRole("button", { name: "그래도 추출하기" }).count()) === 1);
    await row("memo-b.docx").getByRole("button", { name: "그래도 추출하기" }).click();
    await row("memo-b.docx").getByRole("alert").waitFor({ timeout: 8000 });
    check("실패하면 그 행에만 오류가 남는다", (await row("memo-b.docx").getByRole("alert").innerText()).includes("자료를 처리하고 있어요")
      && (await row("memo-a.docx").getByRole("alert").count()) === 0);
    check("실패한 호출도 그 자료 경로였다", state.posts.at(-1) === "/ingest/jobs/32/sources/322/extract-anyway");
    await shot("4-no-result-error");
    await row("memo-b.docx").getByRole("alert").getByRole("button", { name: "다시 시도" }).click();
    await page.getByRole("heading", { name: "정리하고 있어요" }).waitFor({ timeout: 8000 });
    check("다시 시도는 같은 자료만 부른다(memo-a 는 한 번도 안 불림)",
      state.posts.filter((p) => p.endsWith("/322/extract-anyway")).length === 2 && !state.posts.some((p) => p.includes("/321/")));
    await shot("5-no-result-retried");

    // 3. 처리 중 작업: 앞서 끝난 무관 자료가 있어도 버튼이 없다
    await page.goto(`${BASE}/owner/jobs/34`, { waitUntil: "networkidle" });
    await page.getByRole("heading", { name: "정리하고 있어요" }).waitFor({ timeout: 8000 });
    check("처리 중에는 버튼이 없다", (await anyway.count()) === 0);
    await shot("6-in-progress");

    check("페이지 오류 없음", errors.length === 0);
    check("fixture 밖 요청 없음", unknown.length === 0);
    console.log("PASS WB-UI all");
  } finally {
    await browser.close();
  }
})().catch((e) => { console.error(e); process.exit(1); });
