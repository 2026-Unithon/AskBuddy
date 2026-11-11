import assert from "node:assert/strict";
import { test } from "node:test";
import { pushState } from "../lib/push-state.ts";

const base = { hasPushApi: true, ios: false, standalone: false, permission: "default", subscribed: false, configured: true };
test("아이폰 Safari 탭은 홈 화면에 추가해야 한다", () => {
  assert.equal(pushState({ ...base, ios: true, hasPushApi: false }), "IOS_NEEDS_HOME");
  assert.equal(pushState({ ...base, ios: true, hasPushApi: true, standalone: false }), "IOS_NEEDS_HOME");
});
test("홈 화면 앱이면 아이폰도 켤 수 있다", () => assert.equal(pushState({ ...base, ios: true, standalone: true }), "OFF"));
test("푸시 API 가 없으면 안 된다", () => assert.equal(pushState({ ...base, hasPushApi: false }), "UNSUPPORTED"));
test("서버 키가 없으면 준비 안 됨", () => assert.equal(pushState({ ...base, configured: false }), "NOT_CONFIGURED"));
test("거절했으면 폰 설정", () => assert.equal(pushState({ ...base, permission: "denied" }), "DENIED"));
test("허락하고 구독 중이면 켜짐", () => assert.equal(pushState({ ...base, permission: "granted", subscribed: true }), "ON"));
test("허락만 하고 구독이 없으면 꺼짐", () => assert.equal(pushState({ ...base, permission: "granted" }), "OFF"));
