import { test } from "node:test";
import assert from "node:assert/strict";
import { fieldsOf, isModified } from "../components/owner/fact-card/use-fact-edit-draft.ts";

const row = {
  fact_revision_id: 1, sentence: "컵=16", assertion: "컵은 16온즈를 써요", polarity: "AFFIRMATIVE",
  value: "16", unit: null, conditions: [], exceptions: [], step_order: null,
  variant: { temperature: null, size: null }, predicate: null,
};

test("정리한 글을 보여 줘도 아무것도 안 고쳤으면 바뀐 게 아니다", () => {
  assert.equal(isModified({ key: "r1", base: row, clientRef: null, fields: fieldsOf(row), slot: null }), false);
});

test("정리한 글을 고치면 바뀐 것이다", () => {
  const fields = { ...fieldsOf(row), sentence: "컵은 20온즈를 써요" };
  assert.equal(isModified({ key: "r1", base: row, clientRef: null, fields, slot: null }), true);
});
