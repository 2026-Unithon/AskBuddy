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
