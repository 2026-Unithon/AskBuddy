"use client";

import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useMemo, useState } from "react";
import {
  Button,
  Chip,
  Empty,
  ErrorInline,
  Icon,
  ListGroup,
  ListRow,
  OWNER_TABS,
  PageHeader,
  RefreshingHint,
  Screen,
  Skeleton,
  TabBar,
  focusRing,
} from "@/components/kit";
import { apiErrorMessage, type CardFilters, type CardListItem } from "@/lib/api";
import { cardsInfiniteQuery, proposalsQuery } from "@/lib/query";
import { useApp } from "@/lib/store";

const FILTERS: { value: NonNullable<CardFilters["status"]>; label: string }[] = [
  { value: "all", label: "전체" },
  { value: "needs_review", label: "확인 필요" },
  { value: "pending", label: "공개 전" },
  { value: "excluded", label: "지운 카드" },
];

const ROW_BADGE: Partial<Record<CardListItem["review_status"], { label: string; tone: "warn" | "neutral" | "danger" }>> = {
  NEEDS_REVIEW: { label: "확인 필요", tone: "warn" },
  PENDING: { label: "공개 전", tone: "neutral" },
  EXCLUDED: { label: "지움", tone: "danger" },
};

/** 본문 첫 두 줄을 " · "로 이어 한 줄 요약으로 쓴다 (Figma O9 부제). */
function summary(content: string) {
  return content
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .slice(0, 2)
    .join(" · ");
}

// O9 카드: 카테고리별 묶음 + 검색 + 상태 필터. 알림 딥링크의 status/job_id/category_id/query 를 그대로 받는다.
function CardsScreen() {
  const router = useRouter();
  const params = useSearchParams();
  const { state } = useApp();

  const rawStatus = params.get("status");
  const status = FILTERS.some((f) => f.value === rawStatus) ? (rawStatus as CardFilters["status"]) : "all";
  const rawJobId = params.get("job_id");
  const jobId = rawJobId && /^\d+$/.test(rawJobId) ? Number(rawJobId) : undefined;
  const rawCategoryId = params.get("category_id");
  const categoryId = rawCategoryId && /^\d+$/.test(rawCategoryId) ? Number(rawCategoryId) : undefined;
  const queryText = params.get("query")?.trim() ?? "";
  const [search, setSearch] = useState(queryText);

  const filters = useMemo<CardFilters>(
    () => ({ status, jobId, categoryId, query: queryText || undefined }),
    [status, jobId, categoryId, queryText]
  );
  const cards = useInfiniteQuery(cardsInfiniteQuery(state.token, state.storeId, filters));
  const proposals = useQuery(proposalsQuery(state.token, state.storeId));

  const setParam = (key: string, value: string | null) => {
    const next = new URLSearchParams(params.toString());
    if (value) next.set(key, value);
    else next.delete(key);
    router.replace(`/owner/cards${next.size ? `?${next}` : ""}`);
  };

  const items = cards.data?.pages.flatMap((page) => page.items) ?? [];
  // "전체"에서는 지운 카드를 빼고 보여준다 — 지운 카드는 따로 모아 본다
  const visible = status === "all" ? items.filter((card) => card.review_status !== "EXCLUDED") : items;
  const groups = new Map<string, CardListItem[]>();
  for (const card of visible) {
    const name = card.category?.name ?? "기타";
    groups.set(name, [...(groups.get(name) ?? []), card]);
  }
  const proposalCount = proposals.data?.items.length ?? 0;
  const filtered = Boolean(jobId || categoryId || queryText) || status !== "all";

  return (
    <Screen tabBar={<TabBar tabs={OWNER_TABS} />}>
      <PageHeader title="카드" />
      <form
        role="search"
        className="flex w-full items-center gap-2 rounded-full bg-surface px-4 py-3 shadow-card"
        onSubmit={(event) => {
          event.preventDefault();
          setParam("query", search.trim() || null);
        }}
      >
        <Icon name="search" size={16} className="text-ink-muted" />
        <input
          type="search"
          aria-label="카드 찾기"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder="메뉴·위치·할 일로 찾기"
          enterKeyHint="search"
          className="min-w-0 flex-1 bg-transparent text-[15px] leading-[1.45] tracking-[-0.15px] text-ink outline-none placeholder:text-ink-muted"
        />
      </form>

      <div className="-mx-1 flex gap-2 overflow-x-auto px-1 pb-1" role="tablist" aria-label="카드 상태">
        {FILTERS.map((filter) => {
          const active = filter.value === status;
          return (
            <button
              key={filter.value}
              type="button"
              role="tab"
              aria-selected={active}
              onClick={() => setParam("status", filter.value === "all" ? null : filter.value)}
              className={`min-h-9 shrink-0 rounded-full px-3.5 text-[13px] font-bold ${
                active ? "bg-primary text-white" : "bg-surface text-ink-muted shadow-card"
              } ${focusRing}`}
            >
              {filter.label}
            </button>
          );
        })}
      </div>

      {proposalCount > 0 && (
        <Link
          href="/owner/cards/proposals"
          className={`flex items-center gap-2 rounded-[20px] bg-warn-50 px-[18px] py-3.5 text-[14px] font-bold text-warn-700 ${focusRing}`}
        >
          <span className="flex-1">기존 카드와 다른 답이 있어요 · {proposalCount}</span>
          <Icon name="right" size={18} />
        </Link>
      )}
      {(jobId || categoryId) && (
        <button type="button" onClick={() => router.replace("/owner/cards")} className={`self-start ${focusRing}`}>
          <Chip tone="neutral">{jobId ? "이번에 넣은 자료의 카드만" : "한 카테고리만"} · 모두 보기</Chip>
        </button>
      )}

      {cards.isLoading && (
        <>
          <Skeleton className="h-36" />
          <Skeleton className="h-28" />
        </>
      )}
      {cards.error && (
        <ErrorInline message={apiErrorMessage(cards.error, "카드를 불러오지 못했어요.")} onRetry={() => void cards.refetch()} retrying={cards.isRefetching} />
      )}
      {cards.data && visible.length === 0 && (
        filtered ? (
          <Empty buddy={false} title="찾는 카드가 없어요" description="다른 말로 찾거나 필터를 바꿔 보세요." />
        ) : (
          <Empty title="아직 확인할 카드가 없어요" description="자료를 올리면 카드가 만들어져요." />
        )
      )}

      {[...groups.entries()].map(([name, list]) => (
        <ListGroup key={name} label={name}>
          {list.map((card) => {
            const badge = ROW_BADGE[card.review_status];
            return (
              <ListRow
                key={card.card_id}
                title={card.title}
                subtitle={summary(card.content)}
                href={`/owner/cards/${card.card_id}`}
                badge={badge ? <Chip size="sm" tone={badge.tone}>{badge.label}</Chip> : undefined}
              />
            );
          })}
        </ListGroup>
      ))}
      {cards.hasNextPage && (
        <Button variant="secondary" loading={cards.isFetchingNextPage} onClick={() => void cards.fetchNextPage()}>
          카드 더 보기
        </Button>
      )}
      <RefreshingHint active={cards.isRefetching && !cards.isFetchingNextPage} />
    </Screen>
  );
}

export default function OwnerCardsPage() {
  return (
    <Suspense>
      <CardsScreen />
    </Suspense>
  );
}
