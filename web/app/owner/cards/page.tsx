"use client";

import { useInfiniteQuery, useMutation, useQuery, useQueryClient, type InfiniteData } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useRef, useState } from "react";
import {
  Button,
  Chip,
  ConfirmDialog,
  CountBadge,
  Empty,
  ErrorInline,
  focusRing,
  Icon,
  OWNER_TABS,
  PageHeader,
  RefreshingHint,
  Screen,
  Sheet,
  Skeleton,
  TabBar,
  TextButton,
  useFeedback,
} from "@/components/kit";
import { SelectBar, useCardSelection } from "@/components/owner/card-select";
import { CardTile, tileStatus } from "@/components/owner/card-tile";
import { apiErrorMessage, bulkCards, mutateProductCard, type BulkAction, type CardFilters, type CardListItem, type CardListResponse } from "@/lib/api";
import { cardsInfiniteQuery, productCategoriesQuery, proposalsQuery, queryKeys } from "@/lib/query";
import { useCardReviewCount } from "@/lib/card-review-count";
import { cardKind } from "@/lib/card-kind";
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
  // 선택 모드 켜짐, 일괄 처리 실패 이유, 이동 시트(화면 상태)
  const [selecting, setSelecting] = useState(false);
  const [bulkError, setBulkError] = useState<string | null>(null);
  const [moving, setMoving] = useState(false);
  // 삭제는 바로 하지 않고 먼저 묻는다(2026-11-10 사용자). 묻는 동안 지울 카드
  const [askDelete, setAskDelete] = useState<{ ids: number[]; bulk: boolean } | null>(null);

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
  // 삭제한 카드를 캐시에 남은 모든 목록(다른 탭 포함)과 상세에서 바로 뺀다.
  // 안 그러면 다른 탭으로 갈 때 서버 응답 전까지 옛 목록·옛 상세('직원에게 보여요')가 그려진다(2026-11-10 사용자)
  const forgetExcluded = (ids: number[]) => {
    const gone = new Set(ids);
    client.setQueriesData<InfiniteData<CardListResponse>>({ queryKey: queryKeys.cardLists(state.storeId) }, (data) =>
      data?.pages
        ? { ...data, pages: data.pages.map((page) => ({ ...page, items: page.items.map((card) => (gone.has(card.card_id) ? { ...card, review_status: "EXCLUDED" } : card)) })) }
        : data,
    );
    for (const id of ids) client.removeQueries({ queryKey: queryKeys.card(state.storeId, id) });
  };
  const setHiddenFor = (cardId: number, on: boolean) =>
    setHidden((prev) => {
      const next = new Set(prev);
      if (on) next.add(cardId);
      else next.delete(cardId);
      return next;
    });

  const restore = useMutation({
    mutationFn: (cardId: number) => mutateProductCard(cardId, "restore", state.token!),
    onSuccess: (_, cardId) => {
      setHiddenFor(cardId, false);
      client.removeQueries({ queryKey: queryKeys.card(state.storeId, cardId) });
    },
    onError: (_error, cardId) => snackbar({ message: "되돌리지 못했어요", actionLabel: "다시", onAction: () => restore.mutate(cardId) }),
    onSettled: refresh,
  });
  const remove = useMutation({
    mutationFn: (cardId: number) => mutateProductCard(cardId, "exclude", state.token!),
    onMutate: (cardId) => setHiddenFor(cardId, true),
    onSuccess: (_, cardId) => {
      forgetExcluded([cardId]);
      snackbar({ message: "삭제했어요", actionLabel: "되돌리기", onAction: () => restore.mutate(cardId) });
    },
    onError: (_error, cardId) => {
      setHiddenFor(cardId, false);
      toast("삭제하지 못했어요");
    },
    onSettled: refresh,
  });
  // 공개를 보내는 중인 카드. 끝날 때까지 그 카드의 공개 밀기를 막는다(연타로 두 번 보내지 않게)
  const [publishing, setPublishing] = useState<Set<number>>(new Set());
  const setPublishingFor = (cardId: number, on: boolean) =>
    setPublishing((prev) => {
      const next = new Set(prev);
      if (on) next.add(cardId);
      else next.delete(cardId);
      return next;
    });
  // 같은 순간에 두 번 눌리면 화면이 다시 그려지기 전이라 위 상태로는 못 막는다. 누를 때 바로 기록한다
  const sending = useRef<Set<number>>(new Set());
  const publishOnce = (cardId: number) => {
    if (sending.current.has(cardId)) return;
    sending.current.add(cardId);
    publish.mutate(cardId);
  };
  // 미공개(공개 내리기): 직원 화면에서 바로 빠진다. 5초 안에 되돌리면 다시 공개
  const unpublish = useMutation({
    mutationFn: (cardId: number) => mutateProductCard(cardId, "unpublish", state.token!),
    onMutate: (cardId) => setHiddenFor(cardId, status === "approved"),
    onSuccess: (_, cardId) =>
      snackbar({
        message: "미공개로 바꿨어요",
        actionLabel: "되돌리기",
        onAction: () => {
          setHiddenFor(cardId, false);
          publishOnce(cardId);
        },
      }),
    onError: (error, cardId) => {
      setHiddenFor(cardId, false);
      toast(apiErrorMessage(error, "미공개로 바꾸지 못했어요"));
    },
    onSettled: refresh,
  });
  const publish = useMutation({
    mutationFn: (cardId: number) => mutateProductCard(cardId, "approve", state.token!),
    onMutate: (cardId) => setPublishingFor(cardId, true),
    onSuccess: () => toast("공개했어요"),
    onError: (error) => toast(apiErrorMessage(error, "공개하지 못했어요")),
    onSettled: async (_data, _error, cardId) => {
      await refresh();
      sending.current.delete(cardId);
      setPublishingFor(cardId, false);
    },
  });

  // 삭제된 카드에 걸린 제안은 보이지 않는다(카드가 어디에도 없다, 2026-11-08)
  const proposalItems = (proposals.data?.items ?? []).filter((p) => p.target_card_id !== null && p.target_review_status !== "EXCLUDED");
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
      // 한 카테고리만 보는 중이면 그 카테고리 제안만
      if (categoryId && proposal.category_id !== categoryId) continue;
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
  // 선택 모드(계획 7 Task 5): 화면에 보이는 순서가 끌기 범위·전체 선택의 기준
  const cardOrder = sections.flatMap(([, list]) => list.map((card) => card.card_id));
  const selection = useCardSelection(cardOrder);
  const count = selection.selected.size;
  const ACTION_WORD: Record<BulkAction, string> = { approve: "공개", unpublish: "미공개로 바꾸", exclude: "삭제", restore: "되돌리", move: "옮기" };
  const bulk = useMutation({
    mutationFn: (body: { action: BulkAction; card_ids: number[]; category_id?: number }) => bulkCards(body, state.token!),
    onMutate: () => setBulkError(null),
    onSuccess: (result, body) => {
      const failed = result.results.filter((r) => !r.ok);
      const done = result.results.filter((r) => r.ok).map((r) => r.card_id);
      if (failed.length) {
        // 실패한 카드만 고른 채로 남기고 이유를 알린다
        selection.setSelected(new Set(failed.map((r) => r.card_id)));
        setBulkError(`${failed.length}장은 ${ACTION_WORD[body.action]}하지 못했어요. ${failed[0].error?.message ?? ""}`.trim());
      } else {
        setSelecting(false);
        selection.clear();
      }
      if (!done.length) return;
      // 상태가 바뀐 카드의 상세 캐시는 버린다(다시 열면 서버에서 새로 받는다)
      for (const id of done) client.removeQueries({ queryKey: queryKeys.card(state.storeId, id) });
      if (body.action === "exclude") {
        forgetExcluded(done);
        snackbar({
          message: `${done.length}장 삭제했어요`,
          actionLabel: "되돌리기",
          onAction: () => bulk.mutate({ action: "restore", card_ids: done }),
        });
      } else if (body.action !== "restore") {
        toast(body.action === "move" ? `${done.length}장 옮겼어요` : body.action === "approve" ? `${done.length}장 공개했어요` : `${done.length}장 미공개로 바꿨어요`);
      }
    },
    onError: (error) => setBulkError(apiErrorMessage(error, "한꺼번에 처리하지 못했어요.")),
    onSettled: refresh,
  });
  const runBulk = (action: BulkAction, categoryIdForMove?: number) =>
    bulk.mutate({ action, card_ids: cardOrder.filter((id) => selection.selected.has(id)), ...(categoryIdForMove ? { category_id: categoryIdForMove } : {}) });

  return (
    <Screen
      tabBar={
        selecting ? (
          <SelectBar
            count={count}
            busy={bulk.isPending}
            onMove={() => setMoving(true)}
            onPublish={() => runBulk("approve")}
            onUnpublish={() => runBulk("unpublish")}
            onDelete={() => setAskDelete({ ids: cardOrder.filter((id) => selection.selected.has(id)), bulk: true })}
          />
        ) : (
          <TabBar tabs={OWNER_TABS} />
        )
      }
      onRefresh={() => Promise.all([cards.refetch(), review.refetch()])}
    >
      <PageHeader
        title={selecting ? (count ? `${count}장 선택` : "카드 선택") : "카드"}
        action={
          selecting ? (
            <div className="flex items-center gap-3">
              <TextButton onClick={selection.toggleAll}>{selection.allSelected ? "전체 해제" : "전체 선택"}</TextButton>
              <TextButton
                className="font-bold text-primary!"
                onClick={() => {
                  setSelecting(false);
                  selection.clear();
                  setBulkError(null);
                }}
              >
                완료
              </TextButton>
            </div>
          ) : (
            <TextButton disabled={!cards.data || visible.length === 0} onClick={() => setSelecting(true)}>
              선택
            </TextButton>
          )
        }
      />
      {bulkError && (
        <p role="alert" className="rounded-[14px] bg-danger-50 px-4 py-3 text-[14px] font-semibold text-danger-700 [word-break:keep-all]">
          {bulkError}
        </p>
      )}
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

      <div className="-mx-1 flex shrink-0 gap-2 overflow-x-auto px-1 pb-1" role="group" aria-label="카드 상태">
        {FILTERS.map((filter) => {
          const active = filter.value === status;
          return (
            <button
              key={filter.value}
              type="button"
              aria-pressed={active}
              aria-label={filter.value === "needs_review" && reviewCount > 0 ? `${filter.label} ${reviewCount}` : undefined}
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
            <div
              className={`grid gap-3 ${cardKind(list[0]?.category ?? { name }) === "RECIPE" ? "grid-cols-2" : "grid-cols-1"}`}
              {...(selecting ? selection.containerProps : {})}
            >
              {list.map((card) => {
                const proposal = proposalCards.has(card.card_id);
                const tile = tileStatus(card, proposal);
                const canPublish = tile === "pending" && (status === "all" || status === "pending") && !publishing.has(card.card_id);
                if (selecting) {
                  return (
                    <CardTile
                      key={card.card_id}
                      card={card}
                      status={tile}
                      select={{ selected: selection.selected.has(card.card_id), onToggle: () => selection.toggle(card.card_id) }}
                    />
                  );
                }
                return (
                  <CardTile
                    key={card.card_id}
                    card={card}
                    status={tile}
                    proposal={proposal}
                    right={canPublish ? { label: "공개", ariaLabel: `${card.title} 공개`, tone: "primary", onAction: () => publishOnce(card.card_id) } : undefined}
                    left={
                      tile === "pending" && status === "pending"
                        ? { label: "삭제", ariaLabel: `${card.title} 삭제`, tone: "danger", onAction: () => setAskDelete({ ids: [card.card_id], bulk: false }) }
                        : tile === "approved" && card.review_status === "APPROVED" && (status === "all" || status === "approved") && !unpublish.isPending
                          ? { label: "미공개", ariaLabel: `${card.title} 미공개`, tone: "neutral", onAction: () => unpublish.mutate(card.card_id) }
                          : undefined
                    }
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
      <ConfirmDialog
        open={askDelete !== null}
        title={`카드 ${askDelete?.ids.length ?? 0}장을 삭제할까요?`}
        description="직원에게도 더 이상 보이지 않아요."
        confirmLabel="삭제하기"
        cancelLabel="그대로 두기"
        tone="danger"
        onConfirm={() => {
          if (!askDelete) return;
          if (askDelete.bulk) runBulk("exclude");
          else remove.mutate(askDelete.ids[0]);
          setAskDelete(null);
        }}
        onCancel={() => setAskDelete(null)}
      />
      <Sheet open={moving} onClose={() => setMoving(false)} title="어디로 옮길까요?">
        <div className="flex max-h-[50dvh] flex-col gap-1 overflow-y-auto">
          {categories.data?.items.map((category) => (
            <Button
              key={category.category_id}
              variant="secondary"
              disabled={bulk.isPending}
              onClick={() => {
                setMoving(false);
                runBulk("move", category.category_id);
              }}
            >
              {category.name}
            </Button>
          ))}
        </div>
      </Sheet>
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
