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

// 계획 6: 이미 만들어진 카드도 서버 규칙과 같게 보인다
const v = (sentence, step_order, value, temperature = null) => ({ sentence, step_order, value, unit: null, conditions: [], exceptions: [], variant: { temperature, size: null } });

test("'→' 문장에서 나뉜 단계는 단계 줄로 펼친다", () => {
  const s = "제조순서=컵(재료) → 얼음 → 액상";
  const { groups } = groupFacts([v(s, 1, "컵(재료)"), v(s, 2, "얼음"), v(s, 3, "액상")]);
  assert.equal(groups.length, 1);
  assert.equal(groups[0].label, "제조순서");
  assert.deepEqual(groups[0].segments, ["컵(재료)", "얼음", "액상"]);
});
test("메뉴 표 칸에 모두 붙은 1번은 단계가 아니라 번호를 숨긴다", () => {
  const { numbered } = groupFacts([v("구분=에이드", 1, "에이드"), v("금액=3,500원", 1, "3,500원")]);
  assert.equal(numbered, false);
});
test("한 문장 값 나열에 붙은 1·2번은 한 줄, 번호 없음", () => {
  const s = "재료=레몬퓨레 1.5P + 슈가시럽 1P";
  const { groups, numbered } = groupFacts([v(s, 1, "1.5"), v(s, 2, "1")]);
  assert.equal(groups.length, 1);
  assert.equal(groups[0].segments, null);
  assert.equal(numbered, false);
});
