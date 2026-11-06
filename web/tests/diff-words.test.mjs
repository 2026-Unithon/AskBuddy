import { test } from "node:test";
import assert from "node:assert/strict";
import { diffWords } from "../lib/diff-words.ts";
test("바뀐 낱말만 del/add", () => {
  assert.deepEqual(diffWords("ICE 시럽 2펌프", "ICE 시럽 3펌프"), [
    { text: "ICE 시럽 ", kind: "same" }, { text: "2펌프", kind: "del" }, { text: "3펌프", kind: "add" },
  ]);
});
test("같으면 하나, 비면 전부 add", () => {
  assert.deepEqual(diffWords("우유 200", "우유 200"), [{ text: "우유 200", kind: "same" }]);
  assert.deepEqual(diffWords("", "새 내용"), [{ text: "새 내용", kind: "add" }]);
});
