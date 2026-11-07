// 한 번 호출 추출 S9·S10 — 업로드 결과 화면의 "정리하지 못한 부분" 안내 실제 브라우저 검사.
// API 는 Playwright 가 가로채는 **합성 fixture** 다. 실제 FastAPI·DB·모델을 부르지 않는다(지출 0).
//
// 실행:
//   pnpm --dir web build && pnpm --dir web exec next start -p 3014
//   NODE_PATH=<playwright 가 있는 node_modules> node api/scripts/verify_single_call_partial_ui.cjs
// 화면 사진은 SC_UI_SHOTS(기본 api/tmp/single-call-partial-ui) 에 남는다.
const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const BASE = process.env.SC_UI_BASE || "http://127.0.0.1:3014";
const OUT = process.env.SC_UI_SHOTS || path.resolve(__dirname, "../tmp/single-call-partial-ui");

const CORS = { "access-control-allow-origin": BASE, "access-control-allow-credentials": "true", "access-control-allow-headers": "authorization,content-type,idempotency-key", "access-control-allow-methods": "GET,POST,PUT,PATCH,DELETE,OPTIONS" };
const json = (route, status, payload) =>
  route.fulfill({ status, contentType: "application/json", headers: CORS, body: JSON.stringify(payload) });
const apiError = (route, status, code, message) =>
  json(route, status, { error: { code, message, retryable: false, details: {} } });

const MSG = "자료의 일부를 정리하지 못했어요. 정리된 내용은 반영했어요.";
const range = (from_line, to_line, extra = {}) => ({ from_line, to_line, reason: "TRUNCATED", first_line: "5. 첫 샷 2잔은 버리고", attempts: 3, owner_retry_used: false, ...extra });
const partial = (source_id, filename, ranges) => ({ source_id, filename, status: "PARTIAL", card_count: 1, error: { code: "UNPROCESSED_LINES", message: MSG }, source_availability: "AVAILABLE", unprocessed_ranges: ranges });
const done = (source_id, filename) => ({ source_id, filename, status: "SUCCEEDED", card_count: 1, error: null, source_availability: "AVAILABLE", unprocessed_ranges: [] });

const job = (job_id, status, sources) => ({
  job_id, title: "합성 작업", status, category_version: 1,
  counts: { sources: sources.length, succeeded: sources.filter((s) => s.status === "SUCCEEDED").length, failed: 0, partial: sources.filter((s) => s.status === "PARTIAL").length, cards: sources.reduce((n, s) => n + s.card_count, 0) },
  sources, review_destination: `/owner/cards/review?job_id=${job_id}`,
});

const state = {
  posts: [],
  jobs: {
    // 매뉴얼 PDF 한 부분(31~67줄)이 끊겼다. 다른 자료는 성공
    41: job(41, "PARTIAL", [partial(401, "오픈 매뉴얼.pdf", [range(31, 67)]), done(402, "레시피.docx")]),
    // 사진(줄 번호 없음) — 다시 시도를 이미 썼다
    42: job(42, "PARTIAL", [partial(421, "벽 공지.jpg", [range(0, 0, { reason: "EMPTY", first_line: "", owner_retry_used: true })])]),
  },
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
  m = p.match(/^\/ingest\/jobs\/(\d+)\/retry$/);
  if (m && method === "POST") {
    const jobId = Number(m[1]);
    state.posts.push(p);
    const j = state.jobs[jobId];
    // 서버처럼 PARTIAL 자료를 QUEUED 로. 몇 번 조회 뒤 끝난다 — 이번엔 끝내 일부가 남는다(다시 시도 표시)
    j.status = "QUEUED";
    j.sources = j.sources.map((s) => (s.status === "PARTIAL" ? { ...s, status: "QUEUED", error: null } : s));
    state.finishAfter = { jobId, polls: 1 };
    return json(route, 202, { job_id: jobId, status: "QUEUED" });
  }
  if (p === "/cards" && method === "GET") {
    const jobId = Number(url.searchParams.get("job_id"));
    return json(route, 200, { items: [{ card_id: jobId * 10, review_status: "APPROVED", title: "합성 카드 오픈 절차", content: "머신 예열 15분", category: { category_id: 1, name: "오픈" }, assignment_type: "AUTOMATIC", source: null, job_id: jobId, has_evidence: true, needs_review_reason: null, updated_at: "2026-11-07T00:00:00Z" }], next_cursor: null, total: 1 });
  }
  return apiError(route, 404, "NOT_FOUND", `합성 fixture 에 없는 경로: ${method} ${p}`);
}

function advance() {
  const f = state.finishAfter;
  if (!f) return;
  if (f.polls-- > 0) return;
  const j = state.jobs[f.jobId];
  // 다시 시도로 31~50줄은 정리했고 51~67줄이 남았다 — owner_retry_used=true
  j.sources = j.sources.map((s) => (s.source_id === 401
    ? partial(401, s.filename, [range(51, 67, { first_line: "7. 09:00 오픈", owner_retry_used: true })])
    : s));
  j.status = "PARTIAL";
  state.finishAfter = null;
}

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  const errors = [];
  const unknown = [];
  const check = (name, value) => { assert.ok(value, name); console.log("PASS SC-UI", name); };
  try {
    for (const width of [390, 360]) {
      state.posts = [];
      state.jobs[41] = job(41, "PARTIAL", [partial(401, "오픈 매뉴얼.pdf", [range(31, 67)]), done(402, "레시피.docx")]);
      const ctx = await browser.newContext({ viewport: { width, height: 844 } });
      await ctx.route(/^http:\/\/(localhost|127\.0\.0\.1):8000\//, async (route) => {
        const before = route.request().url();
        if (/\/ingest\/jobs\/\d+$/.test(new URL(before).pathname)) advance();
        await handle(route).catch((e) => { unknown.push(`${before}: ${e.message}`); return route.abort("failed"); });
      });
      const page = await ctx.newPage();
      page.on("pageerror", (e) => errors.push(e.message));
      const shot = async (name) => { await page.waitForTimeout(300); await page.screenshot({ path: path.join(OUT, `${width}-${name}.png`), fullPage: true }); };
      const panel = page.getByTestId("unprocessed-ranges");
      const retry = panel.getByRole("button", { name: "다시 시도" });
      const write = panel.getByRole("link", { name: "직접 적기" });

      // 1. 부분 실패 — 위치·사유와 [다시 시도]·[직접 적기]
      await page.goto(`${BASE}/owner/jobs/41`, { waitUntil: "networkidle" });
      await page.getByRole("heading", { name: "이렇게 나눴어요" }).waitFor({ timeout: 8000 });
      const text = await panel.innerText();
      check(`${width} 정리하지 못한 부분 안내가 보인다(위치·첫 줄·사유·시도 수)`,
        text.includes("오픈 매뉴얼.pdf") && text.includes("31~67줄") && text.includes("5. 첫 샷 2잔은 버리고")
        && text.includes("정리하다가 끊겼어요") && text.includes("3번 시도"));
      check(`${width} 성공한 자료는 안내에 없다`, !text.includes("레시피.docx"));
      check(`${width} [다시 시도]·[직접 적기] 둘 다`, (await retry.count()) === 1 && (await write.count()) === 1);
      check(`${width} 일반 '일부 완료' 경고는 대신 보이지 않는다`, (await page.getByText("실패한 자료만 다시 시도할 수 있어요").count()) === 0);
      check(`${width} 정리된 카드는 그대로 보인다`, await page.getByText("합성 카드 오픈 절차").isVisible());
      check(`${width} 가로 넘침 없음`, await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth));
      await shot("1-partial");

      // 2. [다시 시도] → 처리 중 → 끝내 일부가 남으면 [다시 시도]가 사라지고 [직접 적기]만
      await retry.click();
      await page.getByRole("heading", { name: "정리하고 있어요" }).waitFor({ timeout: 8000 });
      check(`${width} 다시 시도는 작업 재시도 경로를 한 번 부른다`, JSON.stringify(state.posts) === JSON.stringify(["/ingest/jobs/41/retry"]));
      await shot("2-processing");
      await page.getByRole("heading", { name: "이렇게 나눴어요" }).waitFor({ timeout: 10000 });
      const after = await panel.innerText();
      check(`${width} 남은 범위로 안내가 바뀐다(51~67줄)`, after.includes("51~67줄") && !after.includes("31~67줄"));
      check(`${width} 다시 시도를 쓴 뒤에는 [다시 시도]가 없고 [직접 적기]만`, (await retry.count()) === 0 && (await write.count()) === 1);
      await shot("3-after-retry");

      // 3. 새로고침해도 버튼이 되살아나지 않는다(서버 상태가 정본)
      await page.reload({ waitUntil: "networkidle" });
      await page.getByRole("heading", { name: "이렇게 나눴어요" }).waitFor({ timeout: 8000 });
      check(`${width} 새로고침 뒤에도 [다시 시도] 없음·[직접 적기] 있음`, (await retry.count()) === 0 && (await write.count()) === 1);

      // 4. 사진(줄 번호 없음)·이미 다시 시도를 쓴 범위
      await page.goto(`${BASE}/owner/jobs/42`, { waitUntil: "networkidle" });
      await panel.waitFor({ timeout: 8000 });
      const photo = await panel.innerText();
      check(`${width} 사진은 '이 자료' 로 안내·사유 '내용을 읽지 못했어요'`, photo.includes("이 자료를 정리하지 못했어요") && photo.includes("내용을 읽지 못했어요"));
      check(`${width} 다시 시도를 쓴 사진 범위는 [직접 적기]만`, (await retry.count()) === 0 && (await write.count()) === 1);
      await shot("4-photo");

      // 5. [직접 적기] 는 자료 넣기 화면으로
      check(`${width} [직접 적기] 는 /owner/add`, (await write.getAttribute("href")) === "/owner/add");
      await ctx.close();
    }
    check("페이지 오류 없음", errors.length === 0);
    check("fixture 밖 요청 없음", unknown.length === 0);
    console.log("PASS SC-UI all");
  } finally {
    await browser.close();
  }
})().catch((e) => { console.error(e); process.exit(1); });
