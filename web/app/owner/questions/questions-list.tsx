"use client";

import { useState } from "react";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { BackButton, Button, ButtonLink, Caption, Chip, Empty, ErrorInline, PageHeader, RefreshingHint, Screen, Skeleton, Surface } from "@/components/kit";
import { apiErrorMessage } from "@/lib/api";
import { questionsQuery, rPendingQuery } from "@/lib/query";
import { useApp } from "@/lib/store";
import { OwnerBottomNav } from "@/components/owner/owner-bottom-nav";

export function QuestionsList() {
  const { state } = useApp();
  const [tab, setTab] = useState<"waiting" | "all">("waiting");
  const pending = useInfiniteQuery(rPendingQuery(state.token, state.storeId, state.userId, tab === "waiting" ? "WAITING" : undefined));
  const history = useQuery({ ...questionsQuery(state.token, state.storeId), enabled: Boolean(state.token && state.storeId && tab === "all") });
  const questions = pending.data?.pages.flatMap((page) => page.questions) ?? [];
  // 서로 다른 문맥의 질문은 같은 문장이어도 합치지 않는다.
  const items = questions.filter((q) => tab === "all" || q.status === "WAITING");
  return (
    <Screen tabBar={<OwnerBottomNav />}>
      <BackButton href="/owner" label="오늘 매장" />
      <PageHeader title="직원 질문" description="답을 전달한 뒤 카드 반영 상태까지 확인할 수 있어요." />
      <div className="flex gap-2">
        <Button variant={tab === "waiting" ? "primary" : "secondary"} onClick={() => setTab("waiting")}>답변 대기</Button>
        <Button variant={tab === "all" ? "primary" : "secondary"} onClick={() => setTab("all")}>전체 이력</Button>
      </div>
      {pending.isLoading && <><Skeleton className="h-24" /><Skeleton className="h-24" /></>}
      {pending.error && <ErrorInline message={apiErrorMessage(pending.error, "질문을 불러오지 못했어요.")} onRetry={() => void pending.refetch()} retrying={pending.isRefetching} />}
      {pending.data && !pending.error && items.length === 0 && (
        <Empty title={pending.hasNextPage ? "불러온 질문에는 대기 중인 질문이 없어요" : tab === "waiting" ? "답변을 기다리는 질문이 없어요" : "아직 직원 질문이 없어요"}
          description={pending.hasNextPage ? "다음 질문을 더 불러와 확인해 주세요." : "직원이 물어보면 여기서 확인할 수 있어요."} />
      )}
      {items.map((q) => <Surface key={q.pending_id} className="flex flex-col gap-3 p-4">
        <Chip tone={q.status === "WAITING" ? "warn" : "neutral"}>{q.status === "WAITING" ? "답변 대기" : "답변 전달됨"}</Chip>
        <p className="whitespace-pre-wrap text-[16px] font-bold">{q.question}</p>
        <ButtonLink href={`/owner/questions/${q.pending_id}`} variant="secondary">{q.status === "WAITING" ? "답변하기" : "답변·카드 상태 보기"}</ButtonLink>
      </Surface>)}
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
