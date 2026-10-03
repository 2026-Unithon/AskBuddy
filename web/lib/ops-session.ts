// 운영자 토큰 저장소. sessionStorage 에 둬 탭을 닫으면 사라지고, 제품 로그인(localStorage)과 섞지 않는다.
// 화면 컴포넌트는 토큰 수명을 직접 다루지 않고 이 모듈만 거친다.
import { useSyncExternalStore } from "react";
import { ApiError } from "@/lib/api";

const KEY = "askbuddy:ops-token";
const listeners = new Set<() => void>();

function read(): string | null {
  try {
    return window.sessionStorage.getItem(KEY);
  } catch {
    return null;
  }
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function setOpsToken(token: string | null) {
  try {
    if (token) window.sessionStorage.setItem(KEY, token);
    else window.sessionStorage.removeItem(KEY);
  } catch {
    // 저장소를 못 쓰는 환경이면 이번 화면에서만 로그인 상태가 유지되지 않는다
  }
  listeners.forEach((listener) => listener());
}

export function useOpsToken(): string | null {
  return useSyncExternalStore(subscribe, read, () => null);
}

// 401(토큰 없음·만료)·403(역할 회수)이면 토큰을 지워 로그인 폼으로 돌려보낸다
export async function withOpsSession<T>(run: () => Promise<T>): Promise<T> {
  try {
    return await run();
  } catch (error) {
    if (error instanceof ApiError && (error.status === 401 || error.status === 403)) setOpsToken(null);
    throw error;
  }
}
