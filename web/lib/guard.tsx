"use client";

import { useEffect } from "react";
import { usePathname, useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { ApiError } from "./api";
import { bootstrapQuery } from "./query";
import { useApp } from "./store";
import type { Role } from "./types";

type AuthGuardResult =
  | { ready: true; state: "ready"; retry: () => void }
  | { ready: false; state: "loading" | "redirecting" | "error"; retry: () => void };

// 로그인하지 않으면 화면에 들어갈 수 없다. 토큰이 없으면 해당 역할의 인증 화면으로 돌린다.
// hydrate 전에는 판단하지 않는다 — localStorage 를 읽기 전이라 항상 비어 보인다.
export function useAuthGuard(role: Role, authPath: string): AuthGuardResult {
  const router = useRouter();
  const pathname = usePathname();
  const { state, dispatch } = useApp();
  const hasLocalSession = state.token !== null && state.role === role;
  const bootstrap = useQuery(
    bootstrapQuery(
      state.hydrated && hasLocalSession ? state.token : null,
      state.userId,
      state.storeId
    )
  );

  const isAuthPage = pathname === authPath;
  const authenticationError =
    bootstrap.error instanceof ApiError &&
    [403, 404].includes(bootstrap.error.status);
  const retry = () => {
    void bootstrap.refetch();
  };

  useEffect(() => {
    if (!state.hydrated) return;
    if (isAuthPage || hasLocalSession) return;
    const destination = `${window.location.pathname}${window.location.search}`;
    router.replace(`${authPath}?next=${encodeURIComponent(destination)}`);
  }, [state.hydrated, isAuthPage, hasLocalSession, router, authPath]);

  useEffect(() => {
    if (!authenticationError) return;
    const destination = `${window.location.pathname}${window.location.search}`;
    dispatch({ type: "LOGOUT" });
    router.replace(`${authPath}?next=${encodeURIComponent(destination)}`);
  }, [authenticationError, dispatch, router, authPath]);

  useEffect(() => {
    const data = bootstrap.data;
    if (!data) return;
    if (data.user.role !== role) {
      dispatch({ type: "LOGOUT" });
      router.replace(authPath);
      return;
    }
    if (isAuthPage && data.default_destination !== pathname) {
      router.replace(data.default_destination);
      return;
    }
    if (role === "OWNER" && data.store === null && pathname !== "/owner/intent") {
      router.replace(data.default_destination);
    }
  }, [bootstrap.data, role, isAuthPage, pathname, dispatch, router, authPath]);

  if (!state.hydrated) {
    return { ready: false, state: "loading", retry };
  }
  if (isAuthPage && !hasLocalSession) {
    return { ready: true, state: "ready", retry };
  }
  if (!hasLocalSession || authenticationError) {
    return { ready: false, state: "redirecting", retry };
  }
  if (bootstrap.isPending) {
    return { ready: false, state: "loading", retry };
  }
  if (bootstrap.isError) {
    return { ready: false, state: "error", retry };
  }

  return { ready: true, state: "ready", retry };
}
