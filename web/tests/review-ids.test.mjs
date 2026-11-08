import { test } from "node:test";
import assert from "node:assert/strict";
import { reviewCardIds } from "../lib/review-ids.ts";

test("검수 필요 카드와 제안 카드의 합집합, 삭제된 카드의 제안은 빼고", () => {
  const ids = reviewCardIds([{ card_id: 3 }], [
    { target_card_id: 1, target_review_status: "APPROVED" },
    { target_card_id: 3, target_review_status: "NEEDS_REVIEW" },
    { target_card_id: 7, target_review_status: "EXCLUDED" },
    { target_card_id: null },
  ]);
  assert.deepEqual([...ids].sort(), [1, 3]);
});
