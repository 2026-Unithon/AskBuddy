"use client";

import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useReducer,
  type ReactNode,
} from "react";
import type { BusinessType, Role } from "./types";

const STORAGE_KEY = "askbuddy_state";
// 데이터 구조(roadmap/categories 등)를 바꿀 때마다 올린다.
// 이전 버전 캐시가 새 코드와 섞이면 없는 필드를 읽다가(예: node.pos) 화면이 그대로 죽는다 — 반드시 올릴 것.
const STATE_VERSION = 9;

type AppState = {
  hydrated: boolean;
  role: Role | null;
  // 백엔드 JWT. store_id 가 이 안에만 있으므로 /ingest/* 호출에 반드시 필요하다.
  // 없으면 보호 화면에 들어갈 수 없다.
  token: string | null;
  userId: number | null;
  storeId: number | null;
  businessType: BusinessType | null;
};

const initialState: AppState = {
  hydrated: false,
  role: null,
  token: null,
  userId: null,
  storeId: null,
  businessType: null,
};

type Action =
  | { type: "HYDRATE"; payload: Partial<AppState> }
  | { type: "LOGOUT" }
  | {
      type: "SET_AUTH";
      token: string;
      role: Role;
      userId: number;
      storeId: number | null;
    }
  | { type: "SET_STORE"; storeId: number; token: string }
  | { type: "SET_BUSINESS_TYPE"; value: BusinessType };

function reducer(state: AppState, action: Action): AppState {
  switch (action.type) {
    case "HYDRATE":
      return { ...state, ...action.payload, hydrated: true };
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
        userId: action.userId,
        storeId: action.storeId,
      };
    case "SET_STORE":
      // 매장 생성 응답의 토큰에는 store_id 가 들어 있다. 옛 토큰을 반드시 버린다.
      return {
        ...state,
        token: action.token,
        storeId: action.storeId,
      };
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
  | "token"
  | "userId"
  | "storeId"
  | "businessType"
>;

function persistedState(state: AppState): PersistedAppState {
  const {
    role,
    token,
    userId,
    storeId,
    businessType,
  } = state;
  return {
    role,
    token,
    userId,
    storeId,
    businessType,
  };
}

function isBusinessType(value: unknown): value is BusinessType {
  return value === "CAFE" || value === "RESTAURANT" || value === "BAKERY" || value === "BAR" || value === "CVS" || value === "SALON";
}

function restorePersistedState(data: object): Partial<AppState> {
  const restored: Partial<AppState> = {};
  if ("role" in data && (data.role === "OWNER" || data.role === "STAFF" || data.role === null)) restored.role = data.role;
  if ("token" in data && (typeof data.token === "string" || data.token === null)) restored.token = data.token;
  if ("userId" in data && (typeof data.userId === "number" || data.userId === null)) restored.userId = data.userId;
  if ("storeId" in data && (typeof data.storeId === "number" || data.storeId === null)) restored.storeId = data.storeId;
  if ("businessType" in data && (isBusinessType(data.businessType) || data.businessType === null)) restored.businessType = data.businessType;
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
        (parsed.v === STATE_VERSION || parsed.v === 8 || parsed.v === 7) &&
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
