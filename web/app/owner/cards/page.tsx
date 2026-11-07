"use client";

import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";
import {
  Button,
  Chip,
  CountBadge,
  Empty,
  ErrorInline,
  focusRing,
  Icon,
  OWNER_TABS,
  PageHeader,
  RefreshingHint,
  Screen,
  Skeleton,
  TabBar,
  useFeedback,
} from "@/components/kit";
import { CardTile, tileStatus } from "@/components/owner/card-tile";
import { apiErrorMessage, mutateProductCard, type CardFilters, type CardListItem } from "@/lib/api";
import { cardsInfiniteQuery, productCategoriesQuery, proposalsQuery, queryKeys } from "@/lib/query";
import { useCardReviewCount } from "@/lib/card-review-count";
import { useApp } from "@/lib/store";

// 카드 상태(2026-11-06 사용자): 공개 = 살아 있는 카드, 검수 필요 = 뭔가 이상한 카드(제안 걸린 카드 포함),
// 미공개 = 공개하지 않는 카드, 삭제 = 어디에서도 보이지 않는 카드(삭제 직후 5초 되돌리기만)
const FILTERS: { value: "all" | "approved" | "needs_review" | "pending"; label: string }[] = [
  { value: "all", label: "전체" },
  { value: "approved", label: "공개" },
  { value: "needs_review", label: "검수 필요" },
  { value: "pending", label: "미공개" },
];
type FilterValue = (typeof FILTERS)[number]["value"];

const SEARCH_DELAY_MS = 250;

// 레시피 카테고리는 두 칸, 공지·위치·순서 같은 나머지는 한 칸씩(2026-11-07 사용자 스케치).
// 카테고리에 종류 정보가 없어 이름으로 가른다(서버 카테고리 종류가 생기면 그걸로 바꾼다: 백로그)
const RECIPE_NAME = /레시피|음료|메뉴|제조|제작/;
function isRecipeCategory(name: string) {
  return RECIPE_NAME.test(name);
}

// O9 카드: 카테고리 섹션 + 2열 카드 + 검색 + 상태 필터. 알림 딥링크의 status/job_id/category_id/query 를 그대로 받는다.
function CardsScreen() {
  const router = useRouter();
  const params = useSearchParams();
  const { state } = useApp();
  const client = useQueryClient();
  const { toast, snackbar } = useFeedback();

  const rawStatus = params.get("status");
  const status: FilterValue = FILTERS.some((f) => f.value === rawStatus) ? (rawStatus as FilterValue) : "all";
  const rawJobId = params.get("job_id");
  const jobId = rawJobId && /^\d+$/.test(rawJobId) ? Number(rawJobId) : undefined;
  const rawCategoryId = params.get("category_id");
  const categoryId = rawCategoryId && /^\d+$/.test(rawCategoryId) ? Number(rawCategoryId) : undefined;
  const queryText = params.get("query")?.trim() ?? "";
  const [search, setSearch] = useState(queryText);
  // 주소가 밖에서 바뀌면(탭, 알림 링크, 모두 보기) 입력창도 주소를 따른다. 안 그러면 옛 검색어가 새 주소에 다시 붙는다
  const [seenQuery, setSeenQuery] = useState(queryText);
  if (seenQuery !== queryText) {
    setSeenQuery(queryText);
    setSearch(queryText);
  }
  // 누르는 즉시 숨긴 카드(삭제·공개 중). 실패하면 되살린다
  const [hidden, setHidden] = useState<Set<number>>(new Set());

  const filters = useMemo<CardFilters>(
    () => ({ status, jobId, categoryId, query: queryText || undefined }),
    [status, jobId, categoryId, queryText],
  );
  const cards = useInfiniteQuery(cardsInfiniteQuery(state.token, state.storeId, filters));
  const proposals = useQuery(proposalsQuery(state.token, state.storeId));
  const review = useCardReviewCount();
  const categories = useQuery(productCategoriesQuery(state.token, state.storeId));

  const setParam = (key: string, value: string | null) => {
    const next = new URLSearchParams(params.toString());
    if (value) next.set(key, value);
    else next.delete(key);
    router.replace(`/owner/cards${next.size ? `?${next}` : ""}`);
  };

  // 칠 때마다 걸러진다(Enter 없이). 주소의 query 가 정본이고 조회 키에 들어가 늦게 온 옛 결과는 쓰이지 않는다
  useEffect(() => {
    const next = search.trim();
    if (next === queryText) return;
    const timer = setTimeout(() => {
      const url = new URLSearchParams(params.toString());
      if (next) url.set("query", next);
      else url.delete("query");
      router.replace(`/owner/cards${url.size ? `?${url}` : ""}`);
    }, SEARCH_DELAY_MS);
    return () => clearTimeout(timer);
  }, [search, queryText, params, router]);

  const refresh = () =>
    Promise.all([
      client.invalidateQueries({ queryKey: queryKeys.cardLists(state.storeId) }),
      client.invalidateQueries({ queryKey: queryKeys.roadmapRoot(state.storeId) }),
    ]);
  const setHiddenFor = (cardId: number, on: boolean) =>
    setHidden((prev) => {
      const next = new Set(prev);
      if (on) next.add(cardId);
      else next.delete(cardId);
      return next;
    });

  const restore = useMutation({
    mutationFn: (cardId: number) => mutateProductCard(cardId, "restore", state.token!),
    onSuccess: (_, cardId) => setHiddenFor(cardId, false),
    onError: (_error, cardId) => snackbar({ message: "되돌리지 못했어요", actionLabel: "다시", onAction: () => restore.mutate(cardId) }),
    onSettled: refresh,
  });
  const remove = useMutation({
    mutationFn: (cardId: number) => mutateProductCard(cardId, "exclude", state.token!),
    onMutate: (cardId) => setHiddenFor(cardId, true),
    onSuccess: (_, cardId) => snackbar({ message: "삭제했어요", actionLabel: "되돌리기", onAction: () => restore.mutate(cardId) }),
    onError: (_error, cardId) => {
      setHiddenFor(cardId, false);
      toast("삭제하지 못했어요");
    },
    onSettled: refresh,
  });
  const publish = useMutation({
    mutationFn: (cardId: number) => mutateProductCard(cardId, "approve", state.token!),
    onSuccess: () => toast("공개했어요"),
    onError: (error) => toast(apiErrorMessage(error, "공개하지 못했어요")),
    onSettled: refresh,
  });

  const proposalItems = (proposals.data?.items ?? []).filter((p) => p.target_card_id !== null);
  const proposalCards = new Set(proposalItems.map((p) => p.target_card_id!));
  const items = cards.data?.pages.flatMap((page) => page.items) ?? [];
  // 삭제한 카드는 어떤 탭에서도 보이지 않는다
  let visible = items.filter((card) => card.review_status !== "EXCLUDED" && !hidden.has(card.card_id));
  if (status === "approved") visible = visible.filter((card) => !proposalCards.has(card.card_id));
  // 검수 필요 탭에는 제안이 걸린 카드도 넣는다(o05b). 목록 조회에 없으면 제안의 제목·카테고리로 만든다
  if (status === "needs_review" && !queryText && !jobId) {
    const shown = new Set(visible.map((card) => card.card_id));
    for (const proposal of proposalItems) {
      if (shown.has(proposal.target_card_id!)) continue;
      shown.add(proposal.target_card_id!);
      const category = categories.data?.items.find((c) => c.category_id === proposal.category_id);
      visible.push({
        card_id: proposal.target_card_id!,
        review_status: "APPROVED",
        title: proposal.current_title ?? "카드",
        content: proposal.current_content ?? "",
        category: category ? { category_id: category.category_id, name: category.name } : null,
        assignment_type: "AUTOMATIC",
        source: null,
        job_id: null,
        has_evidence: false,
        needs_review_reason: null,
        updated_at: proposal.created_at,
      });
    }
  }

  const order = new Map((categories.data?.items ?? []).map((c) => [c.name, c.sort_order]));
  const groups = new Map<string, CardListItem[]>();
  for (const card of visible) {
    const name = card.category?.name ?? "기타";
    groups.set(name, [...(groups.get(name) ?? []), card]);
  }
  const sections = [...groups.entries()].sort(([a], [b]) => (order.get(a) ?? 999) - (order.get(b) ?? 999));
  const reviewCount = review.count;
  const filtered = Boolean(jobId || categoryId || queryText) || status !== "all";

  return (
    <Screen tabBar={<TabBar tabs={OWNER_TABS} />} onRefresh={() => Promise.all([cards.refetch(), review.refetch()])}>
      <PageHeader title="카드" />
      <form role="search" className="flex w-full items-center gap-2 rounded-full bg-surface px-4 py-3 shadow-card" onSubmit={(event) => event.preventDefault()}>
        <Icon name="search" size={16} className="text-ink-muted" />
        <input
          type="search"
          aria-label="카드 찾기"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder="메뉴, 위치, 할 일로 찾기"
          enterKeyHint="search"
          className="min-w-0 flex-1 bg-transparent text-[15px] leading-[1.45] tracking-[-0.15px] text-ink outline-none placeholder:text-ink-muted"
        />
      </form>

      <div className="-mx-1 flex shrink-0 gap-2 overflow-x-auto px-1 pb-1" role="tablist" aria-label="카드 상태">
        {FILTERS.map((filter) => {
          const active = filter.value === status;
          return (
            <button
              key={filter.value}
              type="button"
              role="tab"
              aria-selected={active}
              onClick={() => setParam("status", filter.value === "all" ? null : filter.value)}
              className={`flex min-h-9 shrink-0 items-center rounded-full px-3.5 text-[13px] font-bold ${
                active ? "bg-primary text-white" : "bg-surface text-ink-muted shadow-card"
              } ${focusRing}`}
            >
              {filter.label}
              {filter.value === "needs_review" && reviewCount > 0 && <CountBadge n={reviewCount} tone="danger" />}
            </button>
          );
        })}
      </div>

      {(jobId || categoryId) && (
        <button type="button" onClick={() => router.replace("/owner/cards")} className={`self-start ${focusRing}`}>
          <Chip tone="neutral">{jobId ? "이번에 넣은 자료의 카드만" : "한 카테고리만"}, 모두 보기</Chip>
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
      {cards.data && visible.length === 0 &&
        (filtered ? (
          <Empty buddy={false} title="찾는 카드가 없어요" description="다른 말로 찾거나 필터를 바꿔 보세요." />
        ) : (
          <Empty title="아직 카드가 없어요" description="자료를 올리면 카드가 만들어져요." />
        ))}

      {sections.map(([name, list], index) => {
        // aria-labelledby 는 공백으로 id 를 나누므로 이름 대신 순번으로 id 를 만든다
        const id = `cards-section-${index}`;
        return (
          <section key={name} aria-labelledby={id} className="flex flex-col gap-3">
            <h2 id={id} className="border-b-2 border-ink pb-1.5 text-[17px] font-bold leading-[1.4] tracking-[-0.34px] text-ink">
              {name}
            </h2>
            <div className={`grid gap-3 ${isRecipeCategory(name) ? "grid-cols-2" : "grid-cols-1"}`}>
              {list.map((card) => {
                const proposal = proposalCards.has(card.card_id);
                const tile = tileStatus(card, proposal);
                const canPublish = tile === "pending" && (status === "all" || status === "pending");
                return (
                  <CardTile
                    key={card.card_id}
                    card={card}
                    status={tile}
                    proposal={proposal}
                    right={canPublish ? { label: "공개", tone: "primary", onAction: () => publish.mutate(card.card_id) } : undefined}
                    left={tile === "pending" && status === "pending" ? { label: "삭제", tone: "danger", onAction: () => remove.mutate(card.card_id) } : undefined}
                  />
                );
              })}
            </div>
          </section>
        );
      })}
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
