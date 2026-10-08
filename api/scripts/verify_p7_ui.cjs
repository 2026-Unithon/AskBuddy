// P7 실제 FastAPI·PostgreSQL 확인. 전용 실행기 fixture 사용. API 응답 mock·모델 호출 없음.
const { chromium, request } = require("playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const f = JSON.parse(fs.readFileSync(process.env.P7_FIXTURE_FILE, "utf8"));
const BASE = "http://127.0.0.1:3011";
const output = process.env.P7_ARTIFACT_DIR;
(async () => {
  fs.mkdirSync(output, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  const http = await request.newContext({ baseURL: "http://127.0.0.1:8000" });
  let passed = 0;
  const errors = [];
  const check = (name, condition) => {
    assert.ok(condition, name);
    passed++;
    console.log("PASS P7", name);
  };
  async function json(token, method, url, data) {
    const r = await http.fetch(url, {
      method,
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      data,
    });
    const body = r.status() === 204 ? null : await r.json();
    assert.ok(
      r.ok(),
      `${method} ${url}: ${r.status()} ${JSON.stringify(body)}`,
    );
    return body;
  }
  async function context(role) {
    const login = await json(null, "POST", "/auth/login", {
      email: role === "OWNER" ? "p7-owner@example.com" : "p7-staff@example.com",
      password: f.password,
      role,
    });
    const ctx = await browser.newContext({
      viewport: { width: 390, height: 844 },
    });
    await ctx.addInitScript(
      ({ login, role }) =>
        localStorage.setItem(
          "askbuddy_state",
          JSON.stringify({
            v: 9,
            data: {
              token: login.token,
              role,
              userId: login.user.user_id,
              storeId: login.user.store_id,
            },
          }),
        ),
      { login, role },
    );
    const page = await ctx.newPage();
    page.on("pageerror", (e) => errors.push(e.message));
    return { ctx, page, token: login.token };
  }
  async function shot(page, name) {
    await page
      .locator("main")
      .first()
      .evaluate((main) => main.scrollTo(0, 0));
    await page.screenshot({ path: path.join(output, `${name}.png`) });
  }
  async function widths(page, name) {
    for (const width of [390, 360]) {
      await page.setViewportSize({ width, height: width === 360 ? 800 : 844 });
      check(
        `${name} ${width}px 가로 넘침 없음`,
        await page.evaluate(
          () =>
            [...document.querySelectorAll("main")].every(
              (main) => main.scrollWidth <= main.clientWidth,
            ) && document.documentElement.scrollWidth <= innerWidth,
        ),
      );
      if (name === "staff-today" || name === "owner-today") {
        check(
          `${name} ${width}px 진행 카드 내용 잘림 없음`,
          await page.getByRole("progressbar").evaluate((bar) => {
            const section = bar.closest("section");
            return (
              section &&
              [...section.children]
                .filter(
                  (child) => getComputedStyle(child).position !== "absolute",
                )
                .every(
                  (child) =>
                    child.getBoundingClientRect().bottom <=
                    section.getBoundingClientRect().bottom,
                )
            );
          }),
        );
      }
      await shot(page, `${name}-${width}`);
    }
    await page.setViewportSize({ width: 390, height: 844 });
  }
  try {
    const owner = await context("OWNER"),
      staff = await context("STAFF");
    const op = owner.page,
      sp = staff.page;
    await op.goto(`${BASE}/owner/shifts`);
    await op.getByRole("button", { name: "근무조 추가" }).click();
    await op.getByLabel("이름", { exact: true }).fill("아침");
    await op.getByLabel("시작", { exact: true }).fill("07:00");
    await op.getByLabel("끝", { exact: true }).fill("11:00");
    await op
      .getByRole("dialog")
      .getByRole("button", { name: "저장", exact: true })
      .click();
    await op.getByRole("heading", { name: "아침", exact: true }).waitFor();
    const shift = (await json(owner.token, "GET", "/checklist/shifts"))
      .items[0];
    check(
      "근무조 생성 실제 DB 저장",
      shift.name === "아침" && shift.starts_at === "07:00",
    );
    await op.getByRole("button", { name: "할 일 담기", exact: true }).click();
    await op
      .getByRole("checkbox", { name: "합성 청소 안내", exact: true })
      .click();
    await op
      .getByRole("dialog")
      .getByRole("button", { name: "저장", exact: true })
      .click();
    await op.getByRole("dialog").waitFor({ state: "hidden" });
    check(
      "근무조 카드 연결 실제 저장",
      (
        await json(owner.token, "GET", "/checklist/shifts")
      ).items[0].card_ids.includes(f.cards[0]),
    );
    await json(owner.token, "PUT", `/checklist/cards/${f.cards[1]}`, {
      checklist: true,
      shift_ids: [],
    });
    await op.goto(`${BASE}/owner/members`);
    await op.getByRole("button", { name: "아침", exact: true }).click();
    await op.waitForFunction(() =>
      document.querySelector("[aria-pressed=true]"),
    );
    check(
      "직원 담당 실제 저장",
      (await json(owner.token, "GET", "/checklist/members")).items
        .find((x) => x.member_id === f.member)
        .shift_ids.includes(shift.shift_id),
    );
    await widths(op, "owner-members");
    await sp.goto(`${BASE}/staff`);
    await sp.getByRole("checkbox", { name: "작업대 닦기" }).waitFor();
    check(
      "공통 + 담당 근무조 실제 범위",
      (await sp.getByRole("checkbox").count()) === 3,
    );
    await widths(sp, "staff-today");
    const checkSaved = sp.waitForResponse(
      (response) =>
        response.url().endsWith("/checklist/checks") &&
        response.request().method() === "PUT",
    );
    await sp.getByRole("checkbox", { name: "머신 청소" }).click();
    assert.equal((await checkSaved).status(), 200);
    await sp.waitForFunction(() =>
      [...document.querySelectorAll("[role=checkbox]")].every(
        (row) => row.getAttribute("aria-busy") !== "true",
      ),
    );
    const status = await json(owner.token, "GET", "/checklist/status");
    assert.deepEqual(status.scope_counts, { done: 1, total: 3 });
    check(
      "직원 체크가 점주 실제 API에 반영",
      status.scope_counts.done === 1 && status.scope_counts.total === 3,
    );
    check(
      "점주 현황 제출자 식별 없음",
      !JSON.stringify(status).includes("user_id"),
    );
    await op.goto(`${BASE}/owner`);
    await op.getByText("체크 1/3개", { exact: true }).waitFor();
    await widths(op, "owner-today");
    await sp.getByTestId("checklist-submit").click();
    await sp
      .getByText("2개가 남았어요. 그래도 끝낼까요?", { exact: true })
      .waitFor();
    await sp.getByRole("button", { name: "그래도 끝내기" }).click();
    await sp.getByTestId("checklist-complete").waitFor();
    await sp.reload();
    await sp.getByTestId("checklist-complete").waitFor();
    check(
      "실제 제출·새로고침 복원",
      (await json(staff.token, "GET", "/checklist/today")).my_submission
        .done_lines === 1,
    );
    await widths(sp, "staff-complete");
    const today = (await json(staff.token, "GET", "/checklist/today"))
      .business_date;
    await sp.goto(`${BASE}/staff/me`);
    await sp.getByRole("button", { name: `${today} 33%`, exact: true }).click();
    await sp.getByText("✓ 머신 청소", { exact: true }).waitFor();
    check("실제 기록 달력 제출 퍼센트·체크한 줄", true);
    await widths(sp, "staff-records");
    await op.goto(`${BASE}/owner/me`);
    await op.getByLabel("기록 구성원").selectOption(String(f.staff));
    await op.getByRole("button", { name: `${today} 33%`, exact: true }).click();
    await op.getByText("✓ 머신 청소", { exact: true }).waitFor();
    await widths(op, "owner-records");
    await op.goto(`${BASE}/owner/shifts`);
    await op.getByRole("button", { name: "고치기", exact: true }).click();
    await op.getByLabel("이름", { exact: true }).fill("오전 점검");
    await op.getByLabel("시작", { exact: true }).fill("22:00");
    await op.getByLabel("끝", { exact: true }).fill("02:00");
    await op
      .getByRole("dialog")
      .getByRole("button", { name: "저장", exact: true })
      .click();
    await op.getByRole("heading", { name: "오전 점검", exact: true }).waitFor();
    check(
      "근무조 편집·자정 넘는 시간 저장",
      (await json(owner.token, "GET", "/checklist/shifts")).items[0].ends_at ===
        "02:00",
    );
    await widths(op, "owner-shifts");
    await op.getByRole("switch", { name: /알바생 기록/ }).click();
    await op.waitForFunction(
      () =>
        document
          .querySelector("[role=switch]")
          ?.getAttribute("aria-checked") === "false",
    );
    check(
      "알바생 기록 숨김 실제 조회",
      !(
        await json(
          owner.token,
          "GET",
          `/checklist/records?month=${today.slice(0, 7)}&user_id=${f.staff}`,
        )
      ).visible,
    );
    await op.getByRole("switch", { name: /알바생 기록/ }).click();
    await op.waitForFunction(
      () =>
        document
          .querySelector("[role=switch]")
          ?.getAttribute("aria-checked") === "true",
    );
    check(
      "기록 다시 켜면 이전 기록 유지",
      (
        await json(
          owner.token,
          "GET",
          `/checklist/records?month=${today.slice(0, 7)}&user_id=${f.staff}`,
        )
      ).days.length === 1,
    );
    await sp.goto(`${BASE}/staff/me`);
    await sp.getByRole("switch", { name: /내 기록 남기기/ }).click();
    await sp.waitForFunction(
      () =>
        document
          .querySelector("[role=switch]")
          ?.getAttribute("aria-checked") === "false",
    );
    check(
      "본인 기록 설정 실제 복원",
      !(await json(staff.token, "GET", "/checklist/me"))
        .personal_records_enabled,
    );
    await sp.getByRole("switch", { name: /내 기록 남기기/ }).click();
    await sp.waitForFunction(
      () =>
        document
          .querySelector("[role=switch]")
          ?.getAttribute("aria-checked") === "true",
    );
    // 영업일 설정은 화면과 같은 분 단위로 검증한다. 시작 전에 페이지를 열 여유를 둔다.
    const boundary = new Date(
      Math.ceil((Date.now() + 15_000) / 60_000) * 60_000,
    );
    const start = new Intl.DateTimeFormat("sv-SE", {
      timeZone: "Asia/Seoul",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
    }).format(boundary);
    await json(owner.token, "PATCH", "/checklist/settings", {
      business_day_starts_at: start,
    });
    await sp.goto(`${BASE}/staff`);
    await sp.getByRole("checkbox", { name: "머신 청소" }).waitFor();
    const before = (await json(staff.token, "GET", "/checklist/today"))
      .business_date;
    await new Promise((resolve) =>
      setTimeout(resolve, Math.max(0, boundary.getTime() - Date.now()) + 1200),
    );
    await sp.evaluate(() =>
      document.dispatchEvent(new Event("visibilitychange")),
    );
    await sp.getByText("어제 체크리스트", { exact: true }).waitFor();
    await sp
      .getByRole("dialog")
      .getByRole("checkbox", { name: "바닥 닦기" })
      .click();
    await shot(sp, "staff-yesterday-390");
    await sp.getByTestId("yesterday-save").click();
    await sp.getByRole("dialog").waitFor({ state: "hidden" });
    const late = await json(staff.token, "GET", `/checklist/records/${before}`);
    check(
      "실제 영업일 전환 어제 창·late 저장",
      late.submission?.late === true &&
        late.lines.some((x) => x.text === "바닥 닦기"),
    );
    await json(owner.token, "PATCH", "/checklist/settings", {
      business_day_starts_at: "04:00",
    });
    await op.goto(`${BASE}/owner/notifications`);
    await op.getByText("합성 질문 알림", { exact: true }).click();
    await op.waitForURL(`**/owner/questions/${f.pending}`);
    await op.getByRole("heading", { name: "직원 질문", exact: true }).waitFor();
    check("점주 알림 딥링크 질문 ID 보존", true);
    await widths(op, "owner-question");
    await sp.goto(`${BASE}/staff/notifications/v2`);
    await sp
      .getByRole("listitem")
      .filter({ hasText: "합성 답변 알림" })
      .getByRole("button", { name: "답변 확인" })
      .click();
    await sp.waitForURL(`**/staff/ask?session_id=${f.session}`);
    check("직원 답변 알림 딥링크 세션 ID 보존", true);
    await widths(sp, "staff-ask");
    await sp.goto(`${BASE}/staff/items/${f.item}`);
    await sp.waitForURL(`**/staff/recipes/${f.item}`);
    await sp
      .getByRole("heading", { name: "합성 청소 안내", exact: true })
      .waitFor();
    check("옛 학습 상세 실제 공개 카드로 이동", true);
    await widths(sp, "staff-recipe");
    await sp.goto(`${BASE}/staff/roadmap`);
    await sp.waitForURL("**/staff/recipes");
    await sp.getByText("합성 청소 안내", { exact: true }).waitFor();
    await widths(sp, "staff-recipes");
    await op.goto(`${BASE}/owner/upload`);
    await op.waitForURL("**/owner/add");
    await op
      .getByRole("heading", { name: "알려주고 싶은 걸 아무거나 넣어주세요" })
      .waitFor();
    await widths(op, "owner-add");
    await op.goto(`${BASE}/owner/cards/review?job_id=${f.job}`);
    await op.waitForURL(`**/owner/cards?status=all&job_id=${f.job}`);
    await op.getByText("합성 청소 안내", { exact: true }).waitFor();
    check("옛 검수 딥링크 작업 ID 보존", true);
    await op.goto(`${BASE}/owner/jobs/${f.job}`);
    await op.getByText("합성 청소 안내", { exact: true }).waitFor();
    await widths(op, "owner-job");
    for (const [route, title, name] of [
      ["/owner/cards", "카드", "owner-cards"],
      [`/owner/cards/${f.cards[0]}`, "합성 청소 안내", "owner-card"],
      ["/owner/settings", "설정", "owner-settings"],
      ["/staff/settings", "설정", "staff-settings"],
      ["/owner/invite", "첫 준비 끝났어요", "owner-invite"],
    ]) {
      const page = route.startsWith("/staff") ? sp : op;
      await page.goto(`${BASE}${route}`);
      await page.getByRole("heading", { name: title, exact: true }).waitFor();
      await widths(page, name);
    }
    check("실제 API 브라우저 런타임 오류 없음", errors.length === 0);
    fs.writeFileSync(
      path.join(output, "../result.json"),
      JSON.stringify(
        {
          assertions: passed,
          screenshots: fs.readdirSync(output).filter((x) => x.endsWith(".png"))
            .length,
          runtimeErrors: errors,
        },
        null,
        2,
      ),
    );
    console.log(`PASS P7 real API browser assertions: ${passed}`);
    await owner.ctx.close();
    await staff.ctx.close();
  } finally {
    await http.dispose();
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
