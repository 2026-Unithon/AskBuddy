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
  MOCK_EMPTY_KNOWLEDGE,
  MOCK_INVITE_CODE,
  MOCK_ROADMAP,
  MOCK_STORE_NAME,
  MOCK_TASK_CATEGORIES,
} from "./mock";
import type {
  BusinessType,
  EmptyKnowledgeAlert,
  Role,
  RoadmapNode,
  TaskCategory,
} from "./types";

const STORAGE_KEY = "askbuddy_state";
// 데이터 구조(roadmap/categories 등)를 바꿀 때마다 올린다.
// 이전 버전 캐시가 새 코드와 섞이면 없는 필드를 읽다가(예: node.pos) 화면이 그대로 죽는다 — 반드시 올릴 것.
const STATE_VERSION = 8;

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
  // 카테고리/로드맵 배열은 화면 모양과 비로그인 fallback뿐이다.
  // 로그인 뒤 서버 응답은 TanStack Query 캐시가 소유한다.
  categories: TaskCategory[];
  roadmap: RoadmapNode[];
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
  roadmap: MOCK_ROADMAP,
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
  | { type: "SET_BUSINESS_TYPE"; value: BusinessType };

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
      // 로그인은 항상 빈 상태에서 시작한다.
      // ...state 로 이어받으면 같은 브라우저에서 다른 계정으로 들어왔을 때
      // 앞사람의 업로드 기록·카드·로드맵이 그대로 보인다 — 새로 가입했는데
      // 영상이 이미 올라간 것처럼 보이던 게 이것 때문이다.
      // 화면에 필요한 값은 로그인 뒤 서버에서 다시 받아온다.
      return {
        ...initialState,
        hydrated: true,
        token: action.token,
        role: action.role,
        displayName: action.displayName,
        userId: action.userId,
        storeId: action.storeId,
        storeSlug: action.storeSlug ?? initialState.storeSlug,
        storeName: action.storeName ?? initialState.storeName,
        inviteCode: action.inviteCode ?? initialState.inviteCode,
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
    case "SET_BUSINESS_TYPE":
      return { ...state, businessType: action.value };
    default:
      return state;
  }
}

type AppContextValue = {
  state: AppState;
  dispatch: React.Dispatch<Action>;
};

type PersistedAppState = Pick<
  AppState,
  | "role"
  | "displayName"
  | "token"
  | "userId"
  | "storeId"
  | "storeSlug"
  | "storeName"
  | "businessType"
  | "inviteCode"
  | "streakDays"
  | "hearts"
>;

function persistedState(state: AppState): PersistedAppState {
  const {
    role,
    displayName,
    token,
    userId,
    storeId,
    storeSlug,
    storeName,
    businessType,
    inviteCode,
    streakDays,
    hearts,
  } = state;
  return {
    role,
    displayName,
    token,
    userId,
    storeId,
    storeSlug,
    storeName,
    businessType,
    inviteCode,
    streakDays,
    hearts,
  };
}

function isBusinessType(value: unknown): value is BusinessType {
  return value === "CAFE" || value === "RESTAURANT" || value === "BAKERY" || value === "BAR" || value === "CVS" || value === "SALON";
}

function restorePersistedState(data: object): Partial<AppState> {
  const restored: Partial<AppState> = {};
  if ("role" in data && (data.role === "OWNER" || data.role === "STAFF" || data.role === null)) restored.role = data.role;
  if ("displayName" in data && (typeof data.displayName === "string" || data.displayName === null)) restored.displayName = data.displayName;
  if ("token" in data && (typeof data.token === "string" || data.token === null)) restored.token = data.token;
  if ("userId" in data && (typeof data.userId === "number" || data.userId === null)) restored.userId = data.userId;
  if ("storeId" in data && (typeof data.storeId === "number" || data.storeId === null)) restored.storeId = data.storeId;
  if ("storeSlug" in data && typeof data.storeSlug === "string") restored.storeSlug = data.storeSlug;
  if ("storeName" in data && typeof data.storeName === "string") restored.storeName = data.storeName;
  if ("businessType" in data && (isBusinessType(data.businessType) || data.businessType === null)) restored.businessType = data.businessType;
  if ("inviteCode" in data && typeof data.inviteCode === "string") restored.inviteCode = data.inviteCode;
  if ("streakDays" in data && typeof data.streakDays === "number") restored.streakDays = data.streakDays;
  if ("hearts" in data && typeof data.hearts === "number") restored.hearts = data.hearts;
  return restored;
}

const AppContext = createContext<AppContextValue | null>(null);

export function AppProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(reducer, initialState);

  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(STORAGE_KEY);
      const parsed: unknown = raw ? JSON.parse(raw) : null;
      // 버전이 다르면(스키마가 바뀌었으면) 옛 캐시를 신뢰하지 않고 그냥 버린다.
      if (
        parsed &&
        typeof parsed === "object" &&
        "v" in parsed &&
        (parsed.v === STATE_VERSION || parsed.v === 7) &&
        "data" in parsed &&
        parsed.data &&
        typeof parsed.data === "object"
      ) {
        // v7의 API 응답 캐시는 버리고 인증/환경 값만 v8로 승격한다.
        dispatch({ type: "HYDRATE", payload: restorePersistedState(parsed.data) });
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
      window.localStorage.setItem(
        STORAGE_KEY,
        JSON.stringify({ v: STATE_VERSION, data: persistedState(state) })
      );
    } catch {
      // 저장 공간이 없어도 화면 동작에는 영향 없음
    }
  }, [state]);

  const value = useMemo(() => ({ state, dispatch }), [state]);

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}

export function useApp() {
  const ctx = useContext(AppContext);
  if (!ctx) throw new Error("useApp은 AppProvider 안에서만 사용한다");
  return ctx;
}
