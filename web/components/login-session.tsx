"use client";
import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { useApp } from "@/lib/store";
import { bootstrapQuery } from "@/lib/query";
import { authDestination } from "@/lib/auth-destination";
import { Button } from "./ui";
export function useLoginDestination(next: string | null, enabled = true) {
  const { state, retrySession } = useApp();
  const router = useRouter();
  const boot = useQuery(bootstrapQuery(enabled && state.hydrated ? state.token : null, state.userId, state.storeId));
  useEffect(() => {
    if (enabled && boot.data) router.replace(authDestination(boot.data, next));
  }, [enabled, boot.data, next, router]);
  return { state, error: state.sessionError || (enabled && boot.isError), retry: () => { if (state.sessionError) retrySession(); else void boot.refetch(); } };
}
export function LoginLoading() {
  return <div role="status" aria-label="로그인 상태 확인 중" className="space-y-4 animate-pulse p-6"><div className="mx-auto h-24 w-24 rounded-full bg-surface-muted" /><div className="h-12 rounded-xl bg-surface-muted" /><div className="h-12 rounded-xl bg-surface-muted" /></div>;
}
export function LoginRetry({ retry }: { retry: () => void }) {
  return <div className="space-y-4 p-6 text-center"><p role="alert">연결을 확인한 뒤 다시 시도해 주세요.</p><Button onClick={retry}>다시 시도</Button></div>;
}
