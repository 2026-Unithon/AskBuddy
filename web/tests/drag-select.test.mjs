import { test } from "node:test";
import assert from "node:assert/strict";
import { rangeSelect } from "../lib/drag-select.ts";

const order = [1, 2, 3, 4, 5];
const ids = (set) => [...set].sort((a, b) => a - b);

test("안 고른 카드에서 끌기 시작하면 지나간 범위를 더한다", () => {
  assert.deepEqual(ids(rangeSelect(order, 2, 4, new Set([5]))), [2, 3, 4, 5]);
});
test("고른 카드에서 시작하면 지나간 범위를 뺀다", () => {
  assert.deepEqual(ids(rangeSelect(order, 2, 4, new Set([1, 2, 3, 4, 5]))), [1, 5]);
});
test("되돌아 끌면 지나쳤던 칸은 처음 상태로", () => {
  const base = new Set([4]);
  rangeSelect(order, 1, 5, base);
  assert.deepEqual(ids(rangeSelect(order, 1, 2, base)), [1, 2, 4]);
});
test("위로 끌어도 같은 범위", () => {
  assert.deepEqual(ids(rangeSelect(order, 4, 2, new Set())), [2, 3, 4]);
});
test("목록에 없는 카드면 처음 상태 그대로", () => {
  assert.deepEqual(ids(rangeSelect(order, 9, 2, new Set([1]))), [1]);
});
