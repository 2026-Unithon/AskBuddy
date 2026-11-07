"use client";

import { useState } from "react";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { BackButton, Button, Caption, CardLink, Empty, ErrorInline, PageHeader, RefreshingHint, Screen, Segmented, Skeleton, Stagger, Surface } from "@/components/kit";
import { WaitingQuestionList } from "@/components/owner/waiting-question-list";
import { apiErrorMessage } from "@/lib/api";
import { questionsQuery, rPendingQuery } from "@/lib/query";
import { useApp } from "@/lib/store";

export function QuestionsList() {
  const { state } = useApp();
  const [tab, setTab] = useState<"waiting" | "all">("waiting");
  const pending = useInfiniteQuery(rPendingQuery(state.token, state.storeId, state.userId, tab === "waiting" ? "WAITING" : undefined));
  const history = useQuery({ ...questionsQuery(state.token, state.storeId), enabled: Boolean(state.token && state.storeId && tab === "all") });
  const questions = pending.data?.pages.flatMap((page) => page.questions) ?? [];
  // 서로 다른 문맥의 질문은 같은 문장이어도 합치지 않는다.
  const items = questions.filter((q) => tab === "all" || q.status === "WAITING");
  const waitingCount = tab === "waiting" ? items.length : questions.filter((q) => q.status === "WAITING").length;
  return (
    <Screen>
      <BackButton parent="/owner" label="오늘 매장" />
      <PageHeader title="직원 질문" description="답을 전달한 뒤 카드 반영 상태까지 확인할 수 있어요." />
      <Segmented
        label="질문 보기"
        value={tab}
        onChange={(value) => setTab(value as "waiting" | "all")}
        options={[
          { value: "waiting", label: "답변 대기", badge: waitingCount },
          { value: "all", label: "전체 이력" },
        ]}
      />
      {pending.isLoading && <><Skeleton className="h-24" /><Skeleton className="h-24" /></>}
      {pending.error && <ErrorInline message={apiErrorMessage(pending.error, "질문을 불러오지 못했어요.")} onRetry={() => void pending.refetch()} retrying={pending.isRefetching} />}
      {pending.data && !pending.error && items.length === 0 && (
        <Empty title={pending.hasNextPage ? "불러온 질문에는 대기 중인 질문이 없어요" : tab === "waiting" ? "답변을 기다리는 질문이 없어요" : "아직 직원 질문이 없어요"}
          description={pending.hasNextPage ? "다음 질문을 더 불러와 확인해 주세요." : "직원이 물어보면 여기서 확인할 수 있어요."} />
      )}
      {/* 기다리는 질문은 눌러서 시트로 바로 답하고(o09b), 답한 질문은 상세로 간다 */}
      <WaitingQuestionList questions={items.filter((q) => q.status === "WAITING")} meta="답변 대기" />
      <Stagger>
        {items.filter((q) => q.status !== "WAITING").map((q) => (
          <CardLink key={q.pending_id} href={`/owner/questions/${q.pending_id}`} title={q.question} meta="답변 전달됨" />
        ))}
      </Stagger>
      {pending.hasNextPage && <Button variant="secondary" loading={pending.isFetchingNextPage} disabled={pending.isFetchingNextPage} onClick={() => void pending.fetchNextPage()}>질문 더 보기</Button>}
      <RefreshingHint active={pending.isRefetching && !pending.isLoading} />
      {tab === "all" && <>
        <Caption>이전 Buddy 답변 이력</Caption>
        {history.isLoading && <Skeleton className="h-24" />}
        {history.error && <ErrorInline message={apiErrorMessage(history.error, "이전 이력을 불러오지 못했어요.")} onRetry={() => void history.refetch()} retrying={history.isRefetching} />}
        {history.data?.items.filter((q) => q.status === "HIT").map((q) => <Surface key={q.message_id} className="space-y-2 p-4">
          <p className="font-bold">{q.question_text}</p><p className="whitespace-pre-wrap">{q.answer_text}</p>
        </Surface>)}
      </>}
    </Screen>
  );
}
