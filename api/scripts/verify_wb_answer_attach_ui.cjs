// Phase B Task 13 — 점주 답변 화면 첨부 UI 실제 브라우저 상태 검사.
// API·스토리지는 Playwright 가 가로채는 **합성 fixture** 다. 실제 FastAPI·DB·모델을 부르지 않는다(지출 0).
//
// 실행:
//   pnpm --dir web build && pnpm --dir web exec next start -p 3012
//   NODE_PATH=<playwright 가 있는 node_modules> node api/scripts/verify_wb_answer_attach_ui.cjs
// 화면 사진은 WB_UI_SHOTS(기본 api/tmp/wb-answer-ui) 에 남는다.
const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const BASE = process.env.WB_UI_BASE || "http://127.0.0.1:3012";
const OUT = process.env.WB_UI_SHOTS || path.resolve(__dirname, "../tmp/wb-answer-ui");

const CORS = { "access-control-allow-origin": BASE, "access-control-allow-credentials": "true", "access-control-allow-headers": "authorization,content-type,idempotency-key", "access-control-allow-methods": "GET,POST,PUT,PATCH,DELETE,OPTIONS" };
const json = (route, status, payload) =>
  route.fulfill({ status, contentType: "application/json", headers: CORS, body: JSON.stringify(payload) });
const apiError = (route, status, code, message) =>
  json(route, status, { error: { code, message, retryable: false, details: {} } });

const state = {
  registerBodies: [],
  attachBodies: [],
  answerBodies: [],
  registerCount: {},
  releaseSlow: null, // slow.pdf 의 자료 등록 응답을 쥐고 있다가 놓는다
  nameByUrl: {},
  nameBySource: {},
  attachCount: {},
  nextSource: 100,
};

async function handle(route) {
  const req = route.request();
  const url = new URL(req.url());
  const p = url.pathname;
  const method = req.method();
  if (method === "OPTIONS") return route.fulfill({ status: 204, headers: CORS });
  if (p.startsWith("/__storage/")) return route.fulfill({ status: 200, headers: CORS, body: "" });
  if (p === "/auth/refresh") return json(route, 200, { token: "synthetic-ui-only", user: { user_id: 1, role: "OWNER", store_id: 1 } });
  if (p === "/app/bootstrap") {
    return json(route, 200, { user: { user_id: 1, role: "OWNER", name: "합성 점주" },
      store: { store_id: 1, store_name: "합성 UI 매장", guide_completed: true, category_version: 1 },
      badges: { waiting_questions: 1, pending_cards: 0 }, default_destination: "/owner" });
  }
  if (p === "/ingest/capabilities") {
    return json(route, 200, { SCAN: { extensions: ["pdf", "jpg", "png"], max_bytes: 1024 * 1024 }, VOICE: { extensions: ["m4a"], max_bytes: 1024 * 1024 } });
  }
  if (p === "/ingest/jobs") return json(route, 200, { items: [], next_cursor: null, total: 0 });
  if (p === "/learn/pending") {
    return json(route, 200, { store_id: 1, items: [{ question_id: 7, question_text: "합성 질문: 우유는 어디에 두나요?", miss_reason: "NO_CARD", status: "WAITING", member_id: 2, asked_by: "합성직원", created_at: "2026-10-10T01:00:00Z" }] });
  }
  if (p === "/learn/questions") return json(route, 200, { store_id: 1, items: [] });
  if (p === "/ingest/upload-url") {
    const body = JSON.parse(req.postData() || "{}");
    const file_url = `sources/1/scan/${state.nextSource}-${body.filename}`;
    state.nameByUrl[file_url] = body.filename;
    return json(route, 200, { upload_url: `http://127.0.0.1:8000/__storage/${encodeURIComponent(body.filename)}`, file_url });
  }
  if (p === "/ingest/sources" && method === "POST") {
    const body = JSON.parse(req.postData() || "{}");
    state.registerBodies.push(body);
    const name = body.title;
    state.registerCount[name] = (state.registerCount[name] || 0) + 1;
    if (name === "slow.pdf") await new Promise((resolve) => { state.releaseSlow = resolve; });
    if (name === "fail.pdf" && state.registerCount[name] === 1) return apiError(route, 500, "INTERNAL_ERROR", "합성 등록 오류예요.");
    const sid = state.nextSource++;
    state.nameBySource[sid] = name;
    return json(route, 201, { source_id: sid, status: "UPLOADED", duplicate: false });
  }
  if (/^\/ingest\/owner-answers\/\d+\/attachments$/.test(p)) {
    const body = JSON.parse(req.postData() || "{}");
    state.attachBodies.push({ path: p, ...body });
    const an = state.nameBySource[body.source_id];
    state.attachCount[an] = (state.attachCount[an] || 0) + 1;
    if (an === "attachfail.pdf" && state.attachCount[an] === 1) return apiError(route, 500, "INTERNAL_ERROR", "합성 붙이기 오류예요.");
    return json(route, 200, { question_id: 7, source_id: body.source_id, job_id: 900 + body.source_id, created: true });
  }
  if (p === "/learn/pending/7/answer") {
    state.answerBodies.push(JSON.parse(req.postData() || "{}"));
    return json(route, 200, { question_id: 7, status: "ANSWERED", card_id: 1, answer_text: "x" });
  }
  return apiError(route, 404, "NOT_FOUND", `합성 fixture 에 없는 경로: ${method} ${p}`);
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
      await handle(route).catch((e) => { unknown.push(`${before}: ${e.message}`); return route.abort("failed"); });
    });
    const page = await ctx.newPage();
    page.on("pageerror", (e) => errors.push(e.message));
    const shot = async (name) => { await page.waitForTimeout(300); await page.screenshot({ path: path.join(OUT, `${name}.png`) }); };
    const file = (name, size = 10) => ({ name, mimeType: "application/octet-stream", buffer: Buffer.alloc(size, 1) });
    const submit = page.getByTestId("answer-submit");
    const items = page.getByTestId("attach-item");

    const openSheet = async () => {
      await page.goto(`${BASE}/owner/questions`, { waitUntil: "networkidle" });
      await page.getByText("합성 질문: 우유는 어디에 두나요?").first().click({ timeout: 8000 }).catch(async (e) => {
        console.log("URL", page.url(), (await page.locator("body").innerText()).slice(0, 300));
        throw e;
      });
      await page.getByTestId("answer-input").waitFor();
    };

    // 1. 첨부 없이 제출 + 칩은 첨부가 없으면 안 보임
    await openSheet();
    check("첨부 버튼이 보인다", await page.getByTestId("attach-button").isVisible());
    check("첨부 전에도 칩이 보인다(파일보다 먼저 고른다)", (await page.getByRole("group", { name: "자료 종류" }).count()) === 1);
    check("글이 비면 제출이 꺼져 있다", await submit.isDisabled());
    await page.getByTestId("answer-input").fill("우유는 제빙기 아래 냉장고에 둔다.");
    check("글이 있으면 제출이 켜진다", await submit.isEnabled());
    await shot("1-no-attachment");
    await submit.click();
    await page.getByTestId("answer-input").waitFor({ state: "detached" });
    check("첨부 없이 답변이 전송된다", state.answerBodies.length === 1 && state.attachBodies.length === 0 && state.registerBodies.length === 0);

    // 2. 지원하지 않는 형식·너무 큰 파일은 고를 때 막힌다
    await openSheet();
    await page.getByTestId("attach-input").setInputFiles([file("x.exe"), file("y.exe")]);
    const both = await page.getByTestId("attach-pick-error").innerText();
    check("여러 파일의 거절 메시지를 모두 보여 준다", both.includes("x.exe") && both.includes("y.exe"));
    await page.getByTestId("attach-input").setInputFiles(file("x.exe"));
    check("지원하지 않는 형식은 막힌다", (await page.getByTestId("attach-pick-error").innerText()).includes("올릴 수 없는 형식"));
    await page.getByTestId("attach-input").setInputFiles(file("big.pdf", 2 * 1024 * 1024));
    check("너무 큰 파일은 크기 메시지로 막힌다", (await page.getByTestId("attach-pick-error").innerText()).includes("1MB보다 커서"));
    check("막힌 파일은 목록에 없고 요청도 없다", (await items.count()) === 0 && state.registerBodies.length === 0);
    await shot("2-blocked");

    // 3. 업로드 중에는 제출이 꺼진다
    await page.getByTestId("answer-input").fill("두 번째 답변");
    check("첨부 전에는 제출이 켜져 있다", await submit.isEnabled());
    await page.getByRole("button", { name: "레시피" }).click();
    await page.getByTestId("attach-input").setInputFiles(file("slow.pdf"));
    await items.first().waitFor();
    await page.waitForFunction(() => document.querySelector('[data-testid="attach-item"]')?.getAttribute("data-status") === "UPLOADING");
    check("업로드 중 상태가 보인다", (await items.first().innerText()).includes("올리는 중"));
    check("업로드 중에는 제출이 꺼진다", await submit.isDisabled());
    check("업로드 중에는 시트를 닫을 수 없다", await page.getByRole("button", { name: "닫기" }).isDisabled());
    await page.getByRole("button", { name: "나중에 답하기" }).click({ force: true }).catch(() => {});
    check("닫기를 눌러도 시트가 남아 있다", await page.getByTestId("answer-input").isVisible());
    await shot("3-uploading");

    // 4. 실패한 첨부: 다시 시도 전에는 제출이 꺼져 있고, 빼면 다시 켜진다
    state.releaseSlow();
    const slowBody = state.registerBodies.find((b) => b.title === "slow.pdf");
    check("첫 파일의 등록 본문에 미리 고른 칩이 owner_hints 로 간다", JSON.stringify(slowBody.owner_hints) === JSON.stringify(["RECIPE"]));
    await page.waitForFunction(() => document.querySelector('[data-testid="attach-item"]')?.getAttribute("data-status") === "DONE");
    check("완료되면 제출이 다시 켜진다", await submit.isEnabled());
    await page.getByTestId("attach-input").setInputFiles(file("fail.pdf"));
    await page.waitForFunction(() => document.querySelectorAll('[data-testid="attach-item"][data-status="FAILED"]').length === 1);
    check("실패한 첨부는 제출을 막는다", await submit.isDisabled());
    check("실패 이유와 다시 시도가 보인다", (await page.getByTestId("attach-retry").count()) === 1);
    await shot("4-failed");

    // 5. 칩을 고르고 다시 시도하면 owner_hints 가 요청 본문에 실린다
    await page.getByRole("button", { name: "공지" }).click();
    check("칩이 눌린 상태로 보인다", (await page.getByRole("button", { name: "레시피" }).getAttribute("aria-pressed")) === "true");
    await page.getByTestId("attach-retry").click();
    await page.waitForFunction(() => document.querySelectorAll('[data-testid="attach-item"][data-status="DONE"]').length === 2);
    const retried = state.registerBodies.filter((b) => b.title === "fail.pdf");
    check("첫 시도는 미리 고른 칩만 갔다", JSON.stringify(retried[0].owner_hints) === JSON.stringify(["RECIPE"]));
    check("재시도 요청 본문에 선택한 칩이 owner_hints 로 간다", JSON.stringify(retried[1].owner_hints) === JSON.stringify(["RECIPE", "NOTICE"]));
    check("완료된 첨부에는 빼기가 없다", (await page.getByTestId("attach-remove").count()) === 0);
    check("첨부 API 가 질문 7번에 자료를 붙인다", state.attachBodies.length === 2 && state.attachBodies.every((a) => a.path === "/ingest/owner-answers/7/attachments"));

    // 5b. 등록은 됐고 붙이기만 실패 -> 다시 시도는 등록을 되풀이하지 않는다
    await page.getByTestId("attach-input").setInputFiles(file("attachfail.pdf"));
    await page.waitForFunction(() => document.querySelectorAll('[data-testid="attach-item"][data-status="FAILED"]').length === 1);
    check("붙이기 실패도 제출을 막는다", await submit.isDisabled());
    await page.getByTestId("attach-retry").click();
    await page.waitForFunction(() => document.querySelectorAll('[data-testid="attach-item"][data-status="DONE"]').length === 3);
    check("재시도는 등록을 다시 하지 않는다(등록 1회, 붙이기 2회)", state.registerCount["attachfail.pdf"] === 1 && state.attachCount["attachfail.pdf"] === 2);

    // 6. 칩을 고른 뒤 새로 고른 파일에도 같은 칩이 실린다
    await page.getByTestId("attach-input").setInputFiles(file("extra.pdf"));
    await page.waitForFunction(() => document.querySelectorAll('[data-testid="attach-item"][data-status="DONE"]').length === 4);
    const extra = state.registerBodies.find((b) => b.title === "extra.pdf");
    check("새 첨부에도 선택한 칩이 owner_hints 로 간다", JSON.stringify(extra.owner_hints) === JSON.stringify(["RECIPE", "NOTICE"]));
    await shot("5-all-done");

    // 7. 완료된 첨부 뒤 제출
    check("모두 완료되면 제출이 켜진다", await submit.isEnabled());
    await submit.click();
    await page.getByTestId("answer-input").waitFor({ state: "detached" });
    check("완료 뒤 답변이 전송된다(answer_text 만)", state.answerBodies.length === 2 && Object.keys(state.answerBodies[1]).join() === "answer_text");

    // 8. 실패한 첨부를 빼면 제출이 켜진다 (등록이 항상 실패하는 새 이름)
    await openSheet();
    await page.getByTestId("answer-input").fill("세 번째 답변");
    await ctx.route(/^http:\/\/(localhost|127\.0\.0\.1):8000\/ingest\/sources$/, (route) => apiError(route, 500, "INTERNAL_ERROR", "합성 등록 오류예요."));
    await page.getByTestId("attach-input").setInputFiles(file("always-fail.pdf"));
    await page.waitForFunction(() => document.querySelectorAll('[data-testid="attach-item"][data-status="FAILED"]').length === 1);
    check("실패 첨부가 있으면 제출이 꺼진다", await submit.isDisabled());
    await page.getByTestId("attach-remove").click();
    check("실패 첨부를 빼면 제출이 켜진다", (await items.count()) === 0 && (await submit.isEnabled()));
    check("칩은 첨부와 상관없이 계속 보인다", (await page.getByRole("group", { name: "자료 종류" }).count()) === 1);
    await shot("6-removed");

    check("가로 넘침이 없다", await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    check("페이지 오류가 없다", errors.length === 0);
    check("합성 fixture 에 없는 요청이 없다", unknown.length === 0);
  } catch (e) {
    console.error("FAIL", e.message, { errors, unknown });
    process.exitCode = 1;
  } finally {
    await browser.close();
  }
})();
