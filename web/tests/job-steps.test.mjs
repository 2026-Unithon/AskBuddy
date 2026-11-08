import { test } from "node:test";
import assert from "node:assert/strict";
import { jobStepIndex } from "../components/owner/job-steps-logic.ts";
test("서버 상태 → 단계", () => {
  assert.equal(jobStepIndex("QUEUED"), 1);
  assert.equal(jobStepIndex("EXTRACTING"), 1);
  assert.equal(jobStepIndex("CLASSIFYING"), 2);
  assert.equal(jobStepIndex("SUCCEEDED"), 3);
  assert.equal(jobStepIndex("PARTIAL"), 3);
});
import { jobStepLabel } from "../components/owner/job-steps-logic.ts";
test("끝난 단계는 과거형, 지금·남은 단계는 진행형", () => {
  assert.deepEqual([0, 1, 2].map((i) => jobStepLabel(i, 1)), ["올렸어요", "읽는 중", "카드 제작 중"]);
  assert.deepEqual([0, 1, 2].map((i) => jobStepLabel(i, 3)), ["올렸어요", "읽었어요", "카드 만들었어요"]);
});
