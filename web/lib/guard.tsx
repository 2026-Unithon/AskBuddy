"use client";
import { useEffect } from "react";
import { usePathname, useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { bootstrapQuery } from "./query";
import { useApp } from "./store";
import type { Role } from "./types";
type AuthGuardResult = { ready: true; state: "ready"; retry: () => void } | { ready: false; state: "loading" | "redirecting" | "error"; retry: () => void };
export function useAuthGuard(role: Role, authPath: string): AuthGuardResult {
  const router = useRouter();
  const pathname = usePathname();
  const { state, retrySession } = useApp();
  const bootstrap = useQuery(bootstrapQuery(state.hydrated ? state.token : null, state.userId, state.storeId));
  let destination: string | null = null;
  if (state.hydrated && !state.sessionError) {
    if (pathname === authPath) destination = "/";
    else if (!state.token) destination = `/?next=${encodeURIComponent(pathname)}`;
    else if (bootstrap.data) {
      const data = bootstrap.data;
      if (data.user.role !== role || (!data.store && pathname !== data.default_destination)) destination = data.default_destination;
    }
  }
  useEffect(() => { if (destination) router.replace(destination); }, [destination, router]);
  const retry = () => { if (state.sessionError) retrySession(); else void bootstrap.refetch(); };
  if (!state.hydrated) return { ready: false, state: "loading", retry };
  if (state.sessionError || bootstrap.isError) return { ready: false, state: "error", retry };
  if (destination || !state.token) return { ready: false, state: "redirecting", retry };
  if (!bootstrap.data) return { ready: false, state: "loading", retry };
  return { ready: true, state: "ready", retry };
}
