import { test } from "node:test";
import assert from "node:assert/strict";
import { visibleDetail } from "../lib/api-error-text.ts";

test("서버 기본 영어 문구(Not Found 등)는 보이지 않는다", () => {
  for (const detail of ["Not Found", "Method Not Allowed", "Internal Server Error", "Unprocessable Entity"]) {
    assert.equal(visibleDetail(detail), null, detail);
  }
});

test("우리 서버의 한국어 오류 문구는 그대로", () => {
  assert.equal(visibleDetail("이 사진은 쓸 수 없어요."), "이 사진은 쓸 수 없어요.");
  assert.equal(visibleDetail("접근할 수 있는 매장이 없습니다."), "접근할 수 있는 매장이 없습니다.");
});

test("빈 문구는 없음", () => {
  assert.equal(visibleDetail(""), null);
});
