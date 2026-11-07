"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  BackButton,
  Button,
  ButtonLink,
  ConfirmDialog,
  Empty,
  ErrorInline,
  PageHeader,
  Screen,
  SectionTitle,
  Skeleton,
  Surface,
  SwipeRow,
  TextButton,
  useFeedback,
} from "@/components/kit";
import { InviteLinkCard } from "@/components/invite-link-card";
import { apiErrorMessage, approveJoin, rejectJoin, removeMember } from "@/lib/api";
import { checklistKeys, membersQuery, queryKeys } from "@/lib/query";
import { useApp } from "@/lib/store";

function kst(iso: string) {
  return new Date(iso).toLocaleString("ko-KR", { timeZone: "Asia/Seoul", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}

type Person = { id: number; name: string };

/** 직원 관리(o15a~c). 초대, 합류 요청 승인·거절, 함께 일하는 직원 내보내기. */
export default function OwnerMembersPage() {
  const { state } = useApp();
  const queryClient = useQueryClient();
  const feedback = useFeedback();
  const members = useQuery(membersQuery(state.token, state.storeId));
  const [rejecting, setRejecting] = useState<Person | null>(null);
  const [removing, setRemoving] = useState<Person | null>(null);
  const invalidate = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: queryKeys.members(state.storeId) }),
      queryClient.invalidateQueries({ queryKey: checklistKeys.root(state.storeId) }),
    ]);
  };
  const approve = useMutation({
    mutationFn: (request: Person) => approveJoin(request.id, state.token!),
    onSuccess: (_, request) => feedback.toast(`${request.name}님이 합류했어요`),
    onSettled: invalidate,
  });
  const reject = useMutation({
    mutationFn: (request: Person) => rejectJoin(request.id, state.token!),
    onSuccess: () => {
      setRejecting(null);
      feedback.toast("거절했어요");
    },
    onSettled: invalidate,
  });
  const remove = useMutation({
    mutationFn: (member: Person) => removeMember(member.id, state.token!),
    onSuccess: (_, member) => {
      setRemoving(null);
      feedback.toast(`${member.name}님을 내보냈어요`);
    },
    onSettled: invalidate,
  });
  const staff = members.data?.active.filter((m) => m.role === "STAFF") ?? [];
  const busy = approve.isPending || reject.isPending;

  return (
    <Screen>
      <BackButton parent="/owner/settings" />
      <PageHeader title="직원 관리" />
      <InviteLinkCard />
      <ButtonLink href="/owner/member-shifts" variant="secondary">
        직원 담당 근무조
      </ButtonLink>
      {members.isPending && <Skeleton className="h-40" />}
      {members.isError && (
        <ErrorInline message={apiErrorMessage(members.error, "목록을 불러오지 못했어요.")} onRetry={() => void members.refetch()} retrying={members.isRefetching} />
      )}
      {members.data && members.data.pending.length > 0 && (
        <section className="flex flex-col gap-2">
          <SectionTitle>합류 요청</SectionTitle>
          <Surface as="section" className="px-[18px]">
            <ul className="flex flex-col divide-y divide-background">
              {members.data.pending.map((r) => (
                <li key={r.request_id} data-join-request="" className="flex items-center gap-2 py-3">
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-[16px] font-bold text-ink">{r.name}</p>
                    <p className="text-[13px] text-ink-muted">{kst(r.requested_at)} 요청</p>
                  </div>
                  <TextButton disabled={busy} onClick={() => setRejecting({ id: r.request_id, name: r.name })}>
                    거절
                  </TextButton>
                  <Button
                    className="min-h-10 w-auto! px-4 py-2!"
                    loading={approve.isPending && approve.variables?.id === r.request_id}
                    disabled={busy}
                    onClick={() => approve.mutate({ id: r.request_id, name: r.name })}
                  >
                    승인
                  </Button>
                </li>
              ))}
            </ul>
          </Surface>
          {approve.error && <ErrorInline message={apiErrorMessage(approve.error, "승인하지 못했어요.")} />}
        </section>
      )}
      {members.data && (
        <section className="flex flex-col gap-2">
          <SectionTitle>함께 일하는 직원</SectionTitle>
          {staff.length === 0 && <Empty title="아직 합류한 직원이 없어요" />}
          <ul className="flex flex-col gap-2">
            {staff.map((m) => (
              <li key={m.user_id} data-member="">
                <SwipeRow left={{ label: "내보내기", ariaLabel: `${m.name} 내보내기`, tone: "danger", onAction: () => setRemoving({ id: m.user_id, name: m.name }) }}>
                  <div className="flex min-h-16 flex-col justify-center rounded-[20px] bg-surface px-[18px] py-3 shadow-card">
                    <p className="truncate text-[16px] font-bold text-ink">{m.name}</p>
                    <p className="text-[13px] text-ink-muted">{kst(m.joined_at)} 합류</p>
                  </div>
                </SwipeRow>
              </li>
            ))}
          </ul>
        </section>
      )}
      <ConfirmDialog
        open={Boolean(rejecting)}
        title={`${rejecting?.name ?? ""}님 합류를 거절할까요?`}
        confirmLabel="거절"
        tone="danger"
        loading={reject.isPending}
        error={reject.error ? apiErrorMessage(reject.error, "거절하지 못했어요.") : null}
        onConfirm={() => rejecting && reject.mutate(rejecting)}
        onCancel={() => {
          reject.reset();
          setRejecting(null);
        }}
      />
      <ConfirmDialog
        open={Boolean(removing)}
        title={`${removing?.name ?? ""}님을 내보낼까요?`}
        description="질문과 기록은 남아요."
        confirmLabel="내보내기"
        tone="danger"
        loading={remove.isPending}
        error={remove.error ? apiErrorMessage(remove.error, "내보내지 못했어요.") : null}
        onConfirm={() => removing && remove.mutate(removing)}
        onCancel={() => {
          remove.reset();
          setRemoving(null);
        }}
      />
    </Screen>
  );
}
