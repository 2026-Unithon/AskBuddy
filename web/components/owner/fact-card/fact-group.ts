// 보기 모드 사실 묶기. node --test 가 바로 읽도록 값 import 없이 둔다(타입만).
import type { FactFields } from "@/lib/api";

type Row = Pick<FactFields, "sentence" | "step_order" | "value">;

export type FactGroup<T extends Row = FactFields> = {
  key: string;
  fields: T[];
  stepOrder: number | null;
  /** '제조순서=A → B → C' 처럼 한 문장에 단계가 이어진 줄이면 앞 이름('제조순서')과 단계들 */
  label: string | null;
  segments: string[] | null;
};

// 서버 card_plan._SEQUENCE_MARK 와 같다
const SEQUENCE = /→|->|⇒|➔/;

/** 화살표로 이어진 문장을 단계로 나눈다. 단계 수가 사실의 가장 큰 번호보다 적으면 나누지 않는다. */
function splitSteps(sentence: string, maxOrder: number): { label: string | null; segments: string[] } | null {
  if (!SEQUENCE.test(sentence)) return null;
  let rest = sentence.trim();
  let label: string | null = null;
  const eq = rest.indexOf("=");
  if (eq > 0 && eq < rest.search(SEQUENCE)) {
    label = rest.slice(0, eq).trim();
    rest = rest.slice(eq + 1);
  }
  const segments = rest.split(SEQUENCE).map((s) => s.trim()).filter(Boolean);
  return segments.length >= Math.max(2, maxOrder) ? { label, segments } : null;
}

/**
 * 보기 모드에서 같은 문장에서 나온 사실들을 한 줄로 묶는다(한 문장에 값이 여러 개면 사실이 값마다 나뉘어 저장된다).
 * 값 없는 같은 문장이 다른 단계에 다시 나오면 진짜 반복 단계라 따로 둔다.
 * 번호는 단계가 진짜일 때만 보인다(서버 normalize_step_orders 와 같은 규칙: 같은 번호를 다른 문장과 나눠 쓰거나,
 * 화살표 없는 한 문장에서 번호가 여러 개면 단계가 아니다).
 */
export function groupFacts<T extends Row>(rows: T[]): { groups: FactGroup<T>[]; numbered: boolean } {
  const byKey = new Map<string, FactGroup<T>>();
  const groups: FactGroup<T>[] = [];
  for (const fields of rows) {
    const key = fields.value ? fields.sentence.trim() : `${fields.sentence.trim()}#${fields.step_order ?? ""}`;
    const found = byKey.get(key);
    if (found) {
      found.fields.push(fields);
      if (found.stepOrder !== fields.step_order) found.stepOrder = null;
      continue;
    }
    const group: FactGroup<T> = { key, fields: [fields], stepOrder: fields.step_order, label: null, segments: null };
    byKey.set(key, group);
    groups.push(group);
  }
  for (const group of groups) {
    const orders = new Set(group.fields.map((f) => f.step_order).filter((o): o is number => o !== null));
    if (orders.size > 1) {
      const split = splitSteps(group.fields[0].sentence, Math.max(...orders));
      if (split) {
        group.label = split.label;
        group.segments = split.segments;
      }
    }
  }
  const orders = groups.map((g) => g.stepOrder);
  const numbered = orders.every((o) => o !== null) && new Set(orders).size === orders.length;
  return { groups, numbered };
}

// ── 레시피 한눈에 보기(2026-11-08 사용자 스케치) ──
// 표에서 뽑힌 레시피는 칸마다 '이름=값' 사실이라, 그대로 줄마다 보이면 같은 말이 길게 늘어진다.
// 규격(HOT/ICE)마다 제조 순서 한 줄에 칸 값을 끼워 넣고(컵 → 원액 75ml → 우유가득), 쓰이지 않은 칸만 아래 한 줄로 둔다.

type RecipeRow = Pick<FactFields, "sentence" | "step_order">;
type RecipeBlock = { kind: string; variant: { temperature: string | null; size: string | null }; facts: RecipeRow[] };
/** note: 단계 이름과 같은 칸의 숫자 값(컵 16). 단계 바로 아래 작게 붙인다 */
export type CompactStep = { text: string; note: string | null };
export type CompactSection = { heading: string | null; steps: CompactStep[]; extras: { label: string; value: string }[] };
export type CompactRecipe = { price: string | null; sections: CompactSection[] };

const PRICE = /^(금액|가격|판매가)$/;
const DROP_LABEL = /^(구분)$/;
const EMPTY_VALUE = /^(x|X|-|없음|✕|×)$/;
const STEP_LABEL = /순서|방법/;
// 숫자만 적힌 칸의 단위. 매장 표는 컵 크기를 숫자만 적는다(카페 컵은 HOT, ICE 모두 온즈)
const NUMBER_UNIT: Record<string, string> = { 컵: "온즈" };

const norm = (label: string) => label.replace(/\([^)]*\)/g, "").replace(/\s+/g, "");
function split(sentence: string): { label: string; text: string } | null {
  const eq = sentence.indexOf("=");
  if (eq <= 0) return null;
  return { label: sentence.slice(0, eq).trim(), text: sentence.slice(eq + 1).trim() };
}

/** 이름=값 사실이 대부분인 카드면 한눈에 보기, 아니면 null(원래 보기). */
/** pending: 아직 고르지 않은 칸 이름(검수 고르기). 그 칸은 값을 보이지 않고 '골라 주세요'로 둔다 */
export const PICK_NOTE = "골라 주세요";
export function compactRecipe(blocks: RecipeBlock[], pending: Set<string> = new Set()): CompactRecipe | null {
  const waiting = new Set([...pending].map(norm));
  type Attr = { label: string; text: string };
  const order: string[] = [];
  const headingOf = new Map<string, string | null>();
  const attrs = new Map<string, Map<string, Attr>>();
  const stepRows = new Map<string, RecipeRow[]>();
  let plain = 0;
  let pairs = 0;
  for (const block of blocks) {
    const heading = [block.variant.temperature, block.variant.size].filter(Boolean).join(" ") || null;
    const key = heading ?? "";
    if (!headingOf.has(key)) {
      headingOf.set(key, heading);
      order.push(key);
    }
    for (const fact of block.facts) {
      const pair = split(fact.sentence);
      if (fact.step_order !== null || block.kind === "STEPS" || (pair && STEP_LABEL.test(pair.label))) {
        stepRows.set(key, [...(stepRows.get(key) ?? []), fact]);
        continue;
      }
      if (!pair) {
        plain += 1;
        continue;
      }
      pairs += 1;
      const map = attrs.get(key) ?? new Map<string, Attr>();
      if (!map.has(norm(pair.label))) map.set(norm(pair.label), pair);
      attrs.set(key, map);
    }
  }
  if (pairs === 0 || pairs < (pairs + plain) * 0.6) return null;

  // 가격: 규격마다 같으면 하나, 다르면 규격마다
  const prices = order.map((key) => [headingOf.get(key), [...(attrs.get(key)?.values() ?? [])].find((a) => PRICE.test(norm(a.label)))?.text] as const).filter(([, p]) => p);
  const price = prices.length === 0 ? null : new Set(prices.map(([, p]) => p)).size === 1 ? prices[0][1]! : prices.map(([h, p]) => (h ? `${h} ${p}` : p)).join(", ");

  const common = attrs.get("");
  const sections: CompactSection[] = [];
  for (const key of order) {
    if (key === "" && order.length > 1 && !stepRows.has("")) continue;
    const own = new Map([...(key ? (common ?? []) : []), ...(attrs.get(key) ?? [])]);
    const used = new Set<string>();
    // 단계: 화살표 한 줄이면 나눠 쓰고, 아니면 번호 순서대로 문장
    const rows = stepRows.get(key) ?? [];
    const arrow = rows.find((row) => SEQUENCE.test(row.sentence));
    const raw = arrow
      ? (split(arrow.sentence)?.text ?? arrow.sentence).split(SEQUENCE).map((s) => s.trim()).filter(Boolean)
      : [...new Map([...rows].sort((a, b) => (a.step_order ?? 0) - (b.step_order ?? 0)).map((row) => [row.sentence, split(row.sentence)?.text ?? row.sentence])).values()];
    const steps = raw.map((step): CompactStep => {
      if (waiting.has(norm(step))) {
        used.add(norm(step));
        return { text: step, note: PICK_NOTE };
      }
      const attr = own.get(norm(step));
      if (!attr || EMPTY_VALUE.test(attr.text)) return { text: step, note: null };
      used.add(norm(step));
      // 숫자뿐인 값(컵=16)은 단계 이름을 두고 아래에 붙이고, 나머지는 값으로 바꾼다.
      // '가득'처럼 짧은 값만 남으면 무엇인지 모르니 이름을 붙인다
      if (/^[\d.,\s]+$/.test(attr.text)) return { text: step, note: `${attr.text.trim()}${NUMBER_UNIT[norm(attr.label)] ?? ""}` };
      return { text: attr.text.length <= 3 && !/\d/.test(attr.text) ? `${norm(attr.label)} ${attr.text}` : attr.text, note: null };
    });
    const extras = [...own.entries()]
      .filter(([label, a]) => !used.has(label) && !PRICE.test(label) && !DROP_LABEL.test(label) && !EMPTY_VALUE.test(a.text))
      .map(([label, a]) => ({ label, value: waiting.has(label) ? PICK_NOTE : a.text }));
    if (steps.length || extras.length) sections.push({ heading: headingOf.get(key) ?? null, steps, extras });
  }
  return { price, sections };
}

/**
 * 문장에서 굵게 할 값 자리. 값+단위가 문장에 있으면 그 자리(앞에서부터), 단위 없이 값만 있으면 마지막 자리.
 * 숫자 값은 더 큰 숫자 안('12시'의 2)에서 찾지 않는다. 이미 잡은 자리와 겹치지 않는다.
 */
export function valueSpans(sentence: string, values: { value: string | null; unit: string | null }[]): [number, number][] {
  const spans: [number, number][] = [];
  const overlaps = (a: number, b: number) => spans.some(([x, y]) => a < y && b > x);
  const isDigit = (ch: string | undefined) => ch !== undefined && /[0-9]/.test(ch);
  const places = (needle: string) => {
    const found: number[] = [];
    const numeric = /^[0-9]/.test(needle);
    for (let at = sentence.indexOf(needle); at >= 0; at = sentence.indexOf(needle, at + 1)) {
      const end = at + needle.length;
      if (numeric && (isDigit(sentence[at - 1]) || (/[0-9]$/.test(needle) && isDigit(sentence[end])))) continue;
      if (!overlaps(at, end)) found.push(at);
    }
    return found;
  };
  for (const { value, unit } of values) {
    if (!value) continue;
    const withUnit = unit ? places(`${value}${unit}`) : [];
    if (withUnit.length) {
      spans.push([withUnit[0], withUnit[0] + value.length + unit!.length]);
      continue;
    }
    const bare = places(value);
    if (bare.length) spans.push([bare.at(-1)!, bare.at(-1)! + value.length]);
  }
  return spans.sort((a, b) => a[0] - b[0]);
}

/**
 * 묶은 줄의 조건·예외. 모든 값에 같은 조건이면 한 번, 일부 값에만 붙은 조건은 '값: 조건'으로 어느 값 것인지 남긴다.
 */
export function groupNotes(fields: Pick<FactFields, "value" | "conditions" | "exceptions">[]): { conditions: string[]; exceptions: string[] } {
  const notes = (pick: (f: (typeof fields)[number]) => string[]) => {
    const all = [...new Set(fields.flatMap(pick))];
    if (fields.length <= 1) return all;
    return all.flatMap((note) => {
      const owners = fields.filter((f) => pick(f).includes(note));
      if (owners.length === fields.length || owners.every((f) => !f.value)) return [note];
      return owners.filter((f) => f.value).map((f) => `${f.value}: ${note}`);
    });
  };
  return { conditions: notes((f) => f.conditions), exceptions: notes((f) => f.exceptions) };
}
