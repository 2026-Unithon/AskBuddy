import { test } from "node:test";
import assert from "node:assert/strict";
import { cardKind } from "../lib/card-kind.ts";

test("종류가 있으면 종류를 따른다", () => {
  assert.equal(cardKind({ name: "음료 레시피", kind: "TASK" }), "TASK");
  assert.equal(cardKind({ name: "오픈 마감", kind: "RECIPE" }), "RECIPE");
});
test("종류가 없으면 이름 규칙, 아니면 할 일", () => {
  assert.equal(cardKind({ name: "메뉴 제조", kind: null }), "RECIPE");
  assert.equal(cardKind({ name: "재고 위치" }), "TASK");
  assert.equal(cardKind(null), "TASK");
});
