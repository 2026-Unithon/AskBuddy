"use client";

import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import {
  Button,
  Caption,
  CardLink,
  Coachmark,
  CountBadge,
  Empty,
  ErrorInline,
  HeaderActions,
  OWNER_TABS,
  PageHeader,
  RefreshingHint,
  Screen,
  SectionTitle,
  Skeleton,
  TabBar,
} from "@/components/kit";
import { OwnerChecklistStatus } from "@/components/checklist/owner-status";
import { ActiveJobBanner } from "@/components/owner/active-job-banner";
import { FinishedJobBanner } from "@/components/owner/finished-job-banner";
import { OwnerAddComposer } from "@/components/owner/owner-add-composer";
import { TodayTasksSection } from "@/components/owner/today-tasks-section";
import { apiErrorMessage } from "@/lib/api";
import { bootstrapQuery, rPendingQuery } from "@/lib/query";
import { WaitingQuestionList } from "@/components/owner/waiting-question-list";
import { useCardReviewCount } from "@/lib/card-review-count";
import { useApp } from "@/lib/store";

// 처음 한 번 안내(o01a). 화면이 다시 그려질 때마다 새 배열이면 안내가 처음부터 다시 기다리므로 밖에 둔다
const HOME_COACH = [
  { target: '[aria-label="마이페이지"]', text: "매장 설정은 여기서 바꿔요" },
  { target: '[aria-label^="알림"]', text: "질문이 오면 여기에 알려 드려요" },
  { target: 'textarea[aria-label="새로 알려줄 것"]', text: "사진, 파일, 글 아무거나 넣으면 정리해 드려요" },
];

// O6 오늘 매장: 확인해 주세요(대기 질문) + 새로 알려줄 것 넣기.
export default function OwnerTodayPage() {
  const { state } = useApp();
  const bootstrap = useQuery(bootstrapQuery(state.token, state.userId, state.storeId));
  const pending = useInfiniteQuery(rPendingQuery(state.token, state.storeId, state.userId, "WAITING"));
  const storeName = bootstrap.data?.store?.store_name ?? "";
  const review = useCardReviewCount();
  const waiting = pending.data?.pages.flatMap((page) => page.questions).filter((q) => q.status === "WAITING") ?? [];

  return (
    <Screen tabBar={<TabBar tabs={OWNER_TABS} badges={{ "/owner/cards": review.count }} />} footer={<OwnerAddComposer />} hideFooterOnScroll>
      <Coachmark id="owner-home" steps={HOME_COACH} />
      <PageHeader
        eyebrow={storeName || " "}
        title="오늘 매장"
        action={<HeaderActions role="OWNER" />}
      />
      <ActiveJobBanner />
      <FinishedJobBanner />

      <OwnerChecklistStatus />
      <CardLink href="/owner/report" title="매장 리포트" meta="알바생 질문, AI 답변, 사장님께 넘어온 건수" />
      <TodayTasksSection />
      <SectionTitle>
        확인해 주세요
        {waiting.length > 0 && <CountBadge n={pending.hasNextPage ? 100 : waiting.length} />}
      </SectionTitle>
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
      <WaitingQuestionList questions={waiting} />
      {pending.hasNextPage && (
        <Button variant="secondary" loading={pending.isFetchingNextPage} onClick={() => void pending.fetchNextPage()}>
          질문 더 보기
        </Button>
      )}
      <RefreshingHint active={pending.isRefetching && !pending.isLoading} />
      {waiting.length > 0 && <Caption>새 질문이 오면 바로 알려드려요</Caption>}
      <CardLink href="/owner/guide/service" title="응대 매뉴얼 만들기" meta="손님, 배달, 돌발 상황 대응을 미리 알려 두기" />
    </Screen>
  );
}
