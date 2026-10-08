// P5 브라우저 검증. 모든 API 응답은 합성 fixture이며 실제 매장·DB를 사용하지 않는다.
// next start -p 3011 후 NODE_PATH=<playwright 설치 경로> node api/scripts/verify_ui_checklist.cjs
const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const BASE = process.env.P5_UI_BASE || "http://127.0.0.1:3011";
const artifactDir = process.env.P5_UI_ARTIFACT_DIR || "/tmp/askbuddy-p5-ui";
const fs = require("node:fs");

(async () => {
  fs.mkdirSync(artifactDir, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  let passed = 0;
  const check = (name, condition) => {
    assert.ok(condition, name);
    console.log("PASS P5", name);
    passed++;
  };
  async function setup(role = "STAFF", width = 390) {
    const ctx = await browser.newContext({ viewport: { width, height: 844 } });
    const date = new Date().toLocaleDateString("sv-SE", {
      timeZone: "Asia/Seoul",
    });
    const month = date.slice(0, 7);
    const s = {
      date,
      previous: "2026-10-07",
      checked: [false, false],
      submission: null,
      prevSubmitted: true,
      failCheck: false,
      failSubmit: false,
      failToday: false,
      slowToday: false,
      rollover: false,
      failLate: false,
      calls: [],
      edits: [],
      personal: true,
      visible: true,
      empty: false,
      shifts: [
        {
          shift_id: 1,
          name: "아침",
          starts_at: "07:00",
          ends_at: "11:00",
          sort_order: 0,
          card_ids: [1],
        },
      ],
      links: { checklist: true, shift_ids: [1] },
      memberIds: [],
      failShift: false,
    };
    await ctx.addInitScript(
      (role) =>
        localStorage.setItem(
          "askbuddy_state",
          JSON.stringify({
            v: 9,
            data: {
              token: "synthetic-p5-only",
              role,
              userId: role === "OWNER" ? 1 : 2,
              storeId: 1,
            },
          }),
        ),
      role,
    );
    const sub = () => ({
      submitted_at: `${date}T09:00:00Z`,
      total_lines: 2,
      done_lines: s.checked.filter(Boolean).length,
    });
    const today = (late = false) => ({
      business_date: late ? s.previous : s.date,
      previous_business_date: s.previous,
      previous_submitted: s.prevSubmitted,
      scope: { all: true, shift_ids: s.shifts.map((x) => x.shift_id) },
      current_shift_id: s.shifts[0]?.shift_id ?? null,
      upcoming: false,
      shifts: s.shifts.map((x) => ({
        ...x,
        total: 2,
        done: s.checked.filter(Boolean).length,
        submitted: Boolean(s.submission),
      })),
      scope_counts: {
        total: s.empty ? 0 : 2,
        done: s.checked.filter(Boolean).length,
      },
      view: { total: s.empty ? 0 : 2, done: s.checked.filter(Boolean).length },
      groups: s.empty
        ? []
        : [
            {
              shift_id: s.shifts[0]?.shift_id ?? null,
              name: s.shifts[0]?.name ?? "전체",
              cards: [
                {
                  card_id: 1,
                  card_version_id: 10,
                  title: "합성 청소",
                  lines: ["머신 청소", "바닥 닦기"].map((text, i) => ({
                    line_no: i + 1,
                    text,
                    checked: s.checked[i],
                  })),
                },
              ],
            },
          ],
      my_submission: late ? null : s.submission,
    });
    await ctx.route("http://localhost:8000/**", async (route) => {
      const req = route.request(),
        u = new URL(req.url()),
        p = u.pathname,
        method = req.method();
      if (method === "OPTIONS")
        return route.fulfill({
          status: 204,
          headers: {
            "access-control-allow-origin": "*",
            "access-control-allow-headers": "*",
            "access-control-allow-methods": "*",
          },
        });
      const body = req.postData() ? req.postDataJSON() : null;
      const respond = (payload, status = 200) =>
        route.fulfill({
          status,
          contentType: "application/json",
          body: JSON.stringify(payload),
          headers: { "access-control-allow-origin": "*" },
        });
      const fail = (
        message,
        status = 500,
        code = "SYNTHETIC_ERROR",
        details = {},
      ) =>
        respond(
          { error: { message, code, retryable: false, details } },
          status,
        );
      let payload;
      if (p === "/app/bootstrap")
        payload = {
          user: {
            user_id: role === "OWNER" ? 1 : 2,
            role,
            name: "합성 사용자",
          },
          store: {
            store_id: 1,
            store_name: "합성 매장",
            guide_completed: true,
          },
          badges: {},
          default_destination: role === "OWNER" ? "/owner" : "/staff",
        };
      else if (p === "/learn/v2/pending")
        payload = { questions: [], next_after: null };
      else if (p === "/checklist/today") {
        if (s.slowToday) await new Promise((r) => setTimeout(r, 500));
        if (s.failToday) return fail("합성 조회 실패");
        payload = today(Boolean(u.searchParams.get("date")));
      } else if (p === "/checklist/checks") {
        s.calls.push(body);
        await new Promise((r) => setTimeout(r, 100));
        if (s.rollover) {
          s.rollover = false;
          s.previous = body.business_date;
          const d = new Date(`${body.business_date}T00:00:00Z`);
          d.setUTCDate(d.getUTCDate() + 1);
          s.date = d.toISOString().slice(0, 10);
          s.prevSubmitted = false;
          return fail("하루가 바뀌었어요.", 409, "BUSINESS_DATE_CHANGED", {
            current_business_date: s.date,
            previous_unsubmitted: true,
          });
        }
        if (s.failCheck) {
          s.failCheck = false;
          return fail("합성 체크 실패");
        }
        s.checked[body.line_no - 1] = body.checked;
        if (s.checked.every(Boolean)) s.submission = sub();
        payload = { submitted: Boolean(s.submission) };
      } else if (p === "/checklist/submissions") {
        s.edits.push(body);
        if (body.business_date !== s.date) {
          if (s.failLate) {
            s.failLate = false;
            return fail("합성 어제 저장 실패");
          }
          s.prevSubmitted = true;
        } else {
          if (s.failSubmit) {
            s.failSubmit = false;
            return fail("합성 제출 실패");
          }
          s.submission = sub();
        }
        payload = { submission: sub() };
      } else if (p === "/checklist/status")
        payload = {
          ...today(),
          last_submission: s.submission
            ? { ...s.submission, business_date: s.date, shift_names: ["아침"] }
            : null,
        };
      else if (p === "/checklist/me") {
        if (body) s.personal = body.personal_records_enabled;
        payload = { personal_records_enabled: s.personal };
      } else if (p === "/checklist/settings") {
        if (body?.staff_records_visible !== undefined)
          s.visible = body.staff_records_visible;
        payload = {
          business_day_starts_at: body?.business_day_starts_at ?? "04:00",
          staff_records_visible: s.visible,
          timezone: "Asia/Seoul",
        };
      } else if (p === "/checklist/records")
        payload = {
          user_id: 2,
          month,
          visible: !u.searchParams.has("user_id") || s.visible,
          recording: s.personal,
          days: [
            {
              date,
              percent: 50,
              total: 2,
              done: 1,
              checked_lines: 1,
              submitted: true,
            },
          ],
        };
      else if (p.startsWith("/checklist/records/"))
        payload = {
          date: p.split("/").at(-1),
          visible: true,
          lines: [
            {
              title: "합성 청소",
              text: "머신 청소",
              checked_at: `${date}T09:00:00Z`,
            },
          ],
          submission: sub(),
        };
      else if (p === "/checklist/shifts" && method === "GET")
        payload = { items: s.shifts };
      else if (p === "/checklist/shifts" && method === "POST") {
        if (s.failShift) {
          s.failShift = false;
          return fail("같은 이름의 근무조가 있어요.", 409);
        }
        const shift = {
          ...body,
          shift_id: s.shifts.length + 1,
          sort_order: s.shifts.length,
          card_ids: [],
        };
        s.shifts.push(shift);
        payload = shift;
      } else if (p === "/checklist/shifts/order") {
        s.shifts = body.shift_ids.map((id) =>
          s.shifts.find((x) => x.shift_id === id),
        );
        payload = { items: s.shifts };
      } else if (p === "/checklist/shifts/preset") {
        s.shifts = ["오픈", "미들", "마감"].map((name, i) => ({
          shift_id: i + 1,
          name,
          starts_at: null,
          ends_at: null,
          sort_order: i,
          card_ids: [],
        }));
        payload = { items: s.shifts };
      } else if (/^\/checklist\/shifts\/\d+\/cards$/.test(p)) {
        s.shifts.find((x) => x.shift_id === Number(p.split("/")[3])).card_ids =
          body.ids;
        payload = body;
      } else if (/^\/checklist\/shifts\/\d+$/.test(p)) {
        const id = Number(p.split("/").at(-1));
        if (method === "DELETE") {
          s.shifts = s.shifts.filter((x) => x.shift_id !== id);
          return route.fulfill({ status: 204 });
        }
        Object.assign(
          s.shifts.find((x) => x.shift_id === id),
          body,
        );
        payload = body;
      } else if (p === "/checklist/members")
        payload = {
          items: [
            {
              member_id: 2,
              user_id: 2,
              role: "STAFF",
              name: "합성 알바",
              shift_ids: s.memberIds,
            },
          ],
        };
      else if (/^\/checklist\/members\/\d+\/shifts$/.test(p)) {
        s.memberIds = body.ids;
        payload = body;
      } else if (p === "/checklist/cards/1") {
        if (body) s.links = body;
        payload = s.links;
      } else if (p === "/cards")
        payload = {
          items: [
            {
              card_id: 1,
              title: "합성 청소",
              review_status: "APPROVED",
              category: { category_id: 1, name: "매장 관리" },
            },
          ],
          next_cursor: null,
          total: 1,
        };
      else if (p === "/cards/1")
        payload = {
          card_id: 1,
          title: "합성 청소",
          review_status: "APPROVED",
          published: {
            version_id: 10,
            title: "합성 청소",
            content: "머신 청소\n바닥 닦기",
            created_at: `${date}T09:00:00Z`,
          },
          draft: null,
          category: null,
          source: null,
          evidence: [],
          events: [],
          updated_at: `${date}T09:00:00Z`,
        };
      else if (p === "/ingest/capabilities") payload = {};
      else if (p === "/ingest/jobs")
        payload = { items: [], next_cursor: null, total: 0 };
      else return fail(`합성 경로 없음 ${p}`, 404);
      await respond(payload);
    });
    const page = await ctx.newPage();
    const errors = [];
    page.on("pageerror", (e) => errors.push(e.message));
    return { ctx, page, s, errors };
  }
  try {
    {
      const { ctx, page, s, errors } = await setup();
      s.slowToday = true;
      await page.goto(`${BASE}/staff`);
      await page
        .getByRole("heading", { name: "오늘 할 일", exact: true })
        .waitFor();
      await page.getByRole("checkbox", { name: "머신 청소" }).waitFor();
      s.slowToday = false;
      s.failCheck = true;
      await page.getByRole("checkbox", { name: "머신 청소" }).click();
      await page
        .getByText("이 변경은 저장되지 않았어요. 다시 눌러 주세요.")
        .waitFor();
      check(
        "체크 실패 되돌림",
        (await page
          .getByRole("checkbox", { name: "머신 청소" })
          .getAttribute("aria-checked")) === "false",
      );
      await page.getByRole("checkbox", { name: "머신 청소" }).click();
      await page.waitForFunction(
        () =>
          document
            .querySelector("[role=checkbox]")
            ?.getAttribute("aria-busy") !== "true",
      );
      check("체크 재시도 저장", s.checked[0]);
      await page.getByTestId("checklist-submit").click();
      await page.getByRole("dialog").waitFor();
      check(
        "남은 항목 제출 확인",
        await page.getByText("1개가 남았어요. 그래도 끝낼까요?").isVisible(),
      );
      s.failSubmit = true;
      await page.getByRole("button", { name: "그래도 끝내기" }).click();
      await page.getByText("합성 제출 실패").first().waitFor();
      check(
        "제출 실패 완료 표시 없음",
        (await page.getByTestId("checklist-complete").count()) === 0,
      );
      await page.getByRole("button", { name: "그래도 끝내기" }).click();
      await page.getByTestId("checklist-complete").waitFor();
      await page.reload();
      await page.getByTestId("checklist-complete").waitFor();
      check("제출 재진입 복원", true);
      await page.screenshot({ path: `${artifactDir}/staff-complete.png` });
      check("직원 화면 런타임 오류 없음", errors.length === 0);
      await ctx.close();
    }
    {
      const { ctx, page, s } = await setup("STAFF", 360);
      await page.goto(`${BASE}/staff`);
      await page.getByRole("checkbox", { name: "머신 청소" }).waitFor();
      s.rollover = true;
      s.failLate = true;
      await page.getByRole("checkbox", { name: "머신 청소" }).click();
      const dialog = page.getByRole("dialog");
      await dialog.waitFor();
      check(
        "날짜 변경 어제 창",
        await page.getByText("어제 체크리스트", { exact: true }).isVisible(),
      );
      check(
        "실패한 체크 어제 초안에 반영",
        (await dialog
          .getByRole("checkbox", { name: "머신 청소" })
          .getAttribute("aria-checked")) === "true",
      );
      check(
        "어제 창 닫기 없음",
        (await page
          .getByRole("button", { name: "닫기", exact: true })
          .count()) === 0,
      );
      await page.keyboard.press("Escape");
      check("Escape 어제 창 보존", await dialog.isVisible());
      await page.getByTestId("yesterday-save").focus();
      await page.keyboard.press("Tab");
      check(
        "어제 창 키보드 포커스 유지",
        await page.evaluate(() =>
          document
            .querySelector("[role=dialog]")
            .contains(document.activeElement),
        ),
      );
      await dialog.getByRole("checkbox", { name: "바닥 닦기" }).click();
      await page.getByTestId("yesterday-save").click();
      await page.getByText("합성 어제 저장 실패").waitFor();
      check(
        "어제 저장 실패 입력 보존",
        (await dialog
          .getByRole("checkbox", { name: "바닥 닦기" })
          .getAttribute("aria-checked")) === "true",
      );
      await page.getByTestId("yesterday-save").click();
      await dialog.waitFor({ state: "hidden" });
      check(
        "어제 전체 상태 제출·중복 줄 없음",
        s.edits.at(-1).checks.length === 2 &&
          s.edits.at(-1).checks.every((x) => x.checked),
      );
      check(
        "360px 가로 넘침 없음",
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      );
      await ctx.close();
    }
    {
      const { ctx, page, s } = await setup();
      s.failToday = true;
      await page.goto(`${BASE}/staff`);
      await page.getByText("합성 조회 실패").waitFor();
      check(
        "조회 오류 빈 상태와 구분",
        (await page.getByText("아직 오늘 할 일이 없어요").count()) === 0,
      );
      s.failToday = false;
      s.empty = true;
      await page.getByRole("button", { name: "다시 시도" }).click();
      await page.getByText("아직 오늘 할 일이 없어요").waitFor();
      check("오류 재시도 빈 상태 복구", true);
      await ctx.close();
    }
    {
      const { ctx, page, s, errors } = await setup("OWNER");
      await page.goto(`${BASE}/owner`);
      await page
        .getByRole("progressbar", { name: "매장 체크리스트 진행" })
        .waitFor();
      check(
        "점주 현황 실제 개수",
        await page.getByText("체크 0/2개").isVisible(),
      );
      await page.goto(`${BASE}/owner/shifts`);
      await page.getByRole("heading", { name: "아침", exact: true }).waitFor();
      s.failShift = true;
      await page.getByRole("button", { name: "근무조 추가" }).click();
      await page.getByLabel("이름", { exact: true }).fill("저녁");
      await page
        .getByRole("dialog")
        .getByRole("button", { name: "저장", exact: true })
        .click();
      await page.getByText("같은 이름의 근무조가 있어요.").waitFor();
      check(
        "근무조 실패 이름 보존",
        (await page.getByLabel("이름", { exact: true }).inputValue()) ===
          "저녁",
      );
      await page
        .getByRole("dialog")
        .getByRole("button", { name: "저장", exact: true })
        .click();
      await page.getByRole("heading", { name: "저녁", exact: true }).waitFor();
      check("근무조 추가", s.shifts.length === 2);
      await page.getByRole("button", { name: "저녁 위로" }).click();
      await page.waitForFunction(
        () => document.querySelector("h2")?.textContent === "저녁",
      );
      check("근무조 순서 저장", s.shifts[0].name === "저녁");
      await page.getByRole("button", { name: "할 일 담기" }).first().click();
      await page.getByRole("checkbox", { name: "합성 청소" }).click();
      await page
        .getByRole("dialog")
        .getByRole("button", { name: "저장", exact: true })
        .click();
      await page.getByRole("dialog").waitFor({ state: "hidden" });
      check("근무조 카드 담기", s.shifts[0].card_ids.includes(1));
      await page.getByRole("switch", { name: /알바생 기록/ }).click();
      await page.waitForFunction(
        () =>
          document
            .querySelector("[role=switch]")
            ?.getAttribute("aria-checked") === "false",
      );
      check("알바생 기록 조회 끄기", !s.visible);
      await page.getByRole("switch", { name: /알바생 기록/ }).click();
      await page.waitForFunction(
        () =>
          document
            .querySelector("[role=switch]")
            ?.getAttribute("aria-checked") === "true",
      );
      await page.goto(`${BASE}/owner/members`);
      await page.getByRole("heading", { name: "합성 알바" }).waitFor();
      await page.getByRole("button", { name: "아침", exact: true }).click();
      await page.waitForFunction(() =>
        document.querySelector("[aria-pressed=true]"),
      );
      check("직원 담당 저장", s.memberIds.includes(1));
      await page.goto(`${BASE}/owner/cards/1`);
      await page
        .getByRole("heading", { name: "어느 근무조 할 일인가요?" })
        .waitFor();
      await page.getByRole("button", { name: "공통", exact: true }).click();
      await page.waitForFunction(
        () =>
          document.querySelector("button[aria-pressed=true]")?.textContent ===
          "공통",
      );
      check(
        "카드 공통 연결",
        s.links.checklist && s.links.shift_ids.length === 0,
      );
      await page.goto(`${BASE}/owner/me`);
      await page.getByLabel("기록 구성원").waitFor();
      await page.getByLabel("기록 구성원").selectOption("2");
      await page
        .getByRole("button", { name: `${s.date} 50%`, exact: true })
        .click();
      await page.getByText("✓ 머신 청소").waitFor();
      check("개인 달력 제출 퍼센트·한 일", true);
      await page.getByRole("switch", { name: /내 기록 남기기/ }).click();
      await page.waitForFunction(
        () =>
          document
            .querySelector("[role=switch]")
            ?.getAttribute("aria-checked") === "false",
      );
      check("내 기록 남기기 끄기", !s.personal);
      await page.locator("main").evaluate((main) => main.scrollTo(0, 0));
      await page.screenshot({ path: `${artifactDir}/owner-records.png` });
      await page.goto(`${BASE}/owner/shifts`);
      await page.getByRole("switch", { name: /알바생 기록/ }).click();
      await page.waitForFunction(
        () =>
          document
            .querySelector("[role=switch]")
            ?.getAttribute("aria-checked") === "false",
      );
      await page.goto(`${BASE}/owner/me`);
      await page
        .getByText("알바생 기록을 꺼 두었어요", { exact: false })
        .waitFor();
      check(
        "조회 꺼짐 구성원 선택 숨김",
        (await page.getByLabel("기록 구성원").count()) === 0,
      );
      check("점주 화면 런타임 오류 없음", errors.length === 0);
      await ctx.close();
    }
    {
      const { ctx, page, s } = await setup();
      s.shifts = [];
      await page.goto(`${BASE}/staff`);
      await page.getByRole("checkbox", { name: "머신 청소" }).waitFor();
      check(
        "근무조 0개 전체 묶음",
        await page.getByText("전체", { exact: true }).isVisible(),
      );
      check(
        "근무조 0개 칩 없음",
        (await page.getByLabel("근무조 선택").count()) === 0,
      );
      await page
        .getByRole("checkbox", { name: "머신 청소" })
        .evaluate((button) => {
          button.click();
          button.click();
        });
      await page.waitForFunction(
        () =>
          document
            .querySelector("[role=checkbox]")
            ?.getAttribute("aria-checked") === "true",
      );
      await page.waitForFunction(
        () =>
          document
            .querySelector("[role=checkbox]")
            ?.getAttribute("aria-busy") !== "true",
      );
      check("저장 중 같은 줄 중복 클릭 방지", s.calls.length === 1);
      await page.getByRole("checkbox", { name: "바닥 닦기" }).click();
      await page.getByTestId("checklist-complete").waitFor();
      check(
        "전체 체크 서버 자동 제출",
        Boolean(s.submission) && s.edits.length === 0,
      );
      await ctx.close();
    }
    {
      const { ctx, page, s } = await setup();
      await page.goto(`${BASE}/staff`);
      await page.getByRole("checkbox", { name: "머신 청소" }).waitFor();
      const old = s.date;
      s.previous = old;
      const date = new Date(`${old}T00:00:00Z`);
      date.setUTCDate(date.getUTCDate() + 1);
      s.date = date.toISOString().slice(0, 10);
      s.prevSubmitted = false;
      await page.evaluate(() =>
        document.dispatchEvent(new Event("visibilitychange")),
      );
      await page.getByText("어제 체크리스트", { exact: true }).waitFor();
      check("포커스 복귀 날짜 변경 어제 창", true);
      await ctx.close();
    }
    console.log(`PASS P5 browser assertions: ${passed}`);
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
