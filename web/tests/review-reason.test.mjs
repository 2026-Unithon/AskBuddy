import { test } from "node:test";
import assert from "node:assert/strict";
import { reviewReasonText } from "../lib/review-reason.ts";

test("사유 코드는 사람 말로, 문장은 그대로, 모르는 코드는 일반 문구", () => {
  assert.match(reviewReasonText("FACT_CONFLICT_OPEN"), /서로 다른 값/);
  assert.match(reviewReasonText("FALLBACK:timeout"), /자동으로 정리하지 못한/);
  assert.equal(reviewReasonText("역세척 횟수가 두 가지예요"), "역세척 횟수가 두 가지예요");
  assert.doesNotMatch(reviewReasonText("SOMETHING_NEW"), /SOMETHING/);
  assert.doesNotMatch(reviewReasonText(null), /null/);
});
