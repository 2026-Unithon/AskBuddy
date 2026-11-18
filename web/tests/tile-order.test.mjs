import assert from "node:assert/strict";
import { test } from "node:test";
import { moveTile, slotAt } from "../lib/tile-order.ts";

test("앞으로 옮기기", () => assert.deepEqual(moveTile(["a", "b", "c"], 2, 0), ["c", "a", "b"]));
test("뒤로 옮기기", () => assert.deepEqual(moveTile(["a", "b", "c"], 0, 2), ["b", "c", "a"]));
test("제자리면 그대로", () => assert.deepEqual(moveTile(["a", "b"], 1, 1), ["a", "b"]));
test("범위 밖이면 그대로", () => assert.deepEqual(moveTile(["a", "b"], 0, 5), ["a", "b"]));
// 타일 자리: 가운데 x, 위·아래 y. 들린 타일은 빼고 넘긴다
const two = [{ cx: 40, top: 0, bottom: 40 }, { cx: 120, top: 0, bottom: 40 }, { cx: 40, top: 50, bottom: 90 }];
test("두 줄로 감긴 타일에서 아래 줄 첫 자리", () => assert.equal(slotAt(two, 10, 70, true), 2));
test("윗줄 가운데보다 왼쪽이면 그 앞", () => assert.equal(slotAt(two, 100, 20, true), 1));
test("모든 타일보다 뒤면 맨 끝", () => assert.equal(slotAt(two, 200, 70, true), 3));
test("모든 줄보다 위면 맨 앞", () => assert.equal(slotAt(two, 300, -50, true), 0));
// 한 줄에 하나인 목록(번호·목록 모양): 같은 줄이면 x 가 아니라 타일 위·아래 절반으로 가른다
const list = [{ cx: 180, top: 0, bottom: 40 }, { cx: 180, top: 48, bottom: 88 }];
test("목록에서 마지막 타일 아래 절반이면 맨 끝", () => assert.equal(slotAt(list, 20, 80, false), 2));
test("목록에서 타일 위 절반이면 그 앞", () => assert.equal(slotAt(list, 20, 55, false), 1));
test("화살표 줄에 하나만 남아도 가운데 x 로 가른다", () => assert.equal(slotAt([{ cx: 40, top: 0, bottom: 40 }], 60, 10, true), 1));
