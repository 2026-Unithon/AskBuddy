"use client";

import { useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Badge, Buddy, BuddyBubble, Button, Card, Input } from "@/components/ui";
import { OwnerPrimaryNav } from "@/components/owner-primary-nav";
import { useApp } from "@/lib/store";
import { ApiError, answerPending, type LearnPendingItem, type LearnStaffItem } from "@/lib/api";
import { notificationsQuery, pendingQuery, queryKeys, staffQuery } from "@/lib/query";
import type { PendingQuestion, StaffLevel, StaffMember } from "@/lib/types";

const LEVEL_TONE: Record<StaffLevel, "brand" | "warn" | "danger"> = {
  great: "brand",
  good: "warn",
  warn: "danger",
};
const LEVEL_LABEL: Record<StaffLevel, string> = {
  great: "투입 가능",
  good: "괜찮아요",
  warn: "확인이 필요해요",
};

function staffLevel(progressRate: number, deployThreshold: number): StaffLevel {
  if (progressRate >= deployThreshold) return "great";
  if (progressRate >= 50) return "good";
  return "warn";
}

function toStaff(item: LearnStaffItem, deployThreshold: number): StaffMember {
  const progressPct = Math.round(item.progress_rate);
  return {
    id: String(item.member_id),
    name: item.name,
    label: `알바생 (${item.day_count}일차)`,
    progressPct,
    level: staffLevel(progressPct, deployThreshold),
  };
}

function toPending(item: LearnPendingItem): PendingQuestion {
  return {
    id: String(item.question_id),
    askedBy: item.asked_by,
    questionText: item.question_text,
    createdAt: item.created_at,
  };
}

export default function DashboardPage() {
  const { state } = useApp();
  const queryClient = useQueryClient();
  const pending = useQuery(pendingQuery(state.token, state.storeId));
  const staffResult = useQuery(staffQuery(state.token, state.storeId));
  const notifications = useQuery(notificationsQuery(state.token, state.storeId));
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const threshold = staffResult.data?.deploy_threshold ?? 80;
  const staff = (staffResult.data?.items ?? []).map((item) => toStaff(item, threshold));
  const pendingQuestions = (pending.data?.items ?? []).map(toPending);
  const unreadCount = notifications.data?.unread_count ?? 0;
  const answer = useMutation({
    mutationFn: ({ id, text }: { id: string; text: string }) =>
      answerPending(Number(id), text, state.token!),
    onSuccess: async (_, variables) => {
      setDrafts((d) => ({ ...d, [variables.id]: "" }));
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.pending(state.storeId) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.questions(state.storeId) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.proposals(state.storeId) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.cardLists(state.storeId) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.notificationsRoot(state.storeId) }),
      ]);
    },
  });
  const queryError = pending.error ?? staffResult.error;
  const error = answer.error ?? queryError;
  const errorText = error instanceof ApiError
    ? error.detail || "정보를 불러오지 못했어요"
    : error
      ? "서버에 연결할 수 없습니다"
      : null;

  const avgProgress = staff.length === 0
    ? 0
    : Math.round(staff.reduce((sum, s) => sum + s.progressPct, 0) / staff.length);

  async function submitAnswer(id: string) {
    const text = drafts[id]?.trim();
    if (!text || !state.token || answer.isPending) return;
    answer.mutate({ id, text });
  }

  return (
    <div className="min-h-dvh w-full bg-background">
      <div className="bg-brand-700 px-5 sm:px-8 pt-8 pb-7">
        <div className="max-w-5xl mx-auto">
          <Link
            href="/role"
            className="inline-flex items-center gap-1.5 mb-4 text-white/70 hover:text-white transition-colors text-xs font-semibold"
          >
            ← 이전으로
          </Link>
          <div className="flex items-center justify-between mb-5">
            <div>
              <p className="text-white/55 text-xs font-semibold">사장님 대시보드</p>
              <h1 className="text-2xl font-bold text-white">{state.storeName}</h1>
            </div>
            <div className="flex items-center gap-2">
              <Link
                href="/owner/notifications"
                aria-label={`알림${unreadCount ? ` ${unreadCount}개 읽지 않음` : ""}`}
                className="relative w-10 h-10 rounded-full bg-white/12 text-white flex items-center justify-center"
              >
                🔔
                {unreadCount > 0 && (
                  <span className="absolute -top-1 -right-1 min-w-5 h-5 px-1 rounded-full bg-[#E57373] text-[10px] font-bold flex items-center justify-center">
                    {unreadCount > 99 ? "99+" : unreadCount}
                  </span>
                )}
              </Link>
              <Buddy size={44} />
            </div>
          </div>
          <div className="grid grid-cols-3 gap-2.5 max-w-md">
            {[
              { label: "등록 직원", value: `${staff.length}명` },
              { label: "평균 이해도", value: `${avgProgress}%` },
              { label: "대기 질문", value: `${pendingQuestions.length}건` },
            ].map((s) => (
              <div key={s.label} className="bg-white/12 rounded-2xl py-3 text-center">
                <p className="text-xl font-bold text-white">{s.value}</p>
                <p className="text-[11px] text-white/55 font-medium">{s.label}</p>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="max-w-5xl mx-auto px-5 sm:px-8 pt-5 flex items-center gap-2">
        <div className="w-full max-w-md">
          <OwnerPrimaryNav />
        </div>
      </div>

      <div className="max-w-5xl mx-auto px-5 sm:px-8 py-6 grid grid-cols-1 lg:grid-cols-2 gap-6">
        <section className="space-y-3">
          <h2 className="text-base font-bold text-brand-700">직원 이해도</h2>
          <Card className="divide-y divide-border">
            {staffResult.isLoading && <div className="h-20 animate-pulse bg-surface-muted" aria-label="직원 목록 불러오는 중" />}
            {staff.map((s) => (
              <div key={s.id} className="p-4 flex items-center gap-3">
                <div className="w-10 h-10 rounded-full bg-brand-700 text-white flex items-center justify-center font-bold text-sm">
                  {s.name.slice(0, 1)}
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium">{s.name}</p>
                  <p className="text-xs text-muted">{s.label}</p>
                </div>
                <Badge tone={LEVEL_TONE[s.level]}>
                  {s.progressPct}% · {LEVEL_LABEL[s.level]}
                </Badge>
              </div>
            ))}
            {!staffResult.isLoading && staff.length === 0 && (
              <p className="p-4 text-sm text-muted">아직 합류한 직원이 없어요.</p>
            )}
          </Card>

          <h2 className="text-base font-bold text-brand-700 pt-2">빈 지식 알림</h2>
          <div className="bg-accent-100 border border-accent-500/30 rounded-2xl p-4 space-y-3">
            <BuddyBubble text="이 부분은 아직 아무도 안 알려줬어요!" size={32} />
            {state.emptyKnowledge.map((g) => (
              <div key={g.id} className="flex items-center justify-between bg-surface rounded-xl px-3 py-2.5">
                <span className="text-xs font-semibold">❓ {g.topic}</span>
                <button className="text-xs font-bold text-brand-500">추가하기</button>
              </div>
            ))}
            {state.emptyKnowledge.length === 0 && (
              <p className="text-xs text-muted px-1">빈 지식이 없어요.</p>
            )}
          </div>
        </section>

        <section className="space-y-3">
          <h2 className="text-base font-bold text-brand-700">답변 대기 질문</h2>
          <BuddyBubble
            text="답변하면 Buddy 지식에 자동 반영되고 신입 화면의 배지가 사라져요"
            size={32}
          />
          {errorText && <p className="text-xs font-medium text-[#E57373] px-1">{errorText}</p>}
          <div className="flex flex-col gap-3">
            {pending.isLoading && <div className="h-32 animate-pulse rounded-2xl bg-surface-muted" aria-label="대기 질문 불러오는 중" />}
            {pending.isFetching && !pending.isLoading && <p className="text-[11px] text-muted">최신 질문 확인 중…</p>}
            {pendingQuestions.map((q) => (
              <Card key={q.id} className="p-4 space-y-3">
                <div>
                  <p className="text-xs text-muted">{q.askedBy}님의 질문</p>
                  <p className="text-sm font-medium mt-0.5">{q.questionText}</p>
                </div>
                <div className="flex gap-2">
                  <Input
                    placeholder="답변을 입력하세요"
                    value={drafts[q.id] ?? ""}
                    onChange={(e) => setDrafts((d) => ({ ...d, [q.id]: e.target.value }))}
                    onKeyDown={(e) => e.key === "Enter" && submitAnswer(q.id)}
                    disabled={answer.isPending && answer.variables?.id === q.id}
                  />
                  <Button onClick={() => submitAnswer(q.id)} disabled={answer.isPending}>
                    {answer.isPending && answer.variables?.id === q.id ? "저장 중" : "답변"}
                  </Button>
                </div>
              </Card>
            ))}
            {!pending.isLoading && pendingQuestions.length === 0 && (
              <Card className="p-6 text-center text-sm text-muted">대기 중인 질문이 없어요 🎉</Card>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}
