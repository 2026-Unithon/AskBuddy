"use client";

import { useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { logoutSession, SESSION_EXPIRED_EVENT, STORE_CLOSED_EVENT, type StoreClosedCode } from "@/lib/api";
import { useApp } from "@/lib/store";

export function SessionExpiryHandler() {
  const { state, dispatch } = useApp();
  const queryClient = useQueryClient();
  const router = useRouter();
  const handled = useRef(false);
  const previousUser = useRef<number | null>(null);

  useEffect(() => {
    if (previousUser.current && state.userId !== previousUser.current) {
      queryClient.clear();
    }
    previousUser.current = state.userId;
    if (state.token) handled.current = false;
  }, [state.userId, state.token, queryClient]);

  useEffect(() => {
    function handleExpiredSession() {
      if (!state.token || handled.current) return;
      handled.current = true;
      const authPath = "/";
      const destination = `${window.location.pathname}${window.location.search}`;
      queryClient.clear();
      dispatch({ type: "LOGOUT" });
      router.replace(`${authPath}?next=${encodeURIComponent(destination)}`);
    }

    window.addEventListener(SESSION_EXPIRED_EVENT, handleExpiredSession);
    return () => window.removeEventListener(SESSION_EXPIRED_EVENT, handleExpiredSession);
  }, [state.token, state.role, queryClient, dispatch, router]);

  // 매장이 닫혔다(계획 8). 탈퇴 대기 사장님은 취소 화면으로, 나머지는 로그아웃 후 첫 화면으로
  useEffect(() => {
    function handleStoreClosed(event: Event) {
      const code = (event as CustomEvent<{ code: StoreClosedCode }>).detail?.code;
      if (code === "OWNER_WITHDRAWING") {
        if (window.location.pathname !== "/withdrawal") router.replace("/withdrawal");
        return;
      }
      if (handled.current) return;
      handled.current = true;
      void logoutSession()
        .catch(() => undefined)
        .finally(() => {
          queryClient.clear();
          dispatch({ type: "LOGOUT" });
          router.replace("/");
        });
    }

    window.addEventListener(STORE_CLOSED_EVENT, handleStoreClosed);
    return () => window.removeEventListener(STORE_CLOSED_EVENT, handleStoreClosed);
  }, [queryClient, dispatch, router]);

  return null;
}
