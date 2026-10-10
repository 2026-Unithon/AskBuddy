"use client";

// W3b 사실 카드 편집의 화면 지역 상태. 서버 값(CardFactsView)은 Query 가 정본이고,
// 여기에는 "고치는 중인 초안" 만 둔다. 저장 전에는 서버에 아무것도 쓰지 않는다.
import { useCallback, useMemo, useReducer, useRef } from "react";
import type {
  CardFactsView,
  EditBlock,
  EditBlockKind,
  FactEditRequest,
  FactFields,
  FactRow,
  FactVariant,
  ParsedFactProposal,
} from "@/lib/api";

export type DraftRow = {
  /** 화면 안 열쇠. 고정 판은 "r{판 id}", 새 줄은 client_ref */
  key: string;
  /** 카드에 고정된 판. 새로 넣은 줄이면 null */
  base: FactRow | null;
  clientRef: string | null;
  fields: FactFields;
  /**
   * 순서 블록에서 이 줄이 "끼워 넣은 단계 때문에 밀리기 전" 가질 단계 번호.
   * 고정 판은 처음에 base.step_order, 고정 판끼리 맞바꾸면 같이 맞바꾼다. 새 줄은 null.
   */
  slot: number | null;
};

export type DraftBlock = {
  key: string;
  kind: EditBlockKind;
  variant: FactVariant;
  rows: DraftRow[];
};

export type DraftState = {
  view: CardFactsView;
  blocks: DraftBlock[];
  deleted: number[];
  nextRef: number;
};

type Action =
  | { type: "reset"; view: CardFactsView }
  | { type: "clear" }
  | { type: "modify"; key: string; fields: FactFields }
  | { type: "remove"; key: string }
  | { type: "add"; proposal: ParsedFactProposal }
  | { type: "moveStep"; key: string; dir: -1 | 1 }
  | { type: "moveDisplay"; key: string; dir: -1 | 1 };

export function fieldsOf(row: FactRow): FactFields {
  return {
    sentence: row.sentence,
    polarity: row.polarity,
    value: row.value,
    unit: row.unit,
    conditions: [...row.conditions],
    exceptions: [...row.exceptions],
    step_order: row.step_order,
    variant: { ...row.variant },
    predicate: row.predicate,
  };
}

function sameList(a: string[], b: string[]) {
  return a.length === b.length && a.every((v, i) => v === b[i]);
}

/** 점주가 바꿀 수 있는 칸만 비교한다(규격·속성은 MODIFY 에서 서버가 무시). */
export function isModified(row: DraftRow): boolean {
  if (!row.base) return false;
  const a = row.fields;
  const b = row.base;
  return (
    a.sentence.trim() !== b.sentence ||
    a.polarity !== b.polarity ||
    (a.value?.trim() || null) !== b.value ||
    (a.unit?.trim() || null) !== b.unit ||
    !sameList(a.conditions.map((v) => v.trim()).filter(Boolean), b.conditions) ||
    !sameList(a.exceptions.map((v) => v.trim()).filter(Boolean), b.exceptions) ||
    a.step_order !== b.step_order
  );
}

export function sameVariant(a: FactVariant, b: FactVariant) {
  return (a.temperature ?? null) === (b.temperature ?? null) && (a.size ?? null) === (b.size ?? null);
}

function fromView(view: CardFactsView): DraftState {
  return {
    view,
    blocks: view.blocks
      .filter((block): block is typeof block & { kind: EditBlockKind } => block.kind !== "RAW")
      .map((block) => ({
        key: block.block_id,
        kind: block.kind,
        variant: { ...block.variant },
        rows: block.facts.map((row) => ({
          key: `r${row.fact_revision_id}`,
          base: row,
          clientRef: null,
          fields: fieldsOf(row),
          slot: row.step_order,
        })),
      })),
    deleted: [],
    nextRef: 1,
  };
}

function mapRows(state: DraftState, fn: (block: DraftBlock) => DraftBlock): DraftState {
  return { ...state, blocks: state.blocks.map(fn) };
}

function swap<T>(items: T[], i: number, j: number): T[] {
  const next = [...items];
  [next[i], next[j]] = [next[j], next[i]];
  return next;
}

function withOrder(row: DraftRow, order: number | null): DraftRow {
  return row.fields.step_order === order ? row : { ...row, fields: { ...row.fields, step_order: order } };
}

/**
 * 순서 블록의 단계 번호를 줄 자리에 맞춘다(서버 W3a 규칙: 블록 안 번호는 줄지 않는다).
 * - 새로 넣은 줄 = 바로 위 줄 번호 + 1 (맨 위면 1)
 * - 고정 판 = 원래 번호(slot). 새 줄이 앞에 끼어 밀리면 위 줄보다 1 크게 다시 매긴다.
 *   원래 같은 번호였던 이웃은 같은 번호를 유지한다.
 * 새 줄이 없으면 번호는 slot 그대로다(기존 맞바꾸기 동작과 같다).
 */
export function settleSteps(rows: DraftRow[]): DraftRow[] {
  let prev: number | null = null;
  let prevSlot: number | null = null;
  let prevAdded = false;
  return rows.map((row) => {
    if (!row.base) {
      const order = prev === null ? 1 : prev + 1;
      prev = order;
      prevAdded = true;
      return withOrder(row, order);
    }
    const slot = row.slot;
    if (slot === null) return row;
    let order: number;
    if (prev === null) order = slot;
    else if (!prevAdded && prevSlot !== null && slot === prevSlot) order = prev;
    else order = Math.max(slot, prev + 1);
    prev = order;
    prevSlot = slot;
    prevAdded = false;
    return withOrder(row, order);
  });
}

/** 다시 매긴 번호가 "다른 곳에서 바뀐" 줄을 건드리나(그 줄은 서버가 고칠 수 없다고 거절한다). */
export function disturbsLocked(rows: DraftRow[]): boolean {
  return settleSteps(rows).some((row) => Boolean(row.base?.edit_block) && row.fields.step_order !== row.base!.step_order);
}

/** 순서 블록에서 i 줄을 j 자리로(이웃 맞바꿈). 범위 밖이면 null. 화면의 이동 가능 판정도 이 결과를 쓴다. */
export function moveStepRows(rows: DraftRow[], i: number, j: number): DraftRow[] | null {
  if (i < 0 || j < 0 || i >= rows.length || j >= rows.length) return null;
  const a = rows[i];
  const b = rows[j];
  const bothFixed = Boolean(a.base && b.base);
  const swapped = swap(rows, i, j).map((row) => {
    if (!bothFixed) return row;
    if (row.key === a.key) return { ...row, slot: b.slot };
    if (row.key === b.key) return { ...row, slot: a.slot };
    return row;
  });
  return settleSteps(swapped);
}

function settleBlock(block: DraftBlock): DraftBlock {
  return block.kind === "STEPS" ? { ...block, rows: settleSteps(block.rows) } : block;
}

/** 새로 넣는 단계 줄의 자리: 분석된 번호보다 번호가 크거나 같은 첫 줄 앞. 잠긴 줄을 밀게 되면 끝. */
function insertStep(rows: DraftRow[], row: DraftRow): DraftRow[] {
  const wanted = row.fields.step_order;
  const at = wanted === null ? -1 : rows.findIndex((r) => r.fields.step_order !== null && r.fields.step_order >= wanted);
  if (at >= 0) {
    const inserted = [...rows.slice(0, at), row, ...rows.slice(at)];
    if (!disturbsLocked(inserted)) return settleSteps(inserted);
  }
  return settleSteps([...rows, row]);
}

function reducer(state: DraftState | null, action: Action): DraftState | null {
  if (action.type === "reset") return fromView(action.view);
  if (action.type === "clear") return null;
  if (!state) return state;
  switch (action.type) {
    case "modify":
      return mapRows(state, (block) => ({
        ...block,
        rows: block.rows.map((row) => (row.key === action.key ? { ...row, fields: action.fields } : row)),
      }));
    case "remove": {
      const target = state.blocks.flatMap((b) => b.rows).find((row) => row.key === action.key);
      if (!target) return state;
      // 새 줄을 빼면 그 때문에 밀렸던 단계 번호가 돌아온다
      const blocks = state.blocks
        .map((block) => settleBlock({ ...block, rows: block.rows.filter((row) => row.key !== action.key) }))
        .filter((block) => block.rows.length > 0);
      const deleted = target.base ? [...state.deleted, target.base.fact_revision_id] : state.deleted;
      return { ...state, blocks, deleted };
    }
    case "add": {
      const ref = `n${state.nextRef}`;
      const row: DraftRow = { key: ref, base: null, clientRef: ref, fields: action.proposal.fact, slot: null };
      const kind = action.proposal.block_kind;
      const variant = action.proposal.fact.variant;
      const index = state.blocks.findIndex((b) => b.kind === kind && sameVariant(b.variant, variant));
      // 순서 단계는 분석된 번호 자리에 끼우고 뒤 단계 번호를 다시 매긴다. 그 밖은 블록 끝
      const placed = (rows: DraftRow[]) => (kind === "STEPS" ? insertStep(rows, row) : [...rows, row]);
      const blocks =
        index >= 0
          ? state.blocks.map((b, i) => (i === index ? { ...b, rows: placed(b.rows) } : b))
          : [...state.blocks, { key: `new-${ref}`, kind, variant: { ...variant }, rows: placed([]) }];
      return { ...state, blocks, nextRef: state.nextRef + 1 };
    }
    case "moveStep":
      // D-6: 순서 블록에서 옮기면 절차가 바뀐다.
      // 고정 판끼리는 번호(slot)를 맞바꾼다(번호 집합 유지). 새로 넣은 줄이 끼면 자리만 바꾸고
      // 번호는 settleSteps 가 자리에 맞춰 다시 매긴다 — 그래야 기존 절차 중간에 단계를 끼울 수 있다
      return mapRows(state, (block) => {
        const i = block.rows.findIndex((row) => row.key === action.key);
        if (block.kind !== "STEPS" || i < 0) return block;
        const rows = moveStepRows(block.rows, i, i + action.dir);
        return rows ? { ...block, rows } : block;
      });
    case "moveDisplay":
      // 수치·목록 안에서는 보이는 자리만 바뀐다(사실 판 없음)
      return mapRows(state, (block) => {
        const i = block.rows.findIndex((row) => row.key === action.key);
        const j = i + action.dir;
        if (block.kind === "STEPS" || i < 0 || j < 0 || j >= block.rows.length) return block;
        return { ...block, rows: swap(block.rows, i, j) };
      });
  }
}

/** 남은 줄을 KEEP/MODIFY/ADD 로, 뺀 줄을 deleted 로. */
export function toRequest(state: DraftState, expectedVersionId: number, idempotencyKey: string): FactEditRequest {
  const blocks: EditBlock[] = state.blocks
    .filter((block) => block.rows.length > 0)
    .map((block) => ({
      kind: block.kind,
      items: block.rows.map((row) => {
        if (!row.base) return { op: "ADD" as const, client_ref: row.clientRef ?? row.key, fact: row.fields };
        if (isModified(row)) return { op: "MODIFY" as const, fact_revision_id: row.base.fact_revision_id, fact: row.fields };
        return { op: "KEEP" as const, fact_revision_id: row.base.fact_revision_id };
      }),
    }));
  return {
    expected_version_id: expectedVersionId,
    idempotency_key: idempotencyKey,
    blocks,
    deleted_fact_revision_ids: [...state.deleted],
  };
}

function newKey(): string {
  return globalThis.crypto?.randomUUID?.() ?? `fe_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 10)}`;
}

export function useFactEditDraft() {
  const [draft, dispatch] = useReducer(reducer, null);
  // 멱등 키: 본문(키 제외)이 바뀔 때만 새로 만든다. 같은 본문 재시도는 같은 키
  const keyRef = useRef<{ body: string; key: string } | null>(null);

  const dirty = useMemo(() => {
    if (!draft) return false;
    if (draft.deleted.length > 0) return true;
    const original = draft.view.blocks.filter((b) => b.kind !== "RAW");
    if (original.length !== draft.blocks.length) return true;
    return draft.blocks.some((block, bi) => {
      const before = original[bi];
      if (!before || before.block_id !== block.key || before.facts.length !== block.rows.length) return true;
      return block.rows.some((row, ri) => !row.base || row.base.fact_revision_id !== before.facts[ri].fact_revision_id || isModified(row));
    });
  }, [draft]);

  const remaining = useMemo(() => draft?.blocks.reduce((sum, block) => sum + block.rows.length, 0) ?? 0, [draft]);

  const buildRequest = useCallback((): FactEditRequest | null => {
    if (!draft) return null;
    const body = JSON.stringify(toRequest(draft, draft.view.version_id, ""));
    if (keyRef.current?.body !== body) keyRef.current = { body, key: newKey() };
    return toRequest(draft, draft.view.version_id, keyRef.current.key);
  }, [draft]);

  const actions = useMemo(
    () => ({
      reset: (view: CardFactsView) => dispatch({ type: "reset", view }),
      clear: () => dispatch({ type: "clear" }),
      modify: (key: string, fields: FactFields) => dispatch({ type: "modify", key, fields }),
      remove: (key: string) => dispatch({ type: "remove", key }),
      add: (proposal: ParsedFactProposal) => dispatch({ type: "add", proposal }),
      moveStep: (key: string, dir: -1 | 1) => dispatch({ type: "moveStep", key, dir }),
      moveDisplay: (key: string, dir: -1 | 1) => dispatch({ type: "moveDisplay", key, dir }),
    }),
    [],
  );

  return { draft, dirty, remaining, actions, buildRequest };
}
