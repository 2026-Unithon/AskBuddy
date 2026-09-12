"use client";

import { useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Badge, BuddyBubble, Button, Card, Input, Shell, TopBar } from "@/components/ui";
import { OwnerPrimaryNav } from "@/components/owner-primary-nav";
import { useApp } from "@/lib/store";
import { ApiError, answerPending, type LearnQuestionItem } from "@/lib/api";
import { queryKeys, questionsQuery } from "@/lib/query";

function formatAskedAt(iso: string) {
  return new Date(iso).toLocaleString("ko-KR", {
    timeZone: "Asia/Seoul",
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function statusBadge(status: LearnQuestionItem["status"]) {
  if (status === "WAITING") return { tone: "warn" as const, label: "대기" };
  if (status === "OWNER_ANSWERED") return { tone: "brand" as const, label: "사장님 답" };
  return { tone: "neutral" as const, label: "지식 답" };
}

export default function QuestionsPage() {
  const router = useRouter();
  const params = useSearchParams();
  const { state } = useApp();
  const targetQuestionId = /^\d+$/.test(params.get("question_id") ?? "")
    ? Number(params.get("question_id"))
    : null;
  const queryClient = useQueryClient();
  const questions = useQuery(questionsQuery(state.token, state.storeId));
  const [drafts, setDrafts] = useState<Record<number, string>>({});
  const answer = useMutation({
    mutationFn: ({ questionId, text }: { questionId: number; messageId: number; text: string }) =>
      answerPending(questionId, text, state.token!),
    onSuccess: async (_, variables) => {
      setDrafts((d) => ({ ...d, [variables.messageId]: "" }));
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.questions(state.storeId) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.pending(state.storeId) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.proposals(state.storeId) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.cardLists(state.storeId) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.notificationsRoot(state.storeId) }),
      ]);
    },
  });

  const allItems = questions.data?.items ?? [];
  const showAll = params.get("view") === "all";
  const items = showAll ? allItems : allItems.filter((item) => item.status === "WAITING");
  const error = questions.error ?? answer.error;
  const errorText = error instanceof ApiError
    ? error.detail || "질문을 불러오지 못했어요"
    : error
      ? "서버에 연결할 수 없습니다"
      : null;

  async function submitAnswer(item: LearnQuestionItem) {
    const waitingId = item.waiting_question_id;
    const text = drafts[item.message_id]?.trim();
    if (!waitingId || !text || !state.token || answer.isPending) return;
    answer.mutate({ questionId: waitingId, messageId: item.message_id, text });
  }

  return (
    <Shell>
      <TopBar title="전체 질문" backHref="/owner/dashboard" />
      <div className="px-5 pb-3"><OwnerPrimaryNav /></div>
      <div className="px-5 pt-1 pb-3">
        <BuddyBubble text={params.get("view") === "all" ? "알바가 물은 질문과 답변 기록을 최신순으로 보여 드려요." : "아직 근거가 부족해 사장님 답변을 기다리는 질문이에요."} />
      </div>
      <div className="px-5 flex-1 overflow-y-auto pb-6 space-y-3">
        <div className="grid grid-cols-2 gap-2 rounded-2xl bg-surface-muted p-1.5">
          <button onClick={() => router.replace("/owner/questions")} className={`min-h-11 rounded-xl text-xs font-bold ${!showAll ? "bg-surface text-brand-700 shadow-sm" : "text-muted"}`}>답변 대기</button>
          <button onClick={() => router.replace("/owner/questions?view=all")} className={`min-h-11 rounded-xl text-xs font-bold ${showAll ? "bg-surface text-brand-700 shadow-sm" : "text-muted"}`}>전체 질문</button>
        </div>
        {questions.isFetching && !questions.isLoading && <p className="text-[11px] text-muted">최신 질문 확인 중…</p>}
        {questions.isLoading && <div className="space-y-3" aria-label="질문 불러오는 중">{[0, 1, 2].map((item) => <div key={item} className="h-28 animate-pulse rounded-2xl bg-surface-muted" />)}</div>}
        {errorText && <p className="text-xs font-medium text-[#E57373]">{errorText}</p>}
        {!questions.isLoading && items.length === 0 && !errorText && (
          <Card className="p-6 text-center text-sm text-muted">{showAll ? "아직 질문이 없어요" : "답변을 기다리는 질문이 없어요 🎉"}</Card>
        )}
        {items.map((q) => {
          const badge = statusBadge(q.status);
          const canAnswer = q.status === "WAITING" && q.waiting_question_id != null;
          return (
            <Card key={q.message_id} className={`p-4 space-y-3 ${q.waiting_question_id === targetQuestionId ? "border-brand-500 ring-2 ring-brand-500/20" : ""}`}>
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="text-xs text-muted">
                    {q.asked_by}님 · {formatAskedAt(q.created_at)}
                  </p>
                  <p className="text-sm font-medium mt-0.5">{q.question_text}</p>
                </div>
                <Badge tone={badge.tone}>{badge.label}</Badge>
              </div>
              {q.answer_text && (
                <p className="text-sm text-foreground whitespace-pre-wrap bg-brand-50 rounded-xl px-3 py-2">
                  {q.answer_text}
                </p>
              )}
              {canAnswer && (
                <div className="flex gap-2">
                  <Input
                    placeholder="답변을 입력하세요"
                    value={drafts[q.message_id] ?? ""}
                    onChange={(e) => setDrafts((d) => ({ ...d, [q.message_id]: e.target.value }))}
                    onKeyDown={(e) => e.key === "Enter" && submitAnswer(q)}
                    disabled={answer.isPending && answer.variables?.questionId === q.waiting_question_id}
                  />
                  <Button onClick={() => submitAnswer(q)} disabled={answer.isPending}>
                    {answer.isPending && answer.variables?.questionId === q.waiting_question_id ? "저장 중" : "답변"}
                  </Button>
                </div>
              )}
            </Card>
          );
        })}
      </div>
    </Shell>
  );
}
