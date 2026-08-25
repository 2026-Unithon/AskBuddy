"use client";

import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useReducer,
  type ReactNode,
} from "react";
import {
  MOCK_CHAT_HISTORY,
  MOCK_EMPTY_KNOWLEDGE,
  MOCK_INVITE_CODE,
  MOCK_KNOWLEDGE_SECTIONS,
  MOCK_PENDING_QUESTIONS,
  MOCK_ROADMAP,
  MOCK_STAFF,
  MOCK_STORE_NAME,
  MOCK_TASK_CATEGORIES,
} from "./mock";
import type {
  BusinessType,
  ChatMessage,
  EmptyKnowledgeAlert,
  KnowledgeSection,
  PendingQuestion,
  Role,
  RoadmapNode,
  StaffMember,
  TaskCategory,
  UploadSource,
} from "./types";

const STORAGE_KEY = "askbuddy_state_v1";

type AppState = {
  hydrated: boolean;
  role: Role | null;
  displayName: string | null;
  storeSlug: string;
  storeName: string;
  businessType: BusinessType | null;
  inviteCode: string;
  categories: TaskCategory[];
  uploadSources: UploadSource[];
  knowledgeSections: KnowledgeSection[];
  roadmap: RoadmapNode[];
  chatMessages: ChatMessage[];
  staff: StaffMember[];
  pendingQuestions: PendingQuestion[];
  emptyKnowledge: EmptyKnowledgeAlert[];
};

const initialState: AppState = {
  hydrated: false,
  role: null,
  displayName: null,
  storeSlug: "demo-cafe",
  storeName: MOCK_STORE_NAME,
  businessType: null,
  inviteCode: MOCK_INVITE_CODE,
  categories: MOCK_TASK_CATEGORIES,
  uploadSources: [],
  knowledgeSections: MOCK_KNOWLEDGE_SECTIONS,
  roadmap: MOCK_ROADMAP,
  chatMessages: MOCK_CHAT_HISTORY,
  staff: MOCK_STAFF,
  pendingQuestions: MOCK_PENDING_QUESTIONS,
  emptyKnowledge: MOCK_EMPTY_KNOWLEDGE,
};

type Action =
  | { type: "HYDRATE"; payload: Partial<AppState> }
  | { type: "LOGIN_OWNER"; name: string; storeName: string }
  | { type: "LOGIN_STAFF"; name: string; inviteCode: string }
  | { type: "LOGOUT" }
  | { type: "SET_BUSINESS_TYPE"; value: BusinessType }
  | { type: "TOGGLE_CATEGORY"; key: string }
  | { type: "ADD_UPLOAD_SOURCE"; source: UploadSource }
  | { type: "UPDATE_UPLOAD_SOURCE"; id: string; patch: Partial<UploadSource> }
  | { type: "TOGGLE_ROADMAP_ITEM"; nodeId: string; itemId: string }
  | { type: "ADD_CHAT_MESSAGE"; message: ChatMessage }
  | { type: "ADD_PENDING_QUESTION"; question: PendingQuestion }
  | { type: "ANSWER_PENDING_QUESTION"; id: string; answerText: string };

function recomputeNodeStatus(nodes: RoadmapNode[]): RoadmapNode[] {
  let previousDone = true;
  return nodes.map((node) => {
    const allDone = node.items.every((i) => i.done);
    const someDone = node.items.some((i) => i.done);
    let status: RoadmapNode["status"];
    if (allDone) status = "DONE";
    else if (previousDone && (someDone || node.status !== "LOCKED")) status = "IN_PROGRESS";
    else status = "LOCKED";
    previousDone = allDone;
    return { ...node, status };
  });
}

function reducer(state: AppState, action: Action): AppState {
  switch (action.type) {
    case "HYDRATE":
      return { ...state, ...action.payload, hydrated: true };
    case "LOGIN_OWNER":
      return {
        ...state,
        role: "OWNER",
        displayName: action.name,
        storeName: action.storeName || state.storeName,
      };
    case "LOGIN_STAFF":
      return {
        ...state,
        role: "STAFF",
        displayName: action.name,
        inviteCode: action.inviteCode || state.inviteCode,
      };
    case "LOGOUT":
      return { ...initialState, hydrated: true };
    case "SET_BUSINESS_TYPE":
      return { ...state, businessType: action.value };
    case "TOGGLE_CATEGORY":
      return {
        ...state,
        categories: state.categories.map((c) =>
          c.key === action.key ? { ...c, enabled: !c.enabled } : c
        ),
      };
    case "ADD_UPLOAD_SOURCE":
      return { ...state, uploadSources: [...state.uploadSources, action.source] };
    case "UPDATE_UPLOAD_SOURCE":
      return {
        ...state,
        uploadSources: state.uploadSources.map((s) =>
          s.id === action.id ? { ...s, ...action.patch } : s
        ),
      };
    case "TOGGLE_ROADMAP_ITEM": {
      const nodes = state.roadmap.map((node) => {
        if (node.id !== action.nodeId) return node;
        if (node.status === "LOCKED") return node;
        return {
          ...node,
          items: node.items.map((item) =>
            item.id === action.itemId ? { ...item, done: !item.done } : item
          ),
        };
      });
      return { ...state, roadmap: recomputeNodeStatus(nodes) };
    }
    case "ADD_CHAT_MESSAGE":
      return { ...state, chatMessages: [...state.chatMessages, action.message] };
    case "ADD_PENDING_QUESTION":
      return { ...state, pendingQuestions: [...state.pendingQuestions, action.question] };
    case "ANSWER_PENDING_QUESTION":
      return {
        ...state,
        pendingQuestions: state.pendingQuestions.filter((q) => q.id !== action.id),
      };
    default:
      return state;
  }
}

type AppContextValue = {
  state: AppState;
  dispatch: React.Dispatch<Action>;
  progressPct: number;
};

const AppContext = createContext<AppContextValue | null>(null);

export function AppProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(reducer, initialState);

  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(STORAGE_KEY);
      if (raw) {
        dispatch({ type: "HYDRATE", payload: JSON.parse(raw) });
      } else {
        dispatch({ type: "HYDRATE", payload: {} });
      }
    } catch {
      dispatch({ type: "HYDRATE", payload: {} });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!state.hydrated) return;
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
    } catch {
      // 저장 공간이 없어도 화면 동작에는 영향 없음
    }
  }, [state]);

  const progressPct = useMemo(() => {
    const allItems = state.roadmap.flatMap((n) => n.items);
    if (allItems.length === 0) return 0;
    const done = allItems.filter((i) => i.done).length;
    return Math.round((done / allItems.length) * 100);
  }, [state.roadmap]);

  const value = useMemo(() => ({ state, dispatch, progressPct }), [state, progressPct]);

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}

export function useApp() {
  const ctx = useContext(AppContext);
  if (!ctx) throw new Error("useApp은 AppProvider 안에서만 사용한다");
  return ctx;
}
