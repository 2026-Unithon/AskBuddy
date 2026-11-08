import { test } from "node:test";
import assert from "node:assert/strict";
import { sourceErrorText, SOURCE_ERROR_FALLBACK } from "../lib/source-error.ts";

test("개발자용 예외 문장은 쉬운 말로", () => {
  assert.equal(sourceErrorText({ code: "EXTRACTION_FAILED", message: "RuntimeError: 카카오톡 대화를 한 건도 파싱하지 못했다. '대화 내용 내보내기' 로 받은 txt 인지 확인하라" }), SOURCE_ERROR_FALLBACK);
  assert.equal(sourceErrorText({ code: "EXTRACTION_FAILED", message: "source_kakao 행이 없다. /ingest/sources 로 등록했는지 확인하라" }), SOURCE_ERROR_FALLBACK);
});
test("사장님에게 쓴 문장(해요체)은 그대로", () => {
  assert.equal(sourceErrorText({ code: "FILE_TOO_LARGE", message: "파일이 너무 커서 올릴 수 없어요." }), "파일이 너무 커서 올릴 수 없어요.");
});
test("알려진 코드는 정해 둔 말", () => {
  assert.equal(sourceErrorText({ code: "PARTIAL_RETRY_UNAVAILABLE", message: "x" }), "일부만 읽었어요. 나머지는 다시 시도할 수 없어요.");
});
test("이유가 없으면 기본 문구", () => {
  assert.equal(sourceErrorText(null), SOURCE_ERROR_FALLBACK);
});
