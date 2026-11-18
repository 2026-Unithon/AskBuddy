"use client";

// 카드 수정의 화면 지역 상태(계획 10, D23). 서버 값(CardFactsView)은 Query 가 정본이고,
// 여기에는 "고치는 중인 줄 초안" 만 둔다. 저장 전에는 서버에 아무것도 쓰지 않는다.
import { useCallback, useMemo, useReducer, useRef } from "react";
import type { CardFactsView, FactEditRequest, ParsedFactProposal } from "@/lib/api";
import {
  addLine,
  draftFromView,
  editLine,
  isDirty,
  lineCount,
  moveLine,
  needsParse,
  removeLine,
  toLineRequest,
  type DraftState,
  type ParseNeed,
} from "./line-draft";

type Action =
  | { type: "reset"; view: CardFactsView }
  | { type: "clear" }
  | { type: "move"; block: string; from: number; to: number }
  | { type: "edit"; key: string; text: string }
  | { type: "remove"; key: string }
  | { type: "add"; proposal: ParsedFactProposal };

function reducer(state: DraftState | null, action: Action): DraftState | null {
  if (action.type === "reset") return draftFromView(action.view);
  if (action.type === "clear") return null;
  if (!state) return state;
  switch (action.type) {
    case "move":
      return moveLine(state, action.block, action.from, action.to);
    case "edit":
      return editLine(state, action.key, action.text);
    case "remove":
      return removeLine(state, action.key);
    case "add":
      return addLine(state, action.proposal);
  }
}

function newKey(): string {
  return globalThis.crypto?.randomUUID?.() ?? `fe_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 10)}`;
}

export function useFactEditDraft() {
  const [draft, dispatch] = useReducer(reducer, null);
  // 멱등 키: 본문(키 제외)이 바뀔 때만 새로 만든다. 같은 본문 재시도는 같은 키
  const keyRef = useRef<{ body: string; key: string } | null>(null);

  const dirty = useMemo(() => (draft ? isDirty(draft) : false), [draft]);
  const remaining = useMemo(() => (draft ? lineCount(draft) : 0), [draft]);

  /** 저장 때 다시 분석할 줄(고친 줄) */
  const parseNeeds = useCallback((): ParseNeed[] => (draft ? needsParse(draft) : []), [draft]);

  const buildRequest = useCallback(
    (parsed: Map<string, ParsedFactProposal[]>): FactEditRequest | null => {
      if (!draft) return null;
      const body = JSON.stringify(toLineRequest(draft, parsed, ""));
      if (keyRef.current?.body !== body) keyRef.current = { body, key: newKey() };
      return toLineRequest(draft, parsed, keyRef.current.key);
    },
    [draft],
  );

  const actions = useMemo(
    () => ({
      reset: (view: CardFactsView) => dispatch({ type: "reset", view }),
      clear: () => dispatch({ type: "clear" }),
      move: (block: string, from: number, to: number) => dispatch({ type: "move", block, from, to }),
      edit: (key: string, text: string) => dispatch({ type: "edit", key, text }),
      remove: (key: string) => dispatch({ type: "remove", key }),
      add: (proposal: ParsedFactProposal) => dispatch({ type: "add", proposal }),
    }),
    [],
  );

  return { draft, dirty, remaining, actions, parseNeeds, buildRequest };
}
