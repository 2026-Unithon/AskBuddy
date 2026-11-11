// 화면 검사 공용 실행기. 합성 API(ui_fixture.cjs)만 쓴다.
// 실행: next start -p 3011 을 띄운 뒤 NODE_PATH=<playwright> node api/scripts/<검사>.cjs [이름 앞부분]
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const { syntheticApi } = require('./ui_fixture.cjs');

const BASE = process.env.UI_BASE || 'http://127.0.0.1:3011';
const here = (page) => { const u = new URL(page.url()); return u.pathname + u.search; };
const opened = [];

async function open(browser, role, url, { viewport = { width: 390, height: 844 }, overrides, touch = false } = {}) {
  const api = syntheticApi(role, overrides);
  opened.push(api);
  // touch: 폰처럼 손가락 입력(hasTouch, isMobile). 당겨서 새로고침 같은 몸짓 검사용
  const ctx = await browser.newContext({ viewport, locale: 'ko-KR', ...(touch ? { hasTouch: true, isMobile: true } : {}) });
  await ctx.route('http://localhost:8000/**', api.handler);
  // 처음 한 번 뜨는 안내(코치마크)는 기본으로 끈다. 안내를 보는 테스트만 overrides.coach 로 켠다
  if (!overrides?.coach) {
    await ctx.addInitScript(() => {
      const keys = ['owner-home', 'dev', 'staff-home', 'owner-notifications'];
      try { for (const k of keys) localStorage.setItem(`askbuddy:coach:${k}`, 'done'); } catch {}
    });
  }
  // 계획 8: 푸시 상태 흉내. 아이폰, 홈 화면 앱, 권한, 푸시 API 유무를 브라우저 쪽에서 바꾼다(실제 푸시 서비스는 부르지 않는다)
  if (overrides?.pushEnv) {
    await ctx.addInitScript((env) => {
      const e = { ios: false, standalone: false, permission: 'default', hasPushApi: true, ...env };
      let subscription = null;
      let permission = e.permission;
      const make = () => ({ endpoint: 'https://push.example.invalid/1', toJSON() { return { endpoint: this.endpoint, keys: { p256dh: 'p', auth: 'a' } }; },
        unsubscribe: async () => { subscription = null; return true; } });
      const registration = { pushManager: { getSubscription: async () => subscription, subscribe: async () => (subscription = make()) } };
      if (e.ios) Object.defineProperty(navigator, 'userAgent', { get: () => 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) AppleWebKit/605.1.15 Version/18.1 Mobile/15E148 Safari/604.1' });
      if (e.standalone) Object.defineProperty(navigator, 'standalone', { get: () => true });
      if (e.hasPushApi) {
        window.PushManager = function PushManager() {};
        Object.defineProperty(navigator, 'serviceWorker', { get: () => ({ register: async () => registration, ready: Promise.resolve(registration), getRegistration: async () => registration }) });
      } else {
        delete window.PushManager;
      }
      window.Notification = { get permission() { return permission; }, requestPermission: async () => (permission === 'default' ? (permission = 'granted') : permission) };
    }, overrides.pushEnv);
  }
  const page = await ctx.newPage();
  page.on('pageerror', (error) => api.misses.push(`pageerror ${error.message}`));
  await page.goto(BASE + url);
  await page.waitForLoadState('networkidle');
  return { ctx, page, api };
}
// 앱 뒤로 버튼. 화면마다 글자(카드·직원 질문·뒤로)가 달라 표시 속성으로 찾는다.
const back = (page) => page.locator('[data-back]').first();
async function to(page, path) { await page.waitForURL((u) => u.pathname + u.search === path, { timeout: 5000 }); }
// 폰 뒤로가기. 앱 밖(첫 화면 이전)으로 나가면 about:blank 가 된다.
async function phoneBack(page) { await page.goBack({ waitUntil: 'networkidle' }).catch(() => null); return page.url().startsWith('about:') ? 'about:blank' : here(page); }

function createSuite(label) {
  const cases = [];
  const test = (name, fn) => cases.push([name, fn]);
  const run = () => (async () => {
    const only = process.argv[2];
    const browser = await chromium.launch({ headless: true });
    let passed = 0;
    for (const [name, fn] of cases) {
      if (only && !name.startsWith(only)) continue;
      await fn(browser);
      // fixture 가 모르는 API 를 부른 화면은 실패로 본다(합성 데이터가 화면을 다 덮는지)
      for (const api of opened.splice(0)) assert.deepEqual(api.misses, [], `${name} 모르는 API: ${api.misses.join(', ')}`);
      passed++; console.log(`PASS ${label}`, name);
    }
    await browser.close();
    console.log(`${label} ${passed} passed`);
  })().catch((error) => { console.error(error); process.exit(1); });
  return { test, run };
}

module.exports = { createSuite, open, back, to, phoneBack, here, BASE };
