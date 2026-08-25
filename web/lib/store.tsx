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

const STORAGE_KEY = "askbuddy_state";
// 데이터 구조(roadmap/categories 등)를 바꿀 때마다 올린다.
// 이전 버전 캐시가 새 코드와 섞이면 없는 필드를 읽다가(예: node.pos) 화면이 그대로 죽는다 — 반드시 올릴 것.
const STATE_VERSION = 3;

type AppState = {
  hydrated: boolean;
  role: Role | null;
  displayName: string | null;
  // 백엔드 JWT. store_id 가 이 안에만 있으므로 /ingest/* 호출에 반드시 필요하다.
  // 없으면 화면은 mock 으로 동작한다 — 데모가 끊기지 않게.
  token: string | null;
  userId: number | null;
  storeId: number | null;
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
  streakDays: number;
  hearts: number;
};

const initialState: AppState = {
  hydrated: false,
  role: null,
  displayName: null,
  token: null,
  userId: null,
  storeId: null,
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
  streakDays: 3,
  hearts: 3,
};

type Action =
  | { type: "HYDRATE"; payload: Partial<AppState> }
  | { type: "LOGIN_OWNER"; name: string; storeName: string }
  | { type: "LOGIN_STAFF"; name: string; inviteCode: string }
  | { type: "LOGOUT" }
  | {
      type: "SET_AUTH";
      token: string;
      role: Role;
      displayName: string;
      userId: number;
      storeId: number | null;
      storeSlug?: string;
      storeName?: string;
      inviteCode?: string;
    }
  | { type: "SET_STORE"; storeId: number; storeSlug: string; storeName: string; token: string }
  | { type: "SET_INVITE_CODE"; code: string }
  | { type: "SET_CATEGORIES"; categories: TaskCategory[] }
  | { type: "SET_KNOWLEDGE_SECTIONS"; sections: KnowledgeSection[] }
  | { type: "SET_BUSINESS_TYPE"; value: BusinessType }
  | { type: "TOGGLE_CATEGORY"; key: string }
  | { type: "ADD_UPLOAD_SOURCE"; source: UploadSource }
  | { type: "UPDATE_UPLOAD_SOURCE"; id: string; patch: Partial<UploadSource> }
  | { type: "COMPLETE_ROADMAP_NODE"; nodeId: string }
  | { type: "ADD_CHAT_MESSAGE"; message: ChatMessage }
  | { type: "ADD_PENDING_QUESTION"; question: PendingQuestion }
  | { type: "ANSWER_PENDING_QUESTION"; id: string; answerText: string };

function recomputeNodeStatus(nodes: RoadmapNode[]): RoadmapNode[] {
  let previousDone = true;
  return nodes.map((node) => {
    const done = node.status === "DONE";
    let status: RoadmapNode["status"];
    if (done) status = "DONE";
    else if (previousDone) status = "IN_PROGRESS";
    else status = "LOCKED";
    previousDone = done;
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
    case "SET_AUTH":
      return {
        ...state,
        token: action.token,
        role: action.role,
        displayName: action.displayName,
        userId: action.userId,
        storeId: action.storeId,
        storeSlug: action.storeSlug ?? state.storeSlug,
        storeName: action.storeName ?? state.storeName,
        inviteCode: action.inviteCode ?? state.inviteCode,
      };
    case "SET_STORE":
      // 매장 생성 응답의 토큰에는 store_id 가 들어 있다. 옛 토큰을 반드시 버린다.
      return {
        ...state,
        token: action.token,
        storeId: action.storeId,
        storeSlug: action.storeSlug,
        storeName: action.storeName,
      };
    case "SET_INVITE_CODE":
      return { ...state, inviteCode: action.code };
    case "SET_CATEGORIES":
      return { ...state, categories: action.categories };
    case "SET_KNOWLEDGE_SECTIONS":
      return { ...state, knowledgeSections: action.sections };
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
    case "COMPLETE_ROADMAP_NODE": {
      const nodes = state.roadmap.map((node) =>
        node.id === action.nodeId && node.status !== "LOCKED"
          ? { ...node, status: "DONE" as const }
          : node
      );
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

// 저장된 상태를 그대로 믿지 않는다.
//
// 버전을 올려도 사람 손으로 올리는 것이라 빠뜨릴 수 있고, 그러면 옛 모양이
// 그대로 화면까지 올라가 렌더 중에 터진다 — 실제로 roadmap 노드에 pos 가 없어
// node.pos.x 에서 "This page couldn't load" 가 났다.
// 모양이 맞지 않는 항목은 통째로 버리고 기본값으로 되돌린다.
function isRoadmapNode(n: unknown): n is RoadmapNode {
  if (!n || typeof n !== "object") return false;
  const v = n as Partial<RoadmapNode>;
  return (
    typeof v.id === "string" &&
    typeof v.label === "string" &&
    typeof v.status === "string" &&
    typeof v.pos === "object" &&
    v.pos !== null &&
    typeof (v.pos as { x?: unknown }).x === "number" &&
    typeof (v.pos as { y?: unknown }).y === "number" &&
    Array.isArray(v.details)
  );
}

function sanitize(data: Partial<AppState>): Partial<AppState> {
  const clean: Partial<AppState> = { ...data };

  if (!Array.isArray(data.roadmap) || !data.roadmap.every(isRoadmapNode)) {
    clean.roadmap = initialState.roadmap;
  }
  if (!Array.isArray(data.knowledgeSections)) {
    clean.knowledgeSections = initialState.knowledgeSections;
  }
  if (!Array.isArray(data.categories)) clean.categories = initialState.categories;
  if (!Array.isArray(data.uploadSources)) clean.uploadSources = [];
  if (!Array.isArray(data.chatMessages)) clean.chatMessages = initialState.chatMessages;
  if (!Array.isArray(data.staff)) clean.staff = initialState.staff;
  if (!Array.isArray(data.pendingQuestions)) clean.pendingQuestions = initialState.pendingQuestions;

  return clean;
}

const AppContext = createContext<AppContextValue | null>(null);

export function AppProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(reducer, initialState);

  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(STORAGE_KEY);
      const parsed = raw ? JSON.parse(raw) : null;
      // 버전이 다르면(스키마가 바뀌었으면) 옛 캐시를 신뢰하지 않고 그냥 버린다.
      if (parsed && parsed.v === STATE_VERSION && parsed.data) {
        dispatch({ type: "HYDRATE", payload: sanitize(parsed.data) });
      } else {
        window.localStorage.removeItem(STORAGE_KEY);
        dispatch({ type: "HYDRATE", payload: {} });
      }
    } catch {
      dispatch({ type: "HYDRATE", payload: {} });
    }
  }, []);

  useEffect(() => {
    if (!state.hydrated) return;
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify({ v: STATE_VERSION, data: state }));
    } catch {
      // 저장 공간이 없어도 화면 동작에는 영향 없음
    }
  }, [state]);

  const progressPct = useMemo(() => {
    if (state.roadmap.length === 0) return 0;
    const done = state.roadmap.filter((n) => n.status === "DONE").length;
    return Math.round((done / state.roadmap.length) * 100);
  }, [state.roadmap]);

  const value = useMemo(() => ({ state, dispatch, progressPct }), [state, progressPct]);

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}

export function useApp() {
  const ctx = useContext(AppContext);
  if (!ctx) throw new Error("useApp은 AppProvider 안에서만 사용한다");
  return ctx;
}
