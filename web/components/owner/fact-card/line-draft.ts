// 카드 수정 초안(계획 10, D23): 사장님은 보기와 같은 줄을 옮기고 고친다. 사실은 줄 뒤에 따라간다.
// 서버 값(CardFactsView)은 Query 가 정본이고, 여기에는 저장 전 초안만 둔다. node --test 가 바로 읽도록 타입만 import 한다.
import type { CardFactsView, EditBlock, EditBlockKind, EditItem, FactEditRequest, FactFields, FactRow, ParsedFactProposal } from "@/lib/api";

// lib/tile-order 의 moveTile 과 같다. node --test 가 별칭(@/) 경로를 못 읽어 여기 둔다
function moveTile<T>(order: T[], from: number, to: number): T[] {
  if (from === to || from < 0 || to < 0 || from >= order.length || to >= order.length) return [...order];
  const next = [...order];
  const [item] = next.splice(from, 1);
  next.splice(to, 0, item);
  return next;
}

export type DraftLine = {
  /** 화면 안 열쇠. 처음 줄은 "{블록}:{처음 자리}", 새 줄은 "{블록}:n{번호}" */
  key: string;
  text: string;
  /** 처음 글(새로 넣은 줄은 넣을 때 글). 글이 이것과 다르면 저장 때 다시 분석한다 */
  origText: string;
  /** 근거: 고정 판 id 들 */
  refs: number[];
  /** 근거: 이번에 넣는 사실의 client_ref 들 */
  addRefs: string[];
};

export type DraftAdd = { clientRef: string; fields: FactFields };

export type DraftBlock = {
  key: string;
  kind: EditBlockKind;
  heading: string | null;
  /** 이 블록에 고정된 판(뺀 것 제외) */
  facts: FactRow[];
  adds: DraftAdd[];
  lines: DraftLine[];
};

export type DraftState = { view: CardFactsView; blocks: DraftBlock[]; deleted: number[]; nextRef: number };

/** 다시 분석할 줄. 근거가 고정 판 하나뿐이면 그 판을 고치고(MODIFY), 아니면 새 사실로 바꾼다(ADD) */
export type ParseNeed = { key: string; text: string; mode: "MODIFY" | "ADD"; base: number | null };

export function fieldsOf(row: FactRow): FactFields {
  return {
    sentence: row.assertion?.trim() ? row.assertion : row.sentence,
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

export function draftFromView(view: CardFactsView): DraftState {
  return {
    view,
    blocks: view.blocks
      .filter((block): block is typeof block & { kind: EditBlockKind } => block.kind !== "RAW")
      .map((block) => ({
        key: block.block_id,
        kind: block.kind,
        heading: block.heading,
        facts: [...block.facts],
        adds: [],
        lines: block.lines.map((line, i) => ({ key: `${block.block_id}:${i}`, text: line.text, origText: line.text, refs: [...line.fact_revision_ids], addRefs: [] })),
      })),
    deleted: [],
    nextRef: 1,
  };
}

const edited = (line: DraftLine) => line.text.trim() !== line.origText.trim();

export function moveLine(state: DraftState, blockKey: string, from: number, to: number): DraftState {
  return { ...state, blocks: state.blocks.map((b) => (b.key === blockKey ? { ...b, lines: moveTile(b.lines, from, to) } : b)) };
}

export function editLine(state: DraftState, lineKey: string, text: string): DraftState {
  return { ...state, blocks: state.blocks.map((b) => ({ ...b, lines: b.lines.map((l) => (l.key === lineKey ? { ...l, text } : l)) })) };
}

/** 줄을 뺀다. 그 줄만 인용하던 사실은 카드에서 빠진다(고정 판은 deleted, 새 사실은 버림). 빈 블록은 없앤다 */
export function removeLine(state: DraftState, lineKey: string): DraftState {
  const blocks = state.blocks.map((b) => ({ ...b, lines: b.lines.filter((l) => l.key !== lineKey) }));
  const cited = new Set(blocks.flatMap((b) => b.lines.flatMap((l) => l.refs)));
  const citedAdds = new Set(blocks.flatMap((b) => b.lines.flatMap((l) => l.addRefs)));
  const gone: number[] = [];
  const kept = blocks
    .map((b) => {
      const facts = b.facts.filter((f) => {
        if (cited.has(f.fact_revision_id)) return true;
        gone.push(f.fact_revision_id);
        return false;
      });
      return { ...b, facts, adds: b.adds.filter((a) => citedAdds.has(a.clientRef)) };
    })
    .filter((b) => b.lines.length > 0);
  return { ...state, blocks: kept, deleted: [...state.deleted, ...gone] };
}

/** 분석한 새 사실을 줄 하나로 넣는다. 같은 종류의 마지막 블록 끝, 없으면 새 블록 */
export function addLine(state: DraftState, proposal: ParsedFactProposal): DraftState {
  const ref = `n${state.nextRef}`;
  const line: DraftLine = { key: `add:${ref}`, text: proposal.fact.sentence, origText: proposal.fact.sentence, refs: [], addRefs: [ref] };
  const add: DraftAdd = { clientRef: ref, fields: proposal.fact };
  const index = state.blocks.map((b) => b.kind).lastIndexOf(proposal.block_kind);
  const blocks =
    index >= 0
      ? state.blocks.map((b, i) => (i === index ? { ...b, adds: [...b.adds, add], lines: [...b.lines, line] } : b))
      : [...state.blocks, { key: `new-${ref}`, kind: proposal.block_kind, heading: null, facts: [], adds: [add], lines: [line] }];
  return { ...state, blocks, nextRef: state.nextRef + 1 };
}

export function isDirty(state: DraftState): boolean {
  if (state.deleted.length > 0) return true;
  const original = state.view.blocks.filter((b) => b.kind !== "RAW");
  if (original.length !== state.blocks.length) return true;
  return state.blocks.some((block, bi) => {
    const before = original[bi];
    if (!before || before.block_id !== block.key || block.adds.length > 0 || before.lines.length !== block.lines.length) return true;
    return block.lines.some((line, li) => line.key !== `${block.key}:${li}` || edited(line));
  });
}

export function lineCount(state: DraftState): number {
  return state.blocks.reduce((sum, b) => sum + b.lines.length, 0);
}

export function needsParse(state: DraftState): ParseNeed[] {
  return state.blocks.flatMap((b) =>
    b.lines.filter(edited).map((l) => {
      const single = l.refs.length === 1 && l.addRefs.length === 0;
      return { key: l.key, text: l.text.trim(), mode: single ? ("MODIFY" as const) : ("ADD" as const), base: single ? l.refs[0] : null };
    }),
  );
}

/**
 * 저장 요청. parsed = 고친 줄 열쇠 → 분석 결과.
 * - MODIFY 줄: 첫 제안으로 그 판을 고친다(단계 여부·규격은 원래 판을 따른다). 나머지 제안은 새 사실로 그 줄에 붙인다.
 * - ADD 줄: 제안을 모두 새 사실로 넣고, 그 줄만 인용하던 옛 사실은 뺀다.
 * 분석 결과가 없는 고친 줄은 글만 바뀐다(근거는 그대로).
 */
export function toLineRequest(state: DraftState, parsed: Map<string, ParsedFactProposal[]>, idempotencyKey: string): FactEditRequest {
  const modify = new Map<number, FactFields>();
  const extraAdds = new Map<string, DraftAdd[]>();
  const replaced = new Set<string>();
  let n = 0;
  for (const block of state.blocks) {
    for (const line of block.lines) {
      const proposals = edited(line) ? parsed.get(line.key) : undefined;
      if (!proposals || proposals.length === 0) continue;
      const single = line.refs.length === 1 && line.addRefs.length === 0;
      const rest = single ? proposals.slice(1) : proposals;
      if (single) {
        const base = block.facts.find((f) => f.fact_revision_id === line.refs[0]);
        if (base) modify.set(base.fact_revision_id, { ...proposals[0].fact, step_order: base.step_order, variant: { ...base.variant } });
      } else replaced.add(line.key);
      extraAdds.set(line.key, rest.map((p) => ({ clientRef: `e${(n += 1)}`, fields: p.fact })));
    }
  }
  // ADD 로 바뀐 줄만 인용하던 옛 사실은 뺀다
  const stillCited = new Set(state.blocks.flatMap((b) => b.lines.filter((l) => !replaced.has(l.key)).flatMap((l) => l.refs)));
  const dropped = new Set(state.blocks.flatMap((b) => b.facts.map((f) => f.fact_revision_id)).filter((id) => !stillCited.has(id)));
  const blocks: EditBlock[] = state.blocks.map((block) => {
    const items: EditItem[] = [
      ...block.facts
        .filter((f) => !dropped.has(f.fact_revision_id))
        .map((f): EditItem => {
          const fields = modify.get(f.fact_revision_id);
          return fields ? { op: "MODIFY", fact_revision_id: f.fact_revision_id, fact: fields } : { op: "KEEP", fact_revision_id: f.fact_revision_id };
        }),
      ...block.adds.map((a): EditItem => ({ op: "ADD", client_ref: a.clientRef, fact: a.fields })),
      ...block.lines.flatMap((l) => (extraAdds.get(l.key) ?? []).map((a): EditItem => ({ op: "ADD", client_ref: a.clientRef, fact: a.fields }))),
    ];
    const lines = block.lines.map((l) => {
      const extra = (extraAdds.get(l.key) ?? []).map((a) => a.clientRef);
      const refs = replaced.has(l.key) ? [] : l.refs.filter((id) => !dropped.has(id));
      return { text: l.text.trim(), fact_revision_ids: refs, client_refs: [...l.addRefs, ...extra] };
    });
    return { kind: block.kind, heading: block.heading, items, lines };
  });
  return {
    expected_version_id: state.view.version_id,
    idempotency_key: idempotencyKey,
    blocks,
    deleted_fact_revision_ids: [...state.deleted, ...dropped],
  };
}
