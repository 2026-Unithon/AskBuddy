import assert from "node:assert/strict";
import { test } from "node:test";
import { addLine, draftFromView, editLine, isDirty, moveLine, needsParse, removeLine, toLineRequest } from "../components/owner/fact-card/line-draft.ts";

const fact = (id, sentence, extra = {}) => ({ fact_revision_id: id, fact_id: id * 10, position: id, sentence, assertion: sentence, subject: null, predicate: null,
  variant: { temperature: null, size: null }, value: null, unit: null, polarity: "AFFIRM", step_order: null, conditions: [], exceptions: [], requires: [],
  change_kind: null, previous_sentence: null, origins: [], edit_block: null, ...extra });
const view = { card_id: 1, version_id: 10, title: "합성 꿀 커피", review_status: "APPROVED", editable: true, review_items: [], blocks: [
  { block_id: "b1", kind: "STEPS", order: 1, variant: { temperature: null, size: null }, heading: "HOT",
    facts: [fact(1, "샷=2", { value: "2" }), fact(2, "얼음=가득"), fact(3, "물=붓기")],
    lines: [{ line_no: 1, text: "2샷", fact_revision_ids: [1] }, { line_no: 2, text: "얼음 가득", fact_revision_ids: [2] }, { line_no: 3, text: "물 붓기", fact_revision_ids: [3] }] }] };

test("그대로면 바뀐 것이 없다", () => assert.equal(isDirty(draftFromView(view)), false));

test("옮기면 줄 순서대로 lines 를 보내고 사실은 KEEP", () => {
  const d = moveLine(draftFromView(view), "b1", 2, 0);
  assert.equal(isDirty(d), true);
  const req = toLineRequest(d, new Map(), "k1");
  assert.deepEqual(req.blocks[0].lines.map((l) => l.text), ["물 붓기", "2샷", "얼음 가득"]);
  assert.deepEqual(req.blocks[0].items.map((i) => i.op), ["KEEP", "KEEP", "KEEP"]);
  assert.equal(req.blocks[0].heading, "HOT");
  assert.equal(req.expected_version_id, 10);
});

test("한 사실 줄을 고치면 분석 결과로 MODIFY 하고 줄은 그 사실을 인용한다", () => {
  const d = editLine(draftFromView(view), "b1:0", "3샷");
  const lines = needsParse(d);
  assert.deepEqual(lines.map((l) => [l.text, l.mode, l.base]), [["3샷", "MODIFY", 1]]);
  const parsed = new Map([["b1:0", [{ client_ref: "p1", block_kind: "NOTES", warnings: [], fact: { sentence: "3샷", polarity: "AFFIRM", value: "3", unit: null, conditions: [], exceptions: [], step_order: 5, variant: { temperature: null, size: null }, predicate: null } }]]]);
  const req = toLineRequest(d, parsed, "k2");
  const modify = req.blocks[0].items[0];
  assert.equal(modify.op, "MODIFY");
  assert.equal(modify.fact.step_order, null, "단계 여부는 원래 사실을 따른다");
  assert.deepEqual(req.blocks[0].lines[0], { text: "3샷", fact_revision_ids: [1], client_refs: [] });
});

test("줄을 빼면 그 줄만 인용한 사실은 지운다", () => {
  const d = removeLine(draftFromView(view), "b1:1");
  const req = toLineRequest(d, new Map(), "k3");
  assert.deepEqual(req.deleted_fact_revision_ids, [2]);
  assert.deepEqual(req.blocks[0].lines.map((l) => l.text), ["2샷", "물 붓기"]);
});

test("새 사실은 ADD 와 그 줄", () => {
  const proposal = { client_ref: "p1", block_kind: "NOTES", warnings: [], fact: { sentence: "꿀 2래들 투입", polarity: "AFFIRM", value: "2", unit: null, conditions: [], exceptions: [], step_order: null, variant: { temperature: null, size: null }, predicate: null } };
  const d = addLine(draftFromView(view), proposal);
  const req = toLineRequest(d, new Map(), "k4");
  const add = req.blocks.flatMap((b) => b.items).find((i) => i.op === "ADD");
  assert.ok(add);
  assert.ok(req.blocks.some((b) => b.lines.some((l) => l.text === "꿀 2래들 투입" && l.client_refs.includes(add.client_ref))));
});
