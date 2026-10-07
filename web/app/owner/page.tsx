"use client";

import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import {
  Button,
  Caption,
  CardLink,
  Empty,
  ErrorInline,
  OWNER_TABS,
  PageHeader,
  RefreshingHint,
  Screen,
  SectionTitle,
  SettingsButton,
  Skeleton,
  TabBar,
} from "@/components/kit";
import { OwnerAddComposer } from "@/components/owner/owner-add-composer";
import { apiErrorMessage } from "@/lib/api";
import { bootstrapQuery, rPendingQuery } from "@/lib/query";
import { useApp } from "@/lib/store";

// O6 오늘 매장: 확인해 주세요(대기 질문) + 새로 알려줄 것 넣기.
// 영업 현황 카드(근무조 체크)는 P5 체크리스트에서 붙인다.
export default function OwnerTodayPage() {
  const { state } = useApp();
  const bootstrap = useQuery(bootstrapQuery(state.token, state.userId, state.storeId));
  const pending = useInfiniteQuery(rPendingQuery(state.token, state.storeId, state.userId));
  const storeName = bootstrap.data?.store?.store_name ?? "";
  const waiting = pending.data?.pages.flatMap((page) => page.questions).filter((q) => q.status === "WAITING") ?? [];

  return (
    <Screen tabBar={<TabBar tabs={OWNER_TABS} />} footer={<OwnerAddComposer />}>
      <PageHeader
        eyebrow={storeName || " "}
        title="오늘 매장"
        action={<SettingsButton href="/owner/settings" initial={storeName} />}
      />

      <SectionTitle>확인해 주세요{waiting.length > 0 ? ` · ${waiting.length}${pending.hasNextPage ? "+" : ""}` : ""}</SectionTitle>
      {pending.isLoading && (
        <>
          <Skeleton className="h-[76px]" />
          <Skeleton className="h-[76px]" />
        </>
      )}
      {pending.error && (
        <ErrorInline
          message={apiErrorMessage(pending.error, "질문 목록을 불러오지 못했어요.")}
          onRetry={() => void pending.refetch()}
          retrying={pending.isRefetching}
        />
      )}
      {pending.data && waiting.length === 0 && !pending.hasNextPage && (
        <Empty buddy={false} title="지금은 기다리는 질문이 없어요" description="직원이 매장 카드에 없는 걸 물어보면 여기로 와요" />
      )}
      {waiting.map((question) => (
        <CardLink
          key={question.pending_id}
          href={`/owner/questions/${question.pending_id}`}
          title={question.question}
          meta="답하면 카드로 남아요"
        />
      ))}
      {pending.hasNextPage && (
        <Button variant="secondary" loading={pending.isFetchingNextPage} onClick={() => void pending.fetchNextPage()}>
          질문 더 보기
        </Button>
      )}
      <RefreshingHint active={pending.isRefetching && !pending.isLoading} />
      {waiting.length > 0 && <Caption>새 질문이 오면 바로 알려드려요</Caption>}
    </Screen>
  );
}
