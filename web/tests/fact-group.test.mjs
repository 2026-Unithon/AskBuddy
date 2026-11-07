import { test } from "node:test";
import assert from "node:assert/strict";
import { groupFacts } from "../components/owner/fact-card/fact-group.ts";

const f = (sentence, step_order = null, value = null) => ({ sentence, step_order, value, unit: null, conditions: [], exceptions: [] });

test("한 문장에서 값마다 나뉜 사실은 한 줄로 묶는다", () => {
  const s = "토핑=휘핑 + 오레오 + 쿠키분태";
  const { groups } = groupFacts([f(s, null, "휘핑"), f(s, null, "오레오"), f(s, null, "쿠키분태")]);
  assert.equal(groups.length, 1);
});
test("값 없는 같은 문장이 다른 단계에 있으면 단계를 지우지 않는다", () => {
  const { groups, numbered } = groupFacts([f("컵에 담는다", 1), f("잘 저어 준다", 2), f("시럽을 넣는다", 3), f("잘 저어 준다", 4)]);
  assert.equal(groups.length, 4);
  assert.equal(numbered, true);
});
test("여러 단계가 한 문장이면 한 줄, 번호는 숨긴다", () => {
  const s = "제조순서=블랜더 → 믹싱 → 토핑";
  const { groups, numbered } = groupFacts([f(s, 1, "블랜더"), f(s, 2, "믹싱"), f(s, 3, "토핑")]);
  assert.equal(groups.length, 1);
  assert.equal(numbered, false);
});
