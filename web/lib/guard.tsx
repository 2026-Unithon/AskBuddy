"use client";

import { useEffect } from "react";
import { usePathname, useRouter } from "next/navigation";
import { useApp } from "./store";
import type { Role } from "./types";

// 로그인하지 않으면 화면에 들어갈 수 없다. 토큰이 없으면 해당 역할의 인증 화면으로 돌린다.
// hydrate 전에는 판단하지 않는다 — localStorage 를 읽기 전이라 항상 비어 보인다.
export function useAuthGuard(role: Role, authPath: string) {
  const router = useRouter();
  const pathname = usePathname();
  const { state } = useApp();

  const allowed = pathname === authPath || (state.token !== null && state.role === role);

  useEffect(() => {
    if (!state.hydrated) return;
    if (allowed) return;
    router.replace(authPath);
  }, [state.hydrated, allowed, router, authPath]);

  return { ready: state.hydrated && allowed };
}
