import { test } from "node:test";
import assert from "node:assert/strict";
import { nextStack, enterOf, readStack, NAV_STACK_LIMIT } from "../lib/nav-stack.ts";

test("push 는 쌓고 같은 주소 반복은 무시한다", () => {
  assert.deepEqual(nextStack(["/owner"], "/owner/cards/1", "push"), ["/owner", "/owner/cards/1"]);
  assert.deepEqual(nextStack(["/owner", "/owner/cards/1"], "/owner/cards/1", "push"), ["/owner", "/owner/cards/1"]);
});
test("replace 는 맨 위만 바꾼다", () => {
  assert.deepEqual(nextStack(["/owner", "/owner/add"], "/owner/jobs/7", "replace"), ["/owner", "/owner/jobs/7"]);
});
test("pop 은 바로 아래와 같으면 꺼내고, 다르면(앞으로 가기) 쌓는다", () => {
  assert.deepEqual(nextStack(["/owner", "/owner/cards/1"], "/owner", "pop"), ["/owner"]);
  assert.deepEqual(nextStack(["/owner"], "/owner/cards/1", "pop"), ["/owner", "/owner/cards/1"]);
});
test("스택은 최대 길이를 넘지 않는다", () => {
  let stack = ["/0"];
  for (let i = 1; i <= NAV_STACK_LIMIT + 5; i++) stack = nextStack(stack, `/${i}`, "push");
  assert.equal(stack.length, NAV_STACK_LIMIT);
  assert.equal(stack.at(-1), `/${NAV_STACK_LIMIT + 5}`);
});
test("방향", () => {
  assert.equal(enterOf("push"), "forward");
  assert.equal(enterOf("pop"), "back");
  assert.equal(enterOf("replace"), "fade");
  assert.equal(enterOf("initial"), "initial");
});
test("readStack: 저장 맨 위가 지금 주소면 이어 쓴다(새로고침)", () => {
  const storage = { getItem: () => JSON.stringify(["/owner", "/owner/cards/1"]) };
  assert.deepEqual(readStack(storage, "/owner/cards/1"), ["/owner", "/owner/cards/1"]);
  assert.deepEqual(readStack(storage, "/staff"), ["/staff"]);
});
test("readStack 이 던지거나 깨진 값이면 빈 스택(지금 주소 하나)", () => {
  assert.deepEqual(readStack({ getItem: () => { throw new Error("blocked"); } }, "/owner"), ["/owner"]);
  assert.deepEqual(readStack({ getItem: () => "{oops" }, "/owner"), ["/owner"]);
  assert.deepEqual(readStack(null, "/owner"), ["/owner"]);
});
test("pop 대상이 더 아래에 있으면 그 자리까지 자른다(브라우저 뒤로를 앞으로로 착각하지 않는다)", () => {
  assert.deepEqual(nextStack(["/a", "/b", "/c"], "/a", "pop"), ["/a"]);
  assert.deepEqual(nextStack(["/a", "/b", "/a", "/c"], "/a", "pop"), ["/a", "/b", "/a"]);
});
