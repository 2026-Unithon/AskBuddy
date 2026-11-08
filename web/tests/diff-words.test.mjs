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
test("공백만 같은 것은 같은 것으로 치지 않는다(다 바뀐 글은 지운 것 다음 넣은 것)", () => {
  assert.deepEqual(diffWords("우유 200 얼음", "시럽 2 샷"), [
    { text: "우유 200 얼음", kind: "del" }, { text: "시럽 2 샷", kind: "add" },
  ]);
});
