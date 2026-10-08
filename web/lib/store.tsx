"use client";
import { createContext, useCallback, useContext, useEffect, useMemo, useReducer, type ReactNode } from "react";
import { ApiError, onSessionRenewed, refreshSession, type SessionResponse } from "./api";
import type { BusinessType, Role } from "./types";
type AppState = { hydrated: boolean; sessionError: boolean; role: Role | null; token: string | null; userId: number | null; storeId: number | null; businessType: BusinessType | null };
const initialState: AppState = { hydrated: false, sessionError: false, role: null, token: null, userId: null, storeId: null, businessType: null };
type Action =
  | { type: "HYDRATE"; payload: Partial<AppState> }
  | { type: "LOGOUT" }
  | { type: "SET_AUTH"; token: string; role: Role | null; userId: number; storeId: number | null }
  | { type: "SET_STORE"; storeId: number; token: string }
  | { type: "SET_BUSINESS_TYPE"; value: BusinessType };
function reducer(state: AppState, action: Action): AppState {
  switch (action.type) {
    case "HYDRATE": return { ...state, ...action.payload, hydrated: true };
    case "LOGOUT": return { ...initialState, hydrated: true };
    case "SET_AUTH": return { ...(state.userId === action.userId ? state : initialState), hydrated: true, sessionError: false, token: action.token, role: action.role, userId: action.userId, storeId: action.storeId };
    case "SET_STORE": return { ...state, token: action.token, storeId: action.storeId };
    case "SET_BUSINESS_TYPE": return { ...state, businessType: action.value };
  }
}
const AppContext = createContext<{ state: AppState; dispatch: React.Dispatch<Action>; retrySession: () => void } | null>(null);
export function AppProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(reducer, initialState);
  const retrySession = useCallback(() => {
    // 세션 복원 장애는 로그아웃으로 취급하지 않는다.
    void refreshSession().catch((error: unknown) => {
      if (error instanceof ApiError && error.status === 401) dispatch({ type: "LOGOUT" });
      else dispatch({ type: "HYDRATE", payload: { sessionError: true } });
    });
  }, []);
  useEffect(() => {
    // 예전 영속 JWT는 폐기한다. 인증 정보는 메모리와 HttpOnly 쿠키로만 유지한다.
    try { window.localStorage.removeItem("askbuddy_state"); } catch { /* 저장소 차단은 인증을 막지 않는다. */ }
    const unsubscribe = onSessionRenewed((s: SessionResponse) => dispatch({ type: "SET_AUTH", token: s.token, role: s.user.role, userId: s.user.user_id, storeId: s.user.store_id ?? null }));
    retrySession();
    return unsubscribe;
  }, [retrySession]);
  const value = useMemo(() => ({ state, dispatch, retrySession }), [state, retrySession]);
  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}
export function useApp() {
  const value = useContext(AppContext);
  if (!value) throw new Error("useApp은 AppProvider 안에서만 사용한다");
  return value;
}
