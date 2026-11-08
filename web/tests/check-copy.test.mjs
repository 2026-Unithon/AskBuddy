import { test } from "node:test";
import assert from "node:assert/strict";
import { findMiddots } from "../scripts/check-copy.mjs";

test("화면 글의 중간점을 찾는다", () => {
  const src = `const a = "근거 · 1쪽";\nexport const C = () => <p>확인해 주세요 · 2</p>;\nconst t = \`출처 · \${x}\`;`;
  assert.deepEqual(findMiddots(src, "a.tsx").map((f) => f.line), [1, 2, 3]);
});
test("주석과 중간점 없는 글은 무시한다", () => {
  const src = `// 오늘 매장 · 카드 탭\n/* 근거 · 1쪽 */\nconst a = "정리 끝!";`;
  assert.deepEqual(findMiddots(src, "a.tsx"), []);
});
test("엔티티와 이스케이프 중간점도 찾는다", () => {
  const src = `export const A = () => <p>근거 &middot; 1</p>;\nconst b = "근거 \\u00B7 1";\nexport const C = () => <p>a &#183; b</p>;`;
  assert.deepEqual(findMiddots(src, "a.tsx").map((f) => f.line), [1, 2, 3]);
});
