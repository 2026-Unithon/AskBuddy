import assert from "node:assert/strict";
import { test } from "node:test";
import { priceOfFact, splitPrice } from "../lib/card-price.ts";

// 금액은 칸 이름(금액·판매 가격…)이 제각각이라 단위 칸 하나로 고른다(2026-11-18 실측)
test("단위가 원인 수치 사실이 금액", () => assert.equal(priceOfFact({ value: "2000", unit: "원" }), "2,000원"));
test("단위가 다른 사실은 금액 아님", () => assert.equal(priceOfFact({ value: "120", unit: "ml" }), null));
test("값 글(단위 없음)은 금액 아님", () => assert.equal(priceOfFact({ value: "레귤러 머그", unit: null }), null));

const line = (line_no, text, price = null) => ({ line_no, text, price });

test("금액 줄은 본문에서 빠지고 제목 옆 금액 하나로", () => {
  const out = splitPrice([
    { key: "a", kind: "NOTES", heading: null, lines: [line(1, "물 120ml"), line(2, "금액 2,000원(₩2,000)", "2,000원")] },
  ]);
  assert.deepEqual(out.price, ["2,000원"]);
  assert.deepEqual(out.blocks[0].lines.map((l) => l.text), ["물 120ml"]);
});

test("규격마다 금액이 다르면 구역 제목을 붙여 나란히", () => {
  const out = splitPrice([
    { key: "h", kind: "NOTES", heading: "HOT", lines: [line(1, "금액 1,500원", "1,500원")] },
    { key: "i", kind: "NOTES", heading: "ICE", lines: [line(1, "금액 2,000원", "2,000원"), line(2, "얼음 가득")] },
  ]);
  assert.deepEqual(out.price, ["HOT 1,500원", "ICE 2,000원"]);
  // 금액만 있던 구역은 통째로 빠진다
  assert.deepEqual(out.blocks.map((b) => b.key), ["i"]);
});

test("규격마다 금액이 같으면 하나만", () => {
  const out = splitPrice([
    { key: "h", kind: "NOTES", heading: "HOT", lines: [line(1, "금액 1,500원", "1,500원")] },
    { key: "i", kind: "NOTES", heading: "ICE", lines: [line(1, "금액 1,500원", "1,500원")] },
  ]);
  assert.deepEqual(out.price, ["1,500원"]);
});

test("금액이 없으면 그대로", () => {
  const blocks = [{ key: "a", kind: "STEPS", heading: null, lines: [line(1, "2샷 내리기")] }];
  const out = splitPrice(blocks);
  assert.deepEqual(out.price, []);
  assert.deepEqual(out.blocks, blocks);
});
