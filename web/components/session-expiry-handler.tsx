"use client";

import { useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { SESSION_EXPIRED_EVENT } from "@/lib/api";
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

  return null;
}
