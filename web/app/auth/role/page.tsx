"use client";
import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Shell } from "@/components/ui";
import { BuddyImage, Button, ErrorInline } from "@/components/kit";
import { LoginLoading, LoginRetry } from "@/components/login-session";
import { apiErrorMessage, chooseRole } from "@/lib/api";
import { bootstrapQuery } from "@/lib/query";
import { useApp } from "@/lib/store";
export default function Page() {
  const router = useRouter();
  const { state, dispatch, retrySession } = useApp();
  const queryClient = useQueryClient();
  const boot = useQuery(bootstrapQuery(state.role ? state.token : null, state.userId, state.storeId));
  const choose = useMutation({ mutationFn: (role: "OWNER" | "STAFF") => chooseRole(role, state.token!), onSuccess: async (s) => {
    await queryClient.invalidateQueries({ queryKey: bootstrapQuery(state.token, state.userId, state.storeId).queryKey });
    dispatch({ type: "SET_AUTH", token: s.token, role: s.user.role, userId: s.user.user_id, storeId: s.user.store_id ?? null });
  } });
  useEffect(() => {
    if (!state.hydrated || state.sessionError) return;
    if (!state.token) router.replace("/");
    else if (boot.data) router.replace(boot.data.default_destination);
  }, [state.hydrated, state.sessionError, state.token, boot.data, router]);
  return <Shell>{state.sessionError || boot.isError ? <LoginRetry retry={() => { if (state.sessionError) retrySession(); else void boot.refetch(); }} /> : !state.hydrated || !state.token || state.role ? <LoginLoading /> : <div className="flex flex-1 flex-col justify-center gap-4 px-6"><div className="flex flex-col items-center gap-3 text-center"><BuddyImage size={100} /><h1 className="text-[26px] font-bold leading-[1.35] tracking-[-0.52px] text-ink [word-break:keep-all]">어떤 분이세요?</h1><p className="text-[15px] leading-[1.5] text-ink-muted [word-break:keep-all]">한 번만 고르면 돼요.</p></div><Button loading={choose.isPending && choose.variables === "OWNER"} disabled={choose.isPending} onClick={() => choose.mutate("OWNER")}>사장님이에요</Button><Button variant="secondary" loading={choose.isPending && choose.variables === "STAFF"} disabled={choose.isPending} onClick={() => choose.mutate("STAFF")}>알바생이에요</Button>{choose.error && <ErrorInline message={apiErrorMessage(choose.error, "역할을 설정하지 못했어요.")} />}</div>}</Shell>;
}
