"use client";

import Link from "next/link";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button, TopBar } from "@/components/ui";
import { InviteLinkCard } from "@/components/invite-link-card";
import { apiErrorMessage, approveJoin, rejectJoin, removeMember } from "@/lib/api";
import { membersQuery, queryKeys, checklistKeys } from "@/lib/query";
import { useApp } from "@/lib/store";

function kst(iso: string) {
  return new Date(iso).toLocaleString("ko-KR", { timeZone: "Asia/Seoul", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}

export default function OwnerMembersPage() {
  const { state } = useApp();
  const queryClient = useQueryClient();
  const members = useQuery(membersQuery(state.token, state.storeId));
  const [removing, setRemoving] = useState<{ user_id: number; name: string } | null>(null);
  const invalidate = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: queryKeys.members(state.storeId) }),
      queryClient.invalidateQueries({ queryKey: checklistKeys.root(state.storeId) }),
    ]);
  };
  const decide = useMutation({
    mutationFn: ({ id, approve }: { id: number; approve: boolean }) =>
      approve ? approveJoin(id, state.token!) : rejectJoin(id, state.token!),
    onSettled: invalidate,
  });
  const remove = useMutation({
    mutationFn: (userId: number) => removeMember(userId, state.token!),
    onSuccess: () => setRemoving(null),
    onSettled: invalidate,
  });

  return (
    <>
      <TopBar title="직원 관리" backHref="/owner/settings" />
      <div className="flex-1 overflow-y-auto space-y-4 px-4 pb-8">
        <InviteLinkCard />
        <Link href="/owner/member-shifts" className="flex min-h-11 items-center font-bold text-primary">직원별 담당 근무조 정하기 →</Link>

        <section className="rounded-2xl bg-surface p-4 shadow-sm">
          <h2 className="text-sm font-bold">승인 대기 {members.data ? `(${members.data.pending.length})` : ""}</h2>
          {members.isPending && <p role="status" className="mt-2 text-xs text-muted">불러오는 중…</p>}
          {members.isError && (
            <div className="mt-2 flex items-center gap-2">
              <p role="alert" className="text-xs text-danger-500">{apiErrorMessage(members.error, "목록을 불러오지 못했어요.")}</p>
              <Button onClick={() => void members.refetch()}>다시 시도</Button>
            </div>
          )}
          {members.data?.pending.length === 0 && <p className="mt-2 text-xs text-muted">기다리는 요청이 없어요.</p>}
          <ul className="mt-2 divide-y divide-border">
            {members.data?.pending.map((r) => (
              <li key={r.request_id} className="flex items-center gap-2 py-2.5">
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-bold">{r.name}</p>
                  <p className="text-xs text-muted">{kst(r.requested_at)} 요청</p>
                </div>
                <Button loading={decide.isPending && decide.variables?.id === r.request_id} loadingLabel="처리 중"
                  onClick={() => decide.mutate({ id: r.request_id, approve: true })}>승인</Button>
                <Button disabled={decide.isPending} onClick={() => decide.mutate({ id: r.request_id, approve: false })}>거절</Button>
              </li>
            ))}
          </ul>
          {decide.error && <p role="alert" className="text-xs text-danger-500">{apiErrorMessage(decide.error, "처리하지 못했어요.")}</p>}
        </section>

        <section className="rounded-2xl bg-surface p-4 shadow-sm">
          <h2 className="text-sm font-bold">함께 일하는 직원 {members.data ? `(${members.data.active.filter((m) => m.role === "STAFF").length})` : ""}</h2>
          {members.data && members.data.active.filter((m) => m.role === "STAFF").length === 0 && (
            <p className="mt-2 text-xs text-muted">아직 합류한 직원이 없어요. 초대 링크를 보내 보세요.</p>
          )}
          <ul className="mt-2 divide-y divide-border">
            {members.data?.active.filter((m) => m.role === "STAFF").map((m) => (
              <li key={m.user_id} className="flex items-center gap-2 py-2.5">
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-bold">{m.name}</p>
                  <p className="text-xs text-muted">{kst(m.joined_at)} 합류</p>
                </div>
                <button type="button" className="min-h-11 px-2 text-xs font-bold text-danger-500" onClick={() => setRemoving(m)}>내보내기</button>
              </li>
            ))}
          </ul>
        </section>

        {removing && (
          <div role="dialog" aria-modal="true" className="fixed inset-0 z-20 flex items-end justify-center bg-black/40 p-4">
            <div className="w-full max-w-sm rounded-2xl bg-surface p-5">
              <p className="text-sm font-bold">{removing.name}님을 내보낼까요?</p>
              <p className="mt-1 text-xs text-muted">바로 앱을 쓸 수 없게 돼요. 질문·학습 기록은 남아요. 다시 초대하면 이어서 쓸 수 있어요.</p>
              {remove.error && <p role="alert" className="mt-2 text-xs text-danger-500">{apiErrorMessage(remove.error, "내보내지 못했어요.")}</p>}
              <div className="mt-4 grid grid-cols-2 gap-2">
                <Button onClick={() => setRemoving(null)}>취소</Button>
                <Button loading={remove.isPending} loadingLabel="처리 중" onClick={() => remove.mutate(removing.user_id)}>내보내기</Button>
              </div>
            </div>
          </div>
        )}
      </div>
    </>
  );
}
