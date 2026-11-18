import assert from "node:assert/strict";
import { test } from "node:test";
import { lineLayout } from "../lib/line-layout.ts";

test("16자 넘는 줄이 하나라도 있으면 번호 목록", () => assert.equal(lineLayout(["2샷", "얼음 가득", "꿀 2래들 투입 (샷잔 1/4선)"], "STEPS"), "NUMBERED"));
test("모두 짧으면 화살표", () => assert.equal(lineLayout(["2샷", "얼음 가득", "물 붓기"], "STEPS"), "ARROW"));
test("순서 아닌 구역은 목록", () => assert.equal(lineLayout(["24시간 보관"], "NOTES"), "LIST"));
test("16자 딱 맞으면 화살표", () => assert.equal(lineLayout(["가".repeat(16)], "STEPS"), "ARROW"));
import { headingShown } from "../lib/line-layout.ts";
// 같은 제목 구역이 이어지면 제목은 처음 한 번만(2026-11-17 실측: HOT 이 두 번 보였다)
test("바로 앞 구역과 제목이 같으면 숨김", () => assert.deepEqual(
  ["HOT", "HOT", "ICE", null, null].map((_, i, all) => headingShown(all.map((h) => ({ heading: h })), i)),
  [true, false, true, false, false]));
