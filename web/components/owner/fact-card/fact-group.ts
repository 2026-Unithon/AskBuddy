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
