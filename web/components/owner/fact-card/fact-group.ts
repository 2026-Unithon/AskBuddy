// 보기 모드 사실 묶기. node --test 가 바로 읽도록 값 import 없이 둔다(타입만).
import type { FactFields } from "@/lib/api";

type Row = Pick<FactFields, "sentence" | "step_order" | "value">;

export type FactGroup<T extends Row = FactFields> = { key: string; fields: T[]; stepOrder: number | null };

/**
 * 보기 모드에서 같은 문장에서 나온 사실들을 한 줄로 묶는다(한 문장에 값이 여러 개면 사실이 값마다 나뉘어 저장된다).
 * 묶은 뒤 번호가 겹치거나, 한 줄이 여러 단계를 담으면 그 블록은 번호를 숨긴다.
 */
export function groupFacts<T extends Row>(rows: T[]): { groups: FactGroup<T>[]; numbered: boolean } {
  const byKey = new Map<string, FactGroup<T>>();
  const groups: FactGroup<T>[] = [];
  for (const fields of rows) {
    // 값마다 나뉜 사실(값이 있음)만 같은 문장끼리 묶는다. 값 없는 같은 문장이 다른 단계에 다시 나오면
    // 진짜로 반복되는 단계(예: '잘 저어 준다' 2번·4번)라 따로 둔다
    const key = fields.value ? fields.sentence.trim() : `${fields.sentence.trim()}#${fields.step_order ?? ""}`;
    const found = byKey.get(key);
    if (found) {
      found.fields.push(fields);
      if (found.stepOrder !== fields.step_order) found.stepOrder = null;
      continue;
    }
    const group: FactGroup<T> = { key, fields: [fields], stepOrder: fields.step_order };
    byKey.set(key, group);
    groups.push(group);
  }
  const orders = groups.map((g) => g.stepOrder);
  const numbered = orders.every((o) => o !== null) && new Set(orders).size === orders.length;
  return { groups, numbered };
}

