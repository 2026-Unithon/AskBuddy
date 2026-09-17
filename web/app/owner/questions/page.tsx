"use client";

import { useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useApp } from "@/lib/store";
import {
  ApiError,
  answerPending,
  type LearnPendingItem,
  type LearnQuestionItem,
} from "@/lib/api";
import { pendingQuery, queryKeys, questionsQuery } from "@/lib/query";

import {
  PendingQuestionCard,
  type AggregatedQuestionItem,
} from "@/components/owner/pending-question-card";
import { AnswerQuestionSheet } from "@/components/owner/answer-question-sheet";
import { EmptyState } from "@/components/owner/empty-state";
import { InlineError } from "@/components/owner/inline-error";
import { SkeletonList } from "@/components/owner/skeleton-list";
import { OwnerPageHeader } from "@/components/owner/owner-page-header";

function aggregateQuestions(rawItems: LearnQuestionItem[]): AggregatedQuestionItem[] {
  const map = new Map<string, {
    items: LearnQuestionItem[];
    firstItem: LearnQuestionItem;
  }>();

  for (const q of rawItems) {
    const key = q.waiting_question_id
      ? `waiting-${q.waiting_question_id}`
      : `text-${q.question_text.trim().toLowerCase()}`;

    const existing = map.get(key);
    if (!existing) {
      map.set(key, { items: [q], firstItem: q });
    } else {
      existing.items.push(q);
    }
  }

  const result: AggregatedQuestionItem[] = [];

  for (const [key, { items, firstItem }] of map.entries()) {
    // 날짜 정렬
    const sorted = [...items].sort(
      (a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime()
    );
    const first = sorted[0];
    const last = sorted[sorted.length - 1];

    const staffSet = new Set(items.map((it) => it.asked_by));
    const hasWaiting = items.some((it) => it.status === "WAITING");
    const hasOwnerAnswered = items.some((it) => it.status === "OWNER_ANSWERED");

    const status = hasWaiting
      ? "WAITING"
      : hasOwnerAnswered
      ? "OWNER_ANSWERED"
      : "HIT";

    const waitingId = items.find((it) => it.waiting_question_id != null)?.waiting_question_id ?? null;

    result.push({
      key,
      waitingQuestionId: waitingId,
      questionText: firstItem.question_text,
      firstAskedAt: first.created_at,
      lastAskedAt: last.created_at,
      distinctStaffCount: staffSet.size,
      occurrenceCount: items.length,
      status,
      answerText:
        [...sorted].reverse().find((item) => item.answer_text)?.answer_text ?? null,
      messageId: firstItem.message_id,
    });
  }

  // 정렬 규칙: 1) 대기 중 우선, 2) 오래 기다린 질문 우선(firstAskedAt 오름차순), 3) 반복 횟수 많은 순
  return result.sort((a, b) => {
    if (a.status === "WAITING" && b.status !== "WAITING") return -1;
    if (a.status !== "WAITING" && b.status === "WAITING") return 1;

    // 둘 다 WAITING일 경우 오래 기다린 순
    if (a.status === "WAITING" && b.status === "WAITING") {
      const timeDiff = new Date(a.firstAskedAt).getTime() - new Date(b.firstAskedAt).getTime();
      if (timeDiff !== 0) return timeDiff;
      return b.occurrenceCount - a.occurrenceCount;
    }

    // 그 외는 최근 질문 순
    return new Date(b.lastAskedAt).getTime() - new Date(a.lastAskedAt).getTime();
  });
}

function normalizeQuestion(text: string) {
  return text.trim().replace(/\s+/g, " ").toLowerCase();
}

function mergePendingQuestions(
  pendingItems: LearnPendingItem[],
  historyItems: AggregatedQuestionItem[]
): AggregatedQuestionItem[] {
  const historyByText = new Map(
    historyItems.map((item) => [normalizeQuestion(item.questionText), item])
  );

  return pendingItems.map((item) => {
    const history = historyByText.get(normalizeQuestion(item.question_text));
    return {
      key: `waiting-${item.question_id}`,
      waitingQuestionId: item.question_id,
      questionText: item.question_text,
      firstAskedAt: history?.firstAskedAt ?? item.created_at,
      lastAskedAt: history?.lastAskedAt ?? item.created_at,
      distinctStaffCount: history?.distinctStaffCount ?? 1,
      occurrenceCount: history?.occurrenceCount ?? 1,
      status: "WAITING",
      answerText: null,
      messageId: history?.messageId ?? -item.question_id,
    };
  });
}

export default function QuestionsPage() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const { state } = useApp();
  const queryClient = useQueryClient();

  const [activeTab, setActiveTab] = useState<"waiting" | "all">("waiting");
  const [selectedQuestion, setSelectedQuestion] = useState<AggregatedQuestionItem | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);

  const targetQuestionId = /^\d+$/.test(searchParams.get("question_id") ?? "")
    ? Number(searchParams.get("question_id"))
    : null;

  const questions = useQuery(questionsQuery(state.token, state.storeId));
  const pending = useQuery(pendingQuery(state.token, state.storeId));
  const historyItems = useMemo(
    () => aggregateQuestions(questions.data?.items ?? []),
    [questions.data?.items]
  );

  const waitingItems = useMemo(
    () => mergePendingQuestions(pending.data?.items ?? [], historyItems),
    [historyItems, pending.data?.items]
  );

  const aggregated = useMemo(() => {
    const waitingTexts = new Set(waitingItems.map((item) => normalizeQuestion(item.questionText)));
    return [
      ...waitingItems,
      ...historyItems.filter(
        (item) =>
          item.status !== "WAITING" && !waitingTexts.has(normalizeQuestion(item.questionText))
      ),
    ];
  }, [historyItems, waitingItems]);

  const displayedItems = activeTab === "waiting" ? waitingItems : aggregated;
  const targetQuestion = useMemo(
    () =>
      targetQuestionId === null
        ? null
        : waitingItems.find((item) => item.waitingQuestionId === targetQuestionId) ?? null,
    [targetQuestionId, waitingItems]
  );
  const activeQuestion = selectedQuestion ?? targetQuestion;

  function closeAnswerSheet() {
    setSelectedQuestion(null);
    if (targetQuestionId !== null) router.replace("/owner/questions");
  }

  const answerMutation = useMutation({
    mutationFn: ({ questionId, text }: { questionId: number; text: string }) =>
      answerPending(questionId, text, state.token!),
    onSuccess: () => {
      setSubmitError(null);
      void Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.bootstrap(state.userId, state.storeId) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.questions(state.storeId) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.pending(state.storeId) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.proposals(state.storeId) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.cardLists(state.storeId) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.notificationsRoot(state.storeId) }),
      ]);
    },
    onError: (err) => {
      setSubmitError(
        err instanceof ApiError
          ? err.detail || "답변을 저장하지 못했어요."
          : "서버에 연결할 수 없습니다. 입력 내용은 보존되었습니다."
      );
    },
  });

  async function handleAnswerSubmit(questionId: number, answerText: string) {
    setSubmitError(null);
    await answerMutation.mutateAsync({ questionId, text: answerText });
  }

  const queryError = pending.error ?? questions.error;
  const queryErrorMessage = queryError instanceof ApiError
    ? queryError.detail || "질문 목록을 불러오지 못했어요."
    : queryError
    ? "서버에 연결할 수 없습니다."
    : null;

  return (
    <div className="flex-1 flex flex-col w-full bg-background min-h-dvh">
      <OwnerPageHeader
        title="답변 대기"
        subtitle="매장 지식으로 답하지 못한 직원 질문"
        isFetching={questions.isFetching || pending.isFetching}
        isLoading={questions.isLoading || pending.isLoading}
      />

      {/* 메인 콘텐츠 (하단 탭 바 높이 고려 pb-24) */}
      <main className="flex-1 space-y-3.5 px-4 py-3.5 pb-[calc(6rem+env(safe-area-inset-bottom,0px))] overflow-y-auto">
        {/* 필터 세그먼트 (대기 중 / 전체 질문) */}
        <div className="grid grid-cols-2 gap-1.5 rounded-2xl bg-surface-muted p-1.5 border border-border/50">
          <button
            type="button"
            onClick={() => setActiveTab("waiting")}
            aria-pressed={activeTab === "waiting"}
            className={`min-h-[44px] rounded-xl text-xs font-bold transition-all active:scale-95 flex items-center justify-center gap-1.5 ${
              activeTab === "waiting"
                ? "bg-surface text-brand-700 shadow-xs"
                : "text-muted hover:text-foreground"
            }`}
          >
            <span>답변 대기</span>
            <span
              className={`px-1.5 py-0.5 rounded-full text-xs font-extrabold ${
                waitingItems.length > 0
                  ? "bg-warn-500 text-white"
                  : "bg-surface-muted text-muted"
              }`}
            >
              {waitingItems.length}
            </span>
          </button>
          <button
            type="button"
            onClick={() => setActiveTab("all")}
            aria-pressed={activeTab === "all"}
            className={`min-h-[44px] rounded-xl text-xs font-bold transition-all active:scale-95 flex items-center justify-center gap-1.5 ${
              activeTab === "all"
                ? "bg-surface text-brand-700 shadow-xs"
                : "text-muted hover:text-foreground"
            }`}
          >
            <span>전체 질문</span>
            <span className="text-xs font-medium text-muted">
              ({aggregated.length})
            </span>
          </button>
        </div>

        {/* 쿼리 에러 안내 */}
        {queryErrorMessage && (
          <InlineError
            message={queryErrorMessage}
            isRetrying={pending.isFetching || questions.isFetching}
            onRetry={() => {
              void Promise.all([pending.refetch(), questions.refetch()]);
            }}
          />
        )}

        {/* 로딩 스켈레톤 */}
        {(questions.isLoading || pending.isLoading) && displayedItems.length === 0 && (
          <div className="space-y-3 pt-1">
            <SkeletonList count={4} heightClass="h-28" label="질문 목록 불러오는 중" />
          </div>
        )}

        {/* 빈 상태 (가짜 데이터 없음) */}
        {!questions.isLoading && !pending.isLoading && !queryErrorMessage && displayedItems.length === 0 && (
          <EmptyState
            icon={activeTab === "waiting" ? "🎉" : "💬"}
            title={activeTab === "waiting" ? "답변을 기다리는 질문이 없어요" : "아직 등록된 질문이 없어요"}
            description={
              activeTab === "waiting"
                ? "직원이 모르는 업무를 질문하면 사장님 답변을 위해 여기에 모입니다."
                : "직원이 Buddy에게 질문을 시작하면 이곳에서 전체 질의응답 이력을 확인할 수 있습니다."
            }
          />
        )}

        {/* 질문 카드 목록 */}
        <div className="space-y-2.5">
          {displayedItems.map((item) => (
            <PendingQuestionCard
              key={item.key}
              item={item}
              isSelected={item.key === activeQuestion?.key}
              onSelect={(selected) => setSelectedQuestion(selected)}
            />
          ))}
        </div>
      </main>

      {/* 모바일 바텀시트 답변 창 */}
      <AnswerQuestionSheet
        key={activeQuestion?.key ?? "closed"}
        item={activeQuestion}
        onClose={closeAnswerSheet}
        onSubmit={handleAnswerSubmit}
        isSubmitting={answerMutation.isPending}
        error={submitError}
      />
    </div>
  );
}
