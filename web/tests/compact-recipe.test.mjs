import { test } from "node:test";
import assert from "node:assert/strict";
import { compactRecipe } from "../components/owner/fact-card/fact-group.ts";

const v = (temperature) => ({ temperature, size: null });
const f = (sentence, step_order = null, value = null) => ({ sentence, step_order, value, unit: null, conditions: [], exceptions: [] });
const block = (kind, temperature, facts) => ({ kind, variant: v(temperature), facts });
const steps = (temperature, sentence, names) => block("STEPS", temperature, names.map((n, i) => f(sentence, i + 1, n)));

// 표에서 뽑힌 레시피(합성): 칸마다 '이름=값' 사실, 제조순서는 화살표 한 줄
const blocks = [
  block("QUANTITIES", "HOT", [f("구분=바닐라", null, "바닐라"), f("금액=4,500원"), f("컵=16", null, "16"), f("액상(텀블러)=스팀우유250ml(70°C)", null, "250"), f("재료(시럽 / 파우더 / 베이스)=바닐라시럽 30ml", null, "30")]),
  block("QUANTITIES", "ICE", [f("구분=바닐라"), f("금액=4,500원"), f("컵=20"), f("얼음=가득"), f("액상(텀블러)=우유가득(200ml)"), f("재료(시럽 / 파우더 / 베이스)=바닐라시럽 20ml (컵 밑선)")]),
  steps("HOT", "제조순서=컵 → 재료 → 액상", ["컵", "재료", "액상"]),
  steps("ICE", "제조순서=컵 → 재료 → 얼음 → 액상", ["컵", "재료", "얼음", "액상"]),
  block("NOTES", "HOT", [f("블렌더=x")]),
];

test("규격마다 순서 한 줄에 값을 넣고, 나머지는 아래 한 줄", () => {
  const recipe = compactRecipe(blocks);
  assert.deepEqual(recipe, {
    price: "4,500원",
    sections: [
      { heading: "HOT", steps: [{ text: "컵", note: "16온즈" }, { text: "바닐라시럽 30ml", note: null }, { text: "스팀우유250ml(70°C)", note: null }], extras: [] },
      { heading: "ICE", steps: [{ text: "컵", note: "20온즈" }, { text: "바닐라시럽 20ml (컵 밑선)", note: null }, { text: "얼음 가득", note: null }, { text: "우유가득(200ml)", note: null }], extras: [] },
    ],
  });
});

test("규격마다 값이 다르면 가격도 규격마다", () => {
  const changed = blocks.map((b) => (b.variant.temperature === "ICE" && b.kind === "QUANTITIES" ? { ...b, facts: b.facts.map((x) => (x.sentence.startsWith("금액") ? f("금액=5,000원") : x)) } : b));
  assert.equal(compactRecipe(changed).price, "HOT 4,500원, ICE 5,000원");
});

test("이름=값 사실이 대부분이 아니면 줄이지 않는다", () => {
  assert.equal(compactRecipe([block("NOTES", null, [f("마감 때 머신 청소를 한다."), f("원두는 창고 왼쪽 선반에 둔다.")])]), null);
});

test("화살표 없는 단계는 번호 순서대로 이어 붙인다", () => {
  const recipe = compactRecipe([block("QUANTITIES", null, [f("샷=2"), f("시럽=2펌프")]), block("STEPS", null, [f("시럽을 넣는다", 2), f("샷을 내린다", 1)])]);
  assert.deepEqual(recipe.sections, [{ heading: null, steps: [{ text: "샷을 내린다", note: null }, { text: "시럽을 넣는다", note: null }], extras: [{ label: "샷", value: "2" }, { label: "시럽", value: "2펌프" }] }]);
});
